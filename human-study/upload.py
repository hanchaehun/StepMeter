"""저장된 세션 JSON을 POST /human-sessions로 올린다 (API에 엔드포인트가 생긴 뒤 사용).

  STEPMETER_ACCESS_CODE=<초대 코드> python human-study/upload.py data/human/*.json --api http://127.0.0.1:8000

올린 파일 옆에 `<이름>.json.uploaded`(응답 id)를 남기고, 표시가 있는 파일은 건너뛴다.
표준 라이브러리만 쓴다. 초대 코드는 인자로만 받고 저장하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from schema import validate_session  # noqa: E402


def upload_files(paths: list[Path], *, api: str, access_code: str) -> list[tuple[Path, int]]:
    """올린 (파일, 서버 id) 목록. 이미 올린 파일은 건너뛴다. 스키마에 안 맞는 파일은 ValueError."""
    done: list[tuple[Path, int]] = []
    for path in paths:
        marker = path.with_name(path.name + ".uploaded")
        if marker.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        errors = validate_session(data)
        if errors:
            raise ValueError(f"{path.name}: 스키마에 맞지 않음\n" + "\n".join(errors))
        req = urllib.request.Request(
            api.rstrip("/") + "/human-sessions",
            data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Access-Code": access_code},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                body = json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{path.name}: HTTP {e.code} {e.read().decode('utf-8', 'replace')[:200]}") from e
        marker.write_text(str(body["id"]), encoding="utf-8")
        done.append((path, int(body["id"])))
    return done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="사람 데이터 세션 업로드")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--api", required=True, help="API 서버 주소 (예: http://127.0.0.1:8000)")
    parser.add_argument("--code", help="X-Access-Code 초대 코드. 생략하면 환경 변수 STEPMETER_ACCESS_CODE (셸 기록에 남지 않게)")
    args = parser.parse_args(argv)
    code = args.code or os.environ.get("STEPMETER_ACCESS_CODE")
    if not code:
        parser.error("--code 또는 STEPMETER_ACCESS_CODE가 필요합니다")
    for path, sid in upload_files(args.files, api=args.api, access_code=code):
        print(f"올림: {path.name} → id {sid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
