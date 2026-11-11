"""주보 5종(주가변동표·INDEX·수급그림·컨센서스·ER)에서 '이번 주 튀는 차트'를 규칙으로 골라 JSON 으로 굽는다.

    python build.py                 # ECOS_DIR 의 ecos-fx-rates 체크아웃 + 야후 수집
    python build.py --demo          # 네트워크 없이 가짜 시세로 산출물 모양만 확인(컨테이너용)

산출물: telegram_research_dashboard/static/weekly_highlights/<기준일>.json · latest.json · index.json
화면: static/weekly_highlights_report.html 이 latest.json 을 런타임으로 읽어 그린다(사이드바 📰 주보 › ✨ 이번주.튀는차트).
그림은 원본 PNG 를 쓰지 않고 같은 데이터로 페이지가 직접 그린다 — 갤러리 PNG 는 토 16:40 에 갱신되는데
이 페이지는 토요일 새벽(미국장 마감 직후)에 돌아서, 그림을 빌리면 '목요일 미국 종가 그림 + 금요일 숫자' 가 섞인다.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import catalog  # noqa: E402
import rules  # noqa: E402

REPO = catalog.REPO
OUT_DIR = os.path.join(REPO, "telegram_research_dashboard", "static", "weekly_highlights")
SERIES_JSON = os.path.join(REPO, "coverage_flow", "data", "series.json")
INDEX_DAYS = 60            # INDEX 창(거래일) — 생성기 idx.DAYS 와 같다
LONG_DAYS = 300            # z 계산용 긴 창
RET_DAYS = {"1W": 5, "1M": 21, "3M": 63, "1Y": 252}
SPARK = 63


def log(*a):
    print(*a, flush=True)


# ─────────────────────────── 시세 ───────────────────────────
def fetch_prices(tickers, days=460):
    import yfinance as yf
    start = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    raw = yf.download(tickers, start=start, auto_adjust=True, group_by="ticker", threads=True, progress=False)
    out = {}
    for t in tickers:
        try:
            s = raw[t]["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw["Close"]
        except KeyError:
            s = pd.Series(dtype=float)
        s = s.dropna()
        if s.empty:
            try:
                s = yf.Ticker(t).history(start=start)["Close"].dropna()
            except Exception:
                s = pd.Series(dtype=float)
        if s.empty:
            log(f"⚠️ {t}: 가격 없음")
            continue
        s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
        out[t] = s[~s.index.duplicated(keep="last")]
    return out


def demo_prices(tickers, seed=11, n=320):
    rnd = random.Random(seed)
    idx = pd.bdate_range(end=datetime.today().date(), periods=n)
    out = {}
    for i, t in enumerate(tickers):
        p, vals = 100.0, []
        hot = rnd.random() < 0.12            # 몇 종목만 이번 주에 크게 움직인다
        for k in range(n):
            step = rnd.gauss(0.0004, 0.014)
            if hot and k >= n - 5:
                step += rnd.choice([-1, 1]) * 0.03
            p *= 1 + step
            vals.append(p)
        out[t] = pd.Series(vals, index=idx)
    return out


def _ret(s, n):
    return float(s.iloc[-1] / s.iloc[-1 - n] - 1) if len(s) > n else None


def _ytd(s):
    last_d = s.index[-1]
    prev = s[s.index < datetime(last_d.year, 1, 1)]
    return float(s.iloc[-1] / prev.iloc[-1] - 1) if not prev.empty else None


def _r(v, d=4):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return round(float(v), d)


# ─────────────────────────── ① 주가변동표 ───────────────────────────
def peer_picks(sections, prices):
    picks, scanned = [], 0
    for sec in sections:
        rows, flagged = [], 0
        for g, name, t in sec["rows"]:
            s = prices.get(t)
            if s is None or len(s) < 10:
                continue
            scanned += 1
            reasons, m = rules.price_flags(s.tolist(), is_index=not sec["stock"])
            row = {"group": g, "name": name, "ticker": t, "flag": bool(reasons), "reasons": reasons,
                   "r": {k: _r(_ret(s, n)) for k, n in RET_DAYS.items()}, "last": s.index[-1].strftime("%m/%d"),
                   "spark": [round(float(x), 4) for x in (s.iloc[-(SPARK + 1):] / s.iloc[-(SPARK + 1)]).tolist()]}
            row["r"]["YTD"] = _r(_ytd(s))
            rows.append(row)
            flagged += bool(reasons)
        if not flagged:
            continue
        reasons = [{"name": r["name"], **x} for r in rows if r["flag"] for x in r["reasons"]]
        reasons.sort(key=lambda x: -x["score"])
        picks.append({"key": sec["key"], "source": "peer", "universe": sec["universe"],
                      "title": f"{sec['title']} — {catalog.UNIVERSE_LABEL[sec['universe']]}",
                      "link": sec["link"], "score": rules.total_score(reasons), "reasons": reasons,
                      "n_flag": flagged, "n_rows": len(rows),
                      "chart": {"type": "rows", "rows": rows}})
    picks.sort(key=lambda p: -p["score"])
    return picks, scanned


# ─────────────────────────── ② INDEX 비교 ───────────────────────────
def _window(prices, calendar_t, days):
    k = prices.get(calendar_t)
    if k is None:
        # KOSPI 가 없으면 가장 긴 종목 달력으로
        k = max(prices.values(), key=len)
    idx = k.index[-(days + 1):]
    return pd.DataFrame({t: s.reindex(idx, method="ffill") for t, s in prices.items()}).dropna(axis=1, how="all")


def _cap_weighted(df, items, caps):
    """생성기 cap_weighted 와 같은 산식 — 창 시작일 USD 시총(현재 시총 × 시작가/현재가) 고정 가중."""
    cols, w = [], []
    for name, t in items:
        if t in df.columns and caps.get(t) and df[t].notna().all():
            cols.append(t)
            w.append(caps[t] * float(df[t].iloc[0]) / float(df[t].iloc[-1]))
    if not cols:
        return None, []
    tot = sum(w)
    rel = sum((df[c] / df[c].iloc[0] * 100) * (wi / tot) for c, wi in zip(cols, w))
    return rel, cols


def _line_values(df, line, caps):
    if line["kind"] == "single":
        t = line["items"][0][1]
        if t not in df.columns or not df[t].notna().all():
            return None, []
        return df[t] / df[t].iloc[0] * 100, [t]
    return _cap_weighted(df, line["items"], caps)


def index_picks(charts, prices, caps, calendar_t="^KS11"):
    short = _window(prices, calendar_t, INDEX_DAYS)
    long = _window(prices, calendar_t, LONG_DAYS)
    picks, scanned = [], 0
    for ch in charts:
        lines, reasons, ranks = [], [], []
        for ln in ch["lines"]:
            s, cols = _line_values(short, ln, caps)
            if s is None:
                continue
            scanned += 1
            lo, _ = _line_values(long, ln, caps)
            r_line, m = rules.price_flags((lo if lo is not None else s).tolist(), is_index=ln["kind"] == "index")
            label = ln["name"] + (f" ({len(cols)})" if ln["kind"] == "index" and len(ln["items"]) > 1 and "(" not in ln["name"] else "")
            lines.append({"name": label, "kind": ln["kind"], "flag": bool(r_line),
                          "v": [round(float(x), 2) for x in s.tolist()], "r1w": _r(m["r1w"]), "z1w": _r(m["z1w"], 2)})
            reasons += [{"name": label, **x} for x in r_line]
            ranks.append((label, float(s.iloc[-6]) if len(s) > 5 else None, float(s.iloc[-1])))
        rc = rules.rank_change(ranks)
        if rc:
            reasons.append({"name": "", **rc})
        if not reasons:
            continue
        reasons.sort(key=lambda x: -x["score"])
        picks.append({"key": ch["key"], "source": "index", "universe": ch["universe"],
                      "title": f"{ch['no']}. {ch['title']} — {catalog.UNIVERSE_LABEL[ch['universe']]}",
                      "link": ch["link"], "score": rules.total_score(reasons), "reasons": reasons,
                      "chart": {"type": "lines", "dates": [d.strftime("%y%m%d") for d in short.index], "lines": lines,
                                "note": f"{INDEX_DAYS}거래일 전 = 100 · 묶음은 기준일 USD 시총 가중"}})
    picks.sort(key=lambda p: -p["score"])
    return picks, scanned


# ─────────────────────────── ③ 수급 그림 ───────────────────────────
def flow_picks(groups, names, series):
    picks, scanned = [], 0
    for g in groups:
        items = []
        for code in g["codes"]:
            s = series.get(code)
            if not s:
                continue
            scanned += 1
            reasons = []
            for key, label in (("fr", "외인"), ("in", "기관")):
                r, wk = rules.flow_flags(s["mc"], s[key], label)
                reasons += r
            if not reasons:
                continue
            reasons.sort(key=lambda x: -x["score"])
            d = s["d"]
            items.append({"code": code, "name": names.get(code, code), "reasons": reasons, "score": rules.total_score(reasons),
                          "chart": {"type": "flow", "d": [d[i:i + 6] for i in range(0, len(d), 6)],
                                    "mc": s["mc"], "fr": s["fr"], "in": s["in"]}})
        if not items:
            continue
        items.sort(key=lambda x: -x["score"])
        picks.append({"key": g["key"], "source": "flow", "title": g["title"], "link": g["link"],
                      "score": max(x["score"] for x in items),
                      "reasons": [{"name": it["name"], **x} for it in items for x in it["reasons"]],
                      "items": items})
    picks.sort(key=lambda p: -p["score"])
    return picks, scanned


# ─────────────────────────── ④ 컨센서스 ───────────────────────────
def _period_label(p, kind):
    y, m = str(p).split(".")
    return f"{y}E" if kind == "annual" else f"{int(m) // 3}Q{y[2:]}E"


def _read_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def consensus_picks(companies, quarter_rows, annual_rows, months=6):
    picks, scanned = [], 0
    by = {}
    for kind, rows in (("quarter", quarter_rows), ("annual", annual_rows)):
        for r in rows:
            by.setdefault((r["code"], kind, r["period"]), []).append((r["snapshot_date"], r["op_profit"]))
    latest_date = max((d for v in by.values() for d, _ in v), default=None)
    if latest_date is None:
        return picks, 0
    since = (datetime.fromisoformat(latest_date) - timedelta(days=30 * months)).date().isoformat()
    for sector, name, code in companies:
        lines, reasons = [], []
        for (c, kind, period), pts in sorted(by.items(), key=lambda kv: (kv[0][1], kv[0][2])):
            if c != code:
                continue
            pts = sorted(pts)
            if pts[-1][0] != latest_date:     # 최신 스냅샷에 없는 기간(지난 분기)은 그림에서 뺀다
                continue
            scanned += 1
            label = _period_label(period, kind)
            r, m = rules.consensus_flags(pts, label)
            reasons += r
            keep = [(d, v) for d, v in pts if d >= since]
            lines.append({"name": label, "kind": kind, "flag": bool(r), "d": [d for d, _ in keep],
                          "v": [rules._f(v) for _, v in keep]})
        if not reasons:
            continue
        reasons.sort(key=lambda x: -x["score"])
        picks.append({"key": f"cons:{code}", "source": "cons", "title": f"{name} — {sector}", "link": "consensus_chart.html",
                      "score": rules.total_score(reasons), "reasons": reasons,
                      "chart": {"type": "cons", "lines": lines, "note": "영업이익 컨센서스(억원) · 스냅샷 날짜 기준"}})
    picks.sort(key=lambda p: -p["score"])
    return picks, scanned


# ─────────────────────────── ⑤ ER ───────────────────────────
PERIOD_LABEL = {"0y": "FY1", "+1y": "FY2", "0q": "0Q", "+1q": "+1Q"}
ER_PERIODS = ("0y", "+1y")   # 연간만 — 분기 EPS 는 작아서 1건에도 수십 % 가 튄다(ER 페이지 기본도 FY1/FY2)


def er_picks(rows):
    picks, scanned = [], 0
    by = {}
    for r in rows:
        if r["period"] not in ER_PERIODS:
            continue
        by.setdefault((r["ticker"], r["period"]), []).append(r)
    latest = max((r["date"] for r in rows), default=None)
    if latest is None:
        return picks, 0
    sectors = {}
    for (t, period), rs in by.items():
        rs.sort(key=lambda r: r["date"])
        cur = rs[-1]
        if cur["date"] != latest:
            continue
        scanned += 1
        d1 = datetime.fromisoformat(cur["date"])
        prev = [r for r in rs if (d1 - datetime.fromisoformat(r["date"])).days >= 5]
        reasons = rules.er_flags(cur, prev[-1] if prev else None)
        if not reasons:
            continue
        sectors.setdefault(cur["sector"], []).append({
            "name": cur["name"], "ticker": t, "period": PERIOD_LABEL.get(period, period), "region": cur.get("region", ""),
            "n": rules._f(cur["n_analysts"]), "er30": rules._f(cur["er30"]), "er7": rules._f(cur["er7"]),
            "eps1m": rules._f(cur["eps_chg_1m"]), "eps3m": rules._f(cur["eps_chg_3m"]),
            "up30": rules._f(cur["up30"]), "down30": rules._f(cur["down30"]),
            "flip": any(x["kind"] == "epsflip" for x in reasons),
            "reasons": reasons, "score": rules.total_score(reasons)})
    for sector, items in sectors.items():
        items.sort(key=lambda x: -x["score"])
        picks.append({"key": f"er:{sector}", "source": "er", "title": f"Earnings Revision — {sector}",
                      "link": f"er_report.html?s={sector}", "score": max(x["score"] for x in items),
                      "reasons": [{"name": f"{it['name']} {it['period']}", **x} for it in items for x in it["reasons"]],
                      "chart": {"type": "er", "rows": items, "date": latest}})
    picks.sort(key=lambda p: -p["score"])
    return picks, scanned


# ─────────────────────────── 조립 ───────────────────────────
SOURCES = [
    ("peer", "📈 피어그룹 주가변동표", "peer_price.html", "섹션(낱장 그림) 단위 — 1주 등락 ±8%(지수 ±6%), 직전 52주 대비 z ±2, 52주 신고가·신저가"),
    ("index", "⚔️ 주가 INDEX 비교", "ship_index.html", "그림 단위 — 선(종목·시총가중 묶음)의 1주 등락·z, 선두 교체"),
    ("flow", "💰 수급 그림", "coverage_flow_report.html#weekly", "종목 단위 — 외인/기관 1주 순매수가 시총의 0.4% 이상·직전 주 대비 z ±2·1년 최대·누적 부호 전환"),
    ("cons", "📊 컨센서스 (조선·방산·건기)", "consensus_chart.html", "회사 단위 — 영업이익 컨센 1주 ±3% · 1개월 ±10% · 흑자/적자 전환"),
    ("er", "📐 ER (Earnings Revision)", "er_report.html", "섹터 표(FY1·FY2) — |ER30| ≥ 60 · EPS 컨센 1M ±8% · 3M ±15% · ER 한 주 40pp 이상 이동 (애널 3명 이상)"),
]


def build(demo=False, out_dir=OUT_DIR):
    peer = catalog.peer_sections()
    index = catalog.index_charts()
    groups, names = catalog.flow_groups()
    companies = catalog.consensus_companies()
    tickers = catalog.all_price_tickers(peer, index)
    log(f"📋 주가변동표 {len(peer)}섹션 · INDEX {len(index)}그림 · 수급 {len(groups)}묶음 · 컨센 {len(companies)}사 · 티커 {len(tickers)}")

    if demo:
        prices = demo_prices(tickers)
        caps = {t: 1000.0 * (i + 1) for i, t in enumerate(catalog.index_tickers(index))}
    else:
        prices = fetch_prices(tickers)
        import importlib
        base = importlib.import_module("weekly_peer_price_image")
        caps = base.fetch_market_caps_usd_m([t for t in catalog.index_tickers(index) if t in prices])
    log(f"💹 시세 {len(prices)}/{len(tickers)} · 시총 {len(caps)}")

    with open(SERIES_JSON, encoding="utf-8") as f:
        series = json.load(f)
    cons_dir = os.path.join(catalog.ECOS_DIR, "output", "consensus")
    q_rows = _read_csv(os.path.join(cons_dir, "컨센서스_추이_분기.csv"))
    a_rows = _read_csv(os.path.join(cons_dir, "컨센서스_추이_연간.csv"))
    er_rows = _read_csv(os.path.join(catalog.ECOS_DIR, "output", "earnings_revision", "er_history.csv"))

    result = {}
    result["peer"] = peer_picks(peer, prices)
    result["index"] = index_picks(index, prices, caps)
    result["flow"] = flow_picks(groups, names, series)
    result["cons"] = consensus_picks(companies, q_rows, a_rows)
    result["er"] = er_picks(er_rows)

    stock_t = {t for s in peer if s["stock"] for _, _, t in s["rows"]}
    last_dates = [s.index[-1] for t, s in prices.items() if t in stock_t and s.index[-1].weekday() < 5]
    asof = (max(last_dates) if last_dates else datetime.today()).date()
    flow_asof = None
    if series:
        d = max((v["d"][-6:] for v in series.values() if v and v.get("d")), default=None)
        flow_asof = f"20{d[:2]}-{d[2:4]}-{d[4:]}" if d else None
    payload = {
        "asof": asof.isoformat(), "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "week": {"start": (asof - timedelta(days=asof.weekday())).isoformat(), "end": asof.isoformat()},
        "demo": demo,
        "sources": [{"key": k, "title": title, "link": link, "rule": rule,
                     "picks": result[k][0], "scanned": result[k][1]} for k, title, link, rule in SOURCES],
        "asof_detail": {"prices": asof.isoformat(), "flow": flow_asof,
                        "cons": max((r["snapshot_date"] for r in q_rows + a_rows), default=None),
                        "er": max((r["date"] for r in er_rows), default=None)},
        "thresholds": rules.TH,
    }
    os.makedirs(out_dir, exist_ok=True)
    name = f"{asof.isoformat()}.json"
    txt = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    for fn in (name, "latest.json"):
        with open(os.path.join(out_dir, fn), "w", encoding="utf-8") as f:
            f.write(txt)
    dates = sorted({fn[:-5] for fn in os.listdir(out_dir) if fn.endswith(".json") and fn[:4].isdigit()}, reverse=True)
    with open(os.path.join(out_dir, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"dates": dates, "latest": asof.isoformat()}, f, ensure_ascii=False)
    for s in payload["sources"]:
        log(f"  {s['title']}: {len(s['picks'])}건 꼽힘 / {s['scanned']} 훑음")
        for pk in s["picks"]:   # 러너 로그에서 바로 보게(아티팩트를 못 받는 환경에서 임계 조정용)
            why = " / ".join(f"{r.get('name', '')} {r['text']}".strip() for r in pk["reasons"][:4])
            log(f"     · {pk['title']} [{pk['score']}] {why}")
    log(f"✅ {os.path.join(out_dir, name)} ({len(txt) // 1024}KB)")
    return payload


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="야후 없이 가짜 시세로(컨센·ER·수급은 실제 파일)")
    ap.add_argument("--out", default=OUT_DIR)
    a = ap.parse_args()
    build(demo=a.demo, out_dir=a.out)
