# -*- coding: utf-8 -*-
"""휴장일 게이트와 '구성이 실제로 바뀌었나' 지문 검산.

2026-10-05(대체공휴일)에 하루 세 번 돌면서 휴장일인데도 '매매'가 잡힌 사고를 막는 장치들.
네트워크가 막힌 컨테이너에서도 돌도록 fetch 계층은 전부 가짜로 바꿔 끼운다.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fetch_holdings as fh  # noqa: E402
import watch  # noqa: E402


def _etfs(samsung=370, hynix=59):
    return {"445290": {"label": "KODEX 로봇액티브", "group": "테마", "nav": 31170.0,
                       "holdings": [{"key": "005930", "code": "005930", "name": "삼성전자",
                                     "shares": samsung, "weight": 9.59},
                                    {"key": "000660", "code": "000660", "name": "SK하이닉스",
                                     "shares": hynix, "weight": 5.1}]}}


class TestMarketGate(unittest.TestCase):
    def setUp(self):
        self.orig = fh.market_day
        os.environ.pop("WATCH_FORCE", None)

    def tearDown(self):
        fh.market_day = self.orig
        os.environ.pop("WATCH_FORCE", None)

    def test_holiday_skips(self):
        """휴장일: 거래소 마지막 거래일이 오늘이 아니다 → 돌지 않는다."""
        from datetime import datetime
        fh.market_day = lambda: ("2026-10-02", "CLOSE")
        today = datetime.now(watch.KST).strftime("%Y-%m-%d")
        if today == "2026-10-02":        # 하필 그날 돌리면 의미가 없다
            self.skipTest("기준일과 오늘이 같은 날")
        self.assertFalse(watch.check())

    def test_trading_day_runs(self):
        from datetime import datetime
        today = datetime.now(watch.KST).strftime("%Y-%m-%d")
        fh.market_day = lambda: (today, "OPEN")
        self.assertTrue(watch.check())

    def test_force_overrides_holiday(self):
        """화면의 수동 '갱신' 버튼은 휴장일에도 돌아야 한다."""
        fh.market_day = lambda: ("2026-10-02", "CLOSE")
        os.environ["WATCH_FORCE"] = "1"
        self.assertTrue(watch.check())

    def test_unknown_market_fails_open(self):
        """장 상태 조회 실패로 며칠씩 조용히 비는 쪽이 더 위험하다 → 일단 실행."""
        fh.market_day = lambda: ("", "")
        self.assertTrue(watch.check())


class TestSnapshotGate(unittest.TestCase):
    """구성이 그대로면 스냅샷을 쓰지 않는다 — 가짜 '매매'의 뿌리."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig = (fh.SNAP_DIR, fh.load_universe, fh.fetch_one, fh.market_day)
        fh.SNAP_DIR = self.tmp
        fh.load_universe = lambda: [{"group": "테마", "name": "KODEX 로봇액티브",
                                     "code": "445290"}]
        fh.market_day = lambda: ("2026-10-02", "CLOSE")
        os.environ.pop("GITHUB_OUTPUT", None)

    def tearDown(self):
        fh.SNAP_DIR, fh.load_universe, fh.fetch_one, fh.market_day = self.orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _serve(self, samsung=370, hynix=59, fail=False):
        def one(code, tries=3):
            if fail:
                raise RuntimeError("수집 실패")
            return dict(_etfs(samsung, hynix)["445290"])
        fh.fetch_one = one

    def _files(self):
        return sorted(os.listdir(self.tmp))

    def test_first_run_writes(self):
        self._serve()
        out = fh.snapshot("2026-10-02")
        self.assertTrue(out["changed"])
        self.assertEqual(self._files(), ["2026-10-02.json"])

    def test_same_basket_does_not_write(self):
        self._serve()
        fh.snapshot("2026-10-02")
        out = fh.snapshot("2026-10-05")          # 휴장일 재수집 — 같은 바스켓
        self.assertFalse(out["changed"])
        self.assertEqual(self._files(), ["2026-10-02.json"])   # 새 파일 없음

    def test_weight_only_change_is_not_a_trade(self):
        """비중은 주가만 움직여도 매일 바뀐다 — 그걸 매매로 세면 안 된다."""
        self._serve()
        fh.snapshot("2026-10-02")

        def one(code, tries=3):
            rec = dict(_etfs()["445290"])
            rec["holdings"] = [dict(h) for h in rec["holdings"]]
            rec["holdings"][0]["weight"] = 11.11      # 계약수는 그대로
            rec["nav"] = 99999.0
            return rec
        fh.fetch_one = one
        self.assertFalse(fh.snapshot("2026-10-05")["changed"])

    def test_share_change_writes(self):
        self._serve()
        fh.snapshot("2026-10-02")
        self._serve(samsung=364)                  # 실제 매도
        out = fh.snapshot("2026-10-06")
        self.assertTrue(out["changed"])
        self.assertEqual(self._files(), ["2026-10-02.json", "2026-10-06.json"])

    def test_partial_failure_does_not_write(self):
        """일부 ETF 수집 실패로 종목이 빠진 걸 '이탈'로 저장하면 안 된다."""
        self._serve()
        fh.snapshot("2026-10-02")
        self._serve(fail=True)
        out = fh.snapshot("2026-10-06")
        self.assertFalse(out["changed"])
        self.assertEqual(self._files(), ["2026-10-02.json"])


if __name__ == "__main__":
    unittest.main()
