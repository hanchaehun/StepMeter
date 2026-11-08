"""초대 코드 발급 (F17). 레포 루트에서: python -m apps.api.issue_code "라벨"

원문 코드는 여기서 한 번만 출력한다. DB에는 sha256 지문만 저장한다.
"""

from __future__ import annotations

import secrets
import sys

from apps.api.db.models import AccessCode
from apps.api.main import SessionLocal, hash_code


def main() -> None:
    label = sys.argv[1] if len(sys.argv) > 1 else None
    code = secrets.token_urlsafe(16)
    with SessionLocal.begin() as db:
        db.add(AccessCode(code_hash=hash_code(code), label=label))
    print(code)


if __name__ == "__main__":
    main()
