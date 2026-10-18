# -*- coding: utf-8 -*-
"""한국투자증권 OpenAPI 얇은 클라이언트 — 커버리지 수급 모듈 전용.

etf_signal/etf_signal.py 의 호출 방식을 그대로 따르되, **모듈 임포트 때 키를 요구하지
않는다**(테스트·렌더는 키 없이 돈다). 키는 첫 호출 때 환경변수에서 읽는다.

쓰는 엔드포인트 3개:
  · inquire-daily-itemchartprice (FHKST03010100)  일봉 OHLCV — RSI·52주·거래대금
  · inquire-investor            (FHKST01010900)  종목별 일별 개인·외인·기관 순매수 금액
                                                 (장중엔 오늘 행이 잠정치로 섞여 온다)
  · inquire-price               (FHKST01010100)  현재가·시총·상장주수·외국인 보유비율
"""
from __future__ import annotations
import os, time, requests
import pandas as pd
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
BASE = "https://openapi.koreainvestment.com:9443"
_c = {"t": None, "ts": 0}


def _keys():
    k, s = os.environ.get("KIS_APP_KEY"), os.environ.get("KIS_APP_SECRET")
    if not k or not s:
        raise RuntimeError("KIS_APP_KEY/KIS_APP_SECRET 미설정")
    return k, s


def token():
    if _c["t"] and time.time() - _c["ts"] < 60 * 60 * 23:
        return _c["t"]
    k, s = _keys()
    r = requests.post(f"{BASE}/oauth2/tokenP", timeout=15,
                      json={"grant_type": "client_credentials", "appkey": k, "appsecret": s})
    r.raise_for_status()
    _c.update(t=r.json()["access_token"], ts=time.time())
    return _c["t"]


def _h(tr):
    k, s = _keys()
    return {"authorization": f"Bearer {token()}", "appkey": k, "appsecret": s,
            "tr_id": tr, "custtype": "P"}


def get(path, tr, params, tries=3):
    for i in range(tries):
        try:
            r = requests.get(BASE + path, headers=_h(tr), params=params, timeout=15)
            r.raise_for_status()
            j = r.json()
            if str(j.get("rt_cd", "0")) != "0":
                raise RuntimeError(f"KIS {tr} 오류: {j.get('msg1')}")
            return j
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(0.7)


def today_kst():
    return datetime.now(KST).date()


def fetch_ohlc(code, days=430):
    """일봉 DataFrame[date,o,h,l,c,v,amt(억원)] 오름차순. 오늘(미완성) 봉도 포함해 돌려주고
    잘라내는 건 호출부 몫이다 — 장중 잠정 RSI 에 오늘 현재가가 필요하다."""
    start = (datetime.now(KST) - timedelta(days=days)).strftime("%Y%m%d")
    cur = datetime.now(KST).strftime("%Y%m%d")
    rows = []
    for _ in range(8):
        p = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
             "FID_INPUT_DATE_1": start, "FID_INPUT_DATE_2": cur,
             "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0"}
        j = get("/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice", "FHKST03010100", p)
        d = [x for x in j.get("output2", []) if x.get("stck_bsop_date")]
        if not d:
            break
        rows += d
        old = min(x["stck_bsop_date"] for x in d)
        if old <= start:
            break
        cur = (datetime.strptime(old, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        time.sleep(0.12)
    return ohlc_frame(rows)


def ohlc_frame(rows):
    """KIS output2 행 목록 → 정규화 DataFrame. 테스트가 가짜 행으로 직접 부른다."""
    if not rows:
        return pd.DataFrame(columns=["date", "o", "h", "l", "c", "v", "amt"])
    df = pd.DataFrame(rows).drop_duplicates("stck_bsop_date")
    for a, b in [("o", "stck_oprc"), ("h", "stck_hgpr"), ("l", "stck_lwpr"),
                 ("c", "stck_clpr"), ("v", "acml_vol")]:
        df[a] = pd.to_numeric(df.get(b), errors="coerce")
    # 거래대금(원). 없으면 종가×거래량으로 근사(러너 실측 전 안전망).
    if "acml_tr_pbmn" in df.columns:
        df["amt"] = pd.to_numeric(df["acml_tr_pbmn"], errors="coerce") / 1e8
    else:
        df["amt"] = df["c"] * df["v"] / 1e8
    df["date"] = pd.to_datetime(df["stck_bsop_date"])
    return df[["date", "o", "h", "l", "c", "v", "amt"]].sort_values("date").reset_index(drop=True)


def fetch_investor(code):
    """종목별 일별 투자자 순매수(억원) DataFrame[date,개인,외국인,기관] 오름차순.
    오늘 행이 있으면 장중 잠정치다 — 호출부가 날짜로 구분한다."""
    j = get("/uapi/domestic-stock/v1/quotations/inquire-investor", "FHKST01010900",
            {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})
    return investor_frame(j.get("output", []))


def investor_frame(rows):
    if not rows:
        return pd.DataFrame(columns=["date", "개인", "외국인", "기관"])
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["stck_bsop_date"])
    for a, b in [("개인", "prsn_ntby_tr_pbmn"), ("외국인", "frgn_ntby_tr_pbmn"), ("기관", "orgn_ntby_tr_pbmn")]:
        df[a] = pd.to_numeric(df.get(b), errors="coerce").fillna(0) / 100   # 백만원→억원
    return df[["date", "개인", "외국인", "기관"]].drop_duplicates("date").sort_values("date").reset_index(drop=True)


def naver_trend_frame(rows):
    """네이버 /api/stock/{code}/trend 행 → DataFrame[date,개인,외국인,기관] (억원 **근사**).
    네이버는 순매수 '수량'만 주므로 금액 = 수량 × 그날 종가 / 1e8. 체결 평균가가 아니라
    종가라 정확한 금액과 몇 % 어긋난다 — 한투 금액(최근 30행)이 있는 날짜는 그쪽을 쓴다."""
    out = []
    for r in rows or []:
        try:
            close = _f(r.get("closePrice"))
            if not close:
                continue
            out.append({"date": pd.to_datetime(str(r["bizdate"])),
                        "개인": (_f(r.get("individualPureBuyQuant"), 0.0) or 0.0) * close / 1e8,
                        "외국인": (_f(r.get("foreignerPureBuyQuant"), 0.0) or 0.0) * close / 1e8,
                        "기관": (_f(r.get("organPureBuyQuant"), 0.0) or 0.0) * close / 1e8})
        except Exception:
            continue
    if not out:
        return pd.DataFrame(columns=["date", "개인", "외국인", "기관"])
    df = pd.DataFrame(out).drop_duplicates("date").sort_values("date").reset_index(drop=True)
    for c in ("개인", "외국인", "기관"):
        df[c] = df[c].round(1)
    return df


def merge_investor(kis_df, naver_df):
    """한투(정확, 최근 30행) 우선 + 그 밖의 날짜는 네이버 근사로 보충. 날짜 오름차순."""
    if naver_df is None or naver_df.empty:
        return kis_df
    if kis_df is None or kis_df.empty:
        return naver_df
    extra = naver_df[~naver_df["date"].isin(kis_df["date"])]
    return pd.concat([kis_df, extra], ignore_index=True).sort_values("date").reset_index(drop=True)


def fetch_price(code):
    """현재가 스냅: price·chg_pct·mcap(억)·listed(주)·frgn_pct·amt_today(억)."""
    j = get("/uapi/domestic-stock/v1/quotations/inquire-price", "FHKST01010100",
            {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})
    return price_row(j.get("output", {}))


def _f(x, default=None):
    try:
        return float(str(x).replace(",", ""))
    except Exception:
        return default


def price_row(o):
    return {
        "price": _f(o.get("stck_prpr")),
        "chg_pct": _f(o.get("prdy_ctrt")),
        "mcap": _f(o.get("hts_avls")),            # 억원
        "listed": _f(o.get("lstn_stcn")),         # 상장주수
        "frgn_pct": _f(o.get("hts_frgn_ehrt")),   # 외국인 보유비율 %
        "amt_today": (_f(o.get("acml_tr_pbmn"), 0.0) or 0.0) / 1e8,
        "name": o.get("hts_kor_isnm", ""),
    }
