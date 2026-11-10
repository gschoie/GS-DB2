# -*- coding: utf-8 -*-
"""날짜 규칙 검산 — 거래일 셈·T+2 마감·둘째 목요일·4년 주기. 네트워크 없음."""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_calendar as b  # noqa: E402


class TestTradingDays(unittest.TestCase):
    def setUp(self):
        rules, dates, fomc = b.load()
        self.rules, self.dates, self.fomc = rules, dates, fomc
        hol = {b._d(x) for ys in dates["krx_holidays"].values() for x in ys}
        self.td = b.TradingDays(hol)
        self.data = b.build_events(rules, dates, fomc, [2026, 2027, 2028])

    def win(self, id_, year):
        return [w for w in self.data["windows"] if w["id"] == id_ and w["start"].startswith(str(year))]

    def pins(self, id_, year):
        return [p for p in self.data["pins"] if p["id"] == id_ and p["date"].startswith(str(year))]

    def test_yearend_closed(self):
        """12/31 은 KRX 연말 휴장 — 2026 마지막 거래일은 12/30."""
        self.assertEqual(self.td.prev(dt.date(2026, 12, 31)), dt.date(2026, 12, 30))

    def test_bigholder_deadline_t2(self):
        """대주주 회피 매도 마감 = 마지막 거래일 2거래일 전 (2026: 12/28 월, 2027: 12/28 화)."""
        self.assertEqual(self.pins("kr_bigholder_deadline", 2026)[0]["date"], "2026-12-28")
        self.assertEqual(self.pins("kr_bigholder_deadline", 2027)[0]["date"], "2027-12-28")

    def test_exdiv(self):
        """배당락일 = 마지막 거래일 전 거래일 (2026: 12/29)."""
        self.assertEqual(self.pins("kr_exdiv", 2026)[0]["date"], "2026-12-29")

    def test_santa_window(self):
        """12월 마지막 5거래일 + 1월 첫 2거래일. 2026: 12/23~2027-01-05 (12/25·12/31·1/1 휴장)."""
        w = self.win("us_santa", 2026)[0]
        self.assertEqual((w["start"], w["end"]), ("2026-12-23", "2027-01-05"))

    def test_chuseok_windows(self):
        """추석 2026(9/24~26): 전 5거래일 9/17~9/23, 후 5거래일 9/28~10/2."""
        ws = {w["label"]: w for w in self.win("kr_chuseok", 2026)}
        self.assertEqual((ws["추석 전 5거래일"]["start"], ws["추석 전 5거래일"]["end"]), ("2026-09-17", "2026-09-23"))
        self.assertEqual((ws["추석 후 5거래일"]["start"], ws["추석 후 5거래일"]["end"]), ("2026-09-28", "2026-10-02"))
        self.assertEqual(ws["추석 전 5거래일"]["tone"], "weak")
        self.assertEqual(ws["추석 후 5거래일"]["tone"], "strong")

    def test_quad_witching(self):
        """네 마녀의 날 = 3·6·9·12월 둘째 목요일. 2026: 3/12·6/11·9/10·12/10."""
        self.assertEqual([p["date"] for p in self.pins("kr_quad", 2026)],
                         ["2026-03-12", "2026-06-11", "2026-09-10", "2026-12-10"])

    def test_k200_effective_next_td(self):
        """코스피200 정기변경 효력 = 동시만기 다음 거래일 (2026-12: 12/11)."""
        self.assertIn("2026-12-11", [p["date"] for p in self.pins("k200_rebal", 2026)])

    def test_us_triple_witching(self):
        self.assertEqual([p["date"] for p in self.pins("us_triple", 2026)],
                         ["2026-03-20", "2026-06-19", "2026-09-18", "2026-12-18"])

    def test_phase(self):
        """(year-2024)%4 — 2026 중간선거·2027 대선 전·2028 대선·2029 1년차."""
        self.assertEqual([b.phase_of(y) for y in (2026, 2027, 2028, 2029)],
                         ["midterm", "pre", "election", "post"])

    def test_cycle_only_in_its_year(self):
        """중간선거해 규칙은 2026 에만, 3년차 규칙은 2027 에만 켜진다."""
        m26 = {(x["id"], x["month"]) for x in self.data["months"] if x["year"] == 2026 and x["cycle"]}
        m27 = {(x["id"], x["month"]) for x in self.data["months"] if x["year"] == 2027 and x["cycle"]}
        self.assertIn(("cycle_midterm_weak", 9), m26)
        self.assertIn(("cycle_midterm_strong", 11), m26)
        self.assertNotIn(("cycle_midterm_weak", 9), m27)
        self.assertIn(("cycle_pre_strong", 1), m27)

    def test_election_windows(self):
        """총선 2028-04-12: 전 20거래일·후 20거래일 창 + 선거일 핀."""
        ws = self.win("election_kr_big", 2028)
        self.assertEqual(len(ws), 2)
        pre = next(w for w in ws if "전" in w["label"])
        self.assertEqual(pre["end"], "2028-04-11")
        self.assertEqual(pre["tone"], "strong")
        self.assertIn("2028-04-12", [p["date"] for p in self.pins("election_kr_big", 2028)])

    def test_tentative_propagates(self):
        """2028 명절은 미확인 → 창에 ~ 가 붙는다."""
        self.assertTrue(all(w["tentative"] for w in self.win("kr_chuseok", 2028)))
        self.assertFalse(any(w["tentative"] for w in self.win("kr_chuseok", 2026)))

    def test_fomc_from_macro_desk(self):
        """FOMC 는 macro_desk/fixed_dates.json 을 그대로 읽는다 — 두 곳에 적지 않는다."""
        if self.fomc:
            self.assertIn(self.fomc[0], [p["date"] for p in self.data["pins"] if p["label"] == "FOMC"])

    def test_render_has_payload(self):
        html = b.render(self.data)
        self.assertIn('id="data"', html)
        self.assertNotIn("__PAYLOAD__", html)


if __name__ == "__main__":
    unittest.main()
