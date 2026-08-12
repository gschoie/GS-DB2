# -*- coding: utf-8 -*-
"""signals.json → etf_signal_report.html (GS Research Desk 톤 매칭, 자기완결 HTML).
매 실행 시 signals.json을 history/{asof}.json으로 아카이브하고,
과거 일자를 ◀▶ 네비게이션으로 조회 (최근 MAX_DAYS일 임베드)."""
import os, json, glob, html, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
HIST_DIR = os.path.join(HERE, "history")
MAX_DAYS = 15  # 네비게이션으로 볼 수 있는 과거 일수(페이지 용량 상한)
WD = "월화수목금토일"

def esc(s): return html.escape(str(s))

def reasons(s):
    r = []
    if s["ev_trend"]:
        r.append("＋DI가 −DI 상향돌파 · 추세 전환")
    if s["stoch_oversold"]:
        r.append("Stochastic 과매도 반등 · 골든크로스")
    elif s["ev_stoch"]:
        r.append("Stochastic 골든크로스")
    if s["flow"] == "쌍끌이":
        r.append("외인·기관 동반 순매수")
    return r

def reasons_sell(s):
    r = []
    if s.get("ev_trend_dead"):
        r.append("＋DI가 −DI 하향이탈 · 추세 꺾임")
    if s.get("stoch_overbought"):
        r.append("Stochastic 과열 이탈 · 데드크로스")
    elif s.get("ev_stoch_dead"):
        r.append("Stochastic 데드크로스")
    if s.get("dist"):
        r.append("외인·기관 동반 순매도")
    return r

def reasons_adx(s):
    """추세 강도 신호 사유. 20 = 확인, 25 = 강력(더 센 신호)."""
    up = s.get("adx_up")
    dirn = "상승추세" if up else "하락추세"
    r = []
    if s.get("adx_stage") == 2:
        r.append(f"ADX 25 상향돌파 · {dirn} 강화(강력)")
    elif s.get("adx_stage") == 1:
        r.append(f"ADX 20 상향돌파 · {dirn} 확립(확인)")
    if up and s.get("flow") == "쌍끌이":
        r.append("외인·기관 동반 순매수")
    if not up and s.get("dist"):
        r.append("외인·기관 동반 순매도")
    return r

def flow_badge(flow):
    m = {"쌍끌이": ("쌍끌이 ↑", "b-buy"), "개인몰림": ("개인몰림 ⚠", "b-warn"),
         "중립": ("중립", "b-mut"), "수급없음": ("–", "b-mut")}
    label, cls = m.get(flow, (flow, "b-mut"))
    return f'<span class="badge {cls}">{esc(label)}</span>'

def trend_badge(s):
    if s["up_trend"]:
        return f'<span class="badge b-buy">▲ 상승추세</span>'
    if s.get("down_trend"):
        return f'<span class="badge b-down">▼ 하락추세</span>'
    if s["pdi"] < s["ndi"]:
        return f'<span class="badge b-down">▽ 하락</span>'
    return f'<span class="badge b-mut">– 중립</span>'

def sv(v):
    """정렬용 data-v: None은 nan으로(항상 맨 아래로 밀림)."""
    return "nan" if v is None else v

def num(v):
    if v is None: return '<span class="mut">–</span>'
    sign = "+" if v > 0 else ("" if v == 0 else "−")
    cls = "pos" if v > 0 else ("neg" if v < 0 else "mut")
    return f'<span class="{cls}">{sign}{abs(v):,}</span>'

def name_link(s):
    """ETF 이름을 네이버 금융 해당 종목 차트로 연결한다."""
    name = esc(s["name"])
    code = str(s.get("code") or "")
    if not code:
        return name
    return (f'<a class="etf-link" href="https://finance.naver.com/item/fchart.naver?code={esc(code)}"'
            f' target="_blank" rel="noopener">{name}</a>')

def day_html(payload, is_latest):
    """하루치 본문(네비게이션으로 교체되는 부분)."""
    sig = payload["signals"]
    scanned = len(sig)
    alerts = [s for s in sig if s["alert"]]
    sells = [s for s in sig if s.get("alert_sell")]
    adxs = [s for s in sig if s.get("alert_adx")]
    n_buy = sum(1 for s in sig if s["flow"] == "쌍끌이")
    n_warn = sum(1 for s in sig if s["flow"] == "개인몰림")
    asof = sig[0]["asof"] if sig else "—"
    day = "오늘" if is_latest else "당일"

    def cards(rows, kind):
        """kind: 'buy'(골든크로스) | 'sell'(데드크로스) | 'adx'(추세 강도)"""
        if not rows:
            msg = {"buy": "이날 새로 뜬 매수 신호가 없습니다. (조정·횡보 국면일 가능성)",
                   "sell": "이날 새로 뜬 매도 경고가 없습니다.",
                   "adx": "이날 ADX 20·25를 새로 돌파한 종목이 없습니다."}[kind]
            return f'<p class="none">{msg}</p>'
        out = ""
        for s in rows:
            why = {"buy": reasons, "sell": reasons_sell, "adx": reasons_adx}[kind]
            rs = " · ".join(why(s)) or "신호 발생"
            # 추세 강도 카드는 방향(상승/하락)과 강도(확인/강력)로 색을 나눈다
            cls = kind
            if kind == "adx":
                cls += " adx-down" if not s.get("adx_up") else ""
                cls += " strong" if s.get("adx_stage") == 2 else ""
            out += f'''
      <article class="alert-card {cls}">
        <div class="ac-head"><span class="ac-title"><b>{name_link(s)}</b><button class="btn-chart" data-code="{esc(s.get("code") or "")}" title="최근 120거래일 가격 · 신호 발생 시점">추세</button></span><small>{esc(s["group"])} · {s["close"]:,}원</small></div>
        <p>{esc(rs)}</p>
        <div class="ac-meta">ADX {s["adx"]} · %K {s["k"]}/{s["d"]} · {flow_badge(s["flow"])}</div>
      </article>'''
        return out

    # 전체 표 — 매수 알림 → 매도 경고 → 추세강도 → 나머지, 각 그룹 내부는 스캔순
    def row_order(x):
        s = x[1]
        rank = 0 if s["alert"] else (1 if s.get("alert_sell") else
                                     (2 if s.get("alert_adx") else 3))
        return (rank, x[0])

    rows_sorted = sorted(enumerate(sig), key=row_order)
    trs = ""
    for _, s in rows_sorted:
        flag = '<span class="star">★ 매수</span>' if s["alert"] else ""
        if s.get("alert_sell"):
            flag += '<span class="skull">▼ 매도</span>'
        if s.get("alert_adx"):
            lv = 25 if s.get("adx_stage") == 2 else 20
            flag += f'<span class="bolt">⚡ ADX{lv}</span>'
        if not s["liquid"]:
            flag += '<span class="lowliq">저유동성</span>'
        stoch_ev = ""
        if s["stoch_oversold"]: stoch_ev = '<span class="mini gold">과매도반등</span>'
        elif s.get("stoch_overbought"): stoch_ev = '<span class="mini dead">과열이탈</span>'
        elif s["ev_stoch"]: stoch_ev = '<span class="mini gold">골든</span>'
        elif s.get("ev_stoch_dead"): stoch_ev = '<span class="mini dead">데드</span>'
        cls = "hl" if s["alert"] else ("hs" if s.get("alert_sell")
                                       else ("ha" if s.get("alert_adx")
                                             else ("dim" if not s["liquid"] else "")))
        adx_ev = ""
        if s.get("adx_stage") == 2: adx_ev = '<span class="mini bolt2">25↑강력</span>'
        elif s.get("adx_stage") == 1: adx_ev = '<span class="mini bolt1">20↑</span>'
        # 정렬용 원시값(표시값이 아닌 실제 숫자/랭크)
        tr_rank = 2 if s["up_trend"] else (0 if s["pdi"] < s["ndi"] else 1)
        fl_rank = {"쌍끌이": 3, "중립": 2, "수급없음": 1, "개인몰림": 0}.get(s["flow"], 2)
        fg_rank = (3 if s["alert"] else (2 if s.get("alert_sell") else
                                         (1 if s.get("alert_adx") else 0))) + (0 if s["liquid"] else -1)
        trs += f'''
      <tr class="{cls}">
        <td class="etf" data-v="{esc(s["name"])}"><div class="etf-row"><b>{name_link(s)}</b><button class="btn-chart" data-code="{esc(s.get("code") or "")}" title="최근 120거래일 가격 · 신호 발생 시점">추세</button></div><small>{esc(s["group"])}</small></td>
        <td class="r" data-v="{s["close"]}">{s["close"]:,}</td>
        <td class="c" data-v="{s["adx"]}">{s["adx"]} {adx_ev}<small class="di">{s["pdi"]}/{s["ndi"]}</small></td>
        <td class="c" data-v="{tr_rank}">{trend_badge(s)}</td>
        <td class="c" data-v="{s["k"]}">{s["k"]}/{s["d"]} {stoch_ev}</td>
        <td class="c" data-v="{fl_rank}">{flow_badge(s["flow"])}</td>
        <td class="r" data-v="{sv(s["for5"])}">{num(s["for5"])}</td>
        <td class="r" data-v="{sv(s["org5"])}">{num(s["org5"])}</td>
        <td class="r" data-v="{sv(s["ind5"])}">{num(s["ind5"])}</td>
        <td class="c flags" data-v="{fg_rank}">{flag}</td>
      </tr>'''

    return f"""
<p class="sub">생성 <b>{esc(payload["generated_at"])}</b> · 신호 기준일(전일 확정) <b>{esc(asof)}</b><br>
ADX(추세) + Stochastic Slow(타이밍) + 수급(외인·기관·개인 5일 순매수, 억원). 신호는 장중 흔들림을 피해 <b>전일 확정 종가</b>로 계산.</p>

<section class="stats">
  <article><small>스캔 종목</small><strong>{scanned}</strong></article>
  <article><small>{day} 매수 신호</small><strong class="g">{len(alerts)}</strong></article>
  <article><small>{day} 매도 경고</small><strong class="r">{len(sells)}</strong></article>
  <article><small>{day} 추세 강도</small><strong class="b">{len(adxs)}</strong></article>
  <article><small>외인·기관 쌍끌이</small><strong class="g">{n_buy}</strong></article>
  <article><small>개인몰림 경계</small><strong class="w">{n_warn}</strong></article>
</section>

<h2>{day}의 매수 신호 <small style="font:400 12px Inter;color:#8b918e">— 새로 뜬 골든크로스 · 개인몰림 제외 · 유동성 확보 종목</small></h2>
<div class="alerts">{cards(alerts, "buy")}</div>

<h2>{day}의 매도 경고 <small style="font:400 12px Inter;color:#8b918e">— 새로 뜬 데드크로스 · 쌍끌이 제외 · 유동성 확보 종목</small></h2>
<div class="alerts">{cards(sells, "sell")}</div>

<h2>{day}의 추세 강도 <small style="font:400 12px Inter;color:#8b918e">— ADX 20 돌파(확인) · 25 돌파(강력) · 방향은 DI로 판정</small></h2>
<div class="alerts">{cards(adxs, "adx")}</div>

<h2>전체 신호판 ({scanned})</h2>
<div class="tablewrap"><table>
<thead><tr>
<th data-type="text">ETF</th><th class="r" data-type="num">종가</th><th class="c" data-type="num">ADX<br>+DI/−DI</th><th class="c" data-type="num">추세</th>
<th class="c" data-type="num">%K/%D</th><th class="c" data-type="num">수급</th>
<th class="r" data-type="num">외인5D</th><th class="r" data-type="num">기관5D</th><th class="r" data-type="num">개인5D</th><th class="c" data-type="num">플래그</th>
</tr></thead>
<tbody>{trs}</tbody>
</table></div>
"""


def archive(payload):
    """signals.json을 history/{asof}.json으로 보관 (같은 기준일은 최신으로 덮어씀).
    차트용 history 시계열은 용량이 커서 아카이브에서는 뺀다(차트는 항상 최신 데이터로 표시)."""
    sig = payload.get("signals") or []
    if not sig:
        return
    asof = sig[0].get("asof") or ""
    if len(asof) != 10:
        return
    slim = dict(payload)
    slim["signals"] = [{k: v for k, v in s.items() if k != "history"} for s in sig]
    os.makedirs(HIST_DIR, exist_ok=True)
    with open(os.path.join(HIST_DIR, f"{asof}.json"), "w", encoding="utf-8") as f:
        json.dump(slim, f, ensure_ascii=False)


def build(payload):
    archive(payload)
    hist = {}
    for p in sorted(glob.glob(os.path.join(HIST_DIR, "*.json"))):
        d = os.path.splitext(os.path.basename(p))[0]
        hist[d] = p
    nav_dates = sorted(hist)[-MAX_DAYS:]
    if not nav_dates:  # history가 없으면 현재 payload 단독
        sig = payload.get("signals") or []
        d = sig[0]["asof"] if sig else "—"
        nav_dates = [d]
        pages = {d: day_html(payload, True)}
    else:
        pages = {}
        for d in nav_dates:
            with open(hist[d], encoding="utf-8") as f:
                pages[d] = day_html(json.load(f), is_latest=(d == nav_dates[-1]))

    date_opts = []
    for d in nav_dates:
        try:
            t = datetime.date.fromisoformat(d)
            label = f"{t.month}/{t.day}({WD[t.weekday()]})"
        except ValueError:
            label = d
        if d == nav_dates[-1]:
            label += " · 최신"
        date_opts.append(f'<option value="{d}">{label}</option>')

    pages_json = json.dumps(pages, ensure_ascii=False).replace("</", "<\\/")
    dates_json = json.dumps(nav_dates)

    # 차트 데이터: 최신 payload의 history만 사용(과거 일자 조회 중에도 차트는 최신 시계열)
    charts = {}
    for s in payload.get("signals") or []:
        h = s.get("history")
        if h and s.get("code"):
            charts[s["code"]] = {"name": s["name"], **h}
    charts_json = json.dumps(charts, ensure_ascii=False).replace("</", "<\\/")

    return TEMPLATE.format(nav_opts="".join(date_opts), pages_json=pages_json,
                           dates_json=dates_json, ndays=len(nav_dates),
                           charts_json=charts_json)

TEMPLATE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ETF/섹터 신호 포착 · GS Research Desk</title>
<style>
:root{{--bg:#f3f4f1;--ink:#17211d;--muted:#6c746f;--line:#dfe2dc;--card:#fff;
--green:#173f35;--lime:#d9f272;--red:#bd4335}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);
font-family:Inter,Pretendard,"Noto Sans KR",sans-serif;padding:28px 30px 60px}}
.eyebrow{{font-size:10px;font-weight:800;letter-spacing:1.6px;color:#758079;margin:0 0 7px}}
h1{{font:500 30px Georgia,"Noto Serif KR",serif;margin:0}}
.sub{{color:var(--muted);font-size:12px;margin:8px 0 0;line-height:1.6}}
.sub b{{color:#445049}}
.stats{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin:22px 0 8px}}
.stats article{{background:var(--card);border:1px solid var(--line);padding:18px 20px}}
.stats small{{color:var(--muted);font-size:11px;font-weight:700;letter-spacing:.04em}}
.stats strong{{font:500 32px Georgia;display:block;margin:8px 0 0}}
.stats .g{{color:#286342}}.stats .w{{color:#8a661c}}.stats .r{{color:#a43c31}}
.stats .b{{color:#2b5f8a}}
h2{{font:600 18px Georgia,"Noto Serif KR",serif;margin:30px 0 12px}}
.alerts{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}}
.alert-card{{background:#fff;border:1px solid var(--line);border-left:4px solid var(--green);padding:15px 17px}}
.alert-card.sell{{border-left-color:var(--red)}}
.alert-card.adx{{border-left-color:#2b5f8a}}
.alert-card.adx.adx-down{{border-left-color:#b06a2c}}
.alert-card.adx.strong{{border-left-width:7px}}
.ac-head{{display:flex;justify-content:space-between;align-items:baseline;gap:10px}}
.ac-title{{display:inline-flex;align-items:center;gap:8px}}
.ac-head b{{font-size:15px}}.ac-head small{{color:var(--muted);font-size:11px;white-space:nowrap}}
.alert-card p{{margin:9px 0;font-size:13px;color:#2c3a34;line-height:1.5}}
.ac-meta{{font-size:11px;color:var(--muted);display:flex;gap:8px;align-items:center;flex-wrap:wrap}}
.none{{color:var(--muted);background:#fff;border:1px solid var(--line);padding:22px;text-align:center}}
.tablewrap{{overflow-x:auto;border:1px solid var(--line);background:#fff;margin-top:4px}}
table{{width:100%;min-width:900px;border-collapse:collapse}}
th{{background:#f5f7f3;border-bottom:1px solid #cfd5cf;color:#68736d;font-size:10px;
font-weight:700;letter-spacing:.04em;text-align:left;padding:11px 12px;white-space:nowrap}}
th.c{{text-align:center}}th.r{{text-align:right}}
th.sortable{{cursor:pointer;user-select:none}}th.sortable:hover{{color:#2c3a34}}
th.sortable::after{{content:"⇅";opacity:.32;font-size:9px;margin-left:4px;font-weight:400}}
th.sortable[data-dir=asc]::after{{content:"▲";opacity:.85}}
th.sortable[data-dir=desc]::after{{content:"▼";opacity:.85}}
td{{border-bottom:1px solid #eef1ec;padding:10px 12px;font-size:13px;vertical-align:middle}}
td.c{{text-align:center}}td.r{{text-align:right;font-family:Georgia}}
tbody tr:hover{{background:#fafbf8}}tbody tr.hl{{background:#fbfdf4}}
tbody tr.hl:hover{{background:#f6faea}}tbody tr.dim td{{color:#98a09a}}
tbody tr.hs{{background:#fdf7f5}}tbody tr.hs:hover{{background:#fbefeb}}
tbody tr.ha{{background:#f6f9fc}}tbody tr.ha:hover{{background:#eef4fa}}
.etf b{{font-size:13px;display:block}}.etf small{{color:var(--muted);font-size:10px}}
.etf-link{{color:inherit;text-decoration:none;border-bottom:1px solid transparent}}
.etf-link:hover{{color:#286342;border-bottom-color:#286342}}
.di{{display:block;color:#9aa19d;font-size:10px;font-family:Georgia}}
.badge{{display:inline-block;border-radius:11px;padding:3px 9px;font-size:10px;font-weight:700;white-space:nowrap}}
.b-buy{{background:#e3f3e7;color:#286342}}.b-warn{{background:#fff1cf;color:#765c19}}
.b-down{{background:#f8e9e6;color:#a43c31}}.b-mut{{background:#edf1ed;color:#61706a}}
.mini{{display:inline-block;font-size:9px;font-weight:700;padding:2px 5px;border-radius:4px;margin-left:3px}}
.mini.gold{{background:#fff4d6;color:#8a661c}}
.mini.dead{{background:#f8e3e0;color:#a43c31}}
.mini.bolt1{{background:#e7eef6;color:#2b5f8a}}
.mini.bolt2{{background:#d9e6f3;color:#1d4e75;font-weight:800}}
.pos{{color:#286342}}.neg{{color:#a43c31}}.mut{{color:#a9afab}}
.flags{{white-space:nowrap}}.star{{color:#5a7a1e;font-size:10px;font-weight:800}}
.skull{{color:#a43c31;font-size:10px;font-weight:800;margin-left:5px}}
.bolt{{color:#2b5f8a;font-size:10px;font-weight:800;margin-left:5px}}
.lowliq{{display:inline-block;margin-left:5px;color:#9a8650;font-size:9px;border:1px solid #e0d8bf;border-radius:4px;padding:1px 4px}}
.legend{{margin-top:14px;color:var(--muted);font-size:11px;line-height:1.9}}
.legend b{{color:#445049}}
.nav{{display:flex;align-items:center;gap:8px;margin:16px 0 0;position:sticky;top:0;
background:var(--bg);padding:8px 0;z-index:5}}
.nav button{{background:var(--card);color:var(--ink);border:1px solid var(--line);
padding:7px 15px;font-size:13px;cursor:pointer;line-height:1}}
.nav button:disabled{{opacity:.35;cursor:default}}
.nav button:not(:disabled):hover{{border-color:#758079}}
.nav select{{background:var(--card);color:var(--ink);border:1px solid var(--line);
padding:7px 9px;font-size:12px}}
.nav .hint{{margin-left:auto;font-size:10px;color:#9aa19d}}
.etf-row{{display:flex;align-items:center;justify-content:space-between;gap:8px}}
.btn-chart{{background:#eef3ec;color:#3d554a;border:1px solid #d3dcd2;border-radius:10px;
padding:2px 8px;font-size:10px;font-weight:700;cursor:pointer;white-space:nowrap;line-height:1.5}}
.btn-chart:hover{{background:#e3f3e7;border-color:#8fae9c;color:#286342}}
#modal-bg{{display:none;position:fixed;inset:0;background:rgba(23,33,29,.45);z-index:50;
align-items:center;justify-content:center;padding:20px}}
.modal{{background:#fff;border:1px solid var(--line);max-width:780px;width:100%;
padding:18px 22px 16px;box-shadow:0 12px 40px rgba(23,33,29,.22)}}
.modal-head{{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin-bottom:10px}}
.modal-head b{{font:600 16px Georgia,"Noto Serif KR",serif}}
#modal-x{{background:none;border:none;font-size:18px;color:#8b918e;cursor:pointer;line-height:1}}
#modal-x:hover{{color:#17211d}}
.chart{{width:100%;height:auto;display:block}}
.grid{{stroke:#e9ede7;stroke-width:1}}
.ax{{font:10px Georgia;fill:#8b918e}}
.pline{{fill:none;stroke:#173f35;stroke-width:1.6}}
.mk-t{{fill:#2e7d4f;cursor:help}}.mk-s{{fill:#c98a1e;cursor:help}}
.mk-dt{{fill:#bd4335;cursor:help}}.mk-ds{{fill:#8e5ba6;cursor:help}}
.chart-legend{{margin:10px 0 0;font-size:11px;color:var(--muted);line-height:1.8}}
.chart-legend .lg-t{{color:#2e7d4f}}.chart-legend .lg-s{{color:#c98a1e}}
.chart-legend .lg-dt{{color:#bd4335}}.chart-legend .lg-ds{{color:#8e5ba6}}
@media(max-width:1180px){{.stats{{grid-template-columns:repeat(3,1fr)}}}}
@media(max-width:620px){{body{{padding:20px 12px 50px}}.stats{{grid-template-columns:1fr 1fr}}
table{{min-width:760px}}}}
</style></head><body>
<p class="eyebrow">ETF · SECTOR SIGNAL</p>
<h1>ETF/섹터 신호 포착</h1>
<div class="nav">
<button id="btn-prev" title="이전 기준일 (←)">◀</button>
<select id="sel-date">{nav_opts}</select>
<button id="btn-next" title="다음 기준일 (→)">▶</button>
<span class="hint">← → 키로도 이동 · 과거 {ndays}일 조회</span>
</div>
<div id="day"></div>

<p class="legend">
<b>추세</b> +DI&gt;−DI &amp; ADX&gt;20 = 상승추세, −DI&gt;+DI &amp; ADX&gt;20 = 하락추세 ·
<b>과매도반등</b> Stochastic %K가 %D를 25 미만에서 상향돌파 · <b>과열이탈</b> %K가 %D를 75 초과에서 하향이탈 ·
<b>쌍끌이</b> 외인+기관 5일 동반 순매수 · <b>개인몰림</b> 개인만 순매수(외인·기관 이탈) = 경계 ·
<b>★매수</b> 오늘 새 골든크로스 + 개인몰림 아님 + 20일 거래대금 5억↑ ·
<b>▼매도</b> 오늘 새 데드크로스 + 쌍끌이 아님 + 20일 거래대금 5억↑<br>
<b>⚡추세 강도</b> ADX가 <b>20</b>을 상향돌파하면 추세 확립(확인), <b>25</b>를 상향돌파하면 추세 강화(강력).
ADX는 방향이 없는 강도 지표라 방향은 +DI/−DI로 판정한다(＋DI&gt;−DI = 상승, −DI&gt;＋DI = 하락).
크로스 신호와 별개이므로 같은 날 함께 뜰 수 있다.<br>
수급 단위: 억원 · 매매가 아닌 <b>참고용 신호</b>입니다.<br>
<b>정렬</b> 헤더를 클릭하면 해당 열 기준으로 정렬(다시 클릭 시 오름/내림 전환). 값 없음(–)은 항상 맨 아래.<br>
<b>추세 버튼</b> 종목별 최근 120거래일 가격 차트와 과거 신호 발생 시점(▲ 추세 골든크로스 · ● 과매도 반등 · ▼ 추세 데드크로스 · ◆ 과열 이탈)을 보여줍니다.
</p>

<div id="modal-bg"><div class="modal">
<div class="modal-head"><b id="modal-title"></b><button id="modal-x" title="닫기 (Esc)">✕</button></div>
<div id="modal-body"></div>
</div></div>
<script>
function initSort(){{
  var table = document.querySelector('#day table');
  if(!table) return;
  var tbody = table.tBodies[0];
  var ths = table.tHead.rows[0].cells;
  var cur = -1, dir = 1;
  function val(td, type){{
    var v = td.getAttribute('data-v');
    if(type === 'num'){{
      var n = parseFloat(v);
      return isNaN(n) ? null : n;
    }}
    return (v || td.textContent).trim().toLowerCase();
  }}
  Array.prototype.forEach.call(ths, function(th, i){{
    var type = th.getAttribute('data-type');
    if(!type) return;
    th.classList.add('sortable');
    th.addEventListener('click', function(){{
      dir = (cur === i) ? -dir : 1;
      cur = i;
      Array.prototype.forEach.call(ths, function(x){{ x.removeAttribute('data-dir'); }});
      th.setAttribute('data-dir', dir > 0 ? 'asc' : 'desc');
      var rows = Array.prototype.slice.call(tbody.rows);
      rows.sort(function(a, b){{
        var av = val(a.cells[i], type), bv = val(b.cells[i], type);
        if(av === null && bv === null) return 0;
        if(av === null) return 1;   // 값 없음은 방향과 무관하게 맨 아래
        if(bv === null) return -1;
        if(av < bv) return -dir;
        if(av > bv) return dir;
        return 0;
      }});
      rows.forEach(function(r){{ tbody.appendChild(r); }});
    }});
  }});
}}
var PAGES = {pages_json};
var DATES = {dates_json};
var idx = DATES.length - 1;
var sel = document.getElementById("sel-date");
var prev = document.getElementById("btn-prev");
var next = document.getElementById("btn-next");
function show(i) {{
  idx = Math.max(0, Math.min(i, DATES.length - 1));
  document.getElementById("day").innerHTML = PAGES[DATES[idx]];
  sel.value = DATES[idx];
  prev.disabled = idx === 0;
  next.disabled = idx === DATES.length - 1;
  initSort();
}}
prev.addEventListener("click", function () {{ show(idx - 1); }});
next.addEventListener("click", function () {{ show(idx + 1); }});
sel.addEventListener("change", function () {{ show(DATES.indexOf(sel.value)); }});
document.addEventListener("keydown", function (e) {{
  if (e.key === "ArrowLeft") show(idx - 1);
  else if (e.key === "ArrowRight") show(idx + 1);
}});
show(idx);

/* ── 종목별 시계열 신호 차트 (추세 버튼 → 모달) ── */
var CHARTS = {charts_json};
var mbg = document.getElementById('modal-bg');
document.addEventListener('click', function (e) {{
  var b = e.target.closest ? e.target.closest('.btn-chart') : null;
  if (b) openChart(b.getAttribute('data-code'));
}});
mbg.addEventListener('click', function (e) {{ if (e.target === mbg) closeChart(); }});
document.getElementById('modal-x').addEventListener('click', closeChart);
document.addEventListener('keydown', function (e) {{ if (e.key === 'Escape') closeChart(); }});
function closeChart() {{ mbg.style.display = 'none'; }}
function openChart(code) {{
  var c = CHARTS[code];
  var title = document.getElementById('modal-title');
  var body = document.getElementById('modal-body');
  if (!c) {{
    title.textContent = '시계열 데이터 없음';
    body.innerHTML = '<p class="none">아직 이력이 없습니다. 다음 스캔(매일 오전 10시)부터 차트가 표시됩니다.</p>';
  }} else {{
    title.textContent = c.name + ' · 최근 ' + c.dates.length + '거래일 (' + c.dates[0] + ' ~ ' + c.dates[c.dates.length - 1] + ')';
    body.innerHTML = renderChart(c);
  }}
  mbg.style.display = 'flex';
}}
function renderChart(c) {{
  var W = 700, H = 310, L = 56, R = 14, T = 18, B = 34;
  var n = c.close.length;
  var mn = Math.min.apply(null, c.close), mx = Math.max.apply(null, c.close);
  if (mx === mn) mx = mn + 1;
  var pad = (mx - mn) * 0.07; mn -= pad; mx += pad;
  function X(i) {{ return L + (W - L - R) * (n <= 1 ? 0 : i / (n - 1)); }}
  function Y(v) {{ return T + (H - T - B) * (1 - (v - mn) / (mx - mn)); }}
  var pts = '';
  for (var i = 0; i < n; i++) pts += (i ? ' ' : '') + X(i).toFixed(1) + ',' + Y(c.close[i]).toFixed(1);
  var s = '<svg viewBox="0 0 ' + W + ' ' + H + '" class="chart" role="img">';
  for (var g = 0; g <= 4; g++) {{
    var v = mn + (mx - mn) * g / 4, y = Y(v).toFixed(1);
    s += '<line x1="' + L + '" y1="' + y + '" x2="' + (W - R) + '" y2="' + y + '" class="grid"/>';
    s += '<text x="' + (L - 6) + '" y="' + (+y + 3) + '" class="ax" text-anchor="end">' + Math.round(v).toLocaleString() + '</text>';
  }}
  var step = Math.max(1, Math.round(n / 6));
  for (var i = 0; i < n; i += step)
    s += '<text x="' + X(i).toFixed(1) + '" y="' + (H - 10) + '" class="ax" text-anchor="middle">' + c.dates[i].slice(5) + '</text>';
  s += '<polyline points="' + pts + '" class="pline"/>';
  (c.t || []).forEach(function (i) {{
    var x = X(i).toFixed(1), y = Y(c.close[i]);
    s += '<path d="M' + x + ' ' + (y + 6).toFixed(1) + ' l5 9 h-10 z" class="mk-t">' +
         '<title>' + c.dates[i] + ' · 추세 골든크로스(+DI가 −DI 상향돌파) · ' + c.close[i].toLocaleString() + '원</title></path>';
  }});
  (c.s || []).forEach(function (i) {{
    var x = X(i).toFixed(1), y = Y(c.close[i]);
    s += '<circle cx="' + x + '" cy="' + (y - 10).toFixed(1) + '" r="4.5" class="mk-s">' +
         '<title>' + c.dates[i] + ' · 과매도 반등(Stochastic 골든크로스) · ' + c.close[i].toLocaleString() + '원</title></circle>';
  }});
  (c.dt || []).forEach(function (i) {{
    var x = X(i).toFixed(1), y = Y(c.close[i]);
    s += '<path d="M' + x + ' ' + (y - 6).toFixed(1) + ' l5 -9 h-10 z" class="mk-dt">' +
         '<title>' + c.dates[i] + ' · 추세 데드크로스(+DI가 −DI 하향이탈) · ' + c.close[i].toLocaleString() + '원</title></path>';
  }});
  (c.ds || []).forEach(function (i) {{
    var x = X(i).toFixed(1), y = Y(c.close[i]);
    s += '<path d="M' + x + ' ' + (y + 7).toFixed(1) + ' l5 5 l-5 5 l-5 -5 z" class="mk-ds">' +
         '<title>' + c.dates[i] + ' · 과열 이탈(Stochastic 데드크로스) · ' + c.close[i].toLocaleString() + '원</title></path>';
  }});
  s += '</svg>';
  s += '<p class="chart-legend"><span class="lg-t">▲</span> 추세 골든크로스(+DI가 −DI 상향돌파, 라인 아래) · ' +
       '<span class="lg-s">●</span> 과매도 반등(Stochastic %K↑%D, 라인 위)<br>' +
       '<span class="lg-dt">▼</span> 추세 데드크로스(+DI가 −DI 하향이탈, 라인 위) · ' +
       '<span class="lg-ds">◆</span> 과열 이탈(Stochastic %K↓%D, 라인 아래) · 마커에 마우스를 올리면 날짜·가격 표시</p>';
  return s;
}}
</script>
</body></html>"""

if __name__ == "__main__":
    with open(os.path.join(HERE, "signals.json"), encoding="utf-8") as f:
        payload = json.load(f)
    out = build(payload)
    # 출력 경로: 환경변수 ETF_REPORT_OUT 우선(워크플로가 대시보드 static으로 지정), 없으면 로컬
    dest = os.getenv("ETF_REPORT_OUT", os.path.join(HERE, "etf_signal_report.html"))
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(out)
    print("생성:", dest, f"({len(out)} bytes)")
