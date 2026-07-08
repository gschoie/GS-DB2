# -*- coding: utf-8 -*-
"""전주 대비 영업이익 컨센 리비전 리포트.

두 스냅샷 날짜를 비교해 종목별 영업이익 컨센 변화(%)를 계산하고
상향/하향 랭킹을 출력한다.

사용:
    python report.py                        # 최근 2개 스냅샷 비교, FY2026
    python report.py --metric quarter       # 이번분기 기준
    python report.py --period 2027.12       # 특정 연간
    python report.py --base 2026-06-29 --curr 2026-07-06
"""
import argparse
import sys

import db

sys.stdout.reconfigure(encoding="utf-8")


def revisions(con, kind, period, base_date, curr_date):
    """(name, code, base, curr, wow_pct) 리스트 반환."""
    rows = con.execute(
        """
        SELECT c.code, c.name, b.op_profit AS base, c.op_profit AS curr
        FROM consensus_snapshots c
        JOIN consensus_snapshots b
          ON b.code = c.code AND b.kind = c.kind AND b.period = c.period
         AND b.snapshot_date = ?
        WHERE c.snapshot_date = ? AND c.kind = ? AND c.period = ?
          AND b.op_profit IS NOT NULL AND c.op_profit IS NOT NULL
          AND b.op_profit <> 0
        """,
        (base_date, curr_date, kind, period),
    ).fetchall()
    out = []
    for r in rows:
        wow = (r["curr"] - r["base"]) / abs(r["base"]) * 100.0
        out.append((r["name"], r["code"], r["base"], r["curr"], wow))
    out.sort(key=lambda x: x[4], reverse=True)
    return out


def default_period(con, kind):
    """해당 kind에서 가장 최근 스냅샷의 대표 period."""
    if kind == "quarter":
        row = con.execute(
            "SELECT period FROM consensus_snapshots WHERE kind='quarter' "
            "ORDER BY snapshot_date DESC, period ASC LIMIT 1"
        ).fetchone()
        return row["period"] if row else None
    return "2026.12"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--metric", choices=["annual", "quarter"], default="annual")
    ap.add_argument("--period", default=None, help="예: 2026.12 / 2027.12")
    ap.add_argument("--base", default=None)
    ap.add_argument("--curr", default=None)
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args()

    con = db.connect()
    dates = db.snapshot_dates(con)
    if len(dates) < 2 and not (a.base and a.curr):
        print(f"스냅샷이 {len(dates)}개뿐입니다. 최소 2주치가 있어야 리비전 비교가 됩니다.")
        print("현재 스냅샷:", dates)
        return

    curr = a.curr or dates[-1]
    base = a.base or dates[-2]
    period = a.period or default_period(con, a.metric)

    data = revisions(con, a.metric, period, base, curr)
    label = "이번분기" if a.metric == "quarter" else "연간"
    print(f"■ 영업이익 컨센 리비전 · {label} {period} · {base} → {curr}  "
          f"({len(data)} 종목)\n")

    if not data:
        print("비교 가능한 데이터가 없습니다.")
        return

    up = [d for d in data if d[4] > 0]
    down = [d for d in data if d[4] < 0]
    print(f"상향 {len(up)} · 하향 {len(down)} · 변동없음 {len(data)-len(up)-len(down)}\n")

    print(f"▲ 상향 Top {a.top}")
    for name, code, b, c, w in data[:a.top]:
        print(f"   {name:12}({code})  {b:>12,.0f} → {c:>12,.0f}  {w:+6.1f}%")
    print(f"\n▼ 하향 Top {a.top}")
    for name, code, b, c, w in data[-a.top:][::-1]:
        print(f"   {name:12}({code})  {b:>12,.0f} → {c:>12,.0f}  {w:+6.1f}%")


if __name__ == "__main__":
    main()
