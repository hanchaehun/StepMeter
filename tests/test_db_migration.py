"""apps/api 마이그레이션 검사: 개발계획서 10장 테이블 16개 생성, 초대 코드별 project 분리, 되돌리기.

DB를 비웠다가 다시 만들므로 개발용 DB가 아닌 테스트 전용 DB를 TEST_DATABASE_URL로 준다.
    docker run -d --name stepmeter-pg -e POSTGRES_USER=stepmeter -e POSTGRES_PASSWORD=stepmeter \
      -e POSTGRES_DB=stepmeter -p 5433:5432 postgres:16
    TEST_DATABASE_URL=postgresql+psycopg://stepmeter:stepmeter@localhost:5433/stepmeter
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

URL = os.environ.get("TEST_DATABASE_URL")
INI = Path(__file__).resolve().parents[1] / "apps" / "api" / "alembic.ini"

# 개발계획서 10장 데이터 모델
TABLES = {
    "project", "task", "run", "attempt", "step", "element_snapshot", "metric", "issue",
    "comparison", "llm_call", "human_session", "human_event", "element_alias", "issue_label",
    "model_version", "access_code",
}


@unittest.skipUnless(URL, "TEST_DATABASE_URL 없음")
class MigrationTests(unittest.TestCase):
    def setUp(self):
        from alembic.config import Config
        from sqlalchemy import create_engine

        os.environ["DATABASE_URL"] = URL
        self.cfg = Config(str(INI))
        self.engine = create_engine(URL)

    def tearDown(self):
        self.engine.dispose()

    def tables(self) -> set[str]:
        from sqlalchemy import inspect

        return set(inspect(self.engine).get_table_names()) - {"alembic_version"}

    def test_upgrade_creates_tables_and_downgrade_removes_them(self):
        from alembic import command
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError

        command.downgrade(self.cfg, "base")
        command.upgrade(self.cfg, "head")
        self.assertEqual(self.tables(), TABLES)

        # project는 반드시 초대 코드 하나에 속한다 (F17, 코드 1개 → project 여러 개)
        with self.assertRaises(IntegrityError), self.engine.begin() as conn:
            conn.execute(text("INSERT INTO project (name, base_url) VALUES ('a', 'https://a.example')"))
        with self.engine.begin() as conn:
            code = conn.execute(text("INSERT INTO access_code (code_hash) VALUES ('h') RETURNING id")).scalar()
            for name in ("a", "b"):
                conn.execute(
                    text("INSERT INTO project (name, base_url, owner_id) VALUES (:n, 'https://a.example', :o)"),
                    {"n": name, "o": code},
                )

        command.downgrade(self.cfg, "base")
        self.assertEqual(self.tables(), set())
        command.upgrade(self.cfg, "head")


if __name__ == "__main__":
    unittest.main()
