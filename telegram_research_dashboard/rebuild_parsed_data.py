"""저장된 Telegram 원문에 최신 파싱 규칙을 다시 적용한다."""

import argparse
from datetime import datetime
from types import SimpleNamespace

from db import connect, initialize
from parser import PARSER_VERSION
from telegram_importer import store_message


def rebuild(only_if_parser_changed: bool = False) -> None:
    initialize()
    with connect() as conn:
        stored_version = conn.execute("PRAGMA user_version").fetchone()[0]
        if only_if_parser_changed and stored_version == PARSER_VERSION:
            print(f"파서 v{PARSER_VERSION} 그대로 — 전체 재분류 생략")
            return
        messages = conn.execute(
            "SELECT channel_id,message_id,posted_at,edited_at,text,reply_to_message_id FROM telegram_messages ORDER BY id"
        ).fetchall()
        for index, row in enumerate(messages, 1):
            message = SimpleNamespace(
                id=row["message_id"],
                message=row["text"],
                date=datetime.fromisoformat(row["posted_at"]),
                edit_date=datetime.fromisoformat(row["edited_at"]) if row["edited_at"] else None,
                media=None,
                reply_to_msg_id=row["reply_to_message_id"],
            )
            store_message(conn, row["channel_id"], message)
            if index % 500 == 0:
                conn.commit()
                print(f"{index:,}/{len(messages):,} 재분류")
        conn.commit()
        conn.execute("DELETE FROM companies WHERE id NOT IN (SELECT company_id FROM report_companies UNION SELECT company_id FROM news_companies)")
        conn.execute(f"PRAGMA user_version={int(PARSER_VERSION)}")
        conn.commit()
    print(f"재분류 완료: {len(messages):,}개 원문 (파서 v{PARSER_VERSION})")


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("--if-parser-changed", action="store_true",
                     help="DB에 기록된 파서 버전과 같으면 아무것도 하지 않는다 (CI용)")
    args = cli.parse_args()
    rebuild(only_if_parser_changed=args.if_parser_changed)
