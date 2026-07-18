# -*- coding: utf-8 -*-
"""액티브 ETF 구성종목(Top10) 일일 스냅샷 수집기.
- 소스: 네이버 모바일 API (m.stock.naver.com/.../etfAnalysis) → etfTop10MajorConstituentAssets
  · 각 종목의 계약수(stockCount)와 비중(etfWeight) 제공. requests로 CI 안전.
  · KRX 전체 PDF는 WAF 차단이라 Top10로 시작(향후 운용사 전체 PDF 컬렉터로 교체 가능).
- 결과: snapshots/YYYY-MM-DD.json  (변화감지·리포트·텔레그램이 이 파일을 읽음)
"""
from __future__ import annotations
import os, sys, csv, json, time, re
import requests
from datetime import datetime, timedelta, timezone

try:  # Windows 콘솔(cp949) 출력 대비
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR = os.path.join(HERE, "snapshots")
KST = timezone(timedelta(hours=9))
API = "https://m.stock.naver.com/api/stock/{code}/etfAnalysis"
H = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605",
     "Referer": "https://m.stock.naver.com/"}
# CU당 구성종목 '기준일'(KRX 장마감 기준)은 데스크톱 coinfo 페이지에만 노출됨
COINFO = "https://finance.naver.com/item/coinfo.naver?code={code}"
H_PC = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126",
        "Referer": "https://finance.naver.com/"}
import re as _re
_BASE_RE = _re.compile(r"(\d{4})\.(\d{2})\.(\d{2})\s*<span>\s*기준")


def load_universe():
    rows = []
    with open(os.path.join(HERE, "etf_universe.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("active") == "1" and r.get("code"):
                rows.append({"group": r["group"], "name": r["name"], "code": r["code"].strip()})
    return rows


def _num(s):
    t = re.sub(r"[^0-9.\-]", "", str(s))
    if t in ("", "-", ".", "-.", "--"):
        return 0.0
    try:
        return float(t)
    except ValueError:
        return 0.0


def fetch_base_date(code, tries=2):
    """CU당 구성종목 기준일(YYYY-MM-DD). 못 구하면 ''."""
    for k in range(tries):
        try:
            r = requests.get(COINFO.format(code=code), headers=H_PC, timeout=15)
            r.encoding = "euc-kr"
            m = _BASE_RE.search(r.text)
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""
        except Exception:
            if k == tries - 1:
                return ""
            time.sleep(0.5)


def fetch_one(code, tries=3):
    url = API.format(code=code)
    for k in range(tries):
        try:
            r = requests.get(url, headers=H, timeout=15)
            r.raise_for_status()
            j = r.json()
            top = j.get("etfTop10MajorConstituentAssets") or []
            holdings = [{
                # 해외주식은 itemCode가 비어있어 종목명을 키로 사용
                "key": (h.get("itemCode") or h.get("itemName", "")).strip(),
                "code": h.get("itemCode", ""),
                "name": h.get("itemName", ""),
                "shares": _num(h.get("stockCount")),      # 계약수(CU당 주식수)
                "weight": _num(h.get("etfWeight")),        # 비중 %(해외는 '-'→0)
            } for h in top if (h.get("itemCode") or h.get("itemName"))]
            return {
                "name": j.get("itemName", ""),
                "nav": _num(j.get("nav")),
                "market_value": j.get("marketValue", ""),
                "holdings": holdings,
            }
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(0.7)


def snapshot(date=None):
    date = date or datetime.now(KST).strftime("%Y-%m-%d")
    uni = load_universe()
    etfs, errs = {}, []
    for i, u in enumerate(uni, 1):
        try:
            rec = fetch_one(u["code"])
            rec["group"] = u["group"]
            rec["label"] = u["name"]                      # 우리 유니버스 표기(신뢰)
            rec["base_date"] = fetch_base_date(u["code"])  # CU 구성종목 기준일
            etfs[u["code"]] = rec
            print(f"  [{i}/{len(uni)}] OK {u['name']}  Top{len(rec['holdings'])}  기준 {rec['base_date'] or '?'}")
        except Exception as e:
            errs.append({"name": u["name"], "code": u["code"], "err": str(e)[:120]})
            print(f"  [{i}/{len(uni)}] ERR {u['name']}: {str(e)[:80]}")
        time.sleep(0.12)
    # 대표 기준일 = ETF들 중 가장 흔한 기준일(보통 전 종목 동일)
    from collections import Counter
    bds = Counter(e["base_date"] for e in etfs.values() if e.get("base_date"))
    base_date = bds.most_common(1)[0][0] if bds else ""
    payload = {
        "date": date,
        "fetched_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "base_date": base_date,                            # CU 구성종목 기준일(KRX 장마감)
        "source": "naver_top10",
        "etfs": etfs,
        "errors": errs,
    }
    os.makedirs(SNAP_DIR, exist_ok=True)
    path = os.path.join(SNAP_DIR, f"{date}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n스냅샷 {len(etfs)}/{len(uni)}개 · 에러 {len(errs)} → {os.path.relpath(path, HERE)}")
    return payload


if __name__ == "__main__":
    snapshot()
