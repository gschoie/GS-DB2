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
SCHEDULE_TIME = "평일 10:00 · 13:30 · 15:30"
WD = "월화수목금토일"


def esc(s):
    return html.escape(str(s))


def n(v, nd=0, sign=True):
    if v is None:
        return '<span class="na">–</span>'
    cls = "pos" if v > 0 else ("neg" if v < 0 else "")
    s = f"{v:+,.{nd}f}" if sign else f"{v:,.{nd}f}"
    return f'<span class="{cls}">{s}</span>'


def streak_cell(v):
    if abs(v) < 2:
        return ""
    return f'<span class="mini {"b" if v > 0 else "s"}">{abs(v)}일째 {"매수" if v > 0 else "매도"}</span>'


def flow_table(rows):
    rs = [r for r in rows if r.get("flow")]
    rs.sort(key=lambda r: r["flow"].get("fi5_mcap_pct") if r["flow"].get("fi5_mcap_pct") is not None else -1e9, reverse=True)
    tr = []
    for r in rs:
        f, px = r["flow"], r.get("px", {})
        today = (f"{n(f.get('frgn_today'))} / {n(f.get('inst_today'))}" if f.get("has_today") else '<span class="na">–</span>')
        tr.append(f"<tr><td>{esc(r['name'])}<small>{esc(r['industry'])}{' · ' + esc(r['status']) if r['status'] != '커버리지' else ''}</small></td>"
                  f"<td class='r'>{n(px.get('chg_pct'), 1)}%</td>"
                  f"<td class='r'><b>{n(f.get('fi5_mcap_pct'), 2)}%</b></td>"
                  f"<td class='r'>{n(f.get('frgn5'))} {streak_cell(f.get('frgn_streak', 0))}</td>"
                  f"<td class='r'>{n(f.get('inst5'))} {streak_cell(f.get('inst_streak', 0))}</td>"
                  f"<td class='r'>{n(f.get('indiv5'))}</td>"
                  f"<td class='r'>{today}</td>"
                  f"<td class='r'>{n(px.get('frgn_pct'), 2, sign=False)}%</td>"
                  f"<td class='r'>{n(px.get('mcap'), 0, sign=False)}</td></tr>")
    return ("<table><thead><tr><th>종목</th><th class='r'>등락</th><th class='r'>5일 외인+기관<br><small>시총 대비</small></th>"
            "<th class='r'>외인 5일</th><th class='r'>기관 5일</th><th class='r'>개인 5일</th>"
            "<th class='r'>오늘(잠정)<br><small>외인 / 기관</small></th><th class='r'>외인 보유</th><th class='r'>시총(억)</th></tr></thead>"
            f"<tbody>{''.join(tr)}</tbody></table>")


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
        et.append(f"<tr><td>{esc(e.get('name'))}<small>{esc(e.get('code'))}</small></td>"
                  f"<td class='r'>{n(d, 0) if d is not None else '<span class=na>직전 값 없음</span>'}</td>"
                  f"<td class='r'>{n(e.get('amt'), 1)}</td>"
                  f"<td class='r'>{n(e.get('listed'), 0, sign=False) if e.get('listed') else '–'}</td></tr>")
    etft = ("<table class='compact'><thead><tr><th>섹터 ETF</th><th class='r'>상장주수 변동</th><th class='r'>설정·환매(억)</th><th class='r'>상장주수</th></tr></thead>"
            f"<tbody>{''.join(et) or '<tr><td colspan=4 class=empty>ETF 수집 없음</td></tr>'}</tbody></table>")
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
    ts.sort(key=lambda r: r["tech"].get("rsi") if r["tech"].get("rsi") is not None else 50)
    tr = []
    for r in ts:
        t = r["tech"]
        rsi = t.get("rsi")
        cls = "rsi-lo" if rsi is not None and rsi <= metrics.RSI_LO else ("rsi-hi" if rsi is not None and rsi >= metrics.RSI_HI else "")
        pct = t.get("rsi_pctl")
        pct_s = "–" if pct is None else (f"하위 {pct:.0f}%" if pct <= 50 else f"상위 {100 - pct:.0f}%")
        ex = f"<span class='mini {'b' if (pct or 50) <= 50 else 's'}'>{esc(t['extreme'])}</span>" if t.get("extreme") else ""
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
    ex_lo = [r["name"] for r in rows if r.get("tech", {}).get("extreme") and (r["tech"].get("rsi_pctl") or 50) <= 50]
    ex_hi = [r["name"] for r in rows if r.get("tech", {}).get("extreme") and (r["tech"].get("rsi_pctl") or 50) > 50]
    pas = [r["name"] for r in rows if r.get("passive") and abs(r["passive"].get("adv_pct") or 0) >= 3]
    def tile(label, items, cls):
        body = esc(" · ".join(items)) if items else "<span class='na'>없음</span>"
        return f"<a class='tile' href='#{cls}'><small>{label}</small><div class='names'>{body}</div></a>"
    return ("<div class='stats'>" +
            tile("사는 쪽 (시총 대비 5일)", [r["name"] for r in buy], "flow") +
            tile("파는 쪽 (시총 대비 5일)", [r["name"] for r in sell], "flow") +
            tile("패시브 ADV ±3% 이상", pas, "passive") +
            tile("RSI 1년 최저권", ex_lo, "tech") +
            tile("RSI 1년 최고권", ex_hi, "tech") + "</div>")


def render(d):
    rows = d.get("rows", [])
    try:
        t = datetime.datetime.strptime(d["asof"], "%Y-%m-%d %H:%M")
        asof = f"{t.month}/{t.day}({WD[t.weekday()]}) {t:%H:%M}"
    except Exception:
        asof = d.get("asof", "")
    prov = any(r.get("flow", {}).get("has_today") for r in rows)
    errs = d.get("errors", [])
    err_html = (f"<details class='errs'><summary>수집 오류 {len(errs)}건</summary><ul>{''.join(f'<li>{esc(e)}</li>' for e in errs)}</ul></details>" if errs else "")
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>커버리지 수급·기술지표</title>
<style>
:root{{--ink:#111827;--muted:#6b7280;--line:#e5e7eb;--blue:#2b5f8a}}
*{{box-sizing:border-box}}body{{margin:0;background:#fff;color:var(--ink);font-family:Inter,Pretendard,"Noto Sans KR",sans-serif;padding:28px 30px 60px}}
.eyebrow{{font-size:10px;font-weight:800;letter-spacing:1.6px;color:#6b7280;margin:0 0 7px}}
h1{{font:500 30px Georgia,"Noto Serif KR",serif;margin:0}}
h2{{font:600 18px Georgia,"Noto Serif KR",serif;margin:34px 0 10px}}
h3{{font:600 14px Inter;margin:22px 0 8px}}h3 small{{color:var(--muted);font-weight:400;margin-left:6px}}
.sub{{color:var(--muted);font-size:12px;margin:8px 0 0;line-height:1.6}}.sub b{{color:#4b5563}}
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
.pos{{color:#15803d}}.neg{{color:#dc2626}}.na{{color:#9ca3af}}
.mini{{display:inline-block;font-size:10px;font-weight:800;padding:1px 6px;border-radius:3px;margin-left:4px;white-space:nowrap}}
.mini.b{{background:#dcf5e7;color:#0f7a45}}.mini.s{{background:#fbe1dd;color:#b03a2e}}
.rsi-lo{{color:#0f7a45;font-weight:700}}.rsi-hi{{color:#b03a2e;font-weight:700}}
td.empty{{color:var(--muted);text-align:center;padding:18px}}
table.compact{{font-size:12px}}
.note{{font-size:12px;color:var(--muted);line-height:1.6;margin:8px 0 0}}
.errs{{margin:16px 0;font-size:12px;color:#b45309}}.errs ul{{margin:6px 0 0 18px}}
.wrap{{overflow-x:auto}}
</style></head><body>
<p class="eyebrow">COVERAGE · FLOW &amp; TECHNICALS</p>
<h1>커버리지 기업 수급 / 기술적 지표</h1>
<p class="sub">조선·방산·건설기계 커버리지 + 커버예정 <b>{len(rows)}종목</b>. 외인·기관 순매수(시총 대비) · 섹터 ETF 패시브 추정 + 액티브 ETF 계약수 · RSI 1년 극단.
{'장중 숫자는 <b>잠정치</b>(오늘 행 포함). ' if prov else ''}규칙 기반 상태값이며 검증 전입니다.</p>
<span class="sched">🕙 정기 업데이트 <b>{SCHEDULE_TIME}</b>(한국시간) · 실제 갱신 <b>{esc(asof)}</b> · 슬롯 {esc(d.get('slot', ''))}</span>
{err_html}
{summary_tiles(rows, d)}

<h2 id="flow">① 외국인·기관 순매수 <small style="font:400 12px Inter;color:#6b7280">5일 합산 억원 · 시총 대비 % 순</small></h2>
<div class="wrap">{flow_table(rows)}</div>
<p class="note">5일 창은 오늘 잠정 행을 포함한 최근 5거래일. 연속일수 배지는 2일 이상만. 시총 대비 %는 (외인+기관 5일 합산)/시총.</p>

<h2 id="passive">② 기계적 수급 <small style="font:400 12px Inter;color:#6b7280">ETF 설정·환매 × 비중 (하한값) · 액티브 ETF 계약수</small></h2>
<div class="wrap">{passive_table(rows, d.get('etfs', []), d.get('active', []), d.get('active_date', ''))}</div>
<p class="note">패시브 추정 = Σ(섹터 ETF 상장주수 변동 × 가격 × 종목 비중). 비중은 네이버 Top10 구성종목만 있어 비중 밖 종목의 몫은 잡히지 않는다 → 하한값. ADV 대비 = 추정 매매 / 20일 평균 거래대금.</p>

<h2 id="tech">③ 과매수 · 과매도 <small style="font:400 12px Inter;color:#6b7280">RSI(14, Wilder) · 1년 백분위 · 52주 위치</small></h2>
<div class="wrap">{tech_table(rows)}</div>
<p class="note">RSI 잠정 = 오늘 현재가를 종가로 둔 값, 전일 확정과 나란히 둔다. 1년 백분위는 확정 RSI 252거래일 분포 안에서 잠정 RSI 의 자리 — 하위/상위 {metrics.EXTREME_PCTL}% 안이면 극단. 30 이하 진입은 ETF 신호판 백테스트에서 '1주 단기 반등' 성격(D+5 +0.9%p)이었고 70 하향이탈은 역방향이었다.</p>

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
