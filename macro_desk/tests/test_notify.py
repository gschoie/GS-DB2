# -*- coding: utf-8 -*-
"""텔레그램 발송 본문 검산 — 네트워크 없이 조립만 본다.

여기서 꼭 잡아야 하는 것
  · **밴드는 순서가 규칙이다** — 위에서부터 처음 맞는 것 하나. 뒤집히면 '5% 이상'
    대신 '3~4%' 가 걸려 반대 뜻이 나간다.
  · **값을 모르면 아무 밴드도 고르지 않는다** — 30번 교훈(빈 값을 '없음'으로 읽는
    코드는 조용히 반대로 동작한다)의 같은 부류.
  · **금리는 %p · 나머지는 %** — 섞으면 "10년물이 6% 올랐다"로 읽힌다.
  · **FRED 키가 있으면 야후 us2y(실은 5년물)는 빠진다** — 진짜 2년물과 나란히
    서면 숫자 둘이 어긋나 보인다.
  · **Gemini 키가 없으면 '한 줄' 블록만 빠지고 나머지는 그대로 간다.**
"""
import datetime as dt
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import notify as nt  # noqa: E402

KST = dt.timezone(dt.timedelta(hours=9))

BANDS = [
    {"ge": 5.0, "say": "5% 이상 — 비싸다"},
    {"ge": 4.0, "say": "4~5% — 높다"},
    {"ge": 3.0, "say": "3~4% — 보통"},
    {"say": "3% 미만 — 낮다"},
]

CFG = {
    "quotes": [
        {"group": "미국 금리·채권", "items": [
            {"id": "us2y", "name": "미국 2년물", "unit": "pct"},
            {"id": "us10y", "name": "미국 10년물", "unit": "pct"},
            {"id": "us30y", "name": "미국 30년물", "unit": "pct"},
        ]},
        {"group": "달러·환율", "items": [
            {"id": "usdkrw", "name": "원/달러", "unit": "krw"},
        ]},
    ],
    "fred": [{"id": "dgs2", "name": "미국 2년물(FRED)", "unit": "pct"}],
    "calendar": [],
}

GUIDE = {"quote_reads": {
    "us10y": {"name": "미 10년물", "unit": "pct", "bands": BANDS},
    "t10y2y": {"name": "10−2년 스프레드", "unit": "pp", "bands": [
        {"lt": 0, "say": "역전 — 침체 신호"},
        {"say": "정상 — 장기가 단기보다 높다"}]},
}}

DATA = {
    "date": "2026-10-11",
    "has_fred": True,
    "quotes": {
        "us2y": {"last": 5.021, "1D": {"diff": 0.03, "pct": 0.6}},
        "us10y": {"last": 5.244, "1D": {"diff": 0.013, "pct": 0.25}},
        "us30y": {},                              # 못 받은 칸
        "usdkrw": {"last": 1340.9, "1D": {"diff": -2.09, "pct": -0.16}},
    },
    "fred": {"dgs2": {"last": 4.75, "1D": {"diff": -0.02, "pct": -0.42}},
             "t10y2y": {"last": 0.44, "1D": {"diff": -0.03, "pct": -6.38}}},
    "releases": {},
}


class TestPickBand(unittest.TestCase):
    def test_first_match_wins(self):
        self.assertEqual(nt.pick_band(5.24, BANDS)["say"], "5% 이상 — 비싸다")
        self.assertEqual(nt.pick_band(4.00, BANDS)["say"], "4~5% — 높다")
        self.assertEqual(nt.pick_band(3.99, BANDS)["say"], "3~4% — 보통")
        self.assertEqual(nt.pick_band(2.10, BANDS)["say"], "3% 미만 — 낮다")

    def test_boundary_is_inclusive_on_ge(self):
        # ge 는 '이상' — 경계값은 그 밴드에 들어간다
        self.assertEqual(nt.pick_band(5.0, BANDS)["say"], "5% 이상 — 비싸다")

    def test_lt_is_exclusive(self):
        b = [{"lt": 0, "say": "역전"}, {"say": "정상"}]
        self.assertEqual(nt.pick_band(-0.01, b)["say"], "역전")
        self.assertEqual(nt.pick_band(0.0, b)["say"], "정상")   # 0 은 역전이 아니다

    def test_unknown_value_picks_nothing(self):
        # 모르는 값을 폴백 밴드로 흘려보내면 '3% 미만' 이 사실처럼 나간다
        self.assertIsNone(nt.pick_band(None, BANDS))

    def test_no_bands(self):
        self.assertIsNone(nt.pick_band(1.0, []))
        self.assertIsNone(nt.pick_band(1.0, None))

    def test_no_fallback_defined(self):
        self.assertIsNone(nt.pick_band(1.0, [{"ge": 5.0, "say": "높다"}]))


class TestFormat(unittest.TestCase):
    def test_value_units(self):
        self.assertEqual(nt.fmt_value(5.244, "pct"), "5.24%")
        self.assertEqual(nt.fmt_value(1340.9, "krw"), "1,340.9원")
        self.assertEqual(nt.fmt_value(91.85, "usd"), "$91.85")
        self.assertEqual(nt.fmt_value(14.84, "idx"), "14.84")
        self.assertEqual(nt.fmt_value(None, "pct"), "–")

    def test_spread_gets_sign_and_pp(self):
        # 스프레드를 '0.44%' 로 적으면 수익률처럼 읽힌다
        self.assertEqual(nt.fmt_value(0.44, "pp"), "+0.44%p")
        self.assertEqual(nt.fmt_value(-0.12, "pp"), "-0.12%p")

    def test_change_pct_is_points_others_percent(self):
        ch = {"diff": 0.013, "pct": 0.25}
        self.assertEqual(nt.fmt_change(ch, "pct"), "+0.01%p")
        self.assertEqual(nt.fmt_change(ch, "krw"), "+0.25%")
        self.assertEqual(nt.fmt_change({}, "pct"), "")


class TestQuoteBlocks(unittest.TestCase):
    def test_drops_yahoo_2y_when_real_one_exists(self):
        out = nt.quote_blocks(CFG, DATA)
        self.assertIn("미국 2년물(FRED) 4.75%", out)
        self.assertNotIn("미국 2년물 5.02%", out)

    def test_keeps_yahoo_2y_without_fred(self):
        data = {**DATA, "has_fred": False}
        out = nt.quote_blocks(CFG, data)
        self.assertIn("미국 2년물 5.02%", out)
        self.assertNotIn("FRED", out)

    def test_missing_value_is_omitted_not_dashed(self):
        out = nt.quote_blocks(CFG, DATA)
        self.assertNotIn("미국 30년물", out)
        self.assertNotIn("–", out)

    def test_groups_and_line_wrapping(self):
        out = nt.quote_blocks(CFG, DATA, per_line=2)
        self.assertIn("〈미국 금리·채권〉", out)
        self.assertIn("〈달러·환율〉", out)
        # us10y 하나만 남은 그룹이라 한 줄
        self.assertIn("미국 10년물 5.24% (+0.01%p)", out)


class TestBandBlock(unittest.TestCase):
    def test_lines_and_facts(self):
        block, facts = nt.band_block(GUIDE, DATA)
        self.assertIn("· 미 10년물 5.24% → 5% 이상 — 비싸다", block)
        self.assertIn("· 10−2년 스프레드 +0.44%p → 정상", block)
        self.assertEqual(len(facts), 2)

    def test_only_one_dash_separator_per_line(self):
        # say 가 '구간 — 뜻' 꼴이라 앞도 대시면 한 줄에 대시가 두 번 나온다
        block, _ = nt.band_block(GUIDE, DATA)
        for line in block.splitlines():
            if line.startswith("·"):
                self.assertIn("→", line)

    def test_absent_quote_is_skipped(self):
        guide = {"quote_reads": {"nope": {"name": "없는것", "bands": BANDS}}}
        block, facts = nt.band_block(guide, DATA)
        self.assertEqual((block, facts), ("", []))


class TestUpcoming(unittest.TestCase):
    def setUp(self):
        self.today = dt.date(2026, 10, 12)
        # id 를 실제 지표와 다르게 둬서 consensus.json 내용에 흔들리지 않게 한다
        self.cfg = {"calendar": [
            {"id": "t_fix", "name": "확정 지표", "country": "US", "rule": {"day": 14}},
            {"id": "t_est", "name": "추정 지표", "country": "US", "rule": {"around": 16}},
        ]}

    def test_estimated_marked_and_confirmed_not(self):
        data = {"releases": {"t_fix": {"text": "전년 +3.4%", "period": "2026년 8월"}}}
        out = nt.upcoming_block(self.cfg, self.today, data)
        # rule: day 는 확정일이 아니라 규칙이므로 둘 다 추정(~)으로 나간다
        self.assertIn("~", out)
        self.assertIn("직전(2026년 8월) 전년 +3.4%", out)
        self.assertIn("( ~ 는 규칙으로 뽑은 추정일 )", out)

    def test_bare_entries_collapse_to_one_line(self):
        out = nt.upcoming_block(self.cfg, self.today, {"releases": {}})
        self.assertIn("추정 지표", out)
        self.assertIn("확정 지표", out)

    def test_empty_window(self):
        out = nt.upcoming_block({"calendar": []}, self.today, {})
        self.assertIn("예정된 발표가 없습니다", out)


class TestBuildMessage(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in
                       ("MACRO_GEMINI_API_KEY", "CONSTRUCTION_GEMINI_API_KEY",
                        "GEMINI_API_KEY")}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v

    def test_no_gemini_key_drops_only_the_one_liner(self):
        now = dt.datetime(2026, 10, 12, 21, 0, tzinfo=KST)
        msg = nt.build_message(CFG, GUIDE, DATA, now)
        self.assertNotIn("💬 한 줄", msg)
        self.assertIn("🧭 지금 구간", msg)          # 근거는 그대로 간다
        self.assertIn("📊 GS의 매크로 데스크 · 10/12(월) 21:00", msg)
        self.assertIn(nt.PAGE, msg)

    def test_header_says_numbers_are_previous_us_close(self):
        # 21:00 KST 는 미 장 시작 전이다 — 이 문장을 빼면 거짓 라벨이 된다
        now = dt.datetime(2026, 10, 12, 21, 0, tzinfo=KST)
        self.assertIn("직전 미국 장 종가", nt.build_message(CFG, GUIDE, DATA, now))

    def test_warns_when_payload_is_not_todays(self):
        now = dt.datetime(2026, 10, 12, 21, 0, tzinfo=KST)   # 데이터는 10/11
        self.assertIn("최신 수집은 2026-10-11", nt.build_message(CFG, GUIDE, DATA, now))

    def test_no_warning_when_fresh(self):
        now = dt.datetime(2026, 10, 11, 21, 0, tzinfo=KST)
        self.assertNotIn("오늘 수집 전", nt.build_message(CFG, GUIDE, DATA, now))


class TestToHtml(unittest.TestCase):
    """볼드는 제목·〈묶음〉·🗓🧭💬 머리줄만, 나머지는 escape 만(10/28 요청)."""
    SAMPLE = ("📊 GS의 매크로 데스크 · 10/28(수) 21:05\n"
              "숫자는 직전 미국 장 종가 기준입니다\n\n"
              "〈미국 금리·채권〉\n미국 10년물 4.99% (+0.01%p)\n\n"
              "🗓 앞으로 1주\n10/28(수) FOMC 금리 결정 ★확정일\n\n"
              "🧭 지금 구간\n· VIX 17.46 → 15~20 — 보통\n\n"
              "💬 한 줄\nS&P <5,000> 은 아직\n\n"
              "🔗 https://example.com/a?x=1&y=2")

    def setUp(self):
        self.lines = nt.to_html(self.SAMPLE).split("\n")

    def bold(self, starts):
        return [l for l in self.lines if l.startswith("<b>")
                and l[3:].startswith(starts)]

    def test_title_and_heads_are_bold(self):
        self.assertEqual(self.lines[0], "<b>📊 GS의 매크로 데스크 · 10/28(수) 21:05</b>")
        for h in ("〈미국 금리·채권〉", "🗓 앞으로 1주", "🧭 지금 구간", "💬 한 줄"):
            self.assertIn(f"<b>{h}</b>", self.lines)

    def test_body_lines_are_not_bold(self):
        bolded = [l for l in self.lines if l.startswith("<b>")]
        self.assertEqual(len(bolded), 5)                 # 제목 + 머리줄 4개뿐
        self.assertIn("숫자는 직전 미국 장 종가 기준입니다", self.lines)
        self.assertIn("· VIX 17.46 → 15~20 — 보통", self.lines)

    def test_escapes_angle_brackets_and_ampersand(self):
        # Gemini 한 줄·URL 의 < > & 가 태그로 읽히면 텔레그램이 400 을 준다
        self.assertIn("S&amp;P &lt;5,000&gt; 은 아직", self.lines)
        self.assertIn("🔗 https://example.com/a?x=1&amp;y=2", self.lines)

    def test_blank_lines_survive(self):
        self.assertEqual(nt.to_html(self.SAMPLE).count("\n"), self.SAMPLE.count("\n"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
