# GS Research Desk — 프로젝트 컨텍스트

개인 리서치 자동화 모노리포. 산출물은 GitHub Pages 대시보드(https://gschoie.github.io/GS-output-dashboard)로 배포되고, 수집·알림은 GitHub Actions 스케줄/디스패치로 돌아간다. 원래 PC(로컬 Claude Code)에서 개발하다가 2026-08부터 클라우드 세션으로 이관해 계속 업그레이드 중이다.

## 아키텍처 한눈에

- **대시보드**: `telegram_research_dashboard/`가 정적 사이트를 빌드(`build_static.py` → `_site/`), `deploy-pages.yml`로 GitHub Pages 배포.
- **버튼 → 실행 프록시**: 대시보드 버튼 → GAS `dispatch_proxy`(정본: `gas/dispatch_proxy.gs`) → GitHub Actions `workflow_dispatch`. 라우트: reports / news / union / consensus / flow / etf / holdings / dart / recipe.
  - GAS 수정 시 Apps Script에 붙여넣고 **'배포 관리 → 새 버전'**으로 갱신할 것. **새 배포 금지**(URL이 바뀌어 대시보드가 깨짐).
- **알림**: 텔레그램 봇들(@gs_invest_signal_bot 등). `etf_signal/etf_telegram.py`는 전송 결과를 `telegram_status.json`에 기록 → 시크릿 누락 등 실패 원인을 1회 실행으로 특정 가능.

## 모듈 맵

| 디렉터리 | 역할 |
|---|---|
| `telegram_research_dashboard/` | 메인 대시보드(뉴스·보고서·노조·오늘의요약 등) 수집 + 정적 빌드 |
| `etf_signal/` | ETF/섹터 신호 산출 + 텔레그램 발송 (`etf-signal.yml`, 정기 스캔 오전 7시) |
| `etf_holdings/` | 액티브 ETF 보유종목 변동 감지 리포트 |
| `market_flow/` | 시장 수급 스크랩 + 리포트 + 텔레그램 (평일 10:00/13:00/15:40/16:40, 하루 4회) |
| `market_trend/` | 시장관심.내러티브 — 구독 전 채널 하루치를 계량(급증 키워드·전파 수)하고 Gemini 1회로 테마 합성 + 커뮤니티 온도(네이버 종토·디시 갤러리, 순수 파이썬) (`market-trend.yml`, 매일 06:30) |
| `kospi_consensus/` | 주간 컨센서스 스냅샷 |
| `valuation/` | 야후 파이낸스 PER·PBR·ROE·PSR — 과거 4개 회계연도(확정) + 컨센(올해·내년), 화면 + 엑셀 (`valuation.yml`, 토 07:00) |
| `defense_briefing/` | 방산 데일리 브리핑 (Gemini/Claude 브리핑, `claude-brief-*.yml`) |
| `recipe_bot/` | 유튜브 숏츠 링크 → Gemini 영상 시청 → Notion 「레시피」 DB 저장 |
| `dart_shiporder_bot/` | DART 수주 공시 봇 |
| `peergroup/` | 주간 피어그룹 주가 |
| `source_watcher/` | 외부 소스 감시 |
| `gas/` | Google Apps Script 정본 (dispatch_proxy 등) |

관련 별도 리포: `gschoie/tradewinds_telegram_bot`(TradeWinds 해운뉴스, Python+Playwright, 매시 실행), family-talk-daily(이쁘게.말하기), `gschoie/GS.korea-defense-news-bot`(외신 해외 방산 뉴스 → 텔레그램. 구글뉴스 RSS 30개 피드 + Gemini 배치 채점(10건/호출), 매시 17분, 00~05시 KST 스킵).

## 운영 교훈 (반드시 지킬 것)

- **워크플로 concurrency 주의**: GitHub concurrency는 대기 run을 취소한다(대기열 1개만 유지). 수집/봇 잡에 함부로 걸면 실행이 유실됨 — deploy 잡에만 사용. recipe_bot에서도 이 함정으로 연속 입력이 취소된 적 있어 제거함.
- **텔레그램·유튜브는 GitHub 러너 IP를 간헐 차단**(스로틀·봇체크) → 재시도/폴백/Gemini 영상 직접 시청 등으로 우회.
- **뉴스 캐시**: 캐시는 뉴스DB·노조로 분리, 복원은 읽기전용·저장은 수집 run만. push 배포도 캐시 DB 사용(옛 커밋 DB로 덮어쓰는 7/8 리버트 사고의 원인이었음). 전체 재분류(rebuild)는 파서 변경 시 1회만.
- **Gemini 쿼터**: recipe_bot은 전용 키 `RECIPE_GEMINI_API_KEY`(별도 GCP 프로젝트) 사용, 모델은 `gemini-flash-lite-latest` 등 최신 별칭 우선, 429 시 65초 대기·재시도.
  무료 RPD는 **모델별·프로젝트별**이고 태평양 자정(16:00 KST) 리셋 — 시간당 도는 봇에 `gemini-2.5-flash`를 쓰면 새벽에 소진된다
  (2026-08-18 방산뉴스봇 'AI 채점 실패 발송 보류' 건 → flash-lite-latest로 교체해 해결). 상시 실행 봇은 flash-lite 계열이 기본.
- **배포 안전망(verify)**: 메뉴명 하드코딩 대신 키워드 매칭 — 메뉴 이름을 바꿔도 배포가 깨지지 않게 유지할 것.

## 작업 이력 (2026-07-09 ~ 2026-08-13, PC 시절 정리)

1. **레시피 봇 신설** (8/13): 폼 → GAS dispatch_proxy(recipe) → `recipe-bot.yml` → Gemini 영상 시청 → Notion. 쿼터 분리·모델 404·429 재시도·concurrency 함정까지 해결, 7개 레시피 저장 검증.
2. **뉴스 파이프라인 안정화**: 7/8 리버트 사고(3중 원인: 옛 DB 재배포 / concurrency 취소 / 40분+ 전체 rebuild) 해결. 날짜 기반 증분 수집(자동 3일·수동 2주). 스케줄 하루 1회 → 7회(KST 06·09·12·15·18·21·24). 전용 갱신: refresh-news / refresh-union(09:20, 21:20) / 보도기사 화면 데이터갱신 버튼.
3. **TradeWinds 봇 GAS → Python 이관**: ScreenshotOne 할당량·팝업 잔상·무한 반복 문제 → Playwright로 DOM에서 팝업 제거 후 캡쳐. 새 뉴스면 캡쳐+목록10, 변화 없으면 최근 3링크, 야간(01~05) 스킵.
4. **텔레그램 봇 교체**: ETF/섹터·액티브ETF → @gs_invest_signal_bot(도착 검증 완료). 시장.수급.동향 새 봇 설정(평일 4회). telegram_status.json 진단 인프라.
5. **오늘의 요약(overview) 개편**: 상단 4칸(글로벌방산 30% · Claude 방산 30% · GEMINI 요약 10% · 네이버 Top5 30%). defense_daily 최신 .md에서 핵심 요약 2꼭지 자동 추출. 리스트 컴팩트화(보고서 8·뉴스 10·노조 10·리서치톤 8), 뱃지 크기 통일.
6. **사이드바 메뉴 대개편**: 보고서.발간 / 뉴스.모듬 / 광.전보 w/ GEMS / 관리/모미 / 투자 / 유틸.링크 그룹. 방산브리핑(클)·더구루.원본찾기·외신 번역·Notion·AI·출입등록·레시피 등 신설. iOS: 구캘 주간 뷰 + `googlechromes://` 패턴.
7. **투자 리포트 시각 표기**: 4개 리포트에 '정기 업데이트 시각 + 실제 갱신 시각' 병기, market_flow는 슬롯별 실제 갱신 시각 표시. 텔레그램 수급 메시지에 K200선물 전 슬롯 대비 증감 추가.

## 작업 이력 (2026-08-15 ~, 클라우드 세션)

8. **밸류에이션 모듈 신설** (8/15): 야후 파이낸스로 조선·방산 26개 종목의 PER·PBR·ROE·PSR을
   과거 4개 회계연도(확정) + 컨센(올해·내년)까지 뽑아 화면 + 엑셀로 제공.
   - **야후는 2년후 컨센을 주지 않는다** — `earnings_estimate`/`revenue_estimate`에 `0y`·`+1y`뿐.
     2년후 열은 성장률 추정으로 채우지 않고 공란으로 남겼다(데이터 정직성 우선).
   - **PBR·ROE도 컨센 원본이 없다** — EPS·매출 컨센만 존재. 이익잉여금 롤포워드
     (예상자본 = 직전확정자본 + 컨센순이익 × (1−배당성향))로 자체 산출하고 화면·엑셀에 `*` 표기.
   - **통화 함정**: 야후는 영국(GBp)·이스라엘(ILA)·남아공(ZAc) 주가를 소단위로 준다.
     재무제표는 정단위(GBP)라 그대로 나누면 PER이 100배로 튄다 → 100으로 나눠 맞춤.
     주가통화≠재무통화면 배수를 버리고 경고만 남긴다.
   - 적자·자본잠식(분모 ≤ 0)은 배수를 공란 처리. 단 **ROE는 음수도 그대로 둔다**(해석 가능한 정보).
   - 야후가 개발 컨테이너에서 egress 차단(fc.yahoo.com 403)이라 실호출 검증 불가 →
     가짜 야후 응답으로 산식을 검산하는 테스트 16개를 두고 워크플로에서 매번 돌린다.

이후 작업은 git log와 이 파일을 갱신하며 이어간다.
