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
    # 행사 참석형 출장 — '출장'이란 말 없이 행사명만 말하는 보고
    # ("포스코인터 밸류데이 11.24-11.27"). 컨퍼런스 콜(컨콜)은 자리 비움이 아니다.
    # NDR은 뺐다(10/27) — 시내 일과라 자리 비움이 아니고, 배차 문자에 섞여 오탐만 냈다.
    (r"[밸벨]류데이", "출장"),
    (r"사이트비짓|(?i:sitevisit)", "출장"),
    (r"컨퍼런스(?!콜)", "출장"),
    (r"기업탐방|탐방", "탐방"),
    (r"[샵숍]\s*투어", "샵투어"),
    (r"여행", "여행"),
    (r"휴무", "휴무"),
    (r"오프", "오프"),
    (r"휴가", "휴가"),
]

_KIND_RES = [(re.compile(pattern), label) for pattern, label in KIND_PATTERNS]

# 잡담 오탐 컷: 휴가 단어가 있어도 남 얘기·과거 회상·질문이면 보고가 아니다.
# 과하게 거르면 놓치므로 확실한 것만 — 나머지는 Gemini 또는 needs_review가 받는다.
# 배차·차량·기사 안내문(Web발신 전달)은 일정 공지이지 자리 비움 보고가 아니다
# — 10/27 실사례: NDR 배차 문자가 '출장'으로 잡혔다.
_NEGATIVE_RE = re.compile(r"휴가철|휴가지\s*추천|휴가\s*어땠|휴가\s*잘\s*다녀|휴가\s*는\s*어디"
                          r"|여행\s*가고\s*싶|여행\s*어땠|여행\s*잘\s*다녀|여행지\s*추천|여행사"
                          r"|(?i:web)발신|배차|담당\s*기사|운전\s*기사")


# 키워드 판별용 압축: 글자 사이 공백·점을 걷어낸다 — "휴 가"·"휴.가"도 휴가로.
# 날짜 파싱은 원문을 쓰므로 "9.14" 같은 표기는 영향 없다.
_SEP_RE = re.compile(r"[\s.·・]+")


def _compact(text: str) -> str:
    return _SEP_RE.sub("", text or "")


def detect_kind(text: str) -> str | None:
    """휴가 종류 단어를 찾는다(공백·점 무시). 없으면 None — 후보 아님."""
    compacted = _compact(text)
    for pattern, label in _KIND_RES:
        if pattern.search(compacted):
            return label
    return None


def is_candidate(text: str) -> bool:
    """휴가 보고 '후보' 메시지인지. 넓게 잡고, 정밀 판정은 다음 단계가 한다."""
    if not text or not text.strip():
        return False
    if _NEGATIVE_RE.search(_compact(text)):
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
_DATE_LIST = re.compile(
    r"(?:(\d{4})\s*[년./-]\s*)?(\d{1,2})\s*[월/.]\s*(\d{1,2})\s*일?((?:\s*,\s*\d{1,2}){1,10})"
)
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


def _group_spans(dates: list[date]) -> list[tuple[date, date]]:
    """날짜 목록을 연속 구간으로 묶는다 — 14,15,16은 한 구간, 13과 20은 두 구간."""
    spans: list[list[date]] = []
    for d in sorted(set(dates)):
        if spans and (d - spans[-1][1]).days == 1:
            spans[-1][1] = d
        else:
            spans.append([d, d])
    return [(a, b) for a, b in spans]


# 두 날짜 토큰 '사이' 글에 이게 있으면 구간, 쉼표·나열이면 떨어진 날짜들이다.
_RANGE_SEP = re.compile(r"[-~〜∼–—]|부터|에서|까지")
_LIST_SEP = re.compile(r"[,，]|이랑|랑|하고|및|그리고")


def extract_periods(text: str, base: datetime) -> list[tuple[date, date]]:
    """본문에서 자리 비움 기간들을 추정한다. 실패하면 [] — needs_review 행이 된다.

    "9/15-9/18"·"8/31부터 3일간"은 한 구간, "11/13, 11/20 휴가"처럼 쉼표로 나열된
    떨어진 날짜는 **건마다 따로**(11/6 실사례: 폴백이 11/11~11/13 구간으로 오독).
    연속 날짜 나열("9/14,15,16")은 한 구간으로 묶는다.
    """
    base_date = base.astimezone(KST).date() if base.tzinfo else base.date()

    found: list[tuple[int, int, date, str]] = []  # (start, end, date, 종류)

    for match in _DATE_TOKEN.finditer(text):
        resolved = _resolve_md(match.group(1), int(match.group(2)), int(match.group(3)), base_date)
        if resolved:
            found.append((match.start(), match.end(), resolved, "md"))
    for match in _REL_TOKEN.finditer(text):
        found.append((match.start(), match.end(),
                      base_date + timedelta(days=_REL_DAYS[match.group(0)]), "rel"))
    for match in _WEEKDAY_TOKEN.finditer(text):
        found.append((match.start(), match.end(),
                      _resolve_weekday(match.group(1), match.group(2), base_date), "weekday"))

    # "9/14,15,16"·"9월 14, 15, 16일" 같은 같은 달 나열 — 완전한 날짜 토큰이 하나뿐일 때만
    # 쓴다("11/13, 11/20"도 나열 정규식에 걸리지만 '11'은 날이 아니라 다음 날짜의 월이다).
    if len(found) < 2:
        listing = _DATE_LIST.search(text)
        if listing:
            month = int(listing.group(2))
            days = [int(listing.group(3))] + \
                [int(d) for d in re.findall(r"\d{1,2}", listing.group(4))]
            resolved = [_resolve_md(listing.group(1), month, day, base_date) for day in days]
            resolved = [d for d in resolved if d]
            if len(resolved) >= 2:
                return _group_spans(resolved)

    if not found:
        return []
    found.sort(key=lambda item: item[0])

    if len(found) >= 2:
        # 토큰 사이 글로 구간/나열을 가른다 — 쉼표류가 있고 구간 표지가 없으면 떨어진 날짜들.
        seps = [text[found[k][1]:found[k + 1][0]] for k in range(len(found) - 1)]
        if any(_LIST_SEP.search(s) for s in seps) and not any(_RANGE_SEP.search(s) for s in seps):
            return _group_spans([f[2] for f in found])
        start, end = found[0][2], found[1][2]
        if end < start:
            if found[1][3] == "weekday":
                # "다음주 수요일부터 금요일까지" — 뒤쪽 맨요일은 시작일과 같은 주다.
                while end < start:
                    end += timedelta(days=7)
            else:
                start, end = end, start
        return [(start, end)]

    start = end = found[0][2]
    duration = _DURATION.search(text)
    if duration:
        end = start + timedelta(days=int(duration.group(1)) - 1)
    return [(start, end)]


def extract_dates(text: str, base: datetime) -> tuple[date | None, date | None]:
    """기존 단건 호환 — 첫 기간만 돌려준다. 다건은 extract_periods/rule_extract_all."""
    periods = extract_periods(text, base)
    return periods[0] if periods else (None, None)


def rule_extract_all(text: str, msg_dt: datetime) -> list[dict]:
    """규칙만으로 만든 항목들. 떨어진 날짜 나열이면 여러 건, 못 읽으면 needs_review 한 건."""
    kind = detect_kind(text) or "휴가"
    periods = extract_periods(text, msg_dt)
    if not periods:
        return [{"kind": kind, "start": None, "end": None,
                 "needs_review": True, "engine": "rule"}]
    return [{"kind": kind, "start": s.isoformat(), "end": e.isoformat(),
             "needs_review": False, "engine": "rule"} for s, e in periods]


def rule_extract(text: str, msg_dt: datetime) -> dict:
    """단건 호환 폴백 — 첫 건만. 다건 소비는 rule_extract_all."""
    return rule_extract_all(text, msg_dt)[0]


# ── 대화 맥락 후보 선별 ────────────────────────────────────────────────────
# "출장 언제야?"(내 질문) → "9/15화-9/18금 입니당"(친구 답)처럼 키워드와 날짜가
# 다른 메시지에 갈라져 있는 경우를 잡는다. 키워드 등장 후 window개(기본 10)·hours시간 안의
# 날짜 있는 친구 메시지를 맥락 후보로 삼는다.

def has_date(text: str) -> bool:
    """본문에 날짜로 읽을 만한 토큰이 있는지."""
    return bool(_DATE_TOKEN.search(text) or _REL_TOKEN.search(text)
                or _WEEKDAY_TOKEN.search(text))


def pick_candidates(messages: list[dict], window: int = 10, hours: float = 12.0,
                    allow_own: bool = False) -> list[dict]:
    """시간순 메시지에서 후보를 고른다.

    messages: [{"out": bool, "text": str, "dt": datetime}, ...] (시간순)
    반환: [{"index", "trigger": "keyword"|"context", "kind_hint"}]
      - keyword: 친구 메시지에 휴가·출장 키워드가 직접 있음
      - context: 직전 window개·hours시간 안에 (누구든) 키워드를 말했고,
                 친구가 날짜가 든 메시지로 답함
    내(out) 메시지는 기본적으로 후보가 되지 않고 맥락(키워드 트리거)으로만 쓰이며,
    allow_own=True면 내 메시지도 후보가 된다(그 대화 상대의 일정을 내가 대신 적는 관행).
    """
    picked: list[dict] = []
    last_kw: tuple[int, object, str] | None = None  # (index, dt, kind)
    for index, msg in enumerate(messages):
        text = (msg.get("text") or "").strip()
        if not text:
            continue
        kind = None if _NEGATIVE_RE.search(_compact(text)) else detect_kind(text)
        if kind:
            last_kw = (index, msg["dt"], kind)
        if msg.get("out") and not allow_own:
            continue
        if kind:
            # '여행'은 잡담이 흔해서 같은 메시지에 날짜가 있을 때만 직접 후보로.
            # (키워드 트리거로는 남으니, 이어지는 날짜 답변은 맥락으로 잡힌다.)
            if kind == "여행" and not has_date(text):
                continue
            picked.append({"index": index, "trigger": "keyword", "kind_hint": kind})
        elif (last_kw and (index - last_kw[0]) <= window
              and (msg["dt"] - last_kw[1]).total_seconds() <= hours * 3600
              and has_date(text)):
            picked.append({"index": index, "trigger": "context", "kind_hint": last_kw[2]})
    return picked
