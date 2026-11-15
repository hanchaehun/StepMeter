"""진입점. 소스 방식: `python human-study/app` / exe: PyInstaller가 이 파일을 시작점으로 묶는다."""
from __future__ import annotations

import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    from app.gui import main  # exe: PyInstaller가 app 패키지를 함께 묶었다
elif __package__ in (None, ""):
    # `python human-study/app`처럼 폴더를 직접 실행하면 패키지 이름이 없다. human-study를 경로에 넣고 app으로 부른다
    here = Path(__file__).resolve().parent
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != here]
    sys.path.insert(0, str(here.parent))
    from app.gui import main
else:
    from .gui import main

if __name__ == "__main__":
    raise SystemExit(main())
