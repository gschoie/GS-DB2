# -*- coding: utf-8 -*-
"""발표일 계산 — 규칙으로 뽑는 날짜와, 기관이 공표해야만 아는 날짜를 나눈다.

왜 둘로 나누나: CPI·고용·ISM 같은 건 '매월 몇 번째 무슨 요일'이 거의 고정이라
규칙으로 뽑아도 맞는다. 반면 **FOMC·금통위는 규칙이 없다** — 기관이 연간 일정을
따로 공표한다. 그걸 추측해서 달력에 박으면 틀린 날짜를 사실처럼 보여주게 되므로,
`fixed: true` 인 항목은 `fixed_dates.json`(러너가 공식 페이지에서 받아 캐시)에
있을 때만 표시하고, 없으면 '일정 미확인'으로 남긴다.

규칙으로 뽑은 날짜는 화면에 `~`를 붙여 **확정일이 아님을 표시**한다.
"""
from __future__ import annotations

import calendar as _cal
import datetime as dt
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXED = HERE / "fixed_dates.json"

WD = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def nth_weekday(year: int, month: int, n: int, weekday: int) -> dt.date:
    """n번째 해당 요일. n<0 이면 뒤에서 센다(-1 = 마지막)."""
    days = [d for d in _month_days(year, month) if d.weekday() == weekday]
    if not days:
        raise ValueError(f"{year}-{month}에 요일 {weekday}이 없다")
    return days[n - 1] if n > 0 else days[n]


def nth_bizday(year: int, month: int, n: int) -> dt.date:
    """n번째 영업일. 공휴일은 모르고 **주말만** 제외한다(그래서 추정치다)."""
    biz = [d for d in _month_days(year, month) if d.weekday() < 5]
    if n > len(biz):
        return biz[-1]
    return biz[n - 1]


def on_day(year: int, month: int, day: int) -> dt.date:
    """매월 n일. 주말이면 다음 영업일로 민다.

    단 **그 달을 넘어가면 안 된다** — 월말이 토요일이면 앞으로 미는 순간 다음 달이
    되어 그 달 달력에서 사라진다(2026-02-28이 토요일). 그런 경우엔 뒤로 당긴다.
    """
    last = _cal.monthrange(year, month)[1]
    d = dt.date(year, month, min(day, last))
    while d.weekday() >= 5:
        nxt = d + dt.timedelta(days=1)
        if nxt.month != month:
            while d.weekday() >= 5:          # 월을 넘기느니 직전 영업일로
                d -= dt.timedelta(days=1)
            return d
        d = nxt
    return d


def _month_days(year: int, month: int) -> list[dt.date]:
    last = _cal.monthrange(year, month)[1]
    return [dt.date(year, month, i) for i in range(1, last + 1)]


def load_fixed() -> dict[str, list[str]]:
    """{'fomc': ['2026-01-28', …], 'bok': [...]} — 없으면 빈 dict."""
    if not FIXED.exists():
        return {}
    try:
        return json.loads(FIXED.read_text(encoding="utf-8")).get("dates", {})
    except Exception:
        return {}


def resolve(entry: dict, year: int, month: int, fixed: dict | None = None) -> list[dict]:
    """config.yml 의 calendar 한 줄 → 그 달의 발표 일정 목록.

    반환: [{date, estimated, name, id, country, time, guide}] — 없으면 빈 목록.
    estimated=True 면 규칙으로 뽑은 추정일(화면에 ~ 표시).
    """
    months = entry.get("months")
    if months and month not in months:
        return []

    base = {"id": entry["id"], "name": entry["name"],
            "country": entry.get("country", ""), "time": entry.get("time", ""),
            "guide": entry.get("guide", "")}

    if entry.get("fixed"):
        got = (fixed if fixed is not None else load_fixed()).get(entry["id"], [])
        out = []
        for s in got:
            try:
                d = dt.date.fromisoformat(s)
            except ValueError:
                continue
            if (d.year, d.month) == (year, month):
                out.append({**base, "date": d, "estimated": False})
        return out

    rule = entry.get("rule") or {}
    try:
        if "nth_weekday" in rule:
            n, wd = rule["nth_weekday"]
            d = nth_weekday(year, month, int(n), WD[str(wd).lower()])
        elif "nth_bizday" in rule:
            d = nth_bizday(year, month, int(rule["nth_bizday"]))
        elif "day" in rule:
            d = on_day(year, month, int(rule["day"]))
        elif "around" in rule:
            d = on_day(year, month, int(rule["around"]))
        else:
            return []
    except (ValueError, KeyError):
        return []
    # around 는 '그 날짜 전후'라는 뜻이라 규칙 중에서도 특히 느슨하다
    return [{**base, "date": d, "estimated": True, "loose": "around" in rule}]


def month_events(entries: list[dict], year: int, month: int,
                 fixed: dict | None = None) -> list[dict]:
    """한 달치 전체 일정(날짜 오름차순)."""
    fixed = load_fixed() if fixed is None else fixed
    out = []
    for e in entries:
        out.extend(resolve(e, year, month, fixed))
    return sorted(out, key=lambda x: (x["date"], x["name"]))
