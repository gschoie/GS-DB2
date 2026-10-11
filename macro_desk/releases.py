# -*- coding: utf-8 -*-
"""발표 지표의 **직전치** 수집 — FRED 키 없는 CSV 엔드포인트.

왜 이게 필요한가: 달력에 지표 **이름만** 있으면 쓸모가 없다. "CPI 발표"가 아니라
"직전 +0.2%(전월) · +3.0%(전년)" 처럼 숫자가 옆에 있어야 발표값을 보고 놀랄 수 있다.

왜 키 없는 CSV 인가: `api.stlouisfed.org` 는 `FRED_API_KEY` 가 필요한데 아직 없다.
`fred.stlouisfed.org/graph/fredgraph.csv?id=…` 는 키 없이 열리는 공개 경로라
**키 등록 없이도 직전치가 채워진다**. 키를 넣으면 시세판 쪽(collect.fetch_fred)이
따로 풍부해지는 것이고 여기와는 무관하다.

없는 것은 없다고 적는다
  · **ISM 은 소스가 없다** — ISM 이 2022년 FRED 재배포를 중단시켜 NAPM 계열이 죽었다.
    유료 외엔 경로가 없어 `release` 를 안 달고 '직전치 없음'으로 남긴다.
  · **컨센서스는 무료 API 가 없다** — Investing·TradingEconomics 는 유료/차단.
    `consensus.json`(수동·세션 입력) 에 있을 때만 표시한다.

계열이 또 죽으면: `macro_desk/tests/probe_fred_csv.py` 를 러너에서 돌려 생존 확인.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
CONSENSUS = HERE / "consensus.json"
UA = {"User-Agent": "gs-research-desk/macro"}


# ── 관측치 받기 ─────────────────────────────────────────────────────────────
def observations(series: str, timeout: int = 25) -> list[tuple[dt.date, float]]:
    """[(날짜, 값)] 오름차순. 결측('.')은 버린다."""
    import urllib.request          # 지연 import (렌더 모드는 네트워크 없이 돈다)

    req = urllib.request.Request(CSV_URL.format(series), headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", "replace")

    out = []
    for row in csv.reader(io.StringIO(body)):
        if len(row) < 2:
            continue
        try:
            d = dt.date.fromisoformat(row[0].strip())
            v = float(row[1].strip())
        except ValueError:
            continue                # 헤더·결측
        out.append((d, v))
    if not out:
        raise ValueError("관측치 없음")
    return out


# ── 변환 ───────────────────────────────────────────────────────────────────
def _pick_back(obs: list[tuple[dt.date, float]], months: int) -> float | None:
    """마지막 관측에서 months 개월 앞선 관측값. **날짜로** 찾는다 —
    월간·분기 계열이 섞여 있어 '13번째 뒤' 같은 인덱스 셈은 틀린다."""
    last_d = obs[-1][0]
    y, m = last_d.year, last_d.month - months
    while m <= 0:
        y, m = y - 1, m + 12
    want = (y, m)
    for d, v in reversed(obs):
        if (d.year, d.month) == want:
            return v
    return None


def _pct(cur: float, prev: float | None) -> float | None:
    if prev in (None, 0):
        return None
    return (cur - prev) / abs(prev) * 100


def _period_label(d: dt.date, freq: str) -> str:
    if freq == "q":
        return f"{d.year}년 {(d.month - 1) // 3 + 1}분기"
    if freq == "d":
        return d.isoformat()
    return f"{d.year}년 {d.month}월"


def summarize(obs: list[tuple[dt.date, float]], spec: dict) -> dict:
    """계열 관측치 → 화면에 쓸 직전치 한 덩어리.

    kind: level(값 그대로) / mom(전월비%) / yoy(전년동월비%) / yoy_mom(둘 다)
          / diff(전월 대비 증감, scale 로 단위 환산)
    """
    kind = spec.get("kind", "level")
    freq = spec.get("freq", "m")
    unit = spec.get("unit", "")
    last_d, last_v = obs[-1]
    parts: list[str] = []
    recent: list[str] = []

    if kind == "level":
        parts.append(f"{last_v:,.{spec.get('digits', 1)}f}{unit}")
        for d, v in obs[-3:]:
            recent.append(f"{v:,.{spec.get('digits', 1)}f}")

    elif kind == "diff":
        scale = float(spec.get("scale", 1))
        prev = obs[-2][1] if len(obs) >= 2 else None
        if prev is not None:
            parts.append(f"{(last_v - prev) / scale:+,.1f}{unit}")
        for i in range(max(0, len(obs) - 3), len(obs)):
            if i == 0:
                continue
            recent.append(f"{(obs[i][1] - obs[i - 1][1]) / scale:+,.1f}")

    else:
        mom = _pct(last_v, obs[-2][1] if len(obs) >= 2 else None)
        yoy = _pct(last_v, _pick_back(obs, 12 if freq == "m" else 12))
        if kind in ("yoy", "yoy_mom") and yoy is not None:
            parts.append(f"전년 {yoy:+.1f}%")
        if kind in ("mom", "yoy_mom") and mom is not None:
            parts.append(f"전{'기' if freq == 'q' else '월'} {mom:+.1f}%")
        key = yoy if kind == "yoy" else mom
        for i in range(max(1, len(obs) - 3), len(obs)):
            r = (_pct(obs[i][1], _pick_back(obs[:i + 1], 12)) if kind == "yoy"
                 else _pct(obs[i][1], obs[i - 1][1]))
            if r is not None:
                recent.append(f"{r:+.1f}")
        if key is None and not parts:
            parts.append(f"{last_v:,.1f}")

    return {"period": _period_label(last_d, freq),
            "period_iso": last_d.isoformat(),
            "text": " · ".join(parts) or "–",
            "recent": recent,
            "series": spec.get("series", ""),
            "unit_note": spec.get("unit_note", "")}


# ── 수집 ───────────────────────────────────────────────────────────────────
def fetch(entries: list[dict]) -> dict:
    """config.yml calendar 목록 → {지표id: 직전치}. 실패한 계열은 빠진다."""
    out = {}
    for e in entries:
        spec = e.get("release")
        if not spec or not spec.get("series"):
            continue
        try:
            obs = observations(spec["series"])
            out[e["id"]] = summarize(obs, spec)
            print(f"  OK  {e['name']:<20} {out[e['id']]['period']} {out[e['id']]['text']}")
        except Exception as ex:
            print(f"  ERR {e['name']:<20} {spec['series']} {type(ex).__name__}: {str(ex)[:50]}")
    return out


def load_consensus() -> dict:
    """{'us_cpi': {'text': '전년 +3.1% 예상', 'asof': '2026-10-10'}} — 없으면 빈 dict.

    무료 컨센서스 API 가 없어 **사람이(또는 세션이 웹서치로) 채우는 파일**이다.
    비어 있으면 화면에 '컨센 없음'으로 정직하게 나온다.
    """
    if not CONSENSUS.exists():
        return {}
    try:
        return json.loads(CONSENSUS.read_text(encoding="utf-8")).get("items", {})
    except Exception:
        return {}
