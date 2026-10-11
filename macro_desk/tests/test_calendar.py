# -*- coding: utf-8 -*-
"""발표일 계산 검산. 날짜 산수는 눈으로 보면 맞는 것 같아도 자주 틀린다."""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import calendar_rules as cr  # noqa: E402


class TestNthWeekday(unittest.TestCase):
    def test_first_friday(self):
        # 2026-10-01은 목요일 → 첫 금요일은 2일
        self.assertEqual(cr.nth_weekday(2026, 10, 1, cr.WD["fri"]), dt.date(2026, 10, 2))
        # 2026-05-01이 금요일인 달 — 1일이 바로 첫 금요일이어야 한다
        self.assertEqual(dt.date(2026, 5, 1).weekday(), 4)
        self.assertEqual(cr.nth_weekday(2026, 5, 1, cr.WD["fri"]), dt.date(2026, 5, 1))

    def test_last_friday(self):
        d = cr.nth_weekday(2026, 10, -1, cr.WD["fri"])
        self.assertEqual(d.weekday(), 4)
        self.assertEqual(d, dt.date(2026, 10, 30))
        # 마지막 금요일 + 7일은 다음 달이어야 한다(진짜 마지막인지 확인)
        self.assertNotEqual((d + dt.timedelta(days=7)).month, 10)

    def test_fifth_weekday_when_absent(self):
        """5번째 금요일이 없는 달을 요구하면 조용히 틀린 날을 주면 안 된다."""
        with self.assertRaises(IndexError):
            cr.nth_weekday(2026, 2, 5, cr.WD["fri"])


class TestBizday(unittest.TestCase):
    def test_first_bizday_skips_weekend(self):
        # 2026-08-01은 토요일 → 첫 영업일은 3일(월)
        self.assertEqual(dt.date(2026, 8, 1).weekday(), 5)
        self.assertEqual(cr.nth_bizday(2026, 8, 1), dt.date(2026, 8, 3))

    def test_third_bizday(self):
        self.assertEqual(cr.nth_bizday(2026, 10, 1), dt.date(2026, 10, 1))  # 목
        self.assertEqual(cr.nth_bizday(2026, 10, 3), dt.date(2026, 10, 5))  # 금 다음 월

    def test_overflow_clamps(self):
        self.assertEqual(cr.nth_bizday(2026, 2, 99).month, 2)


class TestOnDay(unittest.TestCase):
    def test_weekend_pushes_forward(self):
        # 2026-11-01은 일요일 → 2일(월)
        self.assertEqual(dt.date(2026, 11, 1).weekday(), 6)
        self.assertEqual(cr.on_day(2026, 11, 1), dt.date(2026, 11, 2))

    def test_short_month_clamps(self):
        self.assertEqual(cr.on_day(2026, 2, 31).month, 2)


class TestResolve(unittest.TestCase):
    PAYROLL = {"id": "us_payrolls", "name": "미국 고용보고서", "country": "US",
               "rule": {"nth_weekday": [1, "fri"]}}
    GDP = {"id": "us_gdp", "name": "미국 GDP", "country": "US",
           "rule": {"nth_weekday": [-1, "thu"]}, "months": [1, 4, 7, 10]}
    FOMC = {"id": "fomc", "name": "FOMC", "country": "US", "fixed": True}

    def test_monthly_rule(self):
        got = cr.resolve(self.PAYROLL, 2026, 10, fixed={})
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["date"], dt.date(2026, 10, 2))
        self.assertTrue(got[0]["estimated"])     # 규칙 추정 → ~ 표시 대상

    def test_quarterly_skips_other_months(self):
        self.assertEqual(cr.resolve(self.GDP, 2026, 10, fixed={}) and True, True)
        self.assertEqual(cr.resolve(self.GDP, 2026, 11, fixed={}), [])

    def test_fixed_without_data_is_empty(self):
        """FOMC 날짜를 모르면 **지어내지 말고 비워야** 한다."""
        self.assertEqual(cr.resolve(self.FOMC, 2026, 10, fixed={}), [])

    def test_fixed_with_data(self):
        got = cr.resolve(self.FOMC, 2026, 10,
                         fixed={"fomc": ["2026-10-28", "2026-12-09"]})
        self.assertEqual([g["date"] for g in got], [dt.date(2026, 10, 28)])
        self.assertFalse(got[0]["estimated"])    # 공표일이므로 ~ 없음

    def test_fixed_ignores_garbage(self):
        got = cr.resolve(self.FOMC, 2026, 10, fixed={"fomc": ["아무말", "2026-10-28"]})
        self.assertEqual(len(got), 1)

    def test_month_events_sorted(self):
        ev = cr.month_events([self.PAYROLL, self.GDP], 2026, 10, fixed={})
        self.assertEqual([e["date"] for e in ev], sorted(e["date"] for e in ev))


if __name__ == "__main__":
    unittest.main()
