# -*- coding: utf-8 -*-
"""커버리지 종목 수급·기술지표 수집 → data/latest.json (+ data/history/<날짜_슬롯>.json).

흐름: 거래일 게이트 → 종목별 KIS(현재가·일봉·투자자) → 섹터 ETF(KIS 상장주수 + 네이버
구성 비중) → 패시브 추정 → 액티브 ETF(etf_holdings/changes.json) → 저장.

장중 3회(10:00·13:30·15:30) 돌므로 '오늘' 숫자는 전부 **잠정**이다 — 저장 데이터에
provisional 플래그를 남기고 화면·텔레가 그대로 적는다.
"""
from __future__ import annotations
import os, sys, csv, json, time, argparse
import requests
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import kis, metrics  # noqa: E402

KST = timezone(timedelta(hours=9))
DATA = os.path.join(HERE, "data")
HIST = os.path.join(DATA, "history")
LATEST = os.path.join(DATA, "latest.json")
SHARES = os.path.join(DATA, "etf_shares.json")
CHANGES = os.path.join(ROOT, "etf_holdings", "changes.json")

NAVER_ETF = "https://m.stock.naver.com/api/stock/{code}/etfAnalysis"
NAVER_H = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605",
           "Referer": "https://m.stock.naver.com/"}
INDEX_BASIC = "https://m.stock.naver.com/api/index/KOSPI/basic"


def load_csv(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r.get("code")]


def market_day():
    """거래소 마지막 거래일·장 상태. 못 가져오면 ('','') → fail-open(그냥 실행)."""
    try:
        j = requests.get(INDEX_BASIC, headers=NAVER_H, timeout=15).json()
        return (j.get("localTradedAt", "")[:10], j.get("marketStatus", ""))
    except Exception:
        return ("", "")


def _num(s):
    try:
        return float(str(s).replace(",", "").replace("%", ""))
    except Exception:
        return 0.0


def naver_etf_holdings(code):
    """네이버 etfAnalysis → [{code, name, weight}] (Top10, 비중 %)."""
    j = requests.get(NAVER_ETF.format(code=code), headers=NAVER_H, timeout=15).json()
    top = j.get("etfTop10MajorConstituentAssets") or []
    return [{"code": (h.get("itemCode") or "").strip(), "name": h.get("itemName", ""),
             "weight": _num(h.get("etfWeight"))} for h in top if h.get("itemCode")]


def collect_stock(u, today):
    code = u["code"]
    px = kis.fetch_price(code)
    time.sleep(0.12)
    ohlc = kis.fetch_ohlc(code)
    time.sleep(0.12)
    inv = kis.fetch_investor(code)
    time.sleep(0.12)
    tech = metrics.technicals(ohlc, today, px.get("price"))
    flow = metrics.flow_summary(inv, today, px.get("mcap"))
    return {**u, "px": px, "tech": tech, "flow": flow}


def collect_etfs(etf_rows):
    out, errors = [], []
    for e in etf_rows:
        try:
            px = kis.fetch_price(e["code"])
            time.sleep(0.12)
            hold = naver_etf_holdings(e["code"])
            name = px.get("name") or e["name"]
            # 코드가 틀려 엉뚱한 종목을 받아오면 조용히 섞이지 않게 이름 키워드로 거른다
            if not any(k in name for k in ("조선", "방산", "기계", "해운", "디펜스", "중공업")):
                errors.append(f"{e['code']} 이름 불일치: {name!r}")
                continue
            out.append({"code": e["code"], "name": name, "sector": e.get("sector", ""),
                        "listed": px.get("listed"), "price": px.get("price"), "holdings": hold})
        except Exception as ex:
            errors.append(f"{e['code']} {e['name']}: {type(ex).__name__}: {ex}")
    return out, errors


def load_json(p, default):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def update_shares(etfs, today, prev_store):
    """상장주수 기록 {etf: {date: listed}} — 패시브 추정의 '직전 값'은 **오늘이 아닌 가장 최근 날짜**.
    같은 날 두 번째 슬롯은 아침 슬롯과 같은 직전(전일) 값을 쓰므로 하루 누적 설정·환매가 된다."""
    store = dict(prev_store)
    prev = {}
    for e in etfs:
        hist = store.setdefault(e["code"], {})
        past = sorted(d for d in hist if d < today)
        if past:
            prev[e["code"]] = hist[past[-1]]
        if e.get("listed"):
            hist[today] = e["listed"]
        # 60일만 보관
        for d in sorted(hist)[:-60]:
            hist.pop(d, None)
    return store, prev


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="휴장일 게이트 무시")
    ap.add_argument("--limit", type=int, default=0, help="종목 수 제한(프로브용)")
    a = ap.parse_args(argv)

    now = datetime.now(KST)
    today = now.date().isoformat()
    mday, mstatus = market_day()
    if mday and mday != today and not a.force:
        print(f"휴장일로 판단(마지막 거래일 {mday}) — 수집 생략")
        return 0
    slot = metrics.decide_slot(now)
    uni = load_csv("universe.csv")
    if a.limit:
        uni = uni[:a.limit]
    rows, errors = [], []
    for u in uni:
        try:
            rows.append(collect_stock(u, today))
            print(f"  {u['name']:<14} RSI {rows[-1]['tech'].get('rsi')}  5일 외인+기관 {rows[-1]['flow'].get('fi5')}")
        except Exception as ex:
            errors.append(f"{u['code']} {u['name']}: {type(ex).__name__}: {ex}")
            print(f"  {u['name']} 실패: {ex}")

    etfs, etf_err = collect_etfs(load_csv("etf_universe.csv"))
    errors += etf_err
    store, prev = update_shares(etfs, today, load_json(SHARES, {}))
    per_stock, per_etf = metrics.passive_flow(etfs, prev)
    for r in rows:
        p = per_stock.get(r["code"])
        adv = r["tech"].get("adv20")
        r["passive"] = ({"amt": p["amt"], "adv_pct": metrics.adv_pct(p["amt"], adv), "etfs": p["etfs"]}
                        if p else None)

    changes = load_json(CHANGES, {})
    codes = {r["code"] for r in rows}
    active = metrics.active_etf_hits(changes, codes)

    payload = {
        "asof": now.strftime("%Y-%m-%d %H:%M"), "date": today, "slot": slot,
        "market_day": mday, "market_status": mstatus,
        "universe": len(uni), "rows": rows,
        "etfs": per_etf, "etf_weights_source": "naver_top10",
        "active": active, "active_date": changes.get("date", ""),
        "errors": errors,
        "note": "규칙 기반 상태값이며 검증 전. 패시브는 섹터 ETF 7개 Top10 비중 기준 하한값. 장중 숫자는 잠정치.",
    }
    os.makedirs(HIST, exist_ok=True)
    with open(LATEST, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    with open(os.path.join(HIST, f"{today}_{slot.replace(':', '')}.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    with open(SHARES, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=1)
    # 30일 지난 히스토리 정리
    cutoff = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    for fn in os.listdir(HIST):
        if fn[:10] < cutoff:
            os.remove(os.path.join(HIST, fn))
    print(f"저장: 종목 {len(rows)}/{len(uni)} · ETF {len(etfs)} · 액티브 히트 {len(active)} · 오류 {len(errors)}")
    for e in errors:
        print("  !", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
