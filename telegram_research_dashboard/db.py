from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def database_path() -> Path:
    return ROOT / os.getenv("DATABASE_PATH", "data/dashboard.db")


def connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize() -> None:
    with connect() as conn:
        conn.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
        columns = {row[1] for row in conn.execute("PRAGMA table_info(reports)")}
        if "weekly_folder" not in columns:
            conn.execute("ALTER TABLE reports ADD COLUMN weekly_folder TEXT")
        news_columns = {row[1] for row in conn.execute("PRAGMA table_info(news_articles)")}
        if "comment" not in news_columns:
            conn.execute("ALTER TABLE news_articles ADD COLUMN comment TEXT")
        _allow_multiple_reports_per_message(conn)


REPORT_COLUMNS = ("id,message_id,title,report_type,weekly_folder,company_name,securities_firm,"
                  "analyst,opinion,target_price,previous_target_price,target_change,"
                  "original_url,confidence,needs_review")


def _allow_multiple_reports_per_message(conn: sqlite3.Connection) -> None:
    """기존 DB의 reports.message_id UNIQUE 제약을 푸는 일회성 마이그레이션.

    묶음 보고서(산업 + 기업 리뷰 N개)를 메시지 하나에 여러 행으로 저장하기 위함.
    SQLite는 제약만 떼어낼 수 없어 테이블을 재생성한다.
    """
    table_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='reports'"
    ).fetchone()[0]
    if "UNIQUE" not in table_sql.upper():
        return
    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("""CREATE TABLE reports_migrated (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      message_id INTEGER NOT NULL REFERENCES telegram_messages(id) ON DELETE CASCADE,
      title TEXT NOT NULL,
      report_type TEXT NOT NULL DEFAULT '기업분석',
      weekly_folder TEXT,
      company_name TEXT,
      securities_firm TEXT,
      analyst TEXT,
      opinion TEXT,
      target_price INTEGER,
      previous_target_price INTEGER,
      target_change TEXT,
      original_url TEXT,
      confidence REAL NOT NULL DEFAULT 0.5,
      needs_review INTEGER NOT NULL DEFAULT 1
    )""")
    conn.execute(f"INSERT INTO reports_migrated({REPORT_COLUMNS}) SELECT {REPORT_COLUMNS} FROM reports")
    conn.execute("DROP TABLE reports")
    conn.execute("ALTER TABLE reports_migrated RENAME TO reports")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_company ON reports(company_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_message ON reports(message_id)")
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")
