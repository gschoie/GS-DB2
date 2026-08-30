"""규칙 파서 계약 테스트 — 네트워크 없이 산식만 검증한다."""

import sys
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rules import KST, detect_kind, extract_dates, is_candidate, rule_extract

# 2026-08-28은 금요일
BASE = datetime(2026, 8, 28, 9, 30, tzinfo=KST)


class Candidate(unittest.TestCase):
    def test_vacation_report_is_candidate(self):
        self.assertTrue(is_candidate("다음주 월요일 연차입니다"))
        self.assertTrue(is_candidate("9/2~9/4 여름휴가 다녀올게"))
        self.assertTrue(is_candidate("내일 오후 반차 쓸게요"))

    def test_smalltalk_is_not(self):
        self.assertFalse(is_candidate("점심 뭐 먹지"))
        self.assertFalse(is_candidate("휴가철이라 길이 막히네"))
        self.assertFalse(is_candidate("휴가 잘 다녀왔어?"))
        self.assertFalse(is_candidate(""))


class Kind(unittest.TestCase):
    def test_longest_wins(self):
        self.assertEqual(detect_kind("내일 오후 반차"), "오후반차")
        self.assertEqual(detect_kind("반차 쓸게"), "반차")
        self.assertEqual(detect_kind("여름휴가 갑니다"), "여름휴가")
        self.assertIsNone(detect_kind("주말에 캠핑 감"))


class Dates(unittest.TestCase):
    def test_slash_range(self):
        self.assertEqual(extract_dates("9/2~9/4 휴가", BASE),
                         (date(2026, 9, 2), date(2026, 9, 4)))

    def test_korean_range(self):
        self.assertEqual(extract_dates("9월 2일부터 9월 4일까지 연차", BASE),
                         (date(2026, 9, 2), date(2026, 9, 4)))

    def test_single_day(self):
        self.assertEqual(extract_dates("9월 1일 연차입니다", BASE),
                         (date(2026, 9, 1), date(2026, 9, 1)))

    def test_relative(self):
        self.assertEqual(extract_dates("내일 반차요", BASE),
                         (date(2026, 8, 29), date(2026, 8, 29)))
        self.assertEqual(extract_dates("모레부터 글피까지 휴가", BASE),
                         (date(2026, 8, 30), date(2026, 8, 31)))

    def test_next_week_weekday(self):
        # 기준일 금(8/28) → 다음주 수요일 = 9/2
        self.assertEqual(extract_dates("다음주 수요일 연차", BASE),
                         (date(2026, 9, 2), date(2026, 9, 2)))

    def test_bare_weekday_is_upcoming(self):
        # 금요일 기준 '월요일' = 다가오는 8/31
        self.assertEqual(extract_dates("월요일에 휴무입니다", BASE),
                         (date(2026, 8, 31), date(2026, 8, 31)))

    def test_range_with_bare_end_weekday(self):
        # 금(8/28) 기준: 다음주 수요일=9/2, 뒤쪽 '금요일'은 같은 주 금요일 9/4
        self.assertEqual(extract_dates("다음주 수요일부터 금요일까지 연차", BASE),
                         (date(2026, 9, 2), date(2026, 9, 4)))

    def test_duration(self):
        self.assertEqual(extract_dates("9/7부터 3일간 휴가", BASE),
                         (date(2026, 9, 7), date(2026, 9, 9)))

    def test_year_rollover(self):
        # 8월에 말한 "1월 5일"은 내년이다
        self.assertEqual(extract_dates("1월 5일 연차 예정", BASE),
                         (date(2027, 1, 5), date(2027, 1, 5)))

    def test_no_date(self):
        self.assertEqual(extract_dates("조만간 휴가 낼게", BASE), (None, None))


class RuleExtract(unittest.TestCase):
    def test_full_entry(self):
        entry = rule_extract("9/2~9/4 연차 씁니다", BASE)
        self.assertEqual(entry["kind"], "연차")
        self.assertEqual(entry["start"], "2026-09-02")
        self.assertEqual(entry["end"], "2026-09-04")
        self.assertFalse(entry["needs_review"])

    def test_dateless_needs_review(self):
        entry = rule_extract("다다음달쯤 휴가 가려고", BASE)
        self.assertTrue(entry["needs_review"])
        self.assertIsNone(entry["start"])


if __name__ == "__main__":
    unittest.main()
