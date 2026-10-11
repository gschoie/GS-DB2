# -*- coding: utf-8 -*-
"""직전치 변환 검산 — 네트워크 없이 가짜 관측치로만 돈다.

valuation 모듈과 같은 이유: 컨테이너에서 fred.stlouisfed.org 가 막혀 실호출을 못 하므로
**산식만** 따로 검산한다. 받아오는 쪽(observations)이 깨지면 그건 probe_release_sources.py 로 본다.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import releases as rl  # noqa: E402

FAIL = []


def eq(got, want, label):
    if got != want:
        FAIL.append(f"{label}: {got!r} != {want!r}")
        print(f"  FAIL {label}: {got!r} != {want!r}")
    else:
        print(f"  ok   {label}")


def monthly(vals: list[float], end=(2026, 9)) -> list[tuple[dt.date, float]]:
    """마지막 관측이 end 인 월간 계열."""
    y, m = end
    out = []
    for v in reversed(vals):
        out.append((dt.date(y, m, 1), v))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def quarterly(vals: list[float], end=(2026, 7)) -> list[tuple[dt.date, float]]:
    y, m = end
    out = []
    for v in reversed(vals):
        out.append((dt.date(y, m, 1), v))
        m -= 3
        if m <= 0:
            y, m = y - 1, m + 12
    return list(reversed(out))


# 1) 지수 계열 → 전월비·전년동월비
obs = monthly([100.0] + [100.0 * 1.002 ** i for i in range(1, 13)])
s = rl.summarize(obs, {"series": "CPIAUCSL", "kind": "yoy_mom"})
eq(s["text"], "전년 +2.4% · 전월 +0.2%", "지수 → 전년·전월")
eq(s["period"], "2026년 9월", "기간 라벨(월)")
eq(len(s["recent"]), 3, "최근 3회 길이")

# 2) 전년동월비만
s = rl.summarize(obs, {"series": "X", "kind": "yoy"})
eq(s["text"], "전년 +2.4%", "yoy 만")

# 3) 전월비만
s = rl.summarize(obs, {"series": "X", "kind": "mom"})
eq(s["text"], "전월 +0.2%", "mom 만")

# 4) 수준값 — 소수 자리 지정
s = rl.summarize(monthly([4.3, 4.2, 4.1]), {"series": "UNRATE", "kind": "level",
                                            "unit": "%", "digits": 1})
eq(s["text"], "4.1%", "수준값")
eq(s["recent"], ["4.3", "4.2", "4.1"], "수준값 최근 3회")

# 5) 증감 — 천명 → 만명 환산
s = rl.summarize(monthly([159000.0, 159100.0, 159219.0]),
                 {"series": "PAYEMS", "kind": "diff", "scale": 10, "unit": "만명"})
eq(s["text"], "+11.9만명", "취업자 증감(천명→만명)")
eq(s["recent"], ["+10.0", "+11.9"], "증감은 직전값이 있어야 계산된다")

# 6) 감소도 부호가 보인다
s = rl.summarize(monthly([159000.0, 158880.0]),
                 {"series": "PAYEMS", "kind": "diff", "scale": 10, "unit": "만명"})
eq(s["text"], "-12.0만명", "취업자 감소")

# 7) 분기 계열 — 라벨과 '전기'
s = rl.summarize(quarterly([2.8, 3.0, 2.4]), {"series": "GDP", "kind": "level",
                                              "freq": "q", "unit": "%"})
eq(s["text"], "2.4%", "분기 수준값")
eq(s["period"], "2026년 3분기", "기간 라벨(분기)")

# 8) 분기 지수의 전기비는 '전기'로 적는다 — '전월'이면 거짓말이 된다
s = rl.summarize(quarterly([100.0, 101.0, 102.0]), {"series": "X", "kind": "mom", "freq": "q"})
eq(s["text"], "전기 +1.0%", "분기는 '전기'")

# 9) 변화율을 못 구하면 '–' — **지수 원값을 대신 찍으면 안 된다.**
#    'CPI 코어 337.8' 처럼 증가율 자리에 지수 레벨이 앉아 전혀 다른 뜻이 된다.
s = rl.summarize(monthly([3.3]), {"series": "X", "kind": "yoy_mom"})
eq(s["text"], "–", "관측치 1개 → 변화율 없음")
s = rl.summarize(monthly([326.0, 337.765]), {"series": "CUSR0000SA0L1E", "kind": "yoy"})
eq(s["text"], "–", "전년 관측이 없으면 지수 레벨을 찍지 않는다")

# 10) 전년 관측이 비어 있으면(결측으로 빠진 달) yoy 를 만들지 않는다
sparse = [(dt.date(2025, 3, 1), 100.0), (dt.date(2026, 8, 1), 103.0),
          (dt.date(2026, 9, 1), 103.2)]
s = rl.summarize(sparse, {"series": "X", "kind": "yoy_mom"})
eq(s["text"], "전월 +0.2%", "전년 관측 없으면 전년비 생략")

# 11) 0 으로 나누지 않는다 — 비율을 못 만들면 '–'
s = rl.summarize(monthly([0.0, 0.5]), {"series": "X", "kind": "mom"})
eq(s["text"], "–", "직전값 0 → 비율 없음")

# 12) 날짜 기준 전년 탐색 — 분기 계열에서 **4분기 전**(같은 달)을 집는다.
#     인덱스로 '13번째 뒤'를 세면 월간 가정이라 분기 계열에서 엉뚱한 값을 집는다.
q = quarterly([100.0, 101.0, 102.0, 103.0, 106.0])   # 2025-07 … 2026-07
eq(q[-1][0].isoformat(), "2026-07-01", "분기 계열 마지막 관측")
eq(rl._pick_back(q, 12), 100.0, "분기 계열의 12개월 전(2025-07)")
eq(rl._pick_back(q, 3), 103.0, "분기 계열의 3개월 전(2026-04)")

# 13) 컨센서스 파일이 없으면 빈 dict (화면은 '–')
if not rl.CONSENSUS.exists():
    eq(rl.load_consensus(), {}, "컨센서스 파일 없음")
else:
    eq(isinstance(rl.load_consensus(), dict), True, "컨센서스 파일 파싱")

print()
if FAIL:
    raise SystemExit(f"{len(FAIL)}개 실패\n" + "\n".join(FAIL))
print("직전치 변환 테스트 전부 통과")

# ── BLS 응답 파싱 ───────────────────────────────────────────────────────────
print("\n[BLS 기간 표기]")
eq(rl._bls_date("2026", "M08"), dt.date(2026, 8, 1), "M08 → 8월")
eq(rl._bls_date("2026", "Q03"), dt.date(2026, 7, 1), "Q03 → 3분기 시작")
eq(rl._bls_date("2026", "A01"), dt.date(2026, 1, 1), "A01 → 연간")
eq(rl._bls_date("2026", "M13"), None, "M13(연평균)은 버린다")
eq(rl._bls_date("2026", "M00"), None, "M00 같은 쓰레기도 버린다")

print("\n[fetch — 가짜 BLS 응답으로]")
# 실호출 없이 fetch 전체 경로를 돈다. 실측값(2026-09 실업률 4.2 · 취업자 159044천명)을 쓴다.
ENTRIES = [
    {"id": "us_payrolls", "name": "미국 고용보고서",
     "release": {"series": "CES0000000001", "kind": "diff", "scale": 10, "unit": "만명",
                 "also": {"series": "LNS14000000", "kind": "level", "unit": "%",
                          "digits": 1, "label": "실업률"}}},
    {"id": "us_cpi", "name": "미국 CPI",
     "release": {"series": "CUSR0000SA0", "kind": "yoy_mom"}},
    {"id": "us_pce", "name": "미국 PCE",
     "release": {"src": "fred", "series": "PCEPI", "kind": "yoy_mom"}},
    {"id": "us_ism_mfg", "name": "ISM"},        # release 없음 — 건너뛴다
]
FAKE = {
    "CES0000000001": monthly([158882.0, 159015.0, 159044.0]),
    "LNS14000000": monthly([4.1, 4.1, 4.2]),
    "CUSR0000SA0": monthly([100 * 1.002 ** i for i in range(14)]),
}
rl.bls_observations = lambda series, **kw: {k: v for k, v in FAKE.items() if k in series}
got = rl.fetch(ENTRIES)                      # FRED 키 없음
eq(sorted(got), ["us_cpi", "us_payrolls"], "키 없으면 FRED 계열은 빠진다")
eq(got["us_payrolls"]["text"], "+2.9만명 · 실업률 4.2%", "also 가 한 줄에 붙는다")
eq(got["us_cpi"]["text"], "전년 +2.4% · 전월 +0.2%", "주 계열만")

# BLS 호출이 통째로 실패해도 터지지 않는다(그 지표만 빠진다)
def boom(series, **kw):
    raise RuntimeError("차단")
rl.bls_observations = boom
eq(rl.fetch(ENTRIES), {}, "BLS 실패 → 빈 dict(수집 전체는 계속된다)")
