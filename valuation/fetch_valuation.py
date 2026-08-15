# -*- coding: utf-8 -*-
"""야후 파이낸스 → 종목별 PER·PBR·ROE·PSR (과거 4개 회계연도 + 컨센서스 기준 올해·내년).

산출: valuation/data/valuation.json  (화면·엑셀이 공통으로 읽는 단일 원본)

지표 정의
---------
과거(A, 실적 확정): 해당 회계연도 '기말 주가 × 기말 주식수'를 시총으로 잡아
  PER = 시총 / 지배주주순이익      PBR = 시총 / 자본총계(기말)
  PSR = 시총 / 매출액              ROE = 순이익 / 자본총계(기초·기말 평균)
  → ROE만 평균자본을 쓴다. 증자·이익유보로 자본이 급증한 해(한화에어로 등)에
    기말자본으로 나누면 ROE가 실제보다 크게 눌리기 때문. 기초자본이 없는
    가장 오래된 연도만 기말자본으로 폴백한다.

컨센서스(E): 야후가 제공하는 건 EPS·매출 컨센 두 개뿐이고, 그것도 '올해(0y)·
  내년(+1y)' 두 해까지다(2년후 항목 자체가 없음).
  PER = 현재주가 / 컨센EPS        PSR = 현재시총 / 컨센매출
  PBR·ROE 는 컨센이 존재하지 않아 이익잉여금 롤포워드로 자체 산출한다:
    예상자본_t = 예상자본_{t-1} + 컨센순이익_t × (1 - 배당성향)
    PBR = 현재시총 / 예상자본_t   ROE = 컨센순이익_t / 평균예상자본
  → 화면·엑셀에서 (자체추정) 으로 따로 표기한다. 컨센 원본이 아님을 숨기지 않는다.

통화 처리
---------
야후는 영국(GBp)·이스라엘(ILA)·남아공(ZAc) 주가를 '소단위'로 준다. 재무제표는
정단위(GBP)라 그대로 나누면 PER 이 100배로 튄다 → 소단위는 100으로 나눠 맞춘다.
그래도 주가통화와 재무통화가 다르면(해외상장 등) 비율이 왜곡되므로 경고를 남기고
해당 종목의 배수는 버린다.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

from companies import TARGET_COMPANIES

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
OUT_JSON = ROOT / "data" / "valuation.json"

HISTORY_YEARS = 4        # 과거 회계연도 수 (야후 무료 API가 안정적으로 주는 범위)
FORWARD_YEARS = 3        # 올해·내년·2년후 슬롯 (2년후는 야후 미제공 → 공란)
KST = timezone(timedelta(hours=9))

# 야후가 소단위로 호가하는 통화 → 정단위 환산 계수
MINOR_UNITS = {"GBp": 100.0, "ILA": 100.0, "ZAc": 100.0, "GBX": 100.0}

# 재무제표 행 이름은 종목·지역마다 조금씩 다르다. 앞에서부터 처음 잡히는 걸 쓴다.
ROW_NET_INCOME = [
    "Net Income Common Stockholders", "Net Income", "Net Income Continuous Operations",
    "Net Income From Continuing Operation Net Minority Interest",
]
ROW_REVENUE = ["Total Revenue", "Operating Revenue"]
ROW_EQUITY = [
    "Stockholders Equity", "Total Stockholders Equity",
    "Common Stock Equity", "Total Equity Gross Minority Interest",
]
ROW_SHARES_BS = ["Ordinary Shares Number", "Share Issued"]
ROW_SHARES_IS = ["Diluted Average Shares", "Basic Average Shares"]
ROW_EBITDA = ["EBITDA", "Normalized EBITDA"]
ROW_OPERATING = ["Operating Income", "Total Operating Income As Reported"]
ROW_DEPRECIATION = [
    "Reconciled Depreciation", "Depreciation And Amortization",
    "Depreciation Amortization Depletion",
]
ROW_DEBT = ["Total Debt", "Total Debt And Capital Lease Obligation"]
ROW_CASH = ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"]

# 환율 시계열 캐시. 종목마다 같은 통화쌍을 다시 받지 않도록 프로세스 전체에서 공유한다.
FX_CACHE = {}


def fx_history(base, quote):
    """base→quote 환율 시계열. 같은 통화면 None(=환산 불필요)."""
    if not base or not quote or base == quote:
        return None
    key = (base, quote)
    if key in FX_CACHE:
        return FX_CACHE[key]
    pair = f"{base}{quote}=X"
    frame = call_with_retry(f"환율 {pair}", lambda: yf.Ticker(pair).history(period="6y", auto_adjust=False))
    series = None
    if frame is not None and not frame.empty and "Close" in frame:
        series = frame["Close"].copy()
        series.index = pd.to_datetime(series.index).tz_localize(None).normalize()
        series = series[~series.index.duplicated(keep="last")]
    FX_CACHE[key] = series
    return series


def fx_at(series, when):
    """해당 시점(회계연도 기말) 이전 마지막 환율. 시계열이 없으면 1.0(환산 안 함)."""
    if series is None or series.empty:
        return 1.0
    window = series.loc[series.index <= when]
    rate = num(window.iloc[-1]) if not window.empty else num(series.iloc[0])
    return rate if rate else 1.0


def num(value):
    """NaN·None·inf 를 전부 None 으로 눕힌다(JSON 직렬화 + 이후 계산 가드용)."""
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(out) or math.isinf(out)) else out


def ratio(numerator, denominator):
    """분모가 0·음수·결측이면 배수를 만들지 않는다.

    적자(순이익<0)·자본잠식(자본<0) 종목의 PER/PBR 은 음수로 찍어봐야 해석이
    불가능하고 정렬만 망친다 → 공란이 정직하다.
    """
    n, d = num(numerator), num(denominator)
    if n is None or d is None or d <= 0:
        return None
    return round(n / d, 2)


def pct(numerator, denominator):
    n, d = num(numerator), num(denominator)
    if n is None or d is None or d <= 0:
        return None
    return round(n / d * 100, 2)


def pick(frame, names):
    """재무제표에서 후보 행 이름 중 처음 존재하는 행을 Series 로 돌려준다."""
    if frame is None or not hasattr(frame, "index") or frame.empty:
        return None
    for name in names:
        if name in frame.index:
            row = frame.loc[name]
            # 같은 이름의 행이 두 번 나오면 DataFrame 이 되어 돌아온다 → 첫 행만.
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            return row
    return None


def at(series, column):
    return None if series is None or column not in series.index else num(series[column])


def call_with_retry(label, fn, attempts=3, wait=3.0):
    """야후는 러너 IP를 간헐적으로 스로틀한다 → 짧게 재시도하고 그래도 안 되면 포기."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt == attempts:
                print(f"    · {label} 실패({attempt}/{attempts}): {exc}")
                return None
            time.sleep(wait * attempt)
    return None


def price_on_or_before(history, when):
    """해당 일자(회계연도 기말) 이전 마지막 거래일 종가."""
    if history is None or history.empty:
        return None
    window = history.loc[history.index <= when]
    return num(window.iloc[-1]) if not window.empty else None


def estimate_row(frame, key):
    """earnings_estimate / revenue_estimate 에서 '0y'·'+1y' 행의 avg 컨센을 뽑는다."""
    if frame is None or not hasattr(frame, "index") or frame.empty:
        return None
    if key not in frame.index:
        return None
    row = frame.loc[key]
    for column in ("avg", "average", "Avg. Estimate", "avgEstimate"):
        if column in row.index:
            return num(row[column])
    return None


def collect(company):
    ticker = company["ticker"]
    record = {**company, "warnings": []}
    stock = yf.Ticker(ticker)

    info = call_with_retry("info", lambda: stock.info) or {}
    history = call_with_retry("history", lambda: stock.history(period="6y", auto_adjust=False))
    income = call_with_retry("income_stmt", lambda: stock.income_stmt)
    balance = call_with_retry("balance_sheet", lambda: stock.balance_sheet)

    if history is None or history.empty:
        record["warnings"].append("주가 이력을 가져오지 못했습니다")
        record["years"] = []
        return record

    closes = history["Close"].copy()
    closes.index = pd.to_datetime(closes.index).tz_localize(None).normalize()
    closes = closes[~closes.index.duplicated(keep="last")]

    # ── 통화 정합성 ─────────────────────────────────────────
    quote_ccy = info.get("currency") or ""
    fin_ccy = info.get("financialCurrency") or quote_ccy
    scale = MINOR_UNITS.get(quote_ccy, 1.0)
    if scale != 1.0:
        closes = closes / scale
    normalized_quote = "GBP" if quote_ccy in ("GBp", "GBX") else quote_ccy

    # 주가통화 ≠ 재무통화인 종목이 실제로 있다(두산밥캣: 호가 KRW / 재무 USD).
    # 시총(주가통화)을 재무통화로 환산해야 배수가 성립한다. 환율을 못 구하면
    # 그때만 배수를 포기한다 — 잘못된 100배·1400배 숫자를 내놓는 것보다 공란이 낫다.
    fx_to_fin = None
    currency_ok = True
    if normalized_quote and fin_ccy and normalized_quote != fin_ccy:
        fx_to_fin = fx_history(normalized_quote, fin_ccy)
        if fx_to_fin is None:
            currency_ok = False
            record["warnings"].append(
                f"주가통화({quote_ccy})와 재무통화({fin_ccy})가 다른데 환율을 구하지 못해 배수를 비웠습니다"
            )
        else:
            record["warnings"].append(
                f"재무통화({fin_ccy})가 주가통화({normalized_quote})와 달라 환율로 환산했습니다"
            )

    # 시가총액은 종목 간 비교를 위해 백만달러로 통일한다.
    fx_to_usd = fx_history(normalized_quote, "USD")

    record["currency"] = normalized_quote or None
    record["fin_currency"] = fin_ccy or None
    current_price = num(closes.iloc[-1])
    record["price"] = round(current_price, 2) if current_price else None
    record["price_date"] = closes.index[-1].date().isoformat()

    net_income = pick(income, ROW_NET_INCOME)
    revenue = pick(income, ROW_REVENUE)
    equity = pick(balance, ROW_EQUITY)
    shares_bs = pick(balance, ROW_SHARES_BS)
    shares_is = pick(income, ROW_SHARES_IS)
    ebitda_row = pick(income, ROW_EBITDA)
    operating_row = pick(income, ROW_OPERATING)
    depreciation_row = pick(income, ROW_DEPRECIATION)
    debt_row = pick(balance, ROW_DEBT)
    cash_row = pick(balance, ROW_CASH)

    if net_income is None or equity is None:
        record["warnings"].append("연간 재무제표를 가져오지 못했습니다")

    # ── 과거 회계연도 ───────────────────────────────────────
    periods = []
    if income is not None and hasattr(income, "columns") and not income.empty:
        periods = sorted([c for c in income.columns], reverse=True)[:HISTORY_YEARS]
    periods = sorted(periods)  # 오래된 연도 → 최근 연도 순으로 표시

    years = []
    prior_equity = None
    latest_fy = None
    latest_shares = None
    for period in periods:
        stamp = pd.Timestamp(period).tz_localize(None).normalize()
        fy = stamp.year
        latest_fy = fy

        ni = at(net_income, period)
        rev = at(revenue, period)
        eq = at(equity, period)
        shares = at(shares_bs, period) or at(shares_is, period)
        close = price_on_or_before(closes, stamp)
        # 시총은 주가통화 → 재무통화로 환산해야 손익·자본과 같은 잣대가 된다.
        market_cap = (close * shares * fx_at(fx_to_fin, stamp)) if (close and shares) else None
        if shares:
            latest_shares = shares

        # EV/EBITDA. EBITDA 행이 없으면 영업이익 + 감가상각으로 만든다.
        ebitda = at(ebitda_row, period)
        if ebitda is None:
            op, da = at(operating_row, period), at(depreciation_row, period)
            ebitda = (op + da) if (op is not None and da is not None) else None
        debt, cash = at(debt_row, period), at(cash_row, period)
        enterprise = None
        if market_cap is not None:
            enterprise = market_cap + (debt or 0) - (cash or 0)

        # ROE 는 기초·기말 평균자본. 첫 연도(기초 없음)만 기말자본으로 폴백한다.
        avg_equity = eq
        if eq is not None and prior_equity is not None:
            avg_equity = (eq + prior_equity) / 2

        usable = currency_ok
        years.append({
            "label": f"{fy}A",
            "year": fy,
            "kind": "A",
            "per": ratio(market_cap, ni) if usable else None,
            "pbr": ratio(market_cap, eq) if usable else None,
            "psr": ratio(market_cap, rev) if usable else None,
            "roe": pct(ni, avg_equity),
            "ev_ebitda": ratio(enterprise, ebitda) if usable else None,
            "eps": round(ni / shares, 2) if (ni and shares) else None,
            "bps": round(eq / shares, 2) if (eq and shares) else None,
            "revenue": rev,
            "net_income": ni,
            "equity": eq,
            "price": round(close, 2) if close else None,
        })
        prior_equity = eq

    # ── 컨센서스(올해·내년) ─────────────────────────────────
    earnings_est = call_with_retry("earnings_estimate", lambda: stock.earnings_estimate)
    revenue_est = call_with_retry("revenue_estimate", lambda: stock.revenue_estimate)

    last_stamp = closes.index[-1]
    quote_cap_now = None                       # 주가통화 기준 현재 시총
    if current_price and latest_shares:
        quote_cap_now = current_price * latest_shares
    if not quote_cap_now:
        raw_cap = num(info.get("marketCap"))
        # info.marketCap 은 호가통화 기준 → 소단위 종목은 여기서도 맞춰준다.
        quote_cap_now = raw_cap / scale if raw_cap else None

    # 배수 계산은 재무통화 기준 시총으로, 화면 표기는 백만달러로.
    fin_rate = fx_at(fx_to_fin, last_stamp)
    market_cap_now = quote_cap_now * fin_rate if quote_cap_now else None
    record["market_cap"] = market_cap_now
    usd_rate = fx_at(fx_to_usd, last_stamp)
    record["market_cap_musd"] = round(quote_cap_now * usd_rate / 1_000_000) if quote_cap_now else None
    # 컨센 EPS·매출은 재무통화 기준이므로 주가도 재무통화로 맞춰 나눈다.
    price_in_fin = current_price * fin_rate if current_price else None

    payout = num(info.get("payoutRatio"))
    if payout is None or payout < 0 or payout > 1:
        payout = 0.0
    retention = 1.0 - payout

    # 야후의 '올해(0y)'는 진행 중인 회계연도 → 마지막 확정 연도 + 1.
    base_year = (latest_fy + 1) if latest_fy else datetime.now(KST).year
    forward_equity = prior_equity  # 마지막 확정 회계연도의 기말자본
    forward_keys = ["0y", "+1y"]   # 야후가 주는 건 여기까지. 2년후는 항목이 없다.

    for offset in range(FORWARD_YEARS):
        fy = base_year + offset
        key = forward_keys[offset] if offset < len(forward_keys) else None

        eps_est = estimate_row(earnings_est, key) if key else None
        rev_est = estimate_row(revenue_est, key) if key else None

        if key is None:
            # 2년후 슬롯: 야후에 컨센 자체가 없어 비워 둔다(추정으로 채우지 않음).
            years.append({
                "label": f"{fy}E", "year": fy, "kind": "E", "unavailable": True,
                "per": None, "pbr": None, "psr": None, "roe": None, "ev_ebitda": None,
                "eps": None, "bps": None, "revenue": None,
                "net_income": None, "equity": None, "price": None,
            })
            continue

        ni_est = (eps_est * latest_shares) if (eps_est and latest_shares) else None

        # 이익잉여금 롤포워드로 예상자본을 굴린다(컨센이 아니라 자체 산출).
        opening_equity = forward_equity
        closing_equity = None
        if opening_equity is not None and ni_est is not None:
            closing_equity = opening_equity + ni_est * retention
            forward_equity = closing_equity
        avg_equity = None
        if opening_equity is not None and closing_equity is not None:
            avg_equity = (opening_equity + closing_equity) / 2

        usable = currency_ok
        years.append({
            "label": f"{fy}E",
            "year": fy,
            "kind": "E",
            "per": ratio(price_in_fin, eps_est) if usable else None,
            "pbr": ratio(market_cap_now, closing_equity) if usable else None,
            "psr": ratio(market_cap_now, rev_est) if usable else None,
            "roe": pct(ni_est, avg_equity),
            # EV/EBITDA 컨센은 야후에 EBITDA 추정이 없어 만들 수 없다 → 공란.
            "ev_ebitda": None,
            "eps": round(eps_est, 2) if eps_est else None,
            "bps": round(closing_equity / latest_shares, 2) if (closing_equity and latest_shares) else None,
            "revenue": rev_est,
            "net_income": ni_est,
            "equity": closing_equity,
            "price": round(current_price, 2) if current_price else None,
            # PER·PSR 은 야후 컨센 원본, PBR·ROE 는 롤포워드 자체 산출임을 화면에 알린다.
            "derived": ["pbr", "roe"],
        })

    record["years"] = years
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="쉼표로 구분한 티커만 수집(디버깅용)")
    parser.add_argument("--sleep", type=float, default=1.0, help="종목 간 대기(초)")
    args = parser.parse_args()

    targets = TARGET_COMPANIES
    if args.only:
        wanted = {t.strip() for t in args.only.split(",") if t.strip()}
        targets = [c for c in TARGET_COMPANIES if c["ticker"] in wanted]

    print(f"📊 밸류에이션 수집 시작 — {len(targets)}개 종목")
    results = []
    for index, company in enumerate(targets, 1):
        print(f"[{index}/{len(targets)}] {company['name']} ({company['ticker']})")
        try:
            record = collect(company)
        except Exception as exc:
            print(f"    ❌ 실패: {exc}")
            record = {**company, "warnings": [f"수집 실패: {exc}"], "years": []}
        filled = sum(1 for y in record.get("years", []) if y.get("per") or y.get("roe"))
        print(f"    → 연도 {len(record.get('years', []))}개 (지표 있음 {filled}개)"
              + (f" ⚠️ {record['warnings'][0]}" if record.get("warnings") else ""))
        results.append(record)
        if args.sleep:
            time.sleep(args.sleep)

    payload = {
        "updated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "history_years": HISTORY_YEARS,
        "companies": results,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    ok = sum(1 for r in results if r.get("years") and not r.get("warnings"))
    print(f"\n✅ 저장: {OUT_JSON}  (정상 {ok} / 전체 {len(results)})")


if __name__ == "__main__":
    main()
