# -*- coding: utf-8 -*-
"""ETF 그룹 등락률 기간 버튼(DoD·WoW·MoM·QoQ·YoY) 산식·렌더 검산 — 가짜 history 로."""
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scrape  # noqa: E402
import build_report as br  # noqa: E402

D = dt.date


def _write(dirp, asof, rows):
    Path(dirp, f"{asof}.json").write_text(json.dumps(
        {"signals": [dict(code=c, close=px, asof=asof, ret_1y=r1y) for c, px, r1y in rows]}),
        encoding="utf-8")


class TestPeriods(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        _write(t, "2026-08-14", [("A", 80, None), ("B", 200, None)])   # 11/14−90 = 8/16 이전 마지막
        _write(t, "2026-08-17", [("A", 999, None)])                     # 기준일 뒤 — 쓰면 안 됨
        _write(t, "2026-10-14", [("A", 90, None)])                      # 11/14−30
        _write(t, "2026-11-06", [("A", 95, None)])                      # 11/14−7=11/7(토) → 11/6
        _write(t, "2026-11-13", [("A", 100, 25.0), ("B", 210, None)])   # 최신, A 1년 +25%
        self.closes, self.latest = scrape.load_close_history(t)

    def tearDown(self):
        self.tmp.cleanup()

    def test_base_close_is_last_on_or_before(self):
        self.assertEqual(scrape.base_close(self.closes["A"], D(2026, 11, 7)), 95)
        self.assertEqual(scrape.base_close(self.closes["A"], D(2026, 8, 16)), 80)
        self.assertIsNone(scrape.base_close(self.closes["A"], D(2026, 1, 1)))   # 모름은 None
        self.assertIsNone(scrape.base_close(self.closes["B"], D(2026, 11, 7)))  # 85일 묵은 종가

    def test_period_returns(self):
        live = [("조선", "A", 110.0, 10.0), ("조선", "B", 220.0, 4.76)]
        res, bases = scrape.period_returns(live, self.closes, self.latest, D(2026, 11, 14))
        g = {k: dict((r[0], (r[1], r[2])) for r in v) for k, v in res.items()}
        self.assertEqual(g["1d"]["조선"], (round((10.0 + 4.76) / 2, 2), 2))
        self.assertEqual(g["1w"]["조선"], (round((110 / 95 - 1) * 100, 2), 1))   # B 의 8/14 는 11/7 보다 너무 옛것
        self.assertEqual(g["1m"]["조선"], (round((110 / 90 - 1) * 100, 2), 1))
        self.assertEqual(g["3m"]["조선"], (round(((110 / 80 - 1) + (220 / 200 - 1)) * 50, 2), 2))
        self.assertEqual(g["1y"]["조선"], (round((110 / 80 - 1) * 100, 2), 1))   # 100/1.25=80
        self.assertEqual(bases["1w"], "2026-11-07")
        self.assertEqual(bases["1y"], "2025-11-13")

    def test_no_price_keeps_dod_only(self):
        res, _ = scrape.period_returns([("방산", "A", None, -1.0)], self.closes, self.latest,
                                       D(2026, 11, 14))
        self.assertEqual(list(res), ["1d"])


class TestRender(unittest.TestCase):
    def test_old_payload_no_buttons(self):
        h = br.group_ret_block({"group_1d": {"time": "11:00", "groups": [["조선", 1.2, 3]]}}, True)
        self.assertIn("gbars", h)
        self.assertNotIn("gper", h)

    def test_buttons_and_hidden_lists(self):
        gr = {"time": "16:00", "groups": [["조선", 1.0, 2]],
              "periods": {"1d": [["조선", 1.0, 2]], "1w": [["조선", -3.0, 2]],
                          "1y": [["조선", 40.0, 1]]},
              "bases": {"1w": "2026-11-07", "1y": "2025-11-13"}}
        h = br.group_ret_block({"group_1d": gr}, True)
        for lab in ("오늘의 수익률", "주간 수익률", "연간 수익률"):
            self.assertIn(f">{lab}</button>", h)
        self.assertNotIn(">월간 수익률<", h)               # 데이터 없는 기간은 버튼도 없음
        self.assertNotIn("<script", h)                     # innerHTML 로 들어가 인라인 script 는 안 돈다
        self.assertIn('data-p="1d">', h)
        self.assertIn('data-p="1w" hidden', h)
        self.assertIn("26/11/07 이전 마지막 종가", h)


class TestHistoryBackfill(unittest.TestCase):
    """기간 버튼 이전에 수집된 날 — 그날 종가로 보충."""
    def test_periods_from_history(self):
        with tempfile.TemporaryDirectory() as t:
            _write(t, "2026-11-06", [("A", 95, None)])
            _write(t, "2026-11-13", [("A", 100, 25.0)])
            uni = Path(t, "u.csv")
            uni.write_text("group,name,code,active,note\n조선,X,A,1,\n방산,Y,Z,1,\n", encoding="utf-8")
            per, bases = scrape.periods_from_history("2026-11-13", t, uni)
            self.assertNotIn("1d", per)                       # DoD 는 수집값 그대로
            self.assertEqual(per["1w"], [["조선", round((100 / 95 - 1) * 100, 2), 1]])
            self.assertEqual(per["1y"], [["조선", 25.0, 1]])
            self.assertEqual(bases["1y"], "2025-11-13")
            self.assertIsNone(scrape.periods_from_history("2026-11-12", t, uni))   # 그날 파일 없음


if __name__ == "__main__":
    unittest.main()
