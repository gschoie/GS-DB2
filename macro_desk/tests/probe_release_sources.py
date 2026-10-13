# -*- coding: utf-8 -*-
"""러너 전용 탐색 — 발표 지표 '직전치'를 **키 없이** 받을 수 있는 곳 찾기.

1차·2차 프로브 결론
  · **FRED 는 러너에서 아예 안 된다** — `fred.stlouisfed.org/graph/fredgraph.csv` 가
    0.05초 만에 `curl (92) HTTP/2 stream was not closed cleanly: INTERNAL_ERROR`.
    키가 있든 없든 소용없는 네트워크 단 차단이다(텔레그램·유튜브가 러너 IP 를 막는
    것과 같은 부류). 파이썬 urlopen 은 이걸 timeout 으로 잡지 못해 15분을 매달렸다.
  · **BLS 공개 API v1 은 키 없이 된다** — CPI 지수가 그대로 왔다.
    v1 은 IP당 하루 25회·요청당 50계열·10년 — 하루 한 번이면 **한 번의 호출로 충분**.

이 3차 프로브가 가리는 것
  ① BLS 계열 ID 7개가 전부 유효한가(물가·고용·임금)
  ② Census MARTS(소매판매)는 302 였다 — 리다이렉트를 따라가면 되는가
  ③ `api.stlouisfed.org`(FRED 키 경로)도 같이 막혔는가 — 사용자가 FRED 키를
     등록할 가치가 있는지 판단하려면 이걸 알아야 한다
  ④ BEA(GDP·PCE)는 키 없이 되는가

사용: python macro_desk/tests/probe_release_sources.py
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

BLS = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
BLS_SERIES = {
    "CUSR0000SA0": "CPI 전체(SA, 지수)",
    "CUSR0000SA0L1E": "CPI 코어(SA, 지수)",
    "WPSFD4": "PPI 최종수요(SA, 지수)",
    "WPSFD49116": "PPI 최종수요 코어(SA, 지수)",
    "CES0000000001": "비농업 취업자(천명)",
    "LNS14000000": "실업률(%)",
    "CES0500000003": "시간당임금($)",
}

OTHERS = [
    ("Census MARTS 소매판매(리다이렉트 추적)",
     "https://api.census.gov/data/timeseries/eits/marts"
     "?get=cell_value,time_slot_id&for=us:*&category_code=44X72"
     "&data_type_code=SM&seasonally_adj=yes&time=from+2026-01"),
    ("FRED API(키 경로 — 키 없이 부르면 400이 정상, 차단이면 연결 자체가 실패)",
     "https://api.stlouisfed.org/fred/series/observations"
     "?series_id=CPIAUCSL&file_type=json&api_key=notakey"),
    ("BEA(키 필요 — 역시 연결되는지만 본다)",
     "https://apps.bea.gov/api/data/?UserID=notakey&method=GETDATASETLIST"),
]


def get(url: str, data: bytes | None = None, timeout: int = 15) -> tuple[int, str]:
    req = urllib.request.Request(
        url, data=data,
        headers={"User-Agent": "gs-research-desk/macro",
                 **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]


def probe_bls() -> None:
    print("=== BLS 공개 API v1 (키 불필요) ===")
    body = json.dumps({"seriesid": list(BLS_SERIES), "startyear": "2025",
                       "endyear": "2026"}).encode()
    status, text = get(BLS, data=body)
    j = json.loads(text)
    print(f"http={status} status={j.get('status')} message={j.get('message')}")
    got = {s["seriesID"]: s["data"] for s in j.get("Results", {}).get("series", [])}
    for sid, label in BLS_SERIES.items():
        rows = [d for d in got.get(sid, []) if d.get("value") not in ("-", "", None)]
        if not rows:
            print(f"  DEAD {sid:<16} {label}")
            continue
        tail = " | ".join(f'{d["year"]}-{d["period"]} {d["value"]}' for d in rows[:3])
        print(f"  OK   {sid:<16} {label:<22} {tail}")
    # 2025년 예산 공백으로 결측된 달이 있다 — 전년동월비를 못 만드는 구간이 생긴다
    holes = [f'{d["year"]}-{d["period"]}' for d in got.get("CUSR0000SA0", [])
             if d.get("value") in ("-", "", None)]
    print(f"  결측 달(CPI): {holes or '없음'}")


def main() -> None:
    probe_bls()
    for label, url in OTHERS:
        print(f"\n=== {label} ===")
        try:
            status, text = get(url)
            print(f"http={status} {text[:260]}")
        except Exception as e:
            print(f"연결 실패 — {type(e).__name__}: {str(e)[:120]}")


if __name__ == "__main__":
    main()
