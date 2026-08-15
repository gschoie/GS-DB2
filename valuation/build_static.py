# -*- coding: utf-8 -*-
"""valuation.json → 'valuation_report.html' + 'valuation_full.xlsx'.

- 화면: 지표(PER·PBR·ROE·PSR) 탭 + 산업 필터 + 검색, 행=기업 / 열=회계연도
- 엑셀: 지표별 시트 4개 + 원자료 시트 1개 (버튼 한 번에 내려받기)
출력: telegram_research_dashboard/static/{valuation_report.html, valuation_full.xlsx}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
STATIC = (ROOT.parent / "telegram_research_dashboard" / "static").resolve()
IN_JSON = ROOT / "data" / "valuation.json"
OUT_HTML = STATIC / "valuation_report.html"
OUT_XLSX = STATIC / "valuation_full.xlsx"

METRICS = [
    ("per", "PER", "배"),
    ("pbr", "PBR", "배"),
    ("roe", "ROE", "%"),
    ("psr", "PSR", "배"),
]

NAVY = "1F4E79"
GRAY = "F2F2F2"
EST_FILL = "FFF6E5"   # 컨센(E) 열 배경


def year_axis(companies):
    """종목별 회계연도가 조금씩 달라도 한 축에 세우도록 연도 합집합을 만든다."""
    seen = {}
    for company in companies:
        for year in company.get("years", []):
            # 같은 연도가 A와 E로 겹치면 확정(A)을 우선한다.
            if year["year"] not in seen or year["kind"] == "A":
                seen[year["year"]] = year["kind"]
    return [{"year": y, "kind": seen[y], "label": f"{y}{seen[y]}"} for y in sorted(seen)]


def value_of(company, year, metric):
    for entry in company.get("years", []):
        if entry["year"] == year:
            return entry.get(metric)
    return None


def build_xlsx(payload):
    companies = payload["companies"]
    axis = year_axis(companies)

    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)

    header_font = Font(name="Malgun Gothic", size=10, bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor=NAVY)
    body_font = Font(name="Malgun Gothic", size=10)
    est_fill = PatternFill("solid", fgColor=EST_FILL)
    center = Alignment(horizontal="center", vertical="center")

    def write_sheet(title, columns, rows, number_format, est_from=None):
        sheet = workbook.create_sheet(title)
        for index, name in enumerate(columns, 1):
            cell = sheet.cell(row=1, column=index, value=name)
            cell.font, cell.fill, cell.alignment = header_font, header_fill, center
        for r, row in enumerate(rows, 2):
            for c, value in enumerate(row, 1):
                cell = sheet.cell(row=r, column=c, value=value)
                cell.font = body_font
                if c > 4 and isinstance(value, (int, float)):
                    cell.number_format = number_format
                if est_from is not None and c >= est_from:
                    cell.fill = est_fill
        sheet.freeze_panes = "E2"
        widths = [16, 11, 10, 13] + [11] * (len(columns) - 4)
        for index, width in enumerate(widths[:len(columns)], 1):
            sheet.column_dimensions[get_column_letter(index)].width = width
        return sheet

    # 컨센(E) 열이 시작되는 위치 — 엑셀에서도 배경색으로 확정/추정을 구분한다.
    est_from = None
    for index, column in enumerate(axis):
        if column["kind"] == "E":
            est_from = 5 + index
            break

    base_columns = ["기업명", "티커", "산업", "지역"]
    for key, label, unit in METRICS:
        columns = base_columns + [f"{c['label']}" for c in axis]
        rows = []
        for company in companies:
            rows.append(
                [company["name"], company["ticker"], company["industry"], company["region"]]
                + [value_of(company, c["year"], key) for c in axis]
            )
        fmt = "0.0" if key == "roe" else "0.00"
        write_sheet(f"{label}({unit})", columns, rows, fmt, est_from)

    # 원자료: 배수의 분자·분모를 그대로 실어 검산이 가능하게 한다.
    raw_sheet = workbook.create_sheet("원자료")
    raw_columns = ["기업명", "티커", "산업", "지역", "연도", "구분", "주가", "EPS", "BPS",
                   "매출액", "순이익", "자본총계", "PER", "PBR", "ROE(%)", "PSR", "통화"]
    for index, name in enumerate(raw_columns, 1):
        cell = raw_sheet.cell(row=1, column=index, value=name)
        cell.font, cell.fill, cell.alignment = header_font, header_fill, center
    row_index = 2
    for company in companies:
        for entry in company.get("years", []):
            values = [
                company["name"], company["ticker"], company["industry"], company["region"],
                entry["label"], "확정" if entry["kind"] == "A" else "컨센",
                entry.get("price"), entry.get("eps"), entry.get("bps"),
                entry.get("revenue"), entry.get("net_income"), entry.get("equity"),
                entry.get("per"), entry.get("pbr"), entry.get("roe"), entry.get("psr"),
                company.get("currency"),
            ]
            for c, value in enumerate(values, 1):
                cell = raw_sheet.cell(row=row_index, column=c, value=value)
                cell.font = body_font
                if c in (10, 11, 12):
                    cell.number_format = "#,##0"
            if entry["kind"] == "E":
                for c in range(1, len(raw_columns) + 1):
                    raw_sheet.cell(row=row_index, column=c).fill = est_fill
            row_index += 1
    raw_sheet.freeze_panes = "A2"
    for index, width in enumerate([16, 11, 10, 12, 9, 8] + [13] * 11, 1):
        raw_sheet.column_dimensions[get_column_letter(index)].width = width

    notes = workbook.create_sheet("산출기준")
    for index, line in enumerate([
        ["항목", "정의"],
        ["PER (확정)", "회계연도 기말 시총 ÷ 지배주주순이익"],
        ["PBR (확정)", "회계연도 기말 시총 ÷ 자본총계(기말)"],
        ["PSR (확정)", "회계연도 기말 시총 ÷ 매출액"],
        ["ROE (확정)", "순이익 ÷ 자본총계(기초·기말 평균, 기초 없으면 기말)"],
        ["PER (컨센)", "현재주가 ÷ 야후 컨센서스 EPS"],
        ["PSR (컨센)", "현재시총 ÷ 야후 컨센서스 매출액"],
        ["PBR (컨센)", "현재시총 ÷ 예상자본 — ※ 컨센 원본 아님(이익잉여금 롤포워드 자체 산출)"],
        ["ROE (컨센)", "컨센순이익 ÷ 평균예상자본 — ※ 컨센 원본 아님(자체 산출)"],
        ["예상자본", "직전 확정자본 + 컨센순이익 × (1 − 배당성향)"],
        ["2년후", "야후 파이낸스가 2년후 컨센서스를 제공하지 않아 공란"],
        ["적자·자본잠식", "분모가 0 이하면 배수를 만들지 않고 공란 처리"],
        ["출처", "Yahoo Finance (yfinance)"],
        ["기준시각", payload.get("updated_at", "")],
    ], 1):
        for c, value in enumerate(line, 1):
            cell = notes.cell(row=index, column=c, value=value)
            cell.font = header_font if index == 1 else body_font
            if index == 1:
                cell.fill = header_fill
    notes.column_dimensions["A"].width = 16
    notes.column_dimensions["B"].width = 78

    OUT_XLSX.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(OUT_XLSX)
    print(f"📥 엑셀: {OUT_XLSX} ({OUT_XLSX.stat().st_size / 1024:.0f} KB)")


HTML_TEMPLATE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>밸류에이션 (PER·PBR·ROE·PSR)</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1a1d21;--muted:#6b7280;--line:#e5e7eb;
--accent:#185fa5;--est:#fff6e5;--estline:#f0d9a8;--good:#0ca30c;--bad:#d03b3b}
@media(prefers-color-scheme:dark){:root{--bg:#141516;--card:#1d1e1f;--ink:#f2f2f0;
--muted:#9a9a92;--line:#2f3032;--est:#2a2418;--estline:#4a3f28}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font-family:-apple-system,"Segoe UI","Malgun Gothic",sans-serif;line-height:1.5}
.wrap{max-width:1180px;margin:0 auto;padding:24px 18px 60px}
h1{font-size:20px;font-weight:600;margin:0 0 2px}
.sub{color:var(--muted);font-size:13px}
.bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:16px 0 14px}
.dl{display:inline-flex;align-items:center;gap:6px;background:var(--accent);color:#fff;
text-decoration:none;font-size:13px;font-weight:600;padding:9px 15px;border-radius:9px;border:0;cursor:pointer}
.dl.ghost{background:var(--card);color:var(--ink);border:1px solid var(--line)}
input[type=search]{flex:1;min-width:150px;background:var(--card);border:1px solid var(--line);
border-radius:9px;padding:9px 12px;font-size:13px;color:var(--ink)}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.tab{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:7px 16px;
font-size:13px;font-weight:600;color:var(--muted);cursor:pointer}
.tab.on{background:var(--accent);border-color:var(--accent);color:#fff}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px}
.chip{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:5px 13px;
font-size:12px;color:var(--muted);cursor:pointer}
.chip.on{background:var(--ink);border-color:var(--ink);color:var(--bg)}
.tablewrap{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:auto}
table{border-collapse:collapse;width:100%;font-size:13px;min-width:760px}
th,td{padding:8px 10px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--line)}
th{background:var(--card);font-weight:600;font-size:12px;color:var(--muted);position:sticky;top:0;z-index:2}
th.name,td.name{text-align:left;position:sticky;left:0;background:var(--card);z-index:1}
th.name{z-index:3}
td.name b{font-weight:600}
td.name span{display:block;font-size:11px;color:var(--muted)}
th.est,td.est{background:var(--est)}
th.est{border-bottom:1px solid var(--estline)}
tr:hover td{background:rgba(24,95,165,.06)}
td.na{color:var(--muted)}
.grp{font-size:11px;color:var(--muted);font-weight:600;background:var(--bg)}
.legend{margin-top:14px;font-size:12px;color:var(--muted);line-height:1.7}
.legend b{color:var(--ink)}
.warn{margin-top:10px;font-size:12px;color:var(--bad)}
.mark{color:var(--accent);font-weight:700}
</style></head><body><div class="wrap">
<h1>밸류에이션 — PER · PBR · ROE · PSR</h1>
<div class="sub">야후 파이낸스 기준 · 과거 __HY__개 회계연도(확정) + 컨센서스(올해·내년) · 기준 __UPDATED__</div>

<div class="bar">
  <a class="dl" href="valuation_full.xlsx" download>📥 엑셀 전체 다운로드</a>
  <button class="dl ghost" id="csv" type="button">⤓ 현재 화면 CSV</button>
  <input type="search" id="q" placeholder="기업명 · 티커 검색">
</div>

<div class="tabs" id="tabs"></div>
<div class="chips" id="chips"></div>
<div class="tablewrap"><table><thead id="head"></thead><tbody id="body"></tbody></table></div>

<div class="legend">
  <b>확정(A)</b> = 해당 회계연도 기말 주가·재무제표 기준 · <b class="mark">컨센(E)</b> = 음영 열, 현재 주가 기준<br>
  PER(E)·PSR(E)는 야후 컨센서스 EPS·매출 원본. <b>PBR(E)·ROE(E)는 컨센 항목이 없어</b>
  «직전 확정자본 + 컨센순이익 × (1 − 배당성향)» 롤포워드로 <b>자체 산출</b>한 값이다.<br>
  2년후 열은 야후가 컨센서스를 제공하지 않아 비워 두었다. 적자·자본잠식으로 분모가 0 이하인 배수는 공란.<br>
  ROE는 기초·기말 평균자본 기준(기초 없는 최초 연도만 기말자본).
</div>
<div class="warn" id="warn"></div>
</div>
<script>
const DATA = __PAYLOAD__;
const METRICS = __METRICS__;
const AXIS = __AXIS__;
const state = {metric:'per', industry:'전체', q:''};

const industries = ['전체', ...new Set(DATA.companies.map(c=>c.industry))];
const fmt = (v,m) => v==null ? '' : (m==='roe' ? v.toFixed(1)+'%' : v.toFixed(2));

function render(){
  document.getElementById('tabs').innerHTML = METRICS.map(m=>
    `<button class="tab ${m[0]===state.metric?'on':''}" data-m="${m[0]}">${m[1]}</button>`).join('');
  document.getElementById('chips').innerHTML = industries.map(i=>
    `<button class="chip ${i===state.industry?'on':''}" data-i="${i}">${i}</button>`).join('');

  document.getElementById('head').innerHTML = '<tr><th class="name">기업</th>' +
    AXIS.map(a=>`<th class="${a.kind==='E'?'est':''}">${a.label}</th>`).join('') + '</tr>';

  const q = state.q.trim().toLowerCase();
  const rows = DATA.companies.filter(c =>
    (state.industry==='전체' || c.industry===state.industry) &&
    (!q || c.name.toLowerCase().includes(q) || c.ticker.toLowerCase().includes(q)));

  let html = '', lastSub = null;
  for(const c of rows){
    const key = c.industry + ' · ' + c.sub;
    if(key !== lastSub){
      html += `<tr><td class="grp name">${key}</td>` +
        AXIS.map(a=>`<td class="grp ${a.kind==='E'?'est':''}"></td>`).join('') + '</tr>';
      lastSub = key;
    }
    html += `<tr><td class="name"><b>${c.name}</b><span>${c.ticker} · ${c.region}</span></td>` +
      AXIS.map(a=>{
        const y = (c.years||[]).find(y=>y.year===a.year);
        const v = y ? y[state.metric] : null;
        const derived = y && (y.derived||[]).includes(state.metric) && v!=null;
        return `<td class="${a.kind==='E'?'est':''} ${v==null?'na':''}">` +
               `${fmt(v,state.metric)}${derived?'<span class="mark">*</span>':''}</td>`;
      }).join('') + '</tr>';
  }
  document.getElementById('body').innerHTML = html ||
    '<tr><td class="name">조건에 맞는 종목이 없습니다.</td></tr>';

  const bad = DATA.companies.filter(c=>(c.warnings||[]).length);
  document.getElementById('warn').innerHTML = bad.length
    ? '⚠️ ' + bad.map(c=>`${c.name}: ${c.warnings[0]}`).join(' / ') : '';
}

document.getElementById('tabs').addEventListener('click', e=>{
  const b = e.target.closest('.tab'); if(b){ state.metric = b.dataset.m; render(); }});
document.getElementById('chips').addEventListener('click', e=>{
  const b = e.target.closest('.chip'); if(b){ state.industry = b.dataset.i; render(); }});
document.getElementById('q').addEventListener('input', e=>{ state.q = e.target.value; render(); });

// 화면에 보이는 지표·필터 그대로 CSV. 엑셀 전체본은 위 버튼(4개 지표+원자료).
document.getElementById('csv').addEventListener('click', ()=>{
  const cell = v => `"${String(v??'').replace(/"/g,'""')}"`;
  const head = ['기업명','티커','산업','지역', ...AXIS.map(a=>a.label)];
  const q = state.q.trim().toLowerCase();
  const rows = DATA.companies.filter(c =>
    (state.industry==='전체' || c.industry===state.industry) &&
    (!q || c.name.toLowerCase().includes(q) || c.ticker.toLowerCase().includes(q)))
    .map(c => [c.name, c.ticker, c.industry, c.region,
      ...AXIS.map(a=>{ const y=(c.years||[]).find(y=>y.year===a.year); return y ? (y[state.metric] ?? '') : ''; })]);
  const csv = '\\ufeff' + [head, ...rows].map(r=>r.map(cell).join(',')).join('\\r\\n');
  const url = URL.createObjectURL(new Blob([csv], {type:'text/csv;charset=utf-8'}));
  const a = document.createElement('a');
  a.href = url; a.download = `밸류에이션_${state.metric.toUpperCase()}_${DATA.updated_at.slice(0,10)}.csv`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(()=>URL.revokeObjectURL(url), 1000);
});

render();
</script></body></html>
"""


def build_html(payload):
    axis = year_axis(payload["companies"])
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = (HTML_TEMPLATE
            .replace("__PAYLOAD__", data)
            .replace("__METRICS__", json.dumps([[k, l] for k, l, _ in METRICS], ensure_ascii=False))
            .replace("__AXIS__", json.dumps(axis, ensure_ascii=False))
            .replace("__HY__", str(payload.get("history_years", 4)))
            .replace("__UPDATED__", payload.get("updated_at", "")[:16].replace("T", " ")))
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"🖥️  화면: {OUT_HTML} ({OUT_HTML.stat().st_size / 1024:.0f} KB)")


def main():
    if not IN_JSON.exists():
        sys.exit(f"수집 데이터가 없습니다: {IN_JSON} — 먼저 fetch_valuation.py 를 실행하세요.")
    payload = json.loads(IN_JSON.read_text(encoding="utf-8"))
    if not payload.get("companies"):
        sys.exit("수집 결과가 비어 있어 산출물을 만들지 않습니다.")
    build_xlsx(payload)
    build_html(payload)


if __name__ == "__main__":
    main()
