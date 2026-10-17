# -*- coding: utf-8 -*-
"""순수 계산부 검산 — 네트워크 없음. 컨테이너·러너 모두에서 돈다.
python tests/test_metrics.py"""
import os, sys, json, unittest, unittest.mock
import numpy as np, pandas as pd
from datetime import datetime, timezone, timedelta
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import metrics, kis, notify, build_report  # noqa: E402

KST = timezone(timedelta(hours=9))


def ohlc(closes, start="2025-01-01"):
    d = pd.bdate_range(start, periods=len(closes))
    c = pd.Series(closes, dtype="float64")
    return pd.DataFrame({"date": d, "o": c, "h": c * 1.01, "l": c * 0.99, "c": c, "v": 1000, "amt": 10.0})


class Slot(unittest.TestCase):
    def test_boundaries(self):
        mk = lambda h, m: datetime(2026, 10, 17, h, m, tzinfo=KST)
        self.assertEqual(metrics.decide_slot(mk(10, 5)), "10:00")
        self.assertEqual(metrics.decide_slot(mk(11, 44)), "10:00")
        self.assertEqual(metrics.decide_slot(mk(11, 45)), "13:30")
        self.assertEqual(metrics.decide_slot(mk(14, 29)), "13:30")
        self.assertEqual(metrics.decide_slot(mk(14, 30)), "15:30")
        self.assertEqual(metrics.decide_slot(mk(23, 0)), "15:30")


class Rsi(unittest.TestCase):
    def test_monotone_extremes(self):
        up = metrics.rsi(np.arange(1, 60, dtype=float))
        dn = metrics.rsi(np.arange(60, 1, -1, dtype=float))
        self.assertGreater(up.iloc[-1], 99)
        self.assertLess(dn.iloc[-1], 1)

    def test_provisional_uses_today_price(self):
        df = ohlc([100 + i * 0.3 for i in range(300)])
        today = df["date"].iloc[-1] + pd.Timedelta(days=1)
        t_conf = metrics.technicals(df, today)                       # 현재가 없음 → 확정만
        t_prov = metrics.technicals(df, today, price_now=60)         # 급락 현재가
        self.assertFalse(t_conf["provisional"])
        self.assertTrue(t_prov["provisional"])
        self.assertEqual(t_conf["rsi"], t_conf["rsi_prev"])
        self.assertLess(t_prov["rsi"], t_prov["rsi_prev"])
        self.assertEqual(t_prov["rsi_prev"], t_conf["rsi_prev"])    # 확정값은 현재가와 무관

    def test_percentile_and_extreme(self):
        # 1년 내내 완만한 상승(RSI 높음) 뒤 급락 → 오늘 RSI 는 하위권
        df = ohlc([100 + i * 0.2 for i in range(300)])
        today = df["date"].iloc[-1] + pd.Timedelta(days=1)
        t = metrics.technicals(df, today, price_now=70)
        self.assertIsNotNone(t["rsi_pctl"])
        self.assertLessEqual(t["rsi_pctl"], 5)
        self.assertIn("최저권", t["extreme"])
        self.assertIsNone(metrics.extreme_label(50))
        self.assertEqual(metrics.extreme_label(97), "1년 최고권 (상위 3%)")

    def test_short_history_no_percentile(self):
        df = ohlc([100, 101, 99, 102, 98, 103, 97, 104, 96, 105])
        t = metrics.technicals(df, df["date"].iloc[-1] + pd.Timedelta(days=1), 100)
        self.assertIsNone(t["rsi_pctl"]); self.assertIsNone(t["extreme"])

    def test_52w_and_adv(self):
        df = ohlc([100] * 300)
        t = metrics.technicals(df, df["date"].iloc[-1] + pd.Timedelta(days=1), 90)
        self.assertAlmostEqual(t["hi52_pct"], round((90 / 101 - 1) * 100, 1))
        self.assertAlmostEqual(t["lo52_pct"], round((90 / 99 - 1) * 100, 1))
        self.assertEqual(t["adv20"], 10.0)


class Flow(unittest.TestCase):
    def inv(self, f, o, start="2026-10-01"):
        d = pd.bdate_range(start, periods=len(f))
        return pd.DataFrame({"date": d, "개인": [-(a + b) for a, b in zip(f, o)], "외국인": f, "기관": o})

    def test_streak(self):
        self.assertEqual(metrics.streak([1, 2, -1, 3, 4, 5]), 3)
        self.assertEqual(metrics.streak([1, -2, -3]), -2)
        self.assertEqual(metrics.streak([1, 2, 0]), 0)
        self.assertEqual(metrics.streak([]), 0)

    def test_window_includes_today_provisional(self):
        inv = self.inv([10, 20, 30, 40, 50, 60, 7], [1, 1, 1, 1, 1, 1, 1])
        today = inv["date"].iloc[-1]
        f = metrics.flow_summary(inv, today, mcap=10000)
        self.assertTrue(f["has_today"]); self.assertEqual(f["days"], 5)
        self.assertEqual(f["frgn5"], 30 + 40 + 50 + 60 + 7)
        self.assertEqual(f["frgn_today"], 7); self.assertEqual(f["frgn_streak"], 7)
        self.assertAlmostEqual(f["fi5_mcap_pct"], round((187 + 5) / 10000 * 100, 2))

    def test_window_without_today(self):
        inv = self.inv([10, 20, 30, 40, 50, 60], [0, 0, 0, 0, 0, 0])
        today = inv["date"].iloc[-1] + pd.Timedelta(days=1)
        f = metrics.flow_summary(inv, today, mcap=None)
        self.assertFalse(f["has_today"]); self.assertNotIn("frgn_today", f)
        self.assertIsNone(f["fi5_mcap_pct"]); self.assertEqual(f["inst_streak"], 0)

    def test_rank_and_today_movers(self):
        rows = [
            {"name": "A", "flow": {"fi5_mcap_pct": 0.7, "has_today": True, "frgn_today": 108, "inst_today": 19}},
            {"name": "B", "flow": {"fi5_mcap_pct": -1.2, "has_today": True, "frgn_today": -66, "inst_today": -31}},
            {"name": "C", "flow": {"fi5_mcap_pct": 0.1, "has_today": False}},
            {"name": "D", "flow": {"fi5_mcap_pct": None}},
            {"name": "E", "flow": {"fi5_mcap_pct": -0.2, "has_today": True, "frgn_today": -130, "inst_today": -165}},
        ]
        buy, sell = metrics.rank_flow(rows)
        self.assertEqual([r["name"] for r in buy], ["A", "C"])
        self.assertEqual([r["name"] for r in sell], ["B", "E"])
        tm = metrics.today_movers(rows)
        self.assertEqual([(n, w) for n, w, v in tm], [("E", "기관"), ("E", "외인"), ("A", "외인")])


class Passive(unittest.TestCase):
    def etfs(self):
        return [{"code": "1", "name": "SOL 조선", "listed": 1_100_000, "price": 10_000,
                 "holdings": [{"code": "S1", "weight": 20.0}, {"code": "S2", "weight": 10.0}]},
                {"code": "2", "name": "PLUS 방산", "listed": 500_000, "price": 20_000,
                 "holdings": [{"code": "S1", "weight": 5.0}]}]

    def test_first_run_skips(self):
        per_stock, per_etf = metrics.passive_flow(self.etfs(), {})
        self.assertEqual(per_stock, {})
        self.assertTrue(all(e["delta_shares"] is None for e in per_etf))
        self.assertEqual(per_etf[0]["listed"], 1_100_000)     # 첫 수집도 상장주수는 표에 보여야 한다

    def test_parse_eok(self):
        self.assertEqual(metrics.parse_eok("1조 1,560억"), 11560.0)
        self.assertEqual(metrics.parse_eok("-99.2억"), -99.2)
        self.assertEqual(metrics.parse_eok("-1,536억"), -1536.0)
        self.assertEqual(metrics.parse_eok("1조 247억"), 10247.0)
        self.assertEqual(metrics.parse_eok("2조"), 20000.0)
        self.assertIsNone(metrics.parse_eok("")); self.assertIsNone(metrics.parse_eok(None)); self.assertIsNone(metrics.parse_eok("n/a"))

    def test_delta_times_weight(self):
        per_stock, per_etf = metrics.passive_flow(self.etfs(), {"1": 1_000_000, "2": 520_000})
        # ETF1 +100,000주 × 1만원 = 10억 → S1 2.0억, S2 1.0억 / ETF2 −20,000주 × 2만원 = −4억 → S1 −0.2억
        self.assertAlmostEqual(per_stock["S1"]["amt"], 1.8)
        self.assertAlmostEqual(per_stock["S2"]["amt"], 1.0)
        self.assertEqual(per_etf[0]["amt"], 10.0); self.assertEqual(per_etf[1]["amt"], -4.0)
        self.assertEqual(per_stock["S1"]["etfs"][0][0], "SOL 조선")

    def test_adv_pct_and_label(self):
        self.assertEqual(metrics.adv_pct(1.8, 10.0), 18.0)
        self.assertIsNone(metrics.adv_pct(1.8, None))
        self.assertEqual(metrics.passive_label(35.0), "패시브 순매수 큼")
        self.assertEqual(metrics.passive_label(-7.0), "패시브 순매도")
        self.assertEqual(metrics.passive_label(0.5), "패시브 순매수 미미")

    def test_update_shares_uses_previous_date_not_today(self):
        import collect
        store = {"1": {"2026-10-15": 900_000, "2026-10-16": 1_000_000}}
        etfs = [{"code": "1", "listed": 1_050_000}, {"code": "2", "listed": 10}]
        new, prev = collect.update_shares(etfs, "2026-10-16", store)   # 같은 날 두 번째 슬롯
        self.assertEqual(prev, {"1": 900_000})                           # 전일 값
        self.assertEqual(new["1"]["2026-10-16"], 1_050_000)              # 오늘 값은 최신으로 덮음
        self.assertEqual(new["2"], {"2026-10-16": 10})


class Active(unittest.TestCase):
    def test_filter_universe(self):
        ch = {"date": "2026-10-16", "etfs": [{"label": "TIME 코스피액티브",
               "new": [{"code": "042660", "name": "한화오션", "weight": 3.1}, {"code": "005930", "name": "삼성전자"}],
               "gone": [{"code": "012450", "name": "한화에어로스페이스", "weight_prev": 2.0}],
               "moves": [{"code": "329180", "name": "HD현대중공업", "active_share_pct": -26.8, "weight_now": 4.0},
                         {"code": "000660", "name": "SK하이닉스", "active_share_pct": 50}]}]}
        hits = metrics.active_etf_hits(ch, {"042660", "012450", "329180"})
        self.assertEqual([(h["stock"], h["kind"]) for h in hits],
                         [("한화오션", "편입"), ("한화에어로스페이스", "제외"), ("HD현대중공업", "감소")])
        self.assertEqual(metrics.active_etf_hits({}, {"x"}), [])


class Frames(unittest.TestCase):
    def test_kis_frames(self):
        rows = [{"stck_bsop_date": "20261016", "stck_oprc": "100", "stck_hgpr": "110", "stck_lwpr": "90", "stck_clpr": "105", "acml_vol": "1000", "acml_tr_pbmn": "200000000"},
                {"stck_bsop_date": "20261015", "stck_oprc": "99", "stck_hgpr": "101", "stck_lwpr": "95", "stck_clpr": "100", "acml_vol": "500", "acml_tr_pbmn": "100000000"}]
        df = kis.ohlc_frame(rows)
        self.assertEqual(list(df["c"]), [100.0, 105.0]); self.assertEqual(list(df["amt"]), [1.0, 2.0])
        df2 = kis.ohlc_frame([{k: v for k, v in r.items() if k != "acml_tr_pbmn"} for r in rows])
        self.assertAlmostEqual(df2["amt"].iloc[0], 100 * 500 / 1e8)   # 거래대금 없으면 종가×거래량
        inv = kis.investor_frame([{"stck_bsop_date": "20261016", "prsn_ntby_tr_pbmn": "-1000", "frgn_ntby_tr_pbmn": "10800", "orgn_ntby_tr_pbmn": "1900"}])
        self.assertEqual(inv["외국인"].iloc[0], 108.0)
        px = kis.price_row({"stck_prpr": "12,345", "prdy_ctrt": "-1.20", "hts_avls": "98765", "lstn_stcn": "1000", "hts_frgn_ehrt": "12.34", "acml_tr_pbmn": "300000000"})
        self.assertEqual(px["price"], 12345.0); self.assertEqual(px["amt_today"], 3.0)
        self.assertTrue(kis.ohlc_frame([]).empty); self.assertTrue(kis.investor_frame([]).empty)


def fake_payload():
    return {"asof": "2026-10-16 13:31", "date": "2026-10-16", "slot": "13:30", "universe": 3, "active_date": "2026-10-16",
            "rows": [
                {"code": "042660", "name": "한화오션", "industry": "조선", "status": "커버리지",
                 "px": {"chg_pct": 0.4, "frgn_pct": 20.1, "mcap": 250000},
                 "flow": {"fi5_mcap_pct": 0.7, "frgn5": 108, "inst5": 19, "indiv5": -120, "frgn_streak": 13, "inst_streak": 1, "has_today": True, "frgn_today": 50, "inst_today": 3},
                 "tech": {"rsi": 69.0, "rsi_prev": 66.0, "rsi_pctl": 96.5, "extreme": "1년 최고권 (상위 4%)", "hi52_pct": -1.0, "lo52_pct": 80.0, "adv20": 500, "provisional": True},
                 "passive": {"amt": 12.0, "adv_pct": 2.4, "etfs": [("SOL 조선TOP3플러스", 12.0)]}},
                {"code": "012450", "name": "한화에어로스페이스", "industry": "방산", "status": "커버리지",
                 "px": {"chg_pct": -1.2, "frgn_pct": 30.0, "mcap": 400000},
                 "flow": {"fi5_mcap_pct": -1.2, "frgn5": -66, "inst5": -31, "indiv5": 90, "frgn_streak": -2, "inst_streak": -5, "has_today": True, "frgn_today": -130, "inst_today": -165},
                 "tech": {"rsi": 20.0, "rsi_prev": 24.0, "rsi_pctl": 0.8, "extreme": "1년 최저권 (하위 1%)", "hi52_pct": -30.0, "lo52_pct": 2.0, "adv20": 800, "provisional": True},
                 "passive": {"amt": -300.0, "adv_pct": -37.5, "etfs": [("PLUS K방산", -200.0), ("TIGER K방산&우주", -100.0)]}},
                {"code": "000490", "name": "대동", "industry": "건설기계", "status": "커버예정",
                 "px": {"chg_pct": None, "frgn_pct": None, "mcap": None}, "flow": {}, "tech": {}, "passive": None},
            ],
            "etfs": [{"code": "466920", "name": "SOL 조선TOP3플러스", "delta_shares": 10000, "amt": 1.0, "listed": 1}, {"code": "449450", "name": "PLUS K방산", "delta_shares": None, "amt": None}],
            "active": [{"etf": "TIME 코스피액티브", "stock_code": "042660", "stock": "한화오션", "kind": "증가", "pct": 20.0, "weight": 3.1}],
            "errors": ["000490 대동: RuntimeError: 예시"]}


class Outputs(unittest.TestCase):
    def test_compose(self):
        txt = notify.compose(fake_payload())
        self.assertIn("사는 쪽", txt); self.assertIn("한화오션 +0.7%", txt); self.assertIn("외인 13일째 순매수", txt)
        self.assertIn("한화에어로스페이스 -1.2%", txt); self.assertIn("기관 5일째 순매도", txt)
        self.assertIn("오늘(잠정): 한화에어로스페이스 기관 -165", txt)
        self.assertIn("패시브 순매도 큼 · ADV -37.5%", txt)
        self.assertIn("TIME 코스피액티브 → 한화오션 증가 +20%", txt)
        self.assertIn("한화에어로스페이스 RSI 20 · 1년 최저권 (하위 1%)", txt)
        self.assertIn("한화오션 RSI 69 · 1년 최고권", txt)
        self.assertIn("검증 전", txt); self.assertLess(len(txt), 4000)

    def test_pctl_zero_is_lowest_not_missing(self):
        d = fake_payload()
        d["rows"][1]["tech"].update(rsi_pctl=0.0, extreme="1년 최저권 (하위 0%)")
        d["rows"][0]["tech"].update(rsi_pctl=3.0, extreme="1년 최저권 (하위 3%)")
        txt = notify.compose(d)
        i0, i1 = txt.index("한화에어로스페이스 RSI"), txt.index("한화오션 RSI")
        self.assertLess(i0, i1)                       # 0% 가 3% 보다 먼저
        self.assertEqual(metrics.pctl_or(0.0, 50), 0.0); self.assertEqual(metrics.pctl_or(None, 50), 50)
        h = build_report.render(d)
        self.assertIn("RSI 1년 최저권", h)
        self.assertIn("mini b'>1년 최저권 (하위 0%)", h)

    def test_not_live_keeps_confirmed_only(self):
        df = ohlc([100 + i * 0.3 for i in range(300)])
        today = df["date"].iloc[-1] + pd.Timedelta(days=2)      # 토요일 격
        t = metrics.technicals(df, today, None)
        self.assertFalse(t["provisional"]); self.assertEqual(t["rsi"], t["rsi_prev"])

    def test_creds_never_fall_back_to_public_channel(self):
        env = {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "@public"}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(notify._creds(), ("t", ""))                       # 공개채널은 무시
        env["TELEGRAM_CHAT_ID_PRIVATE"] = "-100123"
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(notify._creds(), ("t", "-100123"))
        env["COVFLOW_TELEGRAM_CHAT_ID"] = "-100999"; env["COVFLOW_TELEGRAM_BOT_TOKEN"] = "t2"
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(notify._creds(), ("t2", "-100999"))

    def test_compose_empty(self):
        txt = notify.compose({"asof": "2026-10-16 10:01", "rows": [], "etfs": [], "active": []})
        self.assertIn("순매수 종목 없음", txt); self.assertIn("첫 수집", txt); self.assertIn("극단권 종목 없음", txt)

    def test_render(self):
        h = build_report.render(fake_payload())
        for s in ("한화오션", "13일째 매수", "1년 최저권", "SOL 조선TOP3플러스", "수집 오류 1건", "커버예정", "직전 값 없음", "TIME 코스피액티브"):
            self.assertIn(s, h)
        self.assertNotIn("chr(", h)


if __name__ == "__main__":
    unittest.main(verbosity=1)
