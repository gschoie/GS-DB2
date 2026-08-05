# 다올 리서치 톤 챗봇 (1단계)

다올리서치 텔레그램 리포트 1,190여 건을 구조화한 **DAOL-RESEARCH-TONE** 데이터
(GitHub Pages JSON, CORS 개방)에 근거해 답하는 챗봇입니다. 별도 DB 없이 Pages의
JSON을 조회하며, 로컬 캐시(기본 10분)로 재요청을 줄입니다.

## 구조

| 파일 | 역할 |
|---|---|
| `data_source.py` | `daol_tone_v2.json` / `tone_summary.json` / `ked_street.json` 로더 + TTL 캐시 |
| `tools.py` | 순수 조회 로직(기업 뷰, 섹터 톤, 오늘 브리핑, 전시장 검색) — 단위 테스트 대상 |
| `chatbot.py` | Anthropic API tool runner + 다올 톤 시스템 프롬프트 |
| `server.py` | 127.0.0.1 전용 로컬 서버 (`POST /api/chat` + 채팅 UI) |
| `static/index.html` | 단일 파일 채팅 UI |

## 실행

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:ANTHROPIC_API_KEY = "sk-ant-..."
python server.py
```

브라우저에서 <http://127.0.0.1:8788>을 엽니다.

CLI로 한 번만 물어보려면:

```powershell
python chatbot.py "최광식 조선 톤 요즘 어때?"
```

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `ANTHROPIC_API_KEY` | (필수) | Anthropic API 키 |
| `DAOL_CHATBOT_MODEL` | `claude-opus-5` | 사용할 Claude 모델 |
| `DAOL_TONE_BASE_URL` | `https://gschoie.github.io/DAOL-RESEARCH-TONE/` | 데이터 베이스 URL |
| `DAOL_CHATBOT_CACHE_TTL` | `600` | JSON 캐시 TTL(초) |
| `PORT` | `8788` | 서버 포트 |

## 챗봇이 따르는 신뢰 원칙 (핸드오프 문서 승계)

- 데이터에 없는 값은 지어내지 않음
- 위클리 자료에는 투자의견 없음 — 의견을 추정하지 않음
- 근거 문구는 리포트 원문 표현 인용
- 의견 어휘: 기업 BUY/HOLD/REDUCE · 산업 비중확대/중립/비중축소

## 테스트

```powershell
python -m unittest discover -s tests -v
```

네트워크·API 키 없이 실행됩니다(조회 로직만 검증).

## 다음 단계 후보

- 답변 스트리밍(SSE)으로 체감 속도 개선
- `daol_pdf_text_cache.json`(PDF 원문) 검색 도구 추가 — 원문 인용 강화
- 기존 리서치 데스크 대시보드(`telegram_research_dashboard`) 사이드바에 챗봇 링크 추가
