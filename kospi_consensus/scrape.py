# -*- coding: utf-8 -*-
"""컨센서스 영업이익 수집.

- 이번분기(가장 가까운 추정 E 분기): 네이버 모바일 JSON API (토큰 불필요, 빠름)
- 연간 2026E/2027E/2028E: 종목분석>컨센서스 탭(c1050001) 헤드리스 렌더링
  ("주가 & 컨센서스" 재무연월 그리드 값이 JS로 수초 뒤 주입되므로 등장까지 폴링)
"""
import datetime as dt
import io
import json as _json
import re

import pandas as pd
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

QUARTER_API = "https://m.stock.naver.com/api/stock/{code}/finance/quarter"
PRICE_API = ("https://api.finance.naver.com/siseJson.naver?symbol={code}"
             "&requestType=1&startTime={s}&endTime={e}&timeframe=day")
CONSENSUS_URL = "https://navercomp.wisereport.co.kr/company/c1050001.aspx?cmp_cd={code}&cn="

# 그리드 값이 채워질 때까지 대기: 재무연월 테이블에 콤마숫자가 등장하면 준비 완료
_GRID_READY_JS = (
    "() => { for (const t of document.querySelectorAll('table')) {"
    " const x = t.innerText;"
    " if (x.includes('재무연월') && /\\d{2,},\\d{3}/.test(x)) return true;"
    " } return false; }"
)


def _num(x):
    if x is None:
        return None
    s = str(x).replace(",", "").strip()
    if s in ("", "-", "N/A", "nan", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fetch_quarters(code, session=None):
    """분기 영업이익: 추정(E) 전부 + 과거 실적(A) 분기. 시간순 list[dict] (없으면 빈 리스트).

    - est=True: 컨센서스(E). 당분기뿐 아니라 다음 분기도 저장해 두면 당분기 시점이
      넘어가도 다음 분기의 리비전 히스토리가 이미 쌓여 있게 된다.
    - est=False: 확정 실적(A). 화면의 QoQ/YoY(직전·전년 분기 대비) 분모용.
    """
    s = session or requests
    headers = {"User-Agent": UA, "Referer": "https://m.stock.naver.com/"}
    try:
        d = s.get(QUARTER_API.format(code=code), headers=headers, timeout=10).json()
    except Exception:
        return []
    # 재무 정보가 없는 종목(신규상장·지주 등)은 financeInfo가 null로 온다 → 빈 결과
    fi = (d.get("financeInfo") if isinstance(d, dict) else None) or {}
    titles = fi.get("trTitleList") or []
    rows = fi.get("rowList") or []

    def val(title, key):
        row = next((r for r in rows if r.get("title", "").strip() == title), None)
        return _num(((row.get("columns") or {}).get(key) or {}).get("value")) if row else None

    out = []
    for tgt in titles:
        key = tgt.get("key")
        period = str(tgt.get("title", "")).rstrip(".")  # 'YYYY.MM'
        if not key or not re.match(r"^20\d\d\.(03|06|09|12)$", period):
            continue
        out.append({
            "period": period,
            "est": tgt.get("isConsensus") == "Y",
            "sales": val("매출액", key),
            "op_profit": val("영업이익", key),
            "net_profit": val("당기순이익", key) or val("당기순이익(지배)", key),
        })
    return out


def fetch_close(code, on_date=None, session=None):
    """on_date(또는 오늘) 이하 최근 거래일의 종가. dict{price_date, close} 또는 None."""
    s = session or requests
    end = on_date or dt.date.today()
    if isinstance(end, str):
        end = dt.date.fromisoformat(end)
    start = end - dt.timedelta(days=14)
    u = PRICE_API.format(code=code, s=start.strftime("%Y%m%d"), e=end.strftime("%Y%m%d"))
    try:
        txt = s.get(u, headers={"User-Agent": UA, "Referer": "https://finance.naver.com/"},
                    timeout=10).text.strip()
        rows = _json.loads(txt.replace("'", '"'))
    except Exception:
        return None
    data = [r for r in rows[1:] if r and r[4] not in (None, "", 0)]
    if not data:
        return None
    last = data[-1]
    d = str(last[0])
    return {"price_date": f"{d[:4]}-{d[4:6]}-{d[6:8]}", "close": float(last[4])}


def _parse_grid(page):
    """현재 화면의 재무연월 그리드를 파싱. list[dict(period, est, sales, op_profit, net_profit)]."""
    grid_html = None
    for t in page.query_selector_all("table"):
        tx = t.inner_text()
        if "재무연월" in tx and re.search(r"\d{2,},\d{3}", tx):
            grid_html = t.evaluate("el => el.outerHTML")
            break
    if not grid_html:
        return []

    df = pd.read_html(io.StringIO(grid_html))[0]
    cols = [" ".join(str(x) for x in c) if isinstance(c, tuple) else str(c)
            for c in df.columns]
    df.columns = cols

    def col(key):
        return next((c for c in cols if key in c), None)

    c_period = col("재무연월")
    c_sales = col("매출액")
    c_op = col("영업이익")
    c_net = col("당기순이익")

    out = []
    for _, r in df.iterrows():
        p = str(r.get(c_period, ""))
        m = re.match(r"(20\d\d)\.(\d\d)\((A|E)\)", p)
        if not m:
            continue
        out.append({
            "period": f"{m.group(1)}.{m.group(2)}",
            "est": m.group(3) == "E",
            "sales": _num(r.get(c_sales)) if c_sales else None,
            "op_profit": _num(r.get(c_op)) if c_op else None,
            "net_profit": _num(r.get(c_net)) if c_net else None,
        })
    return out


# 그리드가 원하는 모드인지: 연간 = 12월 결산 행만, 분기 = 03/06/09월 행 존재
_GRID_MODE_JS = (
    "(wantQuarter) => { for (const t of document.querySelectorAll('table')) {"
    " const x = t.innerText;"
    " if (!x.includes('재무연월') || !/\\d{2,},\\d{3}/.test(x)) continue;"
    " const hasQ = /20\\d\\d\\.(03|06|09)\\(/.test(x);"
    " return wantQuarter ? hasQ : !hasQ;"
    " } return false; }"
)


def scrape_wisereport(page, code, timeout_ms=20000):
    """컨센서스 탭 재무연월 그리드에서 연간 + 분기 둘 다 추출 (A/E 모두).

    그리드에 연간/분기 토글이 있고 분기 모드에는 fwd 분기 컨센(당분기+2개, E)이 있다.
    토글 상태가 세션에 들러붙으므로(한 종목에서 분기를 누르면 다음 종목도 분기로 열림)
    종목마다 '연간 클릭→파싱→분기 클릭→파싱'으로 모드를 명시한다.
    반환: (annual_rows, quarter_rows). page는 재사용하는 Playwright Page.
    """
    page.goto(CONSENSUS_URL.format(code=code),
              wait_until="domcontentloaded", timeout=30000)
    try:
        page.wait_for_function(_GRID_READY_JS, timeout=timeout_ms)
    except Exception:
        return [], []

    out = {}
    for want_q, label in ((False, "연간"), (True, "분기")):
        # 클릭이 간헐적으로 안 먹는다(10/15 첫 전체 run에서 종목 10개의 연간이 빠짐)
        # → 클릭+모드대기를 2회 시도. 토글이 없거나 이미 그 모드면 클릭 실패해도 대기가 통과한다.
        for attempt in range(2):
            try:
                page.get_by_text(label, exact=True).first.click(timeout=3000)
            except Exception:
                pass
            try:
                page.wait_for_function(_GRID_MODE_JS, arg=want_q,
                                       timeout=timeout_ms if attempt == 0 else 8000)
                out[want_q] = _parse_grid(page)
                break
            except Exception:
                continue   # 재클릭 후 한 번 더 — 그래도 안 뜨면 해당 모드만 건너뜀
    return out.get(False, []), out.get(True, [])


def scrape_annual(page, code, timeout_ms=20000):
    """(하위호환) 연간 그리드만. 신규 코드는 scrape_wisereport를 쓸 것."""
    annual, _ = scrape_wisereport(page, code, timeout_ms)
    return annual
