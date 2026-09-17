# 건설기계 브리핑 GPT판 — 수동 등록 inbox

ChatGPT 앱에서 만든 건설기계 브리핑을 대시보드에 올리는 보조 경로입니다.

- 기본 경로는 대시보드 `chatgpt_construction_report.html` 상단의 ✍️ 붙여넣기 폼입니다.
- 폼을 못 쓰는 환경에서는 `inbox/YYYY-MM-DD.md` 파일을 main에 커밋하세요 —
  `construction-gpt.yml`이 push를 받아 발행하고, 처리한 inbox 파일은 지웁니다.
- 파일명이 날짜 형식이 아니면 오늘(KST) 날짜로 처리됩니다.
- 수동 등록은 Claude 예약 세션의 자동(웹서치) 작성보다 우선합니다
  (같은 날짜 md가 이미 있으면 세션은 그날 자동 작성을 건너뜁니다).
