# -*- coding: utf-8 -*-
"""실행 게이트: 오늘이 수집할 날인가.

[2026-10-05 전면 수정]
원래는 CU 구성종목 '기준일'을 1회 조회해 "기준일이 넘어갔을 때만 전체 수집"하는
워처였다. 그 기준일을 긁던 finance.naver.com/item/coinfo.naver 가 9/11 Npay 증권
개편으로 죽어(신규 SPA 로 리다이렉트·'기준' 표기 소멸) **2026-09-10 이후 기준일이
계속 빈 값**이었고, state.json 도 9/10 에 멈춰 있었다. 게다가 GAS 스케줄러가
workflow_dispatch 로 쏘면 워크플로가 WATCH_FORCE=1 을 걸어 **판정 자체를 건너뛰고**
매시간 전체 수집이 돌았다 — 10/5 대체공휴일에도 09·10·11시 세 번.

신규 API 에도 CU 기준일이 없어(etf/analysis·etf/component/list 응답 키 전수 확인)
설계를 둘로 나눴다:
  · 이 파일  = **휴장일이면 아예 돌지 않는다** (거래가 없으니 새 바스켓도 없다)
  · fetch_holdings = **구성이 실제로 바뀌었을 때만** 스냅샷을 쓴다(계약수 지문 비교)

  python watch.py check    # 판정 → GITHUB_OUTPUT(should_run, market_date)

WATCH_FORCE=1 이면 휴장일이라도 실행(화면의 수동 '갱신' 버튼용).
GAS 스케줄러(via=scheduler)는 force 를 걸지 않는다 — 워크플로에서 구분한다.
"""
import os, sys, json
from datetime import datetime, timezone, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
KST = timezone(timedelta(hours=9))

import fetch_holdings


def _emit(should_run, market_date):
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"should_run={'true' if should_run else 'false'}\n")
            f.write(f"market_date={market_date}\n")


def check():
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    force = os.environ.get("WATCH_FORCE") == "1"
    traded, status = fetch_holdings.market_day()

    if force:
        should, why = True, "강제 실행(수동 갱신)"
    elif not traded:
        # 조회 실패로 멈추면 조용히 몇 날 며칠 비는 쪽이 더 위험하다 → fail-open
        should, why = True, "장 상태 조회 실패 — 일단 실행(구성 변화 없으면 저장 생략)"
    elif traded != today:
        should, why = False, f"휴장일 — 마지막 거래일 {traded} ≠ 오늘 {today}"
    else:
        should, why = True, f"거래일({traded}·{status or '?'})"

    print(f"[{now:%Y-%m-%d %H:%M} KST] {'실행' if should else '스킵'} ({why})")
    _emit(should, traded)
    return should


if __name__ == "__main__":
    check()
