# -*- coding: utf-8 -*-
"""RSI 신호(메인 지표) 검산 — 네트워크 없이 합성 시세로 돈다.

규칙: RSI(14)가 30 이하로 '내려선 첫날' = 매수, 70을 위에서 아래로 뚫은 날 = 매도.
실행: python -m unittest discover -s tests -p "test_*.py"
"""
import os, sys, unittest
import numpy as np
import pandas as pd

os.environ.setdefault("KIS_APP_KEY", "x")       # etf_signal 은 import 시 키를 읽는다
os.environ.setdefault("KIS_APP_SECRET", "x")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import etf_signal as E  # noqa: E402

WARMUP = 30   # 지수평활 초기값이 자리 잡기 전 구간은 판정에서 뺀다


def px(closes):
    c = pd.Series(closes, dtype=float)
    return pd.DataFrame({"date": pd.date_range("2026-01-01", periods=len(c)),
                         "o": c, "h": c * 1.01, "l": c * 0.99, "c": c, "v": 1e6})


def events(closes):
    p = px(closes)
    adx, pdi, ndi = E.adx_di(p)
    sk, sd = E.stoch_slow(p)
    r = E.rsi(p)
    return p, r, E.cross_events(adx, pdi, ndi, sk, sd, r)


def hits(mask):
    return [i for i in mask[mask].index if i >= WARMUP]


# 완만히 오르다(RSI 100 근처) 급락 → 70 하향이탈 한 번, 이어서 30 이하 진입 한 번
UP_THEN_DOWN = [100 + i * 0.5 for i in range(40)] + [120 - i * 2 for i in range(15)]


class RsiValue(unittest.TestCase):
    def test_extremes(self):
        self.assertAlmostEqual(E.rsi(px(np.arange(100, 140))).iloc[-1], 100)
        self.assertAlmostEqual(E.rsi(px(np.arange(140, 100, -1))).iloc[-1], 0)

    def test_first_bar_is_nan(self):
        self.assertTrue(pd.isna(E.rsi(px(np.arange(100, 140))).iloc[0]))

    def test_alternating_is_near_50(self):
        r = E.rsi(px([100 + (i % 2) for i in range(200)]))
        self.assertTrue(45 < r.iloc[-1] < 55)


class RsiEvents(unittest.TestCase):
    def test_buy_only_on_first_day_below_30(self):
        _, r, ev = events(UP_THEN_DOWN)
        b = hits(ev["rsi_buy"])
        self.assertEqual(len(b), 1)            # 30 아래에 머무는 동안 매일 뜨지 않는다
        i = b[0]
        self.assertTrue(r.iloc[i] <= 30 < r.iloc[i - 1])
        self.assertTrue((r.iloc[i:] <= 30).all())

    def test_sell_on_cross_down_through_70(self):
        _, r, ev = events(UP_THEN_DOWN)
        s = hits(ev["rsi_sell"])
        self.assertEqual(len(s), 1)
        i = s[0]
        self.assertTrue(r.iloc[i - 1] > 70 >= r.iloc[i])
        self.assertLess(i, hits(ev["rsi_buy"])[0])   # 꺾임(매도)이 과매도(매수)보다 먼저

    def test_no_signal_in_sideways(self):
        _, _, ev = events([100 + (i % 2) for i in range(120)])
        self.assertEqual(hits(ev["rsi_buy"]) + hits(ev["rsi_sell"]), [])

    def test_history_markers(self):
        p, _, ev = events(UP_THEN_DOWN)
        h = E.build_history(p, ev)
        self.assertEqual(len(h["rb"]), 1)
        self.assertEqual(len(h["rs"]), 1)


if __name__ == "__main__":
    unittest.main()
