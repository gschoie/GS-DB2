#!/usr/bin/env python3
"""글로벌 건설기계 데일리 브리핑 봇 (defense_briefing_bot과 동일 골격).

매일 아침(KST 06:10 목표) 실행되어:
  1. yfinance로 글로벌 건설기계주 시세(종가·등락률·시총)와 매크로 지표
     (미국채 10년·금·구리·WTI·환율)를 확정 조회하고
  2. 구글뉴스 RSS로 지난 24시간 기사를 수집한 뒤 Gemini API가 이를 유일한
     뉴스 근거로 데일리 브리핑을 작성하고
  3. 대시보드 static/construction_daily/YYYY-MM-DD.html 로 날짜별 아카이브를 남긴다.
  4. 텔레그램은 시크릿이 설정된 경우에만 발송 (기본 미설정 → 생략).

시세·매크로를 코드로 확정하는 이유: LLM 웹검색만으로 종가·등락률을 찾으면
숫자가 틀리거나 전일 데이터를 가져오는 경우가 잦다 (defense_briefing에서 검증된 원칙).
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

# yfinance·genai·requests는 사용하는 함수 안에서 import한다 —
# --render-md(로컬 렌더 전용) 모드는 네트워크 패키지 없이도 돌아야 한다.

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).resolve().parent
DASH_STATIC = ROOT.parent / "telegram_research_dashboard" / "static"
ARCHIVE_DIR = DASH_STATIC / "construction_daily"
INDEX_PAGE = DASH_STATIC / "construction_briefing_report.html"
INPUTS_DIR = ROOT / "inputs"  # 수집 전용 모드 산출물 (Claude 작성 세션의 입력)

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
LAST_USED_MODEL = MODEL  # 폴백 시 실제 사용 모델로 갱신됨

# (티커, 표기명, 국가, 섹터)
# 섹터: 종합/광산장비/소형장비/크레인·고소장비/렌탈/딜러/농기계·건설/ETF
UNIVERSE = [
    # 한국 — 커버리지의 중심
    ("267270.KS", "HD현대건설기계 (HD Hyundai CE·Develon)", "한국", "종합"),
    # HD현대인프라코어(042670)는 HD현대건설기계와 합병으로 상장폐지 — 디벨론은 존속법인 브랜드
    ("241560.KS", "두산밥캣 (Doosan Bobcat)", "한국", "소형장비"),
    # 미국
    ("CAT", "Caterpillar", "미국", "종합"),
    ("DE", "John Deere", "미국", "농기계·건설"),
    ("CNH", "CNH Industrial", "미국", "농기계·건설"),
    ("TEX", "Terex", "미국", "크레인·고소장비"),
    ("OSK", "Oshkosh (JLG)", "미국", "크레인·고소장비"),
    ("MTW", "Manitowoc", "미국", "크레인·고소장비"),
    ("URI", "United Rentals", "미국", "렌탈"),
    ("HRI", "Herc Holdings", "미국", "렌탈"),
    # 유럽
    ("VOLV-B.ST", "Volvo Group (Volvo CE)", "스웨덴", "종합"),
    ("EPI-A.ST", "Epiroc", "스웨덴", "광산장비"),
    ("SAND.ST", "Sandvik", "스웨덴", "광산장비"),
    ("WAC.DE", "Wacker Neuson", "독일", "소형장비"),
    ("MTU.PA", "Manitou", "프랑스", "크레인·고소장비"),
    # 2026 NYSE 상장 이전으로 런던 티커(AHT.L) 조회 불가 — 미국 티커 사용
    ("AHT", "Ashtead (Sunbelt)", "영국", "렌탈"),
    # 일본
    ("6301.T", "고마쓰 (Komatsu)", "일본", "종합"),
    ("6305.T", "히타치건기 (Hitachi CM)", "일본", "종합"),
    ("6326.T", "구보타 (Kubota)", "일본", "농기계·건설"),
    ("6432.T", "다케우치 (Takeuchi)", "일본", "소형장비"),
    ("6395.T", "타다노 (Tadano)", "일본", "크레인·고소장비"),
    # 중국
    ("600031.SS", "싸니중공업 (SANY)", "중국", "종합"),
    ("000425.SZ", "쉬공기계 (XCMG)", "중국", "종합"),
    ("000157.SZ", "중롄중커 (Zoomlion)", "중국", "크레인·고소장비"),
    ("000528.SZ", "류공 (LiuGong)", "중국", "종합"),
    # 인도
    ("ACE.NS", "Action Construction Equipment", "인도", "크레인·고소장비"),
    ("ESCORTS.NS", "Escorts Kubota", "인도", "농기계·건설"),
    # 딜러 — 장비 유통의 최전선 지표 (세계 최대 CAT 딜러 등)
    ("FTT.TO", "Finning International", "캐나다", "딜러"),
    ("TIH.TO", "Toromont Industries", "캐나다", "딜러"),
    # ETF
    ("PAVE", "Global X US Infrastructure ETF", "미국", "ETF"),
]

# 매크로 지표 (티커, 표기명, 단위) — 금리·주요 원재료(금·은·구리·유가)·환율을 코드로 확정
MACRO_TICKERS = [
    ("^TNX", "미국채 10년 금리", "%"),
    ("GC=F", "금 (COMEX)", "$/oz"),
    ("SI=F", "은 (COMEX)", "$/oz"),
    ("HG=F", "구리 (COMEX)", "$/lb"),
    ("CL=F", "WTI 원유", "$/bbl"),
    ("KRW=X", "원/달러", "₩"),
    ("CNY=X", "위안/달러", "¥"),
]

# 주가표 그룹 구분 (표시 순서) — 대형/중소형/광산/국가 축
PRICE_GROUPS = [
    ("한국", ["267270.KS", "241560.KS"]),
    ("글로벌 대형", ["CAT", "DE", "CNH", "6301.T", "6305.T", "6326.T", "VOLV-B.ST"]),
    ("중소형", ["TEX", "OSK", "MTW", "WAC.DE", "MTU.PA", "6432.T", "6395.T",
               "ACE.NS", "ESCORTS.NS"]),
    ("광산장비", ["EPI-A.ST", "SAND.ST"]),
    ("렌탈·딜러", ["URI", "HRI", "AHT", "FTT.TO", "TIH.TO"]),
    ("중국", ["600031.SS", "000425.SZ", "000157.SZ", "000528.SZ"]),
    ("ETF", ["PAVE"]),
]

# 수익률 계산 구간 (거래일 기준 오프셋)
HORIZONS = [("1M", 21), ("3M", 63), ("12M", 252)]


def horizon_pcts(closes) -> dict[str, float | None]:
    """종가 시계열에서 1M/3M/12M 수익률(%)을 계산. 이력이 짧으면 None."""
    out = {}
    last = float(closes.iloc[-1])
    for label, offset in HORIZONS:
        if len(closes) > offset:
            out[label] = (last / float(closes.iloc[-offset - 1]) - 1) * 100
        else:
            out[label] = None
    return out


def fmt_pct(value: float | None) -> str:
    return "-" if value is None else f"{value:+.1f}%"

CURRENCY_SYMBOL = {"USD": "$", "EUR": "€", "GBP": "£", "GBp": "£", "KRW": "₩", "JPY": "¥",
                   "SEK": "kr", "NOK": "kr", "CNY": "¥", "INR": "₹", "CAD": "C$"}


def fmt_cap(cap: float | None, currency: str) -> str:
    if not cap:
        return "-"
    sym = CURRENCY_SYMBOL.get(currency, currency + " ")
    if currency in ("KRW", "JPY"):
        return f"{sym}{cap / 1e12:.1f}조"
    return f"{sym}{cap / 1e9:.1f}B"


def fetch_prices() -> list[dict]:
    """유니버스 전 종목의 최근 종가·등락률·시총을 조회한다. 실패 종목은 값 None."""
    import yfinance as yf
    rows = []
    for ticker, name, country, sector in UNIVERSE:
        row = {"ticker": ticker, "name": name, "country": country, "sector": sector,
               "close": None, "pct": None, "cap": "-", "date": None}
        for attempt in range(2):
            try:
                t = yf.Ticker(ticker)
                # 12M 수익률 계산을 위해 약 400일치 조회
                hist = t.history(period="400d", interval="1d", auto_adjust=False)
                closes = hist["Close"].dropna()
                if len(closes) >= 2:
                    row["close"] = float(closes.iloc[-1])
                    row["pct"] = (float(closes.iloc[-1]) / float(closes.iloc[-2]) - 1) * 100
                    row["date"] = closes.index[-1].strftime("%m/%d")
                    row.update({f"pct_{k.lower()}": v for k, v in horizon_pcts(closes).items()})
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


def fetch_macro() -> list[dict]:
    """매크로 지표(금리·금·구리·유가·환율)의 최근값·등락률을 조회한다."""
    import yfinance as yf
    rows = []
    for ticker, name, unit in MACRO_TICKERS:
        row = {"ticker": ticker, "name": name, "unit": unit,
               "close": None, "pct": None, "date": None}
        for attempt in range(2):
            try:
                hist = yf.Ticker(ticker).history(period="400d", interval="1d", auto_adjust=False)
                closes = hist["Close"].dropna()
                if len(closes) >= 2:
                    row["close"] = float(closes.iloc[-1])
                    row["pct"] = (float(closes.iloc[-1]) / float(closes.iloc[-2]) - 1) * 100
                    row["date"] = closes.index[-1].strftime("%m/%d")
                    row.update({f"pct_{k.lower()}": v for k, v in horizon_pcts(closes).items()})
                break
            except Exception as e:
                if attempt == 0:
                    time.sleep(3)
                else:
                    print(f"[매크로조회 실패] {ticker}: {e}", file=sys.stderr)
        rows.append(row)
        time.sleep(0.3)
    return rows


def price_table_text(rows: list[dict]) -> str:
    """그룹(한국/대형/중소형/광산/렌탈·딜러/중국/ETF)별로 묶은 시세표 텍스트."""
    by_ticker = {r["ticker"]: r for r in rows}
    lines = ["티커 | 기업명 | 국가 | 종가(기준일) | 1D | 1M | 3M | 12M | 시총"]
    grouped = set()
    for group_name, tickers in PRICE_GROUPS:
        members = [by_ticker[t] for t in tickers if t in by_ticker]
        if not members:
            continue
        lines.append(f"[{group_name}]")
        grouped.update(t for t in tickers)
        for r in members:
            lines.append(price_row_text(r))
    # 그룹 정의에 빠진 신규 종목 안전망
    for r in rows:
        if r["ticker"] not in grouped:
            lines.append(price_row_text(r))
    return "\n".join(lines)


def price_row_text(r: dict) -> str:
    if r["close"] is None:
        return f"{r['ticker']} | {r['name']} | {r['country']} | 조회실패 | - | - | - | - | -"
    flag = ""
    if abs(r["pct"]) >= 10:
        flag = " ⚠️±10%이상"
    elif abs(r["pct"]) >= 5:
        flag = " ●±5%이상"
    return (
        f"{r['ticker']} | {r['name']} | {r['country']} | "
        f"{r['close']:,.2f}({r['date']}) | {r['pct']:+.2f}%{flag} | "
        f"{fmt_pct(r.get('pct_1m'))} | {fmt_pct(r.get('pct_3m'))} | "
        f"{fmt_pct(r.get('pct_12m'))} | {r['cap']}"
    )


def macro_table_text(rows: list[dict]) -> str:
    lines = ["지표 | 값(기준일) | 1D | 1M | 3M | 12M"]
    for r in rows:
        if r["close"] is None:
            lines.append(f"{r['name']} | 조회실패 | - | - | - | -")
            continue
        lines.append(
            f"{r['name']} | {r['close']:,.2f}{r['unit']}({r['date']}) | {r['pct']:+.2f}% | "
            f"{fmt_pct(r.get('pct_1m'))} | {fmt_pct(r.get('pct_3m'))} | {fmt_pct(r.get('pct_12m'))}"
        )
    return "\n".join(lines)


# ── 구글뉴스 RSS 수집 (지난 24시간) ──────────────────────────────────────
# Gemini 그라운딩 검색은 옛 사건을 새 뉴스처럼 서술하는 문제가 있어(방산 봇 교훈)
# 실제 24시간 내 기사 목록을 코드로 수집해 유일한 뉴스 근거로 제공한다.
#
# 커버리지 축: 시장(미국 주택·인프라 / 유럽 / 중국 굴착기·부동산·부양 /
# 자원국 광산 capex / 신흥국) + 기업(한국 2사·글로벌 피어·중국 업체) + 정책·통상.
# Bobcat(동물)·Caterpillar(애벌레) 같은 동음이의어는 장비 문맥을 함께 요구한다.

NEWS_QUERIES = [
    # (query, hl, gl, ceid)
    # 한국 기업 — 영어권 보도 (인프라코어는 합병으로 소멸했지만 구명칭 보도 대비 키워드 유지)
    ('("Doosan Bobcat" OR "Develon" OR "HD Hyundai Construction Equipment" '
     'OR "HD Hyundai Infracore" OR ("Bobcat" AND (excavator OR loader OR "skid steer"))) when:1d',
     "en-US", "US", "US:en"),
    # 글로벌 피어
    ('(Caterpillar OR Komatsu OR "Volvo CE" OR "Volvo Construction" OR "Hitachi Construction" '
     'OR Liebherr OR JCB OR Kubota OR "CNH Industrial" OR "Wacker Neuson" OR Terex '
     'OR "Epiroc" OR "Sandvik") AND (equipment OR machinery OR excavator OR mining OR earnings) when:1d',
     "en-US", "US", "US:en"),
    # 중국 업체·중국 시장 (굴착기 판매 통계 포함)
    ('(SANY OR XCMG OR Zoomlion OR LiuGong OR "China excavator" OR "excavator sales" '
     'OR ("China" AND ("construction machinery" OR "infrastructure stimulus" '
     'OR "special bonds" OR "property market"))) when:1d', "en-US", "US", "US:en"),
    # 미국 수요 — 주택·인프라·렌탈·데이터센터
    ('("housing starts" OR "building permits" OR "homebuilder" OR "construction spending" '
     'OR "infrastructure bill" OR "infrastructure funding" OR "data center construction" '
     'OR "United Rentals" OR Ashtead OR "equipment rental") when:1d', "en-US", "US", "US:en"),
    # 자원국·광산 capex — 금광 포함 (금 가격 → 금광 투자 경로)
    ('((BHP OR "Rio Tinto" OR Vale OR Freeport OR Glencore OR "Anglo American" OR Codelco '
     'OR Barrick OR Newmont OR "Oyu Tolgoi" OR Simandou) AND (capex OR expansion OR "new mine" '
     'OR investment OR fleet OR equipment)) OR ("mining equipment") when:1d',
     "en-US", "US", "US:en"),
    # 신흥국·자원국 지역 — 인도/아세안/중동/아프리카
    ('((India AND ("construction equipment" OR excavator OR "infrastructure budget")) '
     'OR (Indonesia AND (nickel OR coal OR "mining investment")) '
     'OR (Mongolia AND (coal OR copper OR mining)) '
     'OR (("Saudi Arabia" OR NEOM OR UAE) AND (construction OR infrastructure OR "giga project"))) when:1d',
     "en-US", "US", "US:en"),
    # 유럽 수요 — 독일 인프라 기금·건설 경기
    ('(("Europe" OR "European" OR Germany OR Eurozone OR UK) AND ("construction output" '
     'OR "construction PMI" OR "housing permits" OR "infrastructure fund" '
     'OR "infrastructure investment" OR housebuilding)) OR CECE OR bauma when:1d',
     "en-GB", "GB", "GB:en"),
    # 정책·통상 — 관세(철강 232조 = 원가), 금리는 건설·주택 문맥 한정
    ('((tariff AND (machinery OR "construction equipment" OR excavator OR steel)) '
     'OR "Section 232" OR (("rate cut" OR "Federal Reserve") AND (housing OR construction '
     'OR homebuilder OR mortgage))) when:1d', "en-US", "US", "US:en"),
    # 국내 보도 — 한국 기업 + 산업
    ("HD현대건설기계 OR HD현대인프라코어 OR 두산밥캣 OR 디벨론 OR 건설기계 수출 "
     "OR 굴착기 판매 when:1d", "ko", "KR", "KR:ko"),
]


def fetch_news(now: datetime, max_items: int = 60) -> list[dict]:
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
            # 동음이의어 노이즈 1차 컷 (동물 밥캣·애벌레·대학 스포츠팀 Bobcats)
            if re.search(r"(?i)\b(bobcat (sighting|spotted|attack|kitten|rescued)"
                         r"|bobcats (beat|defeat|win|lose|fall|host)"
                         r"|caterpillars? (crawl|found|species)|butterfly|larva)\b", title):
                continue
            seen.add(key)
            items.append({"title": title, "link": link, "source": source, "pub": pub})
        time.sleep(0.5)
    items.sort(key=lambda x: x["pub"], reverse=True)
    return items[:max_items]


def news_list_text(items: list[dict]) -> str:
    lines = []
    for it in items:
        lines.append(f"- [{it['pub']:%m/%d %H:%M} KST] {it['title']} ({it['source']}) {it['link']}")
    return "\n".join(lines)


SYSTEM_PROMPT = """당신은 글로벌 건설기계(Construction Equipment) 섹터를 담당하는 증권사 리서치 어시스턴트(RA)입니다.
매일 아침 한국의 건설기계 담당 애널리스트(HD현대건설기계·두산밥캣 커버 — HD현대인프라코어는 HD현대건설기계에 흡수합병됨, 디벨론(Develon)은 존속 브랜드)에게 보내는 데일리 브리핑을 작성합니다.

[필수 원칙 — 최신성이 가장 중요합니다]
- 제공된 시세표·매크로표가 종가·등락률·시총·지표값의 확정 데이터입니다. 수치는 반드시 이 표의 값을 사용하세요.
- **뉴스 사실관계는 반드시 함께 제공되는 [지난 24시간 뉴스 목록]에 있는 기사만 근거로 쓰세요.** 목록에 없는 사건을 당신의 기억(학습 데이터)에서 꺼내 새 뉴스처럼 쓰는 것을 절대 금지합니다. 과거의 수주·실적·신제품 소식을 오늘 뉴스처럼 서술하면 안 됩니다.
- 각 이슈에는 뉴스 목록에 표기된 보도 시각(월/일)을 함께 적으세요.
- **등락 원인을 설명할 근거 기사가 목록에 없으면 원인을 지어내지 말고 "관련 공시·뉴스 미확인 (수급 요인 추정)"이라고 쓰세요.** 그럴듯한 서사를 만드는 것보다 모른다고 쓰는 것이 훨씬 낫습니다.
- **최종 리포트 본문만 출력하세요.** 계획, 사고 과정, 분석 메모, tool_code, 코드 블록 등을 절대 출력하지 마세요. 응답의 첫 글자는 반드시 서두 문장("글로벌 건설기계 업종에서...")으로 시작해야 합니다.
- 관심 이슈: 수요 지표(미국 주택착공·허가·건설지출·인프라 예산, 유럽 건설경기·독일 인프라 기금, 중국 굴착기 판매·부동산·부양책, 인도·아세안 인프라), 광산 capex(광산사 프로젝트 승인·증설·장비 발주 — 금 가격 상승→금광 투자 확대 경로 포함), 렌탈사(United Rentals·Ashtead·Herc) 실적·가동률·fleet 계획, 기업 이벤트(실적·가이던스, 수주, 신제품·전동화, 딜러망·유통 계약, 공장 투자, M&A, 구조조정), 정책·통상(인프라 법안, 철강·기계 관세, 건설·주택 관련 금리).
- 수치·계약금액·수량·일정·등락률을 우선 제시하고, 사실과 해석을 구분하세요. 확인되지 않은 보도·루머는 "[미확인]" 표시.
- **뉴스의 함의를 끝까지 해석하세요.** 특히 경쟁 구도: 중국 업체(SANY·XCMG·Zoomlion·LiuGong)의 신흥국·자원국 수주나 딜러망 확대는 같은 시장에서 경쟁하는 한국 업체(HD현대건설기계·두산밥캣)의 점유율 위협을 의미할 수 있습니다. 광산 capex 확대는 대형 굴착기·광산트럭 수요, 미국 주택 회복은 소형장비(두산밥캣) 수요로 연결하세요. 수혜 기업과 피해 기업을 모두 짚으세요.
- 뉴스 항목마다 출처 매체명과 원문 링크(목록의 URL 그대로)를 마크다운 링크로 붙이세요.
- 한국어로 간결하게 작성하되, 기업명·제품명은 공식 영문명을 병기하세요.
- 동일 뉴스 반복 금지. 주가에 실제 영향을 준 이슈 중심으로.

[출력 형식 — 반드시 이 구조를 따르세요]
0. 서두: "글로벌 건설기계 업종에서 지난 24시간 동안 발생한 주요 뉴스 및 상장 기업 동향을 정리해 드립니다. 업데이트 시간은 {UPDATE_TIME}입니다." 문장으로 시작 (시간 표기 필수)
1. ## 오늘의 핵심 요약 — 시장에 가장 중요한 이슈 3~5개를 3~5줄로
2. ## 매크로·원재료 — 매크로표의 확정값으로 금리·환율과 주요 원재료(금·은·구리·유가)의 1D 등락 및 1M/3M/12M 추세를 정리하고, 건설기계 수요 관점의 함의(금리→주택, 금·은·구리→광산 capex)를 한 줄씩. 각 지표 행은 "지표명 | 값 | 1D | 1M | 3M | 12M" 형태의 일반 텍스트 줄로. 뉴스 목록에 주택착공·굴착기 판매 등 지표 기사가 있으면 함께.
3. ## 주요 주가 동향 — 시세표의 그룹 구분(**한국 / 글로벌 대형 / 중소형 / 광산장비 / 렌탈·딜러 / 중국**)을 그대로 따라, 그룹명을 굵은 줄로 쓰고 그 아래 각 행을 "기업명 | 1D | 1M | 3M | 12M | 변동 요인" 형태의 일반 텍스트 줄로 쓰세요 (마크다운 표 문법 |---| 사용 금지). 수치는 시세표 값 그대로. 한국 그룹은 전 종목 필수, 다른 그룹은 변동폭이 크거나 뉴스가 있는 종목 위주. 변동 요인이 없으면 1M/3M/12M 추세로 짧게 코멘트.
4. ## 큰 변동 분석 — ±10% 이상 종목은 반드시 별도 표기하고 배경을 뉴스·실적·수급·정책 요인으로 구분해 구체적으로 설명. 해당 없으면 "±10% 이상 변동 종목 없음. (±5% 이상: ...)"으로 처리
5. ## 시장별 동향 — 미국(주택·인프라·렌탈) / 유럽 / 중국(굴착기·부동산·부양책) / 자원국·광산(남미·중동·아프리카·인니·몽골) / 신흥국(인도·아세안) 순으로 핵심 이슈. 이슈 없는 시장은 생략 가능
6. ## 기업 전략 동향 — 신제품·전동화 / 딜러망·유통 / 생산·공장 / M&A 관점의 기업 소식. 한국 기업 관련 함의가 있으면 반드시 명시
7. ## 투자 시사점 — 단기 촉매와 중기 업황 관점 3개 이내. HD현대건설기계·두산밥캣 관점 포함

굵은 강조는 **텍스트**, 링크는 [매체명](URL) 형식의 마크다운을 사용하세요. 마크다운 표(|---|)와 HTML 태그는 사용하지 마세요."""


REPORT_OPENER = "글로벌 건설기계 업종에서 지난 24시간"


def clean_report(text: str) -> str:
    """모델이 사고 과정·계획·tool_code를 본문 앞에 누출했을 때 최종 리포트만 남긴다."""
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


def generate_report(price_table: str, macro_table: str, news_text: str, now: datetime) -> str:
    from google import genai
    from google.genai import types as genai_types
    client = genai.Client()  # GEMINI_API_KEY 환경변수 사용
    update_time = now.strftime("%Y-%m-%d %H:00")
    system = SYSTEM_PROMPT.replace("{UPDATE_TIME}", update_time)
    user = (
        f"현재 시각(KST): {now.strftime('%Y-%m-%d %H:%M')}\n\n"
        f"[확정 매크로표] (최근 종가 기준, 등락률은 직전 거래일 대비):\n"
        f"{macro_table}\n\n"
        f"[확정 시세표] (각 시장의 최근 종가 기준, 등락률은 직전 거래일 대비):\n"
        f"{price_table}\n\n"
        f"[지난 24시간 뉴스 목록] (구글뉴스 RSS 수집 — 뉴스 사실관계는 이 목록만 근거로 사용):\n"
        f"{news_text}\n\n"
        "위 매크로표·시세표와 뉴스 목록을 바탕으로 글로벌 건설기계 데일리 브리핑을 작성해 주세요. "
        "목록에 없는 사건을 새 뉴스처럼 쓰지 마세요."
    )
    config = genai_types.GenerateContentConfig(
        system_instruction=system,
        temperature=0.3,
        max_output_tokens=16384,
    )
    # 1순위 모델(보통 pro) 실패 시 flash로 폴백 — 무료 티어 쿼터로 브리핑이 끊기지 않게
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
        raise RuntimeError("Gemini 호출 모두 실패 (pro·flash 폴백 포함)")
    print(f"[Gemini] 사용 모델: {used_model}")
    global LAST_USED_MODEL
    LAST_USED_MODEL = used_model
    report = clean_report(response.text.strip())
    um = getattr(response, "usage_metadata", None)
    if um:
        print(f"[Gemini] in={um.prompt_token_count} out={um.candidates_token_count}")
    return report


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


def send_telegram(md_report: str, now: datetime) -> None:
    """텔레그램 발송 — 시크릿 미설정이면 생략 (나중 단계)."""
    import requests
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("[텔레그램] 시크릿 미설정 — 발송 생략")
        return
    mode = os.environ.get("TELEGRAM_MODE", "summary")  # summary | full
    base_url = os.environ.get("DASHBOARD_BASE_URL",
                              "https://gschoie.github.io/GS-DB2")
    date_str = now.strftime("%Y-%m-%d")
    md_body = md_report if mode == "full" else extract_summary(md_report)
    body = to_telegram_html(md_body)
    header = f"🏗️ <b>글로벌 건설기계 데일리 브리핑</b> | {date_str}\n"
    footer = ""
    if mode != "full":
        footer = (f'\n\n📊 <a href="{base_url}/construction_daily/{date_str}.html">'
                  "전체 브리핑 보기 (주가표·시장별·투자 시사점)</a>\n"
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


# ── 대시보드 아카이브 페이지 (defense_briefing과 동일 스타일) ──────────────

PAGE_CSS = """
:root{color-scheme:dark}
body{margin:0;padding:28px 24px 60px;background:#0d1117;color:#d8dee9;
  font-family:'Pretendard','Malgun Gothic','Apple SD Gothic Neo',sans-serif;line-height:1.75;font-size:15px}
.wrap{max-width:860px;margin:0 auto}
h1{font-size:21px;color:#e8edf5;margin:0 0 4px}
.meta{color:#8b96a8;font-size:12.5px;margin-bottom:22px}
h2{font-size:16.5px;color:#ffc46b;margin:30px 0 10px;padding-bottom:6px;border-bottom:1px solid #3a3046}
a{color:#6aa8ff;text-decoration:none}a:hover{text-decoration:underline}
b,strong{color:#f0f4fa}
ul{margin:6px 0;padding-left:22px}
p{margin:8px 0}
hr{border:none;border-top:1px solid #3a3046;margin:20px 0}
table.ptab{border-collapse:collapse;width:100%;margin:12px 0;font-size:13.5px}
.ptab td{border-bottom:1px solid #1d2838;padding:7px 9px;text-align:left;vertical-align:top}
.ptab tr:first-child td{color:#8b96a8;font-size:12.5px;border-bottom:1px solid #2c3a52}
.ptab tr:hover td{background:#131a26}
.up{color:#ff6b6b;font-weight:600}
.down{color:#5b9dff;font-weight:600}
"""

PCT_RE = re.compile(r"(?<![\w.%])([+-]\d+(?:\.\d+)?%)")


def colorize(html_text: str) -> str:
    """등락률(+/-x.xx%)에 상승 빨강·하락 파랑 색상 적용 (웹페이지 전용)."""
    return PCT_RE.sub(
        lambda m: f'<span class="{"up" if m.group(1).startswith("+") else "down"}">{m.group(1)}</span>',
        html_text)


def report_to_page_html(md: str) -> str:
    """마크다운 리포트를 아카이브 페이지 본문 HTML로 변환.

    'A | B | C | D | ...' 형태(4개 열 이상)의 연속 줄은 표로 렌더링하고,
    등락률에는 색상을 입힌다.
    """
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
            out.append(f"<h2>{colorize(md_inline(m.group(2)))}</h2>")
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


def write_archive(md_report: str, now: datetime, generator: str | None = None) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    date_str = now.strftime("%Y-%m-%d")
    gen_label = generator or f"Gemini({LAST_USED_MODEL})"
    body = report_to_page_html(md_report)
    page = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>글로벌 건설기계 브리핑 {date_str}</title><style>{PAGE_CSS}</style></head>
<body><div class="wrap">
<h1>🏗️ 글로벌 건설기계 데일리 브리핑</h1>
<div class="meta">기준: {now.strftime('%Y-%m-%d %H:00')} KST · 생성: {gen_label} + 구글뉴스 RSS + yfinance 확정 시세·매크로</div>
{body}
</div></body></html>"""
    (ARCHIVE_DIR / f"{date_str}.html").write_text(page, encoding="utf-8")
    # 마크다운 원문도 보관 — 렌더러 개선 시 과거분 재생성용
    (ARCHIVE_DIR / f"{date_str}.md").write_text(md_report, encoding="utf-8")
    print(f"[아카이브] {date_str}.html 생성")
    write_index()


def write_index() -> None:
    """날짜별 아카이브 목록을 읽어 선택 UI가 있는 인덱스 페이지를 재생성한다."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dates = sorted((p.stem for p in ARCHIVE_DIR.glob("????-??-??.html")), reverse=True)
    dates_js = json.dumps(dates, ensure_ascii=False)
    index = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>글로벌 건설기계 브리핑</title><style>
{PAGE_CSS}
.bar{{display:flex;gap:10px;align-items:center;max-width:860px;margin:0 auto 14px;flex-wrap:wrap}}
.bar h1{{font-size:17px;margin:0;flex:1;min-width:200px}}
select,button{{background:#161d29;color:#d8dee9;border:1px solid #2c3a52;border-radius:8px;
  padding:7px 12px;font-size:13.5px;cursor:pointer}}
iframe{{width:100%;height:calc(100vh - 110px);border:1px solid #3a3046;border-radius:10px;background:#0d1117}}
</style></head><body>
<div class="bar">
  <h1>🏗️ 글로벌 건설기계 데일리 브리핑</h1>
  <button id="prev" title="이전 날짜">◀</button>
  <select id="dsel"></select>
  <button id="next" title="다음 날짜">▶</button>
</div>
<iframe id="frame" title="브리핑"></iframe>
<script>
const DATES={dates_js};
const sel=document.getElementById('dsel'),fr=document.getElementById('frame');
DATES.forEach(d=>{{const o=document.createElement('option');o.value=d;o.textContent=d+' ('+'일월화수목금토'[new Date(d+'T00:00:00').getDay()]+')';sel.appendChild(o)}});
function load(){{fr.src='construction_daily/'+sel.value+'.html'}}
sel.onchange=load;
document.getElementById('prev').onclick=()=>{{if(sel.selectedIndex<DATES.length-1){{sel.selectedIndex++;load()}}}};
document.getElementById('next').onclick=()=>{{if(sel.selectedIndex>0){{sel.selectedIndex--;load()}}}};
if(DATES.length)load();
else fr.srcdoc='<body style="background:#0d1117;color:#8b96a8;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">아직 생성된 브리핑이 없습니다 — 매일 아침 6시경 자동 생성됩니다.</body>';
</script></body></html>"""
    INDEX_PAGE.write_text(index, encoding="utf-8")
    print(f"[인덱스] construction_briefing_report.html 갱신 (누적 {len(dates)}일)")


def collect_data(now: datetime) -> tuple[str, str, list[dict]]:
    """시세·매크로·뉴스를 조회해 (시세표, 매크로표, 뉴스목록)을 반환한다."""
    rows = fetch_prices()
    ok = sum(1 for r in rows if r["close"] is not None)
    print(f"[시세] {ok}/{len(rows)} 종목 조회 성공")
    if ok < len(rows) * 0.5:
        raise RuntimeError("시세 조회 성공률이 50% 미만 — Yahoo 차단 가능성, 중단")
    table = price_table_text(rows)
    macro_rows = fetch_macro()
    macro_ok = sum(1 for r in macro_rows if r["close"] is not None)
    print(f"[매크로] {macro_ok}/{len(macro_rows)} 지표 조회 성공")
    macro_table = macro_table_text(macro_rows)
    news = fetch_news(now)
    print(f"[뉴스] 지난 24시간 기사 {len(news)}건 수집")
    if len(news) < 5:
        print("[경고] 뉴스 수집이 5건 미만 — RSS 차단 가능성", file=sys.stderr)
    return table, macro_table, news


def collect_only(now: datetime) -> None:
    """수집 전용 모드 — Gemini 없이 시세·매크로·뉴스만 inputs JSON으로 저장.

    Claude 세션(예약 루틴)이 이 파일을 읽어 해석·작성한다. Gemini 폴백 경로는
    이 파일을 쓰지 않고 자체 재수집한다(수집~폴백 사이 시차 반영).
    """
    table, macro_table, news = collect_data(now)
    INPUTS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = now.strftime("%Y-%m-%d")
    payload = {
        "date": date_str,
        "collected_at": now.strftime("%Y-%m-%d %H:%M KST"),
        "price_table": table,
        "macro_table": macro_table,
        "news_list": news_list_text(news),
        # 작성 세션(Claude)용 형식 안내 — SYSTEM_PROMPT의 2·3번 섹션과 동일하게 유지할 것
        "format_note": (
            "매크로·원재료 섹션: 각 지표를 '지표명 | 값 | 1D | 1M | 3M | 12M' 줄로, "
            "금·은·구리 추세의 광산 capex 함의 포함. "
            "주요 주가 동향 섹션: 시세표의 그룹([한국]/[글로벌 대형]/[중소형]/[광산장비]/"
            "[렌탈·딜러]/[중국]) 순서를 그대로 따라 그룹명을 굵은 줄로 쓰고, "
            "각 행은 '기업명 | 1D | 1M | 3M | 12M | 변동 요인' 형태로. "
            "한국 그룹은 전 종목 필수."
        ),
    }
    (INPUTS_DIR / f"{date_str}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    # 7일 초과 과거 inputs 정리 (아카이브는 md/html로 이미 남는다)
    for stale in sorted(INPUTS_DIR.glob("????-??-??.json"))[:-7]:
        stale.unlink()
    print(f"[수집] inputs/{date_str}.json 저장 (뉴스 {len(news)}건)")


def render_md(date_str: str) -> None:
    """렌더 전용 모드 — 기존 md(예: Claude 작성분)로 html+인덱스만 재생성.

    네트워크 패키지 불필요 (Claude 세션 컨테이너에서 실행 가능).
    """
    md_path = ARCHIVE_DIR / f"{date_str}.md"
    md_report = md_path.read_text(encoding="utf-8")
    when = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=6, tzinfo=KST)
    write_archive(md_report, when, generator="Claude 리서치 데스크")


def main() -> None:
    now = datetime.now(KST)
    print(f"=== 글로벌 건설기계 브리핑 시작: {now:%Y-%m-%d %H:%M} KST / model={MODEL} ===")
    table, macro_table, news = collect_data(now)
    report = generate_report(table, macro_table, news_list_text(news), now)
    write_archive(report, now)
    send_telegram(report, now)
    print("=== 완료 ===")


if __name__ == "__main__":
    if "--init" in sys.argv:  # 아카이브 인덱스만 재생성 (첫 배포용 플레이스홀더)
        write_index()
    elif "--collect-only" in sys.argv:
        collect_only(datetime.now(KST))
    elif "--render-md" in sys.argv:
        render_md(sys.argv[sys.argv.index("--render-md") + 1])
    else:
        main()
