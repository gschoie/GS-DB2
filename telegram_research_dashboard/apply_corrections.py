"""수동 교정과 기업명 표준화를 DB에 적용한다. 여러 번 실행해도 안전(idempotent)하다.

1) KAI → 한국항공우주 통합 (companies 테이블 병합 + 뉴스/보고서 재연결)
2) 별칭 기사 재추출 (삼성重·KF-21·보라매 등 파서 별칭을 표준 기업명으로)
3) manual_overrides.TITLE_COMPANY_OVERRIDES 반영 (의미상 교정)
"""

from __future__ import annotations

from db import connect, initialize
from parser import extract_companies
from telegram_importer import link_companies
from manual_overrides import TITLE_COMPANY_OVERRIDES


def merge_kai(conn) -> int:
    """KAI 기업 레코드를 한국항공우주로 병합한다."""
    conn.execute("INSERT INTO companies(name) VALUES('한국항공우주') ON CONFLICT(name) DO NOTHING")
    canonical = conn.execute("SELECT id FROM companies WHERE name='한국항공우주'").fetchone()["id"]
    old = conn.execute("SELECT id FROM companies WHERE name='KAI'").fetchone()
    moved = 0
    if old:
        for table, column in (("news_companies", "news_id"), ("report_companies", "report_id")):
            conn.execute(
                f"INSERT OR IGNORE INTO {table}({column},company_id) "
                f"SELECT {column},? FROM {table} WHERE company_id=?",
                (canonical, old["id"]),
            )
            conn.execute(f"DELETE FROM {table} WHERE company_id=?", (old["id"],))
        conn.execute("DELETE FROM companies WHERE id=?", (old["id"],))
        moved = 1
    conn.execute(
        "UPDATE news_articles SET company_name=replace(company_name,'KAI','한국항공우주') "
        "WHERE company_name LIKE '%KAI%'"
    )
    conn.execute(
        "UPDATE reports SET company_name=replace(company_name,'KAI','한국항공우주') "
        "WHERE company_name LIKE '%KAI%'"
    )
    return moved


def reextract_aliases(conn) -> int:
    """파서 별칭이 들어간 제목을 다시 추출해 표준 기업명으로 맞춘다."""
    rows = conn.execute(
        "SELECT id,title FROM news_articles "
        "WHERE title LIKE '%KAI%' OR title LIKE '%KF-21%' OR title LIKE '%KF21%' "
        "OR title LIKE '%보라매%' OR title LIKE '%삼성重%'"
    ).fetchall()
    changed = 0
    for row in rows:
        names = extract_companies(row["title"])
        if not names:
            continue
        conn.execute(
            "UPDATE news_articles SET company_name=?,confidence=0.85,needs_review=0 WHERE id=?",
            (", ".join(names), row["id"]),
        )
        conn.execute("DELETE FROM news_companies WHERE news_id=?", (row["id"],))
        link_companies(conn, "news_companies", "news_id", row["id"], names)
        changed += 1
    return changed


def apply_title_overrides(conn) -> int:
    """제목 기준 수동 교정을 반영한다."""
    changed = 0
    for title, names in TITLE_COMPANY_OVERRIDES.items():
        rows = conn.execute("SELECT id FROM news_articles WHERE title=?", (title,)).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE news_articles SET company_name=?,confidence=0.95,needs_review=0 WHERE id=?",
                (", ".join(names), row["id"]),
            )
            conn.execute("DELETE FROM news_companies WHERE news_id=?", (row["id"],))
            link_companies(conn, "news_companies", "news_id", row["id"], names)
            changed += 1
    return changed


def run() -> None:
    initialize()
    with connect() as conn:
        merged = merge_kai(conn)
        aliased = reextract_aliases(conn)
        overridden = apply_title_overrides(conn)
        conn.commit()
    print(f"KAI 병합: {merged}건 · 별칭 재추출: {aliased:,}건 · 수동 교정: {overridden}건")


if __name__ == "__main__":
    run()
