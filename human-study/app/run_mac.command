#!/bin/bash
# StepMeter 사람 실험 진행 프로그램 — Mac (Finder에서 더블클릭)
# 처음 한 번은 설치·사이트 빌드로 10~15분 걸린다. 진행 화면·메모·저장 형식은 Windows exe와 같다.
cd "$(dirname "$0")/../.." || exit 1
ROOT="$(pwd)"

fail() {
  echo
  echo "[멈춤] $1"
  echo "아무 키나 누르면 창을 닫습니다."
  read -r -n 1
  exit 1
}

echo "== StepMeter 진행 프로그램 준비 ($ROOT)"

# 1) Python 3.12
PY312="$(command -v python3.12 || true)"
if [ -z "$PY312" ]; then
  fail "Python 3.12가 없습니다. python.org에서 macOS용 Python 3.12를 설치한 뒤 다시 더블클릭하세요."
fi

# 2) 가상환경과 패키지
if [ ! -d .venv ]; then
  echo "== 가상환경을 만듭니다 (.venv)"
  "$PY312" -m venv .venv || fail "가상환경을 만들지 못했습니다. .venv 폴더를 지우고 다시 더블클릭하세요."
fi
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || fail ".venv가 깨졌습니다. .venv 폴더를 지우고 다시 더블클릭하세요."
"$PY" -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)' \
  || fail ".venv가 Python 3.12가 아닙니다. .venv 폴더를 지우고 다시 더블클릭하세요."
STAMP=".venv/.stepmeter-requirements.sha256"
WANT="$(shasum -a 256 requirements-dev.txt | cut -d' ' -f1)"
if [ "$(cat "$STAMP" 2>/dev/null)" != "$WANT" ]; then
  echo "== 패키지 설치 (requirements-dev.txt)"
  "$PY" -m pip install -r requirements-dev.txt || fail "pip install 실패. 인터넷 연결을 확인하고 다시 더블클릭하세요."
  echo "$WANT" > "$STAMP"
fi
"$PY" -c 'import tkinter' 2>/dev/null \
  || fail "tkinter가 없습니다. python.org 설치판 Python 3.12를 쓰거나 brew install python-tk@3.12 후 .venv를 지우고 다시 더블클릭하세요."
export PLAYWRIGHT_BROWSERS_PATH="$ROOT/.venv/ms-playwright"
echo "== Chromium 확인"
"$PY" -m playwright install chromium || fail "Chromium 설치 실패. 인터넷 연결을 확인하고 다시 더블클릭하세요."

# 3) 수집 번들
command -v npm >/dev/null 2>&1 || fail "Node 22(npm)가 없습니다. nodejs.org에서 설치한 뒤 다시 더블클릭하세요."
if [ ! -d node_modules ]; then
  echo "== npm ci"
  npm ci || fail "npm ci 실패. 인터넷 연결을 확인하고 다시 더블클릭하세요."
fi
echo "== 수집 번들 (npm run build:collect)"
npm run build:collect || fail "npm run build:collect 실패. node_modules 폴더를 지우고 다시 더블클릭하세요."

# 4) 사이트 빌드·확인
command -v git >/dev/null 2>&1 || fail "git이 없습니다. 터미널에서 xcode-select --install 후 다시 더블클릭하세요."
echo "== 사이트 빌드 (이미 최신이면 건너뜀)"
"$PY" -m benchmark.serve_variants build || fail "사이트 빌드 실패. 위 출력과 benchmark/apps/variants/*.build.log를 세션 운영 담당에게 보내세요."
echo "== 결함판·기준선 확인 (serve_variants check)"
"$PY" -m benchmark.serve_variants check || fail "check 실패. 세션을 열지 말고 세션 운영 담당에게 위 출력 전체를 보내세요."

# 5) 진행 프로그램
echo "== 진행 프로그램을 엽니다"
"$PY" human-study/app || fail "진행 프로그램이 오류로 끝났습니다. 위 출력을 세션 운영 담당에게 보내세요."
