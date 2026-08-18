# -*- coding: utf-8 -*-
"""구성 변화 카드에 등장하는 개별 종목의 시세 시계열을 모아 prices.json에 캐시한다.

카드에 뜨는 종목(Top10 진입·이탈, 실매매)만 대상이라 하루 20~30개 수준이다.
워크플로가 평일 매시간 도는데 시세는 하루 한 번만 받으면 충분하므로,
같은 날 이미 받은 코드는 건너뛴다(첫 실행만 API를 쓰고 이후는 사실상 0회).

시세 출처는 etf_signal 이 매일 쓰는 KIS 일봉 API를 그대로 재사용한다.
해외 종목(MICROSOFT CORP 등)은 6자리 국내 코드가 없어 대상에서 빠진다.

키가 없거나 수집이 실패해도 리포트 생성은 막지 않는다 — 캐시를 그대로 두고 끝낸다.
"""
from __future__ import annotations
import os, sys, json, time, glob
from datetime import datetime, timedelta, timezone

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "prices.json")
KST = timezone(timedelta(hours=9))
BASE = "https://openapi.koreainvestment.com:9443"

KEEP_BARS = 60        # 스파크라인용 최근 거래일 수
LOOKBACK_DAYS = 120   # 60거래일을 확보하려면 달력 기준 넉넉히
PRUNE_DAYS = 30       # 최근 이 기간 카드에 안 나온 코드는 캐시에서 정리

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _load_keys():
    p = os.path.join(HERE, ".env")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    return os.environ.get("KIS_APP_KEY"), os.environ.get("KIS_APP_SECRET")


_c = {"t": None, "ts": 0}


def token(app_key, app_secret):
    if _c["t"] and time.time() - _c["ts"] < 60 * 60 * 23:
        return _c["t"]
    r = requests.post(f"{BASE}/oauth2/tokenP",
                      json={"grant_type": "client_credentials",
                            "appkey": app_key, "appsecret": app_secret}, timeout=20)
    r.raise_for_status()
    _c.update(t=r.json()["access_token"], ts=time.time())
    return _c["t"]


def fetch_closes(code, app_key, app_secret):
    """최근 KEEP_BARS 거래일의 (날짜, 종가). 오늘(미완성) 봉은 제외."""
    url = f"{BASE}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    today = datetime.now(KST)
    params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
              "FID_INPUT_DATE_1": (today - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d"),
              "FID_INPUT_DATE_2": today.strftime("%Y%m%d"),
              "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0"}
    headers = {"authorization": f"Bearer {token(app_key, app_secret)}",
               "appkey": app_key, "appsecret": app_secret,
               "tr_id": "FHKST03010100", "custtype": "P"}
    r = requests.get(url, headers=headers, params=params, timeout=15)
    r.raise_for_status()
    rows = [x for x in r.json().get("output2", []) if x.get("stck_bsop_date") and x.get("stck_clpr")]
    today_s = today.strftime("%Y%m%d")
    pairs = sorted({x["stck_bsop_date"]: x["stck_clpr"] for x in rows
                    if x["stck_bsop_date"] < today_s}.items())
    pairs = pairs[-KEEP_BARS:]
    if len(pairs) < 5:
        return None
    return ([f"{d[:4]}-{d[4:6]}-{d[6:]}" for d, _ in pairs],
            [float(c) for _, c in pairs])


def card_codes():
    """카드에 등장하는 국내 종목 코드 → 이름. changes.json 기준."""
    out = {}
    p = os.path.join(HERE, "changes.json")
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8") as f:
        ch = json.load(f)
    for e in ch.get("etfs", []):
        for key in ("new", "gone", "moves"):
            for x in e.get(key, []):
                c = str(x.get("code") or "")
                if c.isdigit() and len(c) == 6:
                    out[c] = x.get("name") or c
    return out


def main():
    app_key, app_secret = _load_keys()
    cache = {"codes": {}}
    if os.path.exists(CACHE):
        try:
            with open(CACHE, encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            pass
    cache.setdefault("codes", {})

    wanted = card_codes()
    today = datetime.now(KST).strftime("%Y-%m-%d")
    if not wanted:
        print("카드에 국내 종목 없음 — 시세 수집 생략")
        return
    if not (app_key and app_secret):
        print("⚠️ KIS 키 없음 — 기존 캐시 유지하고 종료")
        return

    todo = [c for c in wanted if cache["codes"].get(c, {}).get("fetched") != today]
    print(f"카드 종목 {len(wanted)}개 · 오늘 받을 대상 {len(todo)}개")

    ok = err = 0
    for i, code in enumerate(todo, 1):
        try:
            got = fetch_closes(code, app_key, app_secret)
            if not got:
                raise ValueError("종가 부족")
            dates, closes = got
            cache["codes"][code] = {"name": wanted[code], "dates": dates,
                                    "close": closes, "fetched": today}
            ok += 1
        except Exception as e:
            err += 1
            print(f"  [{i}/{len(todo)}] ERR {wanted[code]}({code}): {str(e)[:70]}")
        time.sleep(0.15)

    # 오래 안 쓰인 코드 정리 — 최근 PRUNE_DAYS 스냅샷 카드에 안 나온 것
    keep = set(wanted)
    cutoff = (datetime.now(KST) - timedelta(days=PRUNE_DAYS)).strftime("%Y-%m-%d")
    for c, v in list(cache["codes"].items()):
        if c not in keep and (v.get("fetched") or "") < cutoff:
            del cache["codes"][c]

    cache["updated"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))
    print(f"시세 캐시 {len(cache['codes'])}종목 (신규/갱신 {ok} · 실패 {err}) → prices.json")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:            # 리포트 생성을 막지 않는다
        print(f"⚠️ 시세 수집 실패(스파크라인만 비표시): {type(e).__name__}: {e}")
