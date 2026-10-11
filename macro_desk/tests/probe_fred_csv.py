# -*- coding: utf-8 -*-
"""러너 전용 탐색 스크립트 — FRED **키 없는** CSV 엔드포인트로 어떤 계열이 살아 있나.

컨테이너는 fred.stlouisfed.org 로 못 나가므로(egress 차단) 이 파일은 워크플로에서만
돌린다. 발표 지표의 '직전치'를 키 없이 받을 수 있는지, 어느 계열 ID가 아직 유지되는지
(ISM·OECD 한국 계열은 폐기된 것이 많다) 실측으로 가린다.

쓰고 나면 지워도 되는 일회성 코드지만, 다음에 계열이 또 죽으면 여기부터 다시 돌릴 수
있게 남겨둔다. 사용: python macro_desk/tests/probe_fred_csv.py
"""
from __future__ import annotations

import csv
import io
import urllib.request

CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"

CANDIDATES = [
    # 미국 — 물가
    ("CPIAUCSL", "CPI 전체(SA, 지수)"),
    ("CPILFESL", "CPI 코어(SA, 지수)"),
    ("PCEPI", "PCE 물가(지수)"),
    ("PCEPILFE", "PCE 코어(지수)"),
    ("PPIFIS", "PPI 최종수요(지수)"),
    # 미국 — 고용
    ("PAYEMS", "비농업 취업자(천명, 수준)"),
    ("UNRATE", "실업률(%)"),
    ("CES0500000003", "시간당임금($)"),
    # 미국 — 실물
    ("RSAFS", "소매판매(백만$)"),
    ("A191RL1Q225SBEA", "실질GDP 전기비연율(%)"),
    # 미국 — 정책
    ("DFEDTARU", "연방기금목표 상한(%)"),
    ("DFEDTARL", "연방기금목표 하한(%)"),
    # ISM — 2022년에 FRED 에서 내려갔다고 알고 있지만 확인
    ("NAPM", "ISM 제조업"),
    ("NAPMNOI", "ISM 제조업 신규주문"),
    ("NMFBAI", "ISM 서비스업"),
    # 한국 — OECD 경유 계열. MEI 폐기로 상당수가 죽었을 것
    ("KORCPIALLMINMEI", "한국 CPI(MEI, 지수)"),
    ("CPALTT01KRM659N", "한국 CPI 전년동월비(%)"),
    ("CPALTT01KRM657N", "한국 CPI 전월비(%)"),
    ("LRHUTTTTKRM156S", "한국 실업률(%)"),
    ("XTEXVA01KRM667S", "한국 수출(지수)"),
    ("XTEXVA01KRM664N", "한국 수출(통화)"),
    ("NAEXKP01KRQ657S", "한국 GDP 전기비(%)"),
    ("IRSTCI01KRM156N", "한국 콜금리(%)"),
    ("INTDSRKRM193N", "한국 재할인율(%)"),
]


def last_obs(series: str, n: int = 3):
    req = urllib.request.Request(CSV.format(series), headers={"User-Agent": "gs-macro-probe"})
    with urllib.request.urlopen(req, timeout=25) as r:
        body = r.read().decode("utf-8", "replace")
    rows = list(csv.reader(io.StringIO(body)))
    if not rows:
        raise ValueError("빈 응답")
    head = rows[0]
    vals = [(a, b) for a, b in (x[:2] for x in rows[1:] if len(x) >= 2)
            if b not in (".", "", None)]
    if not vals:
        raise ValueError(f"관측치 없음(헤더 {head})")
    return vals[-n:]


def main() -> None:
    ok, dead = [], []
    for sid, label in CANDIDATES:
        try:
            got = last_obs(sid)
            ok.append(sid)
            tail = " | ".join(f"{d} {v}" for d, v in got)
            print(f"OK   {sid:<18} {label:<22} {tail}")
        except Exception as e:
            dead.append(sid)
            print(f"DEAD {sid:<18} {label:<22} {type(e).__name__}: {str(e)[:70]}")
    print(f"\n살아있음 {len(ok)} / 죽음 {len(dead)}")
    if dead:
        print("죽은 계열: " + " ".join(dead))


if __name__ == "__main__":
    main()
