# ChatGPT 방산 브리핑

`chatgpt-brief.yml`이 매일 KST 05:55(크론)에 Gemini 판과 같은 골격으로 돕니다 —
러너가 yfinance 확정 시세 + 구글뉴스 RSS(24h)를 수집하고, 작성만 OpenAI API
(`defense_briefing/chatgpt_briefing_bot.py`, OPENAI_API_KEY 시크릿 필요).
결과는 대시보드(`static/chatgpt_defense/`) + 방산 채널 텔레그램.

수동 입력이 자동 생성보다 우선합니다(같은 날짜 md가 있으면 API 생성 스킵):

1. 대시보드 → 🧠 글로벌방산.브리핑(GPT) 페이지의 ✍️ 붙여넣기 폼
   (폼 → GAS dispatch_proxy `gptbrief` → workflow_dispatch)
2. 이 폴더의 `inbox/YYYY-MM-DD.md`로 커밋 — 처리 후 파일은 자동 삭제됩니다.
