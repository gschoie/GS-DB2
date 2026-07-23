# -*- coding: utf-8 -*-
"""SQLite 접근 헬퍼."""
import os
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "data", "consensus.db")
SCHEMA_PATH = os.path.join(BASE, "schema.sql")


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        con.executescript(f.read())
    # 기존 DB 마이그레이션: universe 신규 컬럼(market/groups/status)
    ucols = {r[1] for r in con.execute("PRAGMA table_info(universe)")}
    for c in ("market", "groups", "status"):
        if c not in ucols:
            con.execute(f"ALTER TABLE universe ADD COLUMN {c} TEXT")
    return con


def upsert_consensus(con, snapshot_date, code, name, kind, period,
                     sales, op_profit, net_profit):
    con.execute(
        """
        INSERT INTO consensus_snapshots
            (snapshot_date, code, name, kind, period, sales, op_profit, net_profit)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(snapshot_date, code, kind, period) DO UPDATE SET
            name       = excluded.name,
            sales      = excluded.sales,
            op_profit  = excluded.op_profit,
            net_profit = excluded.net_profit
        """,
        (snapshot_date, code, name, kind, period, sales, op_profit, net_profit),
    )


def upsert_price(con, snapshot_date, code, price_date, close):
    con.execute(
        """
        INSERT INTO stock_prices (snapshot_date, code, price_date, close)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(snapshot_date, code) DO UPDATE SET
            price_date = excluded.price_date,
            close      = excluded.close
        """,
        (snapshot_date, code, price_date, close),
    )


def price_map(con, snapshot_date):
    """해당 스냅샷의 code→close dict."""
    return {r["code"]: r["close"] for r in con.execute(
        "SELECT code, close FROM stock_prices WHERE snapshot_date=? AND close IS NOT NULL",
        (snapshot_date,))}


def upsert_universe(con, snapshot_date, code, name, market=None, groups=None, status=None):
    con.execute(
        """
        INSERT INTO universe (snapshot_date, code, name, market, groups, status)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(snapshot_date, code) DO UPDATE SET
            name   = excluded.name,
            market = excluded.market,
            groups = excluded.groups,
            status = excluded.status
        """,
        (snapshot_date, code, name, market, groups, status),
    )


def snapshot_dates(con):
    """저장된 스냅샷 날짜 목록 (오름차순)."""
    rows = con.execute(
        "SELECT DISTINCT snapshot_date FROM consensus_snapshots ORDER BY snapshot_date"
    ).fetchall()
    return [r[0] for r in rows]
