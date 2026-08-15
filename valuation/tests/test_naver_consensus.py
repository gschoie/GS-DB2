# -*- coding: utf-8 -*-
"""네이버 '기업실적분석' 표 파싱 검산.

네이버는 이 컨테이너에서 막혀 있어 실호출 검증이 불가능하다 → 표의 '모양'을
그대로 흉내 낸 DataFrame 으로 파싱 규칙을 고정한다. 실제 응답과 어긋나면
러너 첫 실행에서 드러나지만, 최소한 파싱 로직 회귀는 여기서 잡힌다.
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import naver_consensus as nc


def realistic_table():
    """네이버 기업실적분석 표 구조: 열 머리글이 (구분, 기간, 기준) 3단이고
    추정치 열만 '(E)' 가 붙는다. 첫 열은 항목 이름."""
    columns = pd.MultiIndex.from_tuples([
        ("주요재무정보", "주요재무정보", "주요재무정보"),
        ("최근 연간 실적", "2024.12", "IFRS연결"),
        ("최근 연간 실적", "2025.12", "IFRS연결"),
        ("최근 연간 실적", "2026.12(E)", "IFRS연결"),
        ("최근 연간 실적", "2027.12(E)", "IFRS연결"),
    ])
    rows = [
        ["매출액", "1,000", "1,200", "1,400", "1,600"],
        ["당기순이익", "100", "120", "140", "160"],
        ["EPS(원)", "1,000", "1,200", "1,400", "1,600"],
        ["PER(배)", "12.50", "14.20", "9.80", "8.40"],
        ["BPS(원)", "10,000", "11,000", "12,000", "13,000"],
        ["PBR(배)", "1.25", "1.42", "0.98", "0.84"],
        ["ROE(지배주주)", "10.50", "11.20", "12.80", "13.40"],
    ]
    return pd.DataFrame(rows, columns=columns)


class Parsing(unittest.TestCase):
    def test_only_estimate_columns_are_returned(self):
        # 확정 실적(2024·2025)은 우리 산식으로 계산하므로 가져오지 않는다.
        out = nc.estimates("005380", tables=[realistic_table()])
        self.assertEqual(sorted(out), [2026, 2027])

    def test_values_are_parsed(self):
        out = nc.estimates("005380", tables=[realistic_table()])
        self.assertEqual(out[2026], {"per": 9.80, "pbr": 0.98, "roe": 12.80})
        self.assertEqual(out[2027]["per"], 8.40)

    def test_commas_and_dashes_handled(self):
        table = realistic_table()
        table.iloc[3, 3] = "1,234.5"     # PER 2026 에 천단위 구분
        table.iloc[5, 3] = "-"           # PBR 2026 결측
        out = nc.estimates("005380", tables=[table])
        self.assertEqual(out[2026]["per"], 1234.5)
        self.assertNotIn("pbr", out[2026])

    def test_wrong_table_is_skipped(self):
        noise = pd.DataFrame([["시가총액", "1조"], ["상장주식수", "100"]])
        out = nc.estimates("005380", tables=[noise, realistic_table()])
        self.assertEqual(sorted(out), [2026, 2027])

    def test_no_matching_table_returns_empty(self):
        noise = pd.DataFrame([["시가총액", "1조"]])
        self.assertEqual(nc.estimates("005380", tables=[noise]), {})

    def test_fetch_failure_returns_empty_not_raise(self):
        def boom(*a, **k):
            raise OSError("네이버 차단")
        saved = nc.read_tables
        nc.read_tables = boom
        try:
            self.assertEqual(nc.estimates("005380"), {})
        finally:
            nc.read_tables = saved


class ColumnYear(unittest.TestCase):
    def test_estimate_marker_detected(self):
        self.assertEqual(nc._column_year(("최근 연간 실적", "2026.12(E)", "IFRS연결")), (2026, True))

    def test_actual_column_not_marked(self):
        self.assertEqual(nc._column_year(("최근 연간 실적", "2025.12", "IFRS연결")), (2025, False))

    def test_non_year_column(self):
        self.assertEqual(nc._column_year("주요재무정보"), (None, False))

    def test_spaced_estimate_marker(self):
        # '2026.12 (E)' 처럼 공백이 끼어도 추정치로 본다.
        self.assertEqual(nc._column_year("2026.12 (E)"), (2026, True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
