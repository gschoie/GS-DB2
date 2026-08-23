#!/usr/bin/env python3
"""글로벌 방산 주간 정리본 봇.

매주 토요일 KST 11:50 실행. 지난 7일의 아침 브리핑 2종
(defense_daily = Gemini판, claude_defense = Claude판)의 마크다운 원문을 모아
Gemini가 주간 정리본 1편을 작성한다. 주간 등락률은 yfinance로 확정 조회해
서술이 아닌 데이터로 제공한다 (일간 봇과 같은 원칙).

산출물:
  - static/defense_weekly/YYYY-MM-DD.{html,md}   날짜별 주간 정리본 (토요일 날짜)
  - static/defense_weekly_report.html            날짜 선택 인덱스 (대시보드 iframe)
  - static/defense_weekly/last4weeks.{md,html}   최근 4주 묶음 — 월간 세미나용
    NotebookLM 소스 업로드용(.md) + 인쇄/PDF용 밝은 테마(.html)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf
from google import genai
from google.genai import types as genai_types

# 일간 봇의 유니버스·렌더러를 재사용한다 (같은 폴더)
from defense_briefing_bot import (
    UNIVERSE,
    PAGE_CSS,
    fmt_cap,
    report_to_page_html,
)

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).resolve().parent
DASH_STATIC = ROOT.parent / "telegram_research_dashboard" / "static"
DAILY_DIRS = [
    ("Gemini판", DASH_STATIC / "defense_daily"),
    ("Claude판", DASH_STATIC / "claude_defense"),
]
WEEKLY_DIR = DASH_STATIC / "defense_weekly"
INDEX_PAGE = DASH_STATIC / "defense_weekly_report.html"

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
LAST_USED_MODEL = MODEL


# ── 입력 수집 ──────────────────────────────────────────────────────────────

def collect_daily_briefs(now: datetime, days: int = 7) -> tuple[str, list[str]]:
    """지난 days일의 일간 브리핑 md를 (본문 텍스트, 사용된 날짜 목록)으로 반환."""
    wanted = [(now - timedelta(days=offset)).strftime("%Y-%m-%d")
              for offset in range(days - 1, -1, -1)]
    blocks, used_dates = [], []
    for date_str in wanted:
        for label, directory in DAILY_DIRS:
            path = directory / f"{date_str}.md"
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8").strip()
            # '참고 출처' 꼬리 목록은 주간 종합에 불필요 — 토큰만 커진다
            text = re.split(r"\n## 참고 출처\n", text)[0].strip()
            blocks.append(f"===== [{date_str} · {label}] =====\n{text}")
            if date_str not in used_dates:
                used_dates.append(date_str)
    return "\n\n".join(blocks), used_dates


def fetch_weekly_prices() -> list[dict]:
    """유니버스 전 종목의 주간(약 5거래일) 등락률·시총을 확정 조회한다."""
    rows = []
    for ticker, name, country, sector in UNIVERSE:
        row = {"ticker": ticker, "name": name, "country": country, "sector": sector,
               "close": None, "wk_pct": None, "cap": "-", "date": None}
        for attempt in range(2):
            try:
                t = yf.Ticker(ticker)
                hist = t.history(period="15d", interval="1d", auto_adjust=False)
                closes = hist["Close"].dropna()
                if len(closes) >= 2:
                    base_idx = -6 if len(closes) >= 6 else 0
                    row["close"] = float(closes.iloc[-1])
                    row["wk_pct"] = (float(closes.iloc[-1]) / float(closes.iloc[base_idx]) - 1) * 100
                    row["date"] = closes.index[-1].strftime("%m/%d")
                try:
                    fi = t.fast_info
                    row["cap"] = fmt_cap(fi.get("marketCap"), fi.get("currency") or "")
                except Exception:
                    pass
                break
            except Exception as e:
                if attempt == 0:
                    time.sleep(3)
                else:
                    print(f"[주간시세 실패] {ticker}: {e}", file=sys.stderr)
        rows.append(row)
        time.sleep(0.3)
    return rows


def weekly_price_table_text(rows: list[dict]) -> str:
    lines = ["티커 | 기업명 | 국가 | 섹터 | 종가(기준일) | 주간 등락률 | 시총"]
    for r in rows:
        if r["close"] is None:
            lines.append(f"{r['ticker']} | {r['name']} | {r['country']} | {r['sector']} | 조회실패 | - | -")
            continue
        flag = ""
        if abs(r["wk_pct"]) >= 15:
            flag = " ⚠️±15%이상"
        elif abs(r["wk_pct"]) >= 7:
            flag = " ●±7%이상"
        lines.append(
            f"{r['ticker']} | {r['name']} | {r['country']} | {r['sector']} | "
            f"{r['close']:,.2f}({r['date']}) | {r['wk_pct']:+.2f}%{flag} | {r['cap']}"
        )
    return "\n".join(lines)


# ── Gemini 작성 ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """당신은 글로벌 방산 섹터를 담당하는 증권사 리서치 어시스턴트(RA)입니다.
지난 한 주(월~토)의 데일리 브리핑들을 종합해, 한국의 방산 담당 애널리스트가 주말에 한 번에 읽는 주간 정리본을 작성합니다.

[필수 원칙]
- **사실관계는 함께 제공되는 [지난 7일 데일리 브리핑 모음]에 있는 내용만 근거로 쓰세요.** 모음에 없는 사건을 당신의 기억에서 꺼내 쓰는 것을 절대 금지합니다.
- 같은 사건이 여러 날 반복 언급되면 한 번만, 가장 진전된 내용으로 정리하고 최초 보도일(월/일)을 적으세요.
- Gemini판과 Claude판 두 브리핑이 같은 사건을 다르게 서술하면 더 구체적인 쪽을 따르되, 사실이 상충하면 "[상충]"을 표기하고 양쪽을 병기하세요.
- 주간 등락률 수치는 반드시 [확정 주간 시세표]의 값을 사용하세요. 데일리 브리핑 속 일간 등락률을 합산·추정해 주간 수치를 만들지 마세요.
- 일간 브리핑에 있던 원문 링크는 주간 정리본에서도 핵심 사건 위주로 최대 15개까지 [매체명](URL) 형식으로 유지하세요.
- 확인되지 않은 보도·루머는 "[미확인]" 표시를 유지하세요.
- **최종 리포트 본문만 출력하세요.** 계획·사고 과정·코드 블록 금지. 응답은 반드시 서두 문장("글로벌 방산 업종의 지난 한 주...")으로 시작해야 합니다.
- 한국어로 간결하게, 기업명·무기체계명은 공식 영문명 병기.

[출력 형식 — 반드시 이 구조를 따르세요]
0. 서두: "글로벌 방산 업종의 지난 한 주({PERIOD}) 주요 흐름을 정리해 드립니다." 문장으로 시작
1. ## 주간 핵심 테마 — 이번 주를 관통한 테마 3~5개. 각 테마 2~3문장, 반복 이슈는 묶어서
2. ## 계약·수주·프로그램 — 이번 주 확정·진전된 계약/수주/선정/취소를 목록으로 (국가 | 프로그램 | 업체 | 금액·수량 | 날짜). 한국 기업 관련 건은 빠짐없이. 각 행은 " | " 구분 일반 텍스트 줄로 (마크다운 표 문법 |---| 금지)
3. ## 주간 주가 리뷰 — [확정 주간 시세표] 기준. 주간 상승·하락 상위와 그 배경을 데일리 브리핑의 뉴스로 연결. ±15% 이상은 반드시 별도 설명
4. ## 정책·지정학 — 국방예산, 전쟁·긴장, 규제·수출승인 흐름
5. ## 한국 방산 종합 — 한국 기업들 관련 한 주 소식 종합과 수주 파이프라인 관점의 평가
6. ## 다음 주 관전 포인트 — 데일리 브리핑에서 예고된 일정·이벤트 기반 3~5개 (모음에 근거 없는 일정 창작 금지)

굵은 강조는 **텍스트**, 링크는 [매체명](URL) 마크다운. 마크다운 표(|---|)와 HTML 태그 금지."""

REPORT_OPENER = "글로벌 방산 업종의 지난 한 주"


def clean_report(text: str) -> str:
    idx = text.find(REPORT_OPENER)
    if idx > 0:
        print(f"[정리] 리포트 앞 사고 과정 누출 {idx}자 제거")
        return text[idx:].strip()
    if idx == 0:
        return text.strip()
    idx = text.find("## 주간 핵심 테마")
    if idx > 0:
        print("[정리] 서두 문장 없음 — 핵심 테마 헤딩부터 절단", file=sys.stderr)
        return text[idx:].strip()
    return text.strip()


def generate_weekly_report(briefs_text: str, price_table: str,
                           period_label: str, now: datetime) -> str:
    client = genai.Client()
    system = SYSTEM_PROMPT.replace("{PERIOD}", period_label)
    user = (
        f"현재 시각(KST): {now.strftime('%Y-%m-%d %H:%M')}\n"
        f"정리 대상 기간: {period_label}\n\n"
        f"[확정 주간 시세표] (최근 종가 기준, 등락률은 약 5거래일 전 대비):\n"
        f"{price_table}\n\n"
        f"[지난 7일 데일리 브리핑 모음] (사실관계는 이 모음만 근거로 사용):\n"
        f"{briefs_text}\n\n"
        "위 자료로 글로벌 방산 주간 정리본을 작성해 주세요."
    )
    config = genai_types.GenerateContentConfig(
        system_instruction=system,
        temperature=0.3,
        max_output_tokens=16384,
    )
    models = list(dict.fromkeys([MODEL, "gemini-2.5-flash"]))
    used_model, response = None, None
    for model in models:
        for attempt in range(2):
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
        raise RuntimeError("Gemini 호출 모두 실패 (pro·flash 폴백 포함)")
    print(f"[Gemini] 사용 모델: {used_model}")
    global LAST_USED_MODEL
    LAST_USED_MODEL = used_model
    um = getattr(response, "usage_metadata", None)
    if um:
        print(f"[Gemini] in={um.prompt_token_count} out={um.candidates_token_count}")
    return clean_report(response.text.strip())


# ── 산출물 ────────────────────────────────────────────────────────────────

def write_archive(md_report: str, period_label: str, now: datetime) -> None:
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    date_str = now.strftime("%Y-%m-%d")
    body = report_to_page_html(md_report)
    page = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>글로벌 방산 주간정리 {date_str}</title><style>{PAGE_CSS}</style></head>
<body><div class="wrap">
<h1>🗓️ 글로벌 방산 주간 정리</h1>
<div class="meta">기간: {period_label} · 생성: {now.strftime('%Y-%m-%d %H:%M')} KST · Gemini({LAST_USED_MODEL}) + 데일리 브리핑 2종(제미나이·클로드) + yfinance 주간 시세</div>
{body}
</div></body></html>"""
    (WEEKLY_DIR / f"{date_str}.html").write_text(page, encoding="utf-8")
    md_head = (f"# 글로벌 방산 주간 정리 {date_str}\n"
               f"(기간: {period_label})\n\n")
    (WEEKLY_DIR / f"{date_str}.md").write_text(md_head + md_report, encoding="utf-8")
    print(f"[아카이브] defense_weekly/{date_str}.html 생성")


def write_last4_bundle() -> None:
    """최근 4주 주간 정리본을 한 파일로 묶는다 — 월간 세미나(NotebookLM) 소스용."""
    dates = sorted((p.stem for p in WEEKLY_DIR.glob("????-??-??.md")), reverse=True)[:4]
    if not dates:
        return
    parts = [(WEEKLY_DIR / f"{d}.md").read_text(encoding="utf-8") for d in reversed(dates)]
    bundle_md = (
        "# 글로벌 방산 월간 정리 (최근 4주 주간 정리본 묶음)\n"
        f"수록 주간: {', '.join(reversed(dates))}\n\n"
        + "\n\n---\n\n".join(parts)
    )
    (WEEKLY_DIR / "last4weeks.md").write_text(bundle_md, encoding="utf-8")

    # 인쇄/PDF용 밝은 테마 — NotebookLM에 PDF로 넣고 싶을 때 Ctrl+P로 저장
    body = report_to_page_html(bundle_md)
    light_css = """
body{margin:0;padding:32px 28px;background:#fff;color:#1a1a1a;
  font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;line-height:1.7;font-size:14px}
.wrap{max-width:820px;margin:0 auto}
h1{font-size:20px;margin:24px 0 6px}
h2{font-size:15.5px;margin:22px 0 8px;padding-bottom:5px;border-bottom:1px solid #ccc;color:#14532d}
a{color:#1d4ed8;text-decoration:none}
table.ptab{border-collapse:collapse;width:100%;margin:10px 0;font-size:12.5px}
.ptab td{border-bottom:1px solid #e2e2e2;padding:5px 8px;text-align:left;vertical-align:top}
.up{color:#c02626;font-weight:600}.down{color:#1d4ed8;font-weight:600}
hr{border:none;border-top:2px solid #999;margin:28px 0}
.note{background:#f4f6f2;border:1px solid #d7ddd2;border-radius:8px;padding:10px 14px;
  font-size:12.5px;color:#444;margin-bottom:18px}
@media print{.note{display:none}}
"""
    page = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>글로벌 방산 월간 정리 (4주 묶음)</title><style>{light_css}</style></head>
<body><div class="wrap">
<div class="note">월간 세미나 인포그래픽 소스용 묶음입니다. NotebookLM에는 같은 폴더의
<b>last4weeks.md</b> 파일 업로드를 권장하고, PDF가 필요하면 이 화면에서 Ctrl+P → PDF로 저장하세요.</div>
{body}
</div></body></html>"""
    (WEEKLY_DIR / "last4weeks.html").write_text(page, encoding="utf-8")
    print(f"[묶음] last4weeks.md/.html 갱신 ({len(dates)}주 수록)")


def write_index() -> None:
    """날짜별 주간 정리 목록 + 4주 묶음 링크가 있는 인덱스 페이지를 재생성한다."""
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    dates = sorted((p.stem for p in WEEKLY_DIR.glob("????-??-??.html")), reverse=True)
    dates_js = json.dumps(dates, ensure_ascii=False)
    index = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>글로벌 방산 주간 정리</title><style>
{PAGE_CSS}
.bar{{display:flex;gap:10px;align-items:center;max-width:860px;margin:0 auto 14px;flex-wrap:wrap}}
.bar h1{{font-size:17px;margin:0;flex:1;min-width:200px}}
select,button{{background:#161d29;color:#d8dee9;border:1px solid #2c3a52;border-radius:8px;
  padding:7px 12px;font-size:13.5px;cursor:pointer}}
.bar a.bundle{{color:#7fb4ff;font-size:12.5px;text-decoration:none;border:1px solid #2c3a52;
  border-radius:8px;padding:7px 12px}}
iframe{{width:100%;height:calc(100vh - 110px);border:1px solid #223046;border-radius:10px;background:#0d1117}}
</style></head><body>
<div class="bar">
  <h1>🗓️ 글로벌 방산 주간 정리 <small style="font-size:11px;color:#8b96a8">매주 토 11:50</small></h1>
  <a class="bundle" href="defense_weekly/last4weeks.html" target="_blank" rel="noopener" title="월간 세미나(NotebookLM)용 최근 4주 묶음">📦 4주 묶음</a>
  <a class="bundle" href="defense_weekly/last4weeks.md" download title="NotebookLM 업로드용 마크다운">⬇ .md</a>
  <button id="prev" title="이전 주">◀</button>
  <select id="dsel"></select>
  <button id="next" title="다음 주">▶</button>
</div>
<iframe id="frame" title="주간 정리"></iframe>
<script>
const DATES={dates_js};
const sel=document.getElementById('dsel'),fr=document.getElementById('frame');
DATES.forEach(d=>{{const o=document.createElement('option');o.value=d;o.textContent=d;sel.appendChild(o)}});
function load(){{fr.src='defense_weekly/'+sel.value+'.html'}}
sel.onchange=load;
document.getElementById('prev').onclick=()=>{{if(sel.selectedIndex<DATES.length-1){{sel.selectedIndex++;load()}}}};
document.getElementById('next').onclick=()=>{{if(sel.selectedIndex>0){{sel.selectedIndex--;load()}}}};
if(DATES.length)load();
else fr.srcdoc='<body style="background:#0d1117;color:#8b96a8;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">아직 주간 정리가 없습니다 — 매주 토요일 11:50에 자동 생성됩니다.</body>';
</script></body></html>"""
    INDEX_PAGE.write_text(index, encoding="utf-8")
    print(f"[인덱스] defense_weekly_report.html 갱신 (누적 {len(dates)}주)")


def main() -> None:
    now = datetime.now(KST)
    period_label = (f"{(now - timedelta(days=6)).strftime('%m/%d')}"
                    f"~{now.strftime('%m/%d')}")
    print(f"=== 방산 주간 정리 시작: {now:%Y-%m-%d %H:%M} KST / 기간 {period_label} / model={MODEL} ===")
    briefs_text, used_dates = collect_daily_briefs(now)
    print(f"[수집] 일간 브리핑 {len(used_dates)}일치 ({', '.join(used_dates)})")
    if len(used_dates) < 3:
        raise RuntimeError("일간 브리핑이 3일치 미만 — 주간 정리를 만들기에 부족, 중단")
    rows = fetch_weekly_prices()
    ok = sum(1 for r in rows if r["close"] is not None)
    print(f"[주간시세] {ok}/{len(rows)} 종목 조회 성공")
    price_table = weekly_price_table_text(rows)
    report = generate_weekly_report(briefs_text, price_table, period_label, now)
    write_archive(report, period_label, now)
    write_last4_bundle()
    write_index()
    print("=== 완료 ===")


if __name__ == "__main__":
    if "--init" in sys.argv:  # 인덱스만 재생성 (첫 배포용 플레이스홀더)
        write_index()
    else:
        main()
