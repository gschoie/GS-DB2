# -*- coding: utf-8 -*-
"""네이버 파이낸스에서 KOSPI 수급 스냅샷을 수집해 data/history.json 에 누적한다.

하루 4회(10:00 / 13:00 / 15:40잠정 / 16:40확정 KST) GitHub Actions로 실행.
 - 매 실행: 시세 메인페이지의 투자자 잠정치(개인/외국인/기관) + 프로그램(차익/비차익/전체) 스냅샷
 - 매 실행: 일별 확정치 백필(투자자별·프로그램·K200선물, 최근 3페이지 ≈ 30영업일)
 - 15:40/16:40 실행: 시간대별 누적 곡선(투자자·프로그램·선물)을 10분 간격으로 샘플링해 저장
휴장일(모바일API localTradedAt 날짜 ≠ 오늘)은 아무것도 쓰지 않고 종료한다.
단위: 현물·프로그램 억원, 선물은 페이지 표기 단위(보통 계약)를 futures_unit에 기록.
"""
import csv
import json
import os
import re
import datetime as dt
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter, Retry
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
HISTORY = DATA / "history.json"
RUN_META = DATA / "run_meta.json"

KST = dt.timezone(dt.timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
BASE = "https://finance.naver.com/sise"

KEEP_DAYS = 60      # history.json에 보관할 일수
KEEP_CURVE_DAYS = 5  # 장중 곡선을 보관할 일수

INV_COLS = ["individual", "foreign", "inst_total",
            "fin_invest", "insurance", "asset_mgmt", "bank",
            "other_fin", "pension", "other_corp"]
PRG_COLS = ["arb_buy", "arb_sell", "arb_net",
            "nonarb_buy", "nonarb_sell", "nonarb_net",
            "total_buy", "total_sell", "total_net"]


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


def get_html(url):
    r = get(url)
    r.encoding = "euc-kr"
    return BeautifulSoup(r.text, "lxml")


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


def snapshot_provisional():
    """시세 메인페이지 lst_kos_info: 개인/외국인/기관 + 차익/비차익/전체 (잠정, 억원)."""
    soup = get_html(f"{BASE}/sise_index.naver?code=KOSPI")
    dl = soup.select_one("dl.lst_kos_info")
    if dl is None:
        raise RuntimeError("lst_kos_info 블록을 찾지 못함 (페이지 구조 변경?)")
    vals = []
    for dd in dl.select("dd.dd"):
        m = re.search(r"([+\-]?[\d,]+)", dd.get_text())
        vals.append(num(m.group(1)) if m else None)
    if len(vals) != 6:
        raise RuntimeError(f"잠정치 6개 기대, {len(vals)}개 파싱됨: {vals}")
    ind, frn, inst, arb, nonarb, total = vals
    return {"individual": ind, "foreign": frn, "institution": inst,
            "arb": arb, "nonarb": nonarb, "program": total}


def _table_rows(soup, ncols):
    """type_1 계열 테이블에서 [첫칸텍스트, 숫자…] 행들을 뽑는다."""
    rows = []
    for tr in soup.select("table tr"):
        tds = tr.find_all("td")
        if len(tds) < ncols + 1:
            continue
        head = tds[0].get_text(strip=True)
        nums = [num(td.get_text(strip=True)) for td in tds[1:ncols + 1]]
        if head and all(v is not None for v in nums):
            rows.append((head, nums))
    return rows


def parse_date(s):
    """'26.07.30' → '2026-07-30'"""
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{2})", s)
    if not m:
        return None
    return f"20{m.group(1)}-{m.group(2)}-{m.group(3)}"


def detect_unit(soup):
    """페이지 본문에서 '단위 : 계약/억원' 표기를 찾는다."""
    m = re.search(r"단위\s*[:：]?\s*(계약|억원|백만원|천주)",
                  soup.get_text(" ", strip=True))
    return m.group(1) if m else None


def futures_daily(bizdate, pages=3):
    """KOSPI200 선물 투자자별 일별 순매수 (sosok=03, 코스피 탭과 동일 템플릿).
    반환: ({date: {INV_COLS…}}, 단위문자열)"""
    out, unit = {}, None
    for page in range(1, pages + 1):
        soup = get_html(f"{BASE}/investorDealTrendDay.naver"
                        f"?bizdate={bizdate}&sosok=03&page={page}")
        if unit is None:
            unit = detect_unit(soup)
        for head, nums in _table_rows(soup, 10):
            d = parse_date(head)
            if d:
                out.setdefault(d, dict(zip(INV_COLS, nums)))
    return out, unit or "계약"


def daily_confirmed(bizdate, pages=3):
    """일별 확정: 투자자별(10칸) + 프로그램(9칸). {date: {"investor":…, "program":…}}"""
    out = {}
    for page in range(1, pages + 1):
        soup = get_html(f"{BASE}/investorDealTrendDay.naver?bizdate={bizdate}&page={page}")
        for head, nums in _table_rows(soup, 10):
            d = parse_date(head)
            if d:
                out.setdefault(d, {})["investor"] = dict(zip(INV_COLS, nums))
    for page in range(1, pages + 1):
        soup = get_html(f"{BASE}/programDealTrendDay.naver?bizdate={bizdate}&page={page}")
        for head, nums in _table_rows(soup, 9):
            d = parse_date(head)
            if d:
                out.setdefault(d, {})["program"] = dict(zip(PRG_COLS, nums))
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


def stock_foreign_flow(top=7):
    """한투 OpenAPI '국내기관_외국인 매매종목가집계'(FHPTJ04400000) — 장중 잠정.
    외국인 순매수/순매도 상위 종목을 금액 기준으로 뽑는다.
    반환: {"time": "HH:MM", "buy": [[종목명, 등락률%, 순매수억], …], "sell": […]} 또는 None
    (KIS_APP_KEY/SECRET 미설정이면 None — 섹션만 비표시)"""
    key = os.environ.get("KIS_APP_KEY")
    sec = os.environ.get("KIS_APP_SECRET")
    if not key or not sec:
        print("KIS 키 미설정 → 종목별 외국인 수급 생략")
        return None
    r = SESSION.post(f"{KIS_BASE}/oauth2/tokenP", timeout=15, json={
        "grant_type": "client_credentials", "appkey": key, "appsecret": sec})
    r.raise_for_status()
    hdr = {"authorization": f"Bearer {r.json()['access_token']}",
           "appkey": key, "appsecret": sec, "tr_id": "FHPTJ04400000", "custtype": "P"}
    out = {"time": now_kst().strftime("%H:%M")}
    for name, sort_cls in (("buy", "0"), ("sell", "1")):
        p = {"FID_COND_MRKT_DIV_CODE": "V", "FID_COND_SCR_DIV_CODE": "16449",
             "FID_INPUT_ISCD": "0000",          # 전체 시장
             "FID_DIV_CLS_CODE": "1",           # 금액 기준 정렬
             "FID_RANK_SORT_CLS_CODE": sort_cls,  # 0 순매수상위 / 1 순매도상위
             "FID_ETC_CLS_CODE": "1"}           # 외국인
        rr = SESSION.get(f"{KIS_BASE}/uapi/domestic-stock/v1/quotations/foreign-institution-total",
                         headers=hdr, params=p, timeout=15)
        rr.raise_for_status()
        j = rr.json()
        if j.get("rt_cd") != "0":
            raise RuntimeError(f"KIS 가집계 오류: {j.get('msg1')}")
        rows = []
        for x in j.get("output", [])[:top]:
            rows.append([x["hts_kor_isnm"], float(x["prdy_ctrt"]),
                         round(int(x["frgn_ntby_tr_pbmn"]) / 100)])  # 백만원 → 억원
        out[name] = rows
    print(f"외국인 종목별 가집계: 매수 {len(out['buy'])} · 매도 {len(out['sell'])}종목")
    return out


def intraday_curve(bizdate, kind, max_pages=45, sosok=None):
    """시간대별 누적치(분 단위)를 전 페이지 수집 후 10분 간격으로 샘플링.
    kind: "investor"(10칸 → 개인/외인/기관만) 또는 "program"(9칸 → 차익순/비차익순/전체순)
    sosok="03"이면 K200 선물 탭.
    반환: [["HH:MM", a, b, c], …] (시간 오름차순)"""
    url = f"{BASE}/{'investorDealTrendTime' if kind == 'investor' else 'programDealTrendTime'}.naver"
    ncols = 10 if kind == "investor" else 9
    extra = f"&sosok={sosok}" if sosok else ""
    by_time = {}
    for page in range(1, max_pages + 1):
        soup = get_html(f"{url}?bizdate={bizdate}&page={page}{extra}")
        rows = _table_rows(soup, ncols)
        if not rows:
            break
        for head, nums in rows:
            if not re.match(r"\d{2}:\d{2}", head):
                continue
            if kind == "investor":
                by_time[head] = [nums[0], nums[1], nums[2]]          # 개인, 외국인, 기관계
            else:
                by_time[head] = [nums[2], nums[5], nums[8]]          # 차익순, 비차익순, 전체순
        if by_time and min(by_time) <= "09:02":   # 장 시작까지 다 받았으면 종료
            break
    # 10분 격자(09:10~15:30)마다 그 시각 이전의 마지막 관측치를 채택
    times = sorted(t for t in by_time if "09:00" <= t <= "15:35")
    grid, out = [], []
    h, m = 9, 10
    while (h, m) <= (15, 30):
        grid.append(f"{h:02d}:{m:02d}")
        m += 10
        if m >= 60:
            h, m = h + 1, 0
    for g in grid:
        prev = [t for t in times if t <= g]
        if prev:
            out.append([g] + by_time[prev[-1]])
    return out


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

    snap = snapshot_provisional()
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
        sf = stock_foreign_flow()
        if sf:
            day["stock_flow"] = sf
    except Exception as e:
        print(f"⚠️ 종목별 외국인 가집계 수집 실패(섹션 비표시): {e}")

    # 마감 이후 실행이면 장중 곡선 저장
    if slot in ("1540", "1640"):
        day["curve"] = {
            "investor": intraday_curve(bizdate, "investor"),
            "program": intraday_curve(bizdate, "program"),
        }
        try:
            fc = intraday_curve(bizdate, "investor", sosok="03")
            if fc:
                day["curve"]["futures"] = fc
        except Exception as e:
            print(f"⚠️ 선물 장중 곡선 수집 실패: {e}")
        print(f"장중 곡선: investor {len(day['curve']['investor'])}점, "
              f"program {len(day['curve']['program'])}점, "
              f"futures {len(day['curve'].get('futures', []))}점")

    save_history(hist)
    write_meta(True, slot=slot)
    print(f"저장 완료: {HISTORY}")


if __name__ == "__main__":
    main()
