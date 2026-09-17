#!/usr/bin/env python3
"""방산 브리핑 통합본 발행 도구.

매일 아침 세 판 — 제미나이(defense_daily)·클로드 웹서치판(claude_defense)·
RSS판(chatgpt_defense) — 이 각자 발행된 뒤, Claude 예약 세션(루틴 [6.6])이
세 md를 편집장 관점에서 하나로 합쳐 쓴 통합 브리핑을
static/defense_unified/<날짜>.md 로 저장하면, 이 스크립트가 아카이브 HTML과
날짜 인덱스(defense_unified_report.html)를 만든다.

통합본의 용도: ① 대시보드 '오늘의 요약' 방산 카드(하나로 통일),
② NotebookLM 구글 문서 적재 소스(gas/defense_notebooklm_doc.gs — 통합본만 쌓음),
③ 사이드바 🌐 글로벌방산.브리핑 서브메뉴의 (통합) 페이지.
원본 3판은 그대로 유지된다(각자 페이지·텔레그램 불변). 통합본 자체는
텔레그램 발송이 없다(대시보드·문서 적재 전용).

렌더링은 claude_brief_publish.py 규칙 재사용(표준 라이브러리만).
main 반영은 claude-brief-ingest 가 다른 판들과 같은 경로로 나른다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import claude_brief_publish as cbp  # 같은 디렉터리 — 렌더러·유틸 재사용

ROOT = Path(__file__).resolve().parent
DASH_STATIC = ROOT.parent / "telegram_research_dashboard" / "static"
ARCHIVE_DIR = DASH_STATIC / "defense_unified"
INDEX_PAGE = DASH_STATIC / "defense_unified_report.html"


def write_archive(date_str: str) -> None:
    md_report = (ARCHIVE_DIR / f"{date_str}.md").read_text(encoding="utf-8")
    body = cbp.report_to_page_html(md_report)
    page = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><base target="_blank">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>방산 브리핑 통합본 {date_str}</title><style>{cbp.PAGE_CSS}</style></head>
<body><div class="wrap">
<h1>🛡️ 글로벌 방산 브리핑 (통합)</h1>
<div class="meta">기준: {cbp.date_label(date_str)} · 제미나이·클로드(웹서치)·GPT(RSS) 3판을 하나로 합친 통합본 — 같은 사건은 한 번만, 수치 상충은 [상충] 병기</div>
{body}
</div></body></html>"""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    (ARCHIVE_DIR / f"{date_str}.html").write_text(page, encoding="utf-8")
    print(f"[아카이브] defense_unified/{date_str}.html 생성")


def write_index() -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dates = sorted((p.stem for p in ARCHIVE_DIR.glob("????-??-??.html")), reverse=True)
    dates_js = json.dumps(dates, ensure_ascii=False)
    index = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>방산 브리핑 통합본</title><style>
{cbp.PAGE_CSS}
.bar{{display:flex;gap:10px;align-items:center;max-width:860px;margin:0 auto 14px;flex-wrap:wrap}}
.bar h1{{font-size:17px;margin:0;flex:1;min-width:200px}}
select,button{{background:#161d29;color:#d8dee9;border:1px solid #2c3a52;border-radius:8px;
  padding:7px 12px;font-size:13.5px;cursor:pointer}}
iframe{{width:100%;height:calc(100vh - 110px);border:1px solid #223046;border-radius:10px;background:#0d1117}}
</style></head><body>
<div class="bar">
  <h1>🛡️ 글로벌 방산 브리핑 (통합)</h1>
  <button id="prev" title="이전 날짜">◀</button>
  <select id="dsel"></select>
  <button id="next" title="다음 날짜">▶</button>
</div>
<iframe id="frame" title="브리핑"></iframe>
<script>
const DATES={dates_js};
const sel=document.getElementById('dsel'),fr=document.getElementById('frame');
DATES.forEach(d=>{{const o=document.createElement('option');o.value=d;o.textContent=d+' ('+'일월화수목금토'[new Date(d+'T00:00:00').getDay()]+')';sel.appendChild(o)}});
function load(){{fr.src='defense_unified/'+sel.value+'.html'}}
sel.onchange=load;
document.getElementById('prev').onclick=()=>{{if(sel.selectedIndex<DATES.length-1){{sel.selectedIndex++;load()}}}};
document.getElementById('next').onclick=()=>{{if(sel.selectedIndex>0){{sel.selectedIndex--;load()}}}};
if(DATES.length)load();
else fr.srcdoc='<body style="background:#0d1117;color:#8b96a8;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">아직 통합본이 없습니다 — 매일 아침 3판 발행 후 자동 생성됩니다.</body>';
</script></body></html>"""
    INDEX_PAGE.write_text(index, encoding="utf-8")
    print(f"[인덱스] defense_unified_report.html 갱신 (누적 {len(dates)}일)")


def main() -> None:
    args = sys.argv[1:]
    date_str = args[args.index("--date") + 1] if "--date" in args else None
    if date_str is None:
        mds = sorted(ARCHIVE_DIR.glob("????-??-??.md"))
        date_str = mds[-1].stem if mds else None
    if date_str:
        write_archive(date_str)
    write_index()


if __name__ == "__main__":
    main()
