"""entries.json → 대시보드 페이지(vacation_report.html).

표준 라이브러리만 쓴다. 다른 리포트 페이지들과 같은 다크 테마.
"""

from __future__ import annotations

import calendar
import html
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from rules import KST

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "telegram_research_dashboard" / "static" / "vacation_report.html"
CONFIG_PATH = Path(__file__).resolve().parent / "config.yml"

# 기입 폼 → GAS dispatch_proxy(vacation) → vacation-tracker.yml(mode=add).
# app.js의 DISPATCH_ENDPOINT와 같은 주소 — 바꿀 땐 두 곳을 같이 고칠 것.
DISPATCH_ENDPOINT = "https://script.google.com/macros/s/AKfycbx3RjIjtlO2Z6fIYo2T3LhJrFg9Wp2hS7dMS3Is52-JVF1hizoCWewbQ1uM_v5sdhR2jw/exec"

KIND_OPTIONS = ["연차", "반차", "오전반차", "오후반차", "휴가", "출장", "해외출장",
                "샵투어", "휴무", "병가", "기타"]


def friend_names() -> list[str]:
    """config.yml의 friends 이름 목록. yaml이 없으면 가벼운 파싱으로 폴백."""
    try:
        text = CONFIG_PATH.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        import yaml

        friends = (yaml.safe_load(text) or {}).get("friends") or []
        return [f if isinstance(f, str) else str(f.get("name") or "") for f in friends if f]
    except ImportError:
        import re

        names, in_friends = [], False
        for line in text.splitlines():
            if line.startswith("friends:"):
                in_friends = True
                continue
            if in_friends:
                match = re.match(r"\s+-\s*(?:name:\s*)?([^#\n]+)", line)
                if match:
                    names.append(match.group(1).strip())
                elif line.strip() and not line.startswith(" "):
                    break
        return names

WEEKDAY_KO = "월화수목금토일"

PAGE_CSS = """
:root{color-scheme:dark}
body{margin:0;padding:28px 24px 60px;background:#0d1117;color:#d8dee9;
  font-family:'Pretendard','Malgun Gothic','Apple SD Gothic Neo',sans-serif;line-height:1.7;font-size:15px}
.wrap{max-width:900px;margin:0 auto}
h1{font-size:21px;color:#e8edf5;margin:0 0 4px}
.meta{color:#8b96a8;font-size:12.5px;margin-bottom:22px}
h2{font-size:16.5px;color:#7fb4ff;margin:30px 0 10px;padding-bottom:6px;border-bottom:1px solid #223046}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{padding:8px 10px;border-bottom:1px solid #1c2534;text-align:left;vertical-align:top}
th{color:#8b96a8;font-weight:600;font-size:12.5px}
tr.today td{background:#14202f}
.badge{display:inline-block;padding:1px 8px;border-radius:20px;font-size:12px;
  background:#1d2a3d;color:#9fc1ff;border:1px solid #2c3a52;white-space:nowrap}
.badge.review{background:#3d2626;color:#ffb3b3;border-color:#5a3535}
.src{color:#8b96a8;font-size:12.5px}
.name{font-weight:700;color:#e8edf5;white-space:nowrap}
.empty{color:#8b96a8;padding:18px 0}
.cal{width:100%;border-collapse:collapse;table-layout:fixed;margin:6px 0 26px;font-size:12.5px}
.cal th{padding:6px 4px;border-bottom:1px solid #223046;color:#8b96a8;font-size:12px;text-align:center}
.cal th.sun,.cal td.sun .d{color:#ff8f8f}
.cal th.sat,.cal td.sat .d{color:#7fb4ff}
.cal td{border:1px solid #1c2534;vertical-align:top;padding:4px 5px;height:56px}
.cal td.blank{background:#0a0e14;border-color:#141b26}
.cal td[data-date]{cursor:pointer}
.cal td[data-date]:hover{background:#121a27}
.cal td.today{background:#14202f;box-shadow:inset 0 0 0 1px #2c3a52}
.cal .d{color:#8b96a8;font-size:11.5px;margin-bottom:3px}
.chip{display:block;margin:2px 0;padding:1px 5px;border-radius:6px;background:#1d2a3d;
  color:#cfe0ff;border:1px solid #2c3a52;font-size:11.5px;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
.chip.trip{background:#3a2f1d;color:#ffd9a0;border-color:#55452c}
.cal-title{font-size:15px;color:#e8edf5;margin:4px 0 6px;font-weight:700}
#cal-strip{display:grid;grid-template-columns:1fr 1fr;gap:18px;align-items:start}
@media(max-width:700px){#cal-strip{grid-template-columns:1fr}}
.cal-month[hidden]{display:none}
.cal-nav{display:flex;align-items:center;gap:12px;margin:10px 0 8px}
.cal-nav button{background:#161d29;color:#cfe0ff;border:1px solid #2c3a52;border-radius:8px;
  padding:5px 14px;font-size:14px;cursor:pointer}
.cal-nav button:hover{border-color:#3d5175}
.cal-nav button:disabled{opacity:.35;cursor:default}
#cal-label{font-size:14.5px;color:#e8edf5;font-weight:700;min-width:180px;text-align:center}
.addform{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0 6px}
.addform input,.addform select{background:#161d29;color:#d8dee9;border:1px solid #2c3a52;
  border-radius:8px;padding:7px 10px;font-size:13.5px;font-family:inherit}
.addform input[type=date]{color-scheme:dark}
.addform button{background:#1d2a3d;color:#cfe0ff;border:1px solid #2c3a52;border-radius:8px;
  padding:7px 14px;font-size:13.5px;cursor:pointer}
.addform button:hover{border-color:#3d5175}
.addform button:disabled{opacity:.5;cursor:default}
#add-status{color:#8b96a8;font-size:12.5px;margin:4px 0 0}
.form-hint{color:#8b96a8;font-size:12.5px;margin:2px 0 0}
.badge.trip{background:#3a2f1d;color:#ffd9a0;border-color:#55452c}
tr.pending td{opacity:.75}
tr.pending .badge,.chip.pending{border-style:dashed}

"""

# 달력 칩 색 구분: 출장·샵투어 계열은 주황, 나머지(휴가·연차·반차…)는 파랑.
TRIP_KINDS = ("출장", "샵투어", "투어")


def _span(entry: dict) -> str:
    if not entry.get("start"):
        return "날짜 미상"
    start = datetime.fromisoformat(entry["start"])
    text = f"{start.strftime('%m/%d')}({WEEKDAY_KO[start.weekday()]})"
    end_raw = entry.get("end") or entry["start"]
    if end_raw != entry["start"]:
        end = datetime.fromisoformat(end_raw)
        days = (end - start).days + 1
        text += f" ~ {end.strftime('%m/%d')}({WEEKDAY_KO[end.weekday()]}) · {days}일"
    return text


def _row(entry: dict, today: str) -> str:
    start, end = entry.get("start"), entry.get("end") or entry.get("start")
    active = ' class="today"' if start and start <= today <= (end or start) else ""
    badge = ('<span class="badge review">확인 필요</span>' if entry.get("needs_review")
             else f'<span class="badge">{html.escape(str(entry.get("kind") or "휴가"))}</span>')
    note = html.escape(str(entry.get("note") or ""))
    msg_date = str(entry.get("msg_date") or "")[:16].replace("T", " ")
    if entry.get("engine") == "manual":
        origin = f"{msg_date} · ✍️ 직접 기입"
    else:
        origin = f"{msg_date} · “{html.escape(str(entry.get('text') or '')[:140])}”"
    return (f"<tr{active}><td class=\"name\">{html.escape(str(entry.get('name') or '?'))}</td>"
            f"<td>{_span(entry)}</td><td>{badge}</td>"
            f"<td>{note}<div class=\"src\">{origin}</div></td></tr>")


def _is_trip(kind: str) -> bool:
    return any(word in str(kind or "") for word in TRIP_KINDS)


def _calendar_section(dated: list[dict], today_d: date) -> str:
    """날짜 있는 항목을 월별 달력 그리드로. 휴가가 있는 달 + 이번 달을 그린다."""
    per_day: dict[date, list[dict]] = {}
    for entry in dated:
        start = date.fromisoformat(entry["start"])
        end = date.fromisoformat(entry.get("end") or entry["start"])
        # 잘못 추출된 초장기 구간이 달력을 도배하지 않게 상한을 둔다.
        end = min(end, start + timedelta(days=60))
        day = start
        while day <= end:
            per_day.setdefault(day, []).append(entry)
            day += timedelta(days=1)

    # 화살표로 좌우 이동하는 구조라 달 목록은 빈 달 없이 연속이어야 한다.
    # 범위: (기록 있는 가장 이른 달 ~ 가장 늦은 달) ∪ (이번 달 ~ +6개월), 최대 24개월.
    def shift(pair, k):
        year, month = pair
        month += k
        while month > 12:
            year, month = year + 1, month - 12
        while month < 1:
            year, month = year - 1, month + 12
        return year, month

    have = {(d.year, d.month) for d in per_day}
    current = (today_d.year, today_d.month)
    lo = min(have | {current})
    hi = max(have | {shift(current, 6)})
    months = []
    cursor = lo
    while cursor <= hi and len(months) < 24:
        months.append(cursor)
        cursor = shift(cursor, 1)
    grid = calendar.Calendar(firstweekday=6)  # 일요일 시작
    parts = []
    for year, month in months:
        rows = []
        for week in grid.monthdatescalendar(year, month):
            cells = []
            for day in week:
                cls = []
                if day.weekday() == 6:
                    cls.append("sun")
                elif day.weekday() == 5:
                    cls.append("sat")
                if day.month != month:
                    cells.append(f'<td class="blank {" ".join(cls)}"></td>')
                    continue
                if day == today_d:
                    cls.append("today")
                attrs = f' data-date="{day.isoformat()}"'
                chips = "".join(
                    f'<span class="chip{" trip" if _is_trip(e.get("kind")) else ""}" '
                    f'title="{html.escape(str(e.get("kind") or ""))}">'
                    f'{html.escape(str(e.get("name") or "?"))}</span>'
                    for e in per_day.get(day, ())
                )
                cells.append(f'<td class="{" ".join(cls)}"{attrs}>'
                             f'<div class="d">{day.day}</div>{chips}</td>')
            rows.append("<tr>" + "".join(cells) + "</tr>")
        head = "".join(
            f'<th class="{cls}">{label}</th>'
            for label, cls in (("일", "sun"), ("월", ""), ("화", ""), ("수", ""),
                               ("목", ""), ("금", ""), ("토", "sat"))
        )
        parts.append(f'<div class="cal-month" data-ym="{year}-{month:02d}" hidden>'
                     f'<div class="cal-title">{year}년 {month}월</div>'
                     f'<table class="cal"><thead><tr>{head}</tr></thead>'
                     f'<tbody>{"".join(rows)}</tbody></table></div>')
    nav = ('<div class="cal-nav"><button id="cal-prev" onclick="calMove(-1)">◀</button>'
           '<span id="cal-label"></span>'
           '<button id="cal-next" onclick="calMove(1)">▶</button></div>')
    return nav + '<div id="cal-strip">' + "".join(parts) + "</div>"


def _add_form(stamp: str) -> str:
    """직접 기입 폼. GAS 프록시(vacation 라우트)로 workflow_dispatch를 쏜다.

    stamp는 이 페이지의 갱신 시각 — 제출 뒤 배포본의 갱신 시각이 달라지면
    자동 새로고침한다. 그 사이 화면에는 점선(pending) 스타일로 즉시 그려 둔다.
    """
    name_options = "".join(f'<option value="{html.escape(n)}">' for n in friend_names() if n)
    kind_options = "".join(f"<option>{k}</option>" for k in KIND_OPTIONS)
    head = f"""
<h2>✍️ 직접 기입</h2>
<p class="form-hint">봇이 못 잡은 일정을 손으로 추가합니다. 화면에는 바로 표시되고,
1~2분 뒤 서버 반영이 끝나면 자동 새로고침됩니다. 잘못 넣은 건 entries.json에서 지우고
rebuild-page로 되돌립니다.</p>
<div class="addform">
  <input id="add-name" list="add-names" placeholder="이름" style="width:110px">
  <datalist id="add-names">{name_options}</datalist>
  <select id="add-kind">{kind_options}</select>
  <input id="add-start" type="date" title="시작일">
  <span>~</span>
  <input id="add-end" type="date" title="종료일 (비우면 하루)">
  <input id="add-note" placeholder="메모 (선택)" style="flex:1;min-width:140px">
  <button id="add-btn" onclick="addEntry()">추가</button>
</div>
<p id="add-status"></p>
<script>
const EP={json.dumps(DISPATCH_ENDPOINT)};
const PAGE_STAMP={json.dumps(stamp)};
"""
    # 아래는 순수 JS — f-string 이스케이프(중괄호 겹침)를 피하려고 분리해 둔다.
    script = """
const $id=i=>document.getElementById(i);
function escText(t){const d=document.createElement('div');d.textContent=t==null?'':t;return d.innerHTML}
function isTrip(kind){return /출장|투어/.test(kind||'')}

// 제출 직후 화면에 임시(pending)로 그린다 — 서버 반영 전에도 바로 보이게.
function localApply(en){
  const today=new Date().toLocaleDateString('sv');
  const tid=(en.end||en.start)>=today?'tbl-upcoming':'tbl-past';
  const tbody=document.querySelector('#'+tid+' tbody');
  if(tbody){
    const empty=tbody.querySelector('.empty-row');if(empty)empty.remove();
    const tr=document.createElement('tr');tr.className='pending';
    const span=en.end&&en.end!==en.start?en.start+' ~ '+en.end:en.start;
    tr.innerHTML='<td class="name">'+escText(en.name)+'</td><td>'+span+'</td>'
      +'<td><span class="badge'+(isTrip(en.kind)?' trip':'')+'">'+escText(en.kind)+'</span></td>'
      +'<td>'+escText(en.note||'')+'<div class="src">방금 · ✍️ 직접 기입 (서버 반영 중…)</div></td>';
    tbody.prepend(tr);
  }
  let day=new Date(en.start+'T00:00:00');const last=new Date((en.end||en.start)+'T00:00:00');
  for(let i=0;i<60&&day<=last;i++){
    const cell=document.querySelector('td[data-date="'+day.toLocaleDateString('sv')+'"]');
    if(cell){const chip=document.createElement('span');
      chip.className='chip pending'+(isTrip(en.kind)?' trip':'');
      chip.title=en.kind;chip.textContent=en.name;cell.appendChild(chip);}
    day.setDate(day.getDate()+1);
  }
}

// 배포본의 '갱신 시각'이 이 페이지와 달라지면 새로고침 — 임시 표시가 진짜 데이터로 교체된다.
async function watchDeploy(){
  const status=$id('add-status');
  for(let i=0;i<24;i++){
    await new Promise(r=>setTimeout(r,15000));
    try{
      const r=await fetch('vacation_report.html?t='+Date.now(),{cache:'no-store'});
      const m=(await r.text()).match(/갱신 ([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2})/);
      if(m&&m[1]!==PAGE_STAMP){location.reload();return}
    }catch(e){}
  }
  if(status)status.textContent='서버 반영 확인이 오래 걸립니다 — 잠시 뒤 수동 새로고침해 주세요';
}

async function addEntry(){
  const name=$id('add-name').value.trim(), start=$id('add-start').value;
  const status=$id('add-status'), btn=$id('add-btn');
  if(!name||!start){status.textContent='⚠ 이름과 시작일은 필수입니다';return}
  // 종료<시작이면 서버(add_manual)가 자동으로 뒤집는다.
  const entry={name:name,start:start,end:$id('add-end').value||start,
    kind:$id('add-kind').value,note:$id('add-note').value.trim()};
  status.textContent='요청 중…';btn.disabled=true;
  try{
    const r=await fetch(EP,{method:'POST',body:JSON.stringify({workflow:'vacation',entry:JSON.stringify(entry)})});
    try{const d=await r.json();
      if(d&&d.ok===false){status.textContent='⚠ 거절 '+(d.code||'?')+' — '+(d.error||'GAS 프록시 확인 필요');return}
    }catch(e){}
    localApply(entry);
    status.textContent='✅ 추가됨 — 화면에 임시 표시했고, 서버 반영이 끝나면 자동 새로고침됩니다';
    $id('add-note').value='';$id('add-start').value='';$id('add-end').value='';
    watchDeploy();
  }catch(e){status.textContent='실패: '+e.message}
  finally{btn.disabled=false}
}

// 달력 페이저: 모든 달이 DOM에 있고, 한 번에 2개월만 보여준다. ◀▶로 한 달씩 이동.
const calMonths=[...document.querySelectorAll('.cal-month')];
let calIdx=0;
function calRender(){
  const maxIdx=Math.max(0,calMonths.length-2);
  calIdx=Math.min(Math.max(0,calIdx),maxIdx);
  calMonths.forEach((m,i)=>{m.hidden=!(i===calIdx||i===calIdx+1)});
  const first=calMonths[calIdx],second=calMonths[calIdx+1];
  const label=$id('cal-label');
  if(label&&first){
    const name=el=>el.querySelector('.cal-title').textContent;
    label.textContent=second?name(first)+' · '+name(second):name(first);
  }
  const prev=$id('cal-prev'),next=$id('cal-next');
  if(prev)prev.disabled=calIdx<=0;
  if(next)next.disabled=calIdx>=maxIdx;
}
function calMove(step){calIdx+=step;calRender()}
{
  const nowYm=new Date().toLocaleDateString('sv').slice(0,7);
  const at=calMonths.findIndex(m=>m.dataset.ym===nowYm);
  calIdx=at>=0?at:0;
  calRender();
}

// 달력 더블클릭 → 기입 폼 날짜 채우기. 첫 더블클릭=시작일,
// 그보다 뒤 날짜를 이어서 더블클릭하면 종료일(기간).
document.addEventListener('dblclick',ev=>{
  const td=ev.target.closest('td[data-date]');if(!td)return;
  const d=td.dataset.date,s=$id('add-start'),e=$id('add-end'),status=$id('add-status');
  if(s.value&&d>s.value&&(!e.value||e.value===s.value)){
    e.value=d;status.textContent='기간 '+s.value+' ~ '+d+" — 이름 고르고 '추가'를 누르세요";
  }else{
    s.value=d;e.value='';status.textContent='시작일 '+d+' — 끝나는 날도 더블클릭하면 기간이 됩니다';
  }
  document.querySelector('.addform').scrollIntoView({behavior:'smooth',block:'center'});
});
</script>"""
    return head + script


def build_page(store: dict) -> Path:
    entries = list((store.get("entries") or {}).values())
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")

    dated = sorted((e for e in entries if e.get("start")),
                   key=lambda e: (e["start"], e.get("name") or ""))
    upcoming = [e for e in dated if (e.get("end") or e["start"]) >= today]
    past = [e for e in dated if (e.get("end") or e["start"]) < today][::-1]  # 최근 순
    review = [e for e in entries if not e.get("start")]

    def table(rows: list[dict], table_id: str = "") -> str:
        # 빈 표도 tbody를 남긴다 — 직접 기입의 즉시 표시(낙관적 행 삽입)가 붙을 곳.
        body = "".join(_row(e, today) for e in rows) or \
            '<tr class="empty-row"><td colspan="4" class="empty">기록 없음</td></tr>'
        id_attr = f' id="{table_id}"' if table_id else ""
        return (f"<table{id_attr}><thead><tr><th>이름</th><th>기간</th><th>종류</th>"
                f"<th>메모 · 원문</th></tr></thead><tbody>{body}</tbody></table>")

    stamp = now.strftime('%Y-%m-%d %H:%M')
    doc = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>팀원 휴가 일정 체크</title><style>{PAGE_CSS}</style></head>
<body><div class="wrap">
<h1>🏖️ 팀원 휴가 일정 체크</h1>
<p class="meta">지정한 팀원들과의 텔레그램 1:1 대화에서 휴가·출장 보고를 자동으로 잡아 정리 ·
갱신 {stamp} KST · 총 {len(entries)}건</p>
<h2>다가오는 휴가 ({len(upcoming)}건)</h2>
{table(upcoming, "tbl-upcoming")}
<h2>📅 달력</h2>
<p class="form-hint">날짜를 더블클릭(모바일: 두 번 탭)하면 아래 기입 폼에 시작일로 들어가고,
이어서 다른 날을 더블클릭하면 기간이 됩니다.</p>
{_calendar_section(dated, now.date()) or '<p class="empty">기록 없음</p>'}
"""
    doc += _add_form(stamp)
    doc += f"""
<h2>지난 휴가 ({len(past)}건)</h2>
{table(past, "tbl-past")}
"""
    if review:
        doc += f"<h2>확인 필요 — 날짜를 못 읽은 보고 ({len(review)}건)</h2>\n{table(review)}\n"
    doc += "</div></body></html>\n"

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(doc, encoding="utf-8")
    print(f"페이지 생성: {OUT_PATH}")
    return OUT_PATH
