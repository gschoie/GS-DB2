# -*- coding: utf-8 -*-
"""네이버 모바일 금융 API(financeInfo) 파싱 검산.

네이버는 이 컨테이너에서 막혀 있어 실호출 검증이 불가능하다 → 응답 '모양'을
그대로 흉내 낸 financeInfo dict 로 파싱 규칙을 고정한다(kospi_consensus 의
fetch_quarters 가 러너에서 검증한 그 모양). 실제 응답과 어긋나면 러너 첫 실행의
'📊 네이버 컨센/분기 재무 적용' 로그 부재로 드러난다.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import naver_consensus as nc


def finance_info(periods, rows):
    """periods: [('2026.12.', est여부), …] / rows: {행제목: [값, …]} → financeInfo."""
    keys = [f"c{i}" for i in range(len(periods))]
    tr = [{"key": k, "title": p, "isConsensus": "Y" if est else "N"}
          for k, (p, est) in zip(keys, periods)]
    row_list = [{"title": t, "columns": {k: {"value": v} for k, v in zip(keys, vals)}}
                for t, vals in rows.items()]
    return {"trTitleList": tr, "rowList": row_list}


ANNUAL = finance_info(
    [("2024.12.", False), ("2025.12.", False), ("2026.12.", True), ("2027.12.", True)],
    {
        "매출액": ["1,000", "1,200", "1,400", "1,600"],
        "영업이익": ["200", "240", "280", "320"],
        "영업이익률": ["20.00", "20.00", "20.00", "20.00"],
        "당기순이익": ["100", "120", "140", "160"],
        "PER(배)": ["12.50", "14.20", "9.80", "8.40"],
        "PBR(배)": ["1.25", "1.42", "0.98", "0.84"],
        "ROE(지배주주지분)": ["10.50", "11.20", "12.80", "13.40"],
    })

QUARTER = finance_info(
    [("2026.03.", False), ("2026.06.", False), ("2026.09.", True)],
    {
        "매출액": ["300", "320", "350"],
        "영업이익": ["60", "64", "70"],
        "영업이익률": ["20.00", "20.00", "20.00"],
        "당기순이익(지배)": ["30", "32", "36"],
        "PER(배)": ["-", "-", "99.00"],
    })


class Estimates(unittest.TestCase):
    def test_only_estimate_columns_are_returned(self):
        # 확정 실적(2024·2025)은 우리 산식으로 계산하므로 가져오지 않는다.
        out = nc.estimates("005380", finance=ANNUAL)
        self.assertEqual(sorted(out), [2026, 2027])

    def test_values_are_parsed(self):
        out = nc.estimates("005380", finance=ANNUAL)
        self.assertEqual(out[2026], {"per": 9.80, "pbr": 0.98, "roe": 12.80})
        self.assertEqual(out[2027]["per"], 8.40)

    def test_dashes_and_commas_handled(self):
        info = finance_info(
            [("2026.12.", True)],
            {"PER(배)": ["1,234.5"], "PBR(배)": ["-"], "ROE(지배주주지분)": ["12.8"]})
        out = nc.estimates("005380", finance=info)
        self.assertEqual(out[2026]["per"], 1234.5)
        self.assertNotIn("pbr", out[2026])

    def test_null_financeinfo_returns_empty(self):
        # 재무 정보가 없는 종목은 financeInfo 가 null 로 온다 → 빈 dict.
        self.assertEqual(nc.estimates("005380", finance=None), {})

    def test_fetch_failure_returns_empty_not_raise(self):
        def boom(*a, **k):
            raise OSError("네이버 차단")
        saved = nc.fetch_finance
        nc.fetch_finance = boom
        try:
            self.assertEqual(nc.estimates("005380"), {})
        finally:
            nc.fetch_finance = saved


class FinancialRows(unittest.TestCase):
    """연간·분기 매출/영업이익/당기순이익 파싱(억원 → 원 환산)."""

    def test_quarterly_and_annual_split(self):
        out = nc.financial_rows("005380", annual=ANNUAL, quarter=QUARTER)
        self.assertEqual([(q["year"], q["month"], q["est"]) for q in out["quarterly"]],
                         [(2026, 3, False), (2026, 6, False), (2026, 9, True)])
        self.assertEqual([(a["year"], a["est"]) for a in out["annual"]],
                         [(2024, False), (2025, False), (2026, True), (2027, True)])

    def test_values_scaled_to_won(self):
        out = nc.financial_rows("005380", annual=ANNUAL, quarter=QUARTER)
        q = out["quarterly"][0]                      # 2026.03
        self.assertEqual(q["sales"], 300e8)
        self.assertEqual(q["op"], 60e8)              # '영업이익률' 행에 걸리면 20×1e8 이 된다
        self.assertEqual(q["ni"], 30e8)              # '당기순이익(지배)' 도 잡힌다

    def test_failed_fetch_passed_in_yields_empty(self):
        # None(조회 실패)을 넘기면 다시 조회하지 않고 그 축만 비운다.
        out = nc.financial_rows("005380", annual=None, quarter=QUARTER)
        self.assertEqual(out["annual"], [])
        self.assertEqual(len(out["quarterly"]), 3)

    def test_fetch_failure_returns_empty_not_raise(self):
        def boom(*a, **k):
            raise OSError("네이버 차단")
        saved = nc.fetch_finance
        nc.fetch_finance = boom
        try:
            out = nc.financial_rows("005380")
        finally:
            nc.fetch_finance = saved
        self.assertEqual(out, {"quarterly": [], "annual": []})


class Columns(unittest.TestCase):
    def test_estimate_marker_from_isconsensus(self):
        info = finance_info([("2026.12.", True), ("2025.12.", False)], {"매출액": ["1", "2"]})
        cols = nc._columns(info)
        self.assertEqual([(y, m, e) for _, y, m, e in cols],
                         [(2026, 12, True), (2025, 12, False)])

    def test_non_period_column_dropped(self):
        info = {"trTitleList": [{"key": "c0", "title": "주요재무정보"}], "rowList": []}
        self.assertEqual(nc._columns(info), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
