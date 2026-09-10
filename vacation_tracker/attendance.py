"""월별 근태 체크 — 팀원의 "근태 완벽합니다" 보고를 잡아 월×이름 표로 정리.

근태 체크는 매월 초의 '체크 기간'에만 돈다: 페이지의 ▶ 체크 시작(대상 월 선택)으로
기간을 열면 휴가 추적과 같은 스캔(하루 2회)이 보고를 잡고, 🏁 마감을 누르면
이후 스캔은 근태 보고를 무시한다(수동 체크박스 토글은 언제든 가능).
기간이 열려 있지 않으면 근태 수집 자체를 하지 않는다 — 평소 잡담에 "근태" 문구가
지나가도 기록되지 않는다.

저장은 state/attendance.json(months=월×이름 기록, campaigns=기간 상태),
화면은 attendance_report.html. 시작·마감·토글 모두 기입 폼과 같은 GAS 경로에
op(att / att-open / att-close)를 얹어 보낸다 — GAS·워크플로 변경 없음.
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
    """근태 확인 보고면 {"month": "YYYY-MM", "explicit": 달을 명시했는지}를 돌려준다.

    explicit=False의 month는 '보낸 달'일 뿐 — 기록 시(record_hits) 열린 체크 기간의
    대상 월로 바뀐다(10월 초에 9월 체크를 돌리는 경우).
    """
    compact = _compact(text or "")
    if "근태" not in compact:
        return None
    if _NEGATIVE_RE.search(compact) or not _AFFIRM_RE.search(compact):
        return None
    month, year = msg_dt.month, msg_dt.year
    explicit = False
    stated = _MONTH_RE.search(text or "")
    if stated:
        m = int(stated.group(1))
        if 1 <= m <= 12:
            # 미래 달 근태를 보고할 리 없다 — 1월에 "12월 근태"면 지난해 12월.
            year = year - 1 if m > month else year
            month = m
            explicit = True
    return {"month": f"{year:04d}-{month:02d}", "explicit": explicit}


# ── 상태 ───────────────────────────────────────────────────────────────────

def load_store() -> dict:
    if ATT_PATH.exists():
        try:
            data = json.loads(ATT_PATH.read_text(encoding="utf-8"))
            data.setdefault("months", {})
            data.setdefault("campaigns", {})
            return data
        except json.JSONDecodeError:
            pass
    return {"months": {}, "campaigns": {}}


def save_store(store: dict) -> None:
    ATT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ATT_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")


def open_campaign_month(store: dict) -> str | None:
    """열려 있는 체크 기간의 대상 월 (없으면 None). 열 때 다른 기간을 닫으므로 최대 1개."""
    opens = sorted(m for m, c in store.get("campaigns", {}).items()
                   if c.get("status") == "open")
    return opens[-1] if opens else None


def record_hits(store: dict, hits: list[dict]) -> list[dict]:
    """스캔에서 온 근태 보고들을 반영하고, 이번에 새로 확인된 것만 돌려준다.

    체크 기간이 열려 있을 때만 기록하고, 모든 보고는 열린 기간의 **대상 월**로
    붙는다 — 9월의 대화는 8월 근태(체크가 8월로 열려 있으면 "근태 완벽"도
    "9월 근태 완벽"도 8월에 기록). 같은 달 재보고는 최신 메시지로 덮고(체크 유지),
    수동 해제 후 새 보고가 오면 다시 체크한다(새 메시지는 새 사실).
    """
    target = open_campaign_month(store)
    fresh = []
    for hit in hits:
        if target is None:
            print(f"  · [근태] 체크 기간 아님 — 무시: {hit['name']} :: {hit['text'][:40]}")
            continue
        month_key = target
        month = store["months"].setdefault(month_key, {})
        prev = month.get(hit["name"]) or {}
        if prev.get("uid") == hit["uid"]:
            continue  # 이미 반영된 메시지 (재스캔)
        if not prev.get("checked"):
            fresh.append({**hit, "month": month_key})
        month[hit["name"]] = {
            "checked": True,
            "uid": hit["uid"],
            "text": hit["text"],
            "note": prev.get("note", ""),  # 손으로 적은 메모는 재보고에도 보존
            "msg_date": hit["msg_date"],
            "source": "telegram",
        }
    return fresh


def apply_op(body: dict) -> None:
    """페이지에서 온 근태 op 한 건.

    att       — 체크 토글: {"op":"att","name","month","checked":true|false}
    att-note  — 내용 메모: {"op":"att-note","name","month","note"} (체크 상태 불변)
    att-open  — 체크 기간 시작: {"op":"att-open","month"} (다른 열린 기간은 닫는다)
    att-close — 체크 기간 마감: {"op":"att-close","month"}
    """
    op = str(body.get("op") or "").strip()
    month = str(body.get("month") or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise SystemExit("month(YYYY-MM)는 필수입니다")
    store = load_store()
    now = datetime.now(KST).isoformat(timespec="minutes")

    if op == "att-open":
        for other, camp in store["campaigns"].items():
            if camp.get("status") == "open" and other != month:
                camp["status"] = "closed"
                camp["closed_at"] = now
                print(f"근태 체크 자동 마감: {other} (새 기간 시작으로)")
        camp = store["campaigns"].setdefault(month, {})
        camp["status"] = "open"
        camp["opened_at"] = now
        camp.pop("closed_at", None)
        print(f"근태 체크 시작: {month}")
    elif op == "att-close":
        camp = store["campaigns"].setdefault(month, {})
        camp["status"] = "closed"
        camp["closed_at"] = now
        print(f"근태 체크 마감: {month} — 이후 스캔은 근태 보고를 무시합니다")
    elif op == "att":
        name = str(body.get("name") or "").strip()
        if not name:
            raise SystemExit("name은 필수입니다")
        checked = bool(body.get("checked"))
        slot = store["months"].setdefault(month, {})
        prev = slot.get(name) or {}
        slot[name] = {
            "checked": checked,
            "uid": prev.get("uid", ""),
            "text": prev.get("text", "") if checked else "",
            "note": prev.get("note", ""),  # 메모는 토글해도 남긴다
            "msg_date": now,
            "source": "manual",
        }
        print(f"근태 {'확인' if checked else '해제'}: {name} ({month}, 수동)")
    elif op == "att-note":
        name = str(body.get("name") or "").strip()
        if not name:
            raise SystemExit("name은 필수입니다")
        slot = store["months"].setdefault(month, {})
        rec = slot.setdefault(name, {"checked": False, "uid": "", "text": "",
                                     "msg_date": "", "source": "manual"})
        rec["note"] = str(body.get("note") or "").strip()
        print(f"근태 메모: {name} ({month}) → {rec['note']!r}")
    else:
        raise SystemExit(f"알 수 없는 근태 op: {op!r}")
    save_store(store)
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
.meta{color:#8a94a0;font-size:12.5px;margin-bottom:14px}
.campaign{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin:0 0 6px;
  padding:10px 12px;background:#f7f9fc;border:1px solid #e3e8ee;border-radius:10px;font-size:13.5px}
.campaign button,.campaign select{background:#fff;border:1px solid #d4dbe3;border-radius:8px;
  padding:4px 12px;font-size:13.5px;cursor:pointer;color:#2b5f8a;font-family:inherit}
.campaign button:hover{border-color:#9fb6cc}
.camp-on{color:#2b7a4b;font-weight:700}
.camp-off{color:#8a94a0}
.pager{display:flex;align-items:center;gap:10px;margin:14px 0 6px}
.pager button{background:#f5f8fb;border:1px solid #d4dbe3;border-radius:8px;
  padding:4px 12px;font-size:14px;cursor:pointer;color:#2b5f8a}
.pager button:disabled{opacity:.35;cursor:default}
.pager .label{font-size:16.5px;font-weight:700;color:#1f2937;min-width:110px;text-align:center}
.status-badge{font-size:12px;padding:1px 9px;border-radius:20px;white-space:nowrap}
.status-badge.open{background:#e7f6ec;color:#2b7a4b;border:1px solid #bfe3cb}
.status-badge.closed{background:#eef1f5;color:#7b8694;border:1px solid #dbe1e8}
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
.srcb{display:inline-block;padding:0 7px;border-radius:20px;font-size:11px;
  background:#eef1f5;color:#7b8694;border:1px solid #dbe1e8;vertical-align:1px}
.srcb.auto{background:#e7f6ec;color:#2b7a4b;border-color:#bfe3cb}
.note-x{color:#8a6d1a}
.note-btn{float:right;background:none;border:none;cursor:pointer;font-size:13px;
  opacity:.45;padding:0 2px}
.note-btn:hover{opacity:1}
.hint{color:#8a94a0;font-size:12.5px;margin-top:16px}
@media (max-width:640px){
  body{padding:18px 10px 50px}
  th.h-when,td.c-when{display:none}
}
"""


def _month_table(month: str, slot: dict, names: list[str], status: str) -> str:
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
        note = str(rec.get("note") or "")
        parts = []
        if checked:
            if rec.get("source") == "telegram" and rec.get("text"):
                parts.append('<span class="srcb auto">자동</span> '
                             f'“{html.escape(rec["text"][:140])}”')
            else:
                parts.append('<span class="srcb">수동</span> '
                             '<span class="manual">수동 체크</span>')
        if note:
            parts.append(f'<span class="note-x">📝 {html.escape(note)}</span>')
        quote = "<br>".join(parts)
        rows.append(
            f'<tr data-name="{html.escape(name)}" data-checked="{1 if checked else 0}"'
            f' data-note="{html.escape(note)}">'
            f'<td class="c-name name">{html.escape(name)}</td>'
            f'<td class="c-chk">{mark}</td>'
            f'<td class="c-when when">{html.escape(when)}</td>'
            f'<td class="c-quote quote"><button class="note-btn" title="내용 메모">✏️</button>'
            f'<span class="q-body">{quote}</span></td></tr>')
    done = sum(1 for n in names if (slot.get(n) or {}).get("checked"))
    return (f'<div class="att-month" data-month="{month}" data-done="{done}"'
            f' data-status="{status}" hidden>'
            '<table><thead><tr><th>이름</th><th>확인</th>'
            '<th class="h-when">시각</th><th>내용</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _prev_month(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


def build_page(store: dict | None = None) -> None:
    from render_page import DISPATCH_ENDPOINT

    store = store if store is not None else load_store()
    names = _team_names()
    now = datetime.now(KST)
    current = now.strftime("%Y-%m")
    campaigns = store.get("campaigns", {})
    months = sorted(set(store.get("months", {})) | set(campaigns) | {current})
    stamp = now.strftime("%Y-%m-%d %H:%M")
    open_month = open_campaign_month(store)

    def month_status(m: str) -> str:
        return campaigns.get(m, {}).get("status") or "none"

    tables = "".join(_month_table(m, store.get("months", {}).get(m, {}), names,
                                  month_status(m))
                     for m in months)

    # 체크 기간 컨트롤 — 열려 있으면 마감·지금 수집, 아니면 대상 월 선택 + 시작.
    if open_month:
        opened = campaigns.get(open_month, {}).get("opened_at", "")[:10]
        campaign = (f'<span class="camp-on">🟢 {html.escape(open_month)} 근태 체크 진행 중'
                    + (f' (시작 {html.escape(opened)})' if opened else '') + '</span>'
                    '<span>— 하루 2회(08:30·18:30) 자동 수집</span>'
                    '<button id="camp-run">🔄 지금 수집</button>'
                    f'<button id="camp-close" data-month="{html.escape(open_month)}">🏁 마감</button>')
    else:
        prev = _prev_month(current)
        campaign = ('<span class="camp-off">⚪ 진행 중인 근태 체크 없음</span>'
                    '<select id="camp-month">'
                    f'<option value="{prev}">전월 ({prev})</option>'
                    f'<option value="{current}">당월 ({current})</option></select>'
                    '<button id="camp-open">▶ 체크 시작</button>')

    head = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>월별 근태 체크</title><style>{PAGE_CSS}</style></head><body><div class="wrap">
<h1>✅ 월별 근태 체크</h1>
<div class="meta">갱신 {stamp} · 체크 기간에만 텔레그램 1:1의 "근태 완벽합니다" 보고를 자동 수집 ·
확인 칸을 누르면 수동 토글</div>
<div class="campaign">{campaign}</div>
<div class="pager"><button id="m-prev">◀</button><span class="label" id="m-label"></span>
<button id="m-next">▶</button><span class="status-badge" id="m-status" hidden></span>
<span class="count" id="m-count"></span></div>
{tables}
<p id="att-status"></p>
<p class="hint">흐름: 매월 초 ▶ 체크 시작(대상 월 선택) → 팀원 보고가 자동으로 ✓ →
다 모이면 🏁 마감(이후 자동 갱신 중단). 자동 체크 문구 예: "근태 완벽합니다",
"9월 근태 이상 없습니다". 마감 뒤에도 확인 칸 클릭으로 수동 수정은 가능합니다.</p>
</div>
<script>
const EP={json.dumps(DISPATCH_ENDPOINT)};
const PAGE_STAMP={json.dumps(stamp)};
const CURRENT={json.dumps(current)};
const OPEN_MONTH={json.dumps(open_month)};
</script>
<script>
"""
    script = """
const $id=i=>document.getElementById(i);
const months=[...document.querySelectorAll('.att-month')];
let idx=months.findIndex(m=>m.dataset.month===(OPEN_MONTH||CURRENT));
if(idx<0)idx=Math.max(0,months.length-1);
function label(ym){const[y,m]=ym.split('-');return y+'년 '+Number(m)+'월 근태'}
function render(){
  months.forEach((el,i)=>{el.hidden=i!==idx});
  const el=months[idx];
  $id('m-label').textContent=label(el.dataset.month);
  const total=el.querySelectorAll('tbody tr').length;
  const done=el.querySelectorAll('tr[data-checked="1"]').length;
  $id('m-count').innerHTML='확인 <b>'+done+'</b> / '+total;
  const st=$id('m-status');
  st.hidden=el.dataset.status==='none';
  st.textContent=el.dataset.status==='open'?'체크 진행 중':'마감';
  st.className='status-badge '+(el.dataset.status==='open'?'open':'closed');
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

async function sendOp(payload){
  const status=$id('att-status');
  status.textContent='요청 중…';
  try{
    const r=await fetch(EP,{method:'POST',
      body:JSON.stringify({workflow:'vacation',entry:JSON.stringify(payload)})});
    try{const d=await r.json();
      if(d&&d.ok===false){status.textContent='⚠ 거절 '+(d.code||'?')+' — '+(d.error||'GAS 프록시 확인 필요');return false}
    }catch(e){}
    status.textContent='✅ 반영 요청됨 — 서버 반영이 끝나면 자동 새로고침됩니다';
    watchDeploy();
    return true;
  }catch(e){status.textContent='실패: '+e.message;return false}
}

// 체크 기간 시작/마감/지금 수집
const openBtn=$id('camp-open');
if(openBtn)openBtn.onclick=async()=>{
  const month=$id('camp-month').value;
  if(!confirm(label(month)+' 체크를 시작할까요?\\n시작하면 하루 2회 자동 수집됩니다.'))return;
  openBtn.disabled=true;
  if(await sendOp({op:'att-open',month:month}))openBtn.textContent='시작 중…';
  else openBtn.disabled=false;
};
const closeBtn=$id('camp-close');
if(closeBtn)closeBtn.onclick=async()=>{
  const month=closeBtn.dataset.month;
  if(!confirm(label(month)+' 체크를 마감할까요?\\n마감하면 자동 갱신이 중단됩니다(수동 수정은 계속 가능).'))return;
  closeBtn.disabled=true;
  if(await sendOp({op:'att-close',month:month}))closeBtn.textContent='마감 중…';
  else closeBtn.disabled=false;
};
const runBtn=$id('camp-run');
if(runBtn)runBtn.onclick=async()=>{
  runBtn.disabled=true;
  const status=$id('att-status');
  status.textContent='요청 중…';
  try{
    const r=await fetch(EP,{method:'POST',body:JSON.stringify({workflow:'vacation',mode:'run'})});
    try{const d=await r.json();
      if(d&&d.ok===false){status.textContent='⚠ 거절 '+(d.code||'?')+' — '+(d.error||'GAS 프록시 확인 필요');runBtn.disabled=false;return}
    }catch(e){}
    status.textContent='✅ 수집 중 — 2~3분 뒤 새 데이터가 오면 자동 새로고침됩니다';
    watchDeploy();
  }catch(e){status.textContent='실패: '+e.message;runBtn.disabled=false}
};

// 확인 칸 클릭 → 토글. 화면에 우선 반영하고 서버(워크플로) 처리 뒤 자동 새로고침.
document.addEventListener('click',async ev=>{
  const chk=ev.target.closest('.chk');if(!chk)return;
  const row=chk.closest('tr'),monthEl=chk.closest('.att-month');
  const name=row.dataset.name,month=monthEl.dataset.month;
  const next=row.dataset.checked!=='1';
  if(!confirm(name+' — '+label(month)+'를 '+(next?'확인 처리':'해제')+'할까요?'))return;
  if(!await sendOp({op:'att',name:name,month:month,checked:next}))return;
  row.dataset.checked=next?'1':'0';
  row.classList.add('pending');
  chk.textContent=next?'✅':'☐';
  chk.classList.toggle('on',next);chk.classList.toggle('off',!next);
  const q=row.querySelector('.q-body');
  if(q)q.innerHTML=next?'<span class="srcb">수동</span> <span class="manual">수동 체크 (반영 중…)</span>':'';
  const w=row.querySelector('.c-when');if(w)w.textContent='방금';
  render();
});

// 내용 ✏️ → 메모 입력/수정 (체크 상태는 안 건드린다)
document.addEventListener('click',async ev=>{
  const btn=ev.target.closest('.note-btn');if(!btn)return;
  const row=btn.closest('tr'),monthEl=btn.closest('.att-month');
  const name=row.dataset.name,month=monthEl.dataset.month;
  const value=prompt(name+' — '+label(month)+' 메모',row.dataset.note||'');
  if(value===null)return;
  if(!await sendOp({op:'att-note',name:name,month:month,note:value.trim()}))return;
  row.dataset.note=value.trim();
  row.classList.add('pending');
  const q=row.querySelector('.q-body');
  if(q){
    const old=q.querySelector('.note-x');if(old)old.remove();
    const br=q.querySelector('br');if(br)br.remove();
    if(value.trim()){
      if(q.innerHTML.trim())q.insertAdjacentHTML('beforeend','<br>');
      const span=document.createElement('span');span.className='note-x';
      span.textContent='📝 '+value.trim();q.appendChild(span);
    }
  }
});
</script></body></html>
"""
    OUT_PATH.write_text(head + script, encoding="utf-8")
    print(f"근태 페이지 생성: {OUT_PATH}")
