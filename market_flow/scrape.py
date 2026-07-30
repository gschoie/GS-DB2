# -*- coding: utf-8 -*-
"""네이버 파이낸스에서 KOSPI 수급 스냅샷을 수집해 data/history.json 에 누적한다.

하루 4회(10:00 / 13:00 / 15:40잠정 / 16:40확정 KST) GitHub Actions로 실행.
 - 매 실행: 시세 메인페이지의 투자자 잠정치(개인/외국인/기관) + 프로그램(차익/비차익/전체) 스냅샷
 - 매 실행: 일별 확정치 백필(투자자별·프로그램, 최근 3페이지 ≈ 30영업일)
 - 15:40/16:40 실행: 시간대별 누적 곡선(투자자·프로그램)을 10분 간격으로 샘플링해 저장
휴장일(모바일API localTradedAt 날짜 ≠ 오늘)은 아무것도 쓰지 않고 종료한다.
단위: 억원.
"""
import json
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


def intraday_curve(bizdate, kind, max_pages=45):
    """시간대별 누적치(분 단위)를 전 페이지 수집 후 10분 간격으로 샘플링.
    kind: "investor"(10칸 → 개인/외인/기관만) 또는 "program"(9칸 → 차익순/비차익순/전체순)
    반환: [["HH:MM", a, b, c], …] (시간 오름차순)"""
    url = f"{BASE}/{'investorDealTrendTime' if kind == 'investor' else 'programDealTrendTime'}.naver"
    ncols = 10 if kind == "investor" else 9
    by_time = {}
    for page in range(1, max_pages + 1):
        soup = get_html(f"{url}?bizdate={bizdate}&page={page}")
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

    # 마감 이후 실행이면 장중 곡선 저장
    if slot in ("1540", "1640"):
        day["curve"] = {
            "investor": intraday_curve(bizdate, "investor"),
            "program": intraday_curve(bizdate, "program"),
        }
        print(f"장중 곡선: investor {len(day['curve']['investor'])}점, "
              f"program {len(day['curve']['program'])}점")

    save_history(hist)
    write_meta(True, slot=slot)
    print(f"저장 완료: {HISTORY}")


if __name__ == "__main__":
    main()
