#!/usr/bin/env python3
"""방산 브리핑 RSS판(3탄) 봇 — 수집은 러너, 작성은 Claude 예약 세션.

chatgpt-brief.yml 의 단일 진입점. 우선순위:
  1. CONTENT 환경변수(대시보드 붙여넣기 폼) 또는 chatgpt_briefing/inbox/*.md 가 있으면
     → gpt_brief_publish.ingest() 로 그 본문을 발행 (수동 등록 = ChatGPT 앱 산출물, 항상 우선)
  2. 둘 다 없으면(스케줄 실행) → **수집만** 한다: defense_briefing_bot 의 yfinance 확정
     시세 + 구글뉴스 RSS(24h)를 chatgpt_briefing/inputs/<날짜>.json 으로 남기고 끝.
     작성은 Claude 예약 세션이 매일 아침 그 inputs 를 근거로 수행한다(건설기계와 동일 구조
     — OpenAI API는 유료라 쓰지 않기로 함, 2026-09-17).
     · 과거 OpenAI API 작성 경로는 --api 플래그로만 남겨둔다(OPENAI_API_KEY 등록 시 사용 가능).

Gemini 판과 동일하게 "숫자는 코드로 확정, 뉴스 근거는 RSS 목록만" 원칙을 지킨다
(LLM 웹검색·기억은 옛 사건을 새 뉴스처럼 서술하는 사고의 원인 — 07/30·08/01 실증).

텔레그램 발송: 수동 발행은 워크플로의 --send-processed 스텝이, 세션 작성분은
claude-brief-ingest 가 main 반영 후 담당한다.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import gpt_brief_publish as pub  # 아카이브·인덱스·processed 기록 (표준 라이브러리만)

KST = ZoneInfo("Asia/Seoul")

# 모델은 환경변수로 교체 가능. 기본 후보를 순서대로 시도한다(404·거절 시 다음으로).
DEFAULT_MODELS = ["gpt-5", "gpt-5-mini", "gpt-4o"]


def has_manual_input() -> bool:
    if os.environ.get("CONTENT", "").strip():
        return True
    if pub.INBOX_DIR.is_dir():
        for f in pub.INBOX_DIR.glob("*.md"):
            if not f.name.lower().startswith("readme"):
                return True
    return False


def generate_via_openai(price_table: str, news_text: str, now: datetime) -> str:
    """defense_briefing_bot 의 SYSTEM_PROMPT·데이터를 그대로 쓰되 호출만 OpenAI로."""
    import requests
    import defense_briefing_bot as gb  # yfinance·genai 의존 — API 생성 경로에서만 임포트

    api_key = os.environ["OPENAI_API_KEY"]
    update_time = now.strftime("%Y-%m-%d %H:00")
    system = gb.SYSTEM_PROMPT.replace("{UPDATE_TIME}", update_time)
    user = (
        f"현재 시각(KST): {now.strftime('%Y-%m-%d %H:%M')}\n\n"
        f"[확정 시세표] (각 시장의 최근 종가 기준, 등락률은 직전 거래일 대비):\n"
        f"{price_table}\n\n"
        f"[지난 24시간 뉴스 목록] (구글뉴스 RSS 수집 — 뉴스 사실관계는 이 목록만 근거로 사용):\n"
        f"{news_text}\n\n"
        "위 시세표와 뉴스 목록을 바탕으로 글로벌 방산 데일리 브리핑을 작성해 주세요. "
        "목록에 없는 사건을 새 뉴스처럼 쓰지 마세요."
    )
    env_model = os.environ.get("OPENAI_MODEL", "").strip()
    models = list(dict.fromkeys(([env_model] if env_model else []) + DEFAULT_MODELS))
    # 파라미터는 최소로 — temperature·max_tokens 는 모델 세대에 따라 이름·허용값이
    # 달라 400을 부른다. 모델 기본값에 맡긴다.
    for model in models:
        for attempt in range(2):
            try:
                resp = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"model": model,
                          "messages": [{"role": "system", "content": system},
                                       {"role": "user", "content": user}]},
                    timeout=300,
                )
                if resp.status_code == 404:  # 모델 없음 — 재시도 없이 다음 모델로
                    print(f"[OpenAI:{model}] 404 모델 없음 → 다음 후보", file=sys.stderr)
                    break
                resp.raise_for_status()
                data = resp.json()
                text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
                if text.strip():
                    usage = data.get("usage", {})
                    print(f"[OpenAI] 사용 모델: {model} "
                          f"(in={usage.get('prompt_tokens')} out={usage.get('completion_tokens')})")
                    return gb.clean_report(text.strip())
                print(f"[OpenAI:{model}] 빈 응답 (시도 {attempt + 1})", file=sys.stderr)
            except Exception as e:
                print(f"[OpenAI:{model} 오류] 시도 {attempt + 1}: {e}", file=sys.stderr)
            time.sleep(20 * (attempt + 1))
    raise RuntimeError(f"OpenAI 호출 모두 실패 (시도 모델: {', '.join(models)})")


def api_generate(force: bool = False) -> None:
    now = datetime.now(KST)
    date_str = now.strftime("%Y-%m-%d")
    md_path = pub.ARCHIVE_DIR / f"{date_str}.md"
    if md_path.exists() and not force:
        print(f"[스킵] chatgpt_defense/{date_str}.md 이미 존재 (수동 등록분 보호 — --force로 재생성)")
        pub.PROCESSED.write_text("[]", encoding="utf-8")
        return
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        print("[스킵] OPENAI_API_KEY 미설정 — API 생성 건너뜀 (붙여넣기 경로는 그대로 동작)")
        pub.PROCESSED.write_text("[]", encoding="utf-8")
        return

    import defense_briefing_bot as gb

    print(f"=== ChatGPT 방산 브리핑 시작: {now:%Y-%m-%d %H:%M} KST ===")
    rows = gb.fetch_prices()
    ok = sum(1 for r in rows if r["close"] is not None)
    print(f"[시세] {ok}/{len(rows)} 종목 조회 성공")
    if ok < len(rows) * 0.5:
        raise RuntimeError("시세 조회 성공률이 50% 미만 — Yahoo 차단 가능성, 중단")
    news = gb.fetch_news(now)
    print(f"[뉴스] 지난 24시간 기사 {len(news)}건 수집")
    if len(news) < 5:
        print("[경고] 뉴스 수집이 5건 미만 — RSS 차단 가능성", file=sys.stderr)

    report = generate_via_openai(gb.price_table_text(rows), gb.news_list_text(news), now)
    pub.ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    md_path.write_text(report + "\n", encoding="utf-8")
    pub.write_archive(date_str)
    pub.write_index()
    pub.PROCESSED.write_text(json.dumps([date_str]), encoding="utf-8")
    print("=== 생성 완료 (텔레그램은 다음 스텝의 --send-processed) ===")


INPUTS_DIR = pub.REPO / "chatgpt_briefing" / "inputs"
INPUTS_KEEP_DAYS = 7

FORMAT_NOTE = (
    "작성 규칙: 뉴스 사실관계는 news_list의 기사만 근거(목록에 없는 사건 금지, 각 항목에 "
    "[매체명](URL) 링크와 보도 시각), 주가·등락률·시총은 price_table 값만 사용. "
    "섹션은 claude_defense와 동일 — 서두 고정문 + ## 오늘의 핵심 요약 / ## 주요 주가 동향"
    "(기업 | 국가 | 기준일 | 등락률 | 시가총액 | 변동 요인) / ## 큰 변동 분석 / ## 섹터별 정리 / "
    "## 투자 시사점 / ## 향후 24~72시간 관전 포인트. 등락 원인 기사가 없으면 "
    "'관련 공시·뉴스 미확인 (수급 요인 추정)'로 쓴다."
)


def collect_only() -> None:
    """스케줄 실행: 시세·뉴스만 수집해 inputs JSON으로 남긴다 (작성은 Claude 세션)."""
    import defense_briefing_bot as gb

    now = datetime.now(KST)
    date_str = now.strftime("%Y-%m-%d")
    print(f"=== RSS판 수집 시작: {now:%Y-%m-%d %H:%M} KST ===")
    rows = gb.fetch_prices()
    ok = sum(1 for r in rows if r["close"] is not None)
    print(f"[시세] {ok}/{len(rows)} 종목 조회 성공")
    if ok < len(rows) * 0.5:
        raise RuntimeError("시세 조회 성공률이 50% 미만 — Yahoo 차단 가능성, 중단")
    news = gb.fetch_news(now)
    print(f"[뉴스] 지난 24시간 기사 {len(news)}건 수집")
    if len(news) < 5:
        print("[경고] 뉴스 수집이 5건 미만 — RSS 차단 가능성", file=sys.stderr)

    INPUTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": date_str,
        "collected_at": now.strftime("%Y-%m-%d %H:%M KST"),
        "price_table": gb.price_table_text(rows),
        "news_list": gb.news_list_text(news),
        "format_note": FORMAT_NOTE,
    }
    (INPUTS_DIR / f"{date_str}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[수집] chatgpt_briefing/inputs/{date_str}.json 저장")
    # 오래된 inputs 정리 (7일 보관 — construction_briefing과 동일 정책)
    from datetime import timedelta
    cutoff = (now - timedelta(days=INPUTS_KEEP_DAYS)).strftime("%Y-%m-%d")
    for f in sorted(INPUTS_DIR.glob("????-??-??.json")):
        if f.stem < cutoff:
            f.unlink()
            print(f"[정리] inputs/{f.name} 삭제 ({INPUTS_KEEP_DAYS}일 경과)")
    pub.PROCESSED.write_text("[]", encoding="utf-8")  # 이 실행은 발송 없음


def main() -> None:
    if has_manual_input():
        print("[모드] 수동 입력(폼/inbox) 발행")
        pub.ingest()
        return
    if "--api" in sys.argv:  # 유료 OpenAI 경로 — 키 등록 시에만 명시적으로
        api_generate(force="--force" in sys.argv)
        return
    collect_only()


if __name__ == "__main__":
    main()
