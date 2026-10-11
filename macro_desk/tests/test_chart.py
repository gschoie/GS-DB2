# -*- coding: utf-8 -*-
"""시계열 저장과 화면 조립 검산 — 네트워크 없이.

꼭 잡아야 하는 것
  · **날짜와 값이 밀리면 차트가 조용히 다른 날짜를 가리킨다.** 한쪽만 dropna 한
    코드가 바로 그 사고를 낸다 → 길이가 다르면 예외.
  · 날짜는 **YYMMDD 고정폭 6자**를 이어 붙인 문자열이다. 한 자라도 어긋나면
    i 번째 날짜를 slice 로 못 꺼내고 전부 밀린다.
  · **시계열이 없으면 누를 수 있는 줄을 만들지 않는다** — 수집이 한 번 더 돌기
    전에는 series 가 없다. 눌러도 아무 일 없는 줄은 고장으로 보인다.
  · 달력 칩의 직전치에는 **'직전' 과 몇 월분인지**가 붙어야 한다. 전에는 아무 말
    없이 숫자만 찍혀 컨센(앞을 보는 숫자)과 분간이 안 됐다.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_report as br  # noqa: E402
import collect as col  # noqa: E402


def mkdates(n: int, start: int = 260101) -> list[str]:
    """YYMMDD 비슷한 더미 — 날짜 산수가 아니라 자릿수·정렬만 본다."""
    return [f"{start + i:06d}" for i in range(n)]


class TestSeries(unittest.TestCase):
    def test_keeps_last_n(self):
        n = col.SERIES_N + 40
        s = col._series(mkdates(n), [float(i) for i in range(n)])
        self.assertEqual(len(s["v"]), col.SERIES_N)
        self.assertEqual(s["v"][-1], float(n - 1))          # 최신이 마지막
        self.assertEqual(len(s["d"]), col.SERIES_N * 6)

    def test_short_series_kept_whole(self):
        s = col._series(mkdates(5), [1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertEqual(s["v"], [1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertEqual(len(s["d"]), 30)

    def test_dates_and_values_stay_aligned(self):
        d = mkdates(10)
        s = col._series(d, [float(i) for i in range(10)])
        for i in range(10):                                  # i 번째 날짜 = slice
            self.assertEqual(s["d"][i * 6:i * 6 + 6], d[i])

    def test_length_mismatch_raises(self):
        # 값만 dropna 하면 날짜가 밀린다 — 조용히 넘어가면 안 된다
        with self.assertRaises(ValueError):
            col._series(mkdates(9), [1.0] * 10)

    def test_bad_date_width_raises(self):
        with self.assertRaises(ValueError):
            col._series(["2026-01-01"] * 3, [1.0, 2.0, 3.0])

    def test_rounds_values(self):
        s = col._series(mkdates(1), [1.23456789])
        self.assertEqual(s["v"], [1.2346])


CFG = {
    "quotes": [{"group": "미국 금리·채권", "items": [
        {"id": "us10y", "name": "미국 10년물", "unit": "pct"},
        {"id": "us30y", "name": "미국 30년물", "unit": "pct"},
    ]}],
    "fred": [{"id": "t10y2y", "name": "10년-2년 스프레드", "unit": "pct"}],
    "calendar": [],
}

SER = {"v": [1.0, 2.0, 3.0], "d": "260101260102260103"}
DATA = {
    "has_fred": True,
    "quotes": {"us10y": {"last": 5.24, "1D": {"diff": 0.01, "pct": 0.2}, "series": SER},
               "us30y": {"last": 5.60}},                     # 시계열 없음
    "fred": {"t10y2y": {"last": 0.44, "series": SER}},
    "releases": {},
}


class TestSeriesJson(unittest.TestCase):
    def test_only_items_with_series(self):
        s = json.loads(br.series_json(CFG, DATA))
        self.assertEqual(sorted(s), ["t10y2y", "us10y"])
        self.assertNotIn("us30y", s)

    def test_carries_name_and_unit(self):
        s = json.loads(br.series_json(CFG, DATA))
        self.assertEqual(s["us10y"]["n"], "미국 10년물")
        self.assertEqual(s["us10y"]["u"], "pct")
        self.assertEqual(s["us10y"]["d"], SER["d"])

    def test_empty_without_fred(self):
        s = json.loads(br.series_json(CFG, {**DATA, "has_fred": False}))
        self.assertNotIn("t10y2y", s)

    def test_valid_json_even_when_nothing_has_series(self):
        bare = {"quotes": {"us30y": {"last": 5.6}}, "fred": {}, "releases": {}}
        self.assertEqual(json.loads(br.series_json(CFG, bare)), {})


class TestQuoteRows(unittest.TestCase):
    def test_clickable_only_with_series(self):
        html = br.quote_table(CFG, DATA)
        self.assertIn('data-q="us10y"', html)
        self.assertIn('data-q="t10y2y"', html)
        self.assertNotIn('data-q="us30y"', html)             # 눌러도 할 게 없는 줄

    def test_no_clickable_rows_before_first_collect(self):
        bare = {"quotes": {"us10y": {"last": 5.24}}, "fred": {}, "releases": {}}
        html = br.quote_table({**CFG, "fred": []}, bare)
        self.assertIn("미국 10년물", html)
        self.assertNotIn("qrow", html)


class TestChipLabel(unittest.TestCase):
    """칩의 '전년 +5.4%' 가 이번 예상인지 지난 발표인지 분간되던가."""

    ENTRY = {"id": "us_ppi", "name": "미국 생산자물가 PPI", "country": "US",
             "guide": "us_ppi"}
    REL = {"us_ppi": {"text": "전년 +5.4% · 전월 +0.4%", "period": "2026년 8월"}}

    def test_prev_release_is_labelled_with_month(self):
        html = br.chip(self.ENTRY, self.REL, {})
        self.assertIn("직전 8월", html)
        self.assertIn("+5.4%", html)

    def test_consensus_wins_and_says_so(self):
        cons = {"us_ppi": {"text": "전년 +3.7%"}}
        html = br.chip(self.ENTRY, self.REL, cons)
        self.assertIn("컨센", html)
        self.assertNotIn("직전", html)                        # 칩 한 줄엔 하나만

    def test_short_period(self):
        self.assertEqual(br._short_period("2026년 8월"), "8월")
        self.assertEqual(br._short_period("2026년 2분기"), "2분기")
        self.assertEqual(br._short_period(None), "")
        self.assertEqual(br._short_period(""), "")

    def test_no_numbers_at_all(self):
        html = br.chip(self.ENTRY, {}, {})
        self.assertNotIn("직전", html)
        self.assertNotIn("컨센", html)


class TestGuideNumbers(unittest.TestCase):
    CFG = {"calendar": [
        {"id": "us_cpi", "name": "미국 소비자물가 CPI", "guide": "us_cpi"},
        {"id": "us_ism_mfg", "name": "미국 ISM 제조업", "guide": "us_ism"},
        {"id": "us_ism_svc", "name": "미국 ISM 서비스업", "guide": "us_ism"},
        {"id": "nope", "name": "가이드 없음"},
    ]}
    REL = {"us_cpi": {"text": "전년 +3.4% · 전월 +0.3%", "period": "2026년 8월",
                      "recent": ["-0.4", "+0.1", "+0.3"]},
           "us_ism_mfg": {"text": "48.2", "period": "2026년 9월"}}
    CONS = {"us_cpi": {"text": "전년 +3.7% · 코어 +2.4%", "for": "2026-10-14 발표(9월분)"}}

    def test_both_sides_labelled(self):
        out = br.guide_numbers(self.CFG, self.REL, self.CONS)
        card = "".join(out["us_cpi"])
        self.assertIn("컨센서스", card)
        self.assertIn("직전 발표", card)
        self.assertIn("2026년 8월", card)                     # 몇 월분인지
        self.assertIn("2026-10-14 발표(9월분)", card)
        self.assertIn("최근 3회", card)

    def test_names_shown_when_several_share_a_card(self):
        out = br.guide_numbers(self.CFG, self.REL, self.CONS)
        self.assertIn("미국 ISM 제조업", "".join(out["us_ism"]))

    def test_single_entry_needs_no_name(self):
        out = br.guide_numbers(self.CFG, self.REL, self.CONS)
        self.assertNotIn("미국 소비자물가 CPI", "".join(out["us_cpi"]))

    def test_indicator_without_numbers_is_absent(self):
        out = br.guide_numbers(self.CFG, {}, {})
        self.assertEqual(out, {})

    def test_cards_render_without_numbers(self):
        guide = {"indicators": {"us_cpi": {"name": "CPI", "read": []}}}
        self.assertIn('id="g-us_cpi"', br.indicator_cards(guide))


class TestRichText(unittest.TestCase):
    """guide.yml 의 **굵게** 가 화면에 별표로 찍히던 것."""

    def test_bold(self):
        self.assertEqual(br.rich("**헤드라인**은 전부"), "<b>헤드라인</b>은 전부")

    def test_two_pairs(self):
        self.assertEqual(br.rich("**가**와 **나**"), "<b>가</b>와 <b>나</b>")

    def test_unpaired_asterisks_left_alone(self):
        self.assertEqual(br.rich("**짝없음"), "**짝없음")

    def test_newlines(self):
        self.assertEqual(br.rich("가\n나"), "가<br>나")

    def test_escapes_html_first(self):
        # esc 를 먼저 하므로 rich 가 만드는 <b> 말고는 태그가 들어올 수 없다
        self.assertEqual(br.rich("<script>"), "&lt;script&gt;")
        self.assertNotIn("<i>", br.rich("**<i>x</i>**"))

    def test_empty(self):
        self.assertEqual(br.rich(""), "")
        self.assertEqual(br.rich(None), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
