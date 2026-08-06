import json
import os
import tempfile
import unittest
from pathlib import Path

from tone_market import (_build_indexes, _match, _norm_link, _street_snapshot,
                         _tone_fields, attach_tone_market)


def tone_fixture():
    return {
        "generated_at": "2026-08-01T00:00:00+00:00",
        "companies": {
            "329180": {
                "key": "329180", "name": "HD현대중공업", "code": "329180",
                "timeline": [
                    {"id": "1", "date": "2026-07-29", "company": "HD현대중공업",
                     "source_url": "https://bit.ly/HHI2Q26RE", "post_url": "https://t.me/daolresearch/1",
                     "one_line": "수익성 개선을 증명한 분기.",
                     "points": ["수익성 개선", "가스선 수주"],
                     "earnings_direction": "상향", "earnings_evidence": "OPM 18.8%",
                     "tp_event": {"direction": "유지", "reasons": ["실적추정"]},
                     "est_compare": {"annual": {"label": "2026E", "op": {"our": 41539.0, "cons": 40000.0, "diff_pct": 3.8}}}},
                    {"id": "2", "date": "2026-06-01", "company": "HD현대중공업", "bundled": True,
                     "source_url": "https://bit.ly/SKIPME"},
                ],
                "street": {"stats": {"daol": 1040000.0}, "items": [
                    {"date": "2026-07-30", "id": 10, "brokerage": "신한투자증권", "tp_new": 650000.0},
                    {"date": "2026-07-01", "id": 5, "brokerage": "신한투자증권", "tp_new": 830000.0},
                    {"date": "2026-07-29", "id": 9, "brokerage": "KB증권", "tp_new": 700000.0},
                    {"date": "2026-07-20", "id": 8, "brokerage": "미래에셋", "tp_new": 900000.0},
                ]},
            },
            "IND:조선": {"key": "IND:조선", "name": "조선 산업", "timeline": [
                {"id": "3", "date": "2026-07-05", "company": "",
                 "source_url": "http://bit.ly/DOS829", "one_line": "가스선 강세 위클리."},
            ]},
        },
    }


class NormLinkTest(unittest.TestCase):
    def test_scheme_and_host_normalized_path_case_kept(self):
        self.assertEqual(_norm_link("http://bit.ly/DOS829"), "bit.ly/DOS829")
        self.assertEqual(_norm_link("https://www.BIT.ly/DOS829/"), "bit.ly/DOS829")
        self.assertIsNone(_norm_link(None))


class MatchTest(unittest.TestCase):
    def setUp(self):
        self.by_link, self.by_co_date = _build_indexes(tone_fixture())

    def test_bundled_records_are_skipped(self):
        self.assertNotIn("bit.ly/SKIPME", self.by_link)

    def test_match_by_short_link_covers_industry_reports(self):
        report = {"original_url": "http://bit.ly/DOS829", "posted_at": "2026-07-05T10:13:42+00:00",
                  "company_names": []}
        self.assertEqual(_match(report, self.by_link, self.by_co_date)["one_line"], "가스선 강세 위클리.")

    def test_match_by_company_and_date_with_one_day_slack(self):
        report = {"original_url": None, "posted_at": "2026-07-29T22:30:00+00:00",  # KST 7/30
                  "company_names": ["HD현대중공업"]}
        self.assertEqual(_match(report, self.by_link, self.by_co_date)["id"], "1")


class FieldsTest(unittest.TestCase):
    def test_tone_fields_keeps_only_present_values(self):
        record = tone_fixture()["companies"]["329180"]["timeline"][0]
        fields = _tone_fields(record)
        self.assertEqual(fields["earn"], "상향")
        self.assertEqual(fields["tp_reasons"], ["실적추정"])
        self.assertEqual(fields["est"]["op"]["our"], 41539.0)
        self.assertEqual(fields["co"], "HD현대중공업")  # 다중 태그일 때 컨센을 붙일 대표 종목
        self.assertNotIn("tone_label", fields)  # 빈 값은 임베드하지 않는다

    def test_tone_fields_drops_blank_company(self):
        record = tone_fixture()["companies"]["IND:조선"]["timeline"][0]
        self.assertNotIn("co", _tone_fields(record))  # 산업 레코드는 대표 종목이 없다

    def test_street_snapshot_dedupes_by_brokerage(self):
        snap = _street_snapshot(tone_fixture()["companies"]["329180"])
        self.assertEqual(snap["n"], 3)  # 신한 2건은 최신 1건만
        self.assertEqual(snap["min"], 650000.0)
        self.assertEqual(snap["max"], 900000.0)
        self.assertEqual(snap["median"], 700000.0)
        self.assertEqual(snap["daol_pct"], 100)


class AttachTest(unittest.TestCase):
    def test_attach_via_env_source_and_market_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "tone.json"
            src.write_text(json.dumps(tone_fixture()), encoding="utf-8")
            os.environ["TONE_V2_SRC"] = str(src)
            try:
                reports = [{"message_id": 1, "original_url": "http://bit.ly/DOS829",
                            "posted_at": "2026-07-05T10:13:42+00:00", "company_names": []}]
                market = attach_tone_market(reports, lambda: {})
            finally:
                del os.environ["TONE_V2_SRC"]
        self.assertEqual(reports[0]["tone"]["one_line"], "가스선 강세 위클리.")
        entry = market["HD현대중공업"]
        self.assertEqual(entry["street"]["n"], 3)
        self.assertEqual(entry["mine"]["op"], 41539.0)
        self.assertEqual(entry["code"], "329180")


if __name__ == "__main__":
    unittest.main()
