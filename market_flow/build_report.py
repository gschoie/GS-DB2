# -*- coding: utf-8 -*-
"""data/history.json → 시장 수급 동향 정적 HTML 리포트.

출력: ../telegram_research_dashboard/static/market_flow_report.html
(MARKET_FLOW_OUT 환경변수로 재지정 가능)
외부 라이브러리 없이 표준 라이브러리 + 인라인 SVG로만 그린다. 단위: 억원.
과거 일자도 ◀▶ 네비게이션으로 조회 가능 (최근 MAX_DAYS일 임베드).
"""
import json
import os
import datetime as dt
from pathlib import Path

HERE = Path(__file__).resolve().parent
HISTORY = HERE / "data" / "history.json"
OUT = Path(os.environ.get(
    "MARKET_FLOW_OUT",
    HERE.parent / "telegram_research_dashboard" / "static" / "market_flow_report.html"))

KST = dt.timezone(dt.timedelta(hours=9))
SLOT_LABEL = {"1000": "10:00", "1300": "13:00",
              "1540": "15:40 잠정", "1640": "16:40 확정"}
WD = "월화수목금토일"
MAX_DAYS = 30  # 네비게이션으로 볼 수 있는 과거 일수(페이지 용량 상한)
# 예약 시각. .github/workflows/market-flow.yml 의 cron 4개와 맞출 것.
# 잠정/확정 구분은 첫 줄의 '최근 스냅샷 …'이 이미 보여주므로 여기선 시각만 적는다.
SCHEDULE_TIME = "평일 하루 4회"
SCHEDULE_SLOTS = "10:00 · 13:00 · 15:40 · 16:40"


def sched_badge(actual):
    """'정기 업데이트 예약 시각 · 실제로 돌아간 시각'을 함께 보여준다.
    대기열 지연으로 실제 실행이 늦는 경우가 많아 예약 시각만으로는 오해가 생긴다."""
    act = f' · 실제 갱신 <b>{actual}</b>' if actual else ""
    return (f'<span class="sched">🕙 정기 업데이트 <b>{SCHEDULE_TIME}</b>(한국시간) '
            f'{SCHEDULE_SLOTS}{act}'
            f'<span class="schedq"> — 대기열 지연으로 예약보다 늦을 수 있음</span></span>')

C_IND, C_FRN, C_INST = "#7f8792", "#d64545", "#3b6fd4"
C_ARB, C_NONARB, C_TOTAL = "#e0902f", "#2fa170", "#666e78"


def fmt(v, sign=True):
    if v is None:
        return "–"
    s = f"{abs(v):,}"
    if sign:
        return ("+" if v > 0 else "-" if v < 0 else "") + s
    return s


def cell(v):
    if v is None:
        return '<td class="na">–</td>'
    cls = "pos" if v > 0 else "neg" if v < 0 else ""
    return f'<td class="{cls}">{fmt(v)}</td>'


def nice_ticks(lo, hi, n=4):
    span = max(hi - lo, 1)
    raw = span / n
    mag = 10 ** len(str(int(raw))) / 10
    step = max(int(raw / mag + 0.999) * int(mag), 1)
    start = int(lo // step) * step
    return list(range(start, int(hi) + step, step))


def line_chart(series, width=760, height=250, unit="억원"):
    """series: [(label, color, [(x_label, value), …]), …] — x 격자는 첫 시리즈 기준."""
    if not series or not series[0][2]:
        return '<p class="na">장중 곡선 데이터 없음 (마감 후 수집)</p>'
    pad_l, pad_r, pad_t, pad_b = 64, 14, 14, 26
    xs = [p[0] for p in series[0][2]]
    all_v = [v for _, _, pts in series for _, v in pts]
    lo, hi = min(all_v + [0]), max(all_v + [0])
    ticks = nice_ticks(lo, hi)
    lo, hi = min(lo, ticks[0]), max(hi, ticks[-1])
    iw, ih = width - pad_l - pad_r, height - pad_t - pad_b

    def X(i):
        return pad_l + (i / max(len(xs) - 1, 1)) * iw

    def Y(v):
        return pad_t + (1 - (v - lo) / max(hi - lo, 1)) * ih

    g = []
    for tv in ticks:
        if lo <= tv <= hi:
            y = Y(tv)
            g.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width-pad_r}" y2="{y:.1f}" '
                     f'class="grid{" zero" if tv == 0 else ""}"/>'
                     f'<text x="{pad_l-6}" y="{y+3.5:.1f}" class="tick" text-anchor="end">{tv:,}</text>')
    for i, x in enumerate(xs):
        if x.endswith(":00"):
            g.append(f'<text x="{X(i):.1f}" y="{height-8}" class="tick" text-anchor="middle">{x}</text>')
    for label, color, pts in series:
        d = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, (_, v) in enumerate(pts))
        g.append(f'<polyline points="{d}" fill="none" stroke="{color}" stroke-width="2.2" '
                 f'stroke-linejoin="round"/>')
    legend = " · ".join(f'<span style="color:{c}">━ {l}</span>' for l, c, _ in series)
    return (f'<div class="legend">{legend}<span class="unit">단위: {unit} (누적)</span></div>'
            f'<svg viewBox="0 0 {width} {height}" role="img">{"".join(g)}</svg>')


def nice_max(m):
    """m 이상인 '깔끔한' 상한(1/2/2.5/5 × 10^k)."""
    m = max(m, 1)
    e = 10 ** (len(str(int(m))) - 1)
    for f in (1, 2, 2.5, 5, 10):
        if f * e >= m:
            v = f * e
            return int(v) if float(v).is_integer() else v
    return 10 * e


def combo_chart(rows, color, line_unit, width=760, height=250):
    """현물(바, 좌축 억원) vs 선물(라인, 우축) 이중축 차트.
    rows: [(date, spot_v, fut_v), …] — 두 축 모두 0 중심 대칭이라 0선을 공유한다."""
    rows = [r for r in rows if r[1] is not None and r[2] is not None]
    if not rows:
        return '<p class="na">현물·선물 동시 확정 데이터 없음</p>'
    pad_l, pad_r, pad_t, pad_b = 64, 64, 14, 30
    sm = nice_max(max(abs(v) for _, v, _ in rows))
    fm = nice_max(max(abs(v) for _, _, v in rows))
    iw, ih = width - pad_l - pad_r, height - pad_t - pad_b
    gw = iw / len(rows)
    bw = min(gw * 0.5, 14)

    def Y(v, m):
        return pad_t + (1 - (v + m) / (2 * m)) * ih

    g = []
    for frac in (-1, -0.5, 0, 0.5, 1):
        y = pad_t + (1 - (frac + 1) / 2) * ih
        g.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width-pad_r}" y2="{y:.1f}" '
                 f'class="grid{" zero" if frac == 0 else ""}"/>'
                 f'<text x="{pad_l-6}" y="{y+3.5:.1f}" class="tick" '
                 f'text-anchor="end">{frac*sm:,.0f}</text>'
                 f'<text x="{width-pad_r+6}" y="{y+3.5:.1f}" class="tick" '
                 f'text-anchor="start">{frac*fm:,.0f}</text>')
    y0 = Y(0, sm)
    pts = []
    for i, (d, sv, fv) in enumerate(rows):
        cx = pad_l + gw * i + gw / 2
        ys = Y(sv, sm)
        g.append(f'<rect x="{cx-bw/2:.1f}" y="{min(ys, y0):.1f}" width="{bw:.1f}" '
                 f'height="{abs(ys-y0):.1f}" fill="{color}" fill-opacity=".4" rx="1"/>')
        pts.append((cx, Y(fv, fm)))
        if i % 2 == (len(rows) - 1) % 2:
            g.append(f'<text x="{cx:.1f}" y="{height-8}" class="tick" '
                     f'text-anchor="middle">{d[5:].replace("-", "/")}</text>')
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    g.append(f'<polyline points="{poly}" fill="none" stroke="{color}" '
             f'stroke-width="2.2" stroke-linejoin="round"/>')
    g += [f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="{color}"/>' for x, y in pts]
    legend = (f'<span style="color:{color};opacity:.65">■ 현물 순매수 (좌축·억원)</span> · '
              f'<span style="color:{color}">●━ 선물 순매수 (우축·{line_unit})</span>')
    return (f'<div class="legend">{legend}</div>'
            f'<svg viewBox="0 0 {width} {height}" role="img">{"".join(g)}</svg>')


def fut_snapshot(day):
    """당일 K200 선물 순매수 (확정 우선, 없으면 장중 곡선 마지막 점).
    반환: ({individual, foreign, inst}, 출처라벨) 또는 (None, None)"""
    f = day.get("confirmed", {}).get("futures")
    if f:
        return ({"individual": f.get("individual"), "foreign": f.get("foreign"),
                 "inst": f.get("inst_total")}, "확정")
    c = (day.get("curve") or {}).get("futures")
    if c:
        last = c[-1]
        return ({"individual": last[1], "foreign": last[2], "inst": last[3]},
                f"장중 {last[0]}")
    return None, None


def fut_quadrant(spot, fut):
    """현물·선물 방향 조합 → (조합라벨, 해석, css클래스)"""
    if spot is None or fut is None:
        return None
    if spot >= 0 and fut >= 0:
        return ("현·선물 동반 매수", "방향성 강세 베팅", "pos")
    if spot >= 0 > fut:
        return ("현물 매수 · 선물 매도", "헤지 동반 — 상승 신뢰 제한", "")
    if spot < 0 <= fut:
        return ("현물 매도 · 선물 매수", "숏커버/반등 베팅 성격", "")
    return ("현·선물 동반 매도", "리스크 오프 압력", "neg")


def bar_chart(days, width=760, height=240):
    """최근 20일 개인/외인/기관 일별 순매수 그룹 바차트. days: [(date, ind, frn, inst), …]"""
    if not days:
        return '<p class="na">일별 확정 데이터 없음</p>'
    pad_l, pad_r, pad_t, pad_b = 64, 8, 12, 30
    all_v = [v for _, a, b, c in days for v in (a, b, c)]
    lo, hi = min(all_v + [0]), max(all_v + [0])
    ticks = nice_ticks(lo, hi)
    lo, hi = min(lo, ticks[0]), max(hi, ticks[-1])
    iw, ih = width - pad_l - pad_r, height - pad_t - pad_b
    gw = iw / len(days)
    bw = min(gw / 4.2, 9)

    def Y(v):
        return pad_t + (1 - (v - lo) / max(hi - lo, 1)) * ih

    g = []
    for tv in ticks:
        if lo <= tv <= hi:
            y = Y(tv)
            g.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width-pad_r}" y2="{y:.1f}" '
                     f'class="grid{" zero" if tv == 0 else ""}"/>'
                     f'<text x="{pad_l-6}" y="{y+3.5:.1f}" class="tick" text-anchor="end">{tv:,}</text>')
    y0 = Y(0)
    for i, (d, *vals) in enumerate(days):
        cx = pad_l + gw * i + gw / 2
        for k, (v, color) in enumerate(zip(vals, (C_IND, C_FRN, C_INST))):
            x = cx + (k - 1) * (bw + 1) - bw / 2
            y = Y(v)
            g.append(f'<rect x="{x:.1f}" y="{min(y, y0):.1f}" width="{bw:.1f}" '
                     f'height="{abs(y-y0):.1f}" fill="{color}" rx="1"/>')
        if i % 2 == (len(days) - 1) % 2:
            g.append(f'<text x="{cx:.1f}" y="{height-8}" class="tick" '
                     f'text-anchor="middle">{d[5:].replace("-", "/")}</text>')
    legend = (f'<span style="color:{C_IND}">■ 개인</span> · '
              f'<span style="color:{C_FRN}">■ 외국인</span> · '
              f'<span style="color:{C_INST}">■ 기관</span>')
    return (f'<div class="legend">{legend}<span class="unit">단위: 억원 (일별 순매수)</span></div>'
            f'<svg viewBox="0 0 {width} {height}" role="img">{"".join(g)}</svg>')


def build_signals(today, prev_slot_snap, fut=None, fut_src="", fut_unit="계약"):
    """룰 기반 한줄 해석 목록."""
    slots = today.get("slots", {})
    latest = None
    for s in ("1640", "1540", "1300", "1000"):
        if s in slots:
            latest = slots[s]
            break
    if not latest:
        return []
    sig = []
    frn, ind, inst = latest["foreign"], latest["individual"], latest["institution"]
    arb, nonarb, prog = latest["arb"], latest["nonarb"], latest["program"]
    if fut and fut.get("foreign") is not None and abs(fut["foreign"]) >= 800:
        ff = fut["foreign"]
        tail = f"(선물 {fmt(ff)}{fut_unit}·{fut_src})"
        if frn > 0 and ff > 0:
            sig.append(f"외국인 현·선물 동반 매수 {tail} — 방향성 강세 베팅")
        elif frn > 0 > ff:
            sig.append(f"외국인 현물 매수·선물 매도 {tail} — 헤지 동반, 지수 상단 제한 가능")
        elif frn < 0 < ff:
            sig.append(f"외국인 현물 매도·선물 매수 {tail} — 숏커버/반등 베팅 성격")
        elif frn < 0 and ff < 0:
            sig.append(f"외국인 현·선물 동반 매도 {tail} — 리스크 오프 압력")
    if frn > 0 and arb > 0:
        sig.append("외국인 현물 매수 + 차익 프로그램 매수 — 베이시스 개선 동반 상승 압력")
    elif frn > 0 > prog:
        sig.append("외국인 현물은 매수하나 프로그램은 유출 — 지수보다 종목 장세 성격")
    elif frn < 0 and arb < 0:
        sig.append("외국인 현물 매도 + 차익 프로그램 매도 — 베이시스 악화 동반 하락 압력")
    if abs(nonarb) >= 5000:
        sig.append(f"비차익 {'대량 유입' if nonarb > 0 else '대량 유출'} "
                   f"({fmt(nonarb)}억) — 패시브·바스켓 자금 이동")
    if ind * (frn + inst) < 0 and abs(ind) >= 3000:
        sig.append("개인이 외국인·기관과 역방향 — 메이저 물량 이전 구도")
    if prev_slot_snap:
        d_frn = frn - prev_slot_snap["foreign"]
        if d_frn * frn < 0 and abs(d_frn) >= 1500:
            sig.append(f"직전 스냅샷 대비 외국인 {fmt(d_frn)}억 — 장중 방향 전환 조짐")
    return sig


def render_day(hist, all_dates, i):
    """all_dates[i] 하루치 본문 HTML (네비게이션으로 교체되는 부분)."""
    days = hist["days"]
    dkey = all_dates[i]
    today = days[dkey]
    is_latest = i == len(all_dates) - 1
    t_date = dt.date.fromisoformat(dkey)
    kospi = today.get("kospi", {})
    slots = today.get("slots", {})
    slot_keys = [k for k in ("1000", "1300", "1540", "1640") if k in slots]

    # ── 스냅샷 표 ──
    conf = today.get("confirmed", {})
    conf_inv, conf_prg = conf.get("investor"), conf.get("program")
    head = "".join(f"<th>{SLOT_LABEL[k]}</th>" for k in slot_keys)
    rows_def = [("개인", "individual", C_IND), ("외국인", "foreign", C_FRN),
                ("기관", "institution", C_INST), ("프로그램 전체", "program", C_TOTAL),
                ("┗ 차익", "arb", C_ARB), ("┗ 비차익", "nonarb", C_NONARB)]
    body = ""
    for label, key, color in rows_def:
        tds = "".join(cell(slots[k].get(key)) for k in slot_keys)
        body += (f'<tr><th style="border-left:3px solid {color}">{label}</th>{tds}</tr>')
    if not slot_keys:
        snap_table = '<p class="na">장중 스냅샷 데이터 없음</p>'
    else:
        snap_table = f'<table><thead><tr><th></th>{head}</tr></thead><tbody>{body}</tbody></table>'
    fut_unit = hist.get("futures_unit", "계약")
    conf_fut = conf.get("futures")
    conf_note = ""
    if conf_inv and conf_prg:
        fut_seg = (f' / K200선물 외인 {fmt(conf_fut["foreign"])}{fut_unit}'
                   if conf_fut else "")
        conf_note = (f'<p class="note">일별 확정(거래소): 개인 {fmt(conf_inv["individual"])} · '
                     f'외국인 {fmt(conf_inv["foreign"])} · 기관 {fmt(conf_inv["inst_total"])} / '
                     f'프로그램 {fmt(conf_prg["total_net"])} '
                     f'(차익 {fmt(conf_prg["arb_net"])} · 비차익 {fmt(conf_prg["nonarb_net"])})'
                     f'{fut_seg}</p>')

    # ── 장중 곡선 (해당 일자 것만 — 최신 페이지에 한해 최근 보유일 폴백) ──
    curve = today.get("curve") or {}
    curve_day = dkey
    if not curve and is_latest:
        for d in reversed(all_dates):
            if days[d].get("curve"):
                curve, curve_day = days[d]["curve"], d
                break
    no_curve = ('<p class="na">장중 곡선 데이터 없음'
                + ('' if is_latest else ' (장중 곡선은 최근 5일만 보관)') + '</p>')
    inv_chart = prg_chart = no_curve
    if curve:
        ic = curve.get("investor", [])
        pc = curve.get("program", [])
        inv_chart = line_chart([("개인", C_IND, [(r[0], r[1]) for r in ic]),
                                ("외국인", C_FRN, [(r[0], r[2]) for r in ic]),
                                ("기관", C_INST, [(r[0], r[3]) for r in ic])])
        prg_chart = line_chart([("차익", C_ARB, [(r[0], r[1]) for r in pc]),
                                ("비차익", C_NONARB, [(r[0], r[2]) for r in pc]),
                                ("전체", C_TOTAL, [(r[0], r[3]) for r in pc])])
    fut_curve_html = ""
    fc = curve.get("futures")
    if fc:
        fut_curve_html = (
            f'<h2>🎯 장중 누적 흐름 — K200 선물 <span class="na" '
            f'style="font-weight:400;font-size:12px">({curve_day} · {fut_unit})</span></h2>'
            '<div class="card">'
            + line_chart([("개인", C_IND, [(r[0], r[1]) for r in fc]),
                          ("외국인", C_FRN, [(r[0], r[2]) for r in fc]),
                          ("기관", C_INST, [(r[0], r[3]) for r in fc])], unit=fut_unit)
            + '</div>')

    # ── 해당 일자 기준 최근 20일 확정 ──
    upto = all_dates[:i + 1]
    conf_days = [(d, days[d]["confirmed"]) for d in upto if days[d].get("confirmed")]
    last20 = conf_days[-20:]
    bars = bar_chart([(d, c["investor"]["individual"], c["investor"]["foreign"],
                       c["investor"]["inst_total"]) for d, c in last20 if "investor" in c])
    cum = {"individual": 0, "foreign": 0, "inst_total": 0, "program": 0}
    for _, c in last20:
        if "investor" in c:
            for k in ("individual", "foreign", "inst_total"):
                cum[k] += c["investor"][k]
        if "program" in c:
            cum["program"] += c["program"]["total_net"]
    n20 = len(last20)

    def chip(label, v, color):
        cls = "pos" if v > 0 else "neg" if v < 0 else ""
        return (f'<div class="chip" style="border-top:3px solid {color}">'
                f'<span>{label}</span><b class="{cls}">{fmt(v)}억</b></div>')
    chips = (chip("개인", cum["individual"], C_IND) + chip("외국인", cum["foreign"], C_FRN) +
             chip("기관", cum["inst_total"], C_INST) + chip("프로그램", cum["program"], C_TOTAL))

    # ── 기관 세부 최근 5일 ──
    detail_cols = [("fin_invest", "금융투자"), ("insurance", "보험"), ("asset_mgmt", "투신"),
                   ("bank", "은행"), ("other_fin", "기타금융"), ("pension", "연기금등"),
                   ("other_corp", "기타법인")]
    det_head = "".join(f"<th>{l}</th>" for _, l in detail_cols)
    det_body = ""
    for d, c in conf_days[-5:][::-1]:
        if "investor" not in c:
            continue
        tds = "".join(cell(c["investor"].get(k)) for k, _ in detail_cols)
        det_body += f'<tr><th>{d[5:]}</th>{tds}</tr>'

    # ── 현·선물 흐름 (K200 선물) ──
    fut_now, fut_src = fut_snapshot(today)
    both = [(d, c["investor"], c["futures"]) for d, c in conf_days
            if "investor" in c and "futures" in c][-20:]
    snap_latest = slots[slot_keys[-1]] if slot_keys else {}
    spot_f = conf_inv["foreign"] if conf_inv else snap_latest.get("foreign")
    spot_i = conf_inv["inst_total"] if conf_inv else snap_latest.get("institution")

    def quad_card(name, color, spot, futv):
        q = fut_quadrant(spot, futv)
        if q is None:
            return ""
        combo, desc, cls = q
        return (f'<div class="chip" style="border-top:3px solid {color}">'
                f'<span>{name} · 현물 {fmt(spot)}억 / 선물 {fmt(futv)}{fut_unit}</span>'
                f'<b class="{cls}" style="font-size:14px">{combo}</b>'
                f'<span>{desc}</span></div>')

    if fut_now or both:
        quads = ""
        if fut_now:
            quads = (quad_card("외국인", C_FRN, spot_f, fut_now["foreign"])
                     + quad_card("기관", C_INST, spot_i, fut_now["inst"]))
            quads = (f'<div class="chips">{quads}</div>'
                     f'<p class="note">선물 수치 기준: {fut_src} · 단위 {fut_unit}</p>') if quads else ""
        fut_cum_f = sum(f["foreign"] for _, _, f in both)
        fut_cum_i = sum(f["inst_total"] for _, _, f in both)
        cum_note = (f'<p class="note">최근 {len(both)}영업일 누적 선물 순매수: '
                    f'외국인 {fmt(fut_cum_f)}{fut_unit} · 기관 {fmt(fut_cum_i)}{fut_unit}</p>'
                    if both else "")
        frn_combo = combo_chart([(d, inv["foreign"], f["foreign"])
                                 for d, inv, f in both], C_FRN, fut_unit)
        inst_combo = combo_chart([(d, inv["inst_total"], f["inst_total"])
                                  for d, inv, f in both], C_INST, fut_unit)
        fut_section = f"""
<h2>🔀 현·선물 흐름 <span class="na" style="font-weight:400;font-size:12px">(K200 선물 · {fut_unit})</span></h2>
{quads}
<div class="card"><p class="ctitle" style="color:{C_FRN}">외국인 — 현물 vs 선물</p>{frn_combo}</div>
<div class="card"><p class="ctitle" style="color:{C_INST}">기관 — 현물 vs 선물</p>{inst_combo}</div>
{cum_note}"""
    else:
        fut_section = ('<h2>🔀 현·선물 흐름 <span class="na" style="font-weight:400;'
                       'font-size:12px">(K200 선물)</span></h2><div class="card">'
                       '<p class="na">선물 데이터 수집 대기 중 — 다음 수집 사이클부터 표시</p></div>'
                       if is_latest else "")

    # ── 시그널 ──
    prev_snap = slots[slot_keys[-2]] if len(slot_keys) >= 2 else None
    sig = build_signals(today, prev_snap, fut_now, fut_src, fut_unit)
    sig_html = "".join(f"<li>{s}</li>" for s in sig) or "<li>특이 신호 없음</li>"

    chg = kospi.get("chg_pct", 0)
    chg_cls = "pos" if chg > 0 else "neg" if chg < 0 else ""
    arrow = "▲" if chg > 0 else "▼" if chg < 0 else "–"
    close = kospi.get("close")
    if isinstance(close, (int, float)):
        kospi_html = f'KOSPI {close:,} <span class="{chg_cls}">{arrow} {abs(chg)}%</span>'
    else:
        kospi_html = 'KOSPI <span class="na">지수 데이터 없음</span>'
    latest_label = SLOT_LABEL.get(slot_keys[-1], "-") if slot_keys else "-"
    updated = hist.get("updated_kst", "")
    upd_txt = ""   # 갱신 시각은 아래 sched 배지에서 표시
    sig_title = "🧭 오늘의 해석" if is_latest else "🧭 당일 해석"

    return f"""
<p class="sub">{t_date.month}/{t_date.day}({WD[t_date.weekday()]}) · 최근 스냅샷 {latest_label}{upd_txt}
 · 단위 억원<br>
{sched_badge(updated and updated + " KST")}</p>
<p class="kospi">{kospi_html}</p>

<h2>{sig_title}</h2>
<div class="card"><ul class="signals">{sig_html}</ul></div>

<h2>📸 시점별 스냅샷 <span class="na" style="font-weight:400;font-size:12px">(잠정치, 억원)</span></h2>
<div class="card scroll">{snap_table}{conf_note}</div>

<h2>📈 장중 누적 흐름 — 투자자별 <span class="na" style="font-weight:400;font-size:12px">({curve_day})</span></h2>
<div class="card">{inv_chart}</div>
<h2>⚙️ 장중 누적 흐름 — 프로그램 <span class="na" style="font-weight:400;font-size:12px">({curve_day})</span></h2>
<div class="card">{prg_chart}</div>
{fut_curve_html}
{fut_section}

<h2>📅 최근 20일 일별 순매수 (확정)</h2>
<div class="chips">{chips}</div>
<p class="note">최근 {n20}영업일 누적 순매수 ({dkey} 기준)</p>
<div class="card">{bars}</div>

<h2>🏦 기관 세부 — 최근 5일 (확정, 억원)</h2>
<div class="card scroll"><table>
<thead><tr><th>날짜</th>{det_head}</tr></thead><tbody>{det_body}</tbody></table></div>
"""


def build():
    hist = json.loads(HISTORY.read_text(encoding="utf-8"))
    days = hist["days"]
    all_dates = sorted(days)
    nav_dates = all_dates[-MAX_DAYS:]
    pages = {d: render_day(hist, all_dates, all_dates.index(d)) for d in nav_dates}

    date_opts = []
    for d in nav_dates:
        t = dt.date.fromisoformat(d)
        label = f"{t.month}/{t.day}({WD[t.weekday()]})"
        if d == nav_dates[-1]:
            label += " · 최신"
        date_opts.append(f'<option value="{d}">{label}</option>')

    pages_json = json.dumps(pages, ensure_ascii=False).replace("</", "<\\/")
    dates_json = json.dumps(nav_dates)

    html = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>시장 수급 동향</title>
<style>
:root{{--bg:#fff;--fg:#1c2430;--muted:#6b7684;--line:#e5e8ec;--card:#f7f8fa;
--pos:#d64545;--neg:#3b6fd4}}
@media(prefers-color-scheme:dark){{:root{{--bg:#14181f;--fg:#e6e9ee;--muted:#8b93a1;
--line:#2a313c;--card:#1b212b}}}}
*{{box-sizing:border-box}}
body{{margin:0;padding:18px 16px 40px;background:var(--bg);color:var(--fg);
font:14px/1.55 -apple-system,"Malgun Gothic","Apple SD Gothic Neo",sans-serif}}
.wrap{{max-width:820px;margin:0 auto}}
h1{{font-size:19px;margin:0 0 2px}} h2{{font-size:15px;margin:26px 0 8px}}
.sub{{color:var(--muted);font-size:12.5px;margin:0 0 14px}}
.schedq{{color:#9aa19d}}
@media(max-width:620px){{.schedq{{display:none}}}}
.sched{{display:inline-block;background:#eef2ec;border:1px solid var(--line);border-radius:4px;
padding:3px 9px;margin:3px 0;font-size:11px;color:#5b6660}}
.sched b{{color:#2c3a34}}
.kospi{{font-size:16px;font-weight:700}}
.pos{{color:var(--pos)}} .neg{{color:var(--neg)}} .na{{color:var(--muted)}}
table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}}
th,td{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;
font-size:13px;white-space:nowrap}}
th{{font-weight:600}} tr th:first-child{{text-align:left}}
thead th{{color:var(--muted);font-weight:600;font-size:12px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:14px 14px 8px;margin:8px 0}}
svg{{width:100%;height:auto;display:block}}
.grid{{stroke:var(--line);stroke-width:1}} .grid.zero{{stroke:var(--muted)}}
.tick{{fill:var(--muted);font-size:10.5px}}
.legend{{font-size:12px;margin-bottom:6px}}
.legend .unit{{float:right;color:var(--muted)}}
.chips{{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}}
.chip{{flex:1;min-width:120px;background:var(--card);border:1px solid var(--line);
border-radius:8px;padding:8px 10px;display:flex;flex-direction:column}}
.chip span{{font-size:12px;color:var(--muted)}} .chip b{{font-size:16px}}
.note{{font-size:12.5px;color:var(--muted);margin:6px 2px}}
.ctitle{{font-size:13px;font-weight:600;margin:0 0 6px}}
.signals{{margin:6px 0;padding-left:20px}} .signals li{{margin:3px 0}}
.scroll{{overflow-x:auto}}
footer{{margin-top:28px;font-size:11.5px;color:var(--muted)}}
.nav{{display:flex;align-items:center;gap:8px;margin:10px 0 4px;position:sticky;top:0;
background:var(--bg);padding:6px 0;z-index:5}}
.nav button{{background:var(--card);color:var(--fg);border:1px solid var(--line);
border-radius:8px;padding:6px 14px;font-size:14px;cursor:pointer;line-height:1}}
.nav button:disabled{{opacity:.35;cursor:default}}
.nav button:not(:disabled):hover{{border-color:var(--muted)}}
.nav select{{background:var(--card);color:var(--fg);border:1px solid var(--line);
border-radius:8px;padding:6px 8px;font-size:13px;flex:0 1 auto}}
.nav .hint{{margin-left:auto;font-size:11.5px;color:var(--muted)}}
</style></head><body><div class="wrap">
<h1>💹 시장 수급 동향 <span style="font-weight:400;font-size:13px">KOSPI</span></h1>
<div class="nav">
<button id="btn-prev" title="이전 영업일 (←)">◀</button>
<select id="sel-date">{"".join(date_opts)}</select>
<button id="btn-next" title="다음 영업일 (→)">▶</button>
<span class="hint">← → 키로도 이동</span>
</div>
<div id="day"></div>

<footer>데이터: NAVER 증권(투자자별·프로그램·K200선물 매매동향) · 장중 수치는 거래소 잠정치로 확정치와 다를 수 있음
 · 하루 4회 자동 갱신(10:00 / 13:00 / 15:40 / 16:40 KST) · 과거 {len(nav_dates)}영업일 조회 가능 · GS Research Desk</footer>
</div>
<script>
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
}}
prev.addEventListener("click", function () {{ show(idx - 1); }});
next.addEventListener("click", function () {{ show(idx + 1); }});
sel.addEventListener("change", function () {{ show(DATES.indexOf(sel.value)); }});
document.addEventListener("keydown", function (e) {{
  if (e.key === "ArrowLeft") show(idx - 1);
  else if (e.key === "ArrowRight") show(idx + 1);
}});
show(idx);
</script>
</body></html>"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"리포트 생성: {OUT} ({OUT.stat().st_size/1024:.0f} KB, {len(nav_dates)}일 임베드)")


if __name__ == "__main__":
    build()
