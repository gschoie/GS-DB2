# -*- coding: utf-8 -*-
"""signals.json → etf_signal_report.html (GS Research Desk 톤 매칭, 자기완결 HTML)."""
import os, json, html

HERE = os.path.dirname(os.path.abspath(__file__))

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

def flow_badge(flow):
    m = {"쌍끌이": ("쌍끌이 ↑", "b-buy"), "개인몰림": ("개인몰림 ⚠", "b-warn"),
         "중립": ("중립", "b-mut"), "수급없음": ("–", "b-mut")}
    label, cls = m.get(flow, (flow, "b-mut"))
    return f'<span class="badge {cls}">{esc(label)}</span>'

def trend_badge(s):
    if s["up_trend"]:
        return f'<span class="badge b-buy">▲ 상승추세</span>'
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

def build(payload):
    sig = payload["signals"]
    scanned = len(sig)
    alerts = [s for s in sig if s["alert"]]
    n_buy = sum(1 for s in sig if s["flow"] == "쌍끌이")
    n_warn = sum(1 for s in sig if s["flow"] == "개인몰림")
    asof = sig[0]["asof"] if sig else "—"

    # 알림 카드
    alert_cards = ""
    if alerts:
        for s in alerts:
            rs = " · ".join(reasons(s)) or "신호 발생"
            alert_cards += f'''
      <article class="alert-card">
        <div class="ac-head"><b>{name_link(s)}</b><small>{esc(s["group"])} · {s["close"]:,}원</small></div>
        <p>{esc(rs)}</p>
        <div class="ac-meta">ADX {s["adx"]} · %K {s["k"]}/{s["d"]} · {flow_badge(s["flow"])}</div>
      </article>'''
    else:
        alert_cards = '<p class="none">오늘 새로 뜬 신호가 없습니다. (조정·횡보 국면일 가능성)</p>'

    # 전체 표 — 알림 우선, 이후 스캔순
    rows_sorted = sorted(enumerate(sig), key=lambda x: (not x[1]["alert"], x[0]))
    trs = ""
    for _, s in rows_sorted:
        flag = '<span class="star">★ 알림</span>' if s["alert"] else ""
        if not s["liquid"]:
            flag += '<span class="lowliq">저유동성</span>'
        stoch_ev = ""
        if s["stoch_oversold"]: stoch_ev = '<span class="mini gold">과매도반등</span>'
        elif s["ev_stoch"]: stoch_ev = '<span class="mini gold">골든</span>'
        cls = "hl" if s["alert"] else ("dim" if not s["liquid"] else "")
        # 정렬용 원시값(표시값이 아닌 실제 숫자/랭크)
        tr_rank = 2 if s["up_trend"] else (0 if s["pdi"] < s["ndi"] else 1)
        fl_rank = {"쌍끌이": 3, "중립": 2, "수급없음": 1, "개인몰림": 0}.get(s["flow"], 2)
        fg_rank = (2 if s["alert"] else 0) + (0 if s["liquid"] else -1)
        trs += f'''
      <tr class="{cls}">
        <td class="etf" data-v="{esc(s["name"])}"><b>{name_link(s)}</b><small>{esc(s["group"])}</small></td>
        <td class="r" data-v="{s["close"]}">{s["close"]:,}</td>
        <td class="c" data-v="{s["adx"]}">{s["adx"]}<small class="di">{s["pdi"]}/{s["ndi"]}</small></td>
        <td class="c" data-v="{tr_rank}">{trend_badge(s)}</td>
        <td class="c" data-v="{s["k"]}">{s["k"]}/{s["d"]} {stoch_ev}</td>
        <td class="c" data-v="{fl_rank}">{flow_badge(s["flow"])}</td>
        <td class="r" data-v="{sv(s["for5"])}">{num(s["for5"])}</td>
        <td class="r" data-v="{sv(s["org5"])}">{num(s["org5"])}</td>
        <td class="r" data-v="{sv(s["ind5"])}">{num(s["ind5"])}</td>
        <td class="c flags" data-v="{fg_rank}">{flag}</td>
      </tr>'''

    return TEMPLATE.format(
        gen=esc(payload["generated_at"]), asof=esc(asof),
        scanned=scanned, n_alert=len(alerts), n_buy=n_buy, n_warn=n_warn,
        alert_cards=alert_cards, rows=trs,
    )

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
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:22px 0 8px}}
.stats article{{background:var(--card);border:1px solid var(--line);padding:18px 20px}}
.stats small{{color:var(--muted);font-size:11px;font-weight:700;letter-spacing:.04em}}
.stats strong{{font:500 32px Georgia;display:block;margin:8px 0 0}}
.stats .g{{color:#286342}}.stats .w{{color:#8a661c}}
h2{{font:600 18px Georgia,"Noto Serif KR",serif;margin:30px 0 12px}}
.alerts{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}}
.alert-card{{background:#fff;border:1px solid var(--line);border-left:4px solid var(--green);padding:15px 17px}}
.ac-head{{display:flex;justify-content:space-between;align-items:baseline;gap:10px}}
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
.etf b{{font-size:13px;display:block}}.etf small{{color:var(--muted);font-size:10px}}
.etf-link{{color:inherit;text-decoration:none;border-bottom:1px solid transparent}}
.etf-link:hover{{color:#286342;border-bottom-color:#286342}}
.di{{display:block;color:#9aa19d;font-size:10px;font-family:Georgia}}
.badge{{display:inline-block;border-radius:11px;padding:3px 9px;font-size:10px;font-weight:700;white-space:nowrap}}
.b-buy{{background:#e3f3e7;color:#286342}}.b-warn{{background:#fff1cf;color:#765c19}}
.b-down{{background:#f8e9e6;color:#a43c31}}.b-mut{{background:#edf1ed;color:#61706a}}
.mini{{display:inline-block;font-size:9px;font-weight:700;padding:2px 5px;border-radius:4px;margin-left:3px}}
.mini.gold{{background:#fff4d6;color:#8a661c}}
.pos{{color:#286342}}.neg{{color:#a43c31}}.mut{{color:#a9afab}}
.flags{{white-space:nowrap}}.star{{color:#5a7a1e;font-size:10px;font-weight:800}}
.lowliq{{display:inline-block;margin-left:5px;color:#9a8650;font-size:9px;border:1px solid #e0d8bf;border-radius:4px;padding:1px 4px}}
.legend{{margin-top:14px;color:var(--muted);font-size:11px;line-height:1.9}}
.legend b{{color:#445049}}
@media(max-width:620px){{body{{padding:20px 12px 50px}}.stats{{grid-template-columns:1fr 1fr}}
table{{min-width:760px}}}}
</style></head><body>
<p class="eyebrow">ETF · SECTOR SIGNAL</p>
<h1>ETF/섹터 신호 포착</h1>
<p class="sub">생성 <b>{gen}</b> · 신호 기준일(전일 확정) <b>{asof}</b><br>
ADX(추세) + Stochastic Slow(타이밍) + 수급(외인·기관·개인 5일 순매수, 억원). 신호는 장중 흔들림을 피해 <b>전일 확정 종가</b>로 계산.</p>

<section class="stats">
  <article><small>스캔 종목</small><strong>{scanned}</strong></article>
  <article><small>오늘 알림</small><strong class="g">{n_alert}</strong></article>
  <article><small>외인·기관 쌍끌이</small><strong class="g">{n_buy}</strong></article>
  <article><small>개인몰림 경계</small><strong class="w">{n_warn}</strong></article>
</section>

<h2>오늘의 알림 <small style="font:400 12px Inter;color:#8b918e">— 새로 뜬 골든크로스 · 개인몰림 제외 · 유동성 확보 종목</small></h2>
<div class="alerts">{alert_cards}</div>

<h2>전체 신호판 ({scanned})</h2>
<div class="tablewrap"><table>
<thead><tr>
<th data-type="text">ETF</th><th class="r" data-type="num">종가</th><th class="c" data-type="num">ADX<br>+DI/−DI</th><th class="c" data-type="num">추세</th>
<th class="c" data-type="num">%K/%D</th><th class="c" data-type="num">수급</th>
<th class="r" data-type="num">외인5D</th><th class="r" data-type="num">기관5D</th><th class="r" data-type="num">개인5D</th><th class="c" data-type="num">플래그</th>
</tr></thead>
<tbody>{rows}</tbody>
</table></div>

<p class="legend">
<b>추세</b> +DI&gt;−DI &amp; ADX&gt;20 = 상승추세 · <b>과매도반등</b> Stochastic %K가 %D를 20 이하에서 상향돌파 ·
<b>쌍끌이</b> 외인+기관 5일 동반 순매수 · <b>개인몰림</b> 개인만 순매수(외인·기관 이탈) = 경계 ·
<b>★알림</b> 오늘 새 골든크로스 + 개인몰림 아님 + 20일 거래대금 5억↑<br>
수급 단위: 억원 · 매매가 아닌 <b>참고용 신호</b>입니다.<br>
<b>정렬</b> 헤더를 클릭하면 해당 열 기준으로 정렬(다시 클릭 시 오름/내림 전환). 값 없음(–)은 항상 맨 아래.
</p>
<script>
(function(){{
  var table = document.querySelector('table');
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
}})();
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
