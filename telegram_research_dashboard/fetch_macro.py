"""오늘의 요약 상단 매크로 데이터 수집.

- 네이버 글로벌경제(101/262) Top5 헤드라인 (title + url)
- (선택) Gemini '오늘의 핵심요약' — 공개 구글 문서에서 읽어온다.

결과는 data/macro.json에 저장되고 build_static이 대시보드에 구워 넣는다.
네트워크 실패 시 기존 macro.json을 보존한다(빈 값으로 덮어쓰지 않음).
"""

from __future__ import annotations

import html
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "macro.json"
KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (compatible; GSResearchDashboard/1.0)"}

NAVER_GLOBAL_ECON = "https://news.naver.com/breakingnews/section/101/262"
# Gemini '오늘의 핵심요약'을 붙여둔 공개 구글 문서(내보내기 txt) URL.
# 문서를 '링크가 있는 모든 사용자(보기)'로 공개해야 읽힌다. 비어 있으면 건너뛴다.
DAILY_BRIEF_DOC_URL = "https://docs.google.com/document/d/1qEwmvA0MUiXDBu32b3IjnrmsX7BGKCkZiGBUNORJCXo/export?format=txt"


def _fetch(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def naver_global_top(limit: int = 5) -> list[dict]:
    src = _fetch(NAVER_GLOBAL_ECON)
    items, seen = [], set()
    for match in re.finditer(r'<a\b[^>]*\bclass="[^"]*sa_text_title[^"]*"[^>]*>(.*?)</a>', src, re.S):
        block = match.group(0)
        href_match = re.search(r'href="([^"]+)"', block)
        if not href_match:
            continue
        url = href_match.group(1)
        title = html.unescape(re.sub(r"<[^>]+>", " ", match.group(1)))
        title = re.sub(r"\s+", " ", title).strip()
        if not title or not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        items.append({"title": title[:110], "url": url})
        if len(items) >= limit:
            break
    return items


def daily_brief() -> str:
    """공개 구글 문서에서 '핵심요약' 내용을 뽑는다.

    - '핵심요약'이 들어간 헤딩이 있으면 그 섹션(다음 번호 섹션 전까지)만.
    - 그런 헤딩이 없으면 제목 한 줄을 뺀 본문 전체를 요약으로 본다.
    - 제목만 있고 본문이 없으면 빈 값(배너 숨김).
    """
    if not DAILY_BRIEF_DOC_URL:
        return ""
    text = _fetch(DAILY_BRIEF_DOC_URL).replace("﻿", "").strip()
    lines = [line for line in text.splitlines() if line.strip()]
    match = re.search(
        r"(?:^|\n)[^\n]*핵심\s*요약[^\n]*\n+(.*?)(?=\n\s*\d+[.)]\s|\Z)",
        text, re.S,
    )
    if match and match.group(1).strip():
        body = match.group(1).strip()
    elif len(lines) > 1:
        body = "\n".join(lines[1:]).strip()  # 제목 줄 제외 전체
    else:
        body = ""  # 제목만 있고 아직 내용 없음
    return re.sub(r"\n{3,}", "\n\n", body)[:2000]


def run() -> None:
    prior = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    data = dict(prior)
    data["generated_at"] = datetime.now(KST).isoformat()
    try:
        top = naver_global_top()
        if top:
            data["global_economy"] = top
    except OSError as exc:
        print(f"네이버 글로벌경제 수집 실패(기존 유지): {exc}")
    try:
        brief = daily_brief()
        if brief:
            data["daily_brief"] = brief
    except OSError as exc:
        print(f"핵심요약 수집 실패(기존 유지): {exc}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"매크로 수집: 글로벌경제 {len(data.get('global_economy', []))}건 · "
          f"핵심요약 {'있음' if data.get('daily_brief') else '없음'}")


if __name__ == "__main__":
    run()
