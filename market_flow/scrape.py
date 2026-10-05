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
  · K200 선물 **투자자별** (누가 샀나 — 네이버가 국내 파생 서비스를 통째로 접었다)

[2026-09-22 선물 자리를 베이시스로 교체]
네이버 개편(Npay 증권) 뒤 국내 선물은 화면도 API 도 없다. 투자자별은 포기하고,
대신 **가격**으로 같은 질문에 답한다 — 선물이 현물보다 비싼가 싼가(베이시스),
이론가 대비 싼가(괴리율). 이것이 차익 프로그램 매매를 직접 설명한다.
가격은 한국투자 OpenAPI 에서 받는다(이 모듈이 종목별 가집계로 이미 쓰는 곳):
  · 근월물 단축코드는 한투 종목마스터(.mst)에서 읽는다 — 코드 규약을 안 박아둔다
  · inquire-price  → 선물 현재가·시장베이시스·이론가·괴리율·미결제약정
  · inquire-daily-fuopchartprice + inquire-daily-indexchartprice → 일별 베이시스 소급
"""
import csv
import io
import json
import os
import re
import zipfile
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
# 한투가 공개 배포하는 지수선물·옵션 종목마스터. 근월물 단축코드를 여기서 읽는다.
FO_MASTER = "https://new.real.download.dws.co.kr/common/master/fo_idx_code_mts.mst.zip"

_KIS_TOKEN = None


def kis_token():
    """접근토큰 1회 발급 후 재사용. 키가 없으면 빈 문자열(호출부가 섹션만 생략)."""
    global _KIS_TOKEN
    if _KIS_TOKEN is not None:
        return _KIS_TOKEN
    key, sec = os.environ.get("KIS_APP_KEY"), os.environ.get("KIS_APP_SECRET")
    if not key or not sec:
        _KIS_TOKEN = ""
        return _KIS_TOKEN
    r = SESSION.post(f"{KIS_BASE}/oauth2/tokenP", timeout=15, json={
        "grant_type": "client_credentials", "appkey": key, "appsecret": sec})
    r.raise_for_status()
    _KIS_TOKEN = r.json()["access_token"]
    return _KIS_TOKEN


def kis_get(path, tr_id, params):
    tok = kis_token()
    if not tok:
        raise RuntimeError("KIS_APP_KEY/SECRET 미설정")
    r = SESSION.get(KIS_BASE + path, timeout=15, params=params, headers={
        "authorization": f"Bearer {tok}",
        "appkey": os.environ["KIS_APP_KEY"], "appsecret": os.environ["KIS_APP_SECRET"],
        "tr_id": tr_id, "custtype": "P"})
    r.raise_for_status()
    j = r.json()
    if j.get("rt_cd") != "0":
        raise RuntimeError(f"KIS {tr_id} 오류: {j.get('msg1')}")
    return j


def _f(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def front_contract():
    """코스피200 **정규** 선물의 근월물 {ym, code, name}.

    단축코드 규약은 문서마다 다르고 바뀐다(옛 문서의 '101W12' 형식은 지금 안 먹는다).
    그래서 코드를 박아두지 않고 한투 종목마스터에서 이름이 'F YYYYMM' 인 것 중
    가장 이른 월물을 고른다 — '미니F' 는 이름이 달라 자동으로 빠진다.
    """
    r = SESSION.get(FO_MASTER, timeout=60)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    raw = z.read(z.namelist()[0]).decode("cp949", "ignore")
    best = None
    for line in raw.splitlines():
        f = [x.strip() for x in line.split("|")]
        if len(f) < 9 or f[-1] != "KOSPI200":
            continue
        m = re.fullmatch(r"F (\d{6})", f[3])
        if m and (best is None or m.group(1) < best[0]):
            best = (m.group(1), f[1], f[3])
    if not best:
        raise RuntimeError("종목마스터에서 코스피200 선물 근월물을 찾지 못함")
    return {"ym": best[0], "code": best[1], "name": best[2]}


def futures_basis(code):
    """지금 시점의 선물 가격과 현물 괴리. 단위: 지수 포인트(베이시스)·%(괴리율).

    basis  = 선물 − 현물(KOSPI200). 양수 콘탱고 / 음수 백워데이션.
    dprt   = 괴리율 = (선물 − 이론가)/이론가. 음수면 선물이 이론가보다 싸다
             → 차익거래는 '선물 매수 + 현물 매도'가 유리해져 차익 프로그램 매도 압력.
    """
    j = kis_get("/uapi/domestic-futureoption/v1/quotations/inquire-price",
                "FHMIF10000000", {"FID_COND_MRKT_DIV_CODE": "F", "FID_INPUT_ISCD": code})
    o1, o3 = j.get("output1") or {}, j.get("output3") or {}
    fut, spot = _f(o1.get("futs_prpr")), _f(o3.get("bstp_nmix_prpr"))
    if fut is None:
        raise RuntimeError(f"선물 시세 응답이 비었다(코드 {code}) — 월물 교체 의심")
    basis = _f(o1.get("mrkt_basis"))
    if basis is None and spot is not None:
        basis = round(fut - spot, 2)
    return {"fut": fut, "spot": spot, "basis": basis,
            "theo": _f(o1.get("hts_thpr")), "dprt": _f(o1.get("dprt")),
            "chg_pct": _f(o1.get("futs_prdy_ctrt")),
            "oi": _f(o1.get("hts_otst_stpl_qty")),
            "oi_chg": _f(o1.get("otst_stpl_qty_icdc")),
            "remain": _f(o1.get("hts_rmnn_dynu"))}


def second_thursday(y, m):
    """해당 월의 두 번째 목요일 = 코스피200 선물 만기일."""
    d = dt.date(y, m, 1)
    return d + dt.timedelta(days=(3 - d.weekday()) % 7 + 7)


def _prev_quarter(ym):
    """'202612' → '202609' (분기물은 3·6·9·12월)."""
    y, m = int(ym[:4]), int(ym[4:6])
    m -= 3
    if m <= 0:
        y, m = y - 1, m + 12
    return f"{y}{m:02d}"


def _contract_code(ym):
    """'202612' → 'A01612'. 마스터에서 확인한 규약(A01 + 연도끝자리 + 월)인데,
    추정이 틀릴 수 있으므로 **쓰는 쪽에서 응답이 비면 조용히 건너뛴다**.
    근월물만은 언제나 마스터에서 직접 읽으므로 이 추정에 기대지 않는다."""
    return f"A01{ym[3]}{ym[4:6]}"


def _index_closes(d1, d2):
    """KOSPI200 일별 종가 {YYYYMMDD: close}"""
    j = kis_get("/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice",
                "FHKUP03500100",
                {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": "2001",
                 "FID_INPUT_DATE_1": d1, "FID_INPUT_DATE_2": d2, "FID_PERIOD_DIV_CODE": "D"})
    return {r["stck_bsop_date"]: _f(r.get("bstp_nmix_prpr"))
            for r in (j.get("output2") or []) if r.get("stck_bsop_date")}


def _futures_closes(code, d1, d2):
    """선물 일별 종가 {YYYYMMDD: close}"""
    j = kis_get("/uapi/domestic-futureoption/v1/quotations/inquire-daily-fuopchartprice",
                "FHKIF03020100",
                {"FID_COND_MRKT_DIV_CODE": "F", "FID_INPUT_ISCD": code,
                 "FID_INPUT_DATE_1": d1, "FID_INPUT_DATE_2": d2, "FID_PERIOD_DIV_CODE": "D"})
    return {r["stck_bsop_date"]: _f(r.get("futs_prpr"))
            for r in (j.get("output2") or []) if r.get("stck_bsop_date")}


def basis_daily(front_ym, days=45):
    """일별 시장 베이시스 {날짜: {fut, spot, basis, contract}} — 선물 종가 − 현물 종가.

    **날짜마다 그날의 근월물**을 쓴다. 베이시스는 만기까지 남은 기간에 비례해서
    커지므로, 월물이 바뀐 날을 넘어 한 월물로 쭉 그리면 레벨이 통째로 어긋난다.
    (그래도 교체일에는 계단이 생긴다 — 화면에 그렇게 적어둔다.)
    """
    end = now_kst().date()
    start = end - dt.timedelta(days=days)
    d1, d2 = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    spots = _index_closes(d1, d2)

    out, ym, hi = {}, front_ym, None
    for _ in range(4):                       # 근월물부터 뒤로 최대 4개 분기물
        p = _prev_quarter(ym)
        lo = second_thursday(int(p[:4]), int(p[4:6]))   # 직전 만기 — 그 다음날부터 근월물
        try:
            closes = _futures_closes(_contract_code(ym), d1, d2)
        except Exception as e:
            print(f"  · 선물 일봉 {ym} 실패: {e}")
            closes = {}
        for d8, fv in closes.items():
            d = dt.date(int(d8[:4]), int(d8[4:6]), int(d8[6:]))
            if not (lo < d <= (hi or dt.date.max)) or fv is None:
                continue
            sv = spots.get(d8)
            if sv is None:
                continue
            out[f"{d8[:4]}-{d8[4:6]}-{d8[6:]}"] = {
                "fut": fv, "spot": sv, "basis": round(fv - sv, 2), "contract": ym}
        if lo <= start:
            break
        hi, ym = lo, p
    return out


def stock_investor_flow(top=7):
    """한투 OpenAPI '국내기관_외국인 매매종목가집계'(FHPTJ04400000) — 장중 잠정.
    외국인·기관 각각의 순매수/순매도 상위 종목을 금액 기준으로 뽑는다.
    반환: {"time": "HH:MM", "buy": [[종목명, 등락률%, 순매수억], …], "sell": […],
           "inst_buy": […], "inst_sell": […]} 또는 None
    (KIS_APP_KEY/SECRET 미설정이면 None — 섹션만 비표시)"""
    if not kis_token():
        print("KIS 키 미설정 → 종목별 수급 생략")
        return None
    key, sec = os.environ["KIS_APP_KEY"], os.environ["KIS_APP_SECRET"]
    hdr = {"authorization": f"Bearer {kis_token()}",
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

    # K200 선물 베이시스 — 투자자별이 사라진 자리를 '가격 괴리'로 대신한다.
    # (실패하거나 KIS 키가 없으면 해당 섹션만 비표시, 본 파이프라인은 그대로)
    try:
        con = front_contract()
        hist["fut_contract"] = con
        snap["basis"] = futures_basis(con["code"])
        print(f"[{slot}] 베이시스: {con['name']}({con['code']}) {snap['basis']}")
        bd = basis_daily(con["ym"])
        n_b = 0
        for d, v in bd.items():
            rec = hist["days"].setdefault(d, {})
            if "basis" not in rec.get("confirmed", {}) or d == today:
                rec.setdefault("confirmed", {})["basis"] = v
                n_b += 1
        print(f"일별 베이시스 백필: {len(bd)}일 수신, {n_b}일 갱신")
    except Exception as e:
        print(f"⚠️ 선물 베이시스 수집 실패(섹션만 비표시): {e}")

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
