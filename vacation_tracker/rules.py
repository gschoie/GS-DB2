"""휴가 보고 메시지의 규칙 기반 판별·날짜 해석.

Gemini가 없거나 실패해도 최소한의 정리는 되도록, 순수 파이썬(표준 라이브러리)으로
후보 판별과 날짜 해석을 한다. Gemini가 있으면 이 결과 대신 Gemini 해석을 쓴다.

날짜 해석은 '메시지를 보낸 시각' 기준이다 — "내일", "다음주 수요일" 같은 상대 표현은
지금이 아니라 그 메시지가 쓰인 날을 기준으로 풀어야 맞다.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9), name="KST")

# 종류 판별은 긴 표현부터 — "오후 반차"가 "반차"보다 먼저 잡혀야 한다.
KIND_PATTERNS: list[tuple[str, str]] = [
    (r"오전\s*반차", "오전반차"),
    (r"오후\s*반차", "오후반차"),
    (r"반\s*반차", "반반차"),
    (r"반차", "반차"),
    (r"여름\s*휴가", "여름휴가"),
    (r"겨울\s*휴가", "겨울휴가"),
    (r"연차", "연차"),
    (r"월차", "월차"),
    (r"연가", "연가"),
    (r"병가", "병가"),
    (r"휴직", "휴직"),
    (r"해외\s*출장", "해외출장"),
    (r"출장", "출장"),
    (r"[샵숍]\s*투어", "샵투어"),
    (r"휴무", "휴무"),
    (r"오프", "오프"),
    (r"휴가", "휴가"),
]

_KIND_RES = [(re.compile(pattern), label) for pattern, label in KIND_PATTERNS]

# 잡담 오탐 컷: 휴가 단어가 있어도 남 얘기·과거 회상·질문이면 보고가 아니다.
# 과하게 거르면 놓치므로 확실한 것만 — 나머지는 Gemini 또는 needs_review가 받는다.
_NEGATIVE_RE = re.compile(r"휴가철|휴가지\s*추천|휴가\s*어땠|휴가\s*잘\s*다녀|휴가\s*는\s*어디")


def detect_kind(text: str) -> str | None:
    """휴가 종류 단어를 찾는다. 없으면 None — 후보 아님."""
    for pattern, label in _KIND_RES:
        if pattern.search(text):
            return label
    return None


def is_candidate(text: str) -> bool:
    """휴가 보고 '후보' 메시지인지. 넓게 잡고, 정밀 판정은 다음 단계가 한다."""
    if not text or not text.strip():
        return False
    if _NEGATIVE_RE.search(text):
        return False
    return detect_kind(text) is not None


# ── 날짜 해석 ──────────────────────────────────────────────────────────────

# 8/31 · 8.31 · 8월 31일 · 2026-08-31 · 2026년 8월 31일
_DATE_TOKEN = re.compile(
    r"(?:(\d{4})\s*[년./-]\s*)?(\d{1,2})\s*[월./-]\s*(\d{1,2})\s*일?"
)
_REL_TOKEN = re.compile(r"오늘|내일|모레|글피")
_REL_DAYS = {"오늘": 0, "내일": 1, "모레": 2, "글피": 3}
_WEEKDAY_TOKEN = re.compile(r"(이번\s*주|다음\s*주|담주|차주|내주)?\s*([월화수목금토일])요일")
_DURATION = re.compile(r"(\d{1,2})\s*일\s*(?:간|동안)")
_WEEKDAYS = "월화수목금토일"


def _resolve_md(year: str | None, month: int, day: int, base: date) -> date | None:
    """월/일을 실제 날짜로. 연도가 없으면 메시지 시점에서 가까운 해로 잡는다."""
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return None
    try:
        if year:
            return date(int(year), month, day)
        candidate = date(base.year, month, day)
    except ValueError:
        return None
    # "1월 2일 휴가"를 12월에 보고했다면 내년 얘기다. 90일 넘게 과거면 다음 해로.
    if (base - candidate).days > 90:
        try:
            return date(base.year + 1, month, day)
        except ValueError:
            return None
    return candidate


def _resolve_weekday(prefix: str | None, weekday_char: str, base: date) -> date:
    target = _WEEKDAYS.index(weekday_char)
    monday = base - timedelta(days=base.weekday())
    prefix = (prefix or "").replace(" ", "")
    if prefix in ("다음주", "담주", "차주", "내주"):
        return monday + timedelta(days=7 + target)
    if prefix == "이번주":
        return monday + timedelta(days=target)
    # 접두어 없으면 오늘 포함 다가오는 그 요일
    delta = (target - base.weekday()) % 7
    return base + timedelta(days=delta)


def extract_dates(text: str, base: datetime) -> tuple[date | None, date | None]:
    """본문에서 휴가 시작·종료일을 추정한다. 실패하면 (None, None) — needs_review 행이 된다.

    날짜 토큰을 등장 순서대로 모아 첫 두 개를 쓴다. 두 개면 구간, 한 개면 하루.
    "8/31부터 3일간"처럼 기간 표현이 붙으면 종료일을 늘린다.
    """
    base_date = base.astimezone(KST).date() if base.tzinfo else base.date()
    found: list[tuple[int, date, str]] = []

    for match in _DATE_TOKEN.finditer(text):
        resolved = _resolve_md(match.group(1), int(match.group(2)), int(match.group(3)), base_date)
        if resolved:
            found.append((match.start(), resolved, "md"))
    for match in _REL_TOKEN.finditer(text):
        found.append((match.start(), base_date + timedelta(days=_REL_DAYS[match.group(0)]), "rel"))
    for match in _WEEKDAY_TOKEN.finditer(text):
        found.append((match.start(), _resolve_weekday(match.group(1), match.group(2), base_date),
                      "weekday"))

    if not found:
        return None, None
    found.sort(key=lambda item: item[0])
    picked = found[:2]

    if len(picked) >= 2:
        start, end = picked[0][1], picked[1][1]
        if end < start:
            if picked[1][2] == "weekday":
                # "다음주 수요일부터 금요일까지" — 뒤쪽 맨요일은 시작일과 같은 주다.
                while end < start:
                    end += timedelta(days=7)
            else:
                start, end = end, start
    else:
        start = end = picked[0][1]
        duration = _DURATION.search(text)
        if duration:
            end = start + timedelta(days=int(duration.group(1)) - 1)
    return start, end


def rule_extract(text: str, msg_dt: datetime) -> dict:
    """규칙만으로 만든 항목 한 건. Gemini 결과가 없을 때의 폴백."""
    kind = detect_kind(text) or "휴가"
    start, end = extract_dates(text, msg_dt)
    return {
        "kind": kind,
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "needs_review": start is None,
        "engine": "rule",
    }
