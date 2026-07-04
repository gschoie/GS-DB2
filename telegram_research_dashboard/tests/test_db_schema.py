"""schema.sql이 db.py/build_static.py 등 소비자가 실제로 참조하는 컬럼을 계속 제공하는지 확인한다."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import db

REQUIRED_COLUMNS = {
    "telegram_messages": {
        "id", "channel_id", "message_id", "posted_at", "edited_at",
        "text", "source_url", "media_type", "imported_at",
    },
    "reports": {
        "id", "message_id", "title", "report_type", "weekly_folder", "company_name",
        "securities_firm", "analyst", "opinion", "target_price", "previous_target_price",
        "target_change", "original_url", "confidence", "needs_review",
    },
    "news_articles": {
        "id", "message_id", "source_index", "title", "company_name", "industry",
        "publisher", "article_url", "event_type", "sentiment", "importance",
        "summary", "confidence", "needs_review",
    },
    "companies": {"id", "name", "ticker", "industry"},
    "report_companies": {"report_id", "company_id"},
    "news_companies": {"news_id", "company_id"},
    "article_metadata_attempts": {"news_id", "attempted_at", "success"},
}


class SchemaContractTest(unittest.TestCase):
    def setUp(self):
        # sqlite3 커넥션은 `with connect() as conn`으로 커밋만 되고 닫히지 않아
        # Windows에서 임시 디렉토리 삭제 시 파일 잠금이 걸릴 수 있어 ignore_cleanup_errors를 쓴다.
        self.tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmpdir.cleanup)
        self._old_db_path = os.environ.get("DATABASE_PATH")
        os.environ["DATABASE_PATH"] = str(Path(self.tmpdir.name) / "schema_test.db")
        self.addCleanup(self._restore_env)
        db.initialize()

    def _restore_env(self):
        if self._old_db_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = self._old_db_path

    def test_required_columns_exist(self):
        with db.connect() as conn:
            for table, required in REQUIRED_COLUMNS.items():
                actual = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                missing = required - actual
                self.assertFalse(missing, f"{table} is missing columns used by consumers: {missing}")


if __name__ == "__main__":
    unittest.main()
