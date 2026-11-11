"""'튀는 차트' 판정 규칙 — 전부 순수 함수(네트워크·파일 없음). 임계값은 TH 한 곳.

원칙(매크로 데스크·수급 모듈과 같다):
  - 판정은 규칙으로만 한다. 생성형 모델이 '의미 있다'를 고르지 않는다.
  - 모르는 값은 '없음'으로 바꿔 읽지 않는다 — 표본이 모자라면 그 규칙은 그냥 침묵(30번 교훈).
  - 이유(reason)마다 score 를 둬 페이지가 큰 것부터 보여준다. score = |값| / 임계값 (1 이상이면 켜진 것).
"""
from __future__ import annotations

import math
from datetime import date, timedelta

TH = {
    "ret_1w": 0.08,         # 종목 1주 등락(절대값). 8% 는 코스피 종목 주간 변동의 상위 ~5% 수준
    "ret_1w_index": 0.06,   # 묶음 지수·시장 지수는 분산돼 덜 움직이므로 낮게
    "z_1w": 2.0,            # 1주 수익률의 z — 직전 52주 '비중복' 주간수익률 대비. 표본 26주 미만이면 판정 안 함
    "z_min_n": 26,
    "hi_lo_days": 252,      # 52주 신고가·신저가 창(거래일)
    "flow_mcap": 0.005,     # 외인/기관 1주 순매수 ÷ 시총 — 0.5% 면 시총 10조 종목에 500억
    "flow_z": 2.0,          # 1주 순매수의 z — 직전 주간 순매수 분포 대비(표본 26주 이상)
    "flow_min_abs": 50,     # 억원 — 이보다 작은 순매수는 비율이 커도 안 꼽는다(소형주 잡음)
    "cons_1w": 0.05,        # 영업이익 컨센 1주 변화율(11/11 실측: 3% 면 실적시즌에 16사 중 10사가 걸린다)
    "cons_1m": 0.15,        # 1개월 변화율
    "er30": 60,             # |ER(30일)| — 상향−하향이 애널 수의 60% 이상
    "eps_1m": 0.08,         # 컨센 EPS 1개월 변화율(실적시즌 5% 는 흔하다)
    "eps_3m": 0.15,
    "score_cap": 8.0,       # 이유 하나의 score 상한 — EPS 가 0 근처면 변화율이 수천 % 로 터져 정렬을 독차지한다
    "er_wow": 40,           # ER(30일) 한 주 변화(pp)
    "er_min_n": 3,          # 애널 3명 미만은 1건에 ±100 이 튀므로 제외
}


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def pct(a, b):
    """a/b − 1. 분모가 0·없음이면 None."""
    a, b = _f(a), _f(b)
    if a is None or b is None or b == 0:
        return None
    return a / b - 1


def weekly_returns(closes, n=5, weeks=52):
    """마지막 종가에서 거꾸로 n 거래일씩 끊은 비중복 주간수익률 — [이번 주, 지난주, …] 순."""
    c = [_f(x) for x in closes]
    out = []
    i = len(c) - 1
    for _ in range(weeks + 1):
        j = i - n
        if j < 0:
            break
        r = pct(c[i], c[j])
        if r is None:
            break
        out.append(r)
        i = j
    return out


def zscore(x, hist, min_n=None):
    """x 의 z(hist 평균·표본표준편차 대비). 표본이 모자라거나 분산이 0 이면 None."""
    min_n = TH["z_min_n"] if min_n is None else min_n
    h = [v for v in (_f(v) for v in hist) if v is not None]
    if x is None or len(h) < min_n:
        return None
    m = sum(h) / len(h)
    var = sum((v - m) ** 2 for v in h) / (len(h) - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return None
    return (x - m) / sd


def _fmt_pct(v, digits=1):
    s = f"{v * 100:+.{digits}f}%"
    return s


def price_flags(closes, is_index=False):
    """종가 리스트(오름차순, 마지막 = 최신) → (reasons, metrics).
    reasons = [{"text", "score", "kind"}], metrics = {"r1w", "z1w", "hi52", "lo52"}."""
    c = [_f(x) for x in closes]
    c = [x for x in c if x is not None]
    reasons = []
    m = {"r1w": None, "z1w": None, "hi52": False, "lo52": False}
    wk = weekly_returns(c)
    if not wk:
        return reasons, m
    r1w = wk[0]
    m["r1w"] = r1w
    th = TH["ret_1w_index"] if is_index else TH["ret_1w"]
    z = zscore(r1w, wk[1:])
    m["z1w"] = z
    # 등락 임계와 z 임계가 같이 걸리면 이유 하나로 합친다(같은 숫자를 두 줄로 적지 않는다)
    big = abs(r1w) >= th
    odd = z is not None and abs(z) >= TH["z_1w"]
    if big or odd:
        reasons.append({"kind": "ret" if big else "z",
                        "score": max(abs(r1w) / th if big else 0, abs(z) / TH["z_1w"] if odd else 0),
                        "text": f"1주 {_fmt_pct(r1w)}" + (f" — 직전 {len(wk) - 1}주 대비 z {z:+.1f}" if odd else "")})
    n = TH["hi_lo_days"]
    if len(c) >= int(n * 0.8):
        win = c[-n:]
        last5 = c[-5:]
        if max(last5) >= max(win):
            m["hi52"] = True
            reasons.append({"kind": "hi52", "score": 1.0, "text": "이번 주 52주 신고가"})
        if min(last5) <= min(win):
            m["lo52"] = True
            reasons.append({"kind": "lo52", "score": 1.0, "text": "이번 주 52주 신저가"})
    return cap(reasons), m


def rank_change(lines):
    """[(이름, 5거래일 전 수준, 지금 수준)] → 1위가 바뀌었으면 reason, 아니면 None."""
    prev = [(v0, n) for n, v0, v1 in lines if v0 is not None]
    now = [(v1, n) for n, v0, v1 in lines if v1 is not None]
    if len(prev) < 2 or len(now) < 2:
        return None
    a, b = max(prev)[1], max(now)[1]
    if a != b:
        return {"kind": "rank", "score": 1.0, "text": f"이번 주 선두 교체: {a} → {b}"}
    return None


def flow_flags(mc, cum, label, n=5):
    """누적 순매수(억원, 오름차순)와 시총(억원) → reasons. label = '외인'|'기관'."""
    cum = [_f(x) for x in cum]
    mc = [_f(x) for x in mc]
    reasons = []
    if len(cum) <= n or cum[-1] is None or cum[-1 - n] is None:
        return reasons, None
    wk = cum[-1] - cum[-1 - n]
    mcap = mc[-1] if mc and mc[-1] else None
    if abs(wk) < TH["flow_min_abs"]:
        return reasons, wk
    if mcap:
        ratio = wk / mcap
        if abs(ratio) >= TH["flow_mcap"]:
            reasons.append({"kind": "flow", "score": abs(ratio) / TH["flow_mcap"],
                            "text": f"{label} 1주 순매수 {wk:+,.0f}억 (시총의 {ratio * 100:+.2f}%)"})
    # 직전 주간 순매수 분포 대비 z
    hist = []
    i = len(cum) - 1 - n
    while i - n >= 0 and cum[i] is not None and cum[i - n] is not None:
        hist.append(cum[i] - cum[i - n])
        i -= n
    z = zscore(wk, hist)
    if z is not None and abs(z) >= TH["flow_z"]:
        reasons.append({"kind": "flowz", "score": abs(z) / TH["flow_z"],
                        "text": f"{label} 1주 순매수 {wk:+,.0f}억 — 직전 {len(hist)}주 대비 z {z:+.1f}"})
    if hist and abs(wk) > max(abs(h) for h in hist):
        reasons.append({"kind": "flowmax", "score": 1.2, "text": f"{label} 1주 순매수 {wk:+,.0f}억 — 1년 중 최대"})
    # 1년 누적선의 부호 전환(이번 주에 0 선을 넘음)
    a, b = cum[-1 - n], cum[-1]
    if a * b < 0 and mcap and abs(b) >= mcap * 0.001:
        reasons.append({"kind": "flip", "score": 1.0,
                        "text": f"{label} 1년 누적 순매수 {'(−)→(+)' if b > 0 else '(+)→(−)'} 전환"})
    return cap(reasons), wk


def _parse_date(s):
    return date.fromisoformat(str(s)[:10])


def consensus_flags(points, label):
    """[(snapshot_date 'YYYY-MM-DD', 영업이익)] 오름차순 → reasons. label = '4Q26E' 등 표시용."""
    pts = [(_parse_date(d), _f(v)) for d, v in points]
    pts = [(d, v) for d, v in pts if v is not None]
    reasons = []
    if len(pts) < 2:
        return reasons, {}
    d1, v1 = pts[-1]
    ref = [(d, v) for d, v in pts if d <= d1 - timedelta(days=6)]
    ref_m = [(d, v) for d, v in pts if d <= d1 - timedelta(days=28)]
    m = {"d": d1.isoformat(), "v": v1}
    if ref:
        d0, v0 = ref[-1]
        m["w"] = {"d": d0.isoformat(), "v": v0}
        if v0 != 0 and v1 * v0 < 0:
            reasons.append({"kind": "flip", "score": 2.0,
                            "text": f"{label} {'흑자 전환' if v1 > 0 else '적자 전환'} ({v0:,.0f} → {v1:,.0f}억)"})
        else:
            r = pct(v1, v0)
            if r is not None and abs(r) >= TH["cons_1w"]:
                reasons.append({"kind": "cons1w", "score": abs(r) / TH["cons_1w"],
                                "text": f"{label} 1주 {_fmt_pct(r)} ({v0:,.0f} → {v1:,.0f}억)"})
    if ref_m:
        d0, v0 = ref_m[-1]
        m["m"] = {"d": d0.isoformat(), "v": v0}
        r = pct(v1, v0)
        if r is not None and v1 * v0 > 0 and abs(r) >= TH["cons_1m"]:
            reasons.append({"kind": "cons1m", "score": abs(r) / TH["cons_1m"],
                            "text": f"{label} 1개월 {_fmt_pct(r)} ({v0:,.0f} → {v1:,.0f}억)"})
    return cap(reasons), m


def er_flags(row, prev=None):
    """ER CSV 한 행(dict, 문자열 값) + 5일 이상 전 같은 종목·기간 행 → reasons."""
    reasons = []
    n = _f(row.get("n_analysts"))
    if n is None or n < TH["er_min_n"]:
        return reasons
    er30 = _f(row.get("er30"))
    if er30 is not None and abs(er30) >= TH["er30"]:
        reasons.append({"kind": "er30", "score": abs(er30) / TH["er30"],
                        "text": f"ER(30일) {er30:+.0f} (애널 {n:.0f}명)"})
    cur = _f(row.get("eps_cur"))
    for key, base_key, th, label in (("eps_chg_1m", "eps_30d", TH["eps_1m"], "1개월"), ("eps_chg_3m", "eps_90d", TH["eps_3m"], "3개월")):
        e = _f(row.get(key))
        b = _f(row.get(base_key))
        if e is None:
            continue
        if cur is not None and b is not None and cur * b < 0:
            # 부호가 바뀌면 변화율은 뜻이 없다(보잉 0Q −5,526% 실측) → 전환으로 적는다
            reasons.append({"kind": "epsflip", "score": 2.0,
                            "text": f"EPS 컨센 {label} {'흑자' if cur > 0 else '적자'} 전환 ({b:,.2f} → {cur:,.2f})"})
        elif abs(e) >= th:
            reasons.append({"kind": key.replace("eps_chg_", "eps"), "score": abs(e) / th, "text": f"EPS 컨센 {label} {_fmt_pct(e)}"})
    if prev is not None:
        p30 = _f(prev.get("er30"))
        if er30 is not None and p30 is not None and abs(er30 - p30) >= TH["er_wow"]:
            reasons.append({"kind": "erwow", "score": abs(er30 - p30) / TH["er_wow"],
                            "text": f"ER(30일) 한 주 {p30:+.0f} → {er30:+.0f}"})
    return cap(reasons)


def cap(reasons):
    for r in reasons:
        r["score"] = round(min(r["score"], TH["score_cap"]), 2)
    return reasons


def total_score(reasons):
    return round(sum(min(r["score"], TH["score_cap"]) for r in reasons), 2)
