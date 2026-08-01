"""공개 Telegram 웹 미리보기에서 글을 가져오는 무로그인 수집기.

공식 API 수집보다 HTML 변경에 취약하므로 간편 시작/백업 경로로 사용한다.
"""

from __future__ import annotations

import argparse
import html
import re
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from types import SimpleNamespace
import urllib.error
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from db import connect, initialize
from telegram_importer import load_dotenv, store_message


POST_RE = re.compile(r'data-post="([^"/]+)/([0-9]+)"')
DATETIME_RE = re.compile(r'<time[^>]+datetime="([^"]+)"')
# 답글의 원글 링크: <a class="tgme_widget_message_reply …" href="https://t.me/<채널>/<번호>"
REPLY_RE = re.compile(r'class="tgme_widget_message_reply[^"]*"\s+href="[^"]*/([0-9]+)"')
BLOCK_RE = re.compile(
    r'(<div class="tgme_widget_message_wrap[^>]*>.*?)(?=<div class="tgme_widget_message_wrap|<div class="tgme_widget_message_centered|\Z)',
    re.S,
)


class MessageTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.capture = False
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        classes = values.get("class", "").split()
        # js-message_reply_text는 답글에 붙는 원글 인용 미리보기 — 본문이 아니므로 제외한다.
        # (섞으면 원글 요약과 잘린 URL("https://en.defence…")이 답글 텍스트에 들어간다.)
        if tag == "div" and "tgme_widget_message_text" in classes and "js-message_reply_text" not in classes:
            self.capture = True
            self.depth = 1
            return
        if self.capture:
            if tag == "div":
                self.depth += 1
            if tag == "br":
                self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.capture and tag == "div":
            self.depth -= 1
            if self.depth == 0:
                self.capture = False

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)

    def text(self) -> str:
        value = html.unescape("".join(self.parts)).replace("\xa0", " ")
        return "\n".join(line.strip() for line in value.splitlines() if line.strip())


def normalize_channel(value: str) -> str:
    value = value.strip().rstrip("/")
    if value.startswith("@"):
        return value[1:]
    if "t.me/" in value:
        return urlparse(value).path.strip("/").removeprefix("s/")
    return value


def fetch_page(channel: str, before: int | None) -> str:
    url = f"https://t.me/s/{channel}"
    if before:
        url += f"?before={before}"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 ResearchDashboard/1.0"})
    # 러너의 일시적 DNS/네트워크 오류(예: Name or service not known)에 죽지 않도록 재시도한다.
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, OSError) as exc:
            last_error = exc
            print(f"  ⚠ 요청 실패({attempt + 1}/4) {url}: {exc} — 재시도", flush=True)
            time.sleep(3 * (attempt + 1))
    raise last_error


def parse_page(source: str) -> list[SimpleNamespace]:
    messages = []
    for block in BLOCK_RE.findall(source):
        post = POST_RE.search(block)
        stamp = DATETIME_RE.search(block)
        if not post or not stamp:
            continue
        parser = MessageTextParser()
        parser.feed(block)
        text = parser.text()
        if not text:
            continue
        reply = REPLY_RE.search(block)
        messages.append(SimpleNamespace(
            id=int(post.group(2)), message=text,
            date=datetime.fromisoformat(stamp.group(1).replace("Z", "+00:00")),
            edit_date=None, media=None,
            reply_to_msg_id=int(reply.group(1)) if reply else None,
        ))
    return messages


def sync(channel_value: str, pages: int, since_days: int = 14) -> None:
    """최신 글부터 과거로 페이징하며 DB에 병합(중복 제거)한다.

    since_days>0 이면 'DB의 최신 글 날짜 − since_days' 시점까지만 되돌아간다(2주 안전창).
    → 그 이전은 이미 DB에 있으므로 전체 이력을 다시 긁지 않아 빠르고, 최근 구간은
      매번 재확인하므로 누락/수정도 보정된다. pages 는 안전 상한(0=상한 없음).
    """
    initialize()
    channel = normalize_channel(channel_value)
    with connect() as conn:
        cutoff = None
        if since_days > 0:
            row = conn.execute(
                "SELECT MAX(posted_at) FROM telegram_messages WHERE channel_id=?", (channel,)
            ).fetchone()
            if row and row[0]:
                cutoff = datetime.fromisoformat(row[0]).astimezone(timezone.utc) - timedelta(days=since_days)
                print(f"증분 기준(2주 안전창): {cutoff.date()} 이후만 수집")
        before = None
        seen_ids: set[int] = set()
        total = 0
        page = 0
        while pages == 0 or page < pages:
            batch = parse_page(fetch_page(channel, before))
            fresh = [message for message in batch if message.id not in seen_ids]
            if not fresh:
                break
            for message in sorted(fresh, key=lambda item: item.id):
                store_message(conn, channel, message)
                seen_ids.add(message.id)
                total += 1
            conn.commit()
            oldest_id = min(message.id for message in fresh)
            oldest_date = min(message.date for message in fresh).astimezone(timezone.utc)
            page += 1
            print(f"{page}페이지 · 누적 {total:,}개 · 최고참 {oldest_date.date()}")
            if cutoff is not None and oldest_date <= cutoff:
                break  # 2주 안전창보다 과거까지 왔으면 중단(그 이전은 이미 DB에 있음)
            if before == oldest_id:
                break
            before = oldest_id
            time.sleep(0.4)
    print(f"@{channel} 공개채널 동기화 완료: {total:,}개 메시지")


if __name__ == "__main__":
    load_dotenv()
    import os
    cli = argparse.ArgumentParser()
    cli.add_argument("--channel", default=os.getenv("TELEGRAM_CHANNEL", "https://t.me/HI_GS"))
    cli.add_argument("--pages", type=int, default=0, help="안전 상한 페이지 수. 0이면 상한 없음(날짜창으로 중단)")
    cli.add_argument("--since-days", type=int, default=14,
                     help="DB 최신글에서 이 일수만큼 이전까지 재수집(2주 안전창). 0이면 날짜창 비활성")
    args = cli.parse_args()
    sync(args.channel, args.pages, args.since_days)

