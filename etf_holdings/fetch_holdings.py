# -*- coding: utf-8 -*-
"""액티브 ETF 구성종목(Top10) 일일 스냅샷 수집기.
- 소스: 네이버 모바일 API (m.stock.naver.com/.../etfAnalysis) → etfTop10MajorConstituentAssets
  · 각 종목의 계약수(stockCount)와 비중(etfWeight) 제공. requests로 CI 안전.
  · KRX 전체 PDF는 WAF 차단이라 Top10로 시작(향후 운용사 전체 PDF 컬렉터로 교체 가능).
- 결과: snapshots/YYYY-MM-DD.json  (변화감지·리포트·텔레그램이 이 파일을 읽음)
"""
from __future__ import annotations
import os, sys, csv, glob, json, time, re
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
INDEX_BASIC = "https://m.stock.naver.com/api/index/KOSPI/basic"

# [2026-10-05] CU 구성종목 '기준일'은 더 이상 어디에서도 안 준다.
# 긁던 곳(finance.naver.com/item/coinfo.naver)은 9/11 Npay 증권 개편으로 신규 SPA 에
# 리다이렉트되며 '기준' 표기 자체가 사라졌다(실측: 리다이렉트 후 본문에 '기준' 없음).
# 신규 front-api 도 상장일·성과기준일만 줄 뿐 CU 기준일이 없다(etf/analysis·etf/component/list
# 응답 키 전수 확인). 그래서 **기준일로 판정하던 설계를 버리고 '구성이 실제로 바뀌었나'로
# 바꿨다** — snapshot() 이 직전 스냅샷과 계약수를 비교해 같으면 파일을 아예 안 쓴다.


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


def market_day():
    """거래소가 마지막으로 거래한 날짜(YYYY-MM-DD)와 장 상태.

    휴장일(주말·공휴일·대체공휴일) 판정에 쓴다 — market_flow 가 쓰는 것과 같은 방법.
    못 가져오면 ('', '') → 호출부는 '모르면 그냥 실행'(fail-open).
    """
    try:
        j = requests.get(INDEX_BASIC, headers=H, timeout=15).json()
        return (j.get("localTradedAt", "")[:10], j.get("marketStatus", ""))
    except Exception:
        return ("", "")


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


def _signature(etfs):
    """구성 지문 = {ETF: {종목: 계약수}}.

    비중(weight)·NAV·시가총액은 **주가만 움직여도 매일 바뀌므로** 지문에서 뺀다.
    계약수(CU당 주식수)만이 '운용사가 실제로 사고팔았나'의 신호다(detect_changes 와 같은 철학).
    """
    return {c: {h["key"]: h["shares"] for h in r.get("holdings", [])}
            for c, r in sorted(etfs.items())}


def _latest_snapshot():
    files = sorted(glob.glob(os.path.join(SNAP_DIR, "*.json")))
    if not files:
        return None, None
    with open(files[-1], encoding="utf-8") as f:
        return os.path.basename(files[-1])[:-5], json.load(f)


def _emit(**kw):
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            for k, v in kw.items():
                f.write(f"{k}={v}\n")


def snapshot(date=None):
    """구성 스냅샷. **직전 스냅샷과 계약수가 같으면 파일을 쓰지 않는다.**

    네이버는 장 마감 뒤 다음 거래일치 CU 바스켓으로 갈아끼운다. 하루 8번 긁는 동안
    대부분의 실행은 '같은 바스켓'을 다시 받는데, 예전에는 그걸 매번 새 스냅샷으로
    덮어쓰고 변화 감지를 돌려 **휴장일에도 매매가 있는 것처럼** 보였다.
    """
    date = date or datetime.now(KST).strftime("%Y-%m-%d")
    uni = load_universe()
    etfs, errs = {}, []
    for i, u in enumerate(uni, 1):
        try:
            rec = fetch_one(u["code"])
            rec["group"] = u["group"]
            rec["label"] = u["name"]                      # 우리 유니버스 표기(신뢰)
            etfs[u["code"]] = rec
            print(f"  [{i}/{len(uni)}] OK {u['name']}  Top{len(rec['holdings'])}")
        except Exception as e:
            errs.append({"name": u["name"], "code": u["code"], "err": str(e)[:120]})
            print(f"  [{i}/{len(uni)}] ERR {u['name']}: {str(e)[:80]}")
        time.sleep(0.12)

    prev_date, prev = _latest_snapshot()
    # 일부 ETF가 실패해 종목 수가 줄었을 뿐인데 '바뀌었다'고 보면 가짜 이탈이 쏟아진다.
    if prev and errs and len(etfs) < len(prev.get("etfs", {})):
        print(f"\n수집 실패 {len(errs)}개로 ETF 수가 줄었다({len(prev['etfs'])}→{len(etfs)}) "
              "— 가짜 이탈 방지를 위해 저장 생략")
        _emit(changed="false", reason="partial")
        return {**(prev or {}), "changed": False}
    if prev and _signature(etfs) == _signature(prev.get("etfs", {})):
        print(f"\n구성 변화 없음 — 직전 스냅샷({prev_date}, {prev.get('fetched_at','')})과 "
              "계약수가 동일해 저장 생략")
        _emit(changed="false", reason="same")
        return {**prev, "changed": False}

    traded, status = market_day()
    payload = {
        "date": date,
        "fetched_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        # 네이버가 CU 기준일을 더 이상 안 주므로(위 주석), '언제 바뀐 걸 봤나'와
        # '그 시점의 마지막 거래일'만 정직하게 남긴다.
        "market_date": traded,
        "market_status": status,
        "base_date": "",          # 옛 키 — 과거 스냅샷 호환용으로만 남김
        "source": "naver_top10",
        "etfs": etfs,
        "errors": errs,
    }
    os.makedirs(SNAP_DIR, exist_ok=True)
    path = os.path.join(SNAP_DIR, f"{date}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n구성 변화 감지 → 스냅샷 {len(etfs)}/{len(uni)}개 · 에러 {len(errs)} "
          f"· 마지막 거래일 {traded or '?'} → {os.path.relpath(path, HERE)}")
    _emit(changed="true", reason="new")
    payload["changed"] = True
    return payload


if __name__ == "__main__":
    snapshot()
