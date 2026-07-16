# -*- coding: utf-8 -*-
"""SQLite 스냅샷 → 'consensus_revision.html' + 'consensus_full.xlsx' 생성.

- 화면: (리비전 주) 어닝 변화 큰 순 상위 20 — 컨센 변동 + 주가 변동 함께 · (첫 주) 컨센 레벨 상위 20
- 전체 종목 데이터는 엑셀 다운로드 버튼으로 제공
출력: telegram_research_dashboard/static/{consensus_revision.html, consensus_full.xlsx}
"""
import datetime as dt
import json
import os
import sys
from collections import Counter

import openpyxl
from openpyxl.styles import Font, PatternFill

import db

sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.normpath(os.path.join(BASE, "..", "telegram_research_dashboard", "static"))
OUT_HTML = os.path.join(STATIC, "consensus_revision.html")
OUT_XLSX = os.path.join(STATIC, "consensus_full.xlsx")

HORIZONS = [
    ("이번분기", "quarter", None, "q"),
    ("2026E", "annual", "2026.12", "a26"),
    ("2027E", "annual", "2027.12", "a27"),
    ("2028E", "annual", "2028.12", "a28"),
]
PAGE_KEYS = ["q", "a26", "a27"]


def dominant_quarter(con, snap):
    rows = con.execute(
        "SELECT period FROM consensus_snapshots WHERE snapshot_date=? AND kind='quarter'",
        (snap,)).fetchall()
    return Counter(r[0] for r in rows).most_common(1)[0][0] if rows else None


def series(con, snap, base, kind, period):
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
    out = {}
    for code, (name, curr) in cur.items():
        b = prev.get(code)
        wow = ((curr - b) / abs(b) * 100.0) if (b not in (None, 0)) else None
        out[code] = {"code": code, "name": name, "curr": curr, "base": b, "wow": wow}
    return out


def price_date_of(con, date):
    r = con.execute(
        "SELECT price_date, COUNT(*) c FROM stock_prices WHERE snapshot_date=? "
        "GROUP BY price_date ORDER BY c DESC LIMIT 1", (date,)).fetchone()
    return r["price_date"] if r else None


def iso_week(date_str):
    y, m, d = map(int, date_str.split("-"))
    iy, iw, _ = dt.date(y, m, d).isocalendar()
    return iy, iw


def weekly_endpoints(dates):
    """오름차순 스냅샷 날짜 → (이번주 최신, 전주 최신).

    각 ISO 주(월~일)에서 가장 늦게 찍힌 날짜를 그 주 대표로 보고,
    데이터가 있는 최근 두 주를 비교 대상으로 돌려준다. 같은 주에 여러 번
    돌려도 마지막(가장 늦은) 실행분만 그 주 값으로 쓰인다.
    """
    latest_of_week = {}
    for d in dates:                 # dates 오름차순 → 같은 주는 뒤 날짜가 덮어써 대표가 됨
        latest_of_week[iso_week(d)] = d
    weeks = sorted(latest_of_week)
    snap = latest_of_week[weeks[-1]]
    base = latest_of_week[weeks[-2]] if len(weeks) >= 2 else None
    return snap, base


def build():
    con = db.connect()
    dates = db.snapshot_dates(con)
    if not dates:
        print("스냅샷이 없습니다. run_snapshot.py 먼저 실행.")
        return
    snap, base = weekly_endpoints(dates)   # 주(월~일)별 최신 스냅샷 → 최근 두 주 비교
    qp = dominant_quarter(con, snap)

    psnap = db.price_map(con, snap)
    pbase = db.price_map(con, base) if base else {}

    def pwow(code):
        a, b = psnap.get(code), pbase.get(code)
        return ((a - b) / b * 100.0) if (a and b) else None

    maps, periods = {}, {}
    for label, kind, period, key in HORIZONS:
        p = period or qp
        periods[key] = p
        maps[key] = series(con, snap, base, kind, p)

    names = {}
    for key in maps:
        for code, d in maps[key].items():
            names[code] = d["name"]

    uni = con.execute("SELECT COUNT(*) FROM universe WHERE snapshot_date=?", (snap,)).fetchone()[0]
    covered = len(names)

    # 전체 종목 (엑셀)
    stocks = []
    for code in sorted(names):
        row = {"code": code, "name": names[code],
               "pcur": psnap.get(code), "pbase": pbase.get(code), "pw": pwow(code)}
        for key in ("q", "a26", "a27", "a28"):
            d = maps[key].get(code)
            row[key] = d["curr"] if d else None
            row[key + "_b"] = d["base"] if d else None
            row[key + "_w"] = d["wow"] if d else None
        stocks.append(row)
    write_excel(stocks, snap, base, periods)

    def compact(d):
        return {"code": d["code"], "name": d["name"], "curr": d["curr"],
                "base": d["base"], "wow": d["wow"], "pwow": pwow(d["code"])}

    page_hz = []
    labels = {k: l for l, _, _, k in HORIZONS}
    for key in PAGE_KEYS:
        data = list(maps[key].values())
        rated = [d for d in data if d["wow"] is not None]
        up = sum(1 for d in rated if d["wow"] > 0.05)
        down = sum(1 for d in rated if d["wow"] < -0.05)
        flat = len(rated) - up - down
        movers = sorted(rated, key=lambda d: abs(d["wow"]), reverse=True)[:30]
        levels = sorted(data, key=lambda d: d["curr"], reverse=True)[:30]
        page_hz.append({
            "label": labels[key], "period": periods[key], "key": key,
            "up": up, "down": down, "flat": flat,
            "movers": [compact(d) for d in movers],
            "levels": [compact(d) for d in levels],
        })

    payload = {
        "snapshot_date": snap, "base_date": base,
        "price_date_snap": price_date_of(con, snap),
        "price_date_base": price_date_of(con, base) if base else None,
        "universe": uni, "covered": covered, "missing": uni - covered,
        "has_revision": base is not None, "horizons": page_hz,
    }
    os.makedirs(STATIC, exist_ok=True)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(_TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")))
    con.close()
    print(f"생성 완료 [{'리비전' if base else '베이스라인'}]: {OUT_HTML}\n            엑셀: {OUT_XLSX}")


def write_excel(stocks, snap, base, periods):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "컨센"
    labels = [("q", "이번분기"), ("a26", "2026E"), ("a27", "2027E"), ("a28", "2028E")]
    header = ["종목코드", "종목명"]
    cols = []
    for key, lab in labels:
        per = periods.get(key, "")
        header.append(f"{lab}({per}) 영업이익")
        cols.append(("v", key))
        if base:
            header += [f"{lab} 전주", f"{lab} 컨센변동%"]
            cols += [("b", key), ("w", key)]
    header.append("현재 종가")
    cols.append(("pc", None))
    if base:
        header += ["전주 종가", "주가변동%"]
        cols += [("pb", None), ("pw", None)]

    title = f"KOSPI200 영업이익 컨센 · 기준일 {snap}" + (f" · 전주 {base}" if base else " · 첫 스냅샷")
    ws.append([title])
    ws.append(header)
    for st in stocks:
        r = [st["code"], st["name"]]
        for typ, key in cols:
            if typ == "v":
                r.append(st[key])
            elif typ == "b":
                r.append(st[key + "_b"])
            elif typ == "w":
                w = st[key + "_w"]
                r.append(round(w, 1) if w is not None else None)
            elif typ == "pc":
                r.append(st["pcur"])
            elif typ == "pb":
                r.append(st["pbase"])
            else:
                r.append(round(st["pw"], 1) if st["pw"] is not None else None)
        ws.append(r)
    ws["A1"].font = Font(bold=True, size=12)
    for c in ws[2]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="E8EEF5")
    ws.freeze_panes = "A3"
    widths = [10, 16] + [15] * (len(header) - 2)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    wb.save(OUT_XLSX)


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
font-family:-apple-system,"Segoe UI","Malgun Gothic",sans-serif;line-height:1.5}
.wrap{max-width:860px;margin:0 auto;padding:24px 18px 60px}
h1{font-size:20px;font-weight:600;margin:0 0 2px}.sub{color:var(--muted);font-size:13px}
.status{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;background:var(--card);
border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:14px 0 16px;font-size:13px}
.status b{font-weight:600}
.dl{display:inline-flex;align-items:center;gap:6px;background:var(--accent);color:#fff;
text-decoration:none;font-size:13px;font-weight:600;padding:9px 15px;border-radius:9px;margin-bottom:22px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:22px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:13px 15px}
.card .lab{font-size:12px;color:var(--muted);margin-bottom:7px}
.card .nums{display:flex;gap:14px;align-items:baseline;font-size:21px;font-weight:600}
.up{color:var(--up)}.down{color:var(--down)}
.bar{display:flex;height:5px;border-radius:3px;overflow:hidden;margin:9px 0 4px;background:var(--line)}
.bar i{display:block}.bar .iu{background:var(--up)}.bar .id{background:var(--down)}
.tiny{font-size:11px;color:var(--muted);font-weight:400}
.tabs{display:flex;gap:6px;margin:6px 0 12px}
.tab{border:1px solid var(--line);background:var(--card);color:var(--ink);font-size:13px;
padding:7px 14px;border-radius:8px;cursor:pointer}
.tab.on{background:var(--accent);color:#fff;border-color:var(--accent);font-weight:600}
.tblwrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px;background:var(--card);
border:1px solid var(--line);border-radius:12px;overflow:hidden;min-width:560px}
th,td{padding:7px 11px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
th:nth-child(2),td:nth-child(2){text-align:left}
th:first-child,td:first-child{text-align:center;color:var(--muted);width:30px}
th{color:var(--muted);font-weight:500;font-size:12px}tr:last-child td{border-bottom:0}
th.sortable{cursor:pointer;user-select:none}th.sortable:hover{color:var(--ink)}
.pos{color:var(--up);font-weight:600}.neg{color:var(--down);font-weight:600}
.note{background:var(--card);border:1px dashed var(--line);border-radius:12px;
padding:14px 16px;color:var(--muted);font-size:13px;margin-bottom:18px}
</style></head><body><div class="wrap">
<h1>KOSPI200 영업이익 컨센 리비전</h1>
<div class="sub" id="sub"></div>
<div class="status" id="status"></div>
<a class="dl" href="consensus_full.xlsx" download>📥 전체 종목 엑셀 다운로드</a>
<div id="cards"></div>
<div class="tabs" id="tabs"></div>
<div class="tblwrap"><div id="tbl"></div></div>
<div class="tiny" id="foot" style="margin-top:14px"></div>
</div>
<script>
var D=__DATA__, sel=0;
function fmt(n){return n==null?'-':Math.round(n).toLocaleString('ko-KR')}
function pct(w){if(w==null)return'<span class="tiny">-</span>';
 var c=w>0?'pos':(w<0?'neg':'');return'<span class="'+c+'">'+(w>0?'+':'')+w.toFixed(1)+'%</span>'}
function md(s){return s?s.slice(5):''}
document.getElementById('sub').textContent =
 D.has_revision?('전주 '+D.base_date+' → 현재 '+D.snapshot_date):(D.snapshot_date+' 기준 · 첫 스냅샷');
document.getElementById('status').innerHTML =
 '<span>📅 기준일 <b>'+D.snapshot_date+'</b></span>'+
 '<span>🎯 유니버스 <b>'+D.universe+'</b></span>'+
 '<span>✅ 컨센 확보 <b>'+D.covered+'</b> · 없음 '+D.missing+'</span>';

if(D.has_revision){
 var ch='<div class="cards">';
 D.horizons.forEach(function(h){var t=h.up+h.down+h.flat||1;
  ch+='<div class="card"><div class="lab">'+h.label+' ('+h.period+')</div>'+
   '<div class="nums"><span class="up">'+h.up+' ▲</span><span class="down">'+h.down+' ▼</span></div>'+
   '<div class="bar"><i class="iu" style="width:'+(h.up/t*100)+'%"></i>'+
   '<i class="id" style="width:'+(h.down/t*100)+'%"></i></div>'+
   '<div class="tiny">보합 '+h.flat+' · 평가 '+(h.up+h.down+h.flat)+'</div></div>';});
 document.getElementById('cards').innerHTML=ch+'</div>';
 document.getElementById('foot').innerHTML='컨센 변동 = 전주 대비 영업이익 컨센 변화율 · '+
  '주가 변동 = 종가 '+(D.price_date_base||'')+' → '+(D.price_date_snap||'')+' · 변화 큰 순 상위 30 · 열 제목 클릭 정렬 · 전체는 엑셀';
}else{
 document.getElementById('cards').innerHTML='<div class="note">첫 스냅샷이라 전주 대비 변동은 '+
  '다음 스냅샷부터 표시됩니다. 아래는 현재 컨센 레벨 상위 30이며, 전체 종목은 엑셀에서 확인하세요.</div>';
}
var tabs='';D.horizons.forEach(function(h,i){tabs+='<button class="tab'+(i===0?' on':'')+'" data-i="'+i+'">'+h.label+'</button>'});
document.getElementById('tabs').innerHTML=tabs;
document.querySelectorAll('.tab').forEach(function(b){b.onclick=function(){
 sel=+b.dataset.i;document.querySelectorAll('.tab').forEach(function(x){x.classList.remove('on')});
 b.classList.add('on');draw()}});
var sortKey=null, sortDir=-1;   // sortKey=null → 서버 순서(변화 큰 순)
function sortRows(rows){
 if(sortKey==null)return rows;
 return rows.slice().sort(function(a,b){var x=a[sortKey],y=b[sortKey];
  if(x==null&&y==null)return 0;if(x==null)return 1;if(y==null)return -1;   // 값 없는 종목은 뒤로
  return typeof x==='string'?sortDir*x.localeCompare(y,'ko'):sortDir*(x-y)});
}
function arrow(k){return sortKey===k?(sortDir<0?' ▼':' ▲'):''}
function draw(){var h=D.horizons[sel],tbl=document.getElementById('tbl'),out;
 if(D.has_revision){
  var cols=[['name','종목',''],['base','컨센 전주',md(D.base_date)],
   ['curr','컨센 현재',md(D.snapshot_date)],['wow','컨센 변동',''],['pwow','주가 변동','']];
  out='<table><tr><th>#</th>';
  cols.forEach(function(c){out+='<th class="sortable" data-k="'+c[0]+'">'+c[1]+
   (c[2]?'<br><span class="tiny">'+c[2]+'</span>':'')+arrow(c[0])+'</th>'});
  out+='</tr>';
  sortRows(h.movers).forEach(function(d,i){out+='<tr><td>'+(i+1)+'</td><td>'+d.name+'</td><td>'+
   fmt(d.base)+'</td><td>'+fmt(d.curr)+'</td><td>'+pct(d.wow)+'</td><td>'+pct(d.pwow)+'</td></tr>'});
  tbl.innerHTML=out+'</table>';
  tbl.querySelectorAll('th.sortable').forEach(function(th){th.onclick=function(){
   var k=th.dataset.k;if(sortKey===k){sortDir=-sortDir}else{sortKey=k;sortDir=k==='name'?1:-1}draw()}});
 }else{
  out='<table><tr><th>#</th><th>종목 · '+h.label+' 컨센 상위</th><th>영업이익</th></tr>';
  h.levels.forEach(function(d,i){out+='<tr><td>'+(i+1)+'</td><td>'+d.name+'</td><td>'+fmt(d.curr)+'</td></tr>'});
  tbl.innerHTML=out+'</table>';
 }
}
draw();
</script></body></html>"""


if __name__ == "__main__":
    build()
