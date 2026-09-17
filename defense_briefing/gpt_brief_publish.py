#!/usr/bin/env python3
"""방산 브리핑 RSS판(3탄) 발행 도구 — Claude 세션 작성분·ChatGPT 앱 등록분 공용.

사용자가 ChatGPT(스케줄 태스크)로 받아 본 브리핑 마크다운을 리포로 넘기면,
Gemini(defense_daily)·Claude(claude_defense)와 같은 방식으로 날짜별 아카이브
(static/chatgpt_defense/<날짜>.md|.html) + 날짜 인덱스(chatgpt_defense_report.html)를
만들고, 방산 채널 텔레그램으로 요약+링크를 발송한다.

입력 경로 두 가지 — chatgpt-brief.yml 워크플로가 둘 다 처리한다:
  1. 대시보드 붙여넣기 폼(인덱스 페이지 상단) → GAS dispatch_proxy(gptbrief)
     → workflow_dispatch inputs.content  (여기엔 환경변수 CONTENT로 들어온다)
  2. chatgpt_briefing/inbox/YYYY-MM-DD.md 파일을 main에 커밋 (push 트리거)
     — GitHub 웹/모바일에서 파일로 올리는 보조 경로. 처리 후 inbox에서 지운다.
     (workflow_dispatch의 문자열 입력칸은 한 줄짜리라 여러 줄 md가 뭉개진다 —
      수동 경로는 반드시 파일로.)

렌더링 규칙(표·색·링크·모바일 카드)은 claude_brief_publish.py 의 것을 그대로
임포트해 재사용한다(표준 라이브러리만 필요). 텔레그램은 방산 데일리와 같은
채널(KDEF_TELEGRAM_*)을 기본으로 쓰되, GPT_TELEGRAM_* 시크릿이 있으면 그쪽 우선
(매핑은 워크플로에서 TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID로 넘어온다).
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

import claude_brief_publish as cbp  # 같은 디렉터리 — 렌더러·유틸 재사용

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).resolve().parent           # defense_briefing/
REPO = ROOT.parent
DASH_STATIC = REPO / "telegram_research_dashboard" / "static"
ARCHIVE_DIR = DASH_STATIC / "chatgpt_defense"
INDEX_PAGE = DASH_STATIC / "chatgpt_defense_report.html"
INBOX_DIR = REPO / "chatgpt_briefing" / "inbox"
# --ingest가 처리한 날짜 목록. 커밋 대상이 아니며(루트에 두고 add 안 함),
# 뒤이은 --send-processed 스텝이 읽어 그 날짜들만 발송한다.
PROCESSED = REPO / ".gpt_brief_processed.json"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# app.js DISPATCH_ENDPOINT · vacation_tracker/render_page.py 와 같은 주소 —
# GAS 웹앱을 새로 배포(주소 변경)하면 세 곳을 같이 고칠 것.
DISPATCH_ENDPOINT = "https://script.google.com/macros/s/AKfycbx3RjIjtlO2Z6fIYo2T3LhJrFg9Wp2hS7dMS3Is52-JVF1hizoCWewbQ1uM_v5sdhR2jw/exec"


def today_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


# ── 아카이브 페이지 + 인덱스 ──────────────────────────────────────────────

def write_archive(date_str: str) -> None:
    md_report = (ARCHIVE_DIR / f"{date_str}.md").read_text(encoding="utf-8")
    body = cbp.report_to_page_html(md_report)
    page = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><base target="_blank">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>방산 브리핑 RSS판 {date_str}</title><style>{cbp.PAGE_CSS}</style></head>
<body><div class="wrap">
<h1>🧠 글로벌 방산 브리핑 (RSS판)</h1>
<div class="meta">기준: {cbp.date_label(date_str)} · 생성: Claude 예약 세션 — 구글뉴스 RSS(24h)+yfinance 확정 시세만 근거(제미나이판과 같은 지침)로 쓴 3탄 · 수동 등록분은 ChatGPT 앱 산출물</div>
{body}
</div></body></html>"""
    (ARCHIVE_DIR / f"{date_str}.html").write_text(page, encoding="utf-8")
    print(f"[아카이브] chatgpt_defense/{date_str}.html 생성")


def write_index() -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dates = sorted((p.stem for p in ARCHIVE_DIR.glob("????-??-??.html")), reverse=True)
    dates_js = json.dumps(dates, ensure_ascii=False)
    index = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>방산 브리핑 RSS판</title><style>
{cbp.PAGE_CSS}
.bar{{display:flex;gap:10px;align-items:center;max-width:860px;margin:0 auto 10px;flex-wrap:wrap}}
.bar h1{{font-size:17px;margin:0;flex:1;min-width:200px}}
select,button{{background:#161d29;color:#d8dee9;border:1px solid #2c3a52;border-radius:8px;
  padding:7px 12px;font-size:13.5px;cursor:pointer}}
iframe{{width:100%;height:calc(100vh - 150px);border:1px solid #223046;border-radius:10px;background:#0d1117}}
details.paste{{max-width:860px;margin:0 auto 12px;border:1px solid #223046;border-radius:10px;background:#111825}}
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
  <h1>🧠 글로벌 방산 브리핑 (RSS판)</h1>
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
    <textarea id="p-md" placeholder="ChatGPT가 만든 브리핑 마크다운 전문을 그대로 붙여넣으세요"></textarea>
    <p id="paste-status"></p>
    <p class="hint">같은 날짜로 다시 등록하면 그 날짜 페이지가 새 내용으로 교체됩니다(텔레그램도 다시 발송).
    붙여넣기가 안 되는 환경에서는 리포의 <code>chatgpt_briefing/inbox/YYYY-MM-DD.md</code> 파일로 올려도 됩니다.</p>
  </div>
</details>
<iframe id="frame" title="브리핑"></iframe>
<script>
const DATES={dates_js};
const EP={json.dumps(DISPATCH_ENDPOINT)};
const sel=document.getElementById('dsel'),fr=document.getElementById('frame');
DATES.forEach(d=>{{const o=document.createElement('option');o.value=d;o.textContent=d+' ('+'일월화수목금토'[new Date(d+'T00:00:00').getDay()]+')';sel.appendChild(o)}});
function load(){{fr.src='chatgpt_defense/'+sel.value+'.html'}}
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
    const r=await fetch(EP,{{method:'POST',body:JSON.stringify({{workflow:'gptbrief',date:date,content:md}})}});
    try{{const d=await r.json();
      if(d&&d.ok===false){{st.textContent='⚠ 거절 '+(d.code||'?')+' — '+(d.error||'GAS 프록시 확인 필요');btn.disabled=false;return}}
    }}catch(e){{}}
    document.getElementById('p-md').value='';
    const isNew=!DATES.includes(date);
    st.textContent='✅ 접수됨 — 페이지 생성·배포에 2~4분, 텔레그램은 곧 도착합니다.'+(isNew?' 새 날짜가 뜨면 자동 새로고침합니다.':' (같은 날짜 재등록 — 잠시 후 직접 새로고침하세요)');
    if(isNew){{
      let n=0;const t=setInterval(async()=>{{
        n++;if(n>20){{clearInterval(t);return}}
        try{{const h=await fetch('chatgpt_defense/'+date+'.html',{{method:'HEAD',cache:'no-store'}});
          if(h.ok){{clearInterval(t);location.reload()}}}}catch(e){{}}
      }},20000);
    }}
  }}catch(e){{st.textContent='실패: '+e.message;btn.disabled=false}}
}}
</script></body></html>"""
    INDEX_PAGE.write_text(index, encoding="utf-8")
    print(f"[인덱스] chatgpt_defense_report.html 갱신 (누적 {len(dates)}일)")


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
        print(f"[입력] 폼 content → chatgpt_defense/{date_str}.md ({len(content)}자)")
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
            print(f"[입력] inbox/{f.name} → chatgpt_defense/{date_str}.md ({len(body)}자)")
    if not dates:
        print("[입력] 처리할 브리핑 없음 (CONTENT 비어 있고 inbox도 빈 상태)")
    for d in dict.fromkeys(dates):
        write_archive(d)
    write_index()
    PROCESSED.write_text(json.dumps(sorted(set(dates))), encoding="utf-8")
    return dates


# ── 텔레그램 (방산 채널 — 시크릿 매핑은 워크플로에서) ─────────────────────

def send_telegram(date_str: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("[텔레그램] TELEGRAM_BOT_TOKEN/CHAT_ID 미설정 — 발송 생략")
        return
    import requests

    md_report = (ARCHIVE_DIR / f"{date_str}.md").read_text(encoding="utf-8")
    base_url = os.environ.get("DASHBOARD_BASE_URL", "https://gschoie.github.io/GS-DB2")
    mode = os.environ.get("TELEGRAM_MODE", "summary")  # summary | full
    md_body = md_report if mode == "full" else cbp.extract_summary(md_report)
    body = cbp.to_telegram_html(md_body)
    header = f"🧠 <b>글로벌 방산 브리핑 (RSS판)</b> | {cbp.date_label(date_str)}\n"
    footer = ""
    if mode != "full":
        footer = (f'\n\n📊 <a href="{base_url}/chatgpt_defense/{date_str}.html">'
                  "전체 브리핑 보기</a>\n"
                  "<i>발송 직후엔 반영 중일 수 있어요 — 2~3분 뒤 열어주세요</i>")
    chunks = cbp.split_chunks(header + body + footer)
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
