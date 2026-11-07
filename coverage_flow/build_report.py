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
SERIES = os.path.join(HERE, "data", "series.json")
OUT = os.path.join(ROOT, "telegram_research_dashboard", "static", "coverage_flow_report.html")
# 지난 기록: 16:00(장 마감 후) 슬롯만 날짜별 페이지로 보관 — 최근 31일은 매일, 그보다 오래된 달은
# 월 2개(15일 이전 마지막 거래일 · 그 달 마지막 거래일)만 남긴다(10/28 사용자 요청).
ARCH_DIR = os.path.join(ROOT, "telegram_research_dashboard", "static", "coverage_flow")
ARCHIVE_SLOT = "16:00"
RECENT_DAYS = 31
SCHEDULE_TIME = "평일 11:30 (장중) · 16:00 (장 마감 후)"
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

# 표의 업종 묶음: 조선(조선+조기) · 방산 · 기계(건기+기계 — 피팅 3사 포함, 10/28 사용자 지정).
# 성광벤드·태광이 기계로 옮겨가며 '조선 맨 밑 고정'은 폐기 — PIN_LAST 는 빈 채로 장치만 남긴다.
GROUPS = (("조선", ("조선", "조기")), ("방산", ("방산",)), ("기계", ("건기", "기계")))
PIN_LAST = ()


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


def returns_table(rows, series=None):
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
            has = bool(series and series.get(r["code"]))
            tr.append(f"<tr{(' class=\'clk\' data-code=\'' + esc(r['code']) + '\' title=\'클릭: 1년 시총·수급 차트\'') if has else ''}><td>{'<span class=\'car\'>▸</span> ' if has else ''}{esc(r['name'])}<small>{esc(r['industry'])}{' · ' + esc(r['status']) if r['status'] != '커버리지' else ''}</small></td>"
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


def archive_keep(dates, today):
    """남길 날짜 집합. dates·today 는 'YYYY-MM-DD'.
    최근 RECENT_DAYS 일은 전부, 그보다 오래된 날짜는 달마다 두 개 — 15일 이전 마지막 날(없으면 그 달
    첫 날) · 그 달 마지막 날. 경계 달은 '오래된 쪽' 날짜만으로 고르므로 진짜 월말이 31일 창을 벗어나는
    날 자연히 그 날로 옮겨 간다(중간에 남겼던 날은 그때 지워진다)."""
    t = datetime.date.fromisoformat(today)
    cutoff = (t - datetime.timedelta(days=RECENT_DAYS)).isoformat()
    keep = {x for x in dates if x >= cutoff}
    months = {}
    for x in dates:
        if x < cutoff:
            months.setdefault(x[:7], []).append(x)
    for xs in months.values():
        xs.sort()
        early = [x for x in xs if int(x[8:10]) <= 15]
        keep.add(early[-1] if early else xs[0])
        keep.add(xs[-1])
    return keep


def archive_dates():
    """보관된 날짜 목록(최신순)."""
    if not os.path.isdir(ARCH_DIR):
        return []
    return sorted((f[:10] for f in os.listdir(ARCH_DIR)
                   if len(f) == 15 and f.endswith(".html") and f[4] == "-"), reverse=True)


def _wd_label(day):
    try:
        t = datetime.date.fromisoformat(day)
        return f"{day}({WD[t.weekday()]})"
    except Exception:
        return day


def archive_nav(d, archive, dates):
    """페이지 맨 위 한 줄(캡쳐 영역 밖). 최신 페이지 = 지난 기록 고르기, 지난 기록 페이지 = 최신으로 돌아가기."""
    if archive:
        return (f"<div class='arch'>🗄️ <b>지난 기록</b> · {esc(_wd_label(d.get('date', '')))} 16:00 장 마감 기준 "
                f"<a href='../coverage_flow_report.html'>← 최신 보기</a></div>")
    if not dates:
        return ""
    opts = "".join(f"<option value='coverage_flow/{x}.html'>{esc(_wd_label(x))}</option>" for x in dates)
    return ("<div class='arch'>🗄️ 지난 기록(매일 16:00 장 마감 기준) "
            "<select onchange=\"if(this.value)location.href=this.value\">"
            f"<option value=''>날짜 고르기 ({len(dates)}개)</option>{opts}</select>"
            "<small> 최근 한 달은 매일, 그 이전은 월 2개(월 중순·월말)</small></div>")

CHART_JS = r"""
<script>
const SERIES=__SERIES__;
(function(){
  const C={mc:"#111827",fr:"#2b6cb0",inn:"#b08a63"};
  function nice(lo,hi,k){const sp=(hi-lo)||1,st=Math.pow(10,Math.floor(Math.log10(sp/k))),m=sp/k/st,s=(m<1.5?1:m<3?2:m<7?5:10)*st;
    const a=Math.floor(lo/s)*s,b=Math.ceil(hi/s)*s,t=[];for(let v=a;v<=b+s/2;v+=s)t.push(+v.toFixed(6));return {t,a,b,s}}
  function fmt(v,s){return Math.abs(v)>=1e4?(v/1e4).toFixed(s<1e4?1:0)+"조":Math.round(v).toLocaleString()}
  function draw(code,months){
    const s=SERIES[code];const N=s.mc.length,from=Math.max(0,N-Math.round(months*21)),
      d=i=>"20"+s.d.slice(i*6,i*6+2)+"."+s.d.slice(i*6+2,i*6+4)+"."+s.d.slice(i*6+4,i*6+6);
    const mc=s.mc.slice(from),fr=s.fr.slice(from),inn=s["in"].slice(from),n=mc.length;
    const b0=fr[0],c0=inn[0],fr2=fr.map(x=>x-b0),in2=inn.map(x=>x-c0);   // 보는 구간 시작을 0 으로
    const W=720,H=300,L=52,R=56,T=14,B=26,pw=W-L-R,ph=H-T-B;
    const lv=nice(Math.min(...mc),Math.max(...mc),5),rv=nice(Math.min(0,...fr2,...in2),Math.max(0,...fr2,...in2),5);
    const x=i=>L+pw*i/Math.max(1,n-1),yl=v=>T+ph*(1-(v-lv.a)/(lv.b-lv.a)),yr=v=>T+ph*(1-(v-rv.a)/(rv.b-rv.a));
    const pl=(a,y)=>a.map((v,i)=>(i?"L":"M")+x(i).toFixed(1)+" "+y(v).toFixed(1)).join("");
    let g="";lv.t.forEach(v=>{g+=`<line x1="${L}" x2="${W-R}" y1="${yl(v)}" y2="${yl(v)}" stroke="#eef0f3"/><text x="${L-6}" y="${yl(v)+4}" text-anchor="end" font-size="10" fill="#6b7280">${fmt(v,lv.s)}</text>`});
    rv.t.forEach(v=>{g+=`<text x="${W-R+6}" y="${yr(v)+4}" font-size="10" fill="#6b7280">${fmt(v,rv.s)}</text>`});
    g+=`<line x1="${L}" x2="${W-R}" y1="${yr(0)}" y2="${yr(0)}" stroke="#9ca3af" stroke-width="1.5"/>`;
    [0,.25,.5,.75,1].forEach(f=>{const i=Math.round((n-1)*f);g+=`<text x="${x(i)}" y="${H-8}" text-anchor="${f==0?"start":f==1?"end":"middle"}" font-size="10" fill="#6b7280">${d(from+i).slice(2)}</text>`});
    g+=`<path d="${pl(mc,yl)}" fill="none" stroke="${C.mc}" stroke-width="2.4"/><path d="${pl(in2,yr)}" fill="none" stroke="${C.inn}" stroke-width="2"/><path d="${pl(fr2,yr)}" fill="none" stroke="${C.fr}" stroke-width="2"/>`;
    const lst=a=>Math.round(a[a.length-1]).toLocaleString();
    return `<div class="hd"><b>${d(from)} ~ ${d(N-1)}</b><span class="lg"><i style="background:${C.mc}"></i>시가총액(억, 좌)</span><span class="lg"><i style="background:${C.fr}"></i>외국인 누적 순매수(억, 우) ${lst(fr2)}</span><span class="lg"><i style="background:${C.inn}"></i>기관 누적 순매수(억, 우) ${lst(in2)}</span>
      <span style="margin-left:auto">${[3,6,12].map(m=>`<button data-m="${m}" style="font:11px Inter;padding:2px 8px;margin-left:4px;border:1px solid ${m==months?"#111827":"#d1d5db"};background:${m==months?"#111827":"#fff"};color:${m==months?"#fff":"#374151"};border-radius:3px;cursor:pointer">${m}개월</button>`).join("")}</span></div>
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="시총·외인·기관 누적 순매수">${g}</svg>`;
  }
  document.addEventListener("click",e=>{
    const b=e.target.closest(".chbox button");
    if(b){const box=b.closest(".chbox");box.innerHTML=draw(box.dataset.code,+b.dataset.m);return}
    const tr=e.target.closest("tr.clk");if(!tr)return;
    const nx=tr.nextElementSibling;
    if(nx&&nx.classList.contains("chart")){nx.remove();tr.querySelector(".car").textContent="▸";return}
    const code=tr.dataset.code;if(!SERIES[code])return;
    const row=document.createElement("tr");row.className="chart";
    row.innerHTML=`<td colspan="${tr.children.length}"><div class="chbox" data-code="${code}">${draw(code,12)}</div><p class="note">시총 = 종가 × <b>현재 상장주수</b>(증자·소각이 있었던 종목은 과거 시총이 다소 어긋남). 누적 순매수는 보는 구간 시작일을 0 으로 둔 합계 — 최근 30거래일은 한투 금액, 그 이전은 네이버 수량 × 종가 <b>근사</b>. x축은 거래일 등간격.</p></td>`;
    tr.after(row);tr.querySelector(".car").textContent="▾";
  });
})();
</script>"""


# 위클리 리포트용 차트(11/7 사용자 요청): 리포트 '조선 수급' 꼭지와 같은 2×2 모양 —
# 회사명(파랑) · 시가총액(십억원, 좌축 검정) · 기관/외인 1년 누적 순매수(억원, 우축 갈색/파랑) · 0 선(회색 굵게).
# 데이터는 종목 클릭 차트와 같은 SERIES(1년 일별)를 쓰고, 그림은 화면에서 SVG 로 그려 PNG 로 받는다
# (리포에 이미지 파일을 쌓지 않는다). 묶음을 늘리려면 이 표에 한 줄 더하면 된다.
WEEKLY_GROUPS = [
    ("조선 수급", ["009540", "010140", "329180", "042660"]),   # HD한국조선해양 · 삼성중공업 · HD현대중공업 · 한화오션
]
WEEKLY_W, WEEKLY_H, WEEKLY_SCALE = 600, 410, 2   # 한 장 viewBox · PNG 배율(1200×820)
# PNG 에 인쇄 해상도(pHYs)를 심는다 — 캔버스 PNG 는 해상도 정보가 없어 워드·한글이 1px=1pt 로 읽어
# 4개 한 장(2432px)이 가로 86cm 로 붙는다(11/7 실측). 384dpi 면 4개 한 장 ≈ 16.1cm, 낱장 ≈ 7.9cm.
WEEKLY_DPI = 384

WEEKLY_JS = r"""
<script>
(function(){
  const W=__W__,H=__H__,SC=__SC__,FONT='"Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",sans-serif';
  const C={mc:"#111111",inn:"#a0825f",fr:"#2f80d1",zero:"#c9c9c9",ax:"#555",title:"#2f6db5"};
  function nice(lo,hi,k){const sp=(hi-lo)||1,st=Math.pow(10,Math.floor(Math.log10(sp/k))),m=sp/k/st,s=(m<1.5?1:m<3?2:m<7?5:10)*st;
    const a=Math.floor(lo/s)*s,b=Math.ceil(hi/s)*s,t=[];for(let v=a;v<=b+s/2;v+=s)t.push(Math.round(v));return {t,a,b}}
  const n0=v=>Math.round(v).toLocaleString("en-US");
  function svg(code,name){
    const s=SERIES[code];if(!s)return "";
    const n=s.mc.length,mc=s.mc.map(v=>v/10),fr=s.fr.map(v=>v-s.fr[0]),inn=s["in"].map(v=>v-s["in"][0]);
    const L=58,R=58,T=54,B=30,pw=W-L-R,ph=H-T-B;
    const lv=nice(Math.min(...mc),Math.max(...mc),6),rv=nice(Math.min(0,...fr,...inn),Math.max(0,...fr,...inn),8);
    const x=i=>L+pw*i/Math.max(1,n-1),yl=v=>T+ph*(1-(v-lv.a)/(lv.b-lv.a)),yr=v=>T+ph*(1-(v-rv.a)/(rv.b-rv.a));
    const pl=(a,y)=>a.map((v,i)=>(i?"L":"M")+x(i).toFixed(1)+" "+y(v).toFixed(1)).join("");
    const tx=(X,Y,t,o)=>`<text x="${X}" y="${Y}" font-family='${FONT}' font-size="${o&&o.fs||11}" fill="${o&&o.c||C.ax}" text-anchor="${o&&o.a||"start"}"${o&&o.b?' font-weight="700"':''}>${t}</text>`;
    let g=`<rect width="${W}" height="${H}" fill="#fff"/>`;
    g+=tx(8,22,name,{fs:15,c:C.title,b:1})+tx(W-6,22,"(1년 누적 매수, 억원)",{a:"end",c:C.title,fs:11});
    const lg=[["시가총액(십억원)",C.mc,2.4],["기관매수(누적)",C.inn,2],["외인매수(누적)",C.fr,1.6]];
    lg.forEach((e,i)=>{const X=W/2-70,Y=14+i*13;g+=`<line x1="${X}" x2="${X+26}" y1="${Y}" y2="${Y}" stroke="${e[1]}" stroke-width="${e[2]}"/>`+tx(X+32,Y+4,e[0],{fs:10.5,c:"#222"})});
    g+=`<rect x="${L}" y="${T}" width="${pw}" height="${ph}" fill="none" stroke="#bbb"/>`;
    lv.t.forEach(v=>{g+=`<line x1="${L-4}" x2="${L}" y1="${yl(v)}" y2="${yl(v)}" stroke="#999"/>`+tx(L-6,yl(v)+4,n0(v),{a:"end"})});
    rv.t.forEach(v=>{g+=`<line x1="${W-R}" x2="${W-R+4}" y1="${yr(v)}" y2="${yr(v)}" stroke="#999"/>`+tx(W-R+6,yr(v)+4,n0(v))});
    g+=`<line x1="${L}" x2="${W-R}" y1="${yr(0)}" y2="${yr(0)}" stroke="${C.zero}" stroke-width="3"/>`;
    let pm="";for(let i=0;i<n;i++){const yy=s.d.slice(i*6,i*6+2),mm=+s.d.slice(i*6+2,i*6+4),k=yy+"."+mm;
      if(k!==pm&&(i===0?false:true)&&mm%2===0){g+=`<line x1="${x(i)}" x2="${x(i)}" y1="${T+ph}" y2="${T+ph+4}" stroke="#999"/>`+tx(x(i),H-10,k,{a:"middle"})}pm=k}
    g+=`<path d="${pl(fr,yr)}" fill="none" stroke="${C.fr}" stroke-width="1.6"/><path d="${pl(inn,yr)}" fill="none" stroke="${C.inn}" stroke-width="2"/><path d="${pl(mc,yl)}" fill="none" stroke="${C.mc}" stroke-width="2.4"/>`;
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${g}</svg>`;
  }
  const CRC=(()=>{const t=new Uint32Array(256);for(let n=0;n<256;n++){let c=n;for(let k=0;k<8;k++)c=c&1?0xEDB88320^(c>>>1):c>>>1;t[n]=c}
    return b=>{let c=0xFFFFFFFF;for(let i=0;i<b.length;i++)c=t[(c^b[i])&255]^(c>>>8);return (c^0xFFFFFFFF)>>>0}})();
  function withDpi(buf,dpi){   // IHDR 뒤에 pHYs(픽셀/미터) 청크를 끼워 넣는다
    const src=new Uint8Array(buf),ppm=Math.round(dpi/0.0254),ch=new Uint8Array(21),dv=new DataView(ch.buffer);
    dv.setUint32(0,9);ch.set([0x70,0x48,0x59,0x73],4);dv.setUint32(8,ppm);dv.setUint32(12,ppm);ch[16]=1;dv.setUint32(17,CRC(ch.subarray(4,17)));
    const at=8+8+13+4,out=new Uint8Array(src.length+21);out.set(src.subarray(0,at));out.set(ch,at);out.set(src.subarray(at),at+21);return out;
  }
  function toPng(svgText,w,h,file){
    const img=new Image(),url=URL.createObjectURL(new Blob([svgText],{type:"image/svg+xml;charset=utf-8"}));
    img.onload=()=>{const c=document.createElement("canvas");c.width=w*SC;c.height=h*SC;const x=c.getContext("2d");
      x.fillStyle="#fff";x.fillRect(0,0,c.width,c.height);x.drawImage(img,0,0,c.width,c.height);URL.revokeObjectURL(url);
      c.toBlob(b=>b.arrayBuffer().then(buf=>{const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([withDpi(buf,__DPI__)],{type:"image/png"}));
        a.download=file;document.body.appendChild(a);a.click();a.remove()}),"image/png")};
    img.src=url;
  }
  const stamp=()=>(document.querySelector("[data-wk-asof]")||{}).dataset?.wkAsof||"";
  // SERIES 는 페이지 끝의 종목 클릭 차트 스크립트가 정의한다 — 그 뒤에 그린다.
  window.addEventListener("DOMContentLoaded",()=>document.querySelectorAll(".wk-cell").forEach(cell=>{
    cell.querySelector(".wk-svg").innerHTML=svg(cell.dataset.code,cell.dataset.name)}));
  document.addEventListener("click",e=>{
    const one=e.target.closest(".wk-one");
    if(one){const cell=one.closest(".wk-cell");toPng(svg(cell.dataset.code,cell.dataset.name),W,H,`${cell.dataset.name}_수급_${stamp()}.png`);return}
    const all=e.target.closest(".wk-all");if(!all)return;
    const grid=document.getElementById(all.dataset.grid),cells=[...grid.querySelectorAll(".wk-cell")],G=16;
    const cols=2,rows=Math.ceil(cells.length/cols),TW=W*cols+G*(cols-1),TH=H*rows+G*(rows-1);
    let body=`<rect width="${TW}" height="${TH}" fill="#fff"/>`;
    cells.forEach((c,i)=>{body+=`<g transform="translate(${(i%cols)*(W+G)},${Math.floor(i/cols)*(H+G)})">${svg(c.dataset.code,c.dataset.name).replace(/^<svg[^>]*>|<\/svg>$/g,"")}</g>`});
    toPng(`<svg xmlns="http://www.w3.org/2000/svg" width="${TW}" height="${TH}" viewBox="0 0 ${TW} ${TH}">${body}</svg>`,TW,TH,`${all.dataset.title}_${stamp()}.png`);
  });
})();
</script>"""


def weekly_section(rows, series, asof_date=""):
    """위클리용 차트 섹션. 시계열이 있는 종목만 칸을 만들고, 한 칸도 없으면 섹션 자체를 안 만든다."""
    if not series:
        return ""
    names = {r["code"]: r["name"] for r in rows}
    blocks = []
    for gi, (title, codes) in enumerate(WEEKLY_GROUPS):
        cells = [c for c in codes if series.get(c)]
        if not cells:
            continue
        gid = f"wk-{gi}"
        cell_html = "".join(
            f"<div class='wk-cell' data-code='{c}' data-name='{esc(names.get(c, c))}'><div class='wk-svg'></div>"
            f"<button class='wk-one'>⬇ PNG</button></div>" for c in cells)
        blocks.append(f"<h3>{esc(title)} <button class='wk-all' data-grid='{gid}' data-title='{esc(title)}'>⬇ {len(cells)}개 한 장 PNG</button></h3>"
                      f"<div class='wk-grid' id='{gid}'>{cell_html}</div>")
    if not blocks:
        return ""
    js = (WEEKLY_JS.replace("__W__", str(WEEKLY_W)).replace("__H__", str(WEEKLY_H))
          .replace("__SC__", str(WEEKLY_SCALE)).replace("__DPI__", str(WEEKLY_DPI)))
    return (f"<details id='weekly' class='sec' open data-wk-asof='{esc(asof_date.replace('-', '')[2:])}'>"
            "<summary><h2>④ 위클리용 차트 <small style=\"font:400 12px Inter;color:#6b7280\">"
            "시가총액 · 기관/외인 1년 누적 순매수 — 리포트에 붙일 PNG</small></h2></summary>"
            + "".join(blocks) +
            f"<p class='note'>PNG 는 한 장 {WEEKLY_W * WEEKLY_SCALE}×{WEEKLY_H * WEEKLY_SCALE}px(가로:세로 ≈ {WEEKLY_W / WEEKLY_H:.2f}:1), "
            f"4개 한 장은 2×2 로 붙인 것. {WEEKLY_DPI}dpi 로 저장되어 워드에 붙이면 4개 한 장 가로 약 "
            f"{2 * WEEKLY_W * WEEKLY_SCALE * 2.54 / WEEKLY_DPI + 0.1:.0f}cm · 낱장 약 {WEEKLY_W * WEEKLY_SCALE * 2.54 / WEEKLY_DPI:.0f}cm 로 들어간다. 시가총액 = 종가 × 현재 상장주수(십억원), 누적 순매수는 1년 창 시작일을 0 으로 둔 합계"
            "(최근 30거래일 한투 금액, 그 이전 네이버 수량 × 종가 근사). 매 수집마다 다시 그려진다.</p>"
            "</details>" + js)


def chart_js(series):
    """종목 클릭 차트 스크립트. 시계열이 없으면 빈 문자열(클릭 가능한 행도 안 생긴다)."""
    if not series:
        return ""
    return CHART_JS.replace("__SERIES__", json.dumps(series, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))


def render(d, archive=False, dates=(), series=None):
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
.wk-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}@media(max-width:900px){{.wk-grid{{grid-template-columns:1fr}}}}.wk-cell{{border:1px solid var(--line);padding:6px;position:relative}}.wk-svg svg{{width:100%;height:auto;display:block}}.wk-one,.wk-all{{font:11px Inter;padding:2px 8px;border:1px solid #d1d5db;background:#fff;border-radius:3px;cursor:pointer;color:#374151}}.wk-one{{position:absolute;right:8px;bottom:8px}}.wk-all{{margin-left:8px;vertical-align:middle}}
tr.clk{{cursor:pointer}}tr.clk:hover td{{background:#f8fafc}}.car{{color:#9ca3af;font-size:11px}}
tr.chart td{{padding:10px 8px 16px;background:#fcfcfd}}.chbox{{max-width:760px}}.chbox .hd{{display:flex;gap:14px;flex-wrap:wrap;align-items:baseline;font-size:12px;margin-bottom:4px}}
.chbox .hd b{{font-size:13px}}.lg{{display:inline-flex;align-items:center;gap:5px;color:var(--muted)}}.lg i{{display:inline-block;width:14px;height:3px;border-radius:2px}}
.chbox svg{{display:block;width:100%;height:auto}}
#cap-1,#cap-2,#cap-3,#cap-1a,#cap-1b{{padding:6px 0 4px;background:#fff}}
.arch{{font-size:12px;color:#6b7280;margin:0 0 14px;padding:7px 10px;background:#f9fafb;border:1px solid var(--line);border-radius:4px}}.arch b{{color:#111827}}.arch a{{margin-left:8px;color:#1d4ed8}}.arch select{{margin:0 6px;font-size:12px;padding:2px 4px}}.arch small{{color:#9ca3af}}
</style></head><body>
{archive_nav(d, archive, dates)}
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
<div class="wrap">{returns_table(rows, series)}</div>
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
{weekly_section(rows, series, d.get('date', ''))}
<p class="note" style="margin-top:28px">출처: 한국투자증권 OpenAPI(일봉·투자자별·현재가·상장주수) · 네이버 증권(ETF 구성 비중) · 액티브ETF.매매동향(etf_holdings). 유니버스는 <code>coverage_flow/universe.csv</code>, 섹터 ETF 는 <code>etf_universe.csv</code>.</p>
{chart_js(series)}</body></html>"""


def write_archive(d):
    """16:00 슬롯 거래일 수집이면 그날 페이지를 보관하고, 보관 규칙 밖의 옛 페이지를 지운다.
    같은 날 16:00 슬롯을 다시 돌리면(수동 수집) 그 날 페이지를 덮어쓴다."""
    day = d.get("date", "")
    mday = d.get("market_day", "")
    if d.get("slot") != ARCHIVE_SLOT or not day or (mday and mday != day):
        return None
    os.makedirs(ARCH_DIR, exist_ok=True)
    path = os.path.join(ARCH_DIR, f"{day}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render(d, archive=True))
    have = archive_dates()
    keep = archive_keep(have, day)
    for x in have:
        if x not in keep:
            os.remove(os.path.join(ARCH_DIR, f"{x}.html"))
            print("archive pruned", x)
    return path


def main():
    with open(LATEST, encoding="utf-8") as f:
        d = json.load(f)
    series = None
    if os.path.exists(SERIES):
        with open(SERIES, encoding="utf-8") as f:
            series = json.load(f)
    path = write_archive(d)
    if path:
        print("archived", path)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(render(d, dates=archive_dates(), series=series))
    print("wrote", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()
