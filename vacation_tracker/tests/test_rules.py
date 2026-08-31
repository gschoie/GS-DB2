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

    def test_trip_and_shoptour(self):
        self.assertEqual(detect_kind("다음주 해외 출장입니다"), "해외출장")
        self.assertEqual(detect_kind("내일부터 부산 출장"), "출장")
        self.assertEqual(detect_kind("9/3 샵투어 갑니다"), "샵투어")
        self.assertEqual(detect_kind("숍 투어 일정 잡혔어"), "샵투어")
        self.assertTrue(is_candidate("내일 출장 가요"))


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




class ContextCandidates(unittest.TestCase):
    """문답 맥락 — 키워드는 내 질문에, 날짜는 친구 답에 갈라진 경우."""

    def _msgs(self, *rows):
        from datetime import timedelta
        return [{"out": out, "text": text, "dt": BASE + timedelta(minutes=10 * i)}
                for i, (out, text) in enumerate(rows)]

    def test_question_then_date_answer(self):
        from rules import pick_candidates
        msgs = self._msgs((True, "아~ 카자흐스탄 출장은 언제~언제라궁"),
                          (False, "9/15화-9/18금 입니당"))
        picked = pick_candidates(msgs)
        self.assertEqual(len(picked), 1)
        self.assertEqual(picked[0]["trigger"], "context")
        self.assertEqual(picked[0]["kind_hint"], "출장")
        self.assertEqual(picked[0]["index"], 1)

    def test_dateless_reply_not_picked(self):
        from rules import pick_candidates
        msgs = self._msgs((True, "출장 언제야?"), (False, "넵 확인해볼게요 ㅎㅎ"))
        self.assertEqual(pick_candidates(msgs), [])

    def test_within_wide_window(self):
        # 키워드 뒤 잡담 몇 마디가 껴도(기본 윈도 10) 날짜 답이면 잡는다
        from rules import pick_candidates
        msgs = self._msgs((True, "출장 언제야?"), (False, "잠시만요"), (False, "회의 중"),
                          (False, "밥 먹자"), (False, "9/15에 봐요"))
        picked = pick_candidates(msgs)
        self.assertEqual([p["trigger"] for p in picked], ["context"])

    def test_window_expiry(self):
        from rules import pick_candidates
        filler = [(False, f"잡담 {i}") for i in range(11)]
        msgs = self._msgs((True, "출장 언제야?"), *filler, (False, "9/15에 봐요"))
        # 키워드로부터 12번째 뒤(윈도 10 초과) — 맥락으로 안 잡힌다
        self.assertEqual(pick_candidates(msgs), [])

    def test_my_message_never_candidate(self):
        from rules import pick_candidates
        msgs = self._msgs((True, "나 9/1 연차야"))
        self.assertEqual(pick_candidates(msgs), [])

    def test_keyword_still_direct(self):
        from rules import pick_candidates
        msgs = self._msgs((False, "저 내일 연차입니다"))
        picked = pick_candidates(msgs)
        self.assertEqual(picked[0]["trigger"], "keyword")


class KazakhDates(unittest.TestCase):
    def test_slash_range_with_weekday_suffix(self):
        # "9/15화-9/18금 입니당" — 요일 붙은 슬래시 구간
        self.assertEqual(extract_dates("9/15화-9/18금 입니당", BASE),
                         (date(2026, 9, 15), date(2026, 9, 18)))


class TravelKeyword(unittest.TestCase):
    def test_travel_report_is_candidate(self):
        self.assertEqual(detect_kind("다음주 제주 여행 갑니다"), "여행")
        self.assertTrue(is_candidate("9/5~9/7 여행 다녀올게요"))

    def test_travel_smalltalk_is_not(self):
        self.assertFalse(is_candidate("여행 가고 싶다"))
        self.assertFalse(is_candidate("여행 어땠어?"))
        self.assertFalse(is_candidate("여행사 추천 좀"))
if __name__ == "__main__":
    unittest.main()
