# -*- coding: utf-8 -*-
"""커버리지 종목 수급·기술지표 수집 → data/latest.json (+ data/history/<날짜_슬롯>.json).

흐름: 거래일 게이트 → 종목별 KIS(현재가·일봉·투자자) → 섹터 ETF(KIS 상장주수 + 네이버
구성 비중) → 패시브 추정 → 액티브 ETF(etf_holdings/changes.json) → 저장.

평일 11:30(장중)·16:00(장 마감 후) 하루 2회 돈다 — '오늘' 숫자는 당일 잠정 집계다 — 저장 데이터에
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

# 수집 부족 가드 — 이 비율 미만이면 저장·커밋·텔레 전부 막는다(10/19 실측: 한투 토큰 403 으로
# 21종목 중 2종목만 모인 화면이 채널에 나갔다). 직전 정상 페이지를 그대로 두는 편이 낫다.
MIN_OK_RATIO = float(os.environ.get("COVFLOW_MIN_OK_RATIO", "0.7"))


def enough(n_ok, n_total, ratio=None):
    """수집 성공 종목이 유니버스의 ratio 이상인가. 유니버스가 비면 False(아무것도 없는 run 은 실패)."""
    r = MIN_OK_RATIO if ratio is None else ratio
    return n_total > 0 and n_ok >= n_total * r

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
# 종목별 일별 수급(수량) — pageSize 상한 60, page 는 무시, **bizdate 커서**(그 날짜 이전 60행)로
# 뒤로 넘긴다(10/19 프로브 실측: bizdate=20260720 → 7/16~4/20). 3개월·YTD 구간의 소스.
NAVER_TREND = "https://m.stock.naver.com/api/stock/{code}/trend?pageSize=60"
TREND_MAX_PAGES = 8   # 60×8 = 480행 ≈ 2년 — YTD 는 늦어도 4~5페이지 안에 전년으로 넘어간다


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


def naver_etf_analysis(code):
    """네이버 etfAnalysis → (구성 Top10 [{code,name,weight}], 순유입 {inflow_1d, inflow_1w, inflow_ref}).
    순유입(cumulativeNetInflowList)은 네이버가 집계한 설정·환매 금액(억) — 기준일이 하루 늦지만
    우리 상장주수 차분의 교차 확인용으로 ETF 표에 같이 적는다(10/17 프로브로 확인)."""
    j = requests.get(NAVER_ETF.format(code=code), headers=NAVER_H, timeout=15).json()
    top = j.get("etfTop10MajorConstituentAssets") or []
    hold = [{"code": (h.get("itemCode") or "").strip(), "name": h.get("itemName", ""),
             "weight": _num(h.get("etfWeight"))} for h in top if h.get("itemCode")]
    inf = j.get("cumulativeNetInflowList") or {}
    flow = {"inflow_1d": metrics.parse_eok(inf.get("cumulativeNetInflow1d")),
            "inflow_1w": metrics.parse_eok(inf.get("cumulativeNetInflow1w")),
            "inflow_ref": inf.get("referenceDate", "")}
    return hold, flow


def naver_investor_history(code, until):
    """네이버 trend 를 bizdate 커서로 `until`(YYYYMMDD) 이전 날짜가 나올 때까지 긁어 행 목록으로.
    until 은 보통 전년 12/31 — flow_windows 의 YTD 판정은 전년 행이 하나라도 있어야 선다."""
    rows, cursor = [], None
    for _ in range(TREND_MAX_PAGES):
        url = NAVER_TREND.format(code=code) + (f"&bizdate={cursor}" if cursor else "")
        r = requests.get(url, headers=NAVER_H, timeout=15)
        r.raise_for_status()
        page = r.json()
        if not isinstance(page, list) or not page:
            break
        rows += page
        last = str(page[-1].get("bizdate", ""))
        if not last or last <= until or len(page) < 60:
            break
        cursor = last
        time.sleep(0.1)
    return rows


def collect_stock(u, today, live=True):
    """live=False(휴장일·--force 테스트)면 현재가를 '오늘 잠정 봉' 으로 붙이지 않는다 —
    금요일 종가를 토요일 잠정치로 찍으면 거짓 라벨이다."""
    code = u["code"]
    px = kis.fetch_price(code)
    time.sleep(0.12)
    ohlc = kis.fetch_ohlc(code)
    time.sleep(0.12)
    inv = kis.fetch_investor(code)
    time.sleep(0.12)
    # 3개월·YTD 는 한투 30행으로 부족 → 네이버 trend(수량×종가 근사)로 전년까지 보충.
    # 네이버가 죽어도 한투 30행으로 오늘·5일·1개월은 그대로 나온다(그 구간만 '–').
    try:
        until = f"{int(today[:4]) - 1}1231"
        inv = kis.merge_investor(inv, kis.naver_trend_frame(naver_investor_history(code, until)))
    except Exception as ex:
        print(f"  {u['name']} 네이버 수급 이력 실패(한투 30행만 사용): {type(ex).__name__}: {ex}")
    est_note = None
    if live:
        # 장중엔 일별 투자자 API 의 오늘 행이 0 이라 추정가집계로 채운다(실패하면 그대로 0/없음).
        try:
            est = kis.fetch_estimate(code)
            time.sleep(0.12)
            inv, applied = metrics.apply_estimate(inv, today, est, px.get("price"))
            if applied:
                est_note = est["time"]
        except Exception as ex:
            print(f"  {u['name']} 추정가집계 실패(오늘 값 미보정): {type(ex).__name__}: {ex}")
    if not live:
        # 장 시작 전·휴장일: 소스가 미리 내주는 '오늘 0' 행을 버리고 KIS 전일대비(0.00)도 안 쓴다.
        # 외국인 보유비율도 장 전엔 0.00 으로 와서(10/19 05:57 실측) 0 은 '모름' 으로 읽는다.
        inv = metrics.drop_today(inv, today)
        if not px.get("frgn_pct"):
            px["frgn_pct"] = None
    tech = metrics.technicals(ohlc, today, px.get("price") if live else None)
    tech["ret"] = metrics.returns(ohlc, today, px.get("price") if live else None,
                                  px.get("chg_pct") if live else None)
    tech["spark"] = metrics.spark_points(ohlc, today, px.get("price") if live else None)
    flow = metrics.flow_summary(inv, today, px.get("mcap"))
    flow["today_src"] = f"estimate {est_note}" if est_note else "daily"
    return {**u, "px": px, "tech": tech, "flow": flow}


def collect_etfs(etf_rows):
    out, errors = [], []
    for e in etf_rows:
        try:
            px = kis.fetch_price(e["code"])
            time.sleep(0.12)
            hold, inflow = naver_etf_analysis(e["code"])
            name = px.get("name") or e["name"]
            # 코드가 틀려 엉뚱한 종목을 받아오면 조용히 섞이지 않게 이름 키워드로 거른다
            if not any(k in name for k in ("조선", "방산", "기계", "해운", "디펜스", "중공업")):
                errors.append(f"{e['code']} 이름 불일치: {name!r}")
                continue
            out.append({"code": e["code"], "name": name, "sector": e.get("sector", ""),
                        "listed": px.get("listed"), "price": px.get("price"), "holdings": hold, **inflow})
        except Exception as ex:
            errors.append(f"{e['code']} {e['name']}: {type(ex).__name__}: {ex}")
    return out, errors


def probe_flow(code):
    """러너 프로브: 종목별 일별 수급을 얼마나 길게 받을 수 있나.
    KIS inquire-investor 행 수·날짜 범위 + 네이버 종목 trend API 후보들의 응답 키."""
    try:
        inv = kis.fetch_investor(code)
        print(f"== KIS inquire-investor rows={len(inv)} range={inv['date'].min().date() if len(inv) else '-'} ~ {inv['date'].max().date() if len(inv) else '-'}")
    except Exception as ex:
        print("KIS inquire-investor 실패:", ex)
    # 1차 프로브(10/19 05:52 KST): KIS 30행(9/2~10/19), 네이버 /api/stock/{code}/trend 는
    # pageSize=60 에 60행(7/20~10/16, 수량+종가), page 파라미터는 무시(page=4 가 page=1 과 동일),
    # front-api /stock/domestic/trend 는 reutersCode 로 400. → pageSize 상한과 bizdate 커서를 본다.
    cands = [
        f"https://m.stock.naver.com/api/stock/{code}/trend?pageSize=120",
        f"https://m.stock.naver.com/api/stock/{code}/trend?pageSize=300",
        f"https://m.stock.naver.com/api/stock/{code}/trend?pageSize=600",
        f"https://m.stock.naver.com/api/stock/{code}/trend?pageSize=60&bizdate=20260720",
        f"https://m.stock.naver.com/api/stock/{code}/trend?pageSize=60&endDate=20260720",
        f"https://m.stock.naver.com/api/stock/{code}/trend?pageSize=60&startDate=20260101&endDate=20260720",
    ]
    for url in cands:
        try:
            r = requests.get(url, headers=NAVER_H, timeout=15)
            body = r.text
            print(f"== {url}\n   status={r.status_code} len={len(body)}")
            try:
                j = r.json()
                items = j if isinstance(j, list) else (j.get("result") or j.get("data") or j.get("items") or j)
                if isinstance(items, dict):
                    print("   top keys:", list(items.keys())[:20])
                    for k, v in items.items():
                        if isinstance(v, list) and v and isinstance(v[0], dict):
                            print(f"   list '{k}' n={len(v)} first keys:", list(v[0].keys()))
                            print("   first:", {kk: str(vv)[:30] for kk, vv in v[0].items()})
                            print("   last :", {kk: str(vv)[:30] for kk, vv in v[-1].items()})
                            break
                elif isinstance(items, list):
                    print(f"   list n={len(items)}")
                    if items and isinstance(items[0], dict):
                        print("   first keys:", list(items[0].keys()))
                        print("   first:", {kk: str(vv)[:30] for kk, vv in items[0].items()})
                        print("   last :", {kk: str(vv)[:30] for kk, vv in items[-1].items()})
            except Exception:
                print("   body:", body[:300].replace("\n", " "))
        except Exception as ex:
            print(url, "실패:", ex)
    return 0


def probe_estimate(code):
    """러너 프로브: 종목별 외인기관 추정가집계(HHPTJ04160200) 원본 응답 — 키 이름·시각 구분 확인용."""
    j = kis.fetch_estimate_raw(code)
    print(json.dumps(j, ensure_ascii=False, indent=1)[:4000])
    print("== parse_estimate →", kis.parse_estimate(j))
    return 0


def probe_etf(code):
    """러너 프로브: ETF 상장주수를 어디서 받을 수 있는지 응답 키를 찍는다.
    첫 실행(10/17)에서 주식용 inquire-price 의 lstn_stcn 이 ETF 7개 전부 None 이었다."""
    def show(label, obj):
        print(f"== {label}")
        if isinstance(obj, dict):
            for k, v in obj.items():
                print(f"   {k}: {str(v)[:80]}")
        else:
            print("  ", str(obj)[:400])
    try:
        j = kis.get("/uapi/domestic-stock/v1/quotations/inquire-price", "FHKST01010100",
                    {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})
        show("KIS inquire-price(J) output", j.get("output"))
    except Exception as ex:
        print("KIS inquire-price(J) 실패:", ex)
    try:
        j = kis.get("/uapi/etfetn/v1/quotations/inquire-price", "FHPST02400000",
                    {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})
        show("KIS etfetn inquire-price output", j.get("output"))
    except Exception as ex:
        print("KIS etfetn inquire-price 실패:", ex)
    for url in (NAVER_ETF.format(code=code), f"https://m.stock.naver.com/api/stock/{code}/basic",
                f"https://m.stock.naver.com/api/stock/{code}/integration"):
        try:
            j = requests.get(url, headers=NAVER_H, timeout=15).json()
            top = {k: v for k, v in j.items() if not isinstance(v, (list, dict))}
            show(url, top)
            for k, v in j.items():
                if isinstance(v, dict):
                    show(f"  └ {k}", {kk: vv for kk, vv in v.items() if not isinstance(vv, (list, dict))})
        except Exception as ex:
            print(url, "실패:", ex)
    return 0


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


def backfill_frgn(rows, prev_latest):
    """외인 보유비율 None 을 직전 스냅샷 값으로 채운다(기준일 frgn_pct_asof 병기).

    장 시작 전·휴장일엔 한투가 0을 줘 None 으로 비는데, 보유비율은 하루 사이 거의
    안 변한다 → 직전 값으로 채우되 어느 날 값인지 남겨 '오늘 값'처럼 보이지 않게 한다.
    직전 값도 이월분이면 원 날짜를 승계. 당일 실측값이 있는 행은 건드리지 않는다.
    """
    prev_px = {r.get("code"): (r.get("px") or {}) for r in (prev_latest or {}).get("rows") or []}
    for r in rows:
        px = r.get("px") or {}
        if px.get("frgn_pct") is None:
            old = prev_px.get(r.get("code")) or {}
            # 직전 값이 0 이면 안 가져온다 — 장 전 수집이 남긴 '가짜 0'과 진짜 0을
            # 소스가 구분해 주지 않아서, 이월하면 모름이 0.00%로 둔갑한다.
            if old.get("frgn_pct"):
                px["frgn_pct"] = old["frgn_pct"]
                px["frgn_pct_asof"] = (old.get("frgn_pct_asof")
                                       or prev_latest.get("market_day") or prev_latest.get("date"))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="휴장일 게이트 무시")
    ap.add_argument("--limit", type=int, default=0, help="종목 수 제한(프로브용)")
    ap.add_argument("--probe-etf", action="store_true", help="ETF 상장주수 소스 탐색 — 응답 키만 찍고 끝(저장 없음)")
    ap.add_argument("--probe-flow", action="store_true", help="종목별 수급 이력 길이 탐색(KIS 행수·네이버 trend) — 저장 없음")
    ap.add_argument("--probe-estimate", action="store_true", help="종목별 외인기관 추정가집계 원본 응답 출력 — 저장 없음")
    a = ap.parse_args(argv)

    now = datetime.now(KST)
    today = now.date().isoformat()
    if a.probe_etf:   # 휴장일 게이트보다 먼저 — 프로브는 거래일과 무관
        return probe_etf(load_csv("etf_universe.csv")[0]["code"])
    if a.probe_flow:
        return probe_flow(load_csv("universe.csv")[0]["code"])
    if a.probe_estimate:
        return probe_estimate(load_csv("universe.csv")[0]["code"])
    mday, mstatus = market_day()
    if mday and mday != today and not a.force:
        print(f"휴장일로 판단(마지막 거래일 {mday}) — 수집 생략")
        return 0
    slot = metrics.decide_slot(now)
    live = (mday == today) or not mday   # 거래일을 모르면 평소대로(fail-open)
    uni = load_csv("universe.csv")
    if a.limit:
        uni = uni[:a.limit]
    rows, errors = [], []
    for u in uni:
        try:
            rows.append(collect_stock(u, today, live))
            print(f"  {u['name']:<14} RSI {rows[-1]['tech'].get('rsi')}  5일 외인+기관 {rows[-1]['flow'].get('fi5')}")
        except Exception as ex:
            errors.append(f"{u['code']} {u['name']}: {type(ex).__name__}: {ex}")
            print(f"  {u['name']} 실패: {ex}")

    if not enough(len(rows), len(uni)):
        print(f"수집 부족 — {len(rows)}/{len(uni)}종목(기준 {MIN_OK_RATIO:.0%}). 저장·발송하지 않고 실패로 끝낸다.")
        for e in errors:
            print("  " + e)
        return 2

    etfs, etf_err = collect_etfs(load_csv("etf_universe.csv"))
    errors += etf_err
    backfill_frgn(rows, load_json(LATEST, {}))   # LATEST 를 덮어쓰기 전에 읽어야 한다
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
