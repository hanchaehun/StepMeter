# 진행 프로그램 exe 빌드 (Windows). 저장소 어디서 실행해도 루트로 옮겨 build_exe.py를 부른다.
# 사전 준비: infra/README.md "W1 실행 환경" (.venv, npm ci, playwright install chromium), serve_variants build
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $root
$PY = if (Test-Path .venv\Scripts\python.exe) { "$root\.venv\Scripts\python.exe" } elseif (Test-Path .venv\python.exe) { "$root\.venv\python.exe" } else { $null }
if (-not $PY) { Write-Host ".venv가 없습니다. infra/README.md 'W1 실행 환경'대로 만드세요."; exit 1 }
if (-not $env:PLAYWRIGHT_BROWSERS_PATH) { $env:PLAYWRIGHT_BROWSERS_PATH = "$root\.venv\ms-playwright" }
& $PY human-study\app\build_exe.py @args
exit $LASTEXITCODE
