# -*- coding: utf-8 -*-
"""네이버 파이낸스에서 KOSPI 수급 스냅샷을 수집해 data/history.json 에 누적한다.

하루 4회(10:00 / 13:00 / 15:40잠정 / 16:40확정 KST) GitHub Actions로 실행.
 - 매 실행: 투자자 잠정치(개인/외국인/기관) + 프로그램(차익/비차익/전체) 스냅샷
 - 매 실행: 일별 확정 백필 — 투자자별은 30영업일, 프로그램은 당일치만
 - 15:40/16:40 실행: 그날 슬롯 스냅샷을 이어 붙인 장중 곡선 저장
휴장일(모바일API localTradedAt 날짜 ≠ 오늘)은 아무것도 쓰지 않고 종료한다.
단위: 억원.

[2026-09-18 수집 경로 전면 교체]
네이버가 옛 PC 수급 페이지를 **410 Gone** 으로 폐기했다(9/11 리다이렉트 →
9/16 시간대별로 우회 → 9/18 그것마저 삭제). 신규 SPA 가 쓰는 JSON API 로 옮겼다:
  · m.stock.naver.com/api/index/<code>/trend?bizdate=  개인·외국인·기관 (과거 조회 O)
  · m.stock.naver.com/front-api/stock/domestic/integration  당일 투자자별+프로그램
JSON 이라 마크업 변경에는 안 깨진다. 다만 옛 페이지가 주던 아래 셋은 대체 경로가 없다:
  · 기관 세부 7항목(금융투자·보험·투신·은행·기타금융·연기금등·기타법인)
  · 프로그램 매수/매도 다리 (순매수만 남음 — 화면·텔레그램은 원래 순매수만 썼다)
  · K200 선물 투자자별 (신규 API 의 KPI200 은 현물이라 대용 불가 — 섹션 비표시)
"""import csv
import json
import os
import re
import datetime as dt
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter, Retry

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
HISTORY = DATA / "history.json"
RUN_META = DATA / "run_meta.json"

KST = dt.timezone(dt.timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

KEEP_DAYS = 60      # history.json에 보관할 일수
KEEP_CURVE_DAYS = 5  # 장중 곡선을 보관할 일수



def now_kst():
    return dt.datetime.now(KST)


SESSION = requests.Session()
SESSION.headers.update(UA)
SESSION.mount("https://", HTTPAdapter(
    max_retries=Retry(total=3, backoff_factor=1.5,
                      status_forcelist=[500, 502, 503, 504])))


def get(url, **kw):
    r = SESSION.get(url, timeout=30, **kw)
    r.raise_for_status()
    return r




def num(s):
    s = s.replace(",", "").replace("+", "").strip()
    try:
        return int(s)
    except ValueError:
        return None


def kospi_basic():
    """모바일 API에서 지수/등락률/장상태. 휴장 판정에도 쓴다."""
    j = get("https://m.stock.naver.com/api/index/KOSPI/basic").json()
    return {
        "close": float(j["closePrice"].replace(",", "")),
        "chg_pct": float(j["fluctuationsRatio"]),
        "market_status": j.get("marketStatus", ""),
        "traded_at": j.get("localTradedAt", ""),
    }


# ── 네이버 신규 JSON API ────────────────────────────────────────────────────
# 2026-09-18: 옛 PC 수급 페이지 4종이 전부 410 Gone 으로 사라졌다(9/16 에 갈아탄
# 시간대별 페이지 포함). 러너 프로브로 신규 SPA 가 쓰는 API 를 찾아 이쪽으로 옮긴다.
#   m.stock.naver.com/api/index/<code>/trend?bizdate=  → 개인·외국인·기관 (과거 조회 O)
#   m.stock.naver.com/front-api/stock/domestic/integration → dealTrendInfo + programTrendInfo
# HTML 파싱이 아니라 JSON 이라 마크업 변경에는 안 깨진다. 단, 옛 페이지가 주던
# 기관 세부 7항목·프로그램 매수/매도 다리·선물 투자자별은 이 API 에 없다.
MAPI = "https://m.stock.naver.com/api"
FRONT = "https://m.stock.naver.com/front-api"


def _amt(s):
    """'+1,311' → 1311 · '-25,126' → -25126 · None/빈값 → None (단위 억원)"""
    if s is None:
        return None
    s = str(s).replace(",", "").replace("+", "").strip()
    try:
        return int(s)
    except ValueError:
        return None


def index_trend(code="KOSPI", bizdate=None):
    """지수의 개인·외국인·기관 순매수(억원). bizdate 를 주면 그날치.

    휴장일을 요청하면 네이버가 직전 거래일 값을 돌려주므로, 응답의 bizdate 가
    요청과 다르면 '그날은 거래일이 아니다'로 보고 None 을 반환한다.
    """
    j = get(f"{MAPI}/index/{code}/trend",
            params={"bizdate": bizdate} if bizdate else None).json()
    got = j.get("bizdate")
    if bizdate and got != bizdate:
        return None
    return {"bizdate": got,
            "individual": _amt(j.get("personalValue")),
            "foreign": _amt(j.get("foreignValue")),
            "inst_total": _amt(j.get("institutionalValue"))}


def index_integration(code="KOSPI"):
    """오늘의 투자자별 + 프로그램(차익·비차익·합계). 과거 조회는 안 된다."""
    j = get(f"{FRONT}/stock/domestic/integration",
            params={"code": code, "endType": "index"}).json()
    res = j.get("result") or {}
    deal = res.get("dealTrendInfo") or {}
    prg = res.get("programTrendInfo") or {}
    return {
        "bizdate": deal.get("bizdate") or prg.get("bizdate"),
        "individual": _amt(deal.get("personalValue")),
        "foreign": _amt(deal.get("foreignValue")),
        "inst_total": _amt(deal.get("institutionalValue")),
        # Real = 실시간 누적. difference=차익, biDifference=비차익.
        "arb_net": _amt(prg.get("indexDifferenceReal")),
        "nonarb_net": _amt(prg.get("indexBiDifferenceReal")),
        "total_net": _amt(prg.get("indexTotalReal")),
    }


def snapshot_provisional(bizdate):
    """잠정 스냅샷: 개인/외국인/기관 + 차익/비차익/전체 (억원).

    옛 시세 메인 → (9/16) 시간대별 페이지 → (9/18) 신규 JSON API 로 두 번 옮겼다.
    integration 은 '지금 이 순간의 누적'을 주므로 슬롯 스냅샷 용도에 그대로 맞는다.
    """
    d = index_integration("KOSPI")
    if d["individual"] is None or d["total_net"] is None:
        raise RuntimeError(f"integration 응답에 수급 값이 없다: {d}")
    return {"individual": d["individual"], "foreign": d["foreign"],
            "institution": d["inst_total"],
            "arb": d["arb_net"], "nonarb": d["nonarb_net"], "program": d["total_net"]}


def daily_confirmed(bizdate, pages=3, want=None):
    """일별 확정. {date: {"investor": {...}, "program": {...}}}

    투자자별은 trend API 로 날짜별 조회가 되지만 **프로그램은 과거 조회 경로가 없어
    오늘치만** 담긴다(옛 programDealTrendDay 소멸). pages 는 옛 시그니처 호환용.
    want 에 날짜(YYYY-MM-DD) 집합을 주면 그 날짜만 채운다 — 매 실행 30회씩
    다시 긁지 않으려는 것.
    """
    today = dt.datetime.strptime(bizdate, "%Y%m%d").date()
    out = {}
    for back in range(0, pages * 14):          # 넉넉히 훑되 주말은 건너뛴다
        d = today - dt.timedelta(days=back)
        if d.weekday() >= 5:
            continue
        iso = d.isoformat()
        if want is not None and iso not in want and d != today:
            continue
        try:
            t = index_trend("KOSPI", d.strftime("%Y%m%d"))
        except Exception as e:
            print(f"  · {iso} 투자자별 조회 실패: {e}")
            continue
        if not t:                               # 휴장일
            continue
        out[iso] = {"investor": {"individual": t["individual"],
                                 "foreign": t["foreign"],
                                 "inst_total": t["inst_total"]}}
        if len(out) >= 30:
            break
    # 프로그램은 오늘치만 — integration 이 과거를 안 준다.
    try:
        g = index_integration("KOSPI")
        if g["bizdate"]:
            iso = f"{g['bizdate'][:4]}-{g['bizdate'][4:6]}-{g['bizdate'][6:]}"
            out.setdefault(iso, {})["program"] = {
                "arb_net": g["arb_net"], "nonarb_net": g["nonarb_net"],
                "total_net": g["total_net"]}
    except Exception as e:
        print(f"  · 프로그램(당일) 조회 실패: {e}")
    return out


def futures_daily(bizdate, pages=3):
    """K200 선물 투자자별 — 2026-09-18 현재 대체 경로가 없다.

    옛 investorDealTrendDay?sosok=03 이 410 으로 사라졌고, 신규 API 의 KPI200 은
    **현물 지수**라 선물이 아니다. 현물을 선물로 저장하면 조용히 틀린 값이 쌓이므로
    차라리 실패시켜 해당 섹션을 숨긴다(호출부가 try/except 로 감싸고 있다).
    """
    raise RuntimeError("선물 투자자별: 네이버 옛 페이지 폐기(410)로 대체 경로 없음")


UNIVERSE_CSV = HERE.parent / "etf_signal" / "etf_universe.csv"


def group_returns():
    """etf_signal 유니버스 ETF들의 현재가 등락률을 그룹 평균으로 묶는다.
    ETF 신호판의 '그룹 평균 WoW' 그림을 수급 화면에서는 당일 등락률로 보여주기 위한 것.
    반환: {"time": "HH:MM", "groups": [[그룹, 평균%, 종목수], …]} (평균 내림차순) 또는 None"""
    rows = list(csv.DictReader(UNIVERSE_CSV.open(encoding="utf-8-sig")))
    by_grp, fail = {}, 0
    for r in rows:
        if (r.get("active") or "").strip() != "1":
            continue
        try:
            j = get(f"https://m.stock.naver.com/api/stock/{r['code'].strip()}/basic").json()
            by_grp.setdefault(r["group"].strip(), []).append(float(j["fluctuationsRatio"]))
        except Exception:
            fail += 1
    if not by_grp:
        return None
    groups = sorted(((g, round(sum(v) / len(v), 2), len(v)) for g, v in by_grp.items()),
                    key=lambda x: -x[1])
    print(f"ETF 그룹 등락률: {len(groups)}그룹 수집 · 실패 {fail}종목")
    return {"time": now_kst().strftime("%H:%M"), "groups": [list(t) for t in groups]}


KIS_BASE = "https://openapi.koreainvestment.com:9443"


def stock_investor_flow(top=7):
    """한투 OpenAPI '국내기관_외국인 매매종목가집계'(FHPTJ04400000) — 장중 잠정.
    외국인·기관 각각의 순매수/순매도 상위 종목을 금액 기준으로 뽑는다.
    반환: {"time": "HH:MM", "buy": [[종목명, 등락률%, 순매수억], …], "sell": […],
           "inst_buy": […], "inst_sell": […]} 또는 None
    (KIS_APP_KEY/SECRET 미설정이면 None — 섹션만 비표시)"""
    key = os.environ.get("KIS_APP_KEY")
    sec = os.environ.get("KIS_APP_SECRET")
    if not key or not sec:
        print("KIS 키 미설정 → 종목별 수급 생략")
        return None
    r = SESSION.post(f"{KIS_BASE}/oauth2/tokenP", timeout=15, json={
        "grant_type": "client_credentials", "appkey": key, "appsecret": sec})
    r.raise_for_status()
    hdr = {"authorization": f"Bearer {r.json()['access_token']}",
           "appkey": key, "appsecret": sec, "tr_id": "FHPTJ04400000", "custtype": "P"}
    out = {"time": now_kst().strftime("%H:%M")}
    # FID_ETC_CLS_CODE: 1 외국인 / 2 기관계 — 기관은 orgn_* 필드에서 금액을 읽는다
    for inv_cls, amt_key, prefix in (("1", "frgn_ntby_tr_pbmn", ""),
                                     ("2", "orgn_ntby_tr_pbmn", "inst_")):
        for name, sort_cls in (("buy", "0"), ("sell", "1")):
            p = {"FID_COND_MRKT_DIV_CODE": "V", "FID_COND_SCR_DIV_CODE": "16449",
                 "FID_INPUT_ISCD": "0000",          # 전체 시장
                 "FID_DIV_CLS_CODE": "1",           # 금액 기준 정렬
                 "FID_RANK_SORT_CLS_CODE": sort_cls,  # 0 순매수상위 / 1 순매도상위
                 "FID_ETC_CLS_CODE": inv_cls}
            rr = SESSION.get(f"{KIS_BASE}/uapi/domestic-stock/v1/quotations/foreign-institution-total",
                             headers=hdr, params=p, timeout=15)
            rr.raise_for_status()
            j = rr.json()
            if j.get("rt_cd") != "0":
                raise RuntimeError(f"KIS 가집계 오류: {j.get('msg1')}")
            rows = []
            for x in j.get("output", [])[:top]:
                rows.append([x["hts_kor_isnm"], float(x["prdy_ctrt"]),
                             round(int(x[amt_key]) / 100)])  # 백만원 → 억원
            out[prefix + name] = rows
    print(f"종목별 가집계: 외국인 {len(out['buy'])}/{len(out['sell'])} · "
          f"기관 {len(out['inst_buy'])}/{len(out['inst_sell'])}종목")
    return out


def curve_from_slots(day, kind):
    """장중 곡선 — 그날 슬롯 스냅샷을 이어 붙인 성긴 판.

    옛 시간대별 페이지(분 단위)가 410 으로 사라졌고 신규 API 는 '지금 누적' 한 점만
    준다. 대신 우리가 이미 슬롯마다(10:00·13:00·15:40·16:40) 저장해 둔 스냅샷을
    쓴다 — 점이 40개에서 3~4개로 줄지만 모양(방향과 전환)은 남는다.
    반환: [["HH:MM", a, b, c], …] 시간 오름차순.
    """
    out = []
    for snap in (day.get("slots") or {}).values():
        t = snap.get("time")
        if not t:
            continue
        if kind == "investor":
            v = [snap.get("individual"), snap.get("foreign"), snap.get("institution")]
        else:
            v = [snap.get("arb"), snap.get("nonarb"), snap.get("program")]
        if all(x is not None for x in v):
            out.append([t] + v)
    return sorted(out, key=lambda r: r[0])

def decide_slot(t):
    """실행 시각(KST) → 슬롯. 크론 지연(수십 분)을 감안해 넉넉한 경계."""
    hm = t.strftime("%H%M")
    if hm < "1130":
        return "1000"
    if hm < "1430":
        return "1300"
    if hm < "1610":
        return "1540"
    return "1640"


def load_history():
    if HISTORY.exists():
        return json.loads(HISTORY.read_text(encoding="utf-8"))
    return {"days": {}}


def save_history(hist):
    DATA.mkdir(exist_ok=True)
    days = hist["days"]
    for d in sorted(days)[:-KEEP_DAYS] if len(days) > KEEP_DAYS else []:
        del days[d]
    for d in sorted(days)[:-KEEP_CURVE_DAYS]:
        days[d].pop("curve", None)
    hist["updated_kst"] = now_kst().strftime("%Y-%m-%d %H:%M")
    HISTORY.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")


def write_meta(ran, slot=None, note=""):
    DATA.mkdir(exist_ok=True)
    RUN_META.write_text(json.dumps({
        "ran": ran, "slot": slot, "note": note,
        "when_kst": now_kst().strftime("%Y-%m-%d %H:%M"),
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    t = now_kst()
    today = t.strftime("%Y-%m-%d")
    bizdate = t.strftime("%Y%m%d")

    basic = kospi_basic()
    traded_date = basic["traded_at"][:10]
    if traded_date != today:
        print(f"휴장일 판정: localTradedAt={basic['traded_at']} ≠ 오늘 {today} → 수집 생략")
        write_meta(False, note="holiday")
        return

    slot = decide_slot(t)
    hist = load_history()
    day = hist["days"].setdefault(today, {})
    day["kospi"] = {"close": basic["close"], "chg_pct": basic["chg_pct"]}

    snap = snapshot_provisional(bizdate)
    snap["time"] = t.strftime("%H:%M")
    snap["kospi"] = basic["close"]
    snap["chg_pct"] = basic["chg_pct"]
    day.setdefault("slots", {})[slot] = snap
    print(f"[{slot}] 잠정 스냅샷: {snap}")

    # 일별 확정 백필 (매 실행, 약 30영업일)
    confirmed = daily_confirmed(bizdate)
    n_new = 0
    for d, payload in confirmed.items():
        rec = hist["days"].setdefault(d, {})
        if "confirmed" not in rec or d == today:
            rec["confirmed"] = payload
            n_new += 1
    print(f"일별 확정 백필: {len(confirmed)}일 수신, {n_new}일 갱신")

    # K200 선물 일별 백필 (실패해도 본 파이프라인은 유지)
    try:
        fut, fut_unit = futures_daily(bizdate)
        # sosok 미적용으로 현물과 같은 표가 오면(2일 이상 완전 일치) 오염 방지 위해 생략
        dup = sum(1 for d, v in fut.items()
                  if hist["days"].get(d, {}).get("confirmed", {}).get("investor") == v)
        if fut and dup >= 2:
            print(f"⚠️ 선물 응답이 현물 확정치와 동일({dup}일) — sosok 미적용 의심, 저장 생략")
        else:
            hist["futures_unit"] = fut_unit
            n_fut = 0
            for d, v in fut.items():
                rec = hist["days"].setdefault(d, {})
                if "futures" not in rec.get("confirmed", {}) or d == today:
                    rec.setdefault("confirmed", {})["futures"] = v
                    n_fut += 1
            if today in fut:  # 슬롯별 선물 스냅샷 → 텔레그램의 전 슬롯 대비 증감 계산용
                snap["futures"] = {"foreign": fut[today]["foreign"],
                                   "inst_total": fut[today]["inst_total"]}
            print(f"선물 일별 백필: {len(fut)}일 수신, {n_fut}일 갱신 (단위: {fut_unit})")
    except Exception as e:
        print(f"⚠️ 선물 일별 수집 실패(리포트에는 해당 섹션만 비표시): {e}")

    # ETF 그룹 평균 등락률 (실패해도 본 파이프라인 유지, 해당 섹션만 비표시)
    try:
        gr = group_returns()
        if gr:
            day["group_1d"] = gr
    except Exception as e:
        print(f"⚠️ ETF 그룹 등락률 수집 실패(섹션 비표시): {e}")

    # 종목별 외국인 수급 가집계 (한투 API, 잠정 — 실패/키 미설정이면 섹션만 비표시)
    try:
        sf = stock_investor_flow()
        if sf:
            day["stock_flow"] = sf
    except Exception as e:
        print(f"⚠️ 종목별 외국인 가집계 수집 실패(섹션 비표시): {e}")

    # 마감 이후 실행이면 장중 곡선 저장 (슬롯 스냅샷 기반 — 위 curve_from_slots 주석 참조)
    if slot in ("1540", "1640"):
        day["curve"] = {"investor": curve_from_slots(day, "investor"),
                        "program": curve_from_slots(day, "program")}
        print(f"장중 곡선(슬롯 기반): investor {len(day['curve']['investor'])}점, "
              f"program {len(day['curve']['program'])}점")

    save_history(hist)
    write_meta(True, slot=slot)
    print(f"저장 완료: {HISTORY}")


if __name__ == "__main__":
    main()
