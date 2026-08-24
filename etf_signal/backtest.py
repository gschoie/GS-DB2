# -*- coding: utf-8 -*-
"""신호 유형별 사후 성과 측정.

지금 판에는 신호가 6종류인데 어느 것이 실제로 돈이 됐는지 측정된 적이 없다.
등급 배점(거래대금 25점, 상대강도 20점 …)도 경험칙이라 근거가 필요하다.
이 스크립트는 과거 전 구간에 같은 판정을 재현하고 신호 이후 수익률을 잰다.

측정 방식 — 왜 이렇게 하는지
- 진입은 '신호 다음 봉 종가'. 신호는 전일 확정 종가로 계산되고 다음 날 아침에
  받아보므로, 신호 당일 종가로 사는 것은 불가능한 수익을 계산하는 셈이다.
- 모든 수치는 '같은 기간 아무 날이나 산 경우'(기준선)와 함께 본다. 상승장에서는
  아무 신호나 +로 나오기 때문에, 기준선을 넘지 못하면 그 신호는 값이 없다.
- 초과수익(신호 − 기준선)이 실제 판단 근거다.

한계 (결과 해석 시 반드시 감안)
- 수급 필터(개인몰림·쌍끌이)는 과거 재현이 안 된다. KIS 투자자별 API가 최근
  구간만 주기 때문이다. 따라서 여기서 재는 것은 '필터 전 원신호'다.
- 지금 유니버스에 살아있는 종목만 본다(생존 편향). 상장폐지·제외 종목은 빠진다.
- 거래비용·슬리피지 미반영. 구간이 겹쳐 표본이 독립이 아니므로 통계적 유의성은
  과대평가되기 쉽다 — 표본 수(N)를 같이 보고 작은 N은 신뢰하지 말 것.
"""
from __future__ import annotations
import os, sys, json, time
from datetime import datetime

import numpy as np
import pandas as pd

import etf_signal as E

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "backtest_result.json")
HORIZONS = (5, 20)        # 거래일 기준 보유기간
FETCH_DAYS = 1100         # 약 3년 — 신호 표본을 충분히 확보

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def indicators(px):
    """전 구간 지표와 신호를 벡터로 계산. scan_one과 같은 함수를 쓴다."""
    adx, pdi, ndi = E.adx_di(px)
    sk, sd = E.stoch_slow(px)
    ev = E.cross_events(adx, pdi, ndi, sk, sd)

    tv = px["c"] * px["v"]
    vol_ratio = tv / tv.shift(1).rolling(20).mean()
    hi = px["c"].rolling(250, min_periods=60).max()
    lo = px["c"].rolling(250, min_periods=60).min()
    from_high = (px["c"] / hi - 1) * 100
    from_low = (px["c"] / lo - 1) * 100

    return {
        "ev": ev,
        "up_trend": (pdi > ndi) & (adx > 20),
        "down_trend": (pdi < ndi) & (adx > 20),
        "vol_surge": vol_ratio >= E.VOL_SURGE_X,
        "near_high": from_high >= -E.NEAR_HIGH_PCT,
        "near_low": from_low <= E.NEAR_HIGH_PCT,
    }


def forward(px, h):
    """진입 = 신호 다음 봉 종가, 청산 = 그로부터 h 거래일 뒤 종가.

    shift(-1)로 진입가를 다음 봉으로 밀어 '신호 당일 종가 매수'라는 불가능한
    가정을 피한다. 마지막 구간은 미래가 없어 NaN이 되고 집계에서 빠진다."""
    entry = px["c"].shift(-1)
    exit_ = px["c"].shift(-1 - h)
    return (exit_ / entry - 1) * 100


def agg(vals):
    v = pd.Series(vals).dropna()
    if v.empty:
        return None
    return {"n": int(v.size), "mean": round(float(v.mean()), 2),
            "median": round(float(v.median()), 2),
            "win": round(float((v > 0).mean() * 100), 1)}


def run(days=FETCH_DAYS, sleep=0.15):
    uni = E.load_universe()
    # 신호 유형 → 각 종목에서 그 신호가 난 봉의 마스크를 만드는 함수
    SIGNALS = {
        "추세골든(+DI↑)":      lambda I: I["ev"]["trend"],
        "과매도반등(%K↑<25)":  lambda I: I["ev"]["oversold"],
        "추세데드(+DI↓)":      lambda I: I["ev"]["trend_dead"],
        "과열이탈(%K↓>75)":    lambda I: I["ev"]["overbought"],
        "ADX20 돌파":          lambda I: I["ev"]["adx20"],
        "ADX25 돌파":          lambda I: I["ev"]["adx25"],
        # 확인 지표가 붙었을 때 — 등급 배점의 근거가 되는지 확인용
        "과매도반등+거래대금":  lambda I: I["ev"]["oversold"] & I["vol_surge"],
        "추세골든+거래대금":    lambda I: I["ev"]["trend"] & I["vol_surge"],
        "추세골든+상승추세":    lambda I: I["ev"]["trend"] & I["up_trend"],
        "과열이탈-강한상승제외": lambda I: I["ev"]["overbought"] & ~(I["up_trend"] & I["near_high"]),
        "과열이탈(강한상승중)":  lambda I: I["ev"]["overbought"] & (I["up_trend"] & I["near_high"]),
    }
    buckets = {k: {h: [] for h in HORIZONS} for k in SIGNALS}
    base = {h: [] for h in HORIZONS}            # 기준선: 아무 날이나 산 경우
    meta = {"symbols": 0, "errors": [], "span": None}

    for i, u in enumerate(uni, 1):
        try:
            px = E.fetch_ohlc(u["code"], days=days)
            if len(px) < 300:
                raise ValueError(f"봉 부족({len(px)})")
            I = indicators(px)
            fwd = {h: forward(px, h) for h in HORIZONS}
            for h in HORIZONS:
                base[h] += list(fwd[h].dropna())
            for name, fn in SIGNALS.items():
                m = fn(I).fillna(False)
                for h in HORIZONS:
                    buckets[name][h] += list(fwd[h][m].dropna())
            meta["symbols"] += 1
            d0, d1 = px["date"].iloc[0], px["date"].iloc[-1]
            meta["span"] = [d0.strftime("%Y-%m-%d"), d1.strftime("%Y-%m-%d")]
            print(f"  [{i}/{len(uni)}] {u['name']} {len(px)}봉")
        except Exception as e:
            meta["errors"].append({"name": u["name"], "err": str(e)[:100]})
            print(f"  [{i}/{len(uni)}] ERR {u['name']}: {str(e)[:70]}")
        time.sleep(sleep)

    result = {"generated_at": datetime.now(E.KST).strftime("%Y-%m-%d %H:%M"),
              "horizons": list(HORIZONS), "meta": meta,
              "baseline": {h: agg(base[h]) for h in HORIZONS},
              "signals": {}}
    for name in SIGNALS:
        row = {}
        for h in HORIZONS:
            a = agg(buckets[name][h])
            if a and result["baseline"][h]:
                a["excess"] = round(a["mean"] - result["baseline"][h]["mean"], 2)
                a["win_vs_base"] = round(a["win"] - result["baseline"][h]["win"], 1)
            row[h] = a
        result["signals"][name] = row
    return result


def render(r):
    b = r["baseline"]
    lines = [f"\n기간 {r['meta']['span'][0]} ~ {r['meta']['span'][1]} · "
             f"종목 {r['meta']['symbols']}개 · 에러 {len(r['meta']['errors'])}",
             "진입 = 신호 다음 봉 종가 (신호 당일 매수는 불가능하므로)", ""]
    for h in r["horizons"]:
        lines.append(f"[기준선] 아무 날이나 매수 D+{h}: 평균 {b[h]['mean']:+.2f}% · "
                     f"승률 {b[h]['win']:.1f}% (N={b[h]['n']:,})")
    lines.append("")
    head = f"{'신호':24}" + "".join(f"{'D+'+str(h):>28}" for h in r["horizons"])
    lines += [head, "-" * len(head)]
    for name, row in r["signals"].items():
        cells = ""
        for h in r["horizons"]:
            a = row[h]
            cells += (f"{a['mean']:+6.2f}% 초과{a['excess']:+6.2f}%p 승{a['win']:4.1f}% N{a['n']:>5}"
                      if a else f"{'표본없음':>28}")
        lines.append(f"{name:24}" + cells)
    lines += ["", "※ 초과 = 신호 평균 − 기준선 평균. 0 이하면 그 신호는 값이 없다.",
              "※ 수급 필터는 과거 재현 불가 — 여기 수치는 '필터 전 원신호' 기준.",
              "※ 생존 편향·거래비용 미반영, 구간 중첩으로 표본 비독립."]
    return "\n".join(lines)


if __name__ == "__main__":
    res = run(days=int(os.getenv("BT_DAYS", FETCH_DAYS)))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(render(res))
    print(f"\n결과 저장: {OUT}")
