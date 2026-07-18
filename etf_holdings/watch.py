# -*- coding: utf-8 -*-
"""기준일 워처: CU 구성종목 '기준일'이 넘어갔을 때만 파이프라인을 돌리기 위한 판정.

매시간 가볍게 대표 ETF 1개의 기준일만 확인(요청 1번)하고, 저장된 마지막 처리 기준일보다
넘어갔으면 실행(should_run=true). 넘어가지 않았으면 스킵 → 하루 한 번, 데이터가 실제로
갱신됐을 때만 무거운 수집·알림이 돈다.

  python watch.py check    # 판정 → GITHUB_OUTPUT(should_run, base) + 콘솔
  python watch.py commit   # 파이프라인 성공 후, 최신 스냅샷 기준일을 state에 저장

state.json: {"last_base_date": "YYYY-MM-DD", "updated_at": "..."}  (커밋해서 런 간 유지)
환경변수 WATCH_FORCE=1 이면 무조건 실행(수동 workflow_dispatch용).
"""
import os, sys, json, glob
from datetime import datetime, timezone, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state.json")
SNAP_DIR = os.path.join(HERE, "snapshots")
KST = timezone(timedelta(hours=9))

import fetch_holdings


def _load_state():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    return {"last_base_date": "", "updated_at": ""}


def _rep_code():
    """대표 ETF(유니버스 첫 active) 티커."""
    uni = fetch_holdings.load_universe()
    return uni[0]["code"] if uni else "445290"


def _emit(should_run, base):
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"should_run={'true' if should_run else 'false'}\n")
            f.write(f"base={base}\n")


def check():
    state = _load_state()
    last = state.get("last_base_date", "")
    force = os.environ.get("WATCH_FORCE") == "1"
    base = fetch_holdings.fetch_base_date(_rep_code())
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")

    if force:
        should = True; why = "강제 실행(수동)"
    elif not base:
        should = False; why = "기준일 조회 실패 — 스킵(다음 시각 재시도)"
    elif not last:
        should = True; why = "최초 실행(state 없음)"
    elif base > last:
        should = True; why = f"기준일 갱신 {last} → {base}"
    else:
        should = False; why = f"기준일 동일({base}) — 아직 새 구성 아님"

    print(f"[{now}] 대표기준일={base or '?'} · 마지막처리={last or '-'} → "
          f"{'실행' if should else '스킵'} ({why})")
    _emit(should, base)
    return should


def commit():
    """최신 스냅샷의 기준일을 state에 기록."""
    snaps = sorted(glob.glob(os.path.join(SNAP_DIR, "*.json")))
    base = ""
    if snaps:
        with open(snaps[-1], encoding="utf-8") as f:
            base = json.load(f).get("base_date", "")
    if not base:
        print("스냅샷 기준일 없음 — state 미갱신")
        return
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump({"last_base_date": base,
                   "updated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M")},
                  f, ensure_ascii=False, indent=2)
    print(f"state 갱신: last_base_date={base}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "commit":
        commit()
    else:
        check()
