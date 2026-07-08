# -*- coding: utf-8 -*-
"""SQLite 스냅샷 → 자체 완결형 'consensus_revision.html' 생성.

기존 GS Research Desk 대시보드의 etf_signal_report.html 패턴을 따른다.
출력: telegram_research_dashboard/static/consensus_revision.html
      (메인 build_static.py가 Pages 루트로 복사)
"""
import json
import os
import sys
from collections import Counter

import db

sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.normpath(os.path.join(
    BASE, "..", "telegram_research_dashboard", "static", "consensus_revision.html"))

# 표시 대상 호라이즌 (라벨, kind, period 결정 방식)
HORIZONS = [
    ("이번분기", "quarter", None),   # period = 최신 스냅샷 최빈 분기
    ("2026E", "annual", "2026.12"),
    ("2027E", "annual", "2027.12"),
]


def dominant_quarter(con, snap):
    rows = con.execute(
        "SELECT period FROM consensus_snapshots WHERE snapshot_date=? AND kind='quarter'",
        (snap,)).fetchall()
    if not rows:
        return None
    return Counter(r[0] for r in rows).most_common(1)[0][0]


def series(con, snap, base, kind, period):
    """해당 호라이즌의 종목별 현재/전주 영업이익 + 변동률."""
    cur = {r["code"]: (r["name"], r["op_profit"]) for r in con.execute(
        "SELECT code,name,op_profit FROM consensus_snapshots "
        "WHERE snapshot_date=? AND kind=? AND period=? AND op_profit IS NOT NULL",
        (snap, kind, period))}
    prev = {}
    if base:
        prev = {r["code"]: r["op_profit"] for r in con.execute(
            "SELECT code,op_profit FROM consensus_snapshots "
            "WHERE snapshot_date=? AND kind=? AND period=? AND op_profit IS NOT NULL",
            (base, kind, period))}
    out = []
    for code, (name, curr) in cur.items():
        b = prev.get(code)
        wow = ((curr - b) / abs(b) * 100.0) if (b not in (None, 0)) else None
        out.append({"code": code, "name": name, "curr": curr, "base": b, "wow": wow})
    return out


def build():
    con = db.connect()
    dates = db.snapshot_dates(con)
    if not dates:
        print("스냅샷이 없습니다. 먼저 run_snapshot.py를 실행하세요.")
        return
    snap = dates[-1]
    base = dates[-2] if len(dates) >= 2 else None

    uni = con.execute("SELECT COUNT(*) FROM universe WHERE snapshot_date=?", (snap,)).fetchone()[0]
    covered = con.execute(
        "SELECT COUNT(DISTINCT code) FROM consensus_snapshots "
        "WHERE snapshot_date=? AND op_profit IS NOT NULL", (snap,)).fetchone()[0]

    horizons = []
    for label, kind, period in HORIZONS:
        p = period or dominant_quarter(con, snap)
        data = series(con, snap, base, kind, p)
        rated = [d for d in data if d["wow"] is not None]
        up = sum(1 for d in rated if d["wow"] > 0.05)
        down = sum(1 for d in rated if d["wow"] < -0.05)
        flat = len(rated) - up - down
        rated.sort(key=lambda d: d["wow"], reverse=True)
        # 리비전이 없으면(첫 주) 현재 레벨 상위로 대체 표시
        level_top = sorted(data, key=lambda d: d["curr"], reverse=True)[:10]
        horizons.append({
            "label": label, "period": p, "count": len(data),
            "up": up, "down": down, "flat": flat,
            "top_up": rated[:8], "top_down": rated[-8:][::-1] if rated else [],
            "level_top": level_top,
        })

    payload = {
        "snapshot_date": snap, "base_date": base,
        "universe": uni, "covered": covered, "missing": uni - covered,
        "has_revision": base is not None,
        "horizons": horizons,
    }
    html = render(payload)
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)
    con.close()
    mode = "리비전" if base else "베이스라인(첫 주)"
    print(f"생성 완료 [{mode}]: {OUTPUT}")


def render(p):
    data_json = json.dumps(p, ensure_ascii=False).replace("</", "<\\/")
    return _TEMPLATE.replace("__DATA__", data_json)


_TEMPLATE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KOSPI200 컨센 리비전</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1a1d21;--muted:#6b7280;--line:#e5e7eb;
--up:#0ca30c;--down:#d03b3b;--accent:#185fa5}
@media(prefers-color-scheme:dark){:root{--bg:#141516;--card:#1d1e1f;--ink:#f2f2f0;
--muted:#9a9a92;--line:#2f3032}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font-family:-apple-system,"Segoe UI","Malgun Gothic",sans-serif;line-height:1.5;
-webkit-font-smoothing:antialiased}
.wrap{max-width:960px;margin:0 auto;padding:24px 18px 60px}
h1{font-size:20px;font-weight:600;margin:0 0 2px}
.sub{color:var(--muted);font-size:13px}
.status{display:flex;flex-wrap:wrap;gap:8px 18px;align-items:center;
background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:12px 16px;margin:14px 0 22px;font-size:13px}
.status b{font-weight:600}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin-bottom:26px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.card .lab{font-size:12px;color:var(--muted);margin-bottom:8px}
.card .nums{display:flex;gap:14px;align-items:baseline;font-size:22px;font-weight:600}
.up{color:var(--up)}.down{color:var(--down)}
.bar{display:flex;height:5px;border-radius:3px;overflow:hidden;margin:10px 0 5px;background:var(--line)}
.bar i{display:block}.bar .iu{background:var(--up)}.bar .id{background:var(--down)}
.tiny{font-size:11px;color:var(--muted)}
h2{font-size:15px;font-weight:600;margin:26px 0 10px}
table{width:100%;border-collapse:collapse;font-size:13px;background:var(--card);
border:1px solid var(--line);border-radius:12px;overflow:hidden}
th,td{padding:7px 12px;text-align:right;border-bottom:1px solid var(--line)}
th:first-child,td:first-child{text-align:left}
th{color:var(--muted);font-weight:500;font-size:12px;background:transparent}
tr:last-child td{border-bottom:0}
.pos{color:var(--up);font-weight:600}.neg{color:var(--down);font-weight:600}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:640px){.grid2{grid-template-columns:1fr}}
.note{background:var(--card);border:1px dashed var(--line);border-radius:12px;
padding:14px 16px;color:var(--muted);font-size:13px;margin:8px 0 24px}
.mvrow{display:grid;grid-template-columns:130px 1fr 62px;align-items:center;gap:8px;
font-size:12.5px;margin:3px 0}
.mvbar{height:16px;border-radius:3px}
</style></head><body><div class="wrap">
<h1>KOSPI200 영업이익 컨센 리비전</h1>
<div class="sub" id="sub"></div>
<div class="status" id="status"></div>
<div id="body"></div>
<div class="tiny" style="margin-top:30px">단위: 억원 · 출처: 네이버 금융 컨센서스 · 매주 금요일 갱신</div>
</div>
<script>
var D=__DATA__;
function fmt(n){return n==null?'-':Math.round(n).toLocaleString('ko-KR')}
function pct(w){if(w==null)return'<span class="tiny">신규</span>';
 var c=w>0?'pos':(w<0?'neg':'');var s=(w>0?'+':'')+w.toFixed(1)+'%';return'<span class="'+c+'">'+s+'</span>'}
document.getElementById('sub').textContent =
 D.has_revision ? (D.base_date+' → '+D.snapshot_date+' 전주 대비') : (D.snapshot_date+' 기준 · 첫 스냅샷');
document.getElementById('status').innerHTML =
 '<span>📅 기준일 <b>'+D.snapshot_date+'</b></span>'+
 '<span>🎯 유니버스 <b>'+D.universe+'</b>종목</span>'+
 '<span>✅ 컨센 확보 <b>'+D.covered+'</b> · 없음 '+D.missing+'</span>'+
 (D.has_revision?'':'<span>🔹 리비전은 다음 주부터</span>');

var out='';
if(!D.has_revision){
 out+='<div class="note">첫 스냅샷이라 전주 대비 변동(▲▼)은 아직 없습니다. '+
      '다음 주 금요일 두 번째 스냅샷부터 리비전이 표시됩니다. 아래는 현재 컨센 레벨(영업이익 상위)입니다.</div>';
 D.horizons.forEach(function(h){
   out+='<h2>'+h.label+' ('+h.period+') · 영업이익 컨센 상위</h2><table>'+
        '<tr><th>종목</th><th>영업이익</th></tr>';
   h.level_top.forEach(function(d){out+='<tr><td>'+d.name+'</td><td>'+fmt(d.curr)+'</td></tr>'});
   out+='</table>';
 });
}else{
 out+='<div class="cards">';
 D.horizons.forEach(function(h){
   var tot=h.up+h.down+h.flat||1;
   out+='<div class="card"><div class="lab">'+h.label+' ('+h.period+')</div>'+
     '<div class="nums"><span class="up">'+h.up+' ▲</span><span class="down">'+h.down+' ▼</span></div>'+
     '<div class="bar"><i class="iu" style="width:'+(h.up/tot*100)+'%"></i>'+
     '<i class="id" style="width:'+(h.down/tot*100)+'%"></i></div>'+
     '<div class="tiny">보합 '+h.flat+' · 평가 '+(h.up+h.down+h.flat)+'종목</div></div>';
 });
 out+='</div>';
 D.horizons.forEach(function(h){
   out+='<h2>'+h.label+' ('+h.period+') · 전주 대비 영업이익 컨센 변동</h2><div class="grid2">';
   [['▲ 상향 Top',h.top_up],['▼ 하향 Top',h.top_down]].forEach(function(g){
     out+='<table><tr><th>'+g[0]+'</th><th>전주</th><th>현재</th><th>변동</th></tr>';
     g[1].forEach(function(d){out+='<tr><td>'+d.name+'</td><td>'+fmt(d.base)+
       '</td><td>'+fmt(d.curr)+'</td><td>'+pct(d.wow)+'</td></tr>'});
     out+='</table>';
   });
   out+='</div>';
 });
}
document.getElementById('body').innerHTML=out;
</script></body></html>"""


if __name__ == "__main__":
    build()
