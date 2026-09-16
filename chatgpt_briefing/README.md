# ChatGPT 방산 브리핑 입력함

ChatGPT가 만든 방산 브리핑 마크다운을 `inbox/YYYY-MM-DD.md` 이름으로 커밋하면
`chatgpt-brief.yml` 워크플로가 대시보드 페이지(chatgpt_defense)를 만들고
방산 채널 텔레그램으로 발송한 뒤 inbox 파일을 지웁니다.

기본 경로는 대시보드 → 🧠 글로벌방산.브리핑(GPT) 페이지의 ✍️ 붙여넣기 폼입니다
(폼 → GAS dispatch_proxy `gptbrief` → workflow_dispatch). 이 폴더는 폼을 쓸 수 없는
환경(모바일 GitHub 등)을 위한 보조 경로입니다.
