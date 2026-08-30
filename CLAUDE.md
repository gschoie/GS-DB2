# GS Research Desk — 프로젝트 컨텍스트

개인 리서치 자동화 모노리포. 산출물은 GitHub Pages 대시보드(https://gschoie.github.io/GS-DB2 — 2026-08-23 리포명 GS-output-dashboard→GS-DB2, 주소 노출 시 리네임으로 주소를 갈아타는 운영)로 배포되고, 수집·알림은 GitHub Actions 스케줄/디스패치로 돌아간다. 원래 PC(로컬 Claude Code)에서 개발하다가 2026-08부터 클라우드 세션으로 이관해 계속 업그레이드 중이다.

## 아키텍처 한눈에

- **대시보드**: `telegram_research_dashboard/`가 정적 사이트를 빌드(`build_static.py` → `_site/`), 워크플로 5종(deploy-pages·refresh-news/union/macro/reports)이 **GitHub Pages로 배포**. 접속 주소는 https://gschoie.github.io/GS-DB2 (공개, 리포명 변경으로 주소 교체 가능). Cloudflare Pages+Access 이관(8/18)은 로그인 번거로움으로 **8/23 원복** — CF 프로젝트·시크릿은 남아있으나 미사용.
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
| `youtube_digest/` | 방산 유튜브 3일 모음 — GAS가 모은 링크를 받아 대시보드 페이지로 굽는다 |
| `recipe_bot/` | 유튜브 숏츠 링크 → Gemini 영상 시청 → Notion 「레시피」 DB 저장 |
| `dart_shiporder_bot/` | DART 수주 공시 봇 |
| `peergroup/` | 주간 피어그룹 주가 |
| `source_watcher/` | 외부 소스 감시 |
| `vacation_tracker/` | 친구 휴가 일정 추적 — 지정 친구와의 텔레그램 1:1 대화에서 휴가 보고를 잡아 정리 |
| `gas/` | Google Apps Script 정본 (dispatch_proxy 등) |

관련 별도 리포: `gschoie/tradewinds_telegram_bot`(TradeWinds 해운뉴스, Python+Playwright, 매시 실행), family-talk-daily(이쁘게.말하기).

## 운영 교훈 (반드시 지킬 것)

- **워크플로 concurrency 주의**: GitHub concurrency는 대기 run을 취소한다(대기열 1개만 유지). 수집/봇 잡에 함부로 걸면 실행이 유실됨 — deploy 잡에만 사용. recipe_bot에서도 이 함정으로 연속 입력이 취소된 적 있어 제거함.
- **텔레그램·유튜브는 GitHub 러너 IP를 간헐 차단**(스로틀·봇체크) → 재시도/폴백/Gemini 영상 직접 시청 등으로 우회.
- **뉴스 캐시**: 캐시는 뉴스DB·노조로 분리, 복원은 읽기전용·저장은 수집 run만. push 배포도 캐시 DB 사용(옛 커밋 DB로 덮어쓰는 7/8 리버트 사고의 원인이었음). 전체 재분류(rebuild)는 파서 변경 시 1회만.
- **Gemini 쿼터**: recipe_bot은 전용 키 `RECIPE_GEMINI_API_KEY`(별도 GCP 프로젝트) 사용, 모델은 `gemini-flash-lite-latest` 등 최신 별칭 우선, 429 시 65초 대기·재시도.
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

9. **대시보드 로그인 벽 — Cloudflare Pages + Access 이관** (8/18): "주소만 알면 다 보이는" 문제 해결.
   - GitHub Pages는 로그인 제한 불가(Enterprise 전용)·repo private 전환은 Actions 무료 무제한 상실 →
     repo는 public 유지, 사이트만 Cloudflare로 이관.
   - 워크플로 5종의 Pages 배포(artifact + deploy 잡)를 `wrangler pages deploy` 단일 스텝으로 교체.
   - `build_static.previous_payload()`(캐시 유실 안전망)는 배포본을 fetch하므로 Access 서비스 토큰
     헤더 지원 추가 — 토큰 미설정 시 빈 dict 폴백으로 빌드는 계속된다.
   - 텔레그램 봇 링크 6곳(etf·flow·trend·holdings·defense×2) pages.dev로 교체, 사이드바 절대링크 2곳 상대경로화.
   - DAOL-RESEARCH-TONE(별도 리포의 Pages)은 여전히 공개 — 필요 시 같은 방식으로 이관.

10. **글로벌 건설기계 브리핑 신설** (8/20): `construction_briefing/` — defense_briefing과 동일
    골격(yfinance 확정 시세 + 구글뉴스 RSS 24h + Gemini 작성)의 건설기계 버전.
    - 유니버스 31종목: 한국 3사(HD현대건설기계·HD현대인프라코어·두산밥캣) + 미·유럽·일본·중국·
      인도 피어 + 렌탈(URI·Ashtead·Herc) + CAT 딜러(Finning·Toromont) + PAVE ETF.
      매크로 6종(미국채10y·금·구리·WTI·원달러·위안달러)도 코드로 확정 조회.
    - 뉴스 쿼리 축: 미국 주택·인프라·렌탈 / 유럽·독일 인프라기금 / 중국 굴착기 판매·부양책 /
      광산 capex(금광 포함 — 금 가격→금광 투자 경로) / 인도·아세안·중동 / 관세·금리 / 한국어 피드.
      Bobcat(동물·대학팀)·Caterpillar(애벌레) 동음이의어는 제목 프리필터로 컷.
    - `construction-briefing.yml` 매일 UTC 21:10(KST 06:10) — 방산(20:40)과 30분 오프셋으로
      Gemini 분당 한도 충돌 회피. 키는 `CONSTRUCTION_GEMINI_API_KEY || GEMINI_API_KEY` 폴백.
    - 산출물: `static/construction_daily/<날짜>.html|.md` + `construction_briefing_report.html`
      (날짜 선택 인덱스). 사이드바 `🏗️ 글로벌건설기계.브리핑` 뷰 추가, deploy-pages workflow_run
      연결, build_static 복사 추가. 텔레그램은 `CONSTRUCTION_TELEGRAM_*` 시크릿 설정 시에만 발송.

11. **Cloudflare 이관 원복** (8/23): Access 로그인(OTP)이 일상 사용에 번거로워 GitHub Pages로 복귀.
    - 워크플로 5종 wrangler 스텝 → Pages artifact+deploy 잡 복원(configure-pages `enablement: true`로
      Unpublish 상태에서도 자동 재개설). 텔레그램 링크 7곳·안전망 fetch 주소 github.io로 원복.
    - cf-access-public-reports.yml(리포트 공개 예외) 삭제. 톤 딥링크·새창 래퍼·동기화 가드는 유지.
    - 후속 과제: "대시보드 이름(주소)을 주기적으로 바꾸는" 접근차단 방식 설계 — repo rename은
      GAS dispatch_proxy·텔레그램 링크와 연동 필요.

12. **방산 주간 정리 신설** (8/24): `defense_briefing/weekly_defense_bot.py` — 매주 토 KST 11:50
    (`defense-weekly.yml`, UTC 02:50 토). 지난 7일 데일리 브리핑 2종(defense_daily·claude_defense)
    md 원문 + yfinance **주간**(5거래일) 확정 시세를 Gemini(pro→flash 폴백)에 넘겨 주간 정리본 작성.
    - 구조: 주간 핵심 테마 / 계약·수주·프로그램 / 주간 주가 리뷰 / 정책·지정학 / 한국 방산 종합 /
      다음 주 관전 포인트. 일간 브리핑에 없는 사건 금지, 두 판 상충 시 [상충] 병기.
    - 산출물: `static/defense_weekly/<토요일>.html|.md` + `defense_weekly_report.html`(날짜 인덱스)
      + **`defense_weekly/last4weeks.md|.html`** — 최근 4주 묶음. 월간 세미나 인포그래픽
      (Gemini·NotebookLM) 소스용: NotebookLM에는 .md 업로드, PDF 필요 시 last4weeks.html에서 인쇄.
    - 사이드바 `🗓️ ┗방산.주간정리(토)` 뷰, build_static 복사, deploy-pages workflow_run 연결.

13. **건설기계 주간 정리 + 방산 주간 텔레 발송** (8/24): `construction_briefing/weekly_construction_bot.py`
    — 방산 주간과 동일 골격, 매주 토 KST 12:10(`construction-weekly.yml`, 방산 주간 11:50과 20분
    오프셋). 소스는 construction_daily 7일치 + 주간 시세·매크로(yfinance). 산출물
    `static/construction_weekly/` + `construction_weekly_report.html` + last4weeks 묶음
    (다운로드명 GLOBAL_CONSTRUCTION_YYMMDD.md). 사이드바 `🗓️ ┗건설기계.주간정리(토)`.
    텔레그램은 CONSTRUCTION_TELEGRAM_* 시크릿 설정 시에만 (현재 미설정 = 대시보드 전용).
    방산 주간(weekly_defense_bot)에는 일간과 같은 채널(KDEF_TELEGRAM_*)로 요약+링크 발송 추가.

14. **건설기계 브리핑 작성 주체를 Gemini → Claude로 전환** (8/25): Gemini 무료 티어에서
    pro 쿼터가 0이 되고 flash 503으로 아침 브리핑이 처음 결측된 것을 계기로,
    "수집은 러너, 해석·작성은 Claude 예약 세션" 구조로 개편.
    - `construction-briefing.yml` 2단 스케줄: 06:10 KST 수집 전용(`--collect-only` →
      `construction_briefing/inputs/<날짜>.json`, 7일 보관) / 07:40 KST Gemini 폴백
      (오늘 md가 이미 있으면 무동작; 모델 gemini-flash-latest).
    - 봇에 `--collect-only`·`--render-md <날짜>` 모드 추가, yfinance·genai·requests는
      지연 import(렌더 모드는 세션 컨테이너에서 네트워크 패키지 없이 실행).
    - claude-brief-ingest가 건설기계 파일도 main으로 나른다. 텔레그램 발송 가드는
      `claude_defense/*.md` 변경으로 한정(건설기계만 바뀐 커밋에 방산 요약 중복 발송 방지).
    - **세션 규율**: 브리핑 push 전 반드시 origin/main 머지 — 폴백이 main에 직접 쓴 날
      브랜치의 구본이 main을 되덮는 사고 방지.

15. **코스피200 컨센 추적 — 분기 시점 자동 전환 + 4개 시계 개편** (8/25): "아직도 2Q26" 문제 해결.
    - 수집: `fetch_quarter`(첫 E분기 1개)→`fetch_quarters`(네이버가 주는 **E분기 전부** 저장).
      기존엔 종목당 1개 분기만 저장 — 3Q26은 네이버가 반기보고서를 반영해 첫 E가 넘어간
      종목(8/24 기준 128개)만 수집되고 있었고, 2Q·3Q를 동시에 가진 종목은 없었다.
    - 화면 상단 4개 시계: **당분기 / 다음분기 / 올해E / 내년E** (연간 연도 하드코딩 제거, 스냅샷 연도 자동).
    - 당분기 앵커 **자동 전환**: 법정 보고서 마감(분기말+45일, 4Q는 90일) 경과 시 다음 분기로.
      반기 마감 8/14 경과 → 지금 기준 당분기=3Q26. 수동 이동은 화면 `분기 시점 ◀▶` 버튼
      (localStorage 저장, `↺ 자동으로` 복귀) — GAS·워크플로 변경 없이 클라이언트에서 처리.
    - 다음분기(4Q26 등) 데이터가 아직 없으면 "다음 스냅샷부터 수집" 안내. 엑셀도
      당분기·다음분기 + 올해~내후년E 동적 구성.

15. **건기 브리핑 시세·매크로 확장** (8/26): 주가표를 그룹(한국/글로벌 대형/중소형/광산장비/
    렌탈·딜러/중국/ETF)으로 구분하고 1D 외 1M/3M/12M 수익률(거래일 21/63/252 오프셋,
    yfinance 400d 조회) 추가. 매크로표에 은(SI=F) 추가 + 동일 4개 구간 표기.
    출력 형식은 SYSTEM_PROMPT(2·3번 섹션)와 inputs JSON의 format_note(Claude 작성 세션용)
    양쪽에 반영 — 두 곳을 항상 같이 고칠 것.

16. **섹션 캡쳐봇 10분 회전 + Actions 쿼터 사태 + 봇 리포 public 전환** (8/24~26):
    매크로(Macro_Section_Get)·산업(industry-section-newportal) 텔레 캡쳐봇을 "6개 한꺼번에" →
    "10분에 1개씩"으로 개편하던 중 겪은 일들.
    - **Actions 무료 2,000분/월은 private 리포 계정 합산** — 산업봇 `*/10`(월 ~1,800분)이 한도를
      소진, 8/24 13:59 UTC부터 모든 private 리포 run이 3~4초 즉사(러너 미배정·로그 404).
      해결: **이쁘게.말하기(family-talk-daily)만 private 유지, 봇 리포 전부 public 전환**
      (public = 러너 무제한). 전환 전 파일+전체 git 히스토리 시크릿 스캔 완료(전부 클린).
    - **GitHub 크론은 10분 간격 틱을 대부분 유실** (무료 러너 스로틀 실측: 슬롯당 6틱 중
      1~2틱만, 발화 간격 30~55분). 크론 재등록 강제(무해 커밋)로도 동일 → 크론으로는
      10분 간격 불가 판정.
    - **매크로봇 최종 구조 = `--serve-slot`**: 슬롯(KST 07:00/10:30/15:00/21:00) 시작 틱 1개
      + 폴백 틱 1개(+20분, 90분 중복 가드로 필터)만 받고, **잡 안에서 sleep으로 10분 간격**
      순차 발송(헤더 `====== 날짜 시각 업데이트입니다 ======` → 네이버 경제 → 네이버 국제 →
      인포맥스 → 연합 → 매경 → 한경). 잡 ~55분, timeout 75분 — public이라 비용 0.
    - 산업봇은 `*/10` 회전 유지(포인터 방식이라 틱 유실 허용): 실제 ~35분 간격 발화,
      6개 한 바퀴 ~3시간. 존재하지 않는 스크립트를 돌리던 고장 워크플로(하루 9회 실패)는 삭제.
    - 방산뉴스봇(GS.korea-defense-news-bot)·GLOBAL_DEFENCE_NEW·ecos-fx-rates도 public 전환으로 재가동.

17. **크론 정시성 — GAS 시계로 이관** (8/29): GitHub 무료 러너의 `schedule` 큐가
    실측으로 market-trend 평소 +19분, **8/27 +3시간 26분(09:56 도착), 8/28 +8시간 1분
    (14:31 도착)**까지 밀려 아침 리포트가 점심에 오던 문제. 크론을 앞당겨도 해결 불가라
    시간에 민감한 5종을 **기존 Apps Script 프로젝트의 5분 트리거**로 옮겼다.
    - `gas/dispatch_proxy.gs`에 스케줄러 추가: `SCHEDULE` 표(KST 시각·요일) +
      `tick()`(5분마다) + `installScheduler()`. doPost의 발사 로직은 `fireWorkflow()`로
      추출해 웹앱(버튼)과 스케줄러가 같이 쓴다. GH_TOKEN·WF 매핑 재사용 — 새 인프라 0.
    - 슬롯: trend 06:30 · etf 07:00 · flow 10:00/13:00/15:40/16:40(평일) ·
      holdings 매시 :17(평일 09~21) · consensus 금 17:00. 발사 기록은 스크립트 속성
      `FIRED`에 날짜로 남겨 하루 1회만, 실패 시 GRACE_MIN(60분) 안에서 자동 재시도.
    - **GitHub 크론은 지우지 않고 안전망으로 유지** — 5종 워크플로에 `guard` 잡을 넣어
      "최근 dispatch 실행이 있으면 schedule 실행을 스킵"(fail-open: 가드가 죽으면 그냥 실행).
      창은 trend·etf·consensus 600분, holdings 45분, **market-flow는 분 단위 창 대신
      슬롯 경계(11:30/14:30/16:10, scrape.decide_slot과 동일)** — 몇 시간 늦은 크론이
      다음 슬롯을 덮어써 수급 텔레그램이 두 번 가는 것을 막기 위함.
    - 사용자 설치: Apps Script에 붙여넣기 → `installScheduler` 1회 실행 → 트리거 확인.

18. **방산 유튜브 3일 모음** (8/28): 구독 방산 채널 7곳(샤를세환·KKMD·까치살모·슈퍼소닉·
    밀덕·KFN+·KFN1)의 영상 링크를 3일마다 모아 텔레그램(@gs_analyst_bot) + 대시보드로.
    NotebookLM에 소스로 넣어 오디오 개요로 듣는 용도다.
    - **수집은 GAS가 이미 하고 있었다** — `gas/youtube_defense_bot.gs`(이 리포에 정본 편입).
      낱개 알림(제미나이 요약)을 보낼 때 링크를 스크립트 속성에 한 건씩 적립하고,
      3일 트리거가 그걸 모아 두 통으로 보낸다: 제목 목록 + **주소만**(붙여넣기용).
      속성 값 하나당 9KB 제한이 있어 JSON 배열 하나가 아니라 영상당 속성 하나로 둔다.
    - **대시보드**: GAS가 같은 내용을 `youtube-digest.yml` workflow_dispatch 입력으로
      넘기면 `youtube_digest/build_digest_page.py`가 `static/youtube_digest/<날짜>.html|.md|.txt`
      + 날짜 인덱스를 굽고 커밋 → deploy-pages가 workflow_run으로 받아 배포.
      **유튜브를 다시 긁지 않으므로 봇에 나간 것과 대시보드가 항상 일치한다.**
      사이드바 `📺 ┗방산유튜브.3일모음`(방산.주간정리 바로 밑), 페이지에 '전체 복사' 버튼.
    - 왜 GitHub Actions로 수집하지 않았나: 채널 목록이 GAS·리포 두 곳으로 갈려 어긋나고,
      17번에서 확인했듯 무료 러너 크론이 몇 시간씩 밀린다. 수집은 GAS 한 곳으로 유지.
    - **쇼츠는 모음에서 뺀다**(`DIGEST_SKIP_SHORTS`). 첫 회차 실측이 32건 중 16건이
      쇼츠였는데, 쇼츠는 자막이 거의 없어 NotebookLM이 소스로 받지 못하고 무료 플랜
      소스 상한(50개)만 잡아먹는다. 낱개 알림에는 영향 없다 — 쇼츠도 그대로 온다.
      피드가 쇼츠를 `/shorts/<id>` 주소로 주는 것에 기대는 최선의 추정이다.
      담는 주소는 `watch?v=`로 정규화한다(같은 영상, NotebookLM 호환).
    - GAS 쪽 고친 것: 키를 소스에서 빼 스크립트 속성으로(`secret_()`), 내부 함수는
      밑줄 접미사로 실행 드롭다운에서 감춤, 기록해 둔 영상이 피드에서 사라지면
      피드 15건이 통째로 나가고 제미나이도 15번 호출되던 문제에 상한(5건).
    - 사용자 설치: 스크립트 속성 `TELEGRAM_TOKEN`·`TELEGRAM_CHAT_ID`·`GEMINI_API_KEY`
      (+대시보드까지 쓰려면 `GH_TOKEN`) → `checkSetup()` → `installDigestTrigger()`.
      `fillBufferFromFeeds(3)`로 3일 안 기다리고 바로 시험해 볼 수 있다.

19. **친구 휴가 일정 추적 신설** (8/30): `vacation_tracker/` — config.yml에 지정한 친구 16명과의
    텔레그램 1:1 대화에서 휴가·연차·반차·출장·샵투어 보고를 잡아 정리 (`vacation-tracker.yml`, KST 08:30·18:30).
    - **봇은 1:1 대화를 못 읽는다** → source_watcher의 계정 세션(state/session.enc +
      SESSION_PASSPHRASE, telegram-login.yml)을 그대로 공유. DEVICE_INFO도 adapters에서 import
      (기기 정보가 다르면 텔레그램이 세션을 끊는다).
    - 친구 매칭은 대화 목록 표시 이름(성+이름, 공백 무시)으로 — username 몰라도 됨.
      확인은 mode=probe(메시지 안 읽음). 수집은 대화별 last_id 증분, 내 메시지 기본 제외.
    - 추출 2단: 규칙 프리필터(키워드+잡담 컷) → Gemini 구조화(상대 날짜는 메시지 시각 기준).
      Gemini 실패 시 규칙 파서 폴백(rules.py, 테스트 15개) — 날짜 못 읽으면 needs_review로
      남긴다(버리지 않음). entries.json을 손으로 고치고 rebuild-page로 재반영 가능.
    - 산출: state/entries.json 누적 + static/vacation_report.html(사이드바 🏖️ ┗휴가/출장.계획,
      관리/모미 그룹 수명 피드백 아래) + 신규 건만 텔레그램(VACATION_* → WATCH_* → KDEF_* 폴백).
      상태 커밋은 발송 성공 뒤에만(실패 run이 last_id를 올리면 그 보고는 영영 안 잡힘).
    - 대시보드가 공개 주소라 친구 이름·휴가 기간이 노출되는 점은 감수(리네임 운영과 동일 정책).
    - **직접 기입 + 달력** (8/30 저녁): 페이지(팀원 휴가 일정 체크)에 ✍️ 기입 폼 —
      GAS dispatch_proxy `vacation` 라우트 → vacation-tracker.yml mode=add(세션 불필요).
      제출 즉시 점선(pending)으로 표시하고, 15초 간격으로 배포본 갱신 시각을 감시하다
      자동 새로고침. 달력은 2개월 나란히 + ◀▶ 이동(이번 달~+6개월 연속 렌더),
      날짜 더블클릭 두 번으로 기간 입력. 순서: 다가오는 → 달력 → 기입 → 지난 → 확인필요.
      친구 매칭은 표시 이름 포함 일치('다리' 수식어 우선). 검증: 김혜영 독일 출장 기입 E2E 성공.

이후 작업은 git log와 이 파일을 갱신하며 이어간다.
