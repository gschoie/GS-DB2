# -*- coding: utf-8 -*-
"""changes.json + 스냅샷 히스토리 → etf_holdings_report.html (GS Research Desk 톤, 자기완결).
과거 일자 변화는 스냅샷 쌍으로 재계산해 ◀▶ 네비게이션으로 조회 (최근 MAX_DAYS일 임베드).
출력 경로: 환경변수 ETF_HOLDINGS_OUT (없으면 HERE/etf_holdings_report.html)."""
import os, sys, json, glob, html, datetime

import detect_changes as dc

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR = os.path.join(HERE, "snapshots")
OUT = os.environ.get("ETF_HOLDINGS_OUT", os.path.join(HERE, "etf_holdings_report.html"))
MAX_DAYS = 20  # 네비게이션으로 볼 수 있는 과거 일수(페이지 용량 상한)
WD = "월화수목금토일"


def esc(s):
    return html.escape(str(s))


def naver_link(name, code):
    name = esc(name)
    if not code:
        return name
    return (f'<a class="lnk" href="https://finance.naver.com/item/fchart.naver?code={esc(code)}"'
            f' target="_blank" rel="noopener">{name}</a>')


def move_row(m):
    """실매매(리밸런싱) 한 줄. 방향/강도 표시."""
    sp = m["active_share_pct"]
    wp = m["active_weight_pp"]
    up = sp >= 0
    arrow = "▲ 매수" if up else "▽ 매도"
    cls = "pos" if up else "neg"
    big = " head" if m["headline"] else ""
    wtxt = "—" if wp is None else f'{"+" if wp >= 0 else "−"}{abs(wp):.2f}%p'
    return (f'<div class="mv{big}"><span class="{cls} dir">{arrow}</span> '
            f'<b>{naver_link(m["name"], m["code"])}</b>'
            f'<span class="mvnum">계약수 <span class="{cls}">{"+" if up else "−"}{abs(sp):.0f}%</span>'
            f' · 액티브비중 <span class="{cls}">{wtxt}</span>'
            f' · 현비중 {m["weight_now"]:.2f}%</span></div>')


def etf_card(e):
    parts = [f'<div class="ec-head"><b>{esc(e["label"])}</b>'
             f'<small>{esc(e["group"])}</small></div>']
    if e["new"]:
        chips = " ".join(f'<span class="chip new">{naver_link(n["name"], n["code"])}'
                         f'{" · "+format(n["weight"],".1f")+"%" if n["weight"] else ""}</span>'
                         for n in e["new"])
        parts.append(f'<div class="row"><span class="tag tnew">Top10 진입</span>{chips}</div>')
    if e["gone"]:
        chips = " ".join(f'<span class="chip gone">{naver_link(g["name"], g["code"])}'
                         f'{" · "+format(g["weight_prev"],".1f")+"%" if g["weight_prev"] else ""}</span>'
                         for g in e["gone"])
        parts.append(f'<div class="row"><span class="tag tgone">Top10 이탈</span>{chips}</div>')
    if e["moves"]:
        parts.append('<div class="moves">' + "".join(move_row(m) for m in e["moves"]) + '</div>')
    if not e["has_weight"]:
        parts.append('<p class="fnote">해외종목 보유 ETF — 비중 미제공, 계약수 변화로 판단</p>')
    return f'<article class="ecard">{"".join(parts)}</article>'


def _bar_rows(holdings, mode):
    """엑셀 데이터막대 스타일. mode='weight'(비중%) 또는 'shares'(계약수)."""
    pairs = [(h, h["weight"] if mode == "weight" else h["shares"]) for h in holdings]
    mx = max((v for _, v in pairs), default=0) or 1
    out = []
    for h, v in pairs:
        w = max(2.0, v / mx * 100)                    # 최소 2% 폭으로 보이게
        label = f"{v:.2f}%" if mode == "weight" else f"{int(v):,}주"
        out.append(
            f'<div class="hbar"><span class="hn" title="{esc(h["name"])}">{esc(h["name"])}</span>'
            f'<span class="htrack"><span class="hfill" style="width:{w:.1f}%"></span></span>'
            f'<span class="hv">{label}</span></div>')
    return "".join(out)


def current_holdings_block(snap, day_label):
    """접이식: 유니버스 전체(21개) 해당일 Top10 보유를 비율 막대로."""
    blocks = []
    for code, e in snap["etfs"].items():
        hs = e.get("holdings", [])
        if not hs:
            continue
        has_w = any(h["weight"] > 0 for h in hs)
        mode = "weight" if has_w else "shares"
        if has_w:
            summ = f'Top10 합계 {sum(h["weight"] for h in hs):.1f}%'
        else:
            summ = '해외·비중 미제공 <span class="ov">(계약수 비율)</span>'
        blocks.append(
            f'<div class="hcard"><div class="hh"><b>{esc(e.get("label", e.get("name","")))}</b>'
            f'<small>{esc(e.get("group",""))} · {summ}</small></div>'
            f'<div class="hbars">{_bar_rows(hs, mode)}</div></div>')
    return (f'<details class="cur" open><summary>전체 유니버스 {esc(day_label)} 보유(Top10) · {len(blocks)}개 · 비율 막대</summary>'
            f'<div class="hgrid">{"".join(blocks)}</div></details>')


def day_html(ch, snap, is_latest):
    """하루치 본문(네비게이션으로 교체되는 부분)."""
    s = ch["summary"]
    base = esc(ch.get("base_date") or "—")
    prevbase = esc(ch.get("prev_base_date") or "—")
    if not ch["etfs"]:
        body = (f'<div class="none">이 날(<b>{prevbase} → {base}</b> 기준일 비교)은 '
                '유의미한 구성 변화가 없습니다. ✅</div>')
    else:
        body = '<div class="cards">' + "".join(etf_card(e) for e in ch["etfs"]) + '</div>'

    raw = ch.get("base_date") or ch.get("date") or ""
    h2d = f"{raw[2:4]}/{raw[5:7]}/{raw[8:10]}" if len(raw) == 10 else "—"
    banner = ""
    if is_latest and ch.get("same_base"):
        banner = ('<div class="banner">⚠ 직전 실행과 <b>구성 기준일이 동일</b>합니다 '
                  f'({base} · KRX 장마감). 아직 새 구성이 반영되지 않아 변화가 없을 수 있습니다.</div>')
    gen = esc(ch.get("generated_at") or "")
    gen_txt = f'생성 <b>{gen}</b> · ' if gen else ''
    title = "오늘" if is_latest else "당일"

    return f"""
<p class="sub">{gen_txt}실행일 {esc(ch["date"])}<br>
구성 기준일 <b>{base}</b> (KRX 장마감) · 비교 <b>{prevbase} → {base}</b><br>
매일 구성종목(Top10)을 스냅샷하고, <b>주가 효과와 CU 자금유출입을 제거</b>해 운용사가 실제로 사고판 것만 잡아냅니다.</p>
{banner}

<section class="stats">
  <article><small>유니버스</small><strong>{s["universe"]}</strong></article>
  <article><small>변화 ETF</small><strong class="g">{s["etfs_changed"]}</strong></article>
  <article><small>Top10 신규 진입</small><strong class="g">{s["new_total"]}</strong></article>
  <article><small>실매매(리밸런싱)</small><strong>{s["moves_total"]}</strong></article>
</section>

<h2>{title}({esc(h2d)})의 구성 변화</h2>
{body}

{current_holdings_block(snap, h2d)}
"""


def build():
    with open(os.path.join(HERE, "changes.json"), encoding="utf-8") as f:
        ch = json.load(f)
    snaps = sorted(glob.glob(os.path.join(SNAP_DIR, "*.json")))
    snap_list = [(os.path.splitext(os.path.basename(p))[0], p) for p in snaps]

    thr = ch.get("thresholds", {"weight_pp_min": 1.0, "weight_pp_big": 5.0, "share_pct_min": 30})

    if len(snap_list) < 2:
        # 첫 실행 — 비교할 과거가 없음: 단일 안내 페이지
        pages = {ch["date"]: ('<div class="none">첫 스냅샷을 저장했습니다. '
                              '<b>내일부터</b> 전일 대비 구성 변화를 감지합니다.</div>')}
        nav_dates = [ch["date"]]
    else:
        pair_dates = [d for d, _ in snap_list][1:]          # 비교 가능한 실행일들
        nav_dates = pair_dates[-MAX_DAYS:]
        pages = {}
        cache = {}

        def load(path):
            if path not in cache:
                with open(path, encoding="utf-8") as f:
                    cache[path] = json.load(f)
            return cache[path]

        for i, (d, path) in enumerate(snap_list):
            if d not in nav_dates:
                continue
            prev_date, prev_path = snap_list[i - 1]
            payload = dc.compare(load(prev_path), load(path), prev_date, d)
            if d == ch.get("date"):                          # 최신일은 실제 실행 기록 사용
                payload = ch
            pages[d] = day_html(payload, load(path), is_latest=(d == nav_dates[-1]))

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

    return TEMPLATE.format(
        nav_opts="".join(date_opts), pages_json=pages_json, dates_json=dates_json,
        ndays=len(nav_dates),
        wmin=thr["weight_pp_min"], wbig=thr["weight_pp_big"], spct=thr["share_pct_min"],
    )


TEMPLATE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>액티브 ETF 구성 변화 · GS Research Desk</title>
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
.stats .g{{color:#286342}}.stats .r{{color:#a43c31}}
h2{{font:600 18px Georgia,"Noto Serif KR",serif;margin:30px 0 12px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px}}
.ecard{{background:#fff;border:1px solid var(--line);border-left:4px solid var(--green);padding:15px 17px}}
.ec-head{{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin-bottom:9px}}
.ec-head b{{font-size:15px}}.ec-head small{{color:var(--muted);font-size:11px;white-space:nowrap}}
.row{{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:7px 0}}
.tag{{font-size:9px;font-weight:800;letter-spacing:.04em;padding:3px 7px;border-radius:5px;white-space:nowrap}}
.tnew{{background:#e3f3e7;color:#286342}}.tgone{{background:#f8e9e6;color:#a43c31}}
.chip{{font-size:12px;padding:3px 8px;border-radius:11px;background:#f2f5f0}}
.chip.new{{background:#eaf6ee}}.chip.gone{{background:#faeeeb}}
.moves{{margin-top:8px;display:flex;flex-direction:column;gap:6px}}
.mv{{font-size:12px;line-height:1.5;padding:6px 9px;background:#fafbf8;border:1px solid #eef1ec;border-radius:6px}}
.mv.head{{background:#fbfdf4;border-color:#e4ecc7}}
.mv .dir{{font-weight:800;font-size:11px;margin-right:5px}}
.mv b{{font-size:12px}}.mvnum{{display:block;color:var(--muted);font-size:11px;margin-top:2px}}
.fnote{{margin:8px 0 0;font-size:10px;color:#9aa19d}}
.lnk{{color:inherit;text-decoration:none;border-bottom:1px solid transparent}}
.lnk:hover{{color:#286342;border-bottom-color:#286342}}
.pos{{color:#286342}}.neg{{color:#a43c31}}
.none{{color:#445049;background:#fff;border:1px solid var(--line);padding:26px;text-align:center;font-size:14px}}
.banner{{margin:14px 0 0;background:#fff8e6;border:1px solid #e7d9a8;color:#7a5f1a;padding:11px 15px;font-size:12px;border-radius:6px}}
.legend{{margin:16px 0 0;color:var(--muted);font-size:11px;line-height:1.85;background:#fff;border:1px solid var(--line);padding:14px 16px}}
.legend b{{color:#445049}}
.cur{{margin-top:26px}}
.cur>summary{{cursor:pointer;padding:14px 16px;font-size:12px;font-weight:700;color:#445049;background:#fff;border:1px solid var(--line)}}
.hgrid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:12px;margin-top:12px}}
.hcard{{background:#fff;border:1px solid var(--line);padding:12px 14px}}
.hh{{display:flex;justify-content:space-between;align-items:baseline;gap:8px;margin-bottom:9px;flex-wrap:wrap}}
.hh b{{font-size:13px}}.hh small{{color:var(--muted);font-size:10px}}
.ov{{color:#9a7d2e}}
.hbars{{display:flex;flex-direction:column;gap:3px}}
.hbar{{display:grid;grid-template-columns:92px 1fr 54px;align-items:center;gap:8px;font-size:11px}}
.hn{{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#2c3a34}}
.htrack{{background:#eef1ec;border-radius:3px;height:13px;overflow:hidden}}
.hfill{{display:block;height:100%;background:linear-gradient(90deg,#286342,#4b8b62);border-radius:3px}}
.hv{{text-align:right;color:#61706a;font-family:Georgia;white-space:nowrap}}
.nav{{display:flex;align-items:center;gap:8px;margin:16px 0 0;position:sticky;top:0;
background:var(--bg);padding:8px 0;z-index:5}}
.nav button{{background:var(--card);color:var(--ink);border:1px solid var(--line);
padding:7px 15px;font-size:13px;cursor:pointer;line-height:1}}
.nav button:disabled{{opacity:.35;cursor:default}}
.nav button:not(:disabled):hover{{border-color:#758079}}
.nav select{{background:var(--card);color:var(--ink);border:1px solid var(--line);
padding:7px 9px;font-size:12px}}
.nav .hint{{margin-left:auto;font-size:10px;color:#9aa19d}}
@media(max-width:620px){{body{{padding:20px 12px 50px}}.stats{{grid-template-columns:1fr 1fr}}
.cards{{grid-template-columns:1fr}}}}
</style></head><body>
<p class="eyebrow">ACTIVE ETF · HOLDINGS</p>
<h1>액티브 ETF 구성 변화</h1>
<div class="nav">
<button id="btn-prev" title="이전 일자 (←)">◀</button>
<select id="sel-date">{nav_opts}</select>
<button id="btn-next" title="다음 일자 (→)">▶</button>
<span class="hint">← → 키로도 이동 · 과거 {ndays}일 조회</span>
</div>
<div id="day"></div>

<div class="legend">
<b>어떻게 읽나</b> · <b>계약수 ±%</b>는 CU 자금유출입(설정·환매)을 정규화해 뺀 <b>순수 매매</b> 강도 —
주가가 아무리 움직여도 운용사가 실제로 수량을 바꾸지 않으면 0에 가깝습니다.
<b>액티브 비중 ±%p</b>는 전일 보유를 오늘 단가로 평가한 '무매매 가정 비중'과 실제 비중의 차(주가 상쇄).
감지 기준: 액티브 비중변화 ≥ {wmin}%p(≥{wbig}%p 강조) 또는 계약수 변화 ≥ {spct}%, 그리고 Top10 진입·이탈.<br>
<b>한계</b> · 소스(네이버)는 상위 10종목만 제공 → 11위 이하 꼬리 종목 움직임과 '완전 신규 편입'은 잡히지 않을 수 있습니다(향후 운용사 전체 PDF로 확장 예정).
</div>

<p style="margin-top:30px;color:#9aa19d;font-size:11px">🎴 GS Research Desk · 액티브 ETF 포트폴리오 트래커</p>
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


if __name__ == "__main__":
    out = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"리포트 생성 → {OUT}")
