# -*- coding: utf-8 -*-
"""컨센서스 영업이익 수집.

- 이번분기(가장 가까운 추정 E 분기): 네이버 모바일 JSON API (토큰 불필요, 빠름)
- 연간 2026E/2027E/2028E: 종목분석>컨센서스 탭(c1050001) 헤드리스 렌더링
  ("주가 & 컨센서스" 재무연월 그리드 값이 JS로 수초 뒤 주입되므로 등장까지 폴링)
"""
import io
import re

import pandas as pd
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

QUARTER_API = "https://m.stock.naver.com/api/stock/{code}/finance/quarter"
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


def fetch_quarter(code, session=None):
    """이번분기(가장 가까운 E 분기) 영업이익 컨센. dict 또는 None."""
    s = session or requests
    headers = {"User-Agent": UA, "Referer": "https://m.stock.naver.com/"}
    try:
        d = s.get(QUARTER_API.format(code=code), headers=headers, timeout=10).json()
    except Exception:
        return None
    fi = d.get("financeInfo", {})
    titles = fi.get("trTitleList", [])
    rows = fi.get("rowList", [])
    # 가장 가까운 추정(E) 분기 = 시간순 첫 consensus 항목
    cons = [t for t in titles if t.get("isConsensus") == "Y"]
    if not cons:
        return None
    tgt = cons[0]
    key = tgt["key"]
    period = tgt["title"].rstrip(".")  # 'YYYY.MM'

    def val(title):
        row = next((r for r in rows if r.get("title", "").strip() == title), None)
        return _num(row["columns"].get(key, {}).get("value")) if row else None

    return {
        "period": period,
        "sales": val("매출액"),
        "op_profit": val("영업이익"),
        "net_profit": val("당기순이익") or val("당기순이익(지배)"),
    }


def scrape_annual(page, code, timeout_ms=20000):
    """연간 재무연월 그리드에서 추정(E) 연도들의 컨센 추출. list[dict].

    page: 재사용하는 Playwright Page. 각 종목마다 goto만 다시 호출.
    """
    page.goto(CONSENSUS_URL.format(code=code),
              wait_until="domcontentloaded", timeout=30000)
    try:
        page.wait_for_function(_GRID_READY_JS, timeout=timeout_ms)
    except Exception:
        return []

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
        if not m or m.group(3) != "E":   # 추정치만 저장 (실적은 안 변함)
            continue
        out.append({
            "period": f"{m.group(1)}.{m.group(2)}",
            "sales": _num(r.get(c_sales)) if c_sales else None,
            "op_profit": _num(r.get(c_op)) if c_op else None,
            "net_profit": _num(r.get(c_net)) if c_net else None,
        })
    return out
