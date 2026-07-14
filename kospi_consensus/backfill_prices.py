# -*- coding: utf-8 -*-
"""기존 스냅샷들의 종가를 소급 수집한다(주가 변동폭 계산용).

각 snapshot_date의 종가 기준일 = 그 스냅샷 수집 시각(captured_at, UTC)의 KST 날짜.
이미 종가가 있으면 건너뛴다.

사용: python backfill_prices.py
"""
import datetime as dt
import sys
import time

import requests

import db
import scrape

sys.stdout.reconfigure(encoding="utf-8")


def main():
    con = db.connect()
    session = requests.Session()
    rows = con.execute(
        "SELECT snapshot_date, MAX(captured_at) mx FROM consensus_snapshots GROUP BY snapshot_date"
    ).fetchall()
    for r in rows:
        snap = r["snapshot_date"]
        # captured_at(UTC) → KST 날짜 = 종가 기준일
        try:
            kst = dt.datetime.fromisoformat(r["mx"]) + dt.timedelta(hours=9)
            pdate = kst.date()
        except Exception:
            pdate = dt.date.fromisoformat(snap)
        have = {x[0] for x in con.execute(
            "SELECT code FROM stock_prices WHERE snapshot_date=?", (snap,))}
        codes = [x[0] for x in con.execute(
            "SELECT DISTINCT code FROM consensus_snapshots WHERE snapshot_date=?", (snap,))]
        todo = [c for c in codes if c not in have]
        print(f"[{snap}] 종가기준일 {pdate} · 대상 {len(todo)}/{len(codes)}종목")
        ok = 0
        for i, code in enumerate(todo, 1):
            pr = scrape.fetch_close(code, on_date=pdate, session=session)
            if pr:
                db.upsert_price(con, snap, code, pr["price_date"], pr["close"])
                ok += 1
            if i % 50 == 0:
                con.commit()
                print(f"   ... {i}/{len(todo)}")
            time.sleep(0.05)
        con.commit()
        print(f"   → {ok}종목 종가 저장")
    con.close()


if __name__ == "__main__":
    main()
