"""단발성 공유(기사 링크 1개 + 본인 코멘트)의 코멘트를 news_articles.comment에 채운다.

원본 텔레그램 메시지(telegram_messages.text)에서 URL·채널 서명·출처 줄을 걷어내고
남은 본문(2줄 이상)을 '내 코멘트'로 본다. 데일리뉴스 묶음·위클리는 제외한다.
enrich로 기사 제목을 실제 제목으로 바꾼 뒤 실행하는 것을 전제로 하며,
여러 번 실행해도 안전하다.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from article_metadata import fetch_article_metadata, TITLE_PLACEHOLDERS
from db import connect, initialize
from parser import URL_RE, DAILY_NEWS_RE, WEEKLY_RE, is_channel_signature


def extract_comment(text: str) -> str | None:
    if not text or DAILY_NEWS_RE.search(text) or WEEKLY_RE.search(text):
        return None
    urls = [u for u in URL_RE.findall(text) if "t.me/" not in u and "telegram.me/" not in u]
    if len(urls) != 1:  # 링크가 정확히 하나인 단발성 공유만 코멘트로 본다
        return None
    lines = []
    for raw in text.splitlines():
        line = raw.strip(" -•>\t")
        if (not line or line.startswith("http") or URL_RE.search(line)
                or is_channel_signature(line)
                or line.startswith(("출처:", "출처 ", "* 위 내용", "위 내용은"))):
            continue
        lines.append(line)
    if len(lines) < 2:  # 한 줄뿐이면 기사 헤드라인일 가능성이 커 코멘트로 보지 않는다
        return None
    return "\n".join(lines)[:1000]


def run() -> int:
    initialize()
    updated = retitled = 0
    with connect() as conn:
        rows = conn.execute(
            """SELECT n.id, n.title, n.article_url, m.text FROM news_articles n
               JOIN telegram_messages m ON m.id = n.message_id
               WHERE n.source_index = 0"""
        ).fetchall()
        targets = [(row, extract_comment(row["text"] or "")) for row in rows]
        targets = [(row, comment) for row, comment in targets if comment]
        # 코멘트 행은 제목이 사실상 코멘트다. 실제 기사 제목을 원문에서 가져와 교체한다.
        with ThreadPoolExecutor(max_workers=min(12, max(1, len(targets)))) as executor:
            metas = list(executor.map(
                lambda t: fetch_article_metadata(t[0]["article_url"]) if t[0]["article_url"] else None,
                targets,
            ))
        for (row, comment), meta in zip(targets, metas):
            title = row["title"]
            fetched = meta.get("title") if meta else None
            if fetched and fetched not in TITLE_PLACEHOLDERS and fetched != title:
                title = fetched
                retitled += 1
            conn.execute("UPDATE news_articles SET comment=?,title=? WHERE id=?", (comment, title, row["id"]))
            updated += 1
        conn.commit()
    print(f"코멘트 backfill: {updated:,}건 (제목 교체 {retitled:,}건)")
    return updated


if __name__ == "__main__":
    run()
