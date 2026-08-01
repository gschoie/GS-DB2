"""단발성 공유(기사 링크 1개 + 본인 코멘트)의 코멘트를 news_articles.comment에 채운다.

원본 텔레그램 메시지(telegram_messages.text)에서 URL·채널 서명·출처 줄을 걷어내고
남은 본문(2줄 이상)을 '내 코멘트'로 본다. 데일리뉴스 묶음·위클리는 제외한다.
enrich로 기사 제목을 실제 제목으로 바꾼 뒤 실행하는 것을 전제로 하며,
여러 번 실행해도 안전하다.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from article_metadata import fetch_article_metadata, should_replace_title
from db import connect, initialize
from parser import URL_RE, DAILY_NEWS_RE, WEEKLY_RE, bilingual_headline_pair, is_channel_signature

# GEM 요약 공유 형식: [제목] + • 불릿 요약 + ❗️ 한줄 평 + ───── + 🎴 내 의견(스포일러).
# •/❗️ 줄은 기사 내용 요약이지 내 코멘트가 아니다 — 내 의견은 🎴 이후에만 있다.
COMMENT_MARKER = "🎴"
SEPARATOR_RE = re.compile(r"^[─━―—=＝_\-]{4,}$")
# DART 알림봇 포맷("공시제목 + 링크 + 날짜")의 날짜 줄. 이 줄을 거르면 제목 한 줄만 남아
# '한 줄은 헤드라인' 규칙이 작동한다 — 공시제목+날짜가 코멘트로 오인되던 문제 방지.
DATE_LINE_RE = re.compile(r"^\d{4}[-./]\s?\d{1,2}[-./]\s?\d{1,2}\.?$")


def extract_comment(text: str) -> str | None:
    if not text or DAILY_NEWS_RE.search(text) or WEEKLY_RE.search(text):
        return None
    urls = [u for u in URL_RE.findall(text) if "t.me/" not in u and "telegram.me/" not in u]
    if len(urls) != 1:  # 링크가 정확히 하나인 단발성 공유만 코멘트로 본다
        return None
    raw_lines = text.splitlines()
    # 🎴 줄부터가 내 의견이다. 단 채널 서명(🎴 조선/기계/방산 | 최광식 …)은 의견이 아니다.
    marker_index = next((index for index, raw in enumerate(raw_lines)
                         if COMMENT_MARKER in raw and not is_channel_signature(raw)), None)
    opinion = None
    if marker_index is not None:
        joined = "\n".join(_clean_lines(raw_lines[marker_index:]))
        opinion = joined.removeprefix(COMMENT_MARKER).strip()[:1000] or None
    pair = bilingual_headline_pair(text)
    if pair:
        # 외신 공유(영어 원제 + 한국어 번역): 제목은 한국어 번역이 가져가므로
        # 코멘트에는 영어 원제를 남긴다(🎴 의견이 있으면 그 아래 덧붙임).
        return "\n".join(part for part in (pair[0], opinion) if part)[:1000]
    if marker_index is not None:
        return opinion
    if any(raw.lstrip().startswith(("•", "❗")) for raw in raw_lines):
        return None  # 요약만 있고 🎴 의견이 없는 GEM 공유
    lines = _clean_lines(raw_lines)
    if len(lines) < 2:  # 한 줄뿐이면 기사 헤드라인일 가능성이 커 코멘트로 보지 않는다
        return None
    return "\n".join(lines)[:1000]


def _clean_lines(raw_lines: list[str]) -> list[str]:
    lines = []
    for raw in raw_lines:
        line = raw.strip(" -•>\t")
        if (not line or line.startswith("http") or URL_RE.search(line)
                or is_channel_signature(line) or SEPARATOR_RE.match(line)
                or DATE_LINE_RE.match(line)
                or line.startswith(("출처:", "출처 ", "* 위 내용", "위 내용은"))):
            continue
        lines.append(line)
    return lines


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
            if fetched and fetched != title and should_replace_title(title, fetched):
                title = fetched
                retitled += 1
            conn.execute("UPDATE news_articles SET comment=?,title=? WHERE id=?", (comment, title, row["id"]))
            updated += 1
        conn.commit()
    print(f"코멘트 backfill: {updated:,}건 (제목 교체 {retitled:,}건)")
    return updated


if __name__ == "__main__":
    run()
