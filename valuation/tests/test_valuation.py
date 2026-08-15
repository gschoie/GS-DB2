# -*- coding: utf-8 -*-
"""야후 응답을 가짜 Ticker로 갈아끼워 지표 산식을 검산한다.

야후는 러너 밖(개발 컨테이너)에서 막혀 있어 실호출 테스트가 불가능하다.
대신 응답 '모양'을 그대로 흉내 내서 PER·PBR·ROE·PSR 계산, 소단위 통화 환산,
컨센 롤포워드, 2년후 공란 처리를 손계산 값과 맞춰 본다.
"""

import json
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fetch_valuation as fv


def frame(rows, periods):
    return pd.DataFrame(rows, index=list(rows.keys()) and None, columns=periods) \
        if False else pd.DataFrame.from_dict(rows, orient="index", columns=periods)


PERIODS = [pd.Timestamp(d) for d in ("2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31")]

INCOME = frame({
    "Total Revenue":  [1000.0, 1200.0, 1400.0, 1600.0],
    "Net Income":     [100.0,  120.0,  140.0,  160.0],
    "EBITDA":         [200.0,  240.0,  280.0,  320.0],
    "Diluted Average Shares": [100.0, 100.0, 100.0, 100.0],
}, PERIODS)

BALANCE = frame({
    "Stockholders Equity":   [500.0, 600.0, 700.0, 800.0],
    "Total Debt":            [300.0, 300.0, 300.0, 300.0],
    "Cash And Cash Equivalents": [100.0, 100.0, 100.0, 100.0],
    "Ordinary Shares Number": [100.0, 100.0, 100.0, 100.0],
}, PERIODS)

HISTORY = pd.DataFrame(
    {"Close": [20.0, 24.0, 28.0, 32.0, 40.0]},
    index=pd.to_datetime(["2022-12-30", "2023-12-29", "2024-12-31", "2025-12-31", "2026-08-14"]),
)

EARNINGS_EST = pd.DataFrame({"avg": [0.5, 0.6, 2.0, 2.4]}, index=["0q", "+1q", "0y", "+1y"])
REVENUE_EST = pd.DataFrame({"avg": [400.0, 450.0, 1800.0, 2100.0]}, index=["0q", "+1q", "0y", "+1y"])

# 환율 시계열(주가통화 → 재무통화). 전 구간 0.5로 두면 환산 검산이 단순해진다.
FX_HISTORY = pd.DataFrame({"Close": [0.5] * 5}, index=HISTORY.index)


class FakeTicker:
    def __init__(self, info=None, history=None, income=None, balance=None,
                 earnings=None, revenue=None):
        self.info = info if info is not None else {"currency": "KRW", "financialCurrency": "KRW",
                                                   "payoutRatio": 0.2}
        self._history = HISTORY if history is None else history
        self.income_stmt = INCOME if income is None else income
        self.balance_sheet = BALANCE if balance is None else balance
        self.earnings_estimate = EARNINGS_EST if earnings is None else earnings
        self.revenue_estimate = REVENUE_EST if revenue is None else revenue

    def history(self, **kwargs):
        return self._history


COMPANY = {"industry": "방산", "sub": "체계", "region": "한국", "name": "테스트", "ticker": "000000.KS"}


def run(monkey_ticker, fx=None):
    """환율 조회('...=X')는 별도 가짜로 갈라 준다 — 종목 응답이 환율로 새지 않게."""
    original = fv.yf.Ticker
    fv.FX_CACHE.clear()   # 통화쌍 캐시는 프로세스 공유라 테스트마다 비운다

    def factory(symbol, *a, **k):
        if str(symbol).endswith("=X"):
            return FakeTicker(history=fx if fx is not None else pd.DataFrame())
        return monkey_ticker

    fv.yf.Ticker = factory
    try:
        return fv.collect(dict(COMPANY))
    finally:
        fv.yf.Ticker = original
        fv.FX_CACHE.clear()


class HistoricalMetrics(unittest.TestCase):
    def setUp(self):
        self.record = run(FakeTicker())
        self.years = {y["label"]: y for y in self.record["years"]}

    def test_four_actual_plus_three_forward_slots(self):
        labels = [y["label"] for y in self.record["years"]]
        self.assertEqual(labels, ["2022A", "2023A", "2024A", "2025A", "2026E", "2027E", "2028E"])

    def test_actual_multiples(self):
        # 2023A: 시총 = 24 × 100 = 2400 → PER 2400/120=20, PBR 2400/600=4, PSR 2400/1200=2
        y = self.years["2023A"]
        self.assertEqual(y["per"], 20.0)
        self.assertEqual(y["pbr"], 4.0)
        self.assertEqual(y["psr"], 2.0)

    def test_roe_uses_average_equity(self):
        # 2023A ROE = 120 / ((500+600)/2) = 21.82%
        self.assertEqual(self.years["2023A"]["roe"], 21.82)

    def test_oldest_year_falls_back_to_closing_equity(self):
        # 2022A 는 기초자본이 없으므로 기말자본 500 사용 → 100/500 = 20%
        self.assertEqual(self.years["2022A"]["roe"], 20.0)

    def test_per_share_values(self):
        self.assertEqual(self.years["2025A"]["eps"], 1.6)
        self.assertEqual(self.years["2025A"]["bps"], 8.0)


class ForwardConsensus(unittest.TestCase):
    def setUp(self):
        self.years = {y["label"]: y for y in run(FakeTicker())["years"]}

    def test_forward_per_and_psr_come_from_consensus(self):
        # 현재주가 40 / 컨센EPS 2.0 = 20배,  시총 4000 / 컨센매출 1800 = 2.22배
        self.assertEqual(self.years["2026E"]["per"], 20.0)
        self.assertEqual(self.years["2026E"]["psr"], 2.22)
        self.assertEqual(self.years["2027E"]["per"], 16.67)

    def test_forward_equity_rolls_forward_with_retention(self):
        # 예상자본 = 800 + (2.0×100)×0.8 = 960 → PBR = 4000/960 = 4.17
        self.assertEqual(self.years["2026E"]["pbr"], 4.17)
        # 다음 해는 960 위에 다시 굴린다: 960 + 240×0.8 = 1152 → 4000/1152 = 3.47
        self.assertEqual(self.years["2027E"]["pbr"], 3.47)

    def test_forward_roe_uses_average_projected_equity(self):
        # 200 / ((800+960)/2) = 22.73%
        self.assertEqual(self.years["2026E"]["roe"], 22.73)

    def test_forward_pbr_roe_flagged_as_derived(self):
        self.assertEqual(self.years["2026E"]["derived"], ["pbr", "roe"])

    def test_two_years_out_left_blank(self):
        far = self.years["2028E"]
        self.assertTrue(far["unavailable"])
        for metric in ("per", "pbr", "roe", "psr"):
            self.assertIsNone(far[metric])


class CurrencyHandling(unittest.TestCase):
    def test_pence_quotes_are_scaled_to_pounds(self):
        # 야후는 영국주를 pence 로 준다. 100으로 나눠야 재무제표(GBP)와 자릿수가 맞는다.
        ticker = FakeTicker(info={"currency": "GBp", "financialCurrency": "GBP", "payoutRatio": 0.2})
        years = {y["label"]: y for y in run(ticker)["years"]}
        self.assertEqual(years["2023A"]["price"], 0.24)      # 24 pence → 0.24 GBP
        self.assertEqual(years["2023A"]["per"], 0.2)          # 배수도 100분의 1로 정합
        self.assertEqual(run(ticker)["currency"], "GBP")

    def test_mismatched_currencies_are_converted_with_fx(self):
        # 두산밥캣형: 호가 KRW / 재무 USD. 시총을 재무통화로 환산해야 배수가 성립한다.
        # 환율 0.5 → 2023A 시총 2400 × 0.5 = 1200 → PER 1200/120 = 10 (환산 전 20의 절반)
        ticker = FakeTicker(info={"currency": "KRW", "financialCurrency": "USD", "payoutRatio": 0.2})
        record = run(ticker, fx=FX_HISTORY)
        year = {y["label"]: y for y in record["years"]}["2023A"]
        self.assertEqual(year["per"], 10.0)
        self.assertEqual(year["pbr"], 2.0)
        self.assertEqual(year["roe"], 21.82)   # ROE는 통화 무관(순이익/자본, 같은 재무통화)
        self.assertTrue(any("환산" in w for w in record["warnings"]))

    def test_forward_per_also_uses_converted_price(self):
        ticker = FakeTicker(info={"currency": "KRW", "financialCurrency": "USD", "payoutRatio": 0.2})
        years = {y["label"]: y for y in run(ticker, fx=FX_HISTORY)["years"]}
        # 현재주가 40 × 0.5 = 20 → 컨센EPS 2.0 대비 10배
        self.assertEqual(years["2026E"]["per"], 10.0)

    def test_mislabeled_financial_currency_is_not_converted(self):
        """두산밥캣 실제 사례: financialCurrency 는 USD인데 재무제표는 원화.

        그대로 환산하면 PER이 0.01배로 조용히 틀린다 → 환산 전 배수가 상식적이면
        야후 라벨을 무시하고 환산하지 않는다.
        """
        # 환율 0.001(원→달러 수준)을 주면 환산 시 PER 20 → 0.02 로 무너진다.
        cheap_fx = pd.DataFrame({"Close": [0.001] * 5}, index=HISTORY.index)
        ticker = FakeTicker(info={"currency": "KRW", "financialCurrency": "USD", "payoutRatio": 0.2})
        record = run(ticker, fx=cheap_fx)
        year = {y["label"]: y for y in record["years"]}["2023A"]
        self.assertEqual(year["per"], 20.0)      # 환산 안 한 원래 값이 유지된다
        self.assertTrue(any("환산하지 않았습니다" in w for w in record["warnings"]))

    def test_multiples_blank_when_fx_unavailable(self):
        # 환율을 못 구하면 틀린 숫자를 내놓느니 공란이 낫다.
        ticker = FakeTicker(info={"currency": "KRW", "financialCurrency": "USD"})
        record = run(ticker, fx=pd.DataFrame())
        year = {y["label"]: y for y in record["years"]}["2023A"]
        self.assertIsNone(year["per"])
        self.assertIsNone(year["pbr"])
        self.assertEqual(year["roe"], 21.82)
        self.assertTrue(any("구하지 못해" in w for w in record["warnings"]))


class TermResolution(unittest.TestCase):
    """회사명으로도 조회되게 — 'SK하이닉스' 처럼 티커를 모르고 넣는 게 자연스럽다."""

    def resolve(self, term, quotes=None):
        class FakeSearch:
            def __init__(self, *a, **k): self.quotes = quotes or []

        class FakeLookup:      # 검색이 비면 여기로 폴백한다 → 테스트가 실제 야후를 때리지 않게 막는다
            def __init__(self, *a, **k): pass
            def get_stock(self, **k): return None

        saved = getattr(fv.yf, "Search", None), getattr(fv.yf, "Lookup", None)
        fv.yf.Search, fv.yf.Lookup = FakeSearch, FakeLookup
        try:
            return fv.resolve_term(term)
        finally:
            for name, value in zip(("Search", "Lookup"), saved):
                if value is not None:
                    setattr(fv.yf, name, value)

    def test_ticker_shape_passes_through_untouched(self):
        # 티커꼴이면 검색하지 않고 그대로 쓴다(불필요한 야후 호출 방지).
        self.assertEqual(self.resolve("000660.KS")[0], "000660.KS")
        self.assertEqual(self.resolve("cat")[0], "CAT")
        self.assertEqual(self.resolve("SAAB-B.ST")[0], "SAAB-B.ST")

    def test_korean_name_is_searched(self):
        symbol, typed = self.resolve("SK하이닉스", quotes=[
            {"symbol": "000660.KS", "quoteType": "EQUITY"}])
        self.assertEqual(symbol, "000660.KS")
        self.assertEqual(typed, "SK하이닉스")

    def test_name_with_space_is_searched_not_split(self):
        symbol, _ = self.resolve("Samsung Electronics", quotes=[
            {"symbol": "005930.KS", "quoteType": "EQUITY"}])
        self.assertEqual(symbol, "005930.KS")

    def test_equity_is_preferred_over_etf(self):
        # ETF·지수가 먼저 잡히면 엉뚱한 종목을 조회하게 된다.
        symbol, _ = self.resolve("현대", quotes=[
            {"symbol": "PLUS.KS", "quoteType": "ETF"},
            {"symbol": "005380.KS", "quoteType": "EQUITY"}])
        self.assertEqual(symbol, "005380.KS")

    def test_no_match_returns_none(self):
        symbol, typed = self.resolve("존재하지않는회사", quotes=[])
        self.assertIsNone(symbol)
        self.assertEqual(typed, "존재하지않는회사")


class LookupRun(unittest.TestCase):
    """run_lookup 전체 경로를 실제로 태운다.

    이 함수는 유닛테스트가 없어서, 변수명을 바꾸다 한 줄을 놓친 NameError 가
    러너에서야 터졌다(조회가 통째로 죽고 커밋이 안 됨). 경로 전체를 굽는다.
    """

    def run_lookup(self, raw, quotes=None, existing=None):
        import tempfile
        from pathlib import Path

        class FakeSearch:
            def __init__(self, *a, **k): self.quotes = quotes or []

        class FakeLookup:
            def __init__(self, *a, **k): pass
            def get_stock(self, **k): return None

        tmp = Path(tempfile.mkdtemp()) / "valuation.json"
        if existing is not None:
            tmp.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")

        saved = (fv.OUT_JSON, fv.yf.Ticker,
                 getattr(fv.yf, "Search", None), getattr(fv.yf, "Lookup", None))
        fv.OUT_JSON = tmp
        fv.yf.Ticker = lambda s, *a, **k: FakeTicker(
            history=pd.DataFrame()) if str(s).endswith("=X") else FakeTicker()
        fv.yf.Search, fv.yf.Lookup = FakeSearch, FakeLookup
        fv.FX_CACHE.clear()
        try:
            fv.run_lookup(raw, 0)
            return json.loads(tmp.read_text(encoding="utf-8"))
        finally:
            fv.OUT_JSON, fv.yf.Ticker = saved[0], saved[1]
            for name, value in zip(("Search", "Lookup"), saved[2:]):
                if value is not None:
                    setattr(fv.yf, name, value)
            fv.FX_CACHE.clear()

    def test_lookup_completes_and_records_query(self):
        out = self.run_lookup("005930.KS", existing={"companies": [], "updated_at": "x"})
        self.assertEqual(out["adhoc_query"], "005930.KS")
        self.assertEqual(len(out["adhoc"]), 1)
        self.assertTrue(out["adhoc_at"])

    def test_regular_companies_are_preserved(self):
        prior = {"companies": [{"name": "기존"}], "updated_at": "2026-01-01T00:00:00+09:00"}
        out = self.run_lookup("005930.KS", existing=prior)
        self.assertEqual(out["companies"], prior["companies"])
        self.assertEqual(out["updated_at"], prior["updated_at"])

    def test_unresolved_name_is_reported_not_crashed(self):
        out = self.run_lookup("없는회사", quotes=[], existing={"companies": []})
        self.assertEqual(out["adhoc"][0]["ticker"], "-")
        self.assertIn("찾지 못했습니다", out["adhoc"][0]["warnings"][0])

    def test_korean_query_prefers_domestic_listing(self):
        # 야후는 'SK하이닉스'에 미국 ADR(SKHY)을 먼저 준다 → 국내 상장을 골라야 한다.
        out = self.run_lookup("SK하이닉스", quotes=[
            {"symbol": "SKHY", "quoteType": "EQUITY"},
            {"symbol": "000660.KS", "quoteType": "EQUITY"}], existing={"companies": []})
        self.assertEqual(out["adhoc"][0]["ticker"], "000660.KS")


class EnterpriseValue(unittest.TestCase):
    def setUp(self):
        self.years = {y["label"]: y for y in run(FakeTicker())["years"]}

    def test_ev_ebitda_uses_net_debt(self):
        # 2023A: EV = 시총 2400 + 차입 300 − 현금 100 = 2600 → EBITDA 240 대비 10.83배
        self.assertEqual(self.years["2023A"]["ev_ebitda"], 10.83)

    def test_ebitda_falls_back_to_operating_plus_depreciation(self):
        income = INCOME.drop(index=["EBITDA"])
        income.loc["Operating Income"] = [150.0, 180.0, 210.0, 240.0]
        income.loc["Reconciled Depreciation"] = [50.0, 60.0, 70.0, 80.0]
        years = {y["label"]: y for y in run(FakeTicker(income=income))["years"]}
        # 180 + 60 = 240 → 위와 같은 10.83배
        self.assertEqual(years["2023A"]["ev_ebitda"], 10.83)

    def test_forward_ev_ebitda_is_blank(self):
        # 야후에 EBITDA 컨센이 없어 만들지 않는다.
        self.assertIsNone(self.years["2026E"]["ev_ebitda"])


class GuardRails(unittest.TestCase):
    def test_loss_making_year_leaves_per_blank(self):
        income = INCOME.copy()
        income.loc["Net Income", PERIODS[1]] = -50.0
        years = {y["label"]: y for y in run(FakeTicker(income=income))["years"]}
        self.assertIsNone(years["2023A"]["per"])   # 적자 PER은 음수로 찍지 않고 공란
        # ROE는 다르다 — 적자면 마이너스 ROE 자체가 해석 가능한 정보라 그대로 남긴다.
        # (-50 / ((500+600)/2) = -9.09%)  분모(자본)가 0 이하일 때만 공란이 된다.
        self.assertEqual(years["2023A"]["roe"], -9.09)
        self.assertEqual(years["2024A"]["per"], 20.0)   # 다른 해는 정상

    def test_missing_history_yields_warning_not_crash(self):
        record = run(FakeTicker(history=pd.DataFrame()))
        self.assertEqual(record["years"], [])
        self.assertTrue(record["warnings"])

    def test_missing_estimates_leave_forward_blank(self):
        years = {y["label"]: y for y in run(FakeTicker(earnings=pd.DataFrame()))["years"]}
        self.assertIsNone(years["2026E"]["per"])
        self.assertEqual(years["2025A"]["per"], 20.0)

    def test_alternate_row_names_are_picked_up(self):
        income = INCOME.rename(index={"Total Revenue": "Operating Revenue",
                                      "Net Income": "Net Income Common Stockholders"})
        balance = BALANCE.rename(index={"Stockholders Equity": "Total Stockholders Equity"})
        years = {y["label"]: y for y in run(FakeTicker(income=income, balance=balance))["years"]}
        self.assertEqual(years["2023A"]["per"], 20.0)
        self.assertEqual(years["2023A"]["pbr"], 4.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
