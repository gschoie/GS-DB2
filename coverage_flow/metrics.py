# -*- coding: utf-8 -*-
"""커버리지 수급 대시보드의 계산부 — 네트워크 없이 순수 함수만.

세 꼭지 + 액티브 ETF 한 줄:
  ① 외인·기관 순매수(5일 합산, 시총 대비 %, 연속일수, 오늘 잠정)
  ② 기계적 수급 — 섹터 ETF 설정·환매(상장주수 변동) × 종목 비중 = 패시브 매매 추정(하한값)
     + 액티브 ETF 계약수 변동(etf_holdings/changes.json)
  ③ 과매수·과매도 — RSI(14, Wilder) + 1년 백분위 + 52주 위치

규칙 기반 상태값이며 검증 전이다(화면·텔레에 그대로 적는다).
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
RSI_N = 14
FLOW_DAYS = 5          # 순매수 합산 창(거래일)
ADV_DAYS = 20          # 평균 거래대금 창
PCTL_DAYS = 252        # RSI 1년 백분위 창
EXTREME_PCTL = 5       # 1년 하위/상위 5% 안이면 '극단'
RSI_LO, RSI_HI = 30, 70

# ── 슬롯 ────────────────────────────────────────────────────────
# 10/19 사용자 요청으로 장중 3회(10:00·13:30·15:30) → 장 마감 후 16:00 하루 1회.
# 하루 한 슬롯이라 수동 🔄 수집도 같은 슬롯에 붙는다(히스토리 파일명 공유 = 그날 최신본 유지).
SLOTS = [("16:00", "24:00")]


def decide_slot(now=None):
    """하루 한 슬롯 — 언제 돌아도 16:00 슬롯 소속."""
    return "16:00"


# ── 기술 지표 ────────────────────────────────────────────────────
def rsi(close, n=RSI_N):
    s = pd.Series(close, dtype="float64")
    d = s.diff()
    up = d.clip(lower=0)
    dn = -d.clip(upper=0)
    au = up.ewm(alpha=1 / n, adjust=False).mean()
    ad = dn.ewm(alpha=1 / n, adjust=False).mean()
    rs = au / ad.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    out[(ad == 0) & (au > 0)] = 100.0
    return out


def percentile_of_last(series, window=PCTL_DAYS):
    """마지막 값이 직전 window 개 값 중 몇 % 자리인지(0=최저, 100=최고). 표본 20개 미만이면 None."""
    s = pd.Series(series, dtype="float64").dropna()
    if len(s) < 20:
        return None
    s = s.iloc[-window:]
    cur = s.iloc[-1]
    return float((s < cur).mean() * 100)


def pctl_or(v, default):
    """None 이면 default, 0.0 은 0.0 그대로(`v or default` 는 0.0 을 '없음' 으로 읽는다)."""
    return default if v is None else v


def extreme_label(pctl):
    """'1년 최저권 (하위 1%)' / '1년 최고권 (상위 3%)' / None"""
    if pctl is None:
        return None
    if pctl <= EXTREME_PCTL:
        return f"1년 최저권 (하위 {pctl:.0f}%)"
    if pctl >= 100 - EXTREME_PCTL:
        return f"1년 최고권 (상위 {100 - pctl:.0f}%)"
    return None


def technicals(ohlc, today, price_now=None):
    """일봉 + (있으면) 오늘 현재가 → {rsi, rsi_prev, rsi_pctl, extreme, hi52_pct, lo52_pct, adv20, provisional}.

    오늘 봉이 일봉에 없고 현재가가 있으면 오늘 종가로 붙여 '잠정' RSI 를 낸다.
    확정(전일) RSI 는 rsi_prev 로 따로 둔다 — 장중 숫자는 마감 때 바뀐다.
    """
    df = ohlc.copy()
    if df.empty:
        return {}
    today = pd.Timestamp(today)
    confirmed = df[df["date"] < today]
    provisional = False
    if price_now and (df["date"] == today).sum() == 0:
        df = pd.concat([confirmed, pd.DataFrame([{"date": today, "o": price_now, "h": price_now,
                                                  "l": price_now, "c": price_now, "v": 0, "amt": 0}])],
                       ignore_index=True)
        provisional = True
    elif (df["date"] == today).sum():
        provisional = True
    r_all = rsi(df["c"])
    r_conf = rsi(confirmed["c"]) if len(confirmed) else pd.Series(dtype="float64")
    # 백분위는 확정 RSI 분포 안에서 오늘 값의 자리 — 오늘 값을 분포에 넣으면 자기 자신과 비교한다
    hist = list(r_conf.dropna().iloc[-PCTL_DAYS:]) if len(r_conf) else []
    cur = float(r_all.iloc[-1]) if len(r_all) and not np.isnan(r_all.iloc[-1]) else None
    pctl = None
    if cur is not None and len(hist) >= 20:
        pctl = float((np.array(hist) < cur).mean() * 100)
    year = confirmed.iloc[-PCTL_DAYS:]
    hi52 = float(year["h"].max()) if len(year) else None
    lo52 = float(year["l"].min()) if len(year) else None
    last = price_now or (float(df["c"].iloc[-1]) if len(df) else None)
    adv = float(confirmed["amt"].iloc[-ADV_DAYS:].mean()) if len(confirmed) else None
    return {
        "rsi": None if cur is None else round(cur, 1),
        "rsi_prev": (None if not len(r_conf) or np.isnan(r_conf.iloc[-1]) else round(float(r_conf.iloc[-1]), 1)),
        "rsi_pctl": None if pctl is None else round(pctl, 1),
        "extreme": extreme_label(pctl),
        "hi52_pct": (None if not (hi52 and last) else round((last / hi52 - 1) * 100, 1)),
        "lo52_pct": (None if not (lo52 and last) else round((last / lo52 - 1) * 100, 1)),
        "adv20": None if adv is None or np.isnan(adv) else round(adv, 1),
        "provisional": provisional,
    }


RET_WINDOWS = {"w1": 5, "m1": 21, "m3": 63}      # 거래일 오프셋(건기 브리핑과 같은 규칙)


def returns(ohlc, today, price_now=None, chg_pct=None):
    """등락률 {d1, w1, m1, m3, ytd} (%). 기준가 = 오늘 현재가(장중) 또는 마지막 종가.
    w1/m1/m3 는 거래일 5/21/63 전 종가 대비, ytd 는 전년 마지막 종가 대비.
    d1 은 KIS 전일대비(chg_pct)를 그대로 쓴다 — 장중엔 현재가/전일종가, 휴장일엔 마지막 종가의 전일대비.
    과거 봉이 모자라면 그 칸만 None."""
    if ohlc is None or ohlc.empty:
        return {}
    today = pd.Timestamp(today)
    conf = ohlc[ohlc["date"] < today]
    closes = list(conf["c"])
    dates = list(conf["date"])
    if price_now:
        closes.append(float(price_now)); dates.append(today)
    elif (ohlc["date"] == today).sum():
        row = ohlc[ohlc["date"] == today].iloc[-1]
        closes.append(float(row["c"])); dates.append(today)
    if not closes:
        return {}
    last = closes[-1]
    out = {"d1": None if chg_pct is None else round(float(chg_pct), 2)}
    if out["d1"] is None and len(closes) >= 2 and closes[-2]:
        out["d1"] = round((last / closes[-2] - 1) * 100, 2)
    for k, n in RET_WINDOWS.items():
        out[k] = round((last / closes[-1 - n] - 1) * 100, 2) if len(closes) > n and closes[-1 - n] else None
    prev_year = [c for c, d in zip(closes, dates) if d.year < today.year]
    out["ytd"] = round((last / prev_year[-1] - 1) * 100, 2) if prev_year and prev_year[-1] else None
    return out


SPARK_DAYS = 63


def spark_points(ohlc, today, price_now=None, n=SPARK_DAYS):
    """등락률 표의 3개월 미니 차트용 종가 n개(오름차순). 장중이면 오늘 현재가를 끝에 붙인다."""
    if ohlc is None or ohlc.empty:
        return []
    today = pd.Timestamp(today)
    closes = [float(x) for x in ohlc[ohlc["date"] < today]["c"] if x == x]
    if price_now:
        closes.append(float(price_now))
    elif (ohlc["date"] == today).sum():
        closes.append(float(ohlc[ohlc["date"] == today].iloc[-1]["c"]))
    return [round(x, 2) for x in closes[-n:]]


FLOW_WINDOWS = {"d5": 5, "m1": 21, "m3": 63}


def flow_windows(inv, today):
    """투자자별 구간 합산(억원) {"frgn":{today,d5,m1,m3,ytd}, "inst":…, "indiv":…, "rows": n}.
    창은 오늘 잠정 행 포함 최근 n행. 행이 모자라면 그 칸은 None(합산이 '작게' 나오는 것보다
    빈칸이 낫다 — 30번 교훈). ytd 는 전년도 행이 하나라도 있어 연초가 덮일 때만."""
    out = {"rows": 0}
    if inv is None or inv.empty:
        return out
    today = pd.Timestamp(today)
    inv = inv[inv["date"] <= today]
    has_today = bool((inv["date"] == today).sum())
    out["rows"] = int(len(inv))
    covers_year = bool((inv["date"].dt.year < today.year).any())
    for who, col in (("frgn", "외국인"), ("inst", "기관"), ("indiv", "개인")):
        w = {"today": round(float(inv.iloc[-1][col]), 1) if has_today else None}
        for k, nrow in FLOW_WINDOWS.items():
            w[k] = round(float(inv[col].iloc[-nrow:].sum()), 1) if len(inv) >= nrow else None
        w["ytd"] = round(float(inv[inv["date"].dt.year == today.year][col].sum()), 1) if covers_year else None
        out[who] = w
    return out


def drop_today(inv, today):
    """장이 아직 안 열렸는데(live=False) 소스가 '오늘' 행을 0으로 미리 내주면 버린다.
    10/19 05:57 실측: 한투 inquire-investor 가 당일 행을 0 으로 주어 '오늘 0' 이 찍히고
    5일 창의 하루를 잡아먹었다. 거짓 0 은 빈칸보다 나쁘다(30번 교훈)."""
    if inv is None or inv.empty:
        return inv
    return inv[inv["date"] < pd.Timestamp(today)].reset_index(drop=True)


# ── 수급 ────────────────────────────────────────────────────────
def streak(vals):
    """최근 값부터 같은 부호가 며칠 이어졌나(+n 순매수, −n 순매도). 0 이면 0."""
    n = 0
    vals = [v for v in vals][::-1]
    if not vals or vals[0] == 0 or pd.isna(vals[0]):
        return 0
    sign = 1 if vals[0] > 0 else -1
    for v in vals:
        if pd.isna(v) or ((v > 0) - (v < 0)) != sign:
            break
        n += 1
    return n * sign


def flow_summary(inv, today, mcap, days=FLOW_DAYS):
    """투자자별 일별(억원) → 5일 합산·시총 대비·연속일수·오늘(잠정).

    5일 창은 **오늘 잠정 포함** 최근 5행이다(장중 3회 발송이라 오늘을 빼면 10시·13시반·
    15시반 메시지가 전부 같아진다). 오늘 행이 없으면(장 시작 전·휴장) 확정 5일이다.
    """
    if inv is None or inv.empty:
        return {}
    today = pd.Timestamp(today)
    inv = inv[inv["date"] <= today]
    has_today = bool((inv["date"] == today).sum())
    win = inv.iloc[-days:]
    f5, o5, p5 = float(win["외국인"].sum()), float(win["기관"].sum()), float(win["개인"].sum())
    out = {
        "frgn5": round(f5, 1), "inst5": round(o5, 1), "indiv5": round(p5, 1),
        "fi5": round(f5 + o5, 1),
        "fi5_mcap_pct": (round((f5 + o5) / mcap * 100, 2) if mcap else None),
        "frgn_streak": streak(inv["외국인"]), "inst_streak": streak(inv["기관"]),
        "has_today": has_today, "days": int(len(win)),
        "window": [d.strftime("%m/%d") for d in win["date"]],
    }
    if has_today:
        t = inv.iloc[-1]
        out.update(frgn_today=round(float(t["외국인"]), 1), inst_today=round(float(t["기관"]), 1),
                   indiv_today=round(float(t["개인"]), 1))
    out["win"] = flow_windows(inv, today)
    return out


def rank_flow(rows, n=3):
    """시총 대비 5일 외인+기관 순매수 % 기준 사는 쪽 상위 n · 파는 쪽 하위 n."""
    ok = [r for r in rows if r.get("flow", {}).get("fi5_mcap_pct") is not None]
    ok.sort(key=lambda r: r["flow"]["fi5_mcap_pct"], reverse=True)
    buy = [r for r in ok[:n] if r["flow"]["fi5_mcap_pct"] > 0]
    sell = [r for r in ok[::-1][:n] if r["flow"]["fi5_mcap_pct"] < 0]
    return buy, sell


def today_movers(rows, n=3):
    """오늘 잠정 외인/기관 순매수 절대값 상위 n — '오늘: 한국콜마 기관 -165' 줄."""
    items = []
    for r in rows:
        f = r.get("flow", {})
        if not f.get("has_today"):
            continue
        for who, key in (("외인", "frgn_today"), ("기관", "inst_today")):
            v = f.get(key)
            if v is not None and abs(v) >= 1:
                items.append((r["name"], who, v))
    items.sort(key=lambda x: abs(x[2]), reverse=True)
    return items[:n]


# ── 기계적 수급(패시브) ──────────────────────────────────────────
def passive_flow(etfs, prev_shares):
    """섹터 ETF 설정·환매 × 종목 비중 → 종목별 추정 매매(억원).

    etfs: [{code, name, listed(상장주수), price, holdings:[{code, weight(%)}]}]
    prev_shares: {etf_code: 직전 저장 상장주수}
    반환 {stock_code: {"amt": 억원, "etfs": [(etf명, 억원)]}} 와 ETF별 설정·환매 요약.
    직전 값이 없는 ETF 는 건너뛴다(첫 수집은 '다음 수집부터'). 비중은 Top10 만 있으므로
    **하한값**이다 — 비중 밖 종목의 몫은 잡히지 않는다.
    """
    per_stock, per_etf = {}, []
    for e in etfs:
        prev = prev_shares.get(e["code"])
        listed, price = e.get("listed"), e.get("price")
        base = {"code": e["code"], "name": e.get("name", ""), "listed": listed,
                "inflow_1d": e.get("inflow_1d"), "inflow_1w": e.get("inflow_1w"), "inflow_ref": e.get("inflow_ref", "")}
        if not prev or not listed or not price:
            per_etf.append({**base, "delta_shares": None, "amt": None})
            continue
        d_sh = listed - prev
        amt_total = d_sh * price / 1e8
        per_etf.append({**base, "delta_shares": d_sh, "amt": round(amt_total, 1), "prev": prev})
        for h in e.get("holdings", []):
            w = h.get("weight") or 0
            if not h.get("code") or not w:
                continue
            a = amt_total * w / 100
            s = per_stock.setdefault(h["code"], {"amt": 0.0, "etfs": []})
            s["amt"] += a
            s["etfs"].append((e.get("name", ""), round(a, 1)))
    for s in per_stock.values():
        s["amt"] = round(s["amt"], 1)
        s["etfs"].sort(key=lambda x: abs(x[1]), reverse=True)
    return per_stock, per_etf


def parse_eok(s):
    """네이버 금액 문자열 → 억원 float. '1조 1,560억'→11560, '-99.2억'→-99.2, '-1,536억'→-1536. 못 읽으면 None."""
    if s is None:
        return None
    t = str(s).replace(",", "").replace(" ", "").strip()
    if not t or t in ("-", "–"):
        return None
    sign = -1 if t.startswith("-") else 1
    t = t.lstrip("+-")
    total, ok = 0.0, False
    import re as _re
    m = _re.match(r"^(?:(\d+(?:\.\d+)?)조)?(?:(\d+(?:\.\d+)?)억)?$", t)
    if not m or not (m.group(1) or m.group(2)):
        return None
    if m.group(1):
        total += float(m.group(1)) * 10000
    if m.group(2):
        total += float(m.group(2))
    return sign * total


def adv_pct(amt, adv20):
    """패시브 금액을 20일 평균 거래대금 대비 % 로. ADV 를 모르면 None."""
    if amt is None or not adv20:
        return None
    return round(amt / adv20 * 100, 1)


def passive_label(adv):
    if adv is None:
        return ""
    a = abs(adv)
    size = "큼" if a >= 20 else ("" if a >= 3 else "미미")
    side = "순매수" if adv > 0 else "순매도"
    return f"패시브 {side}{(' ' + size) if size else ''}"


# ── 액티브 ETF ───────────────────────────────────────────────────
def active_etf_hits(changes, universe_codes):
    """etf_holdings/changes.json → 유니버스 종목이 걸린 액티브 ETF 매매만.
    [{etf, stock_code, stock, kind(편입/제외/증가/감소), pct, weight}]"""
    hits = []
    for e in (changes or {}).get("etfs", []):
        label = e.get("label", e.get("code", ""))
        for h in e.get("new", []):
            if h.get("code") in universe_codes:
                hits.append({"etf": label, "stock_code": h["code"], "stock": h.get("name", ""),
                             "kind": "편입", "pct": None, "weight": h.get("weight")})
        for h in e.get("gone", []):
            if h.get("code") in universe_codes:
                hits.append({"etf": label, "stock_code": h["code"], "stock": h.get("name", ""),
                             "kind": "제외", "pct": None, "weight": h.get("weight_prev")})
        for h in e.get("moves", []):
            if h.get("code") in universe_codes:
                p = h.get("active_share_pct")
                hits.append({"etf": label, "stock_code": h["code"], "stock": h.get("name", ""),
                             "kind": "증가" if (p or 0) > 0 else "감소", "pct": p, "weight": h.get("weight_now")})
    hits.sort(key=lambda x: abs(x["pct"] or 999), reverse=True)
    return hits


# ── 포맷 ────────────────────────────────────────────────────────
def signed(v, nd=0):
    if v is None:
        return "–"
    s = f"{v:+,.{nd}f}"
    return s


def streak_text(f):
    bits = []
    fs, os_ = f.get("frgn_streak", 0), f.get("inst_streak", 0)
    if abs(fs) >= 3:
        bits.append(f"외인 {abs(fs)}일째 {'순매수' if fs > 0 else '순매도'}")
    if abs(os_) >= 3:
        bits.append(f"기관 {abs(os_)}일째 {'순매수' if os_ > 0 else '순매도'}")
    return bits
