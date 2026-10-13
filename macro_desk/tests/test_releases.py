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
eq(s["text"], "YoY +2.4% · MoM +0.2%", "지수 → YoY·MoM")
eq(s["period"], "2026년 9월분", "기간 라벨(월) — 대상 기간이지 발표월이 아니다")
eq(len(s["recent"]), 3, "최근 3회 길이")

# 2) 전년동월비만
s = rl.summarize(obs, {"series": "X", "kind": "yoy"})
eq(s["text"], "YoY +2.4%", "yoy 만")

# 3) 전월비만
s = rl.summarize(obs, {"series": "X", "kind": "mom"})
eq(s["text"], "MoM +0.2%", "mom 만")

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
eq(s["text"], "QoQ +1.0%", "분기는 QoQ")

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
eq(s["text"], "MoM +0.2%", "전년 관측 없으면 YoY 생략")

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
eq(got["us_cpi"]["text"], "YoY +2.4% · MoM +0.2%", "주 계열만")

# BLS 호출이 통째로 실패해도 터지지 않는다(그 지표만 빠진다)
def boom(series, **kw):
    raise RuntimeError("차단")
rl.bls_observations = boom
eq(rl.fetch(ENTRIES), {}, "BLS 실패 → 빈 dict(수집 전체는 계속된다)")

# ── 멈춘 계열은 버린다 ──────────────────────────────────────────────────────
print("\n[폐기 계열 판정]")
TODAY = dt.date(2026, 10, 11)
# 한국 CPI 실사고: KORCPIALLMINMEI 가 2023-11 에 멈췄는데 FRED 는 그 값을 계속 내줬고
# 화면에 "직전 발표: 2023년 11월 전년 +3.3%" 가 찍혔다.
dead = monthly([100.0, 101.0, 102.0], end=(2023, 11))
eq(rl.is_stale(dead, {"freq": "m"}, TODAY), True, "3년 멈춘 월간 계열 = 폐기")
fresh = monthly([100.0, 101.0, 102.0], end=(2026, 9))
eq(rl.is_stale(fresh, {"freq": "m"}, TODAY), False, "지난달까지 있는 월간 계열 = 정상")
# 월간은 발표 지연이 한두 달 있으므로 그건 살려야 한다(CPI 는 8월분이 10월에도 최신)
eq(rl.is_stale(monthly([1.0, 2.0], end=(2026, 8)), {"freq": "m"}, TODAY), False,
   "두 달 전까지 = 아직 정상(발표 지연)")
eq(rl.is_stale(monthly([1.0, 2.0], end=(2026, 4)), {"freq": "m"}, TODAY), True,
   "다섯 달 전 = 멈춤")
# 분기 계열은 더 느긋하게 본다(2분기 GDP 가 10월에도 최신일 수 있다)
eq(rl.is_stale(quarterly([1.0, 2.0], end=(2026, 4)), {"freq": "q"}, TODAY), False,
   "2분기 GDP = 10월에도 정상")
eq(rl.is_stale(quarterly([1.0, 2.0], end=(2025, 7)), {"freq": "q"}, TODAY), True,
   "1년 넘은 분기 계열 = 멈춤")
# 일별(정책금리)은 며칠만 밀려도 이상하다
eq(rl.is_stale([(dt.date(2026, 10, 10), 4.0)], {"freq": "d"}, TODAY), False, "어제치 = 정상")
eq(rl.is_stale([(dt.date(2026, 8, 1), 4.0)], {"freq": "d"}, TODAY), True, "두 달 전 = 멈춤")

print("\n[fetch — 멈춘 계열은 빠진다]")
STALE_ENTRY = [{"id": "kr_cpi", "name": "한국 CPI",
                "release": {"series": "KORCPIALLMINMEI", "kind": "yoy_mom"}}]
rl.bls_observations = lambda series, **kw: {"KORCPIALLMINMEI": dead}
eq(rl.fetch(STALE_ENTRY), {}, "멈춘 계열은 직전치로 내보내지 않는다")
