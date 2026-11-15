# 진행 프로그램을 소스 방식으로 실행 (Windows 개발자용, exe 빌드 전 확인).
# 진행 화면·메모·저장 형식은 exe와 같다. 사이트는 benchmark/apps/variants/ 빌드, 수집 번들은 worker/collect/dist/collect.js.
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $root

function Fail($msg) { Write-Host "`n[멈춤] $msg" -ForegroundColor Red; exit 1 }

if (-not (Test-Path .venv)) {
    Write-Host "가상환경을 만듭니다 (.venv)"
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail "Python 3.12가 필요합니다. python.org에서 3.12를 설치한 뒤 다시 실행하세요." }
}
$PY = if (Test-Path .venv\Scripts\python.exe) { "$root\.venv\Scripts\python.exe" } else { "$root\.venv\python.exe" }
$ver = & $PY -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ($ver -ne "3.12") { Fail ".venv가 Python $ver 입니다. .venv를 지우고 Python 3.12로 다시 실행하세요." }

$stamp = ".venv\.stepmeter-requirements.sha256"
$want = (Get-FileHash requirements-dev.txt -Algorithm SHA256).Hash
$have = if (Test-Path $stamp) { Get-Content $stamp } else { "" }
if ($want -ne $have) {
    & $PY -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { Fail "pip install 실패. 인터넷 연결을 확인하고 다시 실행하세요." }
    Set-Content -Path $stamp -Value $want -Encoding ascii
}
& $PY -c "import tkinter" 2>$null
if ($LASTEXITCODE -ne 0) { Fail "tkinter가 없습니다. python.org 설치판 Python 3.12(tcl/tk 포함)를 쓰세요." }

$env:PLAYWRIGHT_BROWSERS_PATH = "$root\.venv\ms-playwright"
& $PY -m playwright install chromium
if ($LASTEXITCODE -ne 0) { Fail "Chromium 설치 실패. 인터넷 연결을 확인하고 다시 실행하세요." }

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Fail "Node 22(npm)가 필요합니다. nodejs.org에서 설치하세요." }
if (-not (Test-Path node_modules)) {
    npm ci
    if ($LASTEXITCODE -ne 0) { Fail "npm ci 실패. 인터넷 연결을 확인하고 다시 실행하세요." }
}
npm run build:collect
if ($LASTEXITCODE -ne 0) { Fail "npm run build:collect 실패. npm ci를 다시 해 보세요." }

& $PY -m benchmark.serve_variants build
if ($LASTEXITCODE -ne 0) { Fail "사이트 빌드 실패. 위 출력과 benchmark/apps/variants/*.build.log를 세션 운영 담당에게 보내세요." }
& $PY -m benchmark.serve_variants check
if ($LASTEXITCODE -ne 0) { Fail "serve_variants check 실패. 세션을 열지 말고 세션 운영 담당에게 출력 전체를 보내세요." }

& $PY human-study\app @args
exit $LASTEXITCODE
