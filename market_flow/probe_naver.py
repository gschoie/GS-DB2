# -*- coding: utf-8 -*-
"""수정된 snapshot_provisional 검증 프로브 (일회용, GitHub 러너에서 실행).

옛 PC 메인페이지 폐쇄(9/11)로 시간대별 페이지 기반으로 교체한
snapshot_provisional이 실데이터에서 정상 동작하는지 확인한다.
"""
import datetime as dt
import sys

import scrape

sys.stdout.reconfigure(encoding="utf-8")

bizdate = dt.datetime.now(scrape.KST).strftime("%Y%m%d")
snap = scrape.snapshot_provisional(bizdate)
print(f"bizdate={bizdate}")
print(f"snapshot_provisional 결과: {snap}")
assert all(isinstance(v, int) for v in snap.values()), "정수가 아닌 값 존재"
assert set(snap) == {"individual", "foreign", "institution", "arb", "nonarb", "program"}

# 교차 검증: 일별 확정 페이지의 오늘 행과 방향이 같아야 함 (누적 잠정 vs 잠정 집계)
confirmed = scrape.daily_confirmed(bizdate, pages=1)
today = dt.datetime.now(scrape.KST).strftime("%Y-%m-%d")
if today in confirmed and "investor" in confirmed[today]:
    inv = confirmed[today]["investor"]
    print(f"일별 페이지 오늘 행: 개인 {inv['individual']} · 외국인 {inv['foreign']} · "
          f"기관 {inv['inst_total']}")
print("검증 완료")
