# -*- coding: utf-8 -*-
"""55개 ETF 신호 스캔 엔진.
- 일봉(ADX/DI, Stochastic Slow) + 수급(외인/기관/개인 5일) + 거래대금(유동성)
- '오늘 새로 뜬' 크로스오버를 이벤트로 표시 (마지막 2봉 비교 → 상태파일 불필요)
- 신호는 '전일 확정 종가' 기준: 오늘(미완성) 봉은 제외
결과: signals.json  (HTML/텔레그램이 이 파일을 읽음)
"""
from __future__ import annotations
import os, json, time, csv, requests
import pandas as pd, numpy as np
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
KST = timezone(timedelta(hours=9))
BASE = "https://openapi.koreainvestment.com:9443"
LIQ_MIN_EOK = 5          # 20일 평균 거래대금 5억 미만 = 저유동성(알림 제외)

# ── 키 로딩: 로컬 .env → 없으면 환경변수(GitHub Actions) ──
def _load_keys():
    p = os.path.join(HERE, ".env")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    return os.environ["KIS_APP_KEY"], os.environ["KIS_APP_SECRET"]

APP_KEY, APP_SECRET = _load_keys()

_c = {"t": None, "ts": 0}
def token():
    if _c["t"] and time.time() - _c["ts"] < 60*60*23:
        return _c["t"]
    r = requests.post(f"{BASE}/oauth2/tokenP",
        json={"grant_type": "client_credentials", "appkey": APP_KEY, "appsecret": APP_SECRET})
    r.raise_for_status()
    _c.update(t=r.json()["access_token"], ts=time.time())
    return _c["t"]

def H(tr):
    return {"authorization": f"Bearer {token()}", "appkey": APP_KEY, "appsecret": APP_SECRET,
            "tr_id": tr, "custtype": "P"}

def _get(url, tr, params, tries=3):
    for k in range(tries):
        try:
            r = requests.get(url, headers=H(tr), params=params, timeout=15)
            r.raise_for_status()
            return r
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(0.7)

def fetch_ohlc(code, days=300):
    url = f"{BASE}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    start = (datetime.now(KST) - timedelta(days=days)).strftime("%Y%m%d")
    cur = datetime.now(KST).strftime("%Y%m%d"); rows = []
    for _ in range(8):
        p = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
             "FID_INPUT_DATE_1": start, "FID_INPUT_DATE_2": cur,
             "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0"}
        r = _get(url, "FHKST03010100", p)
        d = [x for x in r.json().get("output2", []) if x.get("stck_bsop_date")]
        if not d: break
        rows += d; old = min(x["stck_bsop_date"] for x in d)
        if old <= start: break
        cur = (datetime.strptime(old, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d"); time.sleep(0.12)
    df = pd.DataFrame(rows).drop_duplicates("stck_bsop_date")
    for a, b in [("o","stck_oprc"),("h","stck_hgpr"),("l","stck_lwpr"),("c","stck_clpr"),("v","acml_vol")]:
        df[a] = pd.to_numeric(df[b], errors="coerce")
    df["date"] = pd.to_datetime(df["stck_bsop_date"])
    df = df[["date","o","h","l","c","v"]].sort_values("date").reset_index(drop=True)
    # 신호는 '전일 확정' 기준 → 오늘(미완성) 봉 제거
    today = pd.Timestamp(datetime.now(KST).date())
    df = df[df["date"] < today].reset_index(drop=True)
    return df

def fetch_flow(code):
    url = f"{BASE}/uapi/domestic-stock/v1/quotations/inquire-investor"
    r = _get(url, "FHKST01010900", {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})
    d = r.json().get("output", [])
    if not d: return pd.DataFrame()
    df = pd.DataFrame(d); df["date"] = pd.to_datetime(df["stck_bsop_date"])
    for a, b in [("개인","prsn_ntby_tr_pbmn"),("외국인","frgn_ntby_tr_pbmn"),("기관","orgn_ntby_tr_pbmn")]:
        df[a] = pd.to_numeric(df[b], errors="coerce") / 100   # 백만원→억원
    today = pd.Timestamp(datetime.now(KST).date())
    df = df[df["date"] < today]
    return df[["date","개인","외국인","기관"]].sort_values("date").reset_index(drop=True)

def adx_di(df, n=14):
    h, l, c = df["h"], df["l"], df["c"]; pc = c.shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    up = h.diff(); dn = -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    ndm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    a = 1/n; atr = tr.ewm(alpha=a, adjust=False).mean()
    pdi = 100*pdm.ewm(alpha=a, adjust=False).mean()/atr
    ndi = 100*ndm.ewm(alpha=a, adjust=False).mean()/atr
    dx = 100*(pdi-ndi).abs()/(pdi+ndi)
    return dx.ewm(alpha=a, adjust=False).mean(), pdi, ndi

def stoch_slow(df, n=14, k=3, d=3):
    ll = df["l"].rolling(n).min(); hh = df["h"].rolling(n).max()
    slowk = (100*(df["c"]-ll)/(hh-ll)).rolling(k).mean()
    return slowk, slowk.rolling(d).mean()

def load_universe():
    rows = []
    with open(os.path.join(HERE, "etf_universe.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("active") == "1":
                rows.append({"group": r["group"], "name": r["name"], "code": r["code"]})
    return rows

def scan_one(u):
    px = fetch_ohlc(u["code"]); fl = fetch_flow(u["code"])
    adx, pdi, ndi = adx_di(px); sk, sd = stoch_slow(px)
    turnover = float((px["c"] * px["v"]).tail(20).mean() / 1e8)   # 20일 평균 거래대금(억)
    f5 = fl.tail(5)[["개인","외국인","기관"]].sum() if len(fl) else None

    # 상태
    up_trend = bool(pdi.iloc[-1] > ndi.iloc[-1] and adx.iloc[-1] > 20)
    # 오늘 새로 뜬 크로스오버(마지막 2봉)
    ev_trend = bool(pdi.iloc[-1] > ndi.iloc[-1] and pdi.iloc[-2] <= ndi.iloc[-2])
    ev_stoch = bool(sk.iloc[-1] > sd.iloc[-1] and sk.iloc[-2] <= sd.iloc[-2])
    stoch_oversold = ev_stoch and bool(sk.iloc[-2] < 25)

    if f5 is not None:
        smart = bool(f5["외국인"] > 0 and f5["기관"] > 0)
        antp = bool(f5["개인"] > 0 and f5["외국인"] < 0 and f5["기관"] < 0)
        flow = "쌍끌이" if smart else ("개인몰림" if antp else "중립")
    else:
        flow = "수급없음"

    return {
        "group": u["group"], "name": u["name"], "code": u["code"],
        "close": int(px["c"].iloc[-1]), "asof": px["date"].iloc[-1].strftime("%Y-%m-%d"),
        "adx": round(float(adx.iloc[-1]), 1),
        "pdi": round(float(pdi.iloc[-1]), 1), "ndi": round(float(ndi.iloc[-1]), 1),
        "k": round(float(sk.iloc[-1]), 1), "d": round(float(sd.iloc[-1]), 1),
        "turnover": round(turnover, 1), "liquid": bool(turnover >= LIQ_MIN_EOK),
        "up_trend": up_trend, "ev_trend": ev_trend,
        "ev_stoch": ev_stoch, "stoch_oversold": stoch_oversold,
        "for5": None if f5 is None else round(float(f5["외국인"])),
        "org5": None if f5 is None else round(float(f5["기관"])),
        "ind5": None if f5 is None else round(float(f5["개인"])),
        "flow": flow,
        # 알림감: 오늘 골든(추세 or 과매도-스토캐스틱) + 개인몰림 아님 + 유동성 OK
        "alert": bool((ev_trend or stoch_oversold) and flow != "개인몰림" and turnover >= LIQ_MIN_EOK),
    }

def scan_all():
    uni = load_universe()
    out, errs = [], []
    for i, u in enumerate(uni, 1):
        try:
            rec = scan_one(u); out.append(rec)
            print(f"  [{i}/{len(uni)}] OK {u['name']}  ADX{rec['adx']} flow={rec['flow']}"
                  f"{'  ★ALERT' if rec['alert'] else ''}")
        except Exception as e:
            errs.append({"name": u["name"], "code": u["code"], "err": str(e)[:120]})
            print(f"  [{i}/{len(uni)}] ERR {u['name']}: {str(e)[:80]}")
        time.sleep(0.15)
    payload = {
        "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "signals": out, "errors": errs,
    }
    with open(os.path.join(HERE, "signals.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    alerts = [s for s in out if s["alert"]]
    print(f"\n스캔 {len(out)}/{len(uni)}개 완료 · 에러 {len(errs)} · 오늘 알림 {len(alerts)}개 → signals.json")
    return payload

if __name__ == "__main__":
    scan_all()
