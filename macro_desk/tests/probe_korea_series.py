# -*- coding: utf-8 -*-
"""러너 전용 — 한국 지표 FRED 계열 중 **아직 살아 있는 것** 찾기.

왜: `KORCPIALLMINMEI`(한국 CPI)가 OECD MEI 폐기로 **2023-11 에 멈췄는데** API 는
조용히 그 옛 값을 계속 내줬다. 화면에 "직전 발표: 2023년 11월" 이 멀쩡히 찍혔다.
폐기된 계열은 에러를 주지 않으므로 **마지막 관측 날짜로만** 가릴 수 있다.

사용: FRED_API_KEY 를 주고 러너에서 실행.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import releases as rl  # noqa: E402

CANDIDATES = [
    # 한국 소비자물가
    ("KORCPIALLMINMEI", "한국 CPI(MEI 지수) — 폐기 의심"),
    ("CPALTT01KRM659N", "한국 CPI 전년동월비(%)"),
    ("CPALTT01KRM657N", "한국 CPI 전월비(%)"),
    ("CPALTT01KRM661N", "한국 CPI 지수"),
    ("KORCPALTT01IXNBM", "한국 CPI 지수(IXNB)"),
    ("KORCPALTT01GYM", "한국 CPI 전년동월비(GY)"),
    # 한국 고용·생산·수출
    ("LRHUTTTTKRM156S", "한국 실업률(%)"),
    ("KORPROINDMISMEI", "한국 산업생산(MEI)"),
    ("XTEXVA01KRM667S", "한국 수출(지수)"),
    ("XTEXVA01KRM664N", "한국 수출(통화)"),
    ("KORXTEXVA01CXMLSAM", "한국 수출(CXML)"),
    # 한국 GDP·금리
    ("NAEXKP01KRQ657S", "한국 GDP 전기비(%)"),
    ("NAEXKP01KRQ652S", "한국 GDP 실질(지수)"),
    ("IR3TIB01KRM156N", "한국 3개월 금리(%)"),
    ("IRLTLT01KRM156N", "한국 장기국채 금리(%)"),
    ("INTDSRKRM193N", "한국 재할인율(%)"),
]

FRED = "https://api.stlouisfed.org/fred/series/observations"


def last(series: str, key: str):
    q = urllib.parse.urlencode({"series_id": series, "api_key": key,
                                "file_type": "json",
                                "observation_start": "2022-01-01"})
    req = urllib.request.Request(f"{FRED}?{q}",
                                 headers={"User-Agent": "gs-research-desk/macro"})
    with urllib.request.urlopen(req, timeout=20) as r:
        j = json.loads(r.read().decode("utf-8", "replace"))
    vals = [(o["date"], o["value"]) for o in j.get("observations", [])
            if o.get("value") not in (".", "", None)]
    if not vals:
        raise ValueError("관측치 없음")
    return vals[-2:]


def main() -> None:
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        raise SystemExit("FRED_API_KEY 가 없다")
    today = dt.date.today()
    live = []
    for sid, label in CANDIDATES:
        try:
            got = last(sid, key)
            age = (today - dt.date.fromisoformat(got[-1][0])).days
            tag = "LIVE" if age <= 130 else f"STALE({age}일)"
            if age <= 130:
                live.append(sid)
            print(f"  {tag:<14} {sid:<20} {label:<26} "
                  + " | ".join(f"{d} {v}" for d, v in got))
        except Exception as e:
            print(f"  {'DEAD':<14} {sid:<20} {label:<26} "
                  f"{type(e).__name__}: {str(e)[:60]}")
    print(f"\n살아있는 계열 {len(live)}개: {' '.join(live)}")
    print(f"(판정 기준은 releases.STALE_DAYS = {rl.STALE_DAYS})")


if __name__ == "__main__":
    main()
