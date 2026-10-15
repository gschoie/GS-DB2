# -*- coding: utf-8 -*-
"""수집·성장률 산식 검산 — 네트워크 없이 가짜 응답으로 (컨테이너는 네이버 차단).

python -m pytest tests/test_growth.py 또는 python tests/test_growth.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_static as bs
import scrape


# ---- 가짜 네이버 모바일 분기 API: 실적(A) 4개 + 컨센(E) 2개 ----
def _col(v):
    return {"value": v}


FAKE_QUARTER = {"financeInfo": {
    "trTitleList": [
        {"key": "q1", "title": "2025.09.", "isConsensus": "N"},
        {"key": "q2", "title": "2025.12.", "isConsensus": "N"},
        {"key": "q3", "title": "2026.03.", "isConsensus": "N"},
        {"key": "q4", "title": "2026.06.", "isConsensus": "N"},
        {"key": "q5", "title": "2026.09.", "isConsensus": "Y"},
        {"key": "q6", "title": "2026.12.", "isConsensus": "Y"},
        {"key": "zz", "title": "전년동기", "isConsensus": "N"},   # 비분기 열은 걸러져야 함
    ],
    "rowList": [
        {"title": "매출액", "columns": {k: _col(v) for k, v in
         [("q1", "100"), ("q2", "110"), ("q3", "120"), ("q4", "130"), ("q5", "140"), ("q6", "150")]}},
        {"title": "영업이익", "columns": {k: _col(v) for k, v in
         [("q1", "10"), ("q2", "-5"), ("q3", "12"), ("q4", "13"), ("q5", "14"), ("q6", "15")]}},
        {"title": "당기순이익", "columns": {k: _col(v) for k, v in
         [("q1", "8"), ("q2", "-6"), ("q3", "9"), ("q4", "10"), ("q5", "11"), ("q6", "12")]}},
    ],
}}


class FakeResp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


class FakeSession:
    def __init__(self, payload):
        self._p = payload

    def get(self, *a, **k):
        return FakeResp(self._p)


def test_fetch_quarters_actuals_and_estimates():
    out = scrape.fetch_quarters("005930", FakeSession(FAKE_QUARTER))
    assert [q["period"] for q in out] == \
        ["2025.09", "2025.12", "2026.03", "2026.06", "2026.09", "2026.12"]
    assert [q["est"] for q in out] == [False, False, False, False, True, True]
    byp = {q["period"]: q for q in out}
    assert byp["2026.09"]["op_profit"] == 14.0
    assert byp["2025.09"]["op_profit"] == 10.0      # YoY 분모가 될 전년동기 실적
    assert byp["2025.12"]["op_profit"] == -5.0      # 음수도 그대로


def test_fetch_quarters_null_financeinfo():
    assert scrape.fetch_quarters("000000", FakeSession({"financeInfo": None})) == []


def test_growth_periods():
    assert bs.growth_periods("quarter", "2026.09") == {"qoq": "2026.06", "yoy": "2025.09"}
    assert bs.growth_periods("quarter", "2026.03") == {"qoq": "2025.12", "yoy": "2025.03"}
    assert bs.growth_periods("annual", "2027.12") == {"yoy": "2026.12"}


def test_growth_values():
    assert abs(bs.growth(14, 10) - 40.0) < 1e-9     # +40%
    assert abs(bs.growth(9, 12) + 25.0) < 1e-9      # -25%
    assert bs.growth(-3, 10) == "적전"
    assert bs.growth(14, -5) == "흑전"
    assert bs.growth(-3, -5) == "적지"
    assert bs.growth(14, 0) is None
    assert bs.growth(None, 10) is None
    assert bs.growth(14, None) is None


def test_prev_quarter():
    assert bs.prev_quarter("2026.09") == "2026.06"
    assert bs.prev_quarter("2026.03") == "2025.12"


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f()
            print(f"OK {n}")
    print("전체 통과")
