"""기존 '기사 제목 미확인' 링크를 원문 제목과 기업명으로 점진 보강한다."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor

from article_metadata import (
    JUNK_TITLE_RE, TITLE_PLACEHOLDERS, enrich_news_item, fetch_article_metadata, publisher_from,
)
from db import connect, initialize
from telegram_importer import link_companies


# publisher를 다시 확인해야 하는(단축·집계) 호스트
STALE_PUBLISHERS = ("buly.kr", "bit.ly", "bitly.ws", "tinyurl.com", "han.gl", "url.kr", "me2.do")
# 언론 기사가 아니라 원문 추적이 의미 없는 호스트
NON_ARTICLE_FILTER = """n.article_url NOT LIKE 'https://t.me/%' AND n.article_url NOT LIKE 'http://t.me/%'
                    AND n.article_url NOT LIKE '%cafe.naver.com/%' AND n.article_url NOT LIKE '%dart.fss.or.kr%'
                    AND n.article_url NOT LIKE '%youtu.be/%' AND n.article_url NOT LIKE '%youtube.com/%'
                    AND n.article_url NOT LIKE '%finance.naver.com%'"""


def run(limit: int, force_all: bool = False) -> tuple[int, int]:
    initialize()
    placeholders = tuple(TITLE_PLACEHOLDERS)
    stale = "(" + " OR ".join(f"n.publisher='{host}'" for host in STALE_PUBLISHERS) + ")"
    scope = "1=1" if force_all else f"""(n.title IN (?,?) OR COALESCE(n.company_name,'')=''
                    OR NOT EXISTS (SELECT 1 FROM news_companies nc WHERE nc.news_id=n.id)
                    OR n.publisher IS NULL OR {stale})"""
    attempts = "1=1" if force_all else "(a.news_id IS NULL OR a.attempted_at < datetime('now','-30 days'))"
    sql = f"""SELECT n.id,n.title,n.article_url,n.event_type,n.summary,n.confidence,n.needs_review,
                     n.company_name,n.publisher
             FROM news_articles n
             LEFT JOIN article_metadata_attempts a ON a.news_id=n.id
             WHERE n.article_url IS NOT NULL AND {NON_ARTICLE_FILTER}
               AND {scope} AND {attempts}
             ORDER BY CASE WHEN a.news_id IS NULL THEN 0 ELSE 1 END,n.id DESC LIMIT ?"""
    checked = updated = 0
    with connect() as conn:
        # 과거에 저장돼버린 단축링크 랜딩/봇차단 제목은 placeholder로 되돌려 재수집 대상으로 만든다.
        junk_ids = [row["id"] for row in conn.execute(
            "SELECT id,title FROM news_articles WHERE title IS NOT NULL") if JUNK_TITLE_RE.search(row["title"])]
        if junk_ids:
            conn.executemany("UPDATE news_articles SET title='기사 제목 미확인',summary=NULL WHERE id=?",
                             [(i,) for i in junk_ids])
            print(f"단축링크 랜딩 제목 리셋: {len(junk_ids):,}건")
        rows = conn.execute(sql, (limit,) if force_all else (*placeholders, limit)).fetchall()
        with ThreadPoolExecutor(max_workers=min(12, max(1, len(rows)))) as executor:
            metadata = list(executor.map(fetch_article_metadata, (row["article_url"] for row in rows)))
        for row, fetched in zip(rows, metadata):
            checked += 1
            item = {**dict(row), "companies": [], "company_name": None}
            enrich_news_item(item, lambda _url, value=fetched: value)
            success = int(item["title"] not in TITLE_PLACEHOLDERS)
            conn.execute(
                """INSERT INTO article_metadata_attempts(news_id,attempted_at,success)
                   VALUES(?,CURRENT_TIMESTAMP,?) ON CONFLICT(news_id) DO UPDATE SET
                   attempted_at=CURRENT_TIMESTAMP,success=excluded.success""",
                (row["id"], success),
            )
            if item["title"] in TITLE_PLACEHOLDERS:
                continue
            # 새 추출이 비면 기존 기업 배정을 지우지 않는다.
            company_name = item["company_name"] or row["company_name"]
            publisher = publisher_from(fetched, row["article_url"]) or row["publisher"]
            needs_review = 0 if company_name else item["needs_review"]
            conn.execute(
                """UPDATE news_articles SET title=?,company_name=?,publisher=?,summary=?,confidence=?,needs_review=?
                   WHERE id=?""",
                (item["title"], company_name, publisher, item["summary"], item["confidence"],
                 needs_review, row["id"]),
            )
            if item["companies"]:
                conn.execute("DELETE FROM news_companies WHERE news_id=?", (row["id"],))
                link_companies(conn, "news_companies", "news_id", row["id"], item["companies"])
            updated += 1
        conn.commit()
    print(f"링크 기사 보강: {updated:,}/{checked:,}건")
    return checked, updated


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("--limit", type=int, default=200)
    cli.add_argument("--all", action="store_true")
    args = cli.parse_args()
    run(max(1, args.limit), args.all)
