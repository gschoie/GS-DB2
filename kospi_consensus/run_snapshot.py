# -*- coding: utf-8 -*-
"""주간 컨센서스 스냅샷 1회 실행: 유니버스 → 스크랩 → SQLite 저장.

사용:
    python run_snapshot.py               # KOSPI200 전체
    python run_snapshot.py --limit 5     # 앞 5종목만 (테스트)
    python run_snapshot.py --refresh-universe
    python run_snapshot.py --date 2026-07-06   # 스냅샷 기준일 수동 지정
"""
import argparse
import datetime as dt
import sys
import time

import requests
from playwright.sync_api import sync_playwright

import db
import scrape
import universe

sys.stdout.reconfigure(encoding="utf-8")


def week_monday(d=None):
    d = d or dt.date.today()
    return (d - dt.timedelta(days=d.weekday())).isoformat()


def run(limit=None, snapshot_date=None, refresh_universe=False, delay=0.3):
    snap = snapshot_date or week_monday()
    uni = universe.load_or_crawl(refresh=refresh_universe)
    items = list(uni.items())
    if limit:
        items = items[:limit]
    total = len(items)
    print(f"스냅샷 기준일 {snap} · 대상 {total} 종목")

    con = db.connect()
    session = requests.Session()
    ok_q = ok_a = fail = 0

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            extra_http_headers={"Referer": "https://finance.naver.com/"},
            user_agent=scrape.UA,
        )
        page = ctx.new_page()

        for i, (code, name) in enumerate(items, 1):
            db.upsert_universe(con, snap, code, name)

            q = scrape.fetch_quarter(code, session)
            if q and q["op_profit"] is not None:
                db.upsert_consensus(con, snap, code, name, "quarter", q["period"],
                                    q["sales"], q["op_profit"], q["net_profit"])
                ok_q += 1

            annual = scrape.scrape_annual(page, code)
            for row in annual:
                db.upsert_consensus(con, snap, code, name, "annual", row["period"],
                                    row["sales"], row["op_profit"], row["net_profit"])
            if annual:
                ok_a += 1
            if not q and not annual:
                fail += 1

            con.commit()
            e_years = ",".join(r["period"][:4] for r in annual) or "-"
            print(f"[{i}/{total}] {name}({code})  Q={q['period'] if q else '-'}  "
                  f"연간E={e_years}")
            time.sleep(delay)

        browser.close()
    con.close()
    print(f"\n완료: 분기 {ok_q} · 연간 {ok_a} · 실패 {fail} (총 {total})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--date", dest="snapshot_date", default=None)
    ap.add_argument("--refresh-universe", action="store_true")
    ap.add_argument("--delay", type=float, default=0.3)
    a = ap.parse_args()
    run(limit=a.limit, snapshot_date=a.snapshot_date,
        refresh_universe=a.refresh_universe, delay=a.delay)
