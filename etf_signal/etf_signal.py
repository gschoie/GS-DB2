# -*- coding: utf-8 -*-
"""55개 ETF 신호 스캔 엔진.
- 일봉(ADX/DI, Stochastic Slow) + 수급(외인/기관/개인 5일) + 거래대금(유동성)
- '오늘 새로 뜬' 크로스오버를 이벤트로 표시 (마지막 2봉 비교 → 상태파일 불필요)
- 골든크로스(매수)와 데드크로스(매도) 양방향을 모두 감지
- 신호는 '전일 확정 종가' 기준: 오늘(미완성) 봉은 제외
결과: signals.json  (HTML/텔레그램이 이 파일을 읽음)
"""
from __future__ import annotations
import os, json, time, csv, requests
import pandas as pd, numpy as np
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
KST = timezone(timedelta(hours=9))
BASE = "https://openapi.koreainvestment.com:9443"
LIQ_MIN_EOK = 5          # 20일 평균 거래대금 5억 미만 = 저유동성(알림 제외)
OVERSOLD = 25            # Stochastic 과매도 기준(골든크로스 직전 %K)
OVERBOUGHT = 75          # Stochastic 과열 기준(데드크로스 직전 %K)
ADX_LV1 = 20             # 추세 확립: ADX 상향돌파 → '확인' 신호
ADX_LV2 = 25             # 추세 강화: ADX 상향돌파 → '강력' 신호
EPS = 1e-6               # 지표 동률 판정 허용오차(%K·DI 포인트)

# ── 키 로딩: 로컬 .env → 없으면 환경변수(GitHub Actions) ──
def _load_keys():
    p = os.path.join(HERE, ".env")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    return os.environ["KIS_APP_KEY"], os.environ["KIS_APP_SECRET"]

APP_KEY, APP_SECRET = _load_keys()

_c = {"t": None, "ts": 0}
def token():
    if _c["t"] and time.time() - _c["ts"] < 60*60*23:
        return _c["t"]
    r = requests.post(f"{BASE}/oauth2/tokenP",
        json={"grant_type": "client_credentials", "appkey": APP_KEY, "appsecret": APP_SECRET})
    r.raise_for_status()
    _c.update(t=r.json()["access_token"], ts=time.time())
    return _c["t"]

def H(tr):
    return {"authorization": f"Bearer {token()}", "appkey": APP_KEY, "appsecret": APP_SECRET,
            "tr_id": tr, "custtype": "P"}

def _get(url, tr, params, tries=3):
    for k in range(tries):
        try:
            r = requests.get(url, headers=H(tr), params=params, timeout=15)
            r.raise_for_status()
            return r
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(0.7)

def fetch_ohlc(code, days=430):   # 430일 ≈ 290거래일 — YoY(1년 전 대비) 계산분까지
    url = f"{BASE}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    start = (datetime.now(KST) - timedelta(days=days)).strftime("%Y%m%d")
    cur = datetime.now(KST).strftime("%Y%m%d"); rows = []
    for _ in range(8):
        p = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
             "FID_INPUT_DATE_1": start, "FID_INPUT_DATE_2": cur,
             "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0"}
        r = _get(url, "FHKST03010100", p)
        d = [x for x in r.json().get("output2", []) if x.get("stck_bsop_date")]
        if not d: break
        rows += d; old = min(x["stck_bsop_date"] for x in d)
        if old <= start: break
        cur = (datetime.strptime(old, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d"); time.sleep(0.12)
    df = pd.DataFrame(rows).drop_duplicates("stck_bsop_date")
    for a, b in [("o","stck_oprc"),("h","stck_hgpr"),("l","stck_lwpr"),("c","stck_clpr"),("v","acml_vol")]:
        df[a] = pd.to_numeric(df[b], errors="coerce")
    df["date"] = pd.to_datetime(df["stck_bsop_date"])
    df = df[["date","o","h","l","c","v"]].sort_values("date").reset_index(drop=True)
    # 신호는 '전일 확정' 기준 → 오늘(미완성) 봉 제거
    today = pd.Timestamp(datetime.now(KST).date())
    df = df[df["date"] < today].reset_index(drop=True)
    return df

def fetch_flow(code):
    url = f"{BASE}/uapi/domestic-stock/v1/quotations/inquire-investor"
    r = _get(url, "FHKST01010900", {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})
    d = r.json().get("output", [])
    if not d: return pd.DataFrame()
    df = pd.DataFrame(d); df["date"] = pd.to_datetime(df["stck_bsop_date"])
    for a, b in [("개인","prsn_ntby_tr_pbmn"),("외국인","frgn_ntby_tr_pbmn"),("기관","orgn_ntby_tr_pbmn")]:
        df[a] = pd.to_numeric(df[b], errors="coerce") / 100   # 백만원→억원
    today = pd.Timestamp(datetime.now(KST).date())
    df = df[df["date"] < today]
    return df[["date","개인","외국인","기관"]].sort_values("date").reset_index(drop=True)

def adx_di(df, n=14):
    h, l, c = df["h"], df["l"], df["c"]; pc = c.shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    up = h.diff(); dn = -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    ndm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    a = 1/n; atr = tr.ewm(alpha=a, adjust=False).mean()
    pdi = 100*pdm.ewm(alpha=a, adjust=False).mean()/atr
    ndi = 100*ndm.ewm(alpha=a, adjust=False).mean()/atr
    dx = 100*(pdi-ndi).abs()/(pdi+ndi)
    return dx.ewm(alpha=a, adjust=False).mean(), pdi, ndi

def stoch_slow(df, n=14, k=3, d=3):
    ll = df["l"].rolling(n).min(); hh = df["h"].rolling(n).max()
    slowk = (100*(df["c"]-ll)/(hh-ll)).rolling(k).mean()
    return slowk, slowk.rolling(d).mean()

def _ret(px, days_back):
    """기준일 대비 days_back(달력일) 이전 마지막 확정 종가 대비 등락률(%).

    거래일 개수로 세면 휴장일 때문에 종목마다 기준이 어긋난다. 달력으로 거슬러
    올라가 '그 날짜 이전의 마지막 종가'를 쓰면 휴장·상장일 차이에 영향받지 않는다.
    데이터가 그만큼 없으면(신규 상장 등) None."""
    last_d = px["date"].iloc[-1]
    last_c = float(px["c"].iloc[-1])
    prior = px[px["date"] <= last_d - pd.Timedelta(days=days_back)]
    if prior.empty:
        return None
    base = float(prior["c"].iloc[-1])
    if base <= 0:
        return None
    return round((last_c / base - 1) * 100, 2)


def returns(px):
    """1일·주간(WoW)·월간(MoM)·연간(YoY) 등락률(%).

    YoY는 화면에 아직 쓰지 않지만, 지금부터 같이 저장해 이력을 쌓아둔다."""
    prev = float(px["c"].iloc[-2]) if len(px) >= 2 else None
    last = float(px["c"].iloc[-1])
    return {
        "ret_1d": round((last / prev - 1) * 100, 2) if prev else None,
        "ret_1w": _ret(px, 7),
        "ret_1m": _ret(px, 30),
        "ret_1y": _ret(px, 365),
    }


VOL_SURGE_X = 1.5     # 당일 거래대금이 20일 평균의 몇 배면 '급증'으로 볼지
NEAR_HIGH_PCT = 3.0   # 52주 신고가 대비 이 % 이내면 '신고가권'
BB_N, BB_K = 20, 2.0  # 볼린저 밴드 기간·표준편차
SQUEEZE_PCTL = 0.20   # 밴드폭이 최근 120일 중 하위 20%면 '수축'


def volume_ratio(px):
    """당일 거래대금 / 직전 20일 평균 거래대금.

    크로스가 실제 수급을 동반했는지 가르는 확인 지표다. 분모에 당일을 넣으면
    급증분이 평균을 끌어올려 배수가 희석되므로 직전 20일로 계산한다."""
    tv = px["c"] * px["v"]
    if len(tv) < 22:
        return None
    base = float(tv.iloc[-21:-1].mean())
    if base <= 0:
        return None
    return round(float(tv.iloc[-1]) / base, 2)


def high_low_52w(px):
    """52주(≈250거래일) 최고·최저 종가와 현재가의 이격(%).

    강한 추세 종목은 Stochastic이 늘 과열권이라 오실레이터만으로는 잡히지 않는다.
    신고가 근접도는 그 구간을 따로 보여준다. 데이터가 짧으면 있는 만큼만 쓴다."""
    c = px["c"].tail(250)
    if len(c) < 60:
        return None, None, None, None
    hi, lo, last = float(c.max()), float(c.min()), float(c.iloc[-1])
    return (round(hi), round(lo),
            round((last / hi - 1) * 100, 1) if hi > 0 else None,
            round((last / lo - 1) * 100, 1) if lo > 0 else None)


def bollinger(px):
    """밴드폭과 수축·확장 판정.

    변동성이 수축(스퀴즈)한 뒤 확장할 때 큰 움직임이 나오는 경향을 잡는다.
    반환: (밴드폭%, 수축 여부, 확장 전환 여부)"""
    c = px["c"]
    if len(c) < BB_N + 20:
        return None, False, False
    mid = c.rolling(BB_N).mean()
    sd = c.rolling(BB_N).std()
    bw = (2 * BB_K * sd / mid) * 100          # 밴드폭을 중심선 대비 %로
    tail = bw.dropna().tail(120)
    if len(tail) < 30:
        return None, False, False
    thr = float(tail.quantile(SQUEEZE_PCTL))
    now, prev = float(bw.iloc[-1]), float(bw.iloc[-2])
    return round(now, 1), bool(now <= thr), bool(prev <= thr < now)


def flow_streaks(fl):
    """외국인·기관의 연속 순매수(+)/순매도(−) 일수.

    5일 합계는 하루 큰 금액에 좌우된다. 며칠째 같은 방향인지가 지속성을 더 잘 나타낸다."""
    out = {}
    for who, key in (("for", "외국인"), ("org", "기관")):
        n = 0
        if len(fl):
            vals = list(fl[key])[::-1]
            if vals and vals[0] != 0:
                sign = 1 if vals[0] > 0 else -1
                for v in vals:
                    if (v > 0) - (v < 0) != sign:
                        break
                    n += 1
                n *= sign
        out[f"{who}_streak"] = int(n)
    return out


def _cross_up(a, b):
    """a가 b를 상향돌파한 봉(True). 직전 봉은 a<=b, 이번 봉은 a>b."""
    return (a - b > EPS) & (a.shift(1) - b.shift(1) <= EPS)

def _cross_dn(a, b):
    """a가 b를 하향이탈한 봉(True). 상향돌파의 대칭."""
    return _cross_up(b, a)

def _cross_level(a, lv):
    """a가 고정 임계선 lv를 상향돌파한 봉(True). 지표 대 지표가 아닌 대 상수 버전."""
    return (a - lv > EPS) & (a.shift(1) - lv <= EPS)

def cross_events(adx, pdi, ndi, sk, sd):
    """전 구간 크로스 이벤트(bool Series). 마지막 값 = '오늘 새로 뜬' 신호.
    횡보·박스권에서 두 지표가 같은 값에 붙는 구간이 있어, 부동소수점 오차(1e-14 수준)를
    크로스로 오판하지 않도록 EPS 이내 차이는 '같다'로 본다.
    차트 마커(build_history)와 오늘의 알림(scan_one)이 같은 판정을 쓰도록 한 곳에서 계산."""
    up, dn = _cross_up(sk, sd), _cross_dn(sk, sd)
    return {
        "trend": _cross_up(pdi, ndi), "trend_dead": _cross_dn(pdi, ndi),
        "stoch": up, "stoch_dead": dn,
        "oversold": up & (sk.shift(1) < OVERSOLD),
        "overbought": dn & (sk.shift(1) > OVERBOUGHT),
        # 추세 '강도' 이벤트 — DI 교차와 무관하게 ADX가 임계선을 뚫은 날
        "adx20": _cross_level(adx, ADX_LV1),
        "adx25": _cross_level(adx, ADX_LV2),
    }

HIST_N = 120  # 차트용 이력 봉 수

def build_history(px, ev, n=HIST_N):
    """차트용 시계열: 최근 n봉의 (날짜, 종가)와 과거 신호 발생 위치.
    t = +DI가 -DI 상향돌파(추세 골든크로스), s = 과매도권 Stochastic 골든크로스,
    dt = +DI가 -DI 하향이탈(추세 데드크로스), ds = 과열권 Stochastic 데드크로스."""
    m = min(len(px), n)

    def idx(key):
        tail = ev[key].iloc[-m:].reset_index(drop=True)
        return [int(i) for i in tail.index[tail]]

    return {
        "dates": [d.strftime("%Y-%m-%d") for d in px["date"].iloc[-m:]],
        "close": [int(v) for v in px["c"].iloc[-m:]],
        "t": idx("trend"), "s": idx("oversold"),
        "dt": idx("trend_dead"), "ds": idx("overbought"),
    }

def load_universe():
    rows = []
    with open(os.path.join(HERE, "etf_universe.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("active") == "1":
                rows.append({"group": r["group"], "name": r["name"], "code": r["code"]})
    return rows

def scan_one(u):
    px = fetch_ohlc(u["code"]); fl = fetch_flow(u["code"])
    adx, pdi, ndi = adx_di(px); sk, sd = stoch_slow(px)
    turnover = float((px["c"] * px["v"]).tail(20).mean() / 1e8)   # 20일 평균 거래대금(억)
    f5 = fl.tail(5)[["개인","외국인","기관"]].sum() if len(fl) else None

    # 상태
    up_trend = bool(pdi.iloc[-1] > ndi.iloc[-1] and adx.iloc[-1] > 20)
    down_trend = bool(pdi.iloc[-1] < ndi.iloc[-1] and adx.iloc[-1] > 20)
    # 오늘 새로 뜬 크로스오버(마지막 봉) — 골든(매수) / 데드(매도)
    ev = cross_events(adx, pdi, ndi, sk, sd)
    ev_trend = bool(ev["trend"].iloc[-1])
    ev_stoch = bool(ev["stoch"].iloc[-1])
    stoch_oversold = bool(ev["oversold"].iloc[-1])
    ev_trend_dead = bool(ev["trend_dead"].iloc[-1])
    ev_stoch_dead = bool(ev["stoch_dead"].iloc[-1])
    stoch_overbought = bool(ev["overbought"].iloc[-1])
    # 확인 지표 — 크로스가 '진짜'인지 뒷받침하는 근거들
    vol_ratio = volume_ratio(px)
    vol_surge = bool(vol_ratio and vol_ratio >= VOL_SURGE_X)
    hi52, lo52, from_high, from_low = high_low_52w(px)
    near_high = bool(from_high is not None and from_high >= -NEAR_HIGH_PCT)
    near_low = bool(from_low is not None and from_low <= NEAR_HIGH_PCT)
    bb_bw, bb_squeeze, bb_release = bollinger(px)

    # 추세 강도 단계: 1 = ADX 20 돌파(확인), 2 = 25 돌파(강력). 0 = 해당 없음.
    # 하루에 20과 25를 함께 뚫으면(예: 19→26) 더 센 쪽인 2로 본다.
    ev_adx20 = bool(ev["adx20"].iloc[-1])
    ev_adx25 = bool(ev["adx25"].iloc[-1])
    adx_stage = 2 if ev_adx25 else (1 if ev_adx20 else 0)
    # ADX는 방향이 없는 강도 지표 → 방향은 DI로 판정
    adx_up = bool(pdi.iloc[-1] > ndi.iloc[-1])

    if f5 is not None:
        smart = bool(f5["외국인"] > 0 and f5["기관"] > 0)
        antp = bool(f5["개인"] > 0 and f5["외국인"] < 0 and f5["기관"] < 0)
        flow = "쌍끌이" if smart else ("개인몰림" if antp else "중립")
        dist = bool(f5["외국인"] < 0 and f5["기관"] < 0)   # 외인·기관 동반 순매도
    else:
        flow, dist = "수급없음", False

    return {
        "group": u["group"], "name": u["name"], "code": u["code"],
        "close": int(px["c"].iloc[-1]), "asof": px["date"].iloc[-1].strftime("%Y-%m-%d"),
        "adx": round(float(adx.iloc[-1]), 1),
        "pdi": round(float(pdi.iloc[-1]), 1), "ndi": round(float(ndi.iloc[-1]), 1),
        "k": round(float(sk.iloc[-1]), 1), "d": round(float(sd.iloc[-1]), 1),
        "turnover": round(turnover, 1), "liquid": bool(turnover >= LIQ_MIN_EOK),
        "up_trend": up_trend, "down_trend": down_trend,
        "ev_trend": ev_trend, "ev_stoch": ev_stoch, "stoch_oversold": stoch_oversold,
        "ev_trend_dead": ev_trend_dead, "ev_stoch_dead": ev_stoch_dead,
        "stoch_overbought": stoch_overbought,
        "ev_adx20": ev_adx20, "ev_adx25": ev_adx25,
        "adx_stage": adx_stage, "adx_up": adx_up,
        "for5": None if f5 is None else round(float(f5["외국인"])),
        "org5": None if f5 is None else round(float(f5["기관"])),
        "ind5": None if f5 is None else round(float(f5["개인"])),
        "flow": flow, "dist": dist,
        **returns(px), **flow_streaks(fl),
        "vol_ratio": vol_ratio, "vol_surge": vol_surge,
        "hi52": hi52, "lo52": lo52, "from_high": from_high, "from_low": from_low,
        "near_high": near_high, "near_low": near_low,
        "bb_bw": bb_bw, "bb_squeeze": bb_squeeze, "bb_release": bb_release,
        # 매수 알림: 오늘 골든(추세 or 과매도-스토캐스틱) + 개인몰림 아님 + 유동성 OK
        "alert": bool((ev_trend or stoch_oversold) and flow != "개인몰림" and turnover >= LIQ_MIN_EOK),
        # 매도 알림: 오늘 데드(추세 or 과열-스토캐스틱) + 외인·기관 쌍끌이 아님 + 유동성 OK
        # 단, '상승추세 + 신고가권'에서의 과열이탈은 뺀다 — 강한 추세에서 %K는 계속
        # 고점에 머물며 반복 교차해, 추세가 멀쩡한데 매도 경고만 나가는 문제가 있었다
        # (아카이브 28일 기준 과열이탈 19건 중 7건이 상승추세 중 발생).
        # 추세 자체가 꺾인 신호(ev_trend_dead)는 이 예외와 무관하게 그대로 경고한다.
        "strong_up": bool(up_trend and near_high),
        "alert_sell": bool((ev_trend_dead
                            or (stoch_overbought and not (up_trend and near_high)))
                           and flow != "쌍끌이" and turnover >= LIQ_MIN_EOK),
        # 추세 강도 알림: ADX 20/25 상향돌파 + 방향별 수급 필터(상승은 개인몰림, 하락은
        # 쌍끌이 제외) + 유동성 OK. 크로스 알림과 별개 신호이며 같은 날 함께 뜰 수 있다.
        "alert_adx": bool(adx_stage
                          and flow != ("개인몰림" if adx_up else "쌍끌이")
                          and turnover >= LIQ_MIN_EOK),
        "history": build_history(px, ev),
    }

def add_relative_strength(out):
    """유니버스 내 상대강도 백분위(0~100). 스캔이 끝난 뒤 횡단면으로 계산한다.

    '올랐다'보다 '남들보다 더 올랐다'가 섹터 로테이션의 본질이다. 시장지수 대신
    이 56개 ETF 자체를 비교군으로 쓴다 — 실제로 이 안에서 고르기 때문에
    비교군으로 더 적절하고, 지수 API를 새로 붙이지 않아도 된다."""
    for key, out_key in (("ret_1w", "rs_1w"), ("ret_1m", "rs_1m")):
        vals = sorted(x[key] for x in out if x.get(key) is not None)
        for r in out:
            v = r.get(key)
            if v is None or not vals:
                r[out_key] = None
            else:
                below = sum(1 for u in vals if u < v)
                r[out_key] = round(below / len(vals) * 100)


def add_conviction(out):
    """신호의 '뒷받침 근거' 개수를 점수화(0~100)하고 A/B/C 등급을 매긴다.

    신호를 걸러내는 대신 등급을 매기는 쪽을 택했다. 하드 필터는 근거를 남기지 않아
    왜 빠졌는지 알 수 없지만, 등급은 화면에 다 보여주면서 우선순위만 정한다.
    텔레그램은 B 이상만 보내 알림 피로를 줄인다(대시보드에는 전부 표시)."""
    for r in out:
        side_up = bool(r["alert"] or (r.get("alert_adx") and r.get("adx_up")))
        pts, why = 0, []
        if r.get("vol_surge"):
            pts += 25; why.append(f"거래대금 {r['vol_ratio']}배")
        rs = r.get("rs_1m")
        if rs is not None:
            if side_up and rs >= 70:
                pts += 20; why.append(f"상대강도 상위 {100-rs}%")
            elif not side_up and rs <= 30:
                pts += 20; why.append(f"상대강도 하위 {rs}%")
        if side_up and r.get("up_trend"):
            pts += 20; why.append("ADX 상승추세")
        if not side_up and r.get("down_trend"):
            pts += 20; why.append("ADX 하락추세")
        if side_up and r.get("near_high"):
            pts += 15; why.append("52주 신고가권")
        if not side_up and r.get("near_low"):
            pts += 15; why.append("52주 신저가권")
        if r.get("bb_release"):
            pts += 10; why.append("변동성 수축 후 확장")
        st = (r.get("for_streak") or 0) + (r.get("org_streak") or 0)
        if side_up and st >= 4:
            pts += 10; why.append(f"외인·기관 연속 순매수 {st}일")
        if not side_up and st <= -4:
            pts += 10; why.append(f"외인·기관 연속 순매도 {abs(st)}일")
        r["conviction"] = min(pts, 100)
        r["conviction_why"] = why
        r["grade"] = "A" if pts >= 55 else ("B" if pts >= 30 else "C")


def scan_all():
    uni = load_universe()
    out, errs = [], []
    for i, u in enumerate(uni, 1):
        try:
            rec = scan_one(u); out.append(rec)
            mark = "  ★BUY" if rec["alert"] else ""
            mark += "  ▼SELL" if rec["alert_sell"] else ""
            if rec["alert_adx"]:
                mark += f"  ⚡ADX{ADX_LV2 if rec['adx_stage'] == 2 else ADX_LV1}↑"
            print(f"  [{i}/{len(uni)}] OK {u['name']}  ADX{rec['adx']} flow={rec['flow']}{mark}")
        except Exception as e:
            errs.append({"name": u["name"], "code": u["code"], "err": str(e)[:120]})
            print(f"  [{i}/{len(uni)}] ERR {u['name']}: {str(e)[:80]}")
        time.sleep(0.15)
    add_relative_strength(out)
    add_conviction(out)
    payload = {
        "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "signals": out, "errors": errs,
    }
    with open(os.path.join(HERE, "signals.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    n_buy = sum(1 for s in out if s["alert"])
    n_sell = sum(1 for s in out if s["alert_sell"])
    n_adx = sum(1 for s in out if s["alert_adx"])
    print(f"\n스캔 {len(out)}/{len(uni)}개 완료 · 에러 {len(errs)} · "
          f"오늘 매수 {n_buy}개 · 매도 {n_sell}개 · 추세강도 {n_adx}개 → signals.json")
    return payload

if __name__ == "__main__":
    scan_all()
