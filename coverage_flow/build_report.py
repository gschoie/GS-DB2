# -*- coding: utf-8 -*-
"""data/latest.json → telegram_research_dashboard/static/coverage_flow_report.html (자기완결).

표 4개: ① 외인·기관 순매수(시총 대비 정렬) ② 기계적 수급(패시브 추정 + 액티브 ETF)
③ 과매수·과매도(RSI·1년 백분위·52주 위치) ④ 섹터 ETF 설정·환매.
etf_signal_report 의 톤(Georgia 제목·Inter 본문·파란 배지)을 따른다.
"""
from __future__ import annotations
import os, sys, json, html, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import metrics  # noqa: E402

LATEST = os.path.join(HERE, "data", "latest.json")
OUT = os.path.join(ROOT, "telegram_research_dashboard", "static", "coverage_flow_report.html")
SCHEDULE_TIME = "평일 13:00 (장중) · 16:00 (장 마감 후)"
WD = "월화수목금토일"


def esc(s):
    return html.escape(str(s))


def n(v, nd=0, sign=True):
    if v is None:
        return '<span class="na">–</span>'
    cls = ("pos" if v > 0 else ("neg" if v < 0 else "")) if sign else ""
    s = f"{v:+,.{nd}f}" if sign else f"{v:,.{nd}f}"
    return f'<span class="{cls}">{s}</span>'


def streak_cell(v):
    if abs(v) < 2:
        return ""
    return f'<span class="mini {"b" if v > 0 else "s"}">{abs(v)}일째 {"매수" if v > 0 else "매도"}</span>'


def _pct(v):
    return n(v, 1) + ("%" if v is not None else "")


UP, DN = "220,38,38", "37,99,235"      # 빨강 / 파랑 (한국 증시 관행: 오르면 빨강, 내리면 파랑)


def shade(v, cap):
    """조건부서식 음영 — 열별 최대 |값|(cap) 대비 강도. **양수=빨강·음수=파랑**(한국 증시 관행,
    사용자 지정 — .pos/.neg·스파크와 같은 체계).

    0·결측은 음영 없음. 알파 0.08~0.45 — 글자(진한 빨강/파랑)가 살고, 텔레 캡쳐 앨범으로
    축소돼도 켜짐/꺼짐이 구분되는 하한을 둔다.
    """
    if not v or not cap:
        return ""
    alpha = 0.08 + 0.37 * min(abs(v) / cap, 1.0)
    rgb = UP if v > 0 else DN
    return f' style="background:rgba({rgb},{alpha:.2f})"'


def col_caps(values_by_key):
    """{열키: [값…]} → {열키: max|값|} (전부 결측이면 0 → 음영 없음)."""
    return {k: max((abs(v) for v in vs if v is not None), default=0.0)
            for k, vs in values_by_key.items()}


def spark_svg(vals, w=120, h=30):
    """종가 목록 → 인라인 SVG 선 차트. 첫 값 대비 끝 값이 오르면 초록, 내리면 빨강. 데이터 없으면 빈칸."""
    pts = [v for v in (vals or []) if v is not None]
    if len(pts) < 2:
        return '<span class="na">–</span>'
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1.0
    step = (w - 2) / (len(pts) - 1)
    coords = " ".join(f"{1 + i * step:.1f},{1 + (h - 2) * (1 - (v - lo) / span):.1f}" for i, v in enumerate(pts))
    color = f"rgb({UP})" if pts[-1] >= pts[0] else f"rgb({DN})"
    return (f'<svg class="spark" width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-label="3개월 주가">'
            f'<polyline fill="none" stroke="{color}" stroke-width="1.5" points="{coords}"/></svg>')

# 표의 업종 묶음: 조선(조선+조기) · 방산 · 기계(건기). 성광벤드·태광은 사용자 지정으로 조선 묶음 맨 밑.
GROUPS = (("조선", ("조선", "조기")), ("방산", ("방산",)), ("기계", ("건기",)))
PIN_LAST = ("성광벤드", "태광")


def group_of(r):
    ind = r.get("industry", "")
    for g, inds in GROUPS:
        if ind in inds:
            return g
    return "기타"


def grouped(rows, key, reverse=False):
    """[(묶음명, 정렬된 행들)] — 묶음 안은 key 로 정렬하되 PIN_LAST 종목은 순서 유지한 채 맨 뒤."""
    out = []
    for g, _ in GROUPS + (("기타", ()),):
        rs = [r for r in rows if group_of(r) == g]
        if not rs:
            continue
        main = sorted([r for r in rs if r.get("name") not in PIN_LAST], key=key, reverse=reverse)
        tail = [r for r in rs if r.get("name") in PIN_LAST]
        tail.sort(key=lambda r: PIN_LAST.index(r["name"]))
        out.append((g, main + tail))
    return out


def mcap_key(r):
    """표 정렬 공통 키 — 시총(억) 내림차순. 시총을 모르면 맨 뒤(사용자 요청 10/19: 기업 정렬은 시총 순)."""
    v = (r.get("px") or {}).get("mcap")
    return v if v is not None else -1e18


def group_row(g, ncol):
    return f"<tr class='gh'><td colspan='{ncol}'>{esc(g)}</td></tr>"


def agg(vals, how):
    """묶음 요약 — how='mean' 단순평균 / 'sum' 합계. None 은 빼고, 값이 하나도 없으면 None."""
    xs = [v for v in vals if v is not None]
    if not xs:
        return None
    return sum(xs) / len(xs) if how == "mean" else sum(xs)


def frgn_cell(px):
    """외인 보유비율 칸. 직전 수집값으로 채운 경우(frgn_pct_asof) 기준일을 작게 병기."""
    v = px.get("frgn_pct")
    if v is None:
        return "<td class='r'><span class=na>–</span></td>"
    asof = px.get("frgn_pct_asof") or ""
    tag = f" <small class='stale'>{esc(asof[5:].replace('-', '/'))}</small>" if asof else ""
    return f"<td class='r'>{n(v, 1, sign=False)}%{tag}</td>"


def returns_table(rows):
    """등락률 표: 오늘 · 1W · 1M · 3M · YTD (+ 외인 보유 · 시총)."""
    rs = [r for r in rows if r.get("tech")]
    key = mcap_key
    ret_keys = ("d1", "w1", "m1", "m3", "ytd")
    caps = col_caps({k: [(r["tech"].get("ret") or {}).get(k) for r in rs] for k in ret_keys})
    tr = []
    for g, grs in grouped(rs, key, reverse=True):
        tr.append(group_row(g, 9))
        for r in grs:
            ret, px = r["tech"].get("ret") or {}, r.get("px", {})
            tr.append(f"<tr><td>{esc(r['name'])}<small>{esc(r['industry'])}{' · ' + esc(r['status']) if r['status'] != '커버리지' else ''}</small></td>"
                      + "".join(f"<td class='r'{shade(ret.get(k), caps[k])}>{_pct(ret.get(k))}</td>" for k in ret_keys)
                      + f"<td class='c'>{spark_svg(r['tech'].get('spark'))}</td>"
                      + frgn_cell(px)
                      + f"<td class='r'>{n(px.get('mcap'), 0, sign=False)}</td></tr>")
        # 묶음 요약: 등락률 단순평균(10/20 사용자 요청) + 시총 합계
        avg = {k: agg([(r["tech"].get("ret") or {}).get(k) for r in grs], "mean") for k in ret_keys}
        mcap_sum = agg([(r.get("px") or {}).get("mcap") for r in grs], "sum")
        tr.append(f"<tr class='sub'><td>{esc(g)} 평균<small>{len(grs)}종목 · 단순평균</small></td>"
                  + "".join(f"<td class='r'{shade(avg[k], caps[k])}>{_pct(avg[k])}</td>" for k in ret_keys)
                  + f"<td class='c'></td><td class='r'></td><td class='r'>{n(mcap_sum, 0, sign=False)}</td></tr>")
    return ("<table><thead><tr><th>종목</th><th class='r'>오늘</th><th class='r'>1주</th><th class='r'>1개월</th>"
            "<th class='r'>3개월</th><th class='r'>YTD</th><th class='c'>3개월 차트</th><th class='r'>외인 보유</th><th class='r'>시총(억)</th></tr></thead>"
            f"<tbody>{''.join(tr)}</tbody></table>")


def flow_table(rows):
    """투자자별 순매수(억원) 표: 외인 · 기관 · 개인 × (오늘 · 5일 · 1개월 · 3개월 · YTD).
    5일 칸에 연속일수 배지. 정렬은 시총 순."""
    rs = [r for r in rows if r.get("flow")]
    key = mcap_key
    tr = []
    keys = ("today", "d5", "m1", "m3", "ytd")
    caps = col_caps({(who, k): [((r["flow"].get("win") or {}).get(who) or {}).get(k) for r in rs]
                     for who in ("frgn", "inst", "indiv") for k in keys})
    for g, grs in grouped(rs, key, reverse=True):
        tr.append(group_row(g, 16))
        for r in grs:
            f = r["flow"]; w = f.get("win") or {}
            cells = []
            for who, sk in (("frgn", "frgn_streak"), ("inst", "inst_streak"), ("indiv", None)):
                ww = w.get(who) or {}
                for k in keys:
                    v = ww.get(k)
                    badge = streak_cell(f.get(sk, 0)) if (k == "d5" and sk) else ""
                    cls = "r grp" if k == "today" else "r"
                    cells.append(f"<td class='{cls}'{shade(v, caps[(who, k)])}>{n(v)}{(' ' + badge) if badge else ''}</td>")
            tr.append(f"<tr><td>{esc(r['name'])}</td>{''.join(cells)}</tr>")
        # 묶음 요약: 투자자별 순매수 합계(10/20 사용자 요청)
        cells = []
        for who in ("frgn", "inst", "indiv"):
            for k in keys:
                tot = agg([((r["flow"].get("win") or {}).get(who) or {}).get(k) for r in grs], "sum")
                cls = "r grp" if k == "today" else "r"
                cells.append(f"<td class='{cls}'{shade(tot, caps[(who, k)])}>{n(tot)}</td>")
        tr.append(f"<tr class='sub'><td>{esc(g)} 합계<small>{len(grs)}종목</small></td>{''.join(cells)}</tr>")
    sub = "".join(f"<th class='r{' grp' if k == 'today' else ''}'>{lbl}</th>" for _ in range(3) for k, lbl in zip(keys, ("오늘", "5일", "1개월", "3개월", "YTD")))
    return ("<table class='flow'><thead><tr><th rowspan='2'>종목</th><th colspan='5' class='grp c'>외국인</th><th colspan='5' class='grp c'>기관</th><th colspan='5' class='grp c'>개인</th></tr>"
            f"<tr>{sub}</tr></thead><tbody>{''.join(tr)}</tbody></table>")


def passive_table(rows, etfs, active, active_date):
    ps = [r for r in rows if r.get("passive")]
    ps.sort(key=lambda r: abs(r["passive"].get("adv_pct") or 0), reverse=True)
    tr = []
    for r in ps:
        p = r["passive"]
        src = " · ".join(f"{esc(e)} {a:+,.1f}" for e, a in p.get("etfs", [])[:3])
        tr.append(f"<tr><td>{esc(r['name'])}</td><td class='r'>{n(p.get('amt'), 1)}</td>"
                  f"<td class='r'><b>{n(p.get('adv_pct'), 1)}%</b></td><td>{esc(metrics.passive_label(p.get('adv_pct')))}</td>"
                  f"<td><small>{src}</small></td></tr>")
    first = not any(e.get("delta_shares") is not None for e in etfs)
    body = (f"<tbody>{''.join(tr)}</tbody>" if tr else
            f"<tbody><tr><td colspan='5' class='empty'>{'첫 수집 — 섹터 ETF 설정·환매 비교는 다음 거래일부터 채워집니다.' if first else '유니버스 종목에 걸린 패시브 매매가 없습니다(Top10 비중 밖이거나 설정·환매 0).'}</td></tr></tbody>")
    pt = ("<table><thead><tr><th>종목</th><th class='r'>추정 매매(억)</th><th class='r'>ADV 대비</th><th>상태</th><th>기여 ETF</th></tr></thead>" + body + "</table>")
    et = []
    for e in etfs:
        d = e.get("delta_shares")
        ref = f"<small>{esc(e.get('inflow_ref'))}</small>" if e.get("inflow_ref") else ""
        et.append(f"<tr><td>{esc(e.get('name'))}<small>{esc(e.get('code'))}</small></td>"
                  f"<td class='r'>{n(d, 0) if d is not None else '<span class=na>직전 값 없음</span>'}</td>"
                  f"<td class='r'>{n(e.get('amt'), 1)}</td>"
                  f"<td class='r'>{n(e.get('listed'), 0, sign=False) if e.get('listed') else '–'}</td>"
                  f"<td class='r'>{n(e.get('inflow_1d'), 1)} / {n(e.get('inflow_1w'), 0)}{ref}</td></tr>")
    etft = ("<table class='compact'><thead><tr><th>섹터 ETF</th><th class='r'>상장주수 변동</th><th class='r'>설정·환매(억)</th><th class='r'>상장주수</th>"
            "<th class='r'>네이버 순유입 1d / 1w(억)<br><small>교차 확인 · 기준일 하루 지연</small></th></tr></thead>"
            f"<tbody>{''.join(et) or '<tr><td colspan=5 class=empty>ETF 수집 없음</td></tr>'}</tbody></table>")
    at = []
    for h in active:
        pct = f"{h['pct']:+.0f}%" if h.get("pct") is not None else ""
        at.append(f"<tr><td>{esc(h['etf'])}</td><td>{esc(h['stock'])}</td>"
                  f"<td><span class='mini {'b' if h['kind'] in ('편입', '증가') else 's'}'>{esc(h['kind'])}</span> {pct}</td>"
                  f"<td class='r'>{esc(h.get('weight') or '')}%</td></tr>")
    actt = (f"<h3>액티브 ETF 계약수 변동 <small>액티브ETF.매매동향 {esc(active_date)} 기준 · 유니버스 종목만</small></h3>"
            "<table class='compact'><thead><tr><th>ETF</th><th>종목</th><th>변동</th><th class='r'>비중</th></tr></thead>"
            f"<tbody>{''.join(at) or '<tr><td colspan=4 class=empty>오늘 액티브 ETF 에서 유니버스 종목의 계약수 변동 없음</td></tr>'}</tbody></table>")
    return pt + "<h3>섹터 ETF 설정·환매 <small>상장주수 변동 × 가격. 직전 거래일 저장값 대비</small></h3>" + etft + actt


def tech_table(rows):
    ts = [r for r in rows if r.get("tech")]
    key = mcap_key
    tr = []
    for g, grs in grouped(ts, key, reverse=True):
        tr.append(group_row(g, 8))
        for r in grs:
            t = r["tech"]
            rsi = t.get("rsi")
            cls = "rsi-lo" if rsi is not None and rsi <= metrics.RSI_LO else ("rsi-hi" if rsi is not None and rsi >= metrics.RSI_HI else "")
            pct = t.get("rsi_pctl")
            pct_s = "–" if pct is None else (f"하위 {pct:.0f}%" if pct <= 50 else f"상위 {100 - pct:.0f}%")
            ex = f"<span class='mini {'b' if metrics.pctl_or(pct, 50) <= 50 else 's'}'>{esc(t['extreme'])}</span>" if t.get("extreme") else ""
            rsi_s = "" if rsi is None else f"{rsi:.0f}"
            prev_s = "" if t.get("rsi_prev") is None else f"{t['rsi_prev']:.0f}"
            tr.append(f"<tr><td>{esc(r['name'])}</td><td class='r {cls}'>{rsi_s}</td>"
                      f"<td class='r'>{prev_s}</td>"
                      f"<td class='r'>{pct_s}</td><td>{ex}</td>"
                      f"<td class='r'>{n(t.get('hi52_pct'), 1)}%</td><td class='r'>{n(t.get('lo52_pct'), 1)}%</td>"
                      f"<td class='r'>{n(t.get('adv20'), 0, sign=False)}</td></tr>")
    return ("<table><thead><tr><th>종목</th><th class='r'>RSI(14)<br><small>잠정</small></th><th class='r'>전일 확정</th>"
            "<th class='r'>1년 백분위</th><th>극단</th><th class='r'>52주 고가 대비</th><th class='r'>52주 저가 대비</th><th class='r'>20일 ADV(억)</th></tr></thead>"
            f"<tbody>{''.join(tr)}</tbody></table>")


def summary_tiles(rows, d):
    buy, sell = metrics.rank_flow(rows)
    ex_lo = [r["name"] for r in rows if r.get("tech", {}).get("extreme") and metrics.pctl_or(r["tech"].get("rsi_pctl"), 50) <= 50]
    ex_hi = [r["name"] for r in rows if r.get("tech", {}).get("extreme") and metrics.pctl_or(r["tech"].get("rsi_pctl"), 50) > 50]
    pas = [r["name"] for r in rows if r.get("passive") and abs(r["passive"].get("adv_pct") or 0) >= 3]
    def tile(label, items, cls):
        body = esc(" · ".join(items)) if items else "<span class='na'>없음</span>"
        return f"<a class='tile' href='#{cls}'><small>{label}</small><div class='names'>{body}</div></a>"
    return ("<div class='stats'>" +
            tile("사는 쪽 (시총 대비 5일)", [r["name"] for r in buy], "flow") +
            tile("파는 쪽 (시총 대비 5일)", [r["name"] for r in sell], "flow") +
            tile("RSI 1년 최저권", ex_lo, "tech") +
            tile("RSI 1년 최고권", ex_hi, "tech") +
            tile("패시브 ADV ±3% 이상", pas, "passive") + "</div>")


def render(d):
    rows = d.get("rows", [])
    try:
        t = datetime.datetime.strptime(d["asof"], "%Y-%m-%d %H:%M")
        asof = f"{t.month}/{t.day}({WD[t.weekday()]}) {t:%H:%M}"
    except Exception:
        asof = d.get("asof", "")
    prov = any(r.get("flow", {}).get("has_today") for r in rows)
    est_times = sorted({r["flow"]["today_src"].split(" ", 1)[1] for r in rows
                        if str(r.get("flow", {}).get("today_src", "")).startswith("estimate ")})
    est_line = (f"<b>오늘(장중)은 한투 종목별 외인·기관 추정가집계 {' · '.join(est_times)} 기준</b> — 추정 순매수 수량 × 현재가 근사, "
                "개인은 −(외인+기관)로 둔 값(확정치는 장 마감 뒤 일별 집계로 대체)." if est_times else "")
    errs = d.get("errors", [])
    err_html = (f"<details class='errs'><summary>수집 오류 {len(errs)}건</summary><ul>{''.join(f'<li>{esc(e)}</li>' for e in errs)}</ul></details>" if errs else "")
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>커버리지 수급·기술지표</title>
<style>
:root{{--ink:#111827;--muted:#6b7280;--line:#e5e7eb;--blue:#2b5f8a}}
*{{box-sizing:border-box}}body{{margin:0 auto;max-width:1180px;background:#fff;color:var(--ink);font-family:Inter,Pretendard,"Noto Sans KR",sans-serif;padding:28px 30px 60px}}
details.sec>summary{{cursor:pointer;list-style:none}}details.sec>summary::-webkit-details-marker{{display:none}}
details.sec>summary h2::before{{content:"▶ ";font-size:13px;color:#6b7280}}details.sec[open]>summary h2::before{{content:"▼ "}}
svg.spark{{display:block;margin:0 auto}}td.c{{text-align:center}}
small.stale{{color:#9ca3af;font-size:10px}}
.eyebrow{{font-size:10px;font-weight:800;letter-spacing:1.6px;color:#6b7280;margin:0 0 7px}}
h1{{font:500 30px Georgia,"Noto Serif KR",serif;margin:0}}
h2{{font:600 18px Georgia,"Noto Serif KR",serif;margin:34px 0 10px}}
h3{{font:600 14px Inter;margin:22px 0 8px}}h3 small{{color:var(--muted);font-weight:400;margin-left:6px}}
.sub{{color:var(--muted);font-size:12px;margin:8px 0 0;line-height:1.6}}.sub b{{color:#4b5563}}
.asof{{margin:34px 0 0;font-size:12px;color:#6b7280}}.asof b{{color:#111827}}
.sched{{display:inline-block;background:#eff6ff;border:1px solid var(--line);border-radius:4px;padding:3px 9px;margin:3px 0;font-size:11px;color:#6b7280}}.sched b{{color:#1d4ed8}}
.stats{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin:22px 0 8px}}
@media(max-width:900px){{.stats{{grid-template-columns:repeat(2,minmax(0,1fr))}}body{{padding:16px}}}}
.tile{{border:1px solid var(--line);padding:14px 16px;text-decoration:none;color:inherit;display:block}}
.tile small{{color:var(--muted);font-size:11px;font-weight:700;letter-spacing:.04em}}
.tile .names{{font:500 15px Georgia,"Noto Serif KR",serif;margin-top:8px;line-height:1.45}}
table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
th{{font-size:11px;color:var(--muted);font-weight:700;letter-spacing:.03em;background:#f9fafb}}th small{{font-weight:400}}
td small{{display:block;color:var(--muted);font-size:11px}}
th.r,td.r{{text-align:right;font-variant-numeric:tabular-nums}}
.pos{{color:#b91c1c}}.neg{{color:#1d4ed8}}.na{{color:#9ca3af}}
.mini{{display:inline-block;font-size:10px;font-weight:800;padding:1px 6px;border-radius:3px;margin-left:4px;white-space:nowrap}}
.mini.b{{background:#fde2e2;color:#b91c1c}}.mini.s{{background:#dbe6fd;color:#1d4ed8}}
.rsi-lo{{color:#1d4ed8;font-weight:700}}.rsi-hi{{color:#b91c1c;font-weight:700}}
td.empty{{color:var(--muted);text-align:center;padding:18px}}
tr.sub td{{font-weight:800;color:var(--ink);border-top:2px solid #94a3b8;border-bottom:2px solid #94a3b8;background:#f1f5f9}}tr.sub td .pos,tr.sub td .neg{{font-weight:800}}tr.sub td small{{font-weight:400;font-size:11px}}
tr.gh td{{background:#eef2f7;color:#1f2937;font:700 12px Georgia,"Noto Serif KR",serif;letter-spacing:.06em;padding:6px 8px}}
table.compact{{font-size:12px}}
table.flow{{font-size:12px}}table.flow td,table.flow th{{padding:6px 5px}}th.c{{text-align:center}}td.grp,th.grp{{border-left:2px solid #e5e7eb}}
.note{{font-size:12px;color:var(--muted);line-height:1.6;margin:8px 0 0}}
.errs{{margin:16px 0;font-size:12px;color:#b45309}}.errs ul{{margin:6px 0 0 18px}}
.wrap{{overflow-x:auto}}
#cap-1,#cap-2,#cap-3,#cap-1a,#cap-1b{{padding:6px 0 4px;background:#fff}}
</style></head><body>
<div id="cap-1">
<div id="cap-1a">
<p class="eyebrow">COVERAGE · FLOW &amp; TECHNICALS</p>
<h1>커버리지 기업 수급 / 기술적 지표</h1>
<p class="sub">조선·방산·건설기계 커버리지 + 커버예정 <b>{len(rows)}종목</b>. 외인·기관 순매수(시총 대비) · 섹터 ETF 패시브 추정 + 액티브 ETF 계약수 · RSI 1년 극단.
{'장중 숫자는 <b>잠정치</b>(오늘 행 포함). ' if prov else ''}규칙 기반 상태값이며 검증 전입니다.</p>
<span class="sched">🕙 정기 업데이트 <b>{SCHEDULE_TIME}</b>(한국시간) · 실제 갱신 <b>{esc(asof)}</b> · 슬롯 {esc(d.get('slot', ''))}</span>
{err_html}
{summary_tiles(rows, d)}

<p class="asof">📅 수집 시각 <b>{esc(asof)}</b> · {'장중 잠정(오늘 현재가·오늘 수급 포함)' if prov else '직전 거래일 종가 기준(장 시작 전 또는 휴장일 수집)'}</p>
<h2 id="flow" style="margin-top:6px">① 등락률 <small style="font:400 12px Inter;color:#6b7280">오늘 · 1주 · 1개월 · 3개월 · YTD</small></h2>
<div class="wrap">{returns_table(rows)}</div>
<p class="note">오늘은 전일 종가 대비(장중 현재가). 1주·1개월·3개월은 거래일 5·21·63일 전 종가 대비, YTD 는 전년 마지막 종가 대비. 외인 보유 옆의 작은 날짜는 장 시작 전·휴장이라 그 날짜의 직전 수집값으로 채운 것 — 장중 첫 수집부터 당일 값으로 바뀐다.</p>

</div>
<div id="cap-1b">
<h2 id="flow2">①-2 투자자별 순매수 <small style="font:400 12px Inter;color:#6b7280">억원 · 오늘 · 5일 · 1개월 · 3개월 · YTD · 시총 순</small></h2>
<div class="wrap">{flow_table(rows)}</div>
<p class="note">구간은 오늘 잠정 행을 포함한 최근 거래일 수(5·21·63일, YTD 는 올해 1월부터). 최근 30거래일은 한투 금액(정확), 그 이전은 네이버 순매수 수량 × 종가 <b>근사</b> — 3개월·YTD 합계는 체결 평균가 대신 종가를 써서 몇 % 어긋날 수 있다. 이력이 모자라는 구간은 '–'. 연속일수 배지는 2일 이상만. {est_line}</p>
</div>
</div>
<div id="cap-2">
<h2 id="tech">② 과매수 · 과매도 <small style="font:400 12px Inter;color:#6b7280">RSI(14, Wilder) · 1년 백분위 · 52주 위치</small></h2>
<div class="wrap">{tech_table(rows)}</div>
<p class="note">RSI 잠정 = 오늘 현재가를 종가로 둔 값, 전일 확정과 나란히 둔다. 1년 백분위는 확정 RSI 252거래일 분포 안에서 잠정 RSI 의 자리 — 하위/상위 {metrics.EXTREME_PCTL}% 안이면 극단. 30 이하 진입은 ETF 신호판 백테스트에서 '1주 단기 반등' 성격(D+5 +0.9%p)이었고 70 하향이탈은 역방향이었다.</p>
</div>
<details id="cap-3" class="sec">
<summary><h2 id="passive">③ 기계적 수급 <small style="font:400 12px Inter;color:#6b7280">ETF 설정·환매 × 비중 (하한값) · 액티브 ETF 계약수 — 펼치기</small></h2></summary>
<div class="wrap">{passive_table(rows, d.get('etfs', []), d.get('active', []), d.get('active_date', ''))}</div>
<p class="note">패시브 추정 = Σ(섹터 ETF 상장주수 변동 × 가격 × 종목 비중). 비중은 네이버 Top10 구성종목만 있어 비중 밖 종목의 몫은 잡히지 않는다 → 하한값. ADV 대비 = 추정 매매 / 20일 평균 거래대금.</p>
</details>
<p class="note" style="margin-top:28px">출처: 한국투자증권 OpenAPI(일봉·투자자별·현재가·상장주수) · 네이버 증권(ETF 구성 비중) · 액티브ETF.매매동향(etf_holdings). 유니버스는 <code>coverage_flow/universe.csv</code>, 섹터 ETF 는 <code>etf_universe.csv</code>.</p>
</body></html>"""


def main():
    with open(LATEST, encoding="utf-8") as f:
        d = json.load(f)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(render(d))
    print("wrote", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()
