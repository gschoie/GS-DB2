"""수동 교정과 기업명 표준화를 DB에 적용한다. 여러 번 실행해도 안전(idempotent)하다.

1) KAI → 한국항공우주 통합 (companies 테이블 병합 + 뉴스/보고서 재연결)
2) 별칭 기사 재추출 (삼성重·KF-21·보라매 등 파서 별칭을 표준 기업명으로)
3) manual_overrides.TITLE_COMPANY_OVERRIDES 반영 (의미상 교정)
4) 기업 미연결 보고서 백필 (구사명 별칭 포함 재추출 — 옛 아카이브 자가치유)
"""

from __future__ import annotations

from db import connect, initialize
from parser import APPROVED_COMPANIES, extract_companies, identify_companies
from telegram_importer import link_companies
from manual_overrides import (
    TITLE_COMPANY_OVERRIDES, URL_COMPANY_OVERRIDES, URL_COMMENT_OVERRIDES,
)


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
        "OR title LIKE '%보라매%' OR title LIKE '%삼성重%' OR title LIKE '%고스트로보틱스%'"
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


def _assign(conn, news_id: int, names: list[str]) -> None:
    conn.execute(
        "UPDATE news_articles SET company_name=?,confidence=0.95,needs_review=0 WHERE id=?",
        (", ".join(names), news_id),
    )
    conn.execute("DELETE FROM news_companies WHERE news_id=?", (news_id,))
    link_companies(conn, "news_companies", "news_id", news_id, names)


def apply_title_overrides(conn) -> int:
    """제목·URL 기준 수동 교정을 반영한다."""
    changed = 0
    for title, names in TITLE_COMPANY_OVERRIDES.items():
        for row in conn.execute("SELECT id FROM news_articles WHERE title=?", (title,)).fetchall():
            _assign(conn, row["id"], names)
            changed += 1
    for url, names in URL_COMPANY_OVERRIDES.items():
        for row in conn.execute("SELECT id FROM news_articles WHERE article_url=?", (url,)).fetchall():
            _assign(conn, row["id"], names)
            changed += 1
    for url, comment in URL_COMMENT_OVERRIDES.items():
        conn.execute("UPDATE news_articles SET comment=? WHERE article_url=?", (comment, url))
    return changed


def backfill_report_companies(conn) -> int:
    """승인 기업 링크가 하나도 없는 보고서를 본문에서 다시 추출해 연결한다.

    링크가 아예 없는 보고서뿐 아니라, 옛 파서 폴백이 남긴 노이즈 태그(비승인
    기업명)만 달린 보고서도 대상이다. 파서 사전이 늘어날 때마다(구사명 별칭 등)
    옛 보고서가 자동으로 따라붙는다. 위클리는 여러 기업이 스치는 뉴스
    다이제스트라 링크 노이즈만 생기므로 제외한다.
    """
    # build_static 표시 규칙과 동일하게, 표준명으로 통일하면 승인되는 구명칭도 인정한다.
    canonical = {"KAI": "한국항공우주", "현대마린엔진": "HD현대마린엔진"}
    approved = set(APPROVED_COMPANIES)
    rows = conn.execute(
        "SELECT r.id, m.text, COALESCE((SELECT group_concat(c.name, char(1)) "
        "FROM report_companies rc JOIN companies c ON c.id=rc.company_id "
        "WHERE rc.report_id=r.id), '') linked "
        "FROM reports r JOIN telegram_messages m ON m.id=r.message_id "
        "WHERE r.report_type!='위클리'"
    ).fetchall()
    changed = 0
    for row in rows:
        linked = [name for name in row["linked"].split("\x01") if name]
        if any(canonical.get(name, name) in approved for name in linked):
            continue
        names = identify_companies(row["text"])
        if not names or set(names) == set(linked):
            continue
        conn.execute(
            "UPDATE reports SET company_name=? WHERE id=?", (", ".join(names), row["id"])
        )
        conn.execute("DELETE FROM report_companies WHERE report_id=?", (row["id"],))
        link_companies(conn, "report_companies", "report_id", row["id"], names)
        changed += 1
    return changed


def run() -> None:
    initialize()
    with connect() as conn:
        merged = merge_kai(conn)
        aliased = reextract_aliases(conn)
        overridden = apply_title_overrides(conn)
        backfilled = backfill_report_companies(conn)
        conn.commit()
    print(f"KAI 병합: {merged}건 · 별칭 재추출: {aliased:,}건 · 수동 교정: {overridden}건 · 보고서 기업 백필: {backfilled}건")


if __name__ == "__main__":
    run()
