#!/usr/bin/env python3
"""Claude 글로벌 방산 브리핑 발행 도구 (Gemini 브리핑의 2탄).

Claude 예약 작업(Routine) 세션이 매일 아침 웹 리서치로 작성한 마크다운
리포트(telegram_research_dashboard/static/claude_defense/YYYY-MM-DD.md)를
받아 두 가지 출력을 만든다:

  1. 렌더링(기본): 날짜별 아카이브 HTML 페이지 + 날짜 선택 인덱스
     (claude_defense_report.html) 생성 → 대시보드가 그대로 배포한다.
  2. 텔레그램(--send / --send-only): 핵심 요약을 전용 봇으로 발송.
     GitHub Actions(claude-brief-notify.yml)가 md 커밋을 감지해 실행하며,
     CLAUDE_TELEGRAM_BOT_TOKEN / CLAUDE_TELEGRAM_CHAT_ID 시크릿이 없으면
     조용히 건너뛴다(파이프라인은 실패하지 않는다).

렌더링 로직은 defense_briefing_bot.py와 같은 규칙(표·색상·링크)이지만,
그쪽은 genai·yfinance 의존이 있어 임포트하지 않고 여기 자체 수록한다
(예약 세션·알림 워크플로 모두 표준 라이브러리만으로 렌더링 가능해야 함).
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).resolve().parent
DASH_STATIC = ROOT.parent / "telegram_research_dashboard" / "static"
ARCHIVE_DIR = DASH_STATIC / "claude_defense"
INDEX_PAGE = DASH_STATIC / "claude_defense_report.html"
WEEKDAY_KO = "월화수목금토일"


def date_label(date_str: str) -> str:
    """2026-08-11 → 2026-08-11(화). 파싱 실패 시 원문 그대로."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{date_str}({WEEKDAY_KO[d.weekday()]})"
    except ValueError:
        return date_str


# ── 마크다운 → 텔레그램 HTML / 웹페이지 HTML (defense_briefing_bot과 동일 규칙) ──

MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
MD_BOLD = re.compile(r"\*\*([^*]+)\*\*")
PCT_RE = re.compile(r"(?<![\w.%])([+-]\d+(?:\.\d+)?%)")


def md_inline(line: str) -> str:
    out = html.escape(line, quote=False)
    out = MD_LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', out)
    out = MD_BOLD.sub(r"<b>\1</b>", out)
    return out


def colorize(html_text: str) -> str:
    return PCT_RE.sub(
        lambda m: f'<span class="{"up" if m.group(1).startswith("+") else "down"}">{m.group(1)}</span>',
        html_text)


def to_telegram_html(md: str) -> str:
    lines = []
    for raw in md.splitlines():
        s = raw.strip()
        if not s:
            lines.append("")
        elif re.match(r"^#{1,6}\s", s):
            lines.append("<b>" + md_inline(re.sub(r"^#{1,6}\s+", "", s)) + "</b>")
        elif s.startswith(("- ", "* ")):
            lines.append("• " + md_inline(s[2:]))
        elif s in ("---", "***"):
            lines.append("─────────")
        else:
            lines.append(md_inline(s))
    return "\n".join(lines).strip()


def split_chunks(text: str, limit: int = 3900) -> list[str]:
    chunks, cur = [], ""
    for line in text.split("\n"):
        candidate = (cur + "\n" + line) if cur else line
        if len(candidate) > limit:
            if cur:
                chunks.append(cur)
            cur = line[:limit]
        else:
            cur = candidate
    if cur.strip():
        chunks.append(cur)
    return chunks


def extract_summary(md: str) -> str:
    """서두 + 첫 섹션(오늘의 핵심 요약)만. 두 번째 헤딩부터 제외."""
    out, headings = [], 0
    for line in md.splitlines():
        if re.match(r"^#{1,6}\s", line.strip()):
            headings += 1
            if headings >= 2:
                break
        out.append(line)
    return "\n".join(out).strip()


PAGE_CSS = """
:root{color-scheme:dark}
body{margin:0;padding:28px 24px 60px;background:#0d1117;color:#d8dee9;
  font-family:'Pretendard','Malgun Gothic','Apple SD Gothic Neo',sans-serif;line-height:1.75;font-size:15px}
.wrap{max-width:860px;margin:0 auto}
h1{font-size:21px;color:#e8edf5;margin:0 0 4px}
.meta{color:#8b96a8;font-size:12.5px;margin-bottom:22px}
h2{font-size:16.5px;color:#c9a86a;margin:30px 0 10px;padding-bottom:6px;border-bottom:1px solid #223046}
a{color:#6aa8ff;text-decoration:none}a:hover{text-decoration:underline}
b,strong{color:#f0f4fa}
ul{margin:6px 0;padding-left:22px}
p{margin:8px 0}
hr{border:none;border-top:1px solid #223046;margin:20px 0}
table.ptab{border-collapse:collapse;width:100%;margin:12px 0;font-size:13.5px}
.ptab td{border-bottom:1px solid #1d2838;padding:7px 9px;text-align:left;vertical-align:top}
.ptab tr:first-child td{color:#8b96a8;font-size:12.5px;border-bottom:1px solid #2c3a52}
.ptab tr:hover td{background:#131a26}
.up{color:#ff6b6b;font-weight:600}
.down{color:#5b9dff;font-weight:600}
/* 모바일: 6열 표가 세로로 짓눌리므로 행을 카드로 재배치 (헤더행 기반 라벨) */
@media (max-width:640px){
  body{padding:20px 14px 48px}
  .ptab.hdr, .ptab.hdr tbody, .ptab.hdr tr, .ptab.hdr td{display:block;width:100%;box-sizing:border-box}
  .ptab.hdr tr:first-child{display:none}
  .ptab.hdr tr{border:1px solid #223046;border-radius:10px;margin:10px 0;padding:9px 12px;background:#111825}
  .ptab.hdr tr:hover td{background:transparent}
  .ptab.hdr td{border:none;padding:2px 0;display:flex;gap:10px;align-items:baseline;font-size:13.5px}
  .ptab.hdr td::before{content:attr(data-l);color:#8b96a8;font-size:11.5px;flex:0 0 58px}
  .ptab.hdr td:first-child{display:block;font-weight:700;color:#f0f4fa;font-size:14.5px;
    padding-bottom:5px;margin-bottom:4px;border-bottom:1px solid #1d2838}
  .ptab.hdr td:first-child::before{content:none}
}
"""


def report_to_page_html(md: str) -> str:
    out, in_list, table_rows = [], False, []

    def flush_table():
        if table_rows:
            # 첫 행을 헤더로 간주해 각 셀에 data-l 라벨을 달면, 모바일 CSS가
            # 행을 카드로 재배치할 때 "국가: 한국" 식으로 라벨을 붙일 수 있다.
            has_hdr = len(table_rows) >= 2
            labels = [re.sub(r"<[^>]+>", "", h).strip() for h in table_rows[0]] if has_hdr else []
            out.append(f'<div style="overflow-x:auto"><table class="ptab{" hdr" if has_hdr else ""}">')
            for i, cells in enumerate(table_rows):
                tds = []
                for j, c in enumerate(cells):
                    label = labels[j] if has_hdr and i > 0 and j < len(labels) else ""
                    attr = f' data-l="{html.escape(label, quote=True)}"' if label else ""
                    tds.append(f"<td{attr}>{c}</td>")
                out.append("<tr>" + "".join(tds) + "</tr>")
            out.append("</table></div>")
            table_rows.clear()

    for raw in md.splitlines():
        s = raw.strip()
        m = re.match(r"^(#{1,6})\s+(.*)", s)
        # 마크다운 표 문법(| a | b |)과 'a | b | c' 일반 텍스트 표를 모두 수용
        stripped = s.strip("|").strip()
        is_sep = bool(re.fullmatch(r"\|?[\s:|-]+\|?", s)) and "-" in s
        is_table_row = not m and not is_sep and (s.count(" | ") >= 3 or (s.startswith("|") and s.count("|") >= 4))
        if in_list and not s.startswith(("- ", "* ")):
            out.append("</ul>")
            in_list = False
        if not is_table_row:
            flush_table()
        if not s or is_sep:
            continue
        if m:
            out.append(f"<h2>{colorize(md_inline(m.group(2)))}</h2>")
        elif is_table_row:
            cells = [c.strip() for c in stripped.split("|")] if s.startswith("|") else s.split(" | ")
            table_rows.append([colorize(md_inline(c.strip())) for c in cells])
        elif s.startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{colorize(md_inline(s[2:]))}</li>")
        elif s in ("---", "***"):
            out.append("<hr>")
        else:
            out.append(f"<p>{colorize(md_inline(s))}</p>")
    flush_table()
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


# ── 아카이브 페이지 + 인덱스 ──────────────────────────────────────────────

def write_archive(date_str: str) -> None:
    md_path = ARCHIVE_DIR / f"{date_str}.md"
    md_report = md_path.read_text(encoding="utf-8")
    body = report_to_page_html(md_report)
    page = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Claude 방산 브리핑 {date_str}</title><style>{PAGE_CSS}</style></head>
<body><div class="wrap">
<h1>🤖 Claude 글로벌 방산 브리핑</h1>
<div class="meta">기준: {date_label(date_str)} · 생성: Claude(웹 검색 리서치) — Gemini 브리핑과 별도 관점의 2탄</div>
{body}
</div></body></html>"""
    (ARCHIVE_DIR / f"{date_str}.html").write_text(page, encoding="utf-8")
    print(f"[아카이브] claude_defense/{date_str}.html 생성")
    write_index()


def write_index() -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dates = sorted((p.stem for p in ARCHIVE_DIR.glob("????-??-??.html")), reverse=True)
    dates_js = json.dumps(dates, ensure_ascii=False)
    index = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Claude 방산 브리핑</title><style>
{PAGE_CSS}
.bar{{display:flex;gap:10px;align-items:center;max-width:860px;margin:0 auto 14px;flex-wrap:wrap}}
.bar h1{{font-size:17px;margin:0;flex:1;min-width:200px}}
select,button{{background:#161d29;color:#d8dee9;border:1px solid #2c3a52;border-radius:8px;
  padding:7px 12px;font-size:13.5px;cursor:pointer}}
iframe{{width:100%;height:calc(100vh - 110px);border:1px solid #223046;border-radius:10px;background:#0d1117}}
</style></head><body>
<div class="bar">
  <h1>🤖 Claude 글로벌 방산 브리핑</h1>
  <button id="prev" title="이전 날짜">◀</button>
  <select id="dsel"></select>
  <button id="next" title="다음 날짜">▶</button>
</div>
<iframe id="frame" title="브리핑"></iframe>
<script>
const DATES={dates_js};
const sel=document.getElementById('dsel'),fr=document.getElementById('frame');
DATES.forEach(d=>{{const o=document.createElement('option');o.value=d;o.textContent=d+' ('+'일월화수목금토'[new Date(d+'T00:00:00').getDay()]+')';sel.appendChild(o)}});
function load(){{fr.src='claude_defense/'+sel.value+'.html'}}
sel.onchange=load;
document.getElementById('prev').onclick=()=>{{if(sel.selectedIndex<DATES.length-1){{sel.selectedIndex++;load()}}}};
document.getElementById('next').onclick=()=>{{if(sel.selectedIndex>0){{sel.selectedIndex--;load()}}}};
if(DATES.length)load();
else fr.srcdoc='<body style="background:#0d1117;color:#8b96a8;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">아직 생성된 브리핑이 없습니다 — 매일 아침 6시경 자동 생성됩니다.</body>';
</script></body></html>"""
    INDEX_PAGE.write_text(index, encoding="utf-8")
    print(f"[인덱스] claude_defense_report.html 갱신 (누적 {len(dates)}일)")


# ── 텔레그램 발송 (전용 봇) ────────────────────────────────────────────────

def send_telegram(date_str: str) -> None:
    token = os.environ.get("CLAUDE_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("CLAUDE_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("[텔레그램] CLAUDE_TELEGRAM_BOT_TOKEN/CHAT_ID 미설정 — 발송 생략")
        return
    import requests  # 발송 경로에서만 필요 (렌더링은 표준 라이브러리만)

    md_report = (ARCHIVE_DIR / f"{date_str}.md").read_text(encoding="utf-8")
    base_url = os.environ.get("DASHBOARD_BASE_URL",
                              "https://gschoie.github.io/GS-DB2")
    mode = os.environ.get("TELEGRAM_MODE", "summary")  # summary | full
    md_body = md_report if mode == "full" else extract_summary(md_report)
    body = to_telegram_html(md_body)
    header = f"🤖 <b>Claude 글로벌 방산 브리핑</b> | {date_label(date_str)}\n"
    footer = ""
    if mode != "full":
        footer = (f'\n\n📊 <a href="{base_url}/claude_defense/{date_str}.html">'
                  "전체 브리핑 보기 (주가표·섹터별·투자 시사점)</a>\n"
                  "<i>발송 직후엔 반영 중일 수 있어요 — 2~3분 뒤 열어주세요</i>")
    chunks = split_chunks(header + body + footer)
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
    print(f"[텔레그램] {total}개 메시지 전송 완료")


def latest_date() -> str | None:
    mds = sorted(ARCHIVE_DIR.glob("????-??-??.md"))
    return mds[-1].stem if mds else None


def main() -> None:
    args = sys.argv[1:]
    date_str = None
    if "--date" in args:
        date_str = args[args.index("--date") + 1]
    if date_str is None:
        date_str = latest_date()
    if date_str is None:
        print("claude_defense/*.md 가 없습니다 — 처리할 리포트 없음")
        if "--init" in args:  # 첫 배포용 빈 인덱스만 생성
            write_index()
        return
    if "--send-only" in args:
        send_telegram(date_str)
        return
    write_archive(date_str)
    if "--send" in args:
        send_telegram(date_str)


if __name__ == "__main__":
    main()
