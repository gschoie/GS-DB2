# -*- coding: utf-8 -*-
"""발표 지표의 **직전치** 수집.

왜 필요한가: 달력에 지표 **이름만** 있으면 쓸모가 없다. "CPI 발표"가 아니라
"직전 +0.2%(전월) · +3.4%(전년)" 처럼 숫자가 옆에 있어야 발표값을 보고 놀랄 수 있다.

**소스 두 갈래** (`release.src`)
  · `bls`(기본) — **키가 필요 없다**. 물가(CPI·PPI)·고용·임금을 여기서 받는다.
    v1 한도는 **IP당 25회/일 · 요청당 50계열 · 10년** 이라 계열마다 부르면 한도에
    걸린다 → **전 지표를 한 번의 호출로** 받는다.
  · `fred` — `FRED_API_KEY` 가 있을 때만. 소매판매·PCE·GDP·정책금리·한국 지표처럼
    BLS 소관이 아닌 것들. 키가 없으면 그 줄만 빠지고 화면에 '–' 로 남는다.

러너에서 뭐가 막히고 뭐가 되는지 (실측 2026-10-11, 프로브)
  · **`fred.stlouisfed.org`(그래프·CSV 호스트)는 막혔다** — 0.05초 만에
    `HTTP/2 INTERNAL_ERROR`. 그래서 '키 없이 CSV 로 받는' 우회는 안 된다.
  · **`api.stlouisfed.org`(키 경로)는 열려 있다** — 가짜 키로 부르면 "키 형식이
    틀렸다"는 400 이 정상적으로 온다. 즉 **FRED 키를 등록하면 이 경로는 쓸 수 있다.**
    두 호스트를 뭉떵그려 'FRED 는 안 된다'고 적으면 안 되는 이유.
  · Census(소매판매)는 키를 요구하고(`Missing Key`), BEA 는 타임아웃이다.
  · 파이썬 `urlopen(timeout=)` 은 앞의 차단을 **타임아웃으로 못 잡는다**(소켓 1회
    작업 기준이라 응답이 느리게 흘러오면 안 걸린다) — 1차 프로브가 15분을 매달렸다.

없는 것은 없다고 적는다
  · **ISM** — ISM 이 재배포를 막아 무료 경로가 아예 없다(키를 넣어도 안 된다).
  · **컨센서스** — 무료 API 가 없다. `consensus.json` 에 있을 때만 표시한다.
  이들은 화면에서 '–' 로 남는다. 숫자를 지어내지 않는다.

소스가 또 막히면: `macro_desk/tests/probe_release_sources.py` 를 러너에서 돌려 확인.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BLS_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
CONSENSUS = HERE / "consensus.json"
UA = {"User-Agent": "gs-research-desk/macro", "Content-Type": "application/json"}


# ── BLS 관측치 ──────────────────────────────────────────────────────────────
def _bls_date(year: str, period: str) -> dt.date | None:
    """BLS 기간 표기 → 날짜. M01~M12(월) · Q01~Q04(분기) · A01(연간)."""
    y = int(year)
    kind, num = period[0], period[1:]
    if kind == "M" and num.isdigit() and 1 <= int(num) <= 12:
        return dt.date(y, int(num), 1)
    if kind == "Q" and num.isdigit() and 1 <= int(num) <= 4:
        return dt.date(y, (int(num) - 1) * 3 + 1, 1)
    if kind == "A":
        return dt.date(y, 1, 1)
    return None                       # M13(연평균) 등은 버린다


def bls_observations(series: list[str], years: int = 3,
                     timeout: int = 25) -> dict[str, list[tuple[dt.date, float]]]:
    """계열 여러 개를 **한 번의 호출로** 받아 {계열: [(날짜, 값)] 오름차순}.

    결측('-', 2025년 예산 공백 등)은 버린다 — 전년동월비를 못 만드는 구간이 생기지만
    빈 값을 0 으로 읽는 것보다 낫다(없는 건 없는 것으로 둔다).
    """
    import urllib.request          # 지연 import (렌더 모드는 네트워크 없이 돈다)

    this_year = dt.date.today().year
    body = json.dumps({"seriesid": series, "startyear": str(this_year - years),
                       "endyear": str(this_year)}).encode()
    req = urllib.request.Request(BLS_URL, data=body, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        j = json.loads(r.read().decode("utf-8", "replace"))

    if j.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS 응답 실패: {j.get('status')} {j.get('message')}")

    out: dict[str, list[tuple[dt.date, float]]] = {}
    for s in j.get("Results", {}).get("series", []):
        rows = []
        for d in s.get("data", []):
            if d.get("value") in ("-", "", None):
                continue
            day = _bls_date(d.get("year", ""), d.get("period", ""))
            if day is None:
                continue
            try:
                rows.append((day, float(d["value"])))
            except ValueError:
                continue
        out[s["seriesID"]] = sorted(rows)
    return out


def fred_observations(series: str, key: str, years: int = 4,
                     timeout: int = 20) -> list[tuple[dt.date, float]]:
    """FRED 한 계열 → [(날짜, 값)] 오름차순. **키 경로(api.stlouisfed.org)** 를 쓴다."""
    import urllib.parse
    import urllib.request

    start = (dt.date.today() - dt.timedelta(days=365 * years + 40)).isoformat()
    q = urllib.parse.urlencode({"series_id": series, "api_key": key,
                                "file_type": "json", "observation_start": start})
    req = urllib.request.Request(f"{FRED_URL}?{q}",
                                 headers={"User-Agent": UA["User-Agent"]})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        j = json.loads(r.read().decode("utf-8", "replace"))

    rows = []
    for o in j.get("observations", []):
        if o.get("value") in (".", "", None):
            continue
        try:
            rows.append((dt.date.fromisoformat(o["date"]), float(o["value"])))
        except (ValueError, KeyError):
            continue
    if not rows:
        raise ValueError("관측치 없음")
    return sorted(rows)


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


# 계열이 폐기되면 **API 는 조용히 옛 값을 계속 내준다.** 한국 CPI(KORCPIALLMINMEI)가
# OECD MEI 폐기로 2023-11 에 멈췄는데 화면에는 "직전 발표: 2023년 11월 전년 +3.3%" 가
# 멀쩡히 찍혔다 — 3년 전 숫자를 어제 것처럼 보여주는 게 빈칸보다 훨씬 나쁘다.
# 그래서 마지막 관측이 너무 오래됐으면 **버린다**(30번 교훈과 같은 부류).
STALE_DAYS = {"m": 130, "q": 230, "d": 35}


def is_stale(obs: list[tuple[dt.date, float]], spec: dict,
             today: dt.date | None = None) -> bool:
    """마지막 관측이 그 주기로는 설명이 안 될 만큼 오래됐나."""
    limit = spec.get("stale_days") or STALE_DAYS.get(spec.get("freq", "m"), 130)
    today = today or dt.date.today()
    return (today - obs[-1][0]).days > limit


def _period_label(d: dt.date, freq: str) -> str:
    """관측 기간 라벨. d 는 **대상 기간**이지 발표일이 아니다.

    월간은 `8월분` 처럼 **'분'을 붙인다** — 그냥 '8월' 로 두면 "8월에 발표된"
    으로 읽힌다(실제로 그렇게 읽혔다). 8월분 CPI·PPI 의 발표는 9월 중순이다.
    분기는 '3분기' 만으로도 대상 기간으로 읽히므로 그대로 둔다.
    """
    if freq == "q":
        return f"{d.year}년 {(d.month - 1) // 3 + 1}분기"
    if freq == "d":
        return d.isoformat()
    return f"{d.year}년 {d.month}월분"


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
        yoy = _pct(last_v, _pick_back(obs, 12))
        # 라벨은 YoY/MoM(분기는 QoQ). '전년'·'전월' 은 **무엇 대비인지는 맞지만
        # 무엇을 재는지는 안 말한다** — 숫자만 보고 "지난달 값"으로 읽기 쉽다.
        if kind in ("yoy", "yoy_mom") and yoy is not None:
            parts.append(f"YoY {yoy:+.1f}%")
        if kind in ("mom", "yoy_mom") and mom is not None:
            parts.append(f"{'QoQ' if freq == 'q' else 'MoM'} {mom:+.1f}%")
        for i in range(max(1, len(obs) - 3), len(obs)):
            r = (_pct(obs[i][1], _pick_back(obs[:i + 1], 12)) if kind == "yoy"
                 else _pct(obs[i][1], obs[i - 1][1]))
            if r is not None:
                recent.append(f"{r:+.1f}")
        # 변화율을 못 구하면 **'–' 로 둔다.** 지수 계열의 원값을 대신 찍으면
        # '코어 337.8' 처럼 증가율 자리에 지수 레벨이 앉아 완전히 다른 뜻이 된다
        # (실측으로 잡힌 버그). 모르는 건 모른다고 적는다.

    return {"period": _period_label(last_d, freq),
            "period_iso": last_d.isoformat(),
            "text": " · ".join(parts) or "–",
            "recent": recent,
            "series": spec.get("series", ""),
            "unit_note": spec.get("unit_note", "")}


# ── 수집 ───────────────────────────────────────────────────────────────────
def _specs(entries: list[dict]) -> list[tuple[str, dict, dict | None]]:
    """[(지표id, 주 spec, 부 spec)] — `also` 는 한 줄에 같이 적을 보조 계열
    (고용보고서의 실업률처럼 '취업자 +2.9만명 · 실업률 4.2%' 로 붙는다)."""
    out = []
    for e in entries:
        spec = e.get("release") or {}
        if spec.get("series"):
            out.append((e["id"], spec, spec.get("also")))
    return out


def fetch(entries: list[dict], fred_key: str = "") -> dict:
    """config.yml calendar 목록 → {지표id: 직전치}.

    BLS 는 **한 번의 호출로** 전 계열을 받는다(하루 25회 한도). FRED 는 키가 있을
    때만 계열별로 받는다. 어느 쪽이 실패해도 그 지표만 빠지고 나머지는 저장된다 —
    직전치가 없는 건 화면에서 '–' 일 뿐, 수집 실패가 아니다.
    """
    specs = _specs(entries)
    if not specs:
        return {}

    def src(s: dict) -> str:
        return s.get("src", "bls")

    # BLS — 주·보조 계열을 모아 한 번에
    bls_ids = sorted({s["series"] for _, main, also in specs
                      for s in ([main] + ([also] if also else []))
                      if src(s) == "bls"})
    bls: dict[str, list] = {}
    if bls_ids:
        try:
            bls = bls_observations(bls_ids)
            print(f"  BLS {len(bls)}/{len(bls_ids)} 계열")
        except Exception as ex:
            print(f"  ERR BLS 호출 실패 — {type(ex).__name__}: {str(ex)[:120]}")

    fred_cache: dict[str, list] = {}

    def rows_for(s: dict) -> list:
        if src(s) == "bls":
            return bls.get(s["series"]) or []
        if not fred_key:
            return []
        if s["series"] not in fred_cache:
            try:
                fred_cache[s["series"]] = fred_observations(s["series"], fred_key)
            except Exception as ex:
                print(f"  ERR FRED {s['series']} — {type(ex).__name__}: {str(ex)[:60]}")
                fred_cache[s["series"]] = []
        return fred_cache[s["series"]]

    out = {}
    for ind_id, main, also in specs:
        rows = rows_for(main)
        if not rows:
            print(f"  --  {ind_id:<14} {main['series']} 직전치 없음"
                  f"{' (FRED 키 필요)' if src(main) == 'fred' and not fred_key else ''}")
            continue
        if is_stale(rows, main):
            print(f"  ✗   {ind_id:<14} {main['series']} 계열이 멈췄다 "
                  f"(마지막 관측 {rows[-1][0]}) — 폐기된 계열로 보고 버린다")
            continue
        got = summarize(rows, main)
        if also:
            extra = rows_for(also)
            if extra and not is_stale(extra, also):
                sub = summarize(extra, also)
                if sub["text"] != "–":          # '코어 –' 는 붙이지 않는다
                    label = also.get("label", "")
                    got["text"] += f' · {label}{" " if label else ""}{sub["text"]}'
        out[ind_id] = got
        print(f"  OK  {ind_id:<14} {got['period']} {got['text']}")
    return out


def load_consensus() -> dict:
    """{'us_cpi': {'text': '전년 +3.7% 예상', 'asof': '2026-10-10'}} — 없으면 빈 dict.

    무료 컨센서스 API 가 없어 **사람이(또는 세션이 웹서치로) 채우는 파일**이다.
    비어 있으면 화면에 '–' 로 정직하게 나온다.
    """
    if not CONSENSUS.exists():
        return {}
    try:
        return json.loads(CONSENSUS.read_text(encoding="utf-8")).get("items", {})
    except Exception:
        return {}
