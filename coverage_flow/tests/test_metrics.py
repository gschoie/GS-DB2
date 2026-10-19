# -*- coding: utf-8 -*-
"""순수 계산부 검산 — 네트워크 없음. 컨테이너·러너 모두에서 돈다.
python tests/test_metrics.py"""
import os, sys, json, tempfile, unittest, unittest.mock
import numpy as np, pandas as pd
from datetime import datetime, timezone, timedelta
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import metrics, kis, notify, build_report, collect  # noqa: E402

KST = timezone(timedelta(hours=9))


def ohlc(closes, start="2025-01-01"):
    d = pd.bdate_range(start, periods=len(closes))
    c = pd.Series(closes, dtype="float64")
    return pd.DataFrame({"date": d, "o": c, "h": c * 1.01, "l": c * 0.99, "c": c, "v": 1000, "amt": 10.0})


class Slot(unittest.TestCase):
    def test_single_daily_slot(self):
        # 10/19부터 하루 1회(16:00) — 수동 수집도 같은 슬롯에 붙는다.
        mk = lambda h, m: datetime(2026, 10, 17, h, m, tzinfo=KST)
        self.assertEqual(metrics.decide_slot(mk(10, 5)), "16:00")
        self.assertEqual(metrics.decide_slot(mk(16, 5)), "16:00")
        self.assertEqual(metrics.decide_slot(mk(23, 0)), "16:00")


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


class Returns(unittest.TestCase):
    def test_windows_and_ytd(self):
        # 2025-12-01 부터 영업일 100개: 전년 마지막 종가 → ytd 기준
        d = pd.bdate_range("2025-12-01", periods=100)
        c = pd.Series(np.arange(100, 200, dtype="float64"))
        df = pd.DataFrame({"date": d, "o": c, "h": c, "l": c, "c": c, "v": 1, "amt": 1.0})
        today = d[-1] + pd.Timedelta(days=1)
        r = metrics.returns(df, today, price_now=210.0, chg_pct=5.53)
        self.assertEqual(r["d1"], 5.53)                                   # KIS 전일대비 그대로
        self.assertAlmostEqual(r["w1"], round((210 / c.iloc[-5] - 1) * 100, 2))
        self.assertAlmostEqual(r["m1"], round((210 / c.iloc[-21] - 1) * 100, 2))
        self.assertAlmostEqual(r["m3"], round((210 / c.iloc[-63] - 1) * 100, 2))
        prev_year_last = c[[x.year == 2025 for x in d]].iloc[-1]
        self.assertAlmostEqual(r["ytd"], round((210 / prev_year_last - 1) * 100, 2))

    def test_spark_points(self):
        df = ohlc([100 + i for i in range(100)])
        today = df["date"].iloc[-1] + pd.Timedelta(days=1)
        sp = metrics.spark_points(df, today, price_now=250)
        self.assertEqual(len(sp), 63); self.assertEqual(sp[-1], 250.0); self.assertEqual(sp[0], 100 + 99 - 61)
        self.assertEqual(metrics.spark_points(pd.DataFrame(), today), [])
        svg = build_report.spark_svg(sp); self.assertIn("<svg", svg); self.assertIn("rgb(220,38,38)", svg)   # 오르면 빨강(한국식)
        self.assertIn("rgb(37,99,235)", build_report.spark_svg([10, 9, 8]))   # 내리면 파랑; self.assertIn("na", build_report.spark_svg([5]))

    def test_short_history_none(self):
        df = ohlc([100, 101, 102, 103], start="2026-10-05")
        r = metrics.returns(df, df["date"].iloc[-1] + pd.Timedelta(days=1), None, None)
        self.assertIsNone(r["m1"]); self.assertIsNone(r["m3"]); self.assertIsNone(r["ytd"]); self.assertIsNone(r["w1"])
        self.assertAlmostEqual(r["d1"], round((103 / 102 - 1) * 100, 2))  # chg_pct 없으면 종가로


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

    def test_flow_windows(self):
        d = pd.bdate_range("2025-12-15", periods=80)          # 전년 행 포함 → ytd 유효
        inv = pd.DataFrame({"date": d, "개인": 0.0, "외국인": np.ones(80), "기관": -np.ones(80)})
        today = d[-1]
        w = metrics.flow_windows(inv, today)
        self.assertEqual(w["rows"], 80)
        self.assertEqual(w["frgn"]["today"], 1.0); self.assertEqual(w["frgn"]["d5"], 5.0)
        self.assertEqual(w["frgn"]["m1"], 21.0); self.assertEqual(w["frgn"]["m3"], 63.0)
        self.assertEqual(w["frgn"]["ytd"], float(sum(1 for x in d if x.year == 2026)))
        self.assertEqual(w["inst"]["m3"], -63.0)
        short = metrics.flow_windows(inv.iloc[-10:], today)   # 10행뿐
        self.assertEqual(short["frgn"]["d5"], 5.0); self.assertIsNone(short["frgn"]["m1"])
        self.assertIsNone(short["frgn"]["ytd"])              # 전년 행 없음 → ytd 모름
        self.assertEqual(metrics.flow_windows(pd.DataFrame(), today), {"rows": 0})

    def test_drop_today_premarket_zero_row(self):
        inv = self.inv([10, 20, 30, 40, 50, 0], [1, 1, 1, 1, 1, 0])     # 마지막 행 = 장 전 '오늘 0'
        today = inv["date"].iloc[-1]
        f = metrics.flow_summary(metrics.drop_today(inv, today), today, mcap=None)
        self.assertFalse(f["has_today"]); self.assertEqual(f["frgn5"], 10 + 20 + 30 + 40 + 50)
        self.assertEqual(f["frgn_streak"], 5)                              # 0 행이 연속일수를 끊지 않는다
        self.assertTrue(metrics.drop_today(pd.DataFrame(), today).empty)

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


class NaverTrend(unittest.TestCase):
    def test_frame_and_merge(self):
        rows = [{"itemCode": "009540", "bizdate": "20261016", "foreignerPureBuyQuant": "+16,135", "organPureBuyQuant": "-6,507",
                 "individualPureBuyQuant": "-10,120", "closePrice": "264,500"},
                {"itemCode": "009540", "bizdate": "20261015", "foreignerPureBuyQuant": "-1,000", "organPureBuyQuant": "0",
                 "individualPureBuyQuant": "+1,000", "closePrice": "260,000"},
                {"itemCode": "009540", "bizdate": "20261014", "foreignerPureBuyQuant": "x", "closePrice": "0"}]   # 종가 0 → 버림
        nv = kis.naver_trend_frame(rows)
        self.assertEqual(len(nv), 2)
        self.assertAlmostEqual(nv.iloc[-1]["외국인"], round(16135 * 264500 / 1e8, 1))   # 42.7억 근사
        self.assertAlmostEqual(nv.iloc[0]["개인"], round(1000 * 260000 / 1e8, 1))
        k = kis.investor_frame([{"stck_bsop_date": "20261016", "prsn_ntby_tr_pbmn": "-1000", "frgn_ntby_tr_pbmn": "4000", "orgn_ntby_tr_pbmn": "-1700"}])
        m = kis.merge_investor(k, nv)
        self.assertEqual(len(m), 2)
        self.assertEqual(float(m[m["date"] == "2026-10-16"]["외국인"].iloc[0]), 40.0)   # 같은 날짜는 한투 금액 우선
        self.assertEqual(float(m[m["date"] == "2026-10-15"]["외국인"].iloc[0]), -2.6)  # 없는 날짜만 네이버 근사
        self.assertTrue(kis.naver_trend_frame([]).empty)
        self.assertIs(kis.merge_investor(k, kis.naver_trend_frame([])), k)


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
                 "flow": {"fi5_mcap_pct": 0.7, "frgn5": 108, "inst5": 19, "indiv5": -120, "frgn_streak": 13, "inst_streak": 1, "has_today": True, "frgn_today": 50, "inst_today": 3,
                          "win": {"rows": 30, "frgn": {"today": 50, "d5": 108, "m1": 300, "m3": None, "ytd": None}, "inst": {"today": 3, "d5": 19, "m1": -40, "m3": None, "ytd": None}, "indiv": {"today": -53, "d5": -120, "m1": -260, "m3": None, "ytd": None}}},
                 "tech": {"rsi": 69.0, "rsi_prev": 66.0, "rsi_pctl": 96.5, "extreme": "1년 최고권 (상위 4%)", "hi52_pct": -1.0, "lo52_pct": 80.0, "adv20": 500, "provisional": True,
                          "ret": {"d1": 0.4, "w1": 3.2, "m1": -5.1, "m3": None, "ytd": 42.0}, "spark": [100, 102, 99, 105, 110]},
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
        self.assertNotIn("github.io", txt)                                  # 대시보드 주소 비노출

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

    def test_compose_html_bold_header_and_escape(self):
        d = fake_payload(); d["rows"][0]["name"] = "LIG D&A"; d["errors"] = []
        h = notify.compose_html(d)
        first = h.split("\n")[0]
        self.assertTrue(first.startswith("<b>[GS🎴 조선·방산·건기] 수급 브리핑") and first.endswith("</b>"), first)
        self.assertIn("LIG D&amp;A", h); self.assertNotIn("D&A", h)
        for head in ("<b>📈 사는 쪽 · 시총 대비 5일</b>", "<b>📉 파는 쪽 · 시총 대비 5일</b>", "<b>⚙️ 기계적 수급 (ETF/패시브)</b>"):
            self.assertIn(head, h)
        self.assertEqual(h.count("<b>"), 4)                                    # 머리글 + 섹션 제목 3개만 볼드
        sent = []
        with tempfile.TemporaryDirectory() as tmp:
            latest, status = os.path.join(tmp, "l.json"), os.path.join(tmp, "s.json")
            with open(latest, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
            with unittest.mock.patch.object(notify, "LATEST", latest), unittest.mock.patch.object(notify, "STATUS", status), \
                 unittest.mock.patch.object(notify, "send", lambda text, parse_mode=None: sent.append((text[:3], parse_mode)) or {"ok": True}):
                notify.main([])
        self.assertEqual(sent, [("<b>", "HTML")])

    def test_text_rides_as_album_caption(self):
        """캡쳐가 있으면 본문이 앨범 캡션(사진 밑)으로 간다 — 1024자 이내면 send() 미호출, 넘치면 옛 방식."""
        d = fake_payload(); d["errors"] = []
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            latest, status = os.path.join(tmp, "l.json"), os.path.join(tmp, "s.json")
            for i in range(3):
                open(os.path.join(tmp, f"capture_{i}.png"), "wb").write(b"x")
            with open(latest, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
            with unittest.mock.patch.object(notify, "LATEST", latest), unittest.mock.patch.object(notify, "STATUS", status), \
                 unittest.mock.patch.object(notify, "send", lambda text, parse_mode=None: calls.append(("text", parse_mode)) or {"ok": True}), \
                 unittest.mock.patch.object(notify, "send_photos", lambda paths, caption="", parse_mode=None: calls.append(("album", parse_mode, len(paths), caption[:3], len(caption))) or {"ok": True}):
                notify.main(["--photos", os.path.join(tmp, "capture_*.png")])
                self.assertEqual(calls, [("album", "HTML", 3, "<b>", len(notify.compose_html(d)))])
                # 긴 본문: 캡션 한도 초과 → 본문 따로(HTML) + 사진은 짧은 캡션
                calls.clear()
                with unittest.mock.patch.object(notify, "compose_html", lambda dd: "<b>x</b>" + "y" * 1100):
                    notify.main(["--photos", os.path.join(tmp, "capture_*.png")])
                self.assertEqual(calls[0], ("text", "HTML")); self.assertEqual(calls[1][:2], ("album", None))

    def test_compose_empty(self):
        txt = notify.compose({"asof": "2026-10-16 10:01", "rows": [], "etfs": [], "active": []})
        self.assertIn("순매수 종목 없음", txt); self.assertIn("첫 수집", txt); self.assertIn("극단권 종목 없음", txt)

    def test_render(self):
        h = build_report.render(fake_payload())
        for s in ("한화오션", "13일째 매수", "1년 최저권", "SOL 조선TOP3플러스", "수집 오류 1건", "커버예정", "직전 값 없음", "TIME 코스피액티브",
                  "① 등락률", "①-2 투자자별 순매수", "+42.0", "+300", "② 과매수", "③ 기계적 수급", '<details id="cap-3"', "3개월 차트", "📅 수집 시각 <b>10/16(금) 13:31</b>"):
            self.assertIn(s, h)
        self.assertNotIn("chr(", h)
        self.assertNotIn("5일 외인+기관", h)                                  # 시총 대비 열 제거
        # 조건부서식 음영: 값 있는 칸에 양수=빨강·음수=파랑 rgba 배경이 붙는다(한국식).
        self.assertIn("background:rgba(220,38,38,", h)
        self.assertIn("background:rgba(37,99,235,", h)
        self.assertNotIn('<span class="pos">250,000', h)                             # 시총엔 색 없음

    def test_frgn_backfill_from_previous_snapshot(self):
        """외인 보유비율 None 은 직전 스냅샷 값 + 기준일로 채운다. 실측값·직전도 없음은 불변."""
        import collect
        prev = {"market_day": "2026-10-16", "date": "2026-10-17", "rows": [
            {"code": "A", "px": {"frgn_pct": 12.34}},
            {"code": "B", "px": {"frgn_pct": 5.0, "frgn_pct_asof": "2026-10-15"}},
            {"code": "C", "px": {"frgn_pct": None}},
            {"code": "E", "px": {"frgn_pct": 0.0}},
        ]}
        rows = [
            {"code": "A", "px": {"frgn_pct": None}},     # 직전 실측 → 채움, asof=직전 market_day
            {"code": "B", "px": {"frgn_pct": None}},     # 직전도 이월분 → 원 날짜 승계
            {"code": "C", "px": {"frgn_pct": None}},     # 직전도 없음 → None 유지
            {"code": "D", "px": {"frgn_pct": 7.7}},      # 당일 실측 → 불변·asof 없음
            {"code": "E", "px": {"frgn_pct": None}},     # 직전이 '가짜 0' → 이월 금지
        ]
        collect.backfill_frgn(rows, prev)
        self.assertEqual(rows[0]["px"]["frgn_pct"], 12.34)
        self.assertEqual(rows[0]["px"]["frgn_pct_asof"], "2026-10-16")
        self.assertEqual(rows[1]["px"]["frgn_pct_asof"], "2026-10-15")
        self.assertIsNone(rows[2]["px"]["frgn_pct"])
        self.assertEqual(rows[3]["px"], {"frgn_pct": 7.7})
        self.assertIsNone(rows[4]["px"]["frgn_pct"])
        # 화면: 이월분은 기준일을 작게 병기, 당일 실측은 날짜 없음
        self.assertIn("10/16</small>", build_report.frgn_cell(rows[0]["px"]))
        self.assertNotIn("stale", build_report.frgn_cell(rows[3]["px"]))
        self.assertIn("na", build_report.frgn_cell({"frgn_pct": None}))

    def test_shade_scales_and_skips_blanks(self):
        """음영은 열 최대값 대비 강도, 0·결측·cap 0 은 음영 없음, 상한을 넘지 않는다."""
        self.assertEqual(build_report.shade(None, 10), "")
        self.assertEqual(build_report.shade(0, 10), "")
        self.assertEqual(build_report.shade(5, 0), "")
        full = build_report.shade(10, 10); half = build_report.shade(5, 10)
        self.assertIn("rgba(220,38,38,0.45)", full)                            # 최대 알파, 양수=빨강
        self.assertIn("rgba(220,38,38,0.27)", half)
        self.assertIn("rgba(37,99,235,", build_report.shade(-3, 10))           # 음수=파랑
        self.assertEqual(build_report.shade(999, 10), full)                    # cap 초과도 상한 고정
        caps = build_report.col_caps({"a": [1, -7, None], "b": [None, None]})
        self.assertEqual(caps["a"], 7); self.assertEqual(caps["b"], 0.0)

    def test_grouped_tables(self):
        """표는 조선(조선+조기)·방산·기계 묶음, 성광벤드·태광은 조선 묶음 맨 밑. 묶음 안은 기존 정렬."""
        rows = [
            {"name": "태광", "industry": "조기"}, {"name": "한화오션", "industry": "조선"},
            {"name": "성광벤드", "industry": "조기"}, {"name": "HD현대중공업", "industry": "조선"},
            {"name": "한화시스템", "industry": "방산"}, {"name": "두산밥캣", "industry": "건기"},
        ]
        score = {"태광": 99, "한화오션": 1, "성광벤드": 50, "HD현대중공업": 5, "한화시스템": 0, "두산밥캣": 0}
        g = build_report.grouped(rows, key=lambda r: score[r["name"]], reverse=True)
        self.assertEqual([x[0] for x in g], ["조선", "방산", "기계"])
        self.assertEqual([r["name"] for r in g[0][1]], ["HD현대중공업", "한화오션", "성광벤드", "태광"])  # 점수 높은 태광도 맨 뒤
        d = fake_payload()
        d["rows"][2].update(industry="건기", tech=dict(d["rows"][0]["tech"]), flow=dict(d["rows"][0]["flow"]))  # 오류 행에 지표를 줘서 표에 올린다
        h = build_report.render(d)
        self.assertIn("<tr class='gh'><td colspan='9'>조선</td></tr>", h)
        self.assertIn("<tr class='gh'><td colspan='16'>방산</td></tr>", h)
        self.assertIn("<tr class='gh'><td colspan='8'>기계</td></tr>", h)
        self.assertLess(h.index(">조선</td>"), h.index(">방산</td>")); self.assertLess(h.index(">방산</td>"), h.index(">기계</td>"))

    def test_tables_sorted_by_mcap(self):
        """세 표 모두 묶음 안은 시총 내림차순, 성광벤드·태광은 여전히 조선 맨 밑."""
        d = fake_payload()
        base = d["rows"][0]
        def mk(name, mcap, ind="조선"):
            r = json.loads(json.dumps(base)); r.update(name=name, industry=ind, code=name); r["px"]["mcap"] = mcap
            r["tech"]["rsi"] = 10 if name == "작은" else 90          # RSI 순이면 '작은' 이 먼저 올 값
            r["flow"]["frgn5"] = 999 if name == "작은" else 1       # 외인 5일 순이면 '작은' 이 먼저 올 값
            return r
        d["rows"] = [mk("작은", 100), mk("큰", 5000), mk("성광벤드", 9999), mk("중간", 1000)]
        h = build_report.render(d)
        for tbl in h.split("<table")[1:4]:                                       # 등락률·수급·과매수 세 표
            order = [n for n in ("큰", "중간", "작은", "성광벤드") if n in tbl]
            idx = [tbl.index(f"<td>{n}") for n in order]
            self.assertEqual(idx, sorted(idx), order)


class KisToken(unittest.TestCase):
    def test_token_retries_past_rate_limit_403(self):
        """토큰 발급 403(분당 1회 제한, 다른 잡과 동시 시작)은 기다렸다 재시도한다."""
        import kis

        class R:
            def __init__(self, code):
                self.status_code = code

            def raise_for_status(self):
                if self.status_code != 200:
                    raise RuntimeError(f"HTTP {self.status_code}")

            def json(self):
                return {"access_token": "tok"}

        calls, naps = [], []
        responses = [R(403), R(403), R(200)]
        saved_post, saved_sleep = kis.requests.post, kis.time.sleep
        saved_cache = dict(kis._c)
        kis.requests.post = lambda *a, **k: (calls.append(1), responses[len(calls) - 1])[1]
        kis.time.sleep = lambda s: naps.append(s)
        kis._c.update(t=None, ts=0)
        os.environ.setdefault("KIS_APP_KEY", "k"); os.environ.setdefault("KIS_APP_SECRET", "s")
        try:
            self.assertEqual(kis.token(tries=5, wait=20), "tok")
        finally:
            kis.requests.post, kis.time.sleep = saved_post, saved_sleep
            kis._c.update(saved_cache)
        self.assertEqual(len(calls), 3)          # 403 두 번 뒤 성공
        self.assertEqual(naps, [20, 20])         # 분 경계를 넘길 대기

    def test_token_gives_up_after_tries(self):
        import kis

        class R403:
            status_code = 403

            def raise_for_status(self):
                raise RuntimeError("HTTP 403")

        naps = []
        saved_post, saved_sleep = kis.requests.post, kis.time.sleep
        saved_cache = dict(kis._c)
        kis.requests.post = lambda *a, **k: R403()
        kis.time.sleep = lambda s: naps.append(s)
        kis._c.update(t=None, ts=0)
        os.environ.setdefault("KIS_APP_KEY", "k"); os.environ.setdefault("KIS_APP_SECRET", "s")
        try:
            with self.assertRaises(RuntimeError):
                kis.token(tries=3, wait=1)
        finally:
            kis.requests.post, kis.time.sleep = saved_post, saved_sleep
            kis._c.update(saved_cache)
        self.assertEqual(naps, [1, 1])           # 마지막 시도는 기다리지 않고 올린다


class CollectGuard(unittest.TestCase):
    def test_enough_blocks_partial_runs(self):
        """21종목 중 2종목(10/19 토큰 403 사고)은 부족, 15종목(71%)은 통과, 유니버스 0은 실패."""
        self.assertFalse(collect.enough(2, 21))
        self.assertTrue(collect.enough(15, 21))
        self.assertFalse(collect.enough(14, 21))
        self.assertTrue(collect.enough(21, 21))
        self.assertFalse(collect.enough(0, 0))
        self.assertTrue(collect.enough(1, 2, ratio=0.5))

    def test_partial_run_keeps_previous_latest(self):
        """부족한 run 은 latest.json 을 덮어쓰지 않고 종료코드 2."""
        with tempfile.TemporaryDirectory() as d:
            latest = os.path.join(d, "latest.json")
            with open(latest, "w") as f:
                json.dump({"asof": "이전 정상본"}, f)
            uni = [{"code": str(i), "name": f"s{i}", "industry": "조선", "status": "커버리지"} for i in range(5)]
            calls = {"n": 0}
            def fake_stock(u, today, live):
                calls["n"] += 1
                if calls["n"] > 1:
                    raise RuntimeError("403 tokenP")
                return {"code": u["code"], "name": u["name"], "industry": "조선", "status": "커버리지",
                        "tech": {}, "flow": {}, "px": {}}
            with unittest.mock.patch.object(collect, "LATEST", latest), \
                 unittest.mock.patch.object(collect, "market_day", lambda: ("2026-10-19", "OPEN")), \
                 unittest.mock.patch.object(collect, "load_csv", lambda fn: uni), \
                 unittest.mock.patch.object(collect, "collect_stock", fake_stock), \
                 unittest.mock.patch.object(collect.sys, "argv", ["collect.py", "--force"]):
                rc = collect.main()
            self.assertEqual(rc, 2)
            with open(latest) as f:
                self.assertEqual(json.load(f)["asof"], "이전 정상본")

    def test_notify_skips_when_any_error(self):
        """수집 오류가 하나라도 있으면 send() 를 부르지 않고 status 에 생략 사유만 남긴다."""
        with tempfile.TemporaryDirectory() as d:
            latest, status = os.path.join(d, "latest.json"), os.path.join(d, "status.json")
            payload = fake_payload(); payload["errors"] = ["000490 대동: RuntimeError: 예시"]
            with open(latest, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            sent = []
            with unittest.mock.patch.object(notify, "LATEST", latest), unittest.mock.patch.object(notify, "STATUS", status), \
                 unittest.mock.patch.object(notify, "send", lambda text, parse_mode=None: sent.append(text) or {"ok": True}), \
                 unittest.mock.patch.object(notify, "send_photos", lambda *a, **k: sent.append("photo") or {"ok": True}):
                rc = notify.main(["--photos", os.path.join(d, "none_*.png")])
            self.assertEqual(rc, 0); self.assertEqual(sent, [])
            with open(status, encoding="utf-8") as f:
                st = json.load(f)
            self.assertTrue(st["skipped"]); self.assertIn("오류 1건", st["description"])
            # 오류가 없으면 평소대로 보낸다
            payload["errors"] = []
            with open(latest, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            with unittest.mock.patch.object(notify, "LATEST", latest), unittest.mock.patch.object(notify, "STATUS", status), \
                 unittest.mock.patch.object(notify, "send", lambda text, parse_mode=None: sent.append(text) or {"ok": True}):
                notify.main([])
            self.assertEqual(len(sent), 1)


class KisToken(unittest.TestCase):
    def test_token_retries_past_rate_limit_403(self):
        """토큰 발급 403(분당 1회 제한, 다른 잡과 동시 시작)은 기다렸다 재시도한다."""
        import kis

        class R:
            def __init__(self, code):
                self.status_code = code

            def raise_for_status(self):
                if self.status_code != 200:
                    raise RuntimeError(f"HTTP {self.status_code}")

            def json(self):
                return {"access_token": "tok"}

        calls, naps = [], []
        responses = [R(403), R(403), R(200)]
        saved_post, saved_sleep = kis.requests.post, kis.time.sleep
        saved_cache = dict(kis._c)
        kis.requests.post = lambda *a, **k: (calls.append(1), responses[len(calls) - 1])[1]
        kis.time.sleep = lambda s: naps.append(s)
        kis._c.update(t=None, ts=0)
        os.environ.setdefault("KIS_APP_KEY", "k"); os.environ.setdefault("KIS_APP_SECRET", "s")
        try:
            self.assertEqual(kis.token(tries=5, wait=20), "tok")
        finally:
            kis.requests.post, kis.time.sleep = saved_post, saved_sleep
            kis._c.update(saved_cache)
        self.assertEqual(len(calls), 3)          # 403 두 번 뒤 성공
        self.assertEqual(naps, [20, 20])         # 분 경계를 넘길 대기

    def test_token_gives_up_after_tries(self):
        import kis

        class R403:
            status_code = 403

            def raise_for_status(self):
                raise RuntimeError("HTTP 403")

        naps = []
        saved_post, saved_sleep = kis.requests.post, kis.time.sleep
        saved_cache = dict(kis._c)
        kis.requests.post = lambda *a, **k: R403()
        kis.time.sleep = lambda s: naps.append(s)
        kis._c.update(t=None, ts=0)
        os.environ.setdefault("KIS_APP_KEY", "k"); os.environ.setdefault("KIS_APP_SECRET", "s")
        try:
            with self.assertRaises(RuntimeError):
                kis.token(tries=3, wait=1)
        finally:
            kis.requests.post, kis.time.sleep = saved_post, saved_sleep
            kis._c.update(saved_cache)
        self.assertEqual(naps, [1, 1])           # 마지막 시도는 기다리지 않고 올린다


if __name__ == "__main__":
    unittest.main(verbosity=1)
