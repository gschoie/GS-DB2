# vacation_tracker — 친구 휴가 일정 추적

config.yml에 지정한 친구들과의 텔레그램 **1:1 대화**를 내 계정 세션(Telethon)으로 훑어
"휴가 갑니다"류 보고를 잡아 정리한다. 텔레그램 봇은 1:1 대화를 읽을 수 없어서
계정 세션이 필요하다 — source_watcher의 세션(`state/session.enc`)을 그대로 같이 쓴다.

## 흐름

1. **수집**: 친구별 대화를 마지막 메시지 id 이후만 증분으로 읽는다
   (첫 실행은 `lookback_days` 창). 내가 보낸 메시지는 기본 제외.
2. **후보 판별**: 규칙(휴가·연차·반차… 키워드, 잡담 컷)으로 후보만 남긴다.
3. **구조화**: Gemini가 `{시작일, 종료일, 종류}`로 판정한다. "내일"·"다음주 수요일"은
   메시지를 보낸 시각 기준. Gemini가 없거나 실패하면 규칙 파서(rules.py)가 폴백으로
   날짜를 읽고, 못 읽으면 needs_review로 남긴다(버리지 않는다).
4. **산출**: `state/entries.json` 누적 → `static/vacation_report.html`(대시보드
   🏖️ 친구.휴가일정) + 신규 건만 텔레그램 알림.

## 설정

- `config.yml` — 친구 이름 목록. 이름만 적으면 대화 목록의 표시 이름으로 매칭
  (성+이름, 공백 무시). 동명이인·표시명이 다르면 `username:`/`chat_id:`로 확정.
- 시크릿: `TELEGRAM_API_ID`/`HASH`, `SESSION_PASSPHRASE`(기존 것 재사용),
  `GEMINI_API_KEY`(선택), 알림은 `VACATION_TELEGRAM_BOT_TOKEN`/`CHAT_ID`
  (없으면 WATCH_* → KDEF_* 폴백).

## 실행 (워크플로 `휴가 일정 추적`, KST 08:30·18:30)

| mode | 하는 일 |
|---|---|
| probe | 친구 이름이 실제 대화로 매칭되는지만 확인 (메시지 안 읽음) |
| dry-run | 수집·추출까지만 — 상태·페이지·발송 없음 |
| run | 전체 (기본) |
| rebuild-page | entries.json만으로 페이지 재생성 |

entries.json에서 항목을 지우거나 날짜를 손으로 고친 뒤 rebuild-page를 돌리면
페이지에 그대로 반영된다(수집이 같은 메시지를 다시 넣지 않는다 — last_id 뒤라서).

## 주의

- 대시보드는 공개 주소다 — 친구 이름과 휴가 기간이 그대로 노출된다.
  리포명 리네임 운영(CLAUDE.md 11번) 정책과 같은 감수 위에서 쓰는 페이지.
- 계정 세션을 쓰는 다른 워크플로(source-watcher)와 동시 접속해도 읽기라 무방하지만,
  기기 정보(DEVICE_INFO)는 반드시 source_watcher/adapters.py 것을 import해 같이 쓴다.
