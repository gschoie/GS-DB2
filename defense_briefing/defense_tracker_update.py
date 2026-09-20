#!/usr/bin/env python3
"""방산 입찰·예산 트래커 자동 갱신.

defense-briefing 워크플로에서 브리핑 생성 직후 실행된다. 그날의 방산
브리핑 마크다운(static/defense_daily/<날짜>.md)을 Gemini에 주고
① 입찰/수주경쟁 ② 국방예산 ③ 법안 관련 이벤트를 추출해,
static/defense_tracker.json의 해당 항목 log에 누적한다.

- 기존 항목과 매칭되면 그 항목의 log에 추가
- 매칭 안 되는 신규 이벤트는 meta.inbox에 쌓아 수동 검토 대상으로 남긴다
- 구조화 필드(stage, status, amount 등)는 자동으로 바꾸지 않는다

표준 라이브러리만 사용. GEMINI_API_KEY가 없으면 아무것도 하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DASH_STATIC = ROOT.parent / "telegram_research_dashboard" / "static"
TRACKER_PATH = DASH_STATIC / "defense_tracker.json"
DAILY_DIR = DASH_STATIC / "defense_daily"

GEMINI_API_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
KST = timezone(timedelta(hours=9))


def gemini_extract(catalog: list[dict], briefing_md: str) -> list[dict]:
    model = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
    system_text = (
        "너는 방산 산업 리서치 어시스턴트다. 오늘의 방산 브리핑 본문에서 다음 세 종류의 "
        "이벤트만 추출한다: ① 무기 입찰/수주경쟁(기종 선정·협상·추천·계약 포함) "
        "② 국가별 국방예산(편성·요구·심의·의결) ③ 국방 관련 법안(발의·통과·성립).\n"
        "각 이벤트에 대해:\n"
        "- section: 'tenders'(입찰/경쟁) 또는 'policy'(예산/법안). 해당 없으면 'none'.\n"
        "- target_id: 제공된 트래커 항목 중 같은 사업/예산이면 그 id, 새 항목이면 'new'.\n"
        "- country, name: 국가와 사업/예산 이름(한국어).\n"
        "- text_ko: 한국어 한 문장 요약(금액·단계 포함).\n"
        "- importance: 트래킹 가치 0~10. 단순 시황·주가 언급은 3 이하.\n"
        "일반 뉴스·기업 실적·이미 로그에 있을 법한 반복 언급은 제외한다."
    )
    user_text = json.dumps(
        {"tracker_items": catalog, "briefing": briefing_md[:15000]}, ensure_ascii=False
    )
    body = {
        "systemInstruction": {"parts": [{"text": system_text}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "results": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "section": {"type": "STRING", "enum": ["tenders", "policy", "none"]},
                                "target_id": {"type": "STRING"},
                                "country": {"type": "STRING"},
                                "name": {"type": "STRING"},
                                "text_ko": {"type": "STRING"},
                                "importance": {"type": "INTEGER"},
                            },
                            "required": ["section", "target_id", "country", "name", "text_ko", "importance"],
                        },
                    }
                },
                "required": ["results"],
            },
        },
    }
    max_attempts = int(os.getenv("GEMINI_MAX_RETRIES", "4"))
    base_delay = float(os.getenv("GEMINI_RETRY_BASE_SECONDS", "15"))
    for attempt in range(1, max_attempts + 1):
        request = urllib.request.Request(
            GEMINI_API_TEMPLATE.format(model=model),
            data=json.dumps(body).encode("utf-8"),
            headers={
                "x-goog-api-key": os.environ["GEMINI_API_KEY"],
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
            parts = []
            for candidate in payload.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    if isinstance(part.get("text"), str):
                        parts.append(part["text"])
            return json.loads("\n".join(parts)).get("results", [])
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="ignore")
            if exc.code in (429, 503) and attempt < max_attempts:
                time.sleep(base_delay * (2 ** (attempt - 1)))
                continue
            raise RuntimeError(f"Gemini API error {exc.code}: {error_body or exc.reason}") from exc
    raise RuntimeError("Gemini retry loop exited unexpectedly")


def latest_briefing() -> tuple[str, str] | None:
    """(날짜, 본문). 오늘자 우선, 없으면 최신 md."""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    candidates = sorted(DAILY_DIR.glob("????-??-??.md"), reverse=True)
    for p in candidates:
        if p.stem == today:
            return p.stem, p.read_text(encoding="utf-8")
    if candidates:
        p = candidates[0]
        return p.stem, p.read_text(encoding="utf-8")
    return None


def main() -> int:
    if not os.getenv("GEMINI_API_KEY", "").strip():
        print("GEMINI_API_KEY 없음 — 트래커 갱신 생략")
        return 0
    if not TRACKER_PATH.exists():
        print("defense_tracker.json 없음 — 생략")
        return 0

    found = latest_briefing()
    if not found:
        print("방산 브리핑 md 없음 — 생략")
        return 0
    date_str, md = found

    data = json.loads(TRACKER_PATH.read_text(encoding="utf-8"))
    meta = data.setdefault("meta", {})
    seen = list(meta.get("seen", []))
    md_hash = hashlib.sha1(md.encode("utf-8")).hexdigest()[:16]
    if md_hash in seen:
        print(f"{date_str} 브리핑은 이미 처리됨 — 생략")
        return 0

    catalog = (
        [{"id": t["id"], "section": "tenders", "country": t["country"], "name": t["program"]}
         for t in data.get("tenders", [])]
        + [{"id": p["id"], "section": "policy", "country": p["country"], "name": p["title"]}
           for p in data.get("policy", [])]
    )
    by_id = {t["id"]: t for t in data.get("tenders", [])}
    by_id.update({p["id"]: p for p in data.get("policy", [])})

    try:
        results = gemini_extract(catalog, md)
    except Exception as exc:
        print(f"Gemini 추출 실패 — 생략: {exc}", file=sys.stderr)
        return 0

    min_imp = int(os.getenv("DEFENSE_TRACKER_MIN_IMPORTANCE", "5"))
    added = new_items = 0
    for r in results:
        if r["section"] == "none" or r["importance"] < min_imp:
            continue
        text = r["text_ko"].strip()
        if not text:
            continue
        if r["target_id"] in by_id:
            by_id[r["target_id"]].setdefault("log", []).append({"date": date_str, "text": text, "link": ""})
            added += 1
            print(f"  + [{r['target_id']}] {text[:70]}")
        else:
            meta.setdefault("inbox", []).append(
                {"date": date_str, "country": r["country"], "name": r["name"], "text": text}
            )
            new_items += 1
            print(f"  ? [신규→inbox] {r['country']} {r['name']}: {text[:60]}")

    meta["inbox"] = meta.get("inbox", [])[-50:]
    seen.append(md_hash)
    meta["seen"] = seen[-100:]
    if added or new_items:
        meta["updated"] = date_str
    TRACKER_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"트래커 갱신: 로그 {added}건, 신규(inbox) {new_items}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
