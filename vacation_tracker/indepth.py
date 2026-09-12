"""인뎁스/자료 발간 계획 추적 — 팀원과의 1:1 대화에서 리서치 자료 발간 계획을 잡아 정리.

휴가 추적과 같은 스캔에 편승해 새 메시지를 보고, `--indepth-backfill`로 지난 석 달을
한 번 소급한다(last_id를 건드리지 않아 휴가·근태 수집과 무관).

"인뎁스"라고 콕 집지 않는 보고("발간 타겟해보겠습니다", "자료 마무리 중입니다")도
잡아야 하므로 규칙 프리필터는 넓게 열고(발간·커버리지·개시·자료/보고서 작성 등),
Gemini가 문맥으로 '발간 계획인가'를 판정해 {주제, 예정일, 종류}로 구조화한다.
Gemini가 없으면 강한 키워드(인뎁스·커버리지·개시·발간)만 needs_review로 남긴다.

저장 state/indepth.json, 화면 static/indepth_report.html. 완료✓·메모·삭제는
기입 폼과 같은 GAS 경로에 op(idx-done/idx-note/idx-del)를 얹는다 — GAS 변경 없음.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from rules import KST, _compact

HERE = Path(__file__).resolve().parent
IDX_PATH = HERE / "state" / "indepth.json"
OUT_PATH = HERE.parent / "telegram_research_dashboard" / "static" / "indepth_report.html"

WEEKDAY_KO = "월화수목금토일"

# 프리필터는 관대하게 — 최종 판정은 Gemini가 한다. compact 텍스트(공백·점 제거) 기준.
_KEYWORD_RE = re.compile(
    r"인뎁스|인댑스|indepth|커버리지|개시보고|이니시|발간|스몰캡자료|산업자료|탐방자료"
    r"|자료.{0,8}(?:쓰고|쓸|씁|작성|준비|마무리|초안|타겟)"
    r"|보고서.{0,8}(?:쓰고|쓸|씁|작성|준비|마무리|초안|타겟)",
    re.IGNORECASE)
# Gemini 폴백 때만 쓰는 좁은 키워드 — 이것만 needs_review로 남긴다.
_STRONG_RE = re.compile(r"인뎁스|인댑스|indepth|커버리지|개시보고|이니시|발간", re.IGNORECASE)


def is_candidate(text: str) -> bool:
    return bool(_KEYWORD_RE.search(_compact(text or "")))


def is_strong(text: str) -> bool:
    return bool(_STRONG_RE.search(_compact(text or "")))


def pick_indepth_candidates(timeline: list[dict], hours: int = 12) -> list[dict]:
    """키워드가 있는 메시지 + (내 키워드 질문 뒤의) 상대 답 두 건을 후보로.

    "인뎁스 언제 나와?"(내 질문) → "다음주까지 마무리요"(답)처럼 키워드와 시점이
    갈라진 문답을 잡기 위해서다. 판정은 Gemini가 맥락과 함께 한다.
    """
    picked: dict[int, str] = {}
    for index, msg in enumerate(timeline):
        if not msg.get("text"):
            continue
        if not is_candidate(msg["text"]):
            continue
        picked.setdefault(index, "keyword")
        if msg.get("out"):  # 내 질문/언급 — 뒤따르는 상대 답 2건도 후보에 넣는다
            grabbed = 0
            for j in range(index + 1, len(timeline)):
                later = timeline[j]
                if grabbed >= 2:
                    break
                if (later["dt"] - msg["dt"]) > timedelta(hours=hours):
                    break
                if later.get("out") or not later.get("text"):
                    continue
                picked.setdefault(j, "context")
                grabbed += 1
    return [{"index": i, "trigger": t} for i, t in sorted(picked.items())]


# ── Gemini 판정 ────────────────────────────────────────────────────────────

GEMINI_IDX_PROMPT = """너는 증권사 리서치팀장의 텔레그램 1:1 대화에서 팀원(분석원)의
'자료 발간 계획'을 추려 정리하는 비서다. 발간 계획 = 인뎁스·개시(이니시에이션)·산업·
스몰캡·탐방 등 리서치 자료를 쓰고 있거나 언제까지 내겠다는 이야기. '인뎁스'라는 말이
없어도 자료/보고서를 작성·발간하겠다는 맥락이면 계획이다.

입력은 번호가 붙은 메시지 목록이다. 각 메시지에는 보낸 사람, 보낸 시각(KST, 요일 포함),
본문이 있고 일부에는 (맥락)으로 직전 대화가 붙어 있다. '나'는 팀장(계정 주인)이다.

메시지마다 아래를 판정해 JSON 배열로만 답하라(설명 금지):
[{"i": <메시지 번호>, "plan": true|false, "topic": "주제(종목·산업, 짧게)",
  "target": "YYYY-MM-DD"|null, "target_text": "원문의 시점 표현(없으면 빈 문자열)",
  "kind": "인뎁스|개시|산업|스몰캡|탐방|기타"}]

판정 기준:
- plan=true는 그 대화 상대(분석원)가 자기 자료의 발간 계획·진행 상황을 말한 것만.
  남의 자료 공유, 이미 발간된 자료 링크, 자료 요청("자료 보내줘"), 단순 질문은 false.
- 맥락의 질문(예: "인뎁스 언제 나와?")에 대한 답이면 plan=true — 주제·종류는 맥락에서 찾아라.
- "내일", "다음주 금요일" 같은 상대 시점은 메시지의 보낸 시각 기준으로 target을 계산한다.
  "9월 중", "추석 전"처럼 특정일이 없으면 target=null로 두고 target_text에 그대로 남겨라.
- topic은 종목명/산업명 위주로 짧게. 정 모르겠으면 빈 문자열."""


def _gemini_extract(candidates: list[dict]) -> dict[int, dict] | None:
    if not os.environ.get("GEMINI_API_KEY") or not candidates:
        return None
    try:
        from google import genai
        from google.genai import types as genai_types
    except ImportError:
        return None
    import time

    client = genai.Client()
    config = genai_types.GenerateContentConfig(
        system_instruction=GEMINI_IDX_PROMPT,
        temperature=0.1,
        max_output_tokens=8192,
        response_mime_type="application/json",
    )
    primary = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    models = list(dict.fromkeys([primary, "gemini-flash-lite-latest"]))

    result: dict[int, dict] = {}
    chunk_size = 40  # 백필은 후보가 많다 — 나눠 보낸다
    for offset in range(0, len(candidates), chunk_size):
        chunk = candidates[offset:offset + chunk_size]
        lines = []
        for local_i, cand in enumerate(chunk):
            stamp = datetime.fromisoformat(cand["msg_date"])
            who = "나(팀장)" if cand.get("by_me") else cand["name"]
            block = (f"[{local_i}] {who} · {stamp.strftime('%Y-%m-%d')}"
                     f"({WEEKDAY_KO[stamp.weekday()]}) {stamp.strftime('%H:%M')}")
            if cand.get("context"):
                block += f"\n(맥락)\n{cand['context']}"
            block += f"\n(대상 메시지) {cand['text']}"
            lines.append(block)
        payload = "\n\n".join(lines)
        got = None
        for model in models:
            for attempt in range(2):
                try:
                    response = client.models.generate_content(model=model, contents=payload,
                                                              config=config)
                    rows = json.loads((response.text or "").strip())
                    got = {}
                    for row in rows if isinstance(rows, list) else []:
                        if isinstance(row, dict) and isinstance(row.get("i"), int):
                            got[row["i"]] = row
                    break
                except Exception as exc:
                    print(f"[Gemini-인뎁스:{model}] 오류(시도 {attempt + 1}): {exc}",
                          file=sys.stderr)
                    time.sleep(30 * (attempt + 1))
            if got is not None:
                break
        if got is None:
            return None if not result else result  # 부분 성공은 살린다
        for local_i, verdict in got.items():
            result[offset + local_i] = verdict
        print(f"[Gemini-인뎁스] {offset + len(chunk)}/{len(candidates)} 판정")
    return result


def extract(candidates: list[dict]) -> list[dict]:
    """후보 → 확정 항목. Gemini가 '계획 아님'이라 한 건은 버린다.

    Gemini 불가 시 폴백: 강한 키워드(인뎁스·커버리지·개시·발간)가 본문에 직접 있는
    건만 needs_review로 남긴다(넓은 프리필터를 다 남기면 잡담이 쏟아진다).
    """
    verdicts = _gemini_extract(candidates)
    entries: list[dict] = []
    for index, cand in enumerate(candidates):
        verdict = (verdicts or {}).get(index)
        if verdict is not None:
            if not verdict.get("plan"):
                continue
            target = str(verdict.get("target") or "").strip() or None
            if target:
                try:
                    datetime.strptime(target, "%Y-%m-%d")
                except ValueError:
                    target = None
            entry = {
                "topic": str(verdict.get("topic") or "").strip(),
                "kind": str(verdict.get("kind") or "기타").strip() or "기타",
                "target": target,
                "target_text": str(verdict.get("target_text") or "").strip(),
                "needs_review": False,
                "engine": "gemini",
            }
        else:
            if cand.get("by_me") or not is_strong(cand["text"]):
                continue
            entry = {"topic": "", "kind": "기타", "target": None, "target_text": "",
                     "needs_review": True, "engine": "rule"}
        display_text = cand["text"]
        if cand.get("trigger") == "context" and cand.get("context"):
            display_text = f"{cand['context'].splitlines()[-1]} → {cand['text']}"
        entry.update(uid=cand["uid"], name=cand["name"], text=display_text,
                     note="", done=False,
                     msg_date=cand["msg_date"],
                     detected_at=datetime.now(KST).isoformat(timespec="minutes"))
        entries.append(entry)
    return entries


# ── 상태 ───────────────────────────────────────────────────────────────────

def load_store() -> dict:
    if IDX_PATH.exists():
        try:
            return json.loads(IDX_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"entries": {}}


def save_store(store: dict) -> None:
    IDX_PATH.parent.mkdir(parents=True, exist_ok=True)
    IDX_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")


def record(store: dict, entries: list[dict]) -> list[dict]:
    """새 항목만 저장하고 돌려준다. 아는 uid는 건드리지 않는다(수동 수정 보호)."""
    known = store.setdefault("entries", {})
    fresh = []
    for entry in entries:
        if entry["uid"] in known:
            continue
        known[entry["uid"]] = {k: v for k, v in entry.items() if k != "uid"}
        fresh.append(entry)
    return fresh


def apply_op(body: dict) -> None:
    """페이지에서 온 op 한 건: idx-del / idx-note / idx-done."""
    op = str(body.get("op") or "").strip()
    uid = str(body.get("uid") or "").strip()
    if not uid:
        raise SystemExit("uid가 비어 있습니다")
    store = load_store()
    entry = store["entries"].get(uid)
    if entry is None:
        print(f"[경고] uid를 찾지 못했습니다: {uid} — 변경 없음")
    elif op == "idx-del":
        store["entries"].pop(uid)
        print(f"발간계획 삭제: {entry.get('name')} {entry.get('topic')!r} ({uid})")
    elif op == "idx-note":
        entry["note"] = str(body.get("note") or "").strip()
        print(f"발간계획 메모: {entry.get('name')} ({uid}) → {entry['note']!r}")
    elif op == "idx-done":
        entry["done"] = bool(body.get("done"))
        print(f"발간계획 {'완료' if entry['done'] else '완료 해제'}: "
              f"{entry.get('name')} {entry.get('topic')!r} ({uid})")
    else:
        raise SystemExit(f"알 수 없는 인뎁스 op: {op!r}")
    save_store(store)
    build_page(store)


# ── 페이지 ─────────────────────────────────────────────────────────────────

PAGE_CSS = """
:root{color-scheme:light}
body{margin:0;padding:28px 24px 60px;background:#fff;color:#333c46;
  font-family:'Pretendard','Malgun Gothic','Apple SD Gothic Neo',sans-serif;line-height:1.7;font-size:15px}
.wrap{max-width:900px;margin:0 auto}
h1{font-size:21px;color:#1f2937;margin:0 0 4px}
.meta{color:#8a94a0;font-size:12.5px;margin-bottom:22px}
.run-btn{background:#f5f8fb;border:1px solid #d4dbe3;border-radius:8px;padding:2px 10px;
  font-size:12.5px;cursor:pointer;color:#2b5f8a;margin-left:8px}
h2{font-size:16.5px;color:#2b5f8a;margin:30px 0 10px;padding-bottom:6px;border-bottom:1px solid #e3e8ee}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{padding:8px 10px;border-bottom:1px solid #edf0f4;text-align:left;vertical-align:top}
th{color:#8a94a0;font-weight:600;font-size:12.5px}
.name{font-weight:700;color:#1f2937;white-space:nowrap}
.topic{font-weight:600;color:#2b5f8a}
.badge{display:inline-block;padding:1px 8px;border-radius:20px;font-size:12px;
  background:#e8f0fe;color:#2b5f8a;border:1px solid #c9dcf5;white-space:nowrap}
.badge.review{background:#fdecec;color:#a43c31;border-color:#f2cfcb}
.tgt{white-space:nowrap}
.tgt .vague{color:#8a6d1a}
.chk{font-size:17px;cursor:pointer;user-select:none;display:inline-block;min-width:24px;text-align:center}
.chk.on{color:#2b7a4b}
.chk.off{color:#c3ccd6}
tr.pending td{opacity:.55}
tr.removed{display:none}
.src{color:#8a94a0;font-size:12.5px}
.note-x{color:#8a6d1a;font-size:13px}
.acts{float:right;white-space:nowrap}
.acts button{background:none;border:none;cursor:pointer;font-size:13px;opacity:.45;padding:0 3px}
.acts button:hover{opacity:1}
.empty{color:#8a94a0;padding:18px 0}
.hint{color:#8a94a0;font-size:12.5px;margin-top:16px}
@media (max-width:640px){
  body{padding:18px 10px 50px}
  table,thead,tbody,tr,th,td{display:block}
  thead{display:none}
  tr{border:1px solid #e3e8ee;border-radius:10px;margin-bottom:10px;padding:8px 10px}
  td{border:none;padding:2px 0}
}
"""


def _fmt_target(entry: dict) -> str:
    if entry.get("target"):
        dt = datetime.fromisoformat(entry["target"])
        return f"{dt.strftime('%m/%d')}({WEEKDAY_KO[dt.weekday()]})"
    if entry.get("target_text"):
        return f'<span class="vague">{html.escape(entry["target_text"])}</span>'
    return '<span class="vague">미정</span>'


def _row(uid: str, entry: dict) -> str:
    done = bool(entry.get("done"))
    review = bool(entry.get("needs_review"))
    badge = ('<span class="badge review">확인 필요</span>' if review
             else f'<span class="badge">{html.escape(entry.get("kind") or "기타")}</span>')
    mark = ('<span class="chk on" title="발간 완료 — 누르면 해제">✅</span>' if done
            else '<span class="chk off" title="누르면 발간 완료 처리">☐</span>')
    when = ""
    try:
        when = datetime.fromisoformat(entry.get("msg_date", "")).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        pass
    note = str(entry.get("note") or "")
    note_html = f'<div class="note-x">📝 {html.escape(note)}</div>' if note else ""
    return (f'<tr data-uid="{html.escape(uid)}" data-done="{1 if done else 0}"'
            f' data-note="{html.escape(note)}">'
            f'<td class="c-name name">{html.escape(entry.get("name") or "")}</td>'
            f'<td class="c-topic topic">{html.escape(entry.get("topic") or "—")}</td>'
            f'<td class="c-tgt tgt">{_fmt_target(entry)}</td>'
            f'<td class="c-kind">{badge}</td>'
            f'<td class="c-done">{mark}</td>'
            f'<td class="c-note"><span class="acts">'
            f'<button data-act="note" title="메모">✏️</button>'
            f'<button data-act="del" title="삭제">🗑</button></span>'
            f'{note_html}'
            f'<div class="src">{html.escape(when)} · “{html.escape(entry.get("text", "")[:160])}”</div>'
            f'</td></tr>')


def _table(entries: list[tuple[str, dict]], empty_msg: str) -> str:
    if not entries:
        return f'<p class="empty">{empty_msg}</p>'
    head = ('<table><thead><tr><th>이름</th><th>주제</th><th>예정</th><th>종류</th>'
            '<th>발간</th><th>메모 · 원문</th></tr></thead><tbody>')
    return head + "".join(_row(uid, e) for uid, e in entries) + "</tbody></table>"


def build_page(store: dict | None = None) -> None:
    from render_page import DISPATCH_ENDPOINT

    store = store if store is not None else load_store()
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    stamp = now.strftime("%Y-%m-%d %H:%M")

    items = list(store.get("entries", {}).items())
    review = [(u, e) for u, e in items if e.get("needs_review") and not e.get("done")]
    upcoming = [(u, e) for u, e in items if not e.get("needs_review") and not e.get("done")
                and (not e.get("target") or e["target"] >= today)]
    past = [(u, e) for u, e in items if e.get("done")
            or (not e.get("needs_review") and e.get("target") and e["target"] < today)]
    upcoming.sort(key=lambda x: (x[1].get("target") or "9999", x[1].get("name") or ""))
    past.sort(key=lambda x: (x[1].get("target") or x[1].get("msg_date") or ""), reverse=True)
    review.sort(key=lambda x: x[1].get("msg_date") or "", reverse=True)

    body = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>인뎁스/자료 발간 계획</title><style>{PAGE_CSS}</style></head><body><div class="wrap">
<h1>📚 인뎁스/자료 발간 계획</h1>
<p class="meta">팀원들과의 텔레그램 1:1 대화에서 자료 발간 계획을 자동으로 잡아 정리 ·
갱신 {stamp} KST · 총 {len(items)}건
<button id="run-btn" class="run-btn" onclick="runScan()">🔄 지금 수집</button>
<span id="run-status"></span></p>
<h2>발간 예정 ({len(upcoming)}건)</h2>
{_table(upcoming, "잡힌 발간 계획이 없습니다.")}
<h2>확인 필요 ({len(review)}건)</h2>
{_table(review, "확인할 항목이 없습니다.")}
<h2>지난 계획 · 발간 완료 ({len(past)}건)</h2>
{_table(past, "아직 없습니다.")}
<p id="idx-status"></p>
<p class="hint">발간 칸 ☐를 누르면 완료 처리(✅), ✏️는 메모, 🗑는 삭제.
"인뎁스"라고 안 적어도 발간·커버리지·자료 작성 맥락이면 잡습니다 — 잘못 잡힌 건 지워 주세요.</p>
</div>
<script>
const EP={json.dumps(DISPATCH_ENDPOINT)};
const PAGE_STAMP={json.dumps(stamp)};
</script>
<script>
"""
    script = """
const $id=i=>document.getElementById(i);

async function watchDeploy(){
  for(let i=0;i<24;i++){
    await new Promise(r=>setTimeout(r,15000));
    try{
      const r=await fetch('indepth_report.html?t='+Date.now(),{cache:'no-store'});
      const m=(await r.text()).match(/갱신 ([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2})/);
      if(m&&m[1]!==PAGE_STAMP){location.reload();return}
    }catch(e){}
  }
  const s=$id('idx-status');
  if(s)s.textContent='서버 반영 확인이 오래 걸립니다 — 잠시 뒤 수동 새로고침해 주세요';
}

async function sendOp(payload){
  const status=$id('idx-status');
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

async function runScan(){
  const btn=$id('run-btn'),status=$id('run-status');
  btn.disabled=true;status.textContent='요청 중…';
  try{
    const r=await fetch(EP,{method:'POST',body:JSON.stringify({workflow:'vacation',mode:'run'})});
    try{const d=await r.json();
      if(d&&d.ok===false){status.textContent='⚠ 거절 '+(d.code||'?')+' — '+(d.error||'GAS 프록시 확인 필요');btn.disabled=false;return}
    }catch(e){}
    status.textContent='✅ 수집 중 — 2~3분 뒤 자동 새로고침됩니다';
    watchDeploy();
  }catch(e){status.textContent='실패: '+e.message;btn.disabled=false}
}

// 발간 완료 토글
document.addEventListener('click',async ev=>{
  const chk=ev.target.closest('.chk');if(!chk)return;
  const row=chk.closest('tr');if(!row||!row.dataset.uid)return;
  const next=row.dataset.done!=='1';
  if(!confirm((next?'발간 완료 처리':'완료 해제')+'할까요?'))return;
  if(!await sendOp({op:'idx-done',uid:row.dataset.uid,done:next}))return;
  row.dataset.done=next?'1':'0';
  row.classList.add('pending');
  chk.textContent=next?'✅':'☐';
  chk.classList.toggle('on',next);chk.classList.toggle('off',!next);
});

// ✏️ 메모 / 🗑 삭제
document.addEventListener('click',async ev=>{
  const btn=ev.target.closest('.acts button');if(!btn)return;
  const row=btn.closest('tr');if(!row||!row.dataset.uid)return;
  if(btn.dataset.act==='del'){
    if(!confirm('이 항목을 삭제할까요?'))return;
    if(!await sendOp({op:'idx-del',uid:row.dataset.uid}))return;
    row.classList.add('removed');
  }else{
    const value=prompt('메모',row.dataset.note||'');
    if(value===null)return;
    if(!await sendOp({op:'idx-note',uid:row.dataset.uid,note:value.trim()}))return;
    row.dataset.note=value.trim();
    row.classList.add('pending');
    const cell=row.querySelector('.c-note');
    let el=cell.querySelector('.note-x');
    if(!value.trim()){if(el)el.remove()}
    else{
      if(!el){el=document.createElement('div');el.className='note-x';
        cell.insertBefore(el,cell.querySelector('.src'))}
      el.textContent='📝 '+value.trim();
    }
  }
});
</script></body></html>
"""
    OUT_PATH.write_text(body + script, encoding="utf-8")
    print(f"발간계획 페이지 생성: {OUT_PATH}")
