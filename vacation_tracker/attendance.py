"""월별 근태 체크 — 팀원의 "근태 완벽합니다" 보고를 잡아 월×이름 표로 정리.

휴가 추적과 같은 스캔이 대화를 읽는 김에 근태 보고도 같이 잡는다(별도 세션·
Gemini 없음 — 문구가 정형이라 규칙만으로 충분하다). 저장은 state/attendance.json,
화면은 attendance_report.html(월 ◀▶ + 이름·체크·확인 시각·원문). 구두 보고는
화면 체크박스로 손 토글한다(기입 폼과 같은 GAS 경로에 op=att를 얹음).
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path

from rules import KST, _compact

HERE = Path(__file__).resolve().parent
ATT_PATH = HERE / "state" / "attendance.json"
OUT_PATH = HERE.parent / "telegram_research_dashboard" / "static" / "attendance_report.html"

# "근태 …(긍정)" — 완벽·이상무·문제없음·완료류. 공백/점 낀 표기는 _compact가 붙인다.
_AFFIRM = r"(?:완벽|이상없|이상무|문제없|누락없|완료|끝냈|다했|깨끗|클리어|이슈없|올렸|확인했)"
_AFFIRM_RE = re.compile(rf"근태.{{0,20}}?{_AFFIRM}|{_AFFIRM}.{{0,10}}?근태")
# 부탁·독촉·질문은 보고가 아니다 ("근태 체크해 주세요", "근태 언제까지야?").
_NEGATIVE_RE = re.compile(r"근태[^?]{0,20}[?？]|해줘|해주세요|하세요|해야|부탁|요망|까지야|언제")
_MONTH_RE = re.compile(r"(\d{1,2})\s*월")


def detect_attendance(text: str, msg_dt: datetime) -> dict | None:
    """근태 확인 보고면 {"month": "YYYY-MM"}을, 아니면 None을 돌려준다."""
    compact = _compact(text or "")
    if "근태" not in compact:
        return None
    if _NEGATIVE_RE.search(compact) or not _AFFIRM_RE.search(compact):
        return None
    month, year = msg_dt.month, msg_dt.year
    stated = _MONTH_RE.search(text or "")
    if stated:
        m = int(stated.group(1))
        if 1 <= m <= 12:
            # 미래 달 근태를 보고할 리 없다 — 1월에 "12월 근태"면 지난해 12월.
            year = year - 1 if m > month else year
            month = m
    return {"month": f"{year:04d}-{month:02d}"}


# ── 상태 ───────────────────────────────────────────────────────────────────

def load_store() -> dict:
    if ATT_PATH.exists():
        try:
            return json.loads(ATT_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"months": {}}


def save_store(store: dict) -> None:
    ATT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ATT_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")


def record_hits(store: dict, hits: list[dict]) -> list[dict]:
    """스캔에서 온 근태 보고들을 반영하고, 이번에 새로 확인된 것만 돌려준다.

    hits: [{"name","month","uid","text","msg_date"}] — 같은 달에 다시 보고하면
    최신 메시지로 덮는다(체크 유지). 손으로 해제(checked=false)한 달에 새 보고가
    오면 다시 체크한다(새 메시지는 새 사실).
    """
    fresh = []
    for hit in hits:
        month = store["months"].setdefault(hit["month"], {})
        prev = month.get(hit["name"]) or {}
        if prev.get("uid") == hit["uid"]:
            continue  # 이미 반영된 메시지 (재스캔)
        if not prev.get("checked"):
            fresh.append(hit)
        month[hit["name"]] = {
            "checked": True,
            "uid": hit["uid"],
            "text": hit["text"],
            "msg_date": hit["msg_date"],
            "source": "telegram",
        }
    return fresh


def apply_op(body: dict) -> None:
    """화면 체크박스 토글 한 건: {"op":"att","name","month","checked":true|false}."""
    name = str(body.get("name") or "").strip()
    month = str(body.get("month") or "").strip()
    if not name or not re.fullmatch(r"\d{4}-\d{2}", month):
        raise SystemExit("name과 month(YYYY-MM)는 필수입니다")
    checked = bool(body.get("checked"))
    store = load_store()
    slot = store["months"].setdefault(month, {})
    slot[name] = {
        "checked": checked,
        "uid": slot.get(name, {}).get("uid", ""),
        "text": slot.get(name, {}).get("text", "") if checked else "",
        "msg_date": datetime.now(KST).isoformat(timespec="minutes"),
        "source": "manual",
    }
    save_store(store)
    print(f"근태 {'확인' if checked else '해제'}: {name} ({month}, 수동)")
    build_page(store)


# ── 페이지 ─────────────────────────────────────────────────────────────────

def _team_names() -> list[str]:
    """근태 체크 대상 = 수집하는 팀원(scan:false 제외 → 본인 최광식은 안 나온다)."""
    from render_page import CONFIG_PATH
    try:
        import yaml

        friends = (yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}).get("friends") or []
    except Exception:
        return []
    names = []
    for f in friends:
        if isinstance(f, str):
            names.append(f)
        elif f.get("scan") is not False and f.get("name"):
            names.append(str(f["name"]))
    return sorted(set(names))


PAGE_CSS = """
:root{color-scheme:light}
body{margin:0;padding:28px 24px 60px;background:#fff;color:#333c46;
  font-family:'Pretendard','Malgun Gothic','Apple SD Gothic Neo',sans-serif;line-height:1.7;font-size:15px}
.wrap{max-width:760px;margin:0 auto}
h1{font-size:21px;color:#1f2937;margin:0 0 4px}
.meta{color:#8a94a0;font-size:12.5px;margin-bottom:18px}
.pager{display:flex;align-items:center;gap:10px;margin:14px 0 6px}
.pager button{background:#f5f8fb;border:1px solid #d4dbe3;border-radius:8px;
  padding:4px 12px;font-size:14px;cursor:pointer;color:#2b5f8a}
.pager button:disabled{opacity:.35;cursor:default}
.pager .label{font-size:16.5px;font-weight:700;color:#1f2937;min-width:110px;text-align:center}
.count{color:#8a94a0;font-size:13px;margin-left:6px}
.count b{color:#2b7a4b}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{padding:8px 10px;border-bottom:1px solid #edf0f4;text-align:left;vertical-align:top}
th{color:#8a94a0;font-weight:600;font-size:12.5px}
.name{font-weight:700;color:#1f2937;white-space:nowrap}
.chk{font-size:18px;cursor:pointer;user-select:none;display:inline-block;min-width:26px;text-align:center}
.chk.on{color:#2b7a4b}
.chk.off{color:#c3ccd6}
tr.pending td{opacity:.55}
.when{color:#8a94a0;font-size:12.5px;white-space:nowrap}
.quote{color:#57616c;font-size:13px}
.quote .manual{color:#8a94a0}
.hint{color:#8a94a0;font-size:12.5px;margin-top:16px}
@media (max-width:640px){
  body{padding:18px 10px 50px}
  th.h-when,td.c-when{display:none}
}
"""


def _month_table(month: str, slot: dict, names: list[str]) -> str:
    rows = []
    for name in names:
        rec = slot.get(name) or {}
        checked = bool(rec.get("checked"))
        mark = ('<span class="chk on">✅</span>' if checked
                else '<span class="chk off">☐</span>')
        when = ""
        if rec.get("msg_date"):
            try:
                dt = datetime.fromisoformat(rec["msg_date"])
                when = dt.strftime("%m/%d %H:%M")
            except ValueError:
                when = rec["msg_date"]
        quote = ""
        if checked:
            if rec.get("source") == "manual" or not rec.get("text"):
                quote = '<span class="manual">수동 체크</span>'
            else:
                quote = f"“{html.escape(rec['text'][:140])}”"
        rows.append(
            f'<tr data-name="{html.escape(name)}" data-checked="{1 if checked else 0}">'
            f'<td class="c-name name">{html.escape(name)}</td>'
            f'<td class="c-chk">{mark}</td>'
            f'<td class="c-when when">{html.escape(when)}</td>'
            f'<td class="c-quote quote">{quote}</td></tr>')
    done = sum(1 for n in names if (slot.get(n) or {}).get("checked"))
    return (f'<div class="att-month" data-month="{month}" data-done="{done}" hidden>'
            '<table><thead><tr><th>이름</th><th>확인</th>'
            '<th class="h-when">시각</th><th>내용</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def build_page(store: dict | None = None) -> None:
    from render_page import DISPATCH_ENDPOINT

    store = store if store is not None else load_store()
    names = _team_names()
    now = datetime.now(KST)
    current = now.strftime("%Y-%m")
    months = sorted(set(store.get("months", {})) | {current})
    stamp = now.strftime("%Y-%m-%d %H:%M")

    tables = "".join(_month_table(m, store.get("months", {}).get(m, {}), names)
                     for m in months)
    head = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>월별 근태 체크</title><style>{PAGE_CSS}</style></head><body><div class="wrap">
<h1>✅ 월별 근태 체크</h1>
<div class="meta">갱신 {stamp} · 텔레그램 1:1 대화의 "근태 완벽합니다" 보고를 자동 수집 ·
확인 칸을 누르면 수동 토글</div>
<div class="pager"><button id="m-prev">◀</button><span class="label" id="m-label"></span>
<button id="m-next">▶</button><span class="count" id="m-count"></span></div>
{tables}
<p id="att-status"></p>
<p class="hint">자동 체크 문구 예: "근태 완벽합니다", "9월 근태 이상 없습니다" —
달을 안 적으면 메시지를 보낸 달로 기록됩니다.</p>
</div>
<script>
const EP={json.dumps(DISPATCH_ENDPOINT)};
const PAGE_STAMP={json.dumps(stamp)};
const CURRENT={json.dumps(current)};
</script>
<script>
"""
    script = """
const $id=i=>document.getElementById(i);
const months=[...document.querySelectorAll('.att-month')];
let idx=Math.max(0,months.findIndex(m=>m.dataset.month===CURRENT));
function label(ym){const[y,m]=ym.split('-');return y+'년 '+Number(m)+'월'}
function render(){
  months.forEach((el,i)=>{el.hidden=i!==idx});
  const el=months[idx];
  $id('m-label').textContent=label(el.dataset.month);
  const total=el.querySelectorAll('tbody tr').length;
  const done=el.querySelectorAll('tr[data-checked="1"]').length;
  $id('m-count').innerHTML='확인 <b>'+done+'</b> / '+total;
  $id('m-prev').disabled=idx<=0;
  $id('m-next').disabled=idx>=months.length-1;
}
$id('m-prev').onclick=()=>{if(idx>0){idx--;render()}};
$id('m-next').onclick=()=>{if(idx<months.length-1){idx++;render()}};
render();

async function watchDeploy(){
  for(let i=0;i<24;i++){
    await new Promise(r=>setTimeout(r,15000));
    try{
      const r=await fetch('attendance_report.html?t='+Date.now(),{cache:'no-store'});
      const m=(await r.text()).match(/갱신 ([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2})/);
      if(m&&m[1]!==PAGE_STAMP){location.reload();return}
    }catch(e){}
  }
  const s=$id('att-status');
  if(s)s.textContent='서버 반영 확인이 오래 걸립니다 — 잠시 뒤 수동 새로고침해 주세요';
}

// 확인 칸 클릭 → 토글. 화면에 우선 반영하고 서버(워크플로) 처리 뒤 자동 새로고침.
document.addEventListener('click',async ev=>{
  const chk=ev.target.closest('.chk');if(!chk)return;
  const row=chk.closest('tr'),monthEl=chk.closest('.att-month');
  const name=row.dataset.name,month=monthEl.dataset.month;
  const next=row.dataset.checked!=='1';
  if(!confirm(name+' — '+label(month)+' 근태를 '+(next?'확인 처리':'해제')+'할까요?'))return;
  const status=$id('att-status');
  status.textContent='요청 중…';
  try{
    const payload={op:'att',name:name,month:month,checked:next};
    const r=await fetch(EP,{method:'POST',
      body:JSON.stringify({workflow:'vacation',entry:JSON.stringify(payload)})});
    try{const d=await r.json();
      if(d&&d.ok===false){status.textContent='⚠ 거절 '+(d.code||'?')+' — '+(d.error||'GAS 프록시 확인 필요');return}
    }catch(e){}
    row.dataset.checked=next?'1':'0';
    row.classList.add('pending');
    chk.textContent=next?'✅':'☐';
    chk.classList.toggle('on',next);chk.classList.toggle('off',!next);
    const q=row.querySelector('.c-quote');
    if(q)q.innerHTML=next?'<span class="manual">수동 체크 (반영 중…)</span>':'';
    const w=row.querySelector('.c-when');if(w)w.textContent='방금';
    render();
    status.textContent='✅ 반영 요청됨 — 서버 반영이 끝나면 자동 새로고침됩니다';
    watchDeploy();
  }catch(e){status.textContent='실패: '+e.message}
});
</script></body></html>
"""
    OUT_PATH.write_text(head + script, encoding="utf-8")
    print(f"근태 페이지 생성: {OUT_PATH}")
