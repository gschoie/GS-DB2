# 시장관심.내러티브 — 일일 트렌드 봇

내 텔레그램 계정이 구독한 **모든 채널**의 하루치 글(전일 06:00~당일 06:00 KST)을 보고,
"어제~오늘 시장이 무슨 얘기에 몰려 있나"를 테마 3~6개로 정리한다. 매일 아침 06:30에
자동으로 돌고(`market-trend.yml`), 결과는 날짜별 md + `latest.json`으로 커밋된다.

`source_watcher`의 조선 코멘트 감시(ship_all)와 형제다 — 같은 계정 세션, 같은 수집
어댑터를 쓴다. 차이는 하나: ship_all은 **아는 키워드**가 걸린 글만 뽑지만, 여기는
**전체 글**을 보고 몰랐던 낱말의 급증까지 잡는다.

## 어떻게 뽑나 — 토큰은 딱 한 번 쓴다

| 단계 | 도구 | 하는 일 |
|---|---|---|
| A. 수집 | 파이썬(Telethon) | 구독 전 채널의 하루치 글. 광고·초단문 제거 |
| B. 계량 | 파이썬 | ① 퍼나른 중복 글을 min-hash로 접되 **몇 채널이 실었나(전파 수)**를 기록 ② 낱말·두낱말 빈도를 **최근 7일 평소 대비 배수**로 환산해 급증 감지 ③ 대표 발췌 추출 |
| C. 합성 | Gemini 1회 | B의 신호만 주고 테마 이름·내러티브·근거를 JSON으로 받는다 |

핵심 설계:

- **절대 빈도가 아니라 '평소 대비'가 트렌드다.** '시장' 같은 낱말은 매일 수백 번 나와서
  기준선 비교가 자동으로 눌러 준다. 기준선은 `state/trend_history.json`에 매일 쌓이며,
  3일 이상 쌓여야 배수가 나온다(그 전엔 빈도순 + "기준선 수집 중" 표시).
- **전파 수가 관심의 대리 지표다.** 채널 열 곳이 퍼나른 한 문단이 한 채널의 긴 글보다
  시장 관심을 잘 보여준다. 중복을 버리지 않고 세어서 신호로 쓴다.
- **LLM은 이름 붙이기만 한다.** 팩트(빈도·배수·발췌)는 전부 파이썬이 계산한 것만 넘기고,
  입력에 없는 사실을 쓰지 말라고 못 박는다. 실패하면 `--no-llm` 신호 리포트로라도 남긴다.

## 실행

```bash
pip install -r requirements.txt

python trend_daily.py                 # 수집 → 계량 → Gemini → 저장
python trend_daily.py --check         # 수집·계량 통계만 (토큰·저장 없음)
python trend_daily.py --no-llm        # Gemini 없이 계량 신호만으로 저장
python trend_daily.py --dry-run       # 저장 없이 리포트 출력만
python trend_daily.py --save-corpus corpus.jsonl   # 수집분 저장(디버깅)
python trend_daily.py --corpus corpus.jsonl        # 재수집 없이 파일로 파이프라인 재실행
```

수집에는 source_watcher와 같은 환경변수가 필요하다:
`TELEGRAM_API_ID` / `TELEGRAM_API_HASH` / `TELEGRAM_SESSION_STRING`(또는 세션 파일).
합성에는 `GEMINI_API_KEY`(선택: `GEMINI_MODEL`, 기본 gemini-2.5-flash, 실패 시
flash-lite 폴백).

## 산출물과 소비처

| 경로 | 내용 |
|---|---|
| `…/static/market_trend/<날짜>.md` | 사람이 읽는 아카이브(테마 + 부록 계량 신호) |
| `…/static/market_trend/<날짜>.json` | 날짜별 구조화 데이터 — `build_report.py`가 읽는다 |
| `…/static/market_trend/latest.json` | 최신본 — `telegram_send.py`가 읽는다 |
| `…/static/market_trend_report.html` | 대시보드 '투자 > 시장관심.내러티브'가 iframe으로 띄우는 페이지 (`build_report.py` 산출, 날짜 네비게이션) |
| `state/trend_history.json` | 일별 낱말 빈도 이력(기준선). 워크플로가 커밋. 손대지 말 것 |
| `telegram_status.json` | 마지막 발송 결과 — 시크릿 누락 등 실패 원인을 1회 실행으로 특정 |

## 텔레그램 발송

`telegram_send.py`가 latest.json을 읽어 테마 요약을 보낸다. 산출 날짜가 오늘(KST)이
아니면 옛 리포트를 다시 쏘지 않도록 스스로 생략한다. 봇은 시크릿으로 정한다:

| 시크릿 | 역할 |
|---|---|
| `TREND_TELEGRAM_BOT_TOKEN` / `TREND_TELEGRAM_CHAT_ID` | 전용 봇 (권장, 없어도 동작) |
| (미등록 시) `WATCH_TELEGRAM_*` → `KDEF_TELEGRAM_*` | 소스 감시 봇 → 방산 봇 순 폴백 |

```bash
python telegram_send.py --dry-run   # 무엇이 나갈지 출력만
```

## 대시보드 갱신 버튼

'🔄 트렌드 갱신' 버튼은 GAS dispatch_proxy의 `trend` 라우트로 이 워크플로를 부른다.
**GAS 정본(`gas/dispatch_proxy.gs`)에 라우트가 추가되어 있으므로, Apps Script 편집기에
붙여넣고 '배포 관리 → 새 버전'으로 갱신해야 버튼이 동작한다** (새 배포 금지 — URL이 바뀐다).

## 튜닝은 config.yml 한 곳에서

- 소음 낱말이 상위에 뜨면 → `stopwords`에 추가
- 같은 회사가 여러 표기로 흩어지면 → `aliases`에 묶기 (조선·방산 목록은
  `source_watcher/sources.yml`의 x_ship_keywords 복사본 — 그쪽을 고치면 여기도 맞출 것)
- 광고 글이 섞여 들면 → `ad_patterns`에 확실한 문구만 추가
- 잡담방을 빼려면 → `exclude_chats`

## 테스트

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

네트워크·LLM 없이 돈다. config.yml 파싱도 함께 검사하므로 설정 오타는 수집 전에 걸린다.

## 파일

| 파일 | 하는 일 |
|---|---|
| `trend_daily.py` | 수집 → 계량 → Gemini 합성 → md/json 산출 |
| `build_report.py` | 날짜별 json → 대시보드용 단일 HTML |
| `telegram_send.py` | latest.json → 텔레그램 발송 + 상태 기록 |
| `config.yml` | 불용어·별칭·광고필터 — 평소 튜닝하는 유일한 파일 |
