import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools  # noqa: E402

TONE_FIXTURE = {
    "companies": {
        "003230": {
            "name": "삼양식품",
            "timeline": [
                {"date": "2026-07-01", "opinion": "BUY", "title": "삼양식품 실적 프리뷰",
                 "tp_event": {"direction": "up", "value": 1500000, "prior": 1300000}},
                {"date": "2026-08-01", "opinion": "BUY", "title": "삼양식품 서프라이즈",
                 "one_line": "면 수출 호조 지속으로 판단"},
            ],
        },
        "376300": [
            {"date": "2026-07-15", "opinion": "HOLD", "title": "디어유 업데이트"},
        ],
        "IND:조선": {
            "timeline": [
                {"date": "2026-07-20", "opinion": "비중확대", "title": "조선 위클리"},
            ],
        },
    },
    "sectors": [
        {"sector": "조선", "analyst": "최광식", "recent_tone": "긍정", "baseline": "중립"},
        {"sector": "음식료", "analyst": "홍길동", "recent_tone": "중립", "baseline": "중립"},
    ],
    "street": {"003230": {"range": [1200000, 1600000], "daol_position_pct": 80}},
}

KED_FIXTURE = [
    {"company": "에코프로", "brokerage": "A증권", "tp_new": 100000, "opinion": "BUY"},
    {"company": "에코프로비엠", "brokerage": "B증권", "tp_new": 200000, "opinion": "HOLD"},
]


class ResolveCompanyTest(unittest.TestCase):
    def test_resolves_by_exact_code(self):
        code, _ = tools.resolve_company("003230", TONE_FIXTURE)
        self.assertEqual(code, "003230")

    def test_resolves_by_name(self):
        code, _ = tools.resolve_company("삼양식품", TONE_FIXTURE)
        self.assertEqual(code, "003230")

    def test_resolves_bare_list_entry_by_title(self):
        code, _ = tools.resolve_company("디어유", TONE_FIXTURE)
        self.assertEqual(code, "376300")

    def test_skips_industry_keys(self):
        self.assertIsNone(tools.resolve_company("없는종목", TONE_FIXTURE))


class CompanyViewTest(unittest.TestCase):
    def test_includes_timeline_and_street(self):
        view = tools.company_view("삼양식품", TONE_FIXTURE)
        self.assertEqual(view["code"], "003230")
        self.assertEqual(len(view["timeline_recent"]), 2)
        self.assertEqual(view["street_position"]["daol_position_pct"], 80)

    def test_unknown_company_suggests_street_search(self):
        view = tools.company_view("없는종목", TONE_FIXTURE)
        self.assertIn("search_street", view["error"])

    def test_timeline_is_capped(self):
        tone = {"companies": {"111111": {"name": "많은종목",
                                         "timeline": [{"i": i} for i in range(50)]}}}
        view = tools.company_view("많은종목", tone)
        self.assertEqual(len(view["timeline_recent"]), tools.MAX_TIMELINE_ITEMS)
        self.assertEqual(view["timeline_recent"][-1], {"i": 49})


class SectorToneTest(unittest.TestCase):
    def test_finds_sector_row_and_industry_timeline(self):
        result = tools.sector_tone("조선", TONE_FIXTURE)
        self.assertEqual(len(result["sector_rows"]), 1)
        self.assertEqual(result["industry_key"], "IND:조선")
        self.assertEqual(len(result["industry_timeline_recent"]), 1)

    def test_unknown_sector_lists_available(self):
        result = tools.sector_tone("반도체", TONE_FIXTURE)
        self.assertIn("error", result)
        self.assertIn("IND:조선", result["available_industries"])


class StreetSearchTest(unittest.TestCase):
    def test_matches_by_name(self):
        result = tools.street_search("에코프로비엠", KED_FIXTURE)
        self.assertEqual(result["total_matches"], 1)
        self.assertEqual(result["matches"][0]["brokerage"], "B증권")

    def test_substring_matches_multiple(self):
        result = tools.street_search("에코프로", KED_FIXTURE)
        self.assertEqual(result["total_matches"], 2)

    def test_dict_shaped_ked(self):
        result = tools.street_search("에코프로비엠", {"rows": KED_FIXTURE})
        self.assertEqual(result["total_matches"], 1)

    def test_no_match(self):
        self.assertIn("error", tools.street_search("없는종목", KED_FIXTURE))


class SerializeTest(unittest.TestCase):
    def test_truncates_long_results(self):
        text = tools.serialize({"big": "x" * (tools.MAX_RESULT_CHARS * 2)})
        self.assertLessEqual(len(text), tools.MAX_RESULT_CHARS + 100)
        self.assertIn("잘렸습니다", text)

    def test_valid_json_when_short(self):
        payload = {"한글": "값"}
        self.assertEqual(json.loads(tools.serialize(payload)), payload)


if __name__ == "__main__":
    unittest.main()
