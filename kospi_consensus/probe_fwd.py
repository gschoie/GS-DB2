# -*- coding: utf-8 -*-
"""fwd 분기 수집 E2E 검증 프로브 v3 (일회용, GitHub 러너에서 실행).

run_snapshot --limit 6 을 실제로 돌리고(DB는 러너 로컬, 커밋 안 됨)
- 분기(E)가 당분기+2개(fwd)로 들어왔는지
- 연간 kind에 12월 외 period가 섞이지 않았는지(토글 회귀 검사)
를 출력한다. 검증 후 이 파일과 consensus-probe.yml 삭제.
"""
import sqlite3
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

subprocess.run([sys.executable, "run_snapshot.py", "--limit", "6"], check=True)

con = sqlite3.connect("data/consensus.db")
snap = con.execute("SELECT MAX(snapshot_date) FROM consensus_snapshots").fetchone()[0]
print(f"\n===== 검증: 스냅샷 {snap} =====")

print("\n[분기 kind 종목별 period]")
for code, name in con.execute(
        "SELECT DISTINCT code, name FROM consensus_snapshots WHERE snapshot_date=? ORDER BY code",
        (snap,)):
    for kind in ("quarter", "quarter_actual"):
        rows = con.execute(
            "SELECT period, op_profit FROM consensus_snapshots "
            "WHERE snapshot_date=? AND code=? AND kind=? ORDER BY period",
            (snap, code, kind)).fetchall()
        if rows:
            print(f"  {name}({code}) {kind}: " +
                  " ".join(f"{p}={v:,.0f}" for p, v in rows))

print("\n[연간 kind period 분포 — 12월 외가 있으면 토글 회귀]")
for r in con.execute(
        "SELECT kind, period, COUNT(*) FROM consensus_snapshots "
        "WHERE snapshot_date=? AND kind IN ('annual','annual_actual') GROUP BY 1,2 ORDER BY 1,2",
        (snap,)):
    print(" ", r)

bad = con.execute(
    "SELECT COUNT(*) FROM consensus_snapshots WHERE snapshot_date=? "
    "AND kind IN ('annual','annual_actual') AND period NOT LIKE '%.12'", (snap,)).fetchone()[0]
fwd = con.execute(
    "SELECT COUNT(DISTINCT period) FROM consensus_snapshots WHERE snapshot_date=? "
    "AND kind='quarter'", (snap,)).fetchone()[0]
print(f"\n연간에 섞인 비12월 행: {bad} (0이어야 함) · 분기(E) period 종류: {fwd} (2 이상이어야 함)")
assert bad == 0 and fwd >= 2
print("검증 통과")
