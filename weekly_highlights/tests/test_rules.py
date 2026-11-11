import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rules  # noqa: E402


def flat(n=300, v=100.0):
    return [v] * n


def noisy(n=300, seed=1, drift=0.0, sd=0.01):
    rnd = random.Random(seed)
    out, p = [], 100.0
    for _ in range(n):
        p *= 1 + drift + rnd.gauss(0, sd)
        out.append(p)
    return out


class WeeklyReturns(unittest.TestCase):
    def test_non_overlapping_latest_first(self):
        c = [100] * 11
        c[-1] = 110   # 이번 주 +10%
        c[-6] = 100
        wk = rules.weekly_returns(c)
        self.assertEqual(len(wk), 2)
        self.assertAlmostEqual(wk[0], 0.10)
        self.assertAlmostEqual(wk[1], 0.0)

    def test_short_series(self):
        self.assertEqual(rules.weekly_returns([100, 101, 102]), [])

    def test_zscore_needs_samples(self):
        self.assertIsNone(rules.zscore(0.1, [0.01] * 10))
        self.assertIsNone(rules.zscore(0.1, [0.01] * 30))   # 분산 0
        z = rules.zscore(0.1, [0.01, -0.01] * 15)
        self.assertGreater(z, 5)


class PriceFlags(unittest.TestCase):
    def test_quiet_series_no_reason(self):
        c = [100 * 1.003 ** (i // 5) + (0.2 if i % 2 else 0) for i in range(300)]   # 매주 +0.3%, 분산 ≈ 0
        r, m = rules.price_flags(c)
        self.assertEqual([x["kind"] for x in r if x["kind"] in ("ret", "z")], [])

    def test_big_week_flags_ret_and_z(self):
        c = noisy(sd=0.005, seed=5)
        c[-1] = c[-6] * 1.12   # 이번 주 +12%
        r, m = rules.price_flags(c)
        kinds = [x["kind"] for x in r]
        self.assertEqual(kinds.count("ret") + kinds.count("z"), 1)   # 등락+z 는 한 줄로
        self.assertIn("z ", [x for x in r if x["kind"] == "ret"][0]["text"])
        self.assertAlmostEqual(m["r1w"], 0.12, places=6)
        self.assertTrue(all(x["score"] >= 1 for x in r))

    def test_index_threshold_lower(self):
        c = noisy(sd=0.005, seed=7)
        c[-1] = c[-6] * 1.07   # +7%: 종목 임계(8%) 미만, 지수 임계(6%) 이상
        r_stock, _ = rules.price_flags(c)
        r_index, _ = rules.price_flags(c, is_index=True)
        self.assertNotIn("ret", {x["kind"] for x in r_stock})
        self.assertIn("ret", {x["kind"] for x in r_index})

    def test_52w_high_low(self):
        c = noisy(sd=0.003, seed=9)
        c[-2] = max(c) * 1.01   # 이번 주 안에 신고가
        r, m = rules.price_flags(c)
        self.assertTrue(m["hi52"])
        self.assertIn("hi52", {x["kind"] for x in r})
        c2 = noisy(sd=0.003, seed=9)
        c2[-1] = min(c2) * 0.99
        r2, m2 = rules.price_flags(c2)
        self.assertTrue(m2["lo52"])

    def test_52w_needs_history(self):
        r, m = rules.price_flags([100, 120, 90, 150])
        self.assertFalse(m["hi52"])
        self.assertFalse(m["lo52"])

    def test_z_silent_when_history_short(self):
        c = noisy(n=40, sd=0.005)
        c[-1] = c[-6] * 1.3
        r, m = rules.price_flags(c)
        self.assertIsNone(m["z1w"])
        self.assertIn("ret", {x["kind"] for x in r})


class RankChange(unittest.TestCase):
    def test_leader_swap(self):
        r = rules.rank_change([("A", 105, 102), ("B", 101, 108)])
        self.assertEqual(r["kind"], "rank")
        self.assertIn("A → B", r["text"])

    def test_no_swap(self):
        self.assertIsNone(rules.rank_change([("A", 105, 110), ("B", 101, 104)]))
        self.assertIsNone(rules.rank_change([("A", 105, 110)]))


class FlowFlags(unittest.TestCase):
    def test_big_week_vs_mcap(self):
        cum = [0] * 240
        cum[-1] = 600                       # 이번 주 +600억
        mc = [100000] * 240                 # 시총 10조 → 0.6%(임계 0.5%)
        r, wk = rules.flow_flags(mc, cum, "외인")
        self.assertEqual(wk, 600)
        kinds = {x["kind"] for x in r}
        self.assertIn("flow", kinds)
        self.assertIn("flowmax", kinds)      # 나머지 주가 전부 0 → 1년 최대

    def test_small_abs_ignored(self):
        cum = [0] * 240
        cum[-1] = 30                        # 30억 — 시총 1,000억의 3% 지만 절대값이 작다
        r, wk = rules.flow_flags([1000] * 240, cum, "기관")
        self.assertEqual(r, [])

    def test_sign_flip(self):
        cum = [-300] * 240
        cum[-1] = 400
        r, _ = rules.flow_flags([100000] * 240, cum, "외인")
        self.assertIn("flip", {x["kind"] for x in r})

    def test_short_or_missing(self):
        r, wk = rules.flow_flags([1], [1, 2], "외인")
        self.assertEqual((r, wk), ([], None))


class ConsensusFlags(unittest.TestCase):
    def test_week_change(self):
        pts = [("2026-10-02", 1000), ("2026-10-09", 1000), ("2026-10-30", 1000), ("2026-11-06", 1000), ("2026-11-10", 1060)]
        r, m = rules.consensus_flags(pts, "4Q26E")
        self.assertEqual([x["kind"] for x in r], ["cons1w"])
        self.assertEqual(m["w"]["d"], "2026-10-30")   # 11-06 은 4일 전이라 제외, 6일 이상 전 중 가장 최근 = 10-30

    def test_week_reference_skips_too_recent(self):
        pts = [("2026-11-06", 1000), ("2026-11-09", 1100), ("2026-11-10", 1100)]
        r, m = rules.consensus_flags(pts, "x")
        self.assertNotIn("w", m)          # 6일 이상 전 스냅샷 없음 → 1주 판정 침묵
        self.assertEqual(r, [])

    def test_flip_and_month(self):
        pts = [("2026-10-01", -100), ("2026-11-03", -100), ("2026-11-10", 50)]
        r, m = rules.consensus_flags(pts, "x")
        self.assertIn("flip", {x["kind"] for x in r})
        pts2 = [("2026-10-01", 1000), ("2026-11-03", 1150), ("2026-11-10", 1170)]
        r2, _ = rules.consensus_flags(pts2, "x")
        self.assertEqual({x["kind"] for x in r2}, {"cons1m"})


class ErFlags(unittest.TestCase):
    def test_few_analysts_silent(self):
        self.assertEqual(rules.er_flags({"n_analysts": "2", "er30": "-100", "eps_chg_1m": "-0.3"}), [])

    def test_levels_and_wow(self):
        row = {"n_analysts": "8", "er30": "-62.5", "eps_chg_1m": "-0.09", "eps_chg_3m": "0.02", "eps_cur": "91", "eps_30d": "100", "eps_90d": "89"}
        r = rules.er_flags(row, {"er30": "-10"})
        self.assertEqual([x["kind"] for x in r], ["er30", "eps1m", "erwow"])

    def test_eps_sign_flip_is_not_a_percent(self):
        row = {"n_analysts": "16", "er30": "-10", "eps_chg_1m": "-55.26", "eps_chg_3m": "-57.2",
               "eps_cur": "-2.1", "eps_30d": "0.04", "eps_90d": "0.04"}
        r = rules.er_flags(row)
        self.assertEqual([x["kind"] for x in r], ["epsflip", "epsflip"])
        self.assertTrue(all(x["score"] <= rules.TH["score_cap"] for x in r))

    def test_score_cap(self):
        c = [100.0] * 300
        c[-1] = 900.0
        r, _ = rules.price_flags(c)
        self.assertTrue(all(x["score"] <= rules.TH["score_cap"] for x in r))

    def test_nan_strings(self):
        self.assertEqual(rules.er_flags({"n_analysts": "5", "er30": "nan", "eps_chg_1m": "", "eps_chg_3m": None}), [])


if __name__ == "__main__":
    unittest.main()
