#!/usr/bin/env python3
"""친환경 에너지·FDC 데일리 브리핑 봇 (건설기계 초기 버전과 동일한 Gemini 단일 파이프라인).

매일 아침(KST 06:40 목표) 실행되어:
  1. 구글뉴스 RSS로 지난 24시간 기사를 수집하고 (주제: 친환경 선박 추진 —
     암모니아·액화수소·원자력(SMR), FDC(Floating Data Center), FLNG,
     LNG 액화 프로젝트 FID, 미국 발전원 투자 — 가스복합·신재생·SMR)
  2. Gemini API가 이 목록만 근거로 데일리 브리핑을 작성한 뒤
  3. 대시보드 static/energy_daily/YYYY-MM-DD.html 로 날짜별 아카이브를 남긴다.

시세표 없음(뉴스 전용), 텔레그램 없음(대시보드 전용) — 요청 사양.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).resolve().parent
DASH_STATIC = ROOT.parent / "telegram_research_dashboard" / "static"
ARCHIVE_DIR = DASH_STATIC / "energy_daily"
INDEX_PAGE = DASH_STATIC / "energy_briefing_report.html"

MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
LAST_USED_MODEL = MODEL

# ── 구글뉴스 RSS 수집 (지난 24시간) ──────────────────────────────────────
# 주제 축: ① 친환경 선박 추진(암모니아·액화수소·원자력/SMR) ② FDC
# ③ FLNG·FSRU ④ LNG 액화 FID ⑤ 미국 발전원 투자(가스복합·신재생·SMR).
# 'SMR'·'ammonia' 같은 다의어는 선박·발전 문맥을 함께 요구한다.

NEWS_QUERIES = [
    # (query, hl, gl, ceid)
    # 암모니아 추진선 — 벙커링·이중연료 포함
    ('("ammonia-fueled" OR "ammonia-powered" OR "ammonia dual-fuel" OR "ammonia bunkering" '
     'OR ("ammonia" AND (vessel OR ship OR carrier OR engine OR propulsion))) when:1d',
     "en-US", "US", "US:en"),
    # 수소 추진선·액화수소 운반선
    ('(("hydrogen-powered" OR "liquid hydrogen" OR "hydrogen fuel cell" OR "hydrogen dual-fuel") '
     'AND (ship OR vessel OR carrier OR maritime OR ferry OR shipbuilding)) when:1d',
     "en-US", "US", "US:en"),
    # 원자력 추진선·해상 원자력 (SMR 선박 적용 포함)
    ('("nuclear-powered ship" OR "nuclear-powered vessel" OR "nuclear propulsion" '
     'OR "floating nuclear" OR (("SMR" OR "small modular reactor") AND (ship OR maritime '
     'OR vessel OR shipping))) when:1d', "en-US", "US", "US:en"),
    # FDC — Floating/offshore Data Center
    ('("floating data center" OR "offshore data center" OR "data center ship" '
     'OR ("data center" AND (barge OR floating OR offshore))) when:1d',
     "en-US", "US", "US:en"),
    # FLNG·FSRU
    ('("FLNG" OR "floating LNG" OR "FSRU" OR "floating storage regasification") when:1d',
     "en-US", "US", "US:en"),
    # LNG 액화 프로젝트 FID
    ('("LNG" AND ("final investment decision" OR "FID" OR "liquefaction plant" '
     'OR "liquefaction project" OR "LNG export project" OR "LNG terminal")) when:1d',
     "en-US", "US", "US:en"),
    # 미국 발전원 — 가스복합화력 (데이터센터 전력 수요 문맥 포함)
    ('(("combined cycle" OR "combined-cycle" OR "gas-fired power" OR "natural gas plant" '
     'OR "gas turbine order") AND ("United States" OR US OR utility OR "data center" '
     'OR gigawatt)) when:1d', "en-US", "US", "US:en"),
    # 미국 발전원 — 신재생 (투자·프로젝트 문맥 한정)
    ('(("solar farm" OR "wind farm" OR "offshore wind" OR "battery storage") '
     'AND ("United States" OR US) AND (investment OR construction OR approved OR gigawatt '
     'OR "power purchase")) when:1d', "en-US", "US", "US:en"),
    # SMR — 육상 원전 (개발사 고유명 포함)
    ('("small modular reactor" OR NuScale OR "X-energy" OR TerraPower OR Oklo '
     'OR "Kairos Power" OR ("SMR" AND (nuclear OR reactor OR utility OR "data center"))) when:1d',
     "en-US", "US", "US:en"),
    # 국내 보도 — 조선 3사 친환경·FLNG·SMR 문맥
    ("암모니아 추진선 OR 수소 추진선 OR 원자력 추진선 OR FLNG OR 해상 데이터센터 "
     "OR 부유식 데이터센터 OR 소형모듈원전 OR LNG 액화 when:1d", "ko", "KR", "KR:ko"),
]

# 오검색 컷: 비료·농업용 암모니아, 가정용 수소차 등 (선박·발전 신호 없으면 버림)
NOISE_TITLE_PATTERN = re.compile(
    r"(?i)\b(fertilizer price|crop|farm(ing)? subsid|hydrogen car|fuel-cell (car|suv)"
    r"|passenger car|cosmetic|skincare)\b"
)


def fetch_news(now: datetime, max_items: int = 70) -> list[dict]:
    """구글뉴스 RSS에서 지난 ~30시간 기사만 수집해 최신순으로 반환."""
    import requests
    cutoff = now - timedelta(hours=30)
    items, seen = [], set()
    for query, hl, gl, ceid in NEWS_QUERIES:
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(query)
               + f"&hl={hl}&gl={gl}&ceid={ceid}")
        try:
            resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except Exception as e:
            print(f"[RSS 실패] {query[:40]}...: {e}", file=sys.stderr)
            continue
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            source = (item.findtext("source") or "").strip()
            pub_raw = item.findtext("pubDate") or ""
            try:
                pub = parsedate_to_datetime(pub_raw).astimezone(KST)
            except Exception:
                continue
            key = re.sub(r"\W+", "", title.lower())[:80]
            if not title or pub < cutoff or key in seen:
                continue
            if NOISE_TITLE_PATTERN.search(title):
                continue
            seen.add(key)
            items.append({"title": title, "link": link, "source": source, "pub": pub})
        time.sleep(0.5)
    items.sort(key=lambda x: x["pub"], reverse=True)
    return items[:max_items]


def news_list_text(items: list[dict]) -> str:
    return "\n".join(
        f"- [{it['pub']:%m/%d %H:%M} KST] {it['title']} ({it['source']}) {it['link']}"
        for it in items
    )


SYSTEM_PROMPT = """당신은 조선·에너지 인프라 섹터를 담당하는 증권사 리서치 어시스턴트(RA)입니다.
매일 아침 한국의 조선 담당 애널리스트에게 보내는 '친환경 에너지·FDC 데일리 브리핑'을 작성합니다.
추적 주제는 다섯 가지입니다: ① 친환경 선박 추진 기술(암모니아 추진·액화수소 추진·원자력/SMR 추진)
② FDC(Floating Data Center, 해상 데이터센터) ③ FLNG(Floating LNG)·FSRU
④ LNG 액화 프로젝트의 FID(최종투자결정) 동향 ⑤ 미국의 발전원 투자(가스복합화력·신재생·SMR).

[필수 원칙 — 최신성이 가장 중요합니다]
- **뉴스 사실관계는 반드시 함께 제공되는 [지난 24시간 뉴스 목록]에 있는 기사만 근거로 쓰세요.** 목록에 없는 사건을 당신의 기억(학습 데이터)에서 꺼내 새 뉴스처럼 쓰는 것을 절대 금지합니다. 과거의 수주·FID·계약 소식을 오늘 뉴스처럼 서술하면 안 됩니다.
- 각 이슈에는 뉴스 목록에 표기된 보도 시각(월/일)을 함께 적으세요.
- 다섯 주제와 무관한 기사(비료용 암모니아, 수소차, 일반 IT 데이터센터 등)는 버리세요.
- **최종 리포트 본문만 출력하세요.** 계획·사고 과정·코드 블록 금지. 응답의 첫 글자는 반드시 서두 문장("친환경 에너지·FDC 분야에서...")으로 시작해야 합니다.
- 수치·계약금액·선박 수·용량(GW·mtpa)·일정을 우선 제시하고, 사실과 해석을 구분하세요. 확인되지 않은 보도·루머는 "[미확인]" 표시.
- **뉴스의 함의를 끝까지 해석하세요.** FID 승인 → 신조 발주(LNG운반선·FLNG) 경로, 미국 전력난·데이터센터 수요 → 가스터빈/SMR/해상 발전 경로, 친환경 연료 규제(IMO) → 이중연료 신조 교체 수요 경로를 짚고, 한국 조선 3사(HD한국조선해양·한화오션·삼성중공업)와 기자재 업체에 수혜·경쟁 관점을 연결하세요.
- 뉴스 항목마다 출처 매체명과 원문 링크(목록의 URL 그대로)를 마크다운 링크로 붙이세요.
- 한국어로 간결하게 작성하되, 기업명·프로젝트명은 공식 영문명을 병기하세요.
- 동일 뉴스 반복 금지.

[출력 형식 — 반드시 이 구조를 따르세요]
0. 서두: "친환경 에너지·FDC 분야에서 지난 24시간 동안 발생한 주요 뉴스를 정리해 드립니다. 업데이트 시간은 {UPDATE_TIME}입니다." 문장으로 시작 (시간 표기 필수)
1. ## 오늘의 핵심 요약 — 가장 중요한 이슈 3~5개를 3~5줄로
2. ## 친환경 선박 추진 — ### 암모니아 / ### 액화수소 / ### 원자력·SMR 추진 하위 구분. 수주·시험·인증(AiP)·벙커링 인프라·엔진 개발 소식. 소식 없는 하위 항목은 "- 특이사항 없음." 한 줄로
3. ## FDC (Floating Data Center) — 프로젝트·투자·기술 동향. 없으면 "- 특이사항 없음."
4. ## FLNG · LNG 액화 FID — FLNG/FSRU 발주·건조·배치 소식과 액화 프로젝트 FID 동향. FID 관련 건은 "프로젝트 | 국가 | 운영사 | 규모(mtpa) | 단계 | 날짜" 형태의 일반 텍스트 줄로 (마크다운 표 문법 |---| 금지)
5. ## 미국 발전원 투자 — ### 가스복합화력 / ### 신재생 / ### SMR 하위 구분. 투자·발주·승인·전력구매계약 소식. 없는 항목은 "- 특이사항 없음."
6. ## 한국 조선·기자재 시사점 — HD한국조선해양·한화오션·삼성중공업 및 기자재 관점의 수혜·경쟁 포인트 3개 이내

굵은 강조는 **텍스트**, 링크는 [매체명](URL) 형식의 마크다운을 사용하세요. 마크다운 표(|---|)와 HTML 태그는 사용하지 마세요."""

REPORT_OPENER = "친환경 에너지·FDC 분야에서 지난 24시간"


def clean_report(text: str) -> str:
    """모델이 사고 과정·계획을 본문 앞에 누출했을 때 최종 리포트만 남긴다."""
    idx = text.find(REPORT_OPENER)
    if idx > 0:
        print(f"[정리] 리포트 앞 사고 과정 누출 {idx}자 제거")
        return text[idx:].strip()
    if idx == 0:
        return text.strip()
    idx = text.find("## 오늘의 핵심 요약")
    if idx > 0:
        print("[정리] 서두 문장 없음 — 핵심 요약 헤딩부터 절단", file=sys.stderr)
        return text[idx:].strip()
    return text.strip()


def generate_report(news_text: str, now: datetime) -> str:
    from google import genai
    from google.genai import types as genai_types
    client = genai.Client()  # GEMINI_API_KEY 환경변수 사용
    update_time = now.strftime("%Y-%m-%d %H:00")
    system = SYSTEM_PROMPT.replace("{UPDATE_TIME}", update_time)
    user = (
        f"현재 시각(KST): {now.strftime('%Y-%m-%d %H:%M')}\n\n"
        f"[지난 24시간 뉴스 목록] (구글뉴스 RSS 수집 — 뉴스 사실관계는 이 목록만 근거로 사용):\n"
        f"{news_text}\n\n"
        "위 뉴스 목록을 바탕으로 친환경 에너지·FDC 데일리 브리핑을 작성해 주세요. "
        "목록에 없는 사건을 새 뉴스처럼 쓰지 마세요."
    )
    config = genai_types.GenerateContentConfig(
        system_instruction=system,
        temperature=0.3,
        max_output_tokens=16384,
    )
    models = list(dict.fromkeys([MODEL, "gemini-2.5-flash"]))
    response, used_model = None, None
    for model in models:
        for attempt in range(2):  # 429/503 대비 재시도
            try:
                response = client.models.generate_content(model=model, contents=user, config=config)
                if response.text and response.text.strip():
                    used_model = model
                    break
                print(f"[Gemini:{model}] 빈 응답 (시도 {attempt + 1})", file=sys.stderr)
            except Exception as e:
                print(f"[Gemini:{model} 오류] 시도 {attempt + 1}: {e}", file=sys.stderr)
            time.sleep(30 * (attempt + 1))
        if used_model:
            break
    if not used_model:
        raise RuntimeError("Gemini 호출 모두 실패 (폴백 포함)")
    print(f"[Gemini] 사용 모델: {used_model}")
    global LAST_USED_MODEL
    LAST_USED_MODEL = used_model
    report = clean_report(response.text.strip())
    um = getattr(response, "usage_metadata", None)
    if um:
        print(f"[Gemini] in={um.prompt_token_count} out={um.candidates_token_count}")
    return report


# ── 마크다운 → 웹페이지 HTML (방산·건기 브리핑과 동일 골격, 액센트만 청록) ──

MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
MD_BOLD = re.compile(r"\*\*([^*]+)\*\*")


def md_inline(line: str) -> str:
    out = html.escape(line, quote=False)
    out = MD_LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', out)
    out = MD_BOLD.sub(r"<b>\1</b>", out)
    return out


def extract_summary(md: str) -> str:
    """서두 + 첫 섹션(오늘의 핵심 요약)만 잘라낸다. 두 번째 헤딩부터 제외."""
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
h2{font-size:16.5px;color:#5fd4b0;margin:30px 0 10px;padding-bottom:6px;border-bottom:1px solid #24443a}
h3{font-size:14.5px;color:#a9e8d2;margin:18px 0 6px}
a{color:#6aa8ff;text-decoration:none}a:hover{text-decoration:underline}
b,strong{color:#f0f4fa}
ul{margin:6px 0;padding-left:22px}
p{margin:8px 0}
hr{border:none;border-top:1px solid #24443a;margin:20px 0}
table.ptab{border-collapse:collapse;width:100%;min-width:560px;margin:12px 0;font-size:13.5px}
.ptab td{border-bottom:1px solid #1d2838;padding:7px 9px;text-align:left;vertical-align:top}
.ptab td{white-space:nowrap}.ptab td:first-child{white-space:normal;min-width:130px}.ptab td:last-child{white-space:normal;min-width:200px}
.ptab tr:first-child td{color:#8b96a8;font-size:12.5px;border-bottom:1px solid #2c3a52}
.ptab tr:hover td{background:#131a26}
.up{color:#ff6b6b;font-weight:600}
.down{color:#5b9dff;font-weight:600}
"""

PCT_RE = re.compile(r"(?<![\w.%])([+-]\d+(?:\.\d+)?%)")


def colorize(html_text: str) -> str:
    return PCT_RE.sub(
        lambda m: f'<span class="{"up" if m.group(1).startswith("+") else "down"}">{m.group(1)}</span>',
        html_text)


def report_to_page_html(md: str) -> str:
    """'A | B | C | D' 형태(4열 이상) 연속 줄은 표로, 나머지는 문단·리스트로 렌더."""
    out, in_list, table_rows = [], False, []

    def flush_table():
        if table_rows:
            out.append('<div style="overflow-x:auto"><table class="ptab">')
            for cells in table_rows:
                out.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
            out.append("</table></div>")
            table_rows.clear()

    for raw in md.splitlines():
        s = raw.strip()
        m = re.match(r"^(#{1,6})\s+(.*)", s)
        is_table_row = s.count(" | ") >= 3 and not m
        if in_list and not s.startswith(("- ", "* ")):
            out.append("</ul>")
            in_list = False
        if not is_table_row:
            flush_table()
        if not s:
            continue
        if m:
            tag = "h3" if len(m.group(1)) >= 3 else "h2"
            out.append(f"<{tag}>{colorize(md_inline(m.group(2)))}</{tag}>")
        elif is_table_row:
            table_rows.append([colorize(md_inline(c.strip())) for c in s.split(" | ")])
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


def write_archive(md_report: str, now: datetime) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    date_str = now.strftime("%Y-%m-%d")
    body = report_to_page_html(md_report)
    page = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>친환경 에너지·FDC 브리핑 {date_str}</title><style>{PAGE_CSS}</style></head>
<body><div class="wrap">
<h1>🌊 친환경 에너지·FDC 데일리 브리핑</h1>
<div class="meta">기준: {now.strftime('%Y-%m-%d %H:00')} KST · 생성: Gemini({LAST_USED_MODEL}) + 구글뉴스 RSS · 주제: 친환경 선박(암모니아·수소·원자력)/FDC/FLNG·LNG FID/미국 발전원</div>
{body}
</div></body></html>"""
    (ARCHIVE_DIR / f"{date_str}.html").write_text(page, encoding="utf-8")
    (ARCHIVE_DIR / f"{date_str}.md").write_text(md_report, encoding="utf-8")
    print(f"[아카이브] energy_daily/{date_str}.html 생성")
    write_index()


def write_index() -> None:
    """날짜별 아카이브 목록을 읽어 선택 UI가 있는 인덱스 페이지를 재생성한다."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dates = sorted((p.stem for p in ARCHIVE_DIR.glob("????-??-??.html")), reverse=True)
    dates_js = json.dumps(dates, ensure_ascii=False)
    index = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>친환경 에너지·FDC 브리핑</title><style>
{PAGE_CSS}
.bar{{display:flex;gap:10px;align-items:center;max-width:860px;margin:0 auto 14px;flex-wrap:wrap}}
.bar h1{{font-size:17px;margin:0;flex:1;min-width:200px}}
select,button{{background:#161d29;color:#d8dee9;border:1px solid #2c3a52;border-radius:8px;
  padding:7px 12px;font-size:13.5px;cursor:pointer}}
iframe{{width:100%;height:calc(100vh - 110px);border:1px solid #24443a;border-radius:10px;background:#0d1117}}
</style></head><body>
<div class="bar">
  <h1>🌊 친환경 에너지·FDC 데일리 브리핑</h1>
  <button id="prev" title="이전 날짜">◀</button>
  <select id="dsel"></select>
  <button id="next" title="다음 날짜">▶</button>
</div>
<iframe id="frame" title="브리핑"></iframe>
<script>
const DATES={dates_js};
const sel=document.getElementById('dsel'),fr=document.getElementById('frame');
DATES.forEach(d=>{{const o=document.createElement('option');o.value=d;o.textContent=d+' ('+'일월화수목금토'[new Date(d+'T00:00:00').getDay()]+')';sel.appendChild(o)}});
function load(){{fr.src='energy_daily/'+sel.value+'.html'}}
sel.onchange=load;
document.getElementById('prev').onclick=()=>{{if(sel.selectedIndex<DATES.length-1){{sel.selectedIndex++;load()}}}};
document.getElementById('next').onclick=()=>{{if(sel.selectedIndex>0){{sel.selectedIndex--;load()}}}};
if(DATES.length)load();
else fr.srcdoc='<body style="background:#0d1117;color:#8b96a8;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">아직 생성된 브리핑이 없습니다 — 매일 아침 6시 40분경 자동 생성됩니다.</body>';
</script></body></html>"""
    INDEX_PAGE.write_text(index, encoding="utf-8")
    print(f"[인덱스] energy_briefing_report.html 갱신 (누적 {len(dates)}일)")


def main() -> None:
    now = datetime.now(KST)
    print(f"=== 친환경 에너지·FDC 브리핑 시작: {now:%Y-%m-%d %H:%M} KST / model={MODEL} ===")
    news = fetch_news(now)
    print(f"[뉴스] 지난 24시간 기사 {len(news)}건 수집")
    if len(news) < 3:
        raise RuntimeError("뉴스 수집이 3건 미만 — RSS 차단 가능성, 중단")
    report = generate_report(news_list_text(news), now)
    write_archive(report, now)
    print("=== 완료 ===")


if __name__ == "__main__":
    if "--init" in sys.argv:  # 아카이브 인덱스만 재생성 (첫 배포용 플레이스홀더)
        write_index()
    else:
        main()
