#!/usr/bin/env python3
"""건설기계 브리핑 GPT판(2탄) 발행 도구 — Claude 세션 작성분·ChatGPT 앱 등록분 공용.

기존 건설기계 데일리(construction_daily)는 러너가 수집한 RSS·시세 inputs만 근거로
쓰는 판이라, GPT판은 소스 관점을 달리해 **웹서치 기반**으로 간다(방산과 반대 구성 —
방산은 웹서치판이 원조, RSS판이 3탄). 수동 등록(ChatGPT 앱 산출물)이 항상 우선이고,
등록이 없는 날은 Claude 예약 세션(루틴 [7.5])이 웹서치로 작성한다.

산출물: static/chatgpt_construction/<날짜>.md|.html + chatgpt_construction_report.html
텔레그램: @gs_macro_bot → 'gb 매크로_공부' 채팅방 (CONGPT_TELEGRAM_* 시크릿,
워크플로/ingest가 TELEGRAM_BOT_TOKEN/CHAT_ID로 매핑해 넘긴다. 미설정이면 발송 생략).

입력 경로 두 가지 — construction-gpt.yml 워크플로가 둘 다 처리한다:
  1. 대시보드 붙여넣기 폼(인덱스 페이지 상단) → GAS dispatch_proxy(congpt)
     → workflow_dispatch inputs.content  (환경변수 CONTENT로 들어온다)
  2. construction_gpt/inbox/YYYY-MM-DD.md 파일을 main에 커밋 (push 트리거)
     — workflow_dispatch 문자열 입력칸은 한 줄짜리라 여러 줄 md가 뭉개진다.

렌더링 규칙(표·색)은 construction_briefing_bot.py 의 것을 그대로 재사용한다.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import construction_briefing_bot as cbb  # 같은 디렉터리 — 렌더러·텔레 유틸 재사용

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).resolve().parent           # construction_briefing/
REPO = ROOT.parent
DASH_STATIC = REPO / "telegram_research_dashboard" / "static"
ARCHIVE_DIR = DASH_STATIC / "chatgpt_construction"
INDEX_PAGE = DASH_STATIC / "chatgpt_construction_report.html"
INBOX_DIR = REPO / "construction_gpt" / "inbox"
# --ingest가 처리한 날짜 목록 (커밋 대상 아님) — --send-processed가 읽어 발송
PROCESSED = REPO / ".gpt_construction_processed.json"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# app.js DISPATCH_ENDPOINT 와 같은 주소 — GAS 웹앱 새 배포(주소 변경) 시 같이 고칠 것.
DISPATCH_ENDPOINT = "https://script.google.com/macros/s/AKfycbx3RjIjtlO2Z6fIYo2T3LhJrFg9Wp2hS7dMS3Is52-JVF1hizoCWewbQ1uM_v5sdhR2jw/exec"


def today_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def date_label(date_str: str) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{date_str} ({'월화수목금토일'[d.weekday()]})"


# ── 아카이브 페이지 + 인덱스 ──────────────────────────────────────────────

def write_archive(date_str: str) -> None:
    md_report = (ARCHIVE_DIR / f"{date_str}.md").read_text(encoding="utf-8")
    body = cbb.report_to_page_html(md_report)
    page = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><base target="_blank">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>건설기계 브리핑 GPT판 {date_str}</title><style>{cbb.PAGE_CSS}</style></head>
<body><div class="wrap">
<h1>🧠 글로벌 건설기계 브리핑 (GPT)</h1>
<div class="meta">기준: {date_label(date_str)} · 생성: Claude 예약 세션 — 웹서치 기반 2탄(기존 데일리는 RSS·확정시세 기반) · 수동 등록분은 ChatGPT 앱 산출물</div>
{body}
</div></body></html>"""
    (ARCHIVE_DIR / f"{date_str}.html").write_text(page, encoding="utf-8")
    print(f"[아카이브] chatgpt_construction/{date_str}.html 생성")


def write_index() -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dates = sorted((p.stem for p in ARCHIVE_DIR.glob("????-??-??.html")), reverse=True)
    dates_js = json.dumps(dates, ensure_ascii=False)
    index = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>건설기계 브리핑 GPT판</title><style>
{cbb.PAGE_CSS}
.bar{{display:flex;gap:10px;align-items:center;max-width:860px;margin:0 auto 10px;flex-wrap:wrap}}
.bar h1{{font-size:17px;margin:0;flex:1;min-width:200px}}
select,button{{background:#161d29;color:#d8dee9;border:1px solid #2c3a52;border-radius:8px;
  padding:7px 12px;font-size:13.5px;cursor:pointer}}
iframe{{width:100%;height:calc(100vh - 150px);border:1px solid #3a3046;border-radius:10px;background:#0d1117}}
details.paste{{max-width:860px;margin:0 auto 12px;border:1px solid #3a3046;border-radius:10px;background:#111825}}
details.paste summary{{cursor:pointer;padding:9px 14px;color:#c9a86a;font-size:13.5px}}
.paste-body{{padding:0 14px 12px;display:flex;flex-direction:column;gap:8px}}
.paste-body textarea{{width:100%;box-sizing:border-box;min-height:180px;background:#0d1117;color:#d8dee9;
  border:1px solid #2c3a52;border-radius:8px;padding:10px;font-size:13px;font-family:inherit;line-height:1.6}}
.paste-row{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}
.paste-row input[type=date]{{background:#161d29;color:#d8dee9;border:1px solid #2c3a52;border-radius:8px;padding:6px 10px}}
#paste-status{{font-size:12.5px;color:#8b96a8;margin:0}}
.hint{{font-size:11.5px;color:#66748a}}
</style></head><body>
<div class="bar">
  <h1>🧠 글로벌 건설기계 브리핑 (GPT)</h1>
  <button id="prev" title="이전 날짜">◀</button>
  <select id="dsel"></select>
  <button id="next" title="다음 날짜">▶</button>
</div>
<details class="paste">
  <summary>✍️ ChatGPT 앱 브리핑 직접 등록 (자동 생성보다 우선 적용)</summary>
  <div class="paste-body">
    <div class="paste-row">
      <label for="p-date" style="font-size:12.5px;color:#8b96a8">브리핑 날짜</label>
      <input id="p-date" type="date">
      <button id="p-btn" onclick="submitBrief()">발행 → 대시보드 + 텔레그램</button>
    </div>
    <textarea id="p-md" placeholder="ChatGPT가 만든 건설기계 브리핑 마크다운 전문을 그대로 붙여넣으세요"></textarea>
    <p id="paste-status"></p>
    <p class="hint">같은 날짜로 다시 등록하면 그 날짜 페이지가 새 내용으로 교체됩니다(텔레그램도 다시 발송).
    붙여넣기가 안 되는 환경에서는 리포의 <code>construction_gpt/inbox/YYYY-MM-DD.md</code> 파일로 올려도 됩니다.</p>
  </div>
</details>
<iframe id="frame" title="브리핑"></iframe>
<script>
const DATES={dates_js};
const EP={json.dumps(DISPATCH_ENDPOINT)};
const sel=document.getElementById('dsel'),fr=document.getElementById('frame');
DATES.forEach(d=>{{const o=document.createElement('option');o.value=d;o.textContent=d+' ('+'일월화수목금토'[new Date(d+'T00:00:00').getDay()]+')';sel.appendChild(o)}});
function load(){{fr.src='chatgpt_construction/'+sel.value+'.html'}}
sel.onchange=load;
document.getElementById('prev').onclick=()=>{{if(sel.selectedIndex<DATES.length-1){{sel.selectedIndex++;load()}}}};
document.getElementById('next').onclick=()=>{{if(sel.selectedIndex>0){{sel.selectedIndex--;load()}}}};
if(DATES.length)load();
else fr.srcdoc='<body style="background:#0d1117;color:#8b96a8;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">아직 브리핑이 없습니다 — 매일 아침 자동 생성되며, ✍️ 폼으로 ChatGPT 앱 브리핑을 직접 등록할 수도 있습니다.</body>';
document.getElementById('p-date').value=new Date().toLocaleDateString('sv');
async function submitBrief(){{
  const btn=document.getElementById('p-btn'),st=document.getElementById('paste-status');
  const date=document.getElementById('p-date').value,md=document.getElementById('p-md').value.trim();
  if(!md){{st.textContent='⚠ 본문이 비어 있습니다';return}}
  if(!date){{st.textContent='⚠ 날짜를 선택하세요';return}}
  btn.disabled=true;st.textContent='전송 중…';
  try{{
    const r=await fetch(EP,{{method:'POST',body:JSON.stringify({{workflow:'congpt',date:date,content:md}})}});
    try{{const d=await r.json();
      if(d&&d.ok===false){{st.textContent='⚠ 거절 '+(d.code||'?')+' — '+(d.error||'GAS 프록시 확인 필요');btn.disabled=false;return}}
    }}catch(e){{}}
    document.getElementById('p-md').value='';
    const isNew=!DATES.includes(date);
    st.textContent='✅ 접수됨 — 페이지 생성·배포에 2~4분, 텔레그램은 곧 도착합니다.'+(isNew?' 새 날짜가 뜨면 자동 새로고침합니다.':' (같은 날짜 재등록 — 잠시 후 직접 새로고침하세요)');
    if(isNew){{
      let n=0;const t=setInterval(async()=>{{
        n++;if(n>20){{clearInterval(t);return}}
        try{{const h=await fetch('chatgpt_construction/'+date+'.html',{{method:'HEAD',cache:'no-store'}});
          if(h.ok){{clearInterval(t);location.reload()}}}}catch(e){{}}
      }},20000);
    }}
  }}catch(e){{st.textContent='실패: '+e.message;btn.disabled=false}}
}}
</script></body></html>"""
    INDEX_PAGE.write_text(index, encoding="utf-8")
    print(f"[인덱스] chatgpt_construction_report.html 갱신 (누적 {len(dates)}일)")


# ── 입력 수집 (폼 content 또는 inbox 파일) ────────────────────────────────

def ingest() -> list[str]:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dates: list[str] = []
    content = os.environ.get("CONTENT", "").strip()
    if content:
        date_str = os.environ.get("DATE", "").strip()
        if not DATE_RE.match(date_str):
            date_str = today_kst()
        (ARCHIVE_DIR / f"{date_str}.md").write_text(content + "\n", encoding="utf-8")
        dates.append(date_str)
        print(f"[입력] 폼 content → chatgpt_construction/{date_str}.md ({len(content)}자)")
    elif INBOX_DIR.is_dir():
        for f in sorted(INBOX_DIR.glob("*.md")):
            if f.name.lower().startswith("readme"):
                continue  # 안내문은 브리핑이 아니다
            body = f.read_text(encoding="utf-8").strip()
            if not body:
                f.unlink()
                continue
            date_str = f.stem if DATE_RE.match(f.stem) else today_kst()
            (ARCHIVE_DIR / f"{date_str}.md").write_text(body + "\n", encoding="utf-8")
            f.unlink()  # 처리한 inbox 파일은 지운다 (커밋 스텝이 삭제까지 반영)
            dates.append(date_str)
            print(f"[입력] inbox/{f.name} → chatgpt_construction/{date_str}.md ({len(body)}자)")
    if not dates:
        print("[입력] 처리할 브리핑 없음 (CONTENT 비어 있고 inbox도 빈 상태)")
    for d in dict.fromkeys(dates):
        write_archive(d)
    write_index()
    PROCESSED.write_text(json.dumps(sorted(set(dates))), encoding="utf-8")
    return dates


# ── 텔레그램 (@gs_macro_bot → 'gb 매크로_공부' — 시크릿 매핑은 워크플로에서) ──

def send_telegram(date_str: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("[텔레그램] TELEGRAM_BOT_TOKEN/CHAT_ID 미설정 — 발송 생략")
        return
    import requests

    md_report = (ARCHIVE_DIR / f"{date_str}.md").read_text(encoding="utf-8")
    base_url = os.environ.get("DASHBOARD_BASE_URL", "https://gschoie.github.io/GS-DB2")
    body = cbb.to_telegram_html(cbb.extract_summary(md_report))
    header = f"🧠 <b>글로벌 건설기계 브리핑 (GPT)</b> | {date_label(date_str)}\n"
    footer = (f'\n\n📊 <a href="{base_url}/chatgpt_construction/{date_str}.html">'
              "전체 브리핑 보기</a>\n"
              "<i>발송 직후엔 반영 중일 수 있어요 — 2~3분 뒤 열어주세요</i>")
    chunks = cbb.split_chunks(header + body + footer)
    total = len(chunks)
    for i, chunk in enumerate(chunks, 1):
        suffix = f"\n\n({i}/{total})" if total > 1 else ""
        for attempt in range(3):
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": chunk + suffix, "parse_mode": "HTML",
                      "disable_web_page_preview": True},
                timeout=30,
            )
            if resp.ok:
                break
            if resp.status_code == 400 and attempt == 0:
                print(f"[텔레그램 400] {resp.text[:200]} → 평문 재시도", file=sys.stderr)
                resp = requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": re.sub(r"<[^>]+>", "", chunk) + suffix,
                          "disable_web_page_preview": True},
                    timeout=30,
                )
                if resp.ok:
                    break
            time.sleep(5)
        else:
            raise RuntimeError(f"텔레그램 전송 실패: {resp.status_code} {resp.text[:300]}")
        time.sleep(1.2)
    print(f"[텔레그램] {date_str}: {total}개 메시지 전송 완료")


def send_processed() -> None:
    if not PROCESSED.exists():
        print("[텔레그램] 처리 기록 없음 — 발송 생략")
        return
    dates = json.loads(PROCESSED.read_text(encoding="utf-8"))
    if not dates:
        print("[텔레그램] 이번 실행에서 처리한 브리핑 없음 — 발송 생략")
        return
    for d in dates:
        send_telegram(d)


def main() -> None:
    args = sys.argv[1:]
    if "--ingest" in args:
        ingest()
        return
    if "--send-processed" in args:
        send_processed()
        return
    date_str = args[args.index("--date") + 1] if "--date" in args else None
    if "--send-only" in args:
        if date_str is None:
            mds = sorted(ARCHIVE_DIR.glob("????-??-??.md"))
            date_str = mds[-1].stem if mds else None
        if date_str:
            send_telegram(date_str)
        return
    # 기본: 렌더만 (기존 md 재렌더 또는 --init 빈 인덱스)
    if date_str:
        write_archive(date_str)
    write_index()


if __name__ == "__main__":
    main()
