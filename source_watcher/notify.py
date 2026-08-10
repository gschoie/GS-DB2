"""텔레그램 봇 발송.

defense_briefing_bot.send_telegram과 같은 정책이다.
- 4096자 제한 때문에 문단 경계에서 잘라 여러 통으로 보낸다.
- HTML parse_mode가 400으로 튕기면 태그를 벗겨 평문으로 한 번 더 시도한다.
"""

from __future__ import annotations

import html
import os
import re
import sys
import time

import requests

# 텔레그램 하드 리밋은 4096자. 조각 번호 접미사와 여유를 뺀 값.
CHUNK_LIMIT = 3800
SEND_URL = "https://api.telegram.org/bot{token}/sendMessage"


def escape(value: str) -> str:
    """텔레그램 HTML 모드에 넣을 사용자 텍스트 이스케이프."""
    return html.escape(value, quote=False)


def split_chunks(text: str, limit: int = CHUNK_LIMIT) -> list[str]:
    """문단 → 줄 → 강제 순으로 경계를 낮춰가며 자른다."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    buffer = ""
    for block in text.split("\n\n"):
        candidate = f"{buffer}\n\n{block}" if buffer else block
        if len(candidate) <= limit:
            buffer = candidate
            continue
        if buffer:
            chunks.append(buffer)
            buffer = ""
        while len(block) > limit:
            cut = block.rfind("\n", 0, limit)
            if cut <= 0:
                cut = limit
            chunks.append(block[:cut].rstrip())
            block = block[cut:].lstrip("\n")
        buffer = block
    if buffer:
        chunks.append(buffer)
    return [chunk for chunk in chunks if chunk.strip()]


def send(text: str, *, token: str | None = None, chat_id: str | None = None,
         session: requests.Session | None = None) -> int:
    """메시지 한 건을 보낸다. 보낸 조각 수를 돌려준다."""
    token = token or os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = chat_id or os.environ["TELEGRAM_CHAT_ID"]
    poster = session or requests

    chunks = split_chunks(text)
    total = len(chunks)
    for index, chunk in enumerate(chunks, 1):
        suffix = f"\n\n({index}/{total})" if total > 1 else ""
        payload = {
            "chat_id": chat_id,
            "text": chunk + suffix,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        for attempt in range(3):
            response = poster.post(SEND_URL.format(token=token), json=payload, timeout=30)
            if response.ok:
                break
            if response.status_code == 400 and attempt == 0:
                # 대개 본문에 남은 꺾쇠 때문. 태그를 벗겨 평문으로 재시도한다.
                print(f"[텔레그램 400] {response.text[:200]} → 평문 재시도", file=sys.stderr)
                payload = {
                    "chat_id": chat_id,
                    "text": re.sub(r"<[^>]+>", "", chunk) + suffix,
                    "disable_web_page_preview": False,
                }
                continue
            time.sleep(5)
        else:
            raise RuntimeError(f"텔레그램 전송 실패: {response.status_code} {response.text[:300]}")
        time.sleep(1.2)
    return total
