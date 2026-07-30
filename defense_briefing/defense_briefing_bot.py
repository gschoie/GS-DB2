#!/usr/bin/env python3
"""글로벌 방산 데일리 브리핑 봇.

매일 아침(KST 06시 목표) 실행되어:
  1. yfinance로 글로벌 방산주 시세(종가·등락률·시총)를 확정 조회하고
  2. Claude API(web_search)로 지난 24시간 방산 뉴스를 수집·분석해 리포트를 작성한 뒤
  3. 텔레그램(GS K-Defence NEWS | gs_analyst_bot)으로 발송하고
  4. 대시보드 static/defense_briefing/YYYY-MM-DD.html 로 날짜별 아카이브를 남긴다.

시세를 코드로 확정하는 이유: LLM 웹검색만으로 종가·등락률을 찾으면 숫자가
틀리거나 전일 데이터를 가져오는 경우가 잦다. 시세표를 컨텍스트로 주고
Claude는 뉴스 수집·해석만 담당하게 한다.
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

import requests
import yfinance as yf
from anthropic import Anthropic

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).resolve().parent
DASH_STATIC = ROOT.parent / "telegram_research_dashboard" / "static"
# 아카이브 폴더명은 봇 소스 폴더(defense_briefing/)와 충돌하지 않게 defense_daily 사용
# (로컬 build_static이 리포 루트로 출력할 때 이름이 겹치면 소스 폴더를 오염시킴)
ARCHIVE_DIR = DASH_STATIC / "defense_daily"
INDEX_PAGE = DASH_STATIC / "defense_briefing_report.html"

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5")
MAX_WEB_SEARCHES = int(os.environ.get("MAX_WEB_SEARCHES", "12"))

# (티커, 표기명, 국가, 섹터) — 섹터: 항공우주/지상무기/미사일·방공/해군·조선/전자·센서/종합/엔진·부품/ETF
UNIVERSE = [
    # 미국
    ("LMT", "Lockheed Martin", "미국", "종합"),
    ("RTX", "RTX", "미국", "미사일·방공"),
    ("NOC", "Northrop Grumman", "미국", "항공우주"),
    ("GD", "General Dynamics", "미국", "지상무기"),
    ("BA", "Boeing", "미국", "항공우주"),
    ("LHX", "L3Harris", "미국", "전자·센서"),
    ("HII", "Huntington Ingalls", "미국", "해군·조선"),
    ("GE", "GE Aerospace", "미국", "엔진·부품"),
    ("HWM", "Howmet Aerospace", "미국", "엔진·부품"),
    ("TDG", "TransDigm", "미국", "엔진·부품"),
    ("KTOS", "Kratos Defense", "미국", "항공우주"),
    ("AVAV", "AeroVironment", "미국", "항공우주"),
    ("TXT", "Textron", "미국", "항공우주"),
    # 유럽
    ("BA.L", "BAE Systems", "영국", "종합"),
    ("RR.L", "Rolls-Royce", "영국", "엔진·부품"),
    ("BAB.L", "Babcock", "영국", "해군·조선"),
    ("RHM.DE", "Rheinmetall", "독일", "지상무기"),
    ("HAG.DE", "Hensoldt", "독일", "전자·센서"),
    ("R3NK.DE", "Renk", "독일", "엔진·부품"),
    ("LDO.MI", "Leonardo", "이탈리아", "종합"),
    ("HO.PA", "Thales", "프랑스", "전자·센서"),
    ("AM.PA", "Dassault Aviation", "프랑스", "항공우주"),
    ("AIR.PA", "Airbus", "프랑스", "항공우주"),
    ("SAAB-B.ST", "Saab", "스웨덴", "항공우주"),
    ("KOG.OL", "Kongsberg", "노르웨이", "미사일·방공"),
    # 한국
    ("012450.KS", "한화에어로스페이스 (Hanwha Aerospace)", "한국", "종합"),
    ("079550.KS", "LIG넥스원 (LIG Nex1)", "한국", "미사일·방공"),
    ("047810.KS", "한국항공우주 (KAI)", "한국", "항공우주"),
    ("272210.KS", "한화시스템 (Hanwha Systems)", "한국", "전자·센서"),
    ("064350.KS", "현대로템 (Hyundai Rotem)", "한국", "지상무기"),
    ("042660.KS", "한화오션 (Hanwha Ocean)", "한국", "해군·조선"),
    ("329180.KS", "HD현대중공업 (HD HHI)", "한국", "해군·조선"),
    ("103140.KS", "풍산 (Poongsan)", "한국", "지상무기"),
    # 이스라엘·일본
    ("ESLT", "Elbit Systems", "이스라엘", "종합"),
    ("7011.T", "미쓰비시중공업 (MHI)", "일본", "종합"),
    ("7012.T", "가와사키중공업 (KHI)", "일본", "항공우주"),
    ("7013.T", "IHI", "일본", "엔진·부품"),
    # ETF
    ("ITA", "iShares US Aerospace & Defense ETF", "미국", "ETF"),
    ("PPA", "Invesco Aerospace & Defense ETF", "미국", "ETF"),
    ("SHLD", "Global X Defense Tech ETF", "미국", "ETF"),
    ("EUAD", "Select STOXX Europe A&D ETF", "유럽", "ETF"),
    ("449450.KS", "PLUS K방산 ETF", "한국", "ETF"),
]

CURRENCY_SYMBOL = {"USD": "$", "EUR": "€", "GBP": "£", "GBp": "£", "KRW": "₩", "JPY": "¥",
                   "SEK": "kr", "NOK": "kr", "ILS": "₪"}


def fmt_cap(cap: float | None, currency: str) -> str:
    if not cap:
        return "-"
    sym = CURRENCY_SYMBOL.get(currency, currency + " ")
    if currency in ("KRW", "JPY"):
        return f"{sym}{cap / 1e12:.1f}조"
    return f"{sym}{cap / 1e9:.1f}B"


def fetch_prices() -> list[dict]:
    """유니버스 전 종목의 최근 종가·등락률·시총을 조회한다. 실패 종목은 값 None."""
    rows = []
    for ticker, name, country, sector in UNIVERSE:
        row = {"ticker": ticker, "name": name, "country": country, "sector": sector,
               "close": None, "pct": None, "cap": "-", "date": None}
        for attempt in range(2):
            try:
                t = yf.Ticker(ticker)
                hist = t.history(period="10d", interval="1d", auto_adjust=False)
                closes = hist["Close"].dropna()
                if len(closes) >= 2:
                    row["close"] = float(closes.iloc[-1])
                    row["pct"] = (float(closes.iloc[-1]) / float(closes.iloc[-2]) - 1) * 100
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
                    print(f"[가격조회 실패] {ticker}: {e}", file=sys.stderr)
        rows.append(row)
        time.sleep(0.3)  # Yahoo 요청 간격
    return rows


def price_table_text(rows: list[dict]) -> str:
    lines = ["티커 | 기업명 | 국가 | 섹터 | 종가(기준일) | 등락률 | 시총"]
    for r in rows:
        if r["close"] is None:
            lines.append(f"{r['ticker']} | {r['name']} | {r['country']} | {r['sector']} | 조회실패 | - | -")
            continue
        flag = ""
        if abs(r["pct"]) >= 10:
            flag = " ⚠️±10%이상"
        elif abs(r["pct"]) >= 5:
            flag = " ●±5%이상"
        lines.append(
            f"{r['ticker']} | {r['name']} | {r['country']} | {r['sector']} | "
            f"{r['close']:,.2f}({r['date']}) | {r['pct']:+.2f}%{flag} | {r['cap']}"
        )
    return "\n".join(lines)


SYSTEM_PROMPT = """당신은 글로벌 방산 섹터를 담당하는 증권사 리서치 어시스턴트(RA)입니다.
매일 아침 한국의 방산 담당 애널리스트에게 보내는 데일리 브리핑을 작성합니다.

[필수 원칙]
- 제공된 시세표가 종가·등락률·시총의 확정 데이터입니다. 주가 수치는 반드시 이 표의 값을 사용하고, 웹검색으로 찾은 주가 수치로 대체하지 마세요.
- 웹검색은 지난 24시간(최대 48시간) 뉴스 수집에 사용하세요: 전쟁·지정학 긴장, 국방예산, 무기 도입·수출 계약, 대형 수주·취소, 실적 발표·가이던스, 생산 차질, 공급망, M&A, 규제·수출승인, 주요 프로그램 일정·시험·양산·인도.
- 수치·계약금액·수량·일정·등락률을 우선 제시하고, 사실과 해석을 구분하세요.
- 확인되지 않은 보도·루머는 "[미확인]"으로 표시하세요.
- 뉴스 항목마다 출처 매체명과 원문 링크를 마크다운 링크로 붙이세요.
- 한국어로 간결하게 작성하되, 기업명·무기체계명은 공식 영문명을 병기하세요.
- 동일 뉴스 반복 금지. 주가에 실제 영향을 준 이슈 중심으로.

[출력 형식 — 반드시 이 구조를 따르세요]
0. 서두: "글로벌 방산 업종에서 지난 24시간 동안 발생한 주요 뉴스 및 상장 기업 동향을 정리해 드립니다. 업데이트 시간은 {UPDATE_TIME}입니다." 문장으로 시작 (시간 표기 필수)
1. ## 오늘의 핵심 요약 — 시장에 가장 중요한 이슈 3~5개를 3~5줄로
2. ## 주요 주가 동향 — 기업명 | 국가 | 종가 기준 등락률 | 시총 또는 업종 내 중요도 | 변동 요인. 변동폭이 크거나 뉴스가 있는 종목 위주로 15개 내외. 각 행은 "기업명 | 국가 | +x.xx% | 시총 | 요인" 형태의 일반 텍스트 줄로 쓰세요 (마크다운 표 문법 |---| 사용 금지).
3. ## 큰 변동 분석 — ±10% 이상 종목은 반드시 별도 표기하고 배경을 뉴스·실적·수급·정책 요인으로 구분해 구체적으로 설명. 해당 없으면 "±10% 이상 변동 종목 없음. (±5% 이상: ...)"으로 처리
4. ## 섹터별 정리 — 항공우주 / 지상무기 / 미사일·방공 / 해군·조선 / 전자·센서 순으로 핵심 이슈
5. ## 투자 시사점 — 단기 촉매와 중기 업황·수주잔고 관점 3개 이내

굵은 강조는 **텍스트**, 링크는 [매체명](URL) 형식의 마크다운을 사용하세요. 마크다운 표(|---|)와 HTML 태그는 사용하지 마세요."""


def generate_report(price_table: str, now: datetime) -> str:
    client = Anthropic()
    update_time = now.strftime("%Y-%m-%d %H:00")
    system = SYSTEM_PROMPT.replace("{UPDATE_TIME}", update_time)
    user = (
        f"현재 시각(KST): {now.strftime('%Y-%m-%d %H:%M')}\n"
        f"오늘의 확정 시세표 (각 시장의 최근 종가 기준, 등락률은 직전 거래일 대비):\n\n"
        f"{price_table}\n\n"
        "위 시세표와 지난 24시간 웹검색 결과를 바탕으로 글로벌 방산 데일리 브리핑을 작성해 주세요."
    )
    with client.messages.stream(
        model=MODEL,
        max_tokens=32000,
        system=system,
        tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": MAX_WEB_SEARCHES}],
        messages=[{"role": "user", "content": user}],
    ) as stream:
        response = stream.get_final_message()
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Claude가 요청을 거절했습니다: {response.stop_details}")
    report = "".join(b.text for b in response.content if b.type == "text")
    u = response.usage
    print(f"[Claude] in={u.input_tokens} out={u.output_tokens} stop={response.stop_reason}")
    if not report.strip():
        raise RuntimeError("Claude 응답에 텍스트가 없습니다")
    return report.strip()


# ── 마크다운 → 텔레그램 HTML / 웹페이지 HTML ──────────────────────────────

MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
MD_BOLD = re.compile(r"\*\*([^*]+)\*\*")


def md_inline(line: str) -> str:
    """이스케이프 후 링크·볼드만 변환 (텔레그램·웹 공용 서브셋)."""
    out = html.escape(line, quote=False)
    out = MD_LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', out)
    out = MD_BOLD.sub(r"<b>\1</b>", out)
    return out


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


def send_telegram(md_report: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    body = to_telegram_html(md_report)
    header = "🌍 <b>글로벌 방산 데일리 브리핑</b>\n"
    chunks = split_chunks(header + body)
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
            # HTML 파싱 오류면 평문으로 재시도
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


# ── 대시보드 아카이브 페이지 ──────────────────────────────────────────────

PAGE_CSS = """
:root{color-scheme:dark}
body{margin:0;padding:28px 24px 60px;background:#0d1117;color:#d8dee9;
  font-family:'Pretendard','Malgun Gothic','Apple SD Gothic Neo',sans-serif;line-height:1.75;font-size:15px}
.wrap{max-width:860px;margin:0 auto}
h1{font-size:21px;color:#e8edf5;margin:0 0 4px}
.meta{color:#8b96a8;font-size:12.5px;margin-bottom:22px}
h2{font-size:16.5px;color:#7fb4ff;margin:30px 0 10px;padding-bottom:6px;border-bottom:1px solid #223046}
a{color:#6aa8ff;text-decoration:none}a:hover{text-decoration:underline}
b,strong{color:#f0f4fa}
ul{margin:6px 0;padding-left:22px}
p{margin:8px 0}
hr{border:none;border-top:1px solid #223046;margin:20px 0}
"""


def report_to_page_html(md: str) -> str:
    """마크다운 리포트를 아카이브 페이지 본문 HTML로 변환."""
    out, in_list = [], False
    for raw in md.splitlines():
        s = raw.strip()
        m = re.match(r"^(#{1,6})\s+(.*)", s)
        if in_list and not s.startswith(("- ", "* ")):
            out.append("</ul>")
            in_list = False
        if not s:
            continue
        if m:
            out.append(f"<h2>{md_inline(m.group(2))}</h2>")
        elif s.startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{md_inline(s[2:])}</li>")
        elif s in ("---", "***"):
            out.append("<hr>")
        else:
            out.append(f"<p>{md_inline(s)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def write_archive(md_report: str, now: datetime) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    date_str = now.strftime("%Y-%m-%d")
    body = report_to_page_html(md_report)
    page = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>글로벌 방산 브리핑 {date_str}</title><style>{PAGE_CSS}</style></head>
<body><div class="wrap">
<h1>🌍 글로벌 방산 데일리 브리핑</h1>
<div class="meta">기준: {now.strftime('%Y-%m-%d %H:00')} KST · 생성: Claude({MODEL}) + yfinance 확정 시세</div>
{body}
</div></body></html>"""
    (ARCHIVE_DIR / f"{date_str}.html").write_text(page, encoding="utf-8")
    print(f"[아카이브] {date_str}.html 생성")
    write_index()


def write_index() -> None:
    """날짜별 아카이브 목록을 읽어 선택 UI가 있는 인덱스 페이지를 재생성한다."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dates = sorted((p.stem for p in ARCHIVE_DIR.glob("????-??-??.html")), reverse=True)
    dates_js = json.dumps(dates, ensure_ascii=False)
    index = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>글로벌 방산 브리핑</title><style>
{PAGE_CSS}
.bar{{display:flex;gap:10px;align-items:center;max-width:860px;margin:0 auto 14px;flex-wrap:wrap}}
.bar h1{{font-size:17px;margin:0;flex:1;min-width:200px}}
select,button{{background:#161d29;color:#d8dee9;border:1px solid #2c3a52;border-radius:8px;
  padding:7px 12px;font-size:13.5px;cursor:pointer}}
iframe{{width:100%;height:calc(100vh - 110px);border:1px solid #223046;border-radius:10px;background:#0d1117}}
</style></head><body>
<div class="bar">
  <h1>🌍 글로벌 방산 데일리 브리핑</h1>
  <button id="prev" title="이전 날짜">◀</button>
  <select id="dsel"></select>
  <button id="next" title="다음 날짜">▶</button>
</div>
<iframe id="frame" title="브리핑"></iframe>
<script>
const DATES={dates_js};
const sel=document.getElementById('dsel'),fr=document.getElementById('frame');
DATES.forEach(d=>{{const o=document.createElement('option');o.value=d;o.textContent=d;sel.appendChild(o)}});
function load(){{fr.src='defense_daily/'+sel.value+'.html'}}
sel.onchange=load;
document.getElementById('prev').onclick=()=>{{if(sel.selectedIndex<DATES.length-1){{sel.selectedIndex++;load()}}}};
document.getElementById('next').onclick=()=>{{if(sel.selectedIndex>0){{sel.selectedIndex--;load()}}}};
if(DATES.length)load();
else fr.srcdoc='<body style="background:#0d1117;color:#8b96a8;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">아직 생성된 브리핑이 없습니다 — 매일 아침 6시경 자동 생성됩니다.</body>';
</script></body></html>"""
    INDEX_PAGE.write_text(index, encoding="utf-8")
    print(f"[인덱스] defense_briefing_report.html 갱신 (누적 {len(dates)}일)")


def main() -> None:
    now = datetime.now(KST)
    print(f"=== 글로벌 방산 브리핑 시작: {now:%Y-%m-%d %H:%M} KST / model={MODEL} ===")
    rows = fetch_prices()
    ok = sum(1 for r in rows if r["close"] is not None)
    print(f"[시세] {ok}/{len(rows)} 종목 조회 성공")
    if ok < len(rows) * 0.5:
        raise RuntimeError("시세 조회 성공률이 50% 미만 — Yahoo 차단 가능성, 중단")
    table = price_table_text(rows)
    report = generate_report(table, now)
    write_archive(report, now)
    send_telegram(report)
    print("=== 완료 ===")


if __name__ == "__main__":
    if "--init" in sys.argv:  # 아카이브 인덱스만 재생성 (첫 배포용 플레이스홀더)
        write_index()
    else:
        main()
