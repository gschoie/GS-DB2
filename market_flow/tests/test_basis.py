# -*- coding: utf-8 -*-
"""K200 선물 베이시스 산식 검산.

한투 OpenAPI 는 키가 있어야 하고 개발 컨테이너에서는 네이버·거래소가 막혀 있어
실호출로는 확인할 수 없다. 그래서 가짜 응답을 넣어 **계산과 월물 경계**만 검산한다
(valuation 모듈과 같은 방식).
"""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "market_flow"))

import scrape  # noqa: E402
import build_report as br  # noqa: E402


class TestContractCalendar(unittest.TestCase):
    def test_expiry_is_second_thursday(self):
        # 실측: F 202612 의 futs_last_tr_date 가 20261210 이었다.
        self.assertEqual(scrape.second_thursday(2026, 12), dt.date(2026, 12, 10))
        self.assertEqual(scrape.second_thursday(2026, 9), dt.date(2026, 9, 10))
        # 1일이 목요일인 달 — 그날이 첫 목요일이므로 만기는 8일
        self.assertEqual(dt.date(2026, 1, 1).weekday(), 3)
        self.assertEqual(scrape.second_thursday(2026, 1), dt.date(2026, 1, 8))

    def test_prev_quarter_wraps_year(self):
        self.assertEqual(scrape._prev_quarter("202612"), "202609")
        self.assertEqual(scrape._prev_quarter("202603"), "202512")

    def test_contract_code(self):
        # 마스터 실측: A01612 = F 202612, A01703 = F 202703
        self.assertEqual(scrape._contract_code("202612"), "A01612")
        self.assertEqual(scrape._contract_code("202703"), "A01703")


class TestFuturesBasis(unittest.TestCase):
    """inquire-price 응답 → 베이시스 dict"""

    SAMPLE = {   # 2026-09-22 실측 응답에서 필요한 필드만
        "output1": {"futs_prpr": "1112.00", "futs_prdy_ctrt": "-0.28",
                    "hts_thpr": "1119.90", "dprt": "-0.71", "mrkt_basis": "-1.30",
                    "hts_otst_stpl_qty": "132718", "otst_stpl_qty_icdc": "-405",
                    "hts_rmnn_dynu": "80"},
        "output3": {"bstp_nmix_prpr": "1113.30"},
    }

    def _run(self, payload):
        orig = scrape.kis_get
        scrape.kis_get = lambda *a, **k: payload
        try:
            return scrape.futures_basis("A01612")
        finally:
            scrape.kis_get = orig

    def test_parses_market_basis(self):
        b = self._run(self.SAMPLE)
        self.assertEqual(b["fut"], 1112.00)
        self.assertEqual(b["spot"], 1113.30)
        self.assertEqual(b["basis"], -1.30)          # 선물 − 현물 = 백워데이션
        self.assertEqual(b["dprt"], -0.71)
        self.assertEqual(b["theo"], 1119.90)
        self.assertEqual(b["remain"], 80)

    def test_basis_falls_back_to_subtraction(self):
        """mrkt_basis 가 안 오면 선물−현물로 직접 계산한다."""
        p = {"output1": dict(self.SAMPLE["output1"]), "output3": self.SAMPLE["output3"]}
        del p["output1"]["mrkt_basis"]
        self.assertEqual(self._run(p)["basis"], -1.30)

    def test_empty_response_raises(self):
        """월물이 바뀌어 코드가 틀리면 output1 이 빈 채로 온다 — 조용히 0을 쓰면 안 된다."""
        with self.assertRaises(RuntimeError):
            self._run({"output1": {}, "output3": self.SAMPLE["output3"]})


class TestBasisDaily(unittest.TestCase):
    """날짜마다 '그날의 근월물'을 써야 한다 — 만기 경계 검산."""

    SPOT = {"20260908": 1000.0, "20260909": 1001.0, "20260910": 1002.0,
            "20260911": 1003.0, "20260914": 1004.0}
    FUT = {"202612": 1010.0, "202609": 1005.0}   # 원월물이 더 비싸다(잔존 김)

    def setUp(self):
        self.orig = (scrape.now_kst, scrape._index_closes, scrape._futures_closes)
        scrape.now_kst = lambda: dt.datetime(2026, 9, 14, 16, 0, tzinfo=scrape.KST)
        scrape._index_closes = lambda d1, d2: dict(self.SPOT)

        def futs(code, d1, d2):
            ym = {"A01612": "202612", "A01609": "202609"}[code]
            return {d: self.FUT[ym] for d in self.SPOT}
        scrape._futures_closes = futs

    def tearDown(self):
        scrape.now_kst, scrape._index_closes, scrape._futures_closes = self.orig

    def test_switches_contract_at_expiry(self):
        out = scrape.basis_daily("202612", days=45)
        # 9/10 이 만기 → 그날까지는 9월물, 그 다음날부터 12월물
        self.assertEqual(out["2026-09-09"]["contract"], "202609")
        self.assertEqual(out["2026-09-10"]["contract"], "202609")
        self.assertEqual(out["2026-09-11"]["contract"], "202612")
        self.assertEqual(out["2026-09-14"]["contract"], "202612")

    def test_basis_is_futures_minus_spot(self):
        out = scrape.basis_daily("202612", days=45)
        self.assertAlmostEqual(out["2026-09-10"]["basis"], 1005.0 - 1002.0)
        self.assertAlmostEqual(out["2026-09-11"]["basis"], 1010.0 - 1003.0)

    def test_skips_days_without_spot(self):
        """선물만 있고 지수가 없는 날은 베이시스를 만들 수 없다 — 버린다."""
        scrape._index_closes = lambda d1, d2: {"20260911": 1003.0}
        out = scrape.basis_daily("202612", days=45)
        self.assertEqual(list(out), ["2026-09-11"])


class TestBasisRead(unittest.TestCase):
    def test_contango_and_backwardation(self):
        self.assertEqual(br.basis_read({"basis": 2.5, "dprt": 0.1})[0], "콘탱고")
        self.assertEqual(br.basis_read({"basis": -1.3, "dprt": -0.71})[0], "백워데이션")
        self.assertEqual(br.basis_read({"basis": -1.3})[2], "neg")

    def test_missing_is_none(self):
        self.assertIsNone(br.basis_read(None))
        self.assertIsNone(br.basis_read({"fut": 1112.0}))


if __name__ == "__main__":
    unittest.main()
