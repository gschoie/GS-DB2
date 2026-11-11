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
| `market_flow/` | 시장 수급 스크랩 + 리포트 + 텔레그램 (평일 11:00/16:00, 하루 2회 — 10/20 4회에서 축소) |
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
| `macro_desk/` | 매크로 데스크 — 금리·환율·원자재 + 발표 일정 달력 + 지표 해석 가이드 (`macro-desk.yml`, 매일 21:00) |
| `dart_capacity/` | OpenDART 정기보고서의 생산능력·생산실적·가동률 표 수집 → 정규화 → 대시보드 (`dart-capacity.yml`, 3·5·8·11월 20일) |
| `gas/` | Google Apps Script 정본 (dispatch_proxy 등) |

관련 별도 리포: `gschoie/tradewinds_telegram_bot`(TradeWinds 해운뉴스, Python+Playwright, 매시 실행), family-talk-daily(이쁘게.말하기).

## 운영 교훈 (반드시 지킬 것)

- **워크플로 concurrency 주의**: GitHub concurrency는 대기 run을 취소한다(대기열 1개만 유지). 수집/봇 잡에 함부로 걸면 실행이 유실됨 — deploy 잡에만 사용. recipe_bot에서도 이 함정으로 연속 입력이 취소된 적 있어 제거함.
- **텔레그램·유튜브는 GitHub 러너 IP를 간헐 차단**(스로틀·봇체크) → 재시도/폴백/Gemini 영상 직접 시청 등으로 우회.
- **뉴스 캐시**: 캐시는 뉴스DB·노조로 분리, 복원은 읽기전용·저장은 수집 run만. push 배포도 캐시 DB 사용(옛 커밋 DB로 덮어쓰는 7/8 리버트 사고의 원인이었음). 전체 재분류(rebuild)는 파서 변경 시 1회만.
- **Gemini 쿼터**: recipe_bot은 전용 키 `RECIPE_GEMINI_API_KEY`(별도 GCP 프로젝트) 사용, 모델은 `gemini-flash-lite-latest` 등 최신 별칭 우선, 429 시 65초 대기·재시도.
- **배포 안전망(verify)**: 메뉴명 하드코딩 대신 키워드 매칭 — 메뉴 이름을 바꿔도 배포가 깨지지 않게 유지할 것.
- **셸에서 KST 시각을 UTC로 바꿀 때 `TZ=Asia/Seoul date -u -d "today HH:MM"` 금지** — `-u`가 TZ를
  덮어써 HH:MM을 UTC로 읽는다(10/19 수급 텔레 재발송 사고: 가드의 since가 미래가 되어 무력화).
  올바른 형태: `d=$(TZ=Asia/Seoul date +%F); date -u -d "TZ=\"Asia/Seoul\" $d HH:MM"`.
  또한 지연 크론은 슬롯 **정시 이전**에도 떨어질 수 있다(10:00 크론이 14:39 도착) — 가드에
  "정시 전 도착이면 스킵(정시는 GAS 시계 담당)" 조건을 함께 둘 것.
- **`telegram_research_dashboard/build_static.py` 를 로컬에서 그냥 돌리지 말 것**:
  `DASHBOARD_OUTPUT` 이 없으면 `OUTPUT.parent` 가 **리포 루트**라 ① 배포본 400여 개가
  루트에 쏟아지고 ② 마지막의 `apply_to_tree(OUTPUT.parent)` 가 리포 전체를 훑어
  **소스 HTML 에 비밀번호 가림막을 주입**한다(10/12 실측: 추적 437개 수정 + 미추적 220개,
  커밋 전이라 `git checkout -- . && git clean -fd` 로 복구). CI 는
  `DASHBOARD_OUTPUT=_site/index.html` 을 줘서 안전 — 손으로 볼 땐 반드시 임시 폴더를
  지정한다: `DASHBOARD_OUTPUT=/tmp/site/index.html python build_static.py`.
  (`kospi_consensus/build_static.py` 는 **다른 스크립트**다 — 혼동 말 것.)
- **concurrency 자기교착**: 워크플로 레벨과 그 안의 잡이 **같은 그룹명**을 쓰면 자기 run이 쥔
  자물쇠를 자기 잡이 다시 기다려, 잡이 러너 배정도 못 받고 0초에 실패한다(steps·로그 없음).
  refresh-macro가 이 구성으로 8/23~9/3 78회 연속 배포 실패(마지막 성공 8/22)했고 아무도 못 봤다.
  → `group: pages`는 **deploy 잡에만**. 0초·러너 없음·로그 404 실패를 보면 이걸 먼저 의심할 것.

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
    - **3일 간격은 마지막 발송 기준**: 트리거는 매일 07시에 돌고(`scheduledDigest`),
      `LAST_DIGEST_AT`에서 3일(−6h 여유)이 안 지났으면 건너뛴다. 수동 갱신도 발송이므로
      그 시점부터 다시 3일을 센다. GAS everyDays(3)는 기준점을 못 옮겨 이렇게 했다.
    - **주간(평일) 모음**: 3일 모음과 별개로, 매일 오전 8시대(`scheduledWeekly`)에 WEEKLY_ROTATION 의 그날 담당 채널만(월 샤를세환·화 KKMD·목 까치살모·금 슈퍼소닉·토 KFN+·일 KFN1, 수요일은 비움)
      '지난 7일'의 **일반 영상만**(쇼츠·라이브 제목 휴리스틱 제외) 채널별로 보낸다.
      대상은 weekly:false 를 안 단 5곳(샤를세환·KKMD·까치살모·슈퍼소닉·KFN+).
      `WEEKLY_` 롤링 로그는 발송해도 안 비우고 7일 지난 것만 청소 — 같은 영상이
      평일마다 다시 실리는 게 정상(그날 기준 스냅샷). 피드 15개 한도는
      checkNewVideos 가 지나갈 때마다 로그에 적립해 메운다. 대시보드는 같은
      workflow_dispatch 에 kind:'weekly' 로 실려 `static/youtube_weekly/` +
      사이드바 `🗞 ┗방산유튜브.주간(평일)`. installWeeklyTrigger() 1회 실행 필요.
    - **밀리터리 칼럼 주간 모음**(`sendMilitaryColumns`): 밀리터리 칼럼 목록에서 지난 4일
      기사 링크만 모아 수·일요일 오전 8시대(`scheduledNownews`, `installNownewsTrigger`)에
      텔레그램 두 통(소스별 제목 목록 + [소스명] 링크 묶음)으로. NotebookLM 오디오용.
      소스는 `MIL_SOURCES` 하나에서 관리 — 현재 나우뉴스 밀리터리+(무기인사이드) + 세계 박수찬의 軍 +
      서울경제 이현호의 방산톡. 소스는 dated:true(ID에 YYYYMMDD → 지난 MIL_DAYS일) /
      dated:false(ID가 순번 → 목록 최근 limit건, 서울경제가 이 경우)로 나뉜다. 기사 URL의 id 앞 8자리(YYYYMMDD)로 날짜를 판별하므로 마크업이
      바뀌어도 링크는 뽑힌다(제목은 best-effort). doPost 에 send_nownews 액션.
      매주 롤링(지난 한 달) — 겹침이 정상. `sendNownewsMilitary` 는 옛 이름 호환 별칭.
    - **수동 갱신 버튼**: ytdigest 뷰의 `🔄 모음 갱신` → 유튜브 GAS 프로젝트를 웹 앱으로
      배포한 주소(app.js `YTDIGEST_ENDPOINT`)에 POST {action:'send_digest'} → 최근 3일치를
      피드에서 다시 채워 즉시 발송(텔레그램 두 통 + 대시보드). LockService로 동시 실행 방지.
      dispatch_proxy를 거치지 않는 이유: 모음 데이터가 그 프로젝트의 스크립트 속성 버퍼에
      있어 GitHub 워크플로로는 만들 수 없다. 웹앱 코드 갱신은 '배포 관리 → 새 버전'으로만.
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
    - **퇴사자 처리** (9/15): config.yml `former:` 목록(고영민·김상혁 — 남대종·테크RA로 교체).
      수집 제외 + 세 페이지(휴가·근태·발간계획) 하단의 접힌 '🗄️ 퇴사자' 섹션에 기록만 보관.
    - **직접 기입 + 달력** (8/30 저녁): 페이지(팀원 휴가 일정 체크)에 ✍️ 기입 폼 —
      GAS dispatch_proxy `vacation` 라우트 → vacation-tracker.yml mode=add(세션 불필요).
      제출 즉시 점선(pending)으로 표시하고, 15초 간격으로 배포본 갱신 시각을 감시하다
      자동 새로고침. 달력은 2개월 나란히 + ◀▶ 이동(이번 달~+6개월 연속 렌더),
      날짜 더블클릭 두 번으로 기간 입력. 순서: 다가오는 → 달력 → 기입 → 지난 → 확인필요.
      친구 매칭은 표시 이름 포함 일치('다리' 수식어 우선). 검증: 김혜영 독일 출장 기입 E2E 성공.
    - **떨어진 날짜 나열 = 건별 분리** (11/6, PR #499): "11/13, 11/20 휴가 쓰겠습니다~"
      (이준범)를 Gemini 실패 폴백이 **11/11~11/13 구간으로 오독** — _DATE_LIST 나열
      정규식이 "11/20"의 '11'을 같은 달의 '날'로 삼켰다(안 잡힌 게 아니라 틀리게 잡힘).
      → `rules.extract_periods`: 날짜 토큰 2개 이상이면 **토큰 사이 글**로 판정 —
      쉼표·'및/그리고'류 나열은 건별 분리(연속 날짜는 한 구간: "12/22, 12/23 그리고
      12/28" → 2건), `-`·`~`·부터/까지 구간 표지는 종전대로. 같은 달 나열 정규식은
      완전한 날짜 토큰이 하나뿐일 때만. Gemini 스키마에 periods[](떨어진 기간은 배열),
      extract()가 건마다 uid#k 생성(인뎁스 방식, span 중복은 seen_spans). 테스트 114개.
    - **연차계획서 이미지 등록** (10/28, PR #467): HR 미사용연차사용계획 캡쳐(휴가일자 +
      종일/오전/오후 표)를 휴가 페이지 📷 섹션에 붙여넣으면 달력에 들어간다. 경로:
      페이지 JS(canvas 축소 ≤1600px, jpeg 0.88) → GAS `vacplan` 액션 →
      `vacationPlanImage_`가 **Gemini 비전으로 메모리에서만 추출**(flash↔flash-lite 교대,
      JSON 모드) → `fireWorkflow('vacation', mode=plan)` → `vacation_bot.apply_plan`.
      **이미지는 어디에도 저장하지 않는다** — 캡쳐에 사번이 있고 리포가 공개라서(GAS 응답으로
      추출 행만 돌려줘 페이지에서 바로 검수). GAS 프로젝트에 `GEMINI_API_KEY` 속성 필요.
      - 의미론: 연속 종일은 한 기간으로 묶고(종일→연차, 오전/오후→반차), uid `plan:이름:시작일`.
        **재등록 = 통째 교체**(계획이 수시로 바뀜 — 같은 이름의 기존 plan 중 새 계획에 없는
        날짜는 묘비), 텔레그램으로 이미 잡힌 같은 (이름·기간)은 생략 — 두 소스 합산.
        개별 삭제·수정은 기존 달력 조작 그대로(plan 항목도 묘비 삭제).
      - E2E 검증 (10/28): 이다연 실캡쳐 9행 → 6기간, 4건 등록 + 2건(8/13·10/26 오전반차)은
        텔레그램 기수집분과 중복이라 생략 — 설계 그대로. 테스트 5개(test_plan.py), 총 98개.
      - **중복은 조용히 생략하지 않는다** (10/28 같은 날 사용자 추가 규칙): 텔레그램 보고와
        겹친 계획서 날짜는 그 기존 항목 **메모에 `📷 연차계획서에도 있음`**(PLAN_ALSO_MARK)을
        단다. 재등록 때마다 그 사람의 표시를 걷고 이번 계획 기준으로 다시 달아 멱등 —
        계획에서 빠진 날짜의 낡은 표시가 안 남는다. 기존 메모는 ` · ` 뒤에 이어 붙여 보존.
      - **교체는 오늘 이후만 + 여러 장 합산 + 503 재시도 + 섹션 맨 위** (11/5): ① 재등록
        교체에서 **지난 일정(end<오늘)은 캡쳐에서 빠져도 안 지운다**(사용자 "과거는 굳이
        지우지 말고" — HR 화면이 스크롤로 잘려 과거 행이 캡쳐에 없는 게 보통; 멱등 표시
        걷기도 미래 항목만). 테스트는 _FrozenDT 로 '오늘'을 2026-11-05 고정(안 하면 실제
        날짜가 ROWS 를 지나는 순간 깨진다). ② 긴 표는 **캡쳐 여러 장(최대 4)을 한 제출로**
        — 전부 한 번의 Gemini 호출에 넣어 행 합산(3장을 따로 넣어 실패한 11/5 실사례),
        페이지는 planImgs[] 누적·썸네일·비우기, GAS 는 images[] (옛 image 호환).
        ③ Gemini 503/429 는 flash↔lite 두 바퀴·10초 간격 재시도. ④ 섹션을 페이지 맨
        위(🔄 수집 버튼 바로 밑)로 이동(_plan_form 분리 — 스크립트는 뒤에 있어도 무관).
        **GAS 재붙여넣기 + '배포 관리 → 새 버전' 필요**(vacplan 이 바뀜).
      - **옛 GAS 호환 + 키 유출 수선** (11/6~9): 재붙여넣기 전의 옛 GAS 는 images[] 를
        몰라 전부 400 — 페이지가 한 장일 땐 옛 image 키를 병행(여러 장은 일부러 안 보냄:
        첫 장만 처리되면 빠진 날짜가 조용히 지워진다, 안내문으로 대체). 그리고 GAS
        UrlFetchApp 이 '시간 초과: <URL>' 예외를 던지면 **?key= 가 오류 문구째 화면에
        노출**됐다(11/9 실사례) → 키를 x-goog-api-key 헤더로 이동, fetch 를 try/catch 로
        감싸 시간 초과도 모델 교대 재시도 대상에 포함, doPost 는 오류 문구의 key= 값을
        지우고 돌려준다. **키는 한 번 노출됐으니 AI Studio 에서 재발급 권장**(GAS 스크립트
        속성 + 같은 키면 GitHub 시크릿도 교체). 다른 GAS 3종(youtube·mz_diary·remember)도
        ?key= 패턴이 남아 있다 — 화면에 오류를 돌려주지 않아 급하지 않지만 같은 부류.

20. **월별 근태 체크 신설** (9/9): `vacation_tracker/attendance.py` — 팀원이 텔레그램 1:1로
    보내는 "근태 완벽합니다"류 보고를 휴가 추적과 **같은 스캔**에서 규칙만으로 잡아
    (Gemini 불필요, 상대 메시지만) `state/attendance.json`(월×이름)에 기록.
    - 화면 `static/attendance_report.html`(월별 근태 체크): 월 ◀▶ + 이름·확인✓·시각·원문 표,
      확인 칸 클릭으로 수동 토글(구두 보고 대비) — 기존 vacation 라우트에 op=att만 얹어
      **GAS·워크플로 신규 인프라 0**. 사이드바 `✅ ┗근태.체크(월)`(휴가/출장.계획 밑).
    - **체크 기간(캠페인) 모델** (9/9 개편): 근태 체크는 매월 초에만 하므로 상시 수집이
      아니라 페이지의 `▶ 체크 시작`(대상 월 선택, 기본 전월)으로 기간을 열어야 스캔이
      근태 보고를 잡는다. `🏁 마감`을 누르면 이후 스캔은 근태를 무시(수동 토글은 계속
      가능). 기간 중 모든 보고는 **캠페인 대상 월**로 붙는다 — 9월의 대화는 8월 근태
      ("9월 근태 완벽"이라 적어도 8월 체크 중이면 8월).
    - **수동 수집 전용 전환** (10/6): 하루 2회 자동(휴가 스캔 편승)을 끄고 페이지
      `🔄 지금 수집`을 누를 때만 근태를 수집(워크플로 ATT_SCAN=dispatch만 1).
      증분(last_id) 편승이 아니라 **최근 14일 창을 따로 훑으므로**(att_lookback_days)
      자동 run이 last_id를 올려도 그 사이 보고를 놓치지 않는다. 같은 uid 재발견은
      record_hits가 걸러 중복 알림 없음.
    - 표 제목 "2026년 8월 근태" + 진행중/마감 배지. 내용 칸에 자동(텔레그램 원문)/수동
      출처 배지, 행 ✏️로 메모 입력(op=att-note, 체크 상태 불변·재보고에도 보존).
      부탁·질문("근태 체크해 주세요")은 컷. 신규 확인은 휴가 알림에 합류 발송.
    - **긍정 낱말 요구 폐지 — '근태' 언급 = 보고** (11/4): "10월 근태 소명사유
      등록했습니다"(11/3 김연미)가 _AFFIRM 목록(완벽·완료·정상…)에 없어 탈락한 사고.
      사용자 규칙 "근태라는 단어가 있는데" — 근태 스캔은 체크 기간이 열려 있을 때만
      도니 '근태'가 든 팀원 메시지는 목록 없이 보고로 본다. 컷은 질문·부탁
      (_NEGATIVE_RE)과 **'아직 안 했다'류**(_NOTYET_RE: 아직·못했·할게·하겠·예정·
      진행중)만. _AFFIRM은 '근태' 낱말 없는 답 문맥(detect_attendance_reply) 전용으로
      잔존. 오검출은 페이지 수동 토글로 끈다(원문이 내용 칸에 보이므로 분별 가능).
      같은 날 2탄 — **앵커를 '근태|출근'으로**(사용자 "정상출근 출근도 근태로 분류해야지";
      "이준범 10월 정상출근입니다!"가 '근태' 낱말이 없어 또 탈락한 실사례). '근태' 없이
      '출근'만 있으면 출퇴근 잡담·질문을 추가로 컷(_COMMUTE_RE: 출근길·지금/방금/늦게/일찍
      출근·출근중·퇴근 + 물음표). 테스트 108개.
    - **질문-답 문맥 수집 + 마감 취소** (10/7): 팀장이 '근태'가 들어간 메시지를 보낸 뒤
      12h 안의 답은 '근태' 낱말 없이도 긍정이면 보고로("근태 첼"→"9월 정상 출근입니다"
      실사례, detect_attendance_reply). _AFFIRM에 '정상' 추가. 마감 후 `↩️ 마감 취소`
      버튼(att-open 재사용). 상태 문구(#att-status)는 수집 버튼 바로 아래로 이동,
      수집 버튼 경로는 3분간 '🔄 수집 중… n분 경과' 유지(세 페이지 watchDeploy 12분 감시
      — GitHub Pages CDN이 최대 10분 옛 페이지를 캐시해 6분 감시로는 포기하던 문제).
    - **경합 push 재시도 = '일 재수행'** (10/6): 수동 체크 연타 때 `-X theirs` 줄 병합이
      다른 run의 op를 덮어쓴 사고(박소현·김혜영 체크 유실, git 이력으로 복구). 재시도를
      reset --hard origin/main 후 add 모드는 op 재적용, run 모드는 `reconcile_state.py`
      키 단위 병합(uid/월·이름 합집합, 충돌 시 op=main 우선, checked는 OR, last_id는 max)으로
      교체. 24번 교훈의 git 판: **줄 병합은 상태 JSON의 동시 쓰기를 못 지킨다.**
    - 별도 대시보드로 만든 이유: 수명 피드백에 "근태 26.09" 항목을 다는 방식은 매달
      수동 생성이 필요하고, 근태는 16명×월 체크 표 모양이라 전용 페이지가 맞다.
    - 사이드바는 수명 피드백·휴가/출장·근태 3개를 `🗂️ 팀원.체크` 서브메뉴(nav-subgroup)로 묶음.

21. **인뎁스/자료 발간 계획 추적 신설** (9/12): `vacation_tracker/indepth.py` — 팀원과의
    1:1 대화에서 리서치 자료 발간 계획을 잡아 정리. 휴가 스캔 편승(신규분) +
    `--indepth-backfill`(워크플로 mode=indepth-backfill)로 지난 92일 소급 — last_id를
    안 건드려 휴가·근태 수집과 무관.
    - "인뎁스"라고 콕 안 집는 보고까지: 규칙 프리필터는 넓게(발간·커버리지·개시·이니시·
      자료/보고서 작성·타겟 등) 열고 **Gemini가 문맥으로 '발간 계획인가' 판정** →
      {주제, 예정일(target), 시점 표현(target_text), 종류}. 내 질문("인뎁스 언제 나와?")
      뒤 상대 답 2건도 후보(12h 창). Gemini 폴백은 강한 키워드만 needs_review.
    - 저장 state/indepth.json(uid 키, 아는 uid는 재판정 안 함 — 수동 수정 보호).
      화면 static/indepth_report.html: 발간 예정/확인 필요/지난·완료, 완료✓ 토글·
      ✏️메모·🗑삭제(op=idx-done/idx-note/idx-del, GAS 변경 없음), 🔄 지금 수집.
    - 사이드바 🗂️ 팀원.체크 서브메뉴에 `📚 인뎁스.발간계획`(근태 밑). 신규 건은
      **매크로봇**(IDX_TELEGRAM_* = CONGPT 시크릿, 매크로_공부 방)으로 별도 한 통
      "📚 발간 계획 레이더"(10/7 분리; 미설정 시 휴가 봇 폴백, 백필은 대시보드만).
    - **단체방 + 일정표 다건 + 묘비** (10/5~6): config `indepth_groups`(DAOL 기업분석
      시니어+알짱)를 제목 부분일치로 찾아 발간계획만 수집(발신자→팀원 이름 환원,
      last_id는 group:<id> 키). Gemini 스키마를 plans[]로 — "<10월 인뎁스 일정>"류
      일정표는 건마다 분해(uid#k, 무기명은 담당 '미정'), 콜라보는 한 건 유지·담당
      '이름1·이름2'. 내가 상대 일정을 말한 것도 계획(1:1 단건은 상대 귀속).
      **🗑 삭제는 묘비(deleted=True)** — uid를 지우면 백필이 지운 항목을 되살린다
      (10/6 실사고, 과거 삭제 13건 git 이력에서 묘비 복원). is_known()이 uid#k↔단건
      교차를 인지해 재판정·중복 차단. 편집 op 확장: idx-topic(📝 제목)·idx-name
      (👤 담당, 체크박스 복수 선택 = 콜라보)·주제 빈 칸은 메모로 대신 표기(_shown_topic).
    - **일정 조정 = 기존 건 이동, 두 건 금지** (10/28): 사용자 규칙 "2개가 남는 게 아니라
      잘 보고 옮기도록". `record()`가 새 항목을 저장하기 전에 `find_reschedule()` —
      같은 담당자 + 같은 주제(공백 제거·소문자, 같거나 포함 관계: '전력부품' ↔
      '전기전자(전력 부품)')의 활성 건(묘비·완료 제외, 같은 메시지의 uid#k 형제 제외)이
      있으면 **그 건의 target/target_text/text만 갱신**(주제·종류·담당·메모는 수동 수정
      보호로 불변)하고 새 uid는 merged_into 묘비로 — 백필 재판정도 막힌다. 예정일이
      실제로 움직인 때만 레이더 텔레에 "일정 변경 10-31 → 11-14"로 나가고, 같은 날짜
      재언급은 조용히 병합, **시점 없는 후속 보고는 기존 예정일을 안 지운다**(30번 부류).
      기존 중복이던 김연미 전력부품 인뎁스 2건(1213203·1223291)도 이 방식으로 소급 병합.

17. **친환경 에너지·FDC 브리핑 신설** (9/1): `energy_briefing/` — 건기 초기와 같은
    Gemini 단일 파이프라인(RSS→Gemini flash-latest), 시세·텔레그램 없음(대시보드 전용).
    주제 5축: 친환경 선박 추진(암모니아·액화수소·원자력/SMR) / FDC / FLNG·FSRU /
    LNG 액화 FID / 미국 발전원 투자(가스복합·신재생·SMR). 시사점은 한국 조선 3사 관점.
    `energy-briefing.yml` 매일 UTC 21:40(KST 06:40), 키는 ENERGY_ → CONSTRUCTION_ →
    GEMINI_API_KEY 폴백. 산출물 `static/energy_daily/` + `energy_briefing_report.html`.
    사이드바 `🌊 친환경E·FDC.브리핑`, overview 1행을 네이버Top7|친환경FDC|Claude방산
    33%씩으로 재배치(energyBrief 카드).

18. **유튜브 주간 모음 → 요일별 채널 로테이션** (9/7): 기존 '전 채널 × 지난 7일(평일)'을
    '그날 담당 채널 1개 × 지난 7일(월~토)'로 변경. `gas/youtube_defense_bot.gs`에
    `WEEKLY_ROTATION` (월=샤를세환, 화=KKMD, 수=까치살모, 목=슈퍼소닉, 금=KFN+,
    토=KFN1) 추가, KFN1의 weekly:false 해제(exclude:/이슈&국방/ 유지, 밀덕은 계속 제외),
    `scheduledWeekly`는 일요일만 쉼. 주간 보충 긁기도 담당 채널만. 텔레그램 헤더와
    대시보드 payload에 오늘의 채널 표기(payload.label → 페이지 h1/md 제목 꼬리표,
    `youtube_digest/build_digest_page.py`). GAS는 정본만 갱신 — 사용자가 Apps Script에
    재붙여넣기 필요(웹앱 doPost도 바뀌어 '배포 관리 → 새 버전' 필요, 새 배포 금지).

19. **방산 브리핑 → NotebookLM 구글 문서 동기화(③안)** (9/7): `gas/defense_notebooklm_doc.gs`
    신설 — 새 Apps Script 프로젝트(기존 봇과 분리, 문서 권한 재승인 회피)에서 매일 08시대
    raw.githubusercontent 로 defense_daily·claude_defense 최근 30일 md를 fetchAll(404 스킵)로
    긁어 고정 구글 문서 하나에 덮어씀 — 30일치(수십만 자)는 DocumentApp.setText 가
    'Service Documents failed' 로 죽어서, Drive 고급 서비스(Drive.Files.update +
    text/plain 블롭, v2·v3 모두 동작)로 내용을 통째 교체(서비스 목록 이름은 'Drive API'). 문서는 첫 실행 때 자동 생성, ID는 스크립트
    속성 NOTEBOOKLM_DOC_ID. 리포 공개라 토큰 불필요(비공개 전환 시 GH_TOKEN 속성 지원).
    사용자는 NotebookLM 노트북('Global Defense → 한달 뉴스 PPT')에 그 문서를 Google Docs
    소스로 1회 추가 후 매일 '동기화' 버튼만 누르면 됨. 이후 '계속 쌓고 싶다' 요청으로
    월간 누적 문서 추가(9/8): '방산 브리핑 YYYY-MM' 문서를 매일 1일~오늘로 갱신,
    달이 바뀌면 새 문서 생성·지난달은 얼려져 영구 보존(문서당 ~100만 자 한도 때문에
    단일 무한 누적 대신 월별 분할). 속성 NOTEBOOKLM_DOC_ID_YYYY-MM. 매달 1일 새
    문서를 소스로 1회 추가 필요.

20. **에너지 브리핑에 데이터센터 투자 주제 추가** (9/8): 주제 5→6축 — ⑥ 미국·한국
    데이터센터 투자(하이퍼스케일러 capex·신규 캠퍼스·전력 조달 PPA, 국내 DC 건설).
    영어·한국어 수집 쿼리 2개 추가, 출력에 '## 데이터센터 투자 (미국·한국)' 섹션
    (### 미국/### 한국), 시사점은 7번으로. '일반 IT 데이터센터 버림' 지시는
    '투자·건설·전력 조달만, 서비스·장애·보안 기사 버림'으로 교체. 9/10 보강:
    AI·DC 사업자(Anthropic·OpenAI·Alphabet·Meta 등) 전력 공급 계약(PPA·원전) 전용
    쿼리 + Mousterian/무스테리안 키워드(에너지·DC 문맥 한정, 고고학 기사 컷).

21. **ETF 신호판 누적 블록 — 트레일링 창 + 추세(매수)/추세(매도) 분리** (9/10~9/12):
    화면 상단 고정 블록을 손봤다. PR #208·#209·#210.
    - **달력 주 → 직전 N영업일**: '이번 주 누적'은 월·화에 보면 1~2거래일밖에 안 잡혀
      표가 얇아졌다. `etf_telegram.load_recent(n)`(history/*.json 최신 n개, 휴장일은
      파일이 없어 자동 제외) + `build_report.TRAIL_DAYS = 10`으로 고정 — **한 줄만 고치면
      5영업일로 바뀐다**. 창이 2주에 걸치니 '발생 요일'(월·수)로는 같은 요일이 겹쳐
      구분이 안 돼 `_tally`가 날짜(`dates`)도 함께 적립하고 화면은 `09/07·09/09`로 적는다.
      **일요일 텔레그램은 요청대로 '월~금 누적'(요일 표기) 그대로** — 집계 함수만 공유하고
      창만 다르게 준다.
    - **ADX는 방향이 없는 강도 지표** — `alert_adx` 한 플래그에 상승·하락이 함께 들어온다.
      누적 블록이 이걸 `⚡ 추세` 한 덩어리로 찍어, '하락 추세가 굳었다'가 🟢매수 바로 위에
      방향 없이 붙었다(실제로 그 창의 추세 6건이 전부 하락). 일별 표(`adx-down` 색)와
      텔레그램(🔺🔻)은 이미 구분하고 있었고 누적 블록만 방향을 잃고 있었다.
      → `_tally(days, flag, where=None)`에 술어 인자를 더해 `adx_up`으로 가르고,
      라벨을 **추세(매수) / 추세(매도)**로. 배치는 추세(매수) → 매수 → 매도 → 추세(매도),
      추세 행은 강도순(25 강력 → 20 확인, 일별 표와 같은 규칙), 종류 칸에 ADX 단계 배지.
      표 밑에 "추세는 진입 트리거가 아니라 **가던 방향이 굳었다**는 확인" 한 줄.
    - **`td.r` 함정**: 등락 칸에 `class="g"`/`"r"`을 주고 있었는데 td 문맥에서 `.r`은
      `td.r{text-align:right;font-family:Georgia}`(우측정렬)이라 **색이 안 붙고 음수만
      우측정렬**되고 있었다. 색은 전역 `.pos`/`.neg`로 준다 — 표에 색을 줄 땐 같은 이름의
      정렬 클래스가 있는지 먼저 볼 것.
    - 화면은 **etf-signal.yml 이 다시 돌아야 반영**된다(빌드 산출물이 커밋되는 구조).
      머지만으로는 배포본이 안 바뀐다.

22. **수급 수집 복구 — 네이버 옛 PC 페이지 폐쇄 대응** (9/16): market-flow가 9/11부터 전패
    ("lst_kos_info 블록을 찾지 못함"). 러너 프로브로 원인 특정 — 네이버가 옛 PC 시세
    메인페이지(`sise_index.naver`)를 신규 SPA(`stock.naver.com/domestic/index/…`)로
    302 리다이렉트하며 잠정치 블록이 사라짐. **일별·시간대별 데이터 페이지 5종
    (investorDealTrendDay/Time·programDealTrendDay/Time·선물 sosok=03)은 전부 생존** 확인.
    → `snapshot_provisional`을 시간대별 페이지 최신 행(누적 잠정) 기반으로 교체, 러너
    실측으로 일별 페이지와 값 일치 검증. 확정치는 매 실행 30영업일 백필이라 9/11~15
    공백도 다음 실행에 자동 복구(잠정 슬롯·장중 곡선은 당일 전용이라 소급 불가).
    같은 finance.naver.com 옛 페이지를 쓰는 다른 모듈이 죽으면 이 리다이렉트를 먼저 의심할 것.

20. **커버리지 리서치요약 아침 모음 신설** (9/16): `source_watcher/research_digest.py` —
    구독 전 채널의 "[✨ 리서치 요약] …" 글에서 커버리지(조선·방산·기계) 보고서만 추려
    평일 08:30(KST) 한 통으로 spying 봇(@gs_teleg_trend_bot)에 발송.
    - 낱말은 x_ship_keywords + `x_research_digest_extra`(기계: HD현대인프라코어·두산에너빌리티 등)
      합산 — 관리도 sources.yml 한 곳. 내 채널 제외는 ship_all 설정을 그대로 읽는다.
    - 퍼나른 같은 요약은 제목 지문으로 접고 'n개 채널' 표기. 창은 지난 발송 이후(최대 48h).
    - 발사는 GAS 스케줄러 `research` 슬롯(08:30 평일)이 정시 담당, `research-digest.yml`
      크론(UTC 23:30 일~목)은 안전망 — 스크립트의 '오늘 이미 발송(KST)' 가드로 중복 방지.
      상태(state/research_digest.json)는 발송 성공 뒤에만 커밋.
    - GAS 반영 필요: dispatch_proxy.gs 붙여넣기 → '배포 관리 → 새 버전'.

23. **ChatGPT 방산 브리핑 신설 — API 자동 생성 + 수동 등록** (9/16): Gemini(defense_daily)·
    Claude(claude_defense)에 이은 3탄(`static/chatgpt_defense/` + `chatgpt_defense_report.html`,
    사이드바 `🧠 글로벌방산.브리핑(GPT)`). 텔레그램은 방산 채널(KDEF_TELEGRAM_*,
    GPT_TELEGRAM_* 시크릿 있으면 우선)로 요약+링크.
    - **자동 생성(기본)**: `chatgpt-brief.yml` 크론 UTC 20:55(KST 05:55, Gemini 20:40과
      15분 오프셋) → `defense_briefing/chatgpt_briefing_bot.py` — Gemini 판과 같은 골격으로
      defense_briefing_bot의 yfinance 확정 시세·구글뉴스 RSS(24h)·SYSTEM_PROMPT를 그대로
      재사용하고 **작성만 OpenAI API**(Chat Completions, `OPENAI_API_KEY` 시크릿 필수 —
      없으면 API 생성만 조용히 스킵). 모델은 `OPENAI_MODEL` 리포 변수로 교체 가능,
      기본 후보 gpt-5 → gpt-5-mini → gpt-4o 순 404 폴백. temperature·max_tokens는
      모델 세대별 이름·허용값이 달라 아예 안 보낸다(모델 기본값 사용).
    - **수동 등록이 자동보다 우선**(같은 날짜 md 있으면 API 생성 스킵): ① 인덱스 페이지
      ✍️ 폼 붙여넣기 → GAS dispatch_proxy 라우트 `gptbrief` → workflow_dispatch(content·date),
      ② `chatgpt_briefing/inbox/YYYY-MM-DD.md` 커밋(push 트리거, 처리 후 삭제·README 건너뜀).
      workflow_dispatch 문자열 입력칸은 한 줄짜리라 여러 줄 md가 뭉개짐 — 수동은 폼/파일로.
      같은 날짜 재등록 = 페이지 교체 + 텔레 재발송.
    - 렌더러는 claude_brief_publish.py 임포트 재사용(`gpt_brief_publish.py`, 발행·인덱스·
      텔레그램). deploy-pages workflow_run에 "ChatGPT 방산 브리핑" 추가, build_static 복사
      추가. **GAS 정본 갱신 필요** — Apps Script 재붙여넣기 + '배포 관리 → 새 버전'(새 배포 금지).
    - **(9/17 저녁 A안 전환) OpenAI API는 유료(무료 티어 없음)라 자동 작성 주체를
      Claude 예약 세션으로 교체** — 건설기계와 동일 구조. chatgpt-brief.yml 크론(05:55)은
      **수집 전용**(`chatgpt_briefing_bot.py` 기본 모드 = collect_only →
      `chatgpt_briefing/inputs/<날짜>.json`, 7일 보관), 작성은 루틴 [6.5] 단계가
      inputs(news_list·price_table)만 근거로 수행 → 두 브랜치 push → claude-brief-ingest가
      chatgpt_defense도 main으로 나르고 RSS판 텔레그램 발송(send_gpt 가드).
      명칭도 정직하게 **'RSS판'**으로 변경(사이드바 `🧠 글로벌방산.브리핑(RSS)`, 페이지
      h1·텔레 헤더 동일) — 작성자는 클로드지만 웹서치판(클)과 달리 RSS 목록만 근거라
      소스 관점이 다름. ChatGPT 앱 산출물은 폼/inbox 수동 등록으로 여전히 우선 적용.
      OpenAI 경로는 봇 `--api` 플래그로만 잔존(키 등록 시 사용 가능).

24. **크론 안전망 가드가 중복 발송을 못 막던 버그** (9/16): 수급이 하루 4회인데 저녁에
    18:08·20:58·21:48 세 번 더 돌아 텔레그램이 계속 왔다.
    - **가드가 `event=workflow_dispatch` 만 셌다.** 무료 러너 크론이 밀리면(그날 실측
      +4.5~5.3시간) 15:40·16:40 두 크론이 나란히 16:10~24:00 슬롯에 떨어지는데,
      앞 실행이 schedule 이면 dispatch 검색에 안 잡혀 뒤 크론이 또 돈다. 가드는
      "GAS가 이미 했나"만 보고 "이 슬롯이 이미 처리됐나"는 안 본 것.
    - 고침: **이벤트를 가리지 않고** 창 안의 성공·진행중 run 을 세되 `select(.id !=
      github.run_id)` 로 자기 자신만 뺀다. 실패한 선행 run 은 안 세므로 재시도는 그대로 된다.
      market-flow(슬롯 경계)·etf-holdings(45분 창) 둘 다 적용 — 크론이 여러 개인
      워크플로가 이 두 개뿐이다(trend·etf·consensus 는 하루 1~2회라 자기들끼리 안 겹침).
    - 교훈: **안전망 가드는 "다른 경로가 했나"가 아니라 "이 일이 이미 됐나"를 물어야 한다.**
    - 남은 관찰: 그날 15:40·16:40 슬롯에 dispatch 가 하나도 없었다 — GAS 스케줄러가
      그 두 슬롯을 못 쐈다는 뜻. 가드를 고쳐도 슬롯당 1회는 늦은 크론이 대신 처리하므로
      발송 자체는 되지만, 정시성이 필요하면 Apps Script 쪽 트리거 상태를 확인할 것.

25. **방산 브리핑 통합본 신설** (9/17): 3판(제미나이·클로드 웹서치·GPT/RSS)은 각자 그대로
    두고, 매일 아침 세션 루틴 [6.6]이 세 md를 편집장 관점에서 하나로 합친 **통합본**을
    추가 발행 — `static/defense_unified/<날짜>.md|.html` + `defense_unified_report.html`
    (`defense_briefing/unified_brief_publish.py`, 렌더러 재사용·텔레그램 없음).
    - 통합 문법: 같은 사건은 한 번만(판 표기), 수치 상충은 [상충] 병기, 형식은 일간 브리핑과 동일.
    - **용도 3곳으로 단일화**: ① 사이드바 🌐 글로벌방산.브리핑 서브메뉴 맨 위
      `🛡️ 글로벌방산.브리핑(통합)`, ② 오늘의 요약 방산 카드 — 기존 제미나이·클로드 카드
      2개를 없애고 통합 카드 1개(#unified-brief, payload.unifiedBrief)로(에너지·건기 카드
      유지, 2행은 건기+데일리 재배분), ③ **NotebookLM 구글DOC 적재 소스 — 통합본만**
      (`gas/defense_notebooklm_doc.gs` NLM_SOURCES를 defense_unified 하나로; 사용자
      Apps Script 재붙여넣기 필요 — NotebookLM 전용 별도 프로젝트).
    - claude-brief-ingest가 defense_unified도 나름(경로별 관대 체크아웃, 텔레 가드 없음).
      build_static 복사·unifiedBrief 추출 추가. deploy는 기존 ingest workflow_run 경로 그대로.
    - **방산 주간정리 소스 전환** (9/17): weekly_defense_bot의 지난 7일 수집을 날짜별
      **통합본 우선, 통합본 없는 날짜만 기존 2종(제미나이·클로드) 보충**으로 변경 —
      통합본 아카이브가 9/17부터라 첫 몇 주는 혼합, 이후 자연히 통합본 100%.
      SYSTEM_PROMPT에 (제)/(클)/(GPT)·[상충] 표기 유지 지시 추가.

26. **건설기계 GPT판 + 통합본 신설 / 노션 방산 통합본 전환** (9/17): 방산과 동일 구성으로 확장.
    - GPT판(`static/chatgpt_construction/` + `chatgpt_construction_report.html`,
      `construction_briefing/gpt_construction_publish.py`): 수동 등록(인덱스 ✍️ 폼 → GAS
      `congpt` 라우트 → `construction-gpt.yml` workflow_dispatch / `construction_gpt/inbox/*.md`
      push) 우선, 없는 날은 세션 루틴 [7.5]가 **웹서치 기반**으로 작성 — 기존 데일리가
      RSS·확정시세 기반이라 방산과 반대 구성으로 차별화. ChatGPT 앱에 넣을 지침 정본은
      `construction_gpt/CHATGPT_PROMPT.md`(봇 SYSTEM_PROMPT의 웹서치 개작판).
      텔레는 @gs_macro_bot('gb 매크로_공부') — `CONGPT_TELEGRAM_BOT_TOKEN/CHAT_ID` 시크릿
      필요(미설정이면 발송만 생략, 발행은 정상).
    - 통합본(`static/construction_unified/` + `construction_unified_report.html`,
      `unified_construction_publish.py`, 루틴 [7.6]): 데일리+GPT 2판 합본(같은 사건 1회·
      (클)/(GPT) 표기·[상충] 병기), 텔레 없음. 오늘의 요약 건기 카드(constructionBrief —
      통합본 우선, 데일리가 더 최신 날짜면 데일리 표시, unified 플래그로 링크 분기)와
      노션 입력(제목 "건설기계 브리핑 통합본(2AI) …")의 단일 소스.
      주간정리(weekly_construction_bot)도 통합본 우선·데일리 폴백으로 전환.
    - 사이드바 `🏗️ 글로벌건기.브리핑` 서브메뉴{(통합)·(클)·(GPT)}. claude-brief-ingest가
      두 산출물도 나름(send_congpt 텔레 가드). deploy-pages workflow_run에
      "건설기계 GPT 브리핑" 추가. **GAS 정본 갱신 필요** — dispatch_proxy.gs 재붙여넣기 +
      '배포 관리 → 새 버전'(새 배포 금지).
    - 방산 노션 아카이브도 9/18부터 통합본으로 전환: 루틴 노션 단계를 통합본 발행 뒤([6.6])로
      옮기고 제목 "방산 브리핑 통합본(3AI) YYYY-MM-DD(요일)"·icon 🛡️·defense_unified 링크.
      결측 시 클로드판 폴백(기존 제목). 건기 노션도 동일 원리(과거 캐치업은 데일리 그대로).
    - **가동 확인** (9/17 오후): 사용자 GAS 재붙여넣기 + CONGPT 시크릿 등록 완료 →
      첫 GPT판(9/17)을 세션이 웹서치로 실발행, ingest 성공·매크로_공부 방 텔레 도착까지
      E2E 검증("1개 메시지 전송 완료" 로그). 첫 통합본(9/17)도 세션이 수동 실행으로
      발행·카드 전환까지 검증. 사이드바 라벨은 `┗ 건기.Claude`/`┗ 건기.GPT`로
      축약(PR #249). ChatGPT 앱은 예약 태스크 결과를 내보내는 API가 없어 **앱 산출물
      등록은 언제나 수동**(폼/inbox) — 등록이 없으면 세션 자동판이 기본이고, 아침 [7.5]
      이후 늦게 등록하면 GPT판 페이지만 교체되고 그날 합본에는 반영 안 됨.
    - **텔레 = 섹터당 통합본 한 통** (9/17 저녁 변경): 건기에 이어 방산도 통일.
      건기: 매크로_공부 방 발송을 GPT판 → 통합본으로(send_conuni 가드,
      `unified_construction_publish.py --send-only`, CONGPT_TELEGRAM_*).
      방산: 제미나이(defense-briefing.yml 시크릿 제거+봇 스킵 가드)·클(CLAUDE_TELEGRAM_*)·
      RSS판(chatgpt-brief.yml 스텝 제거) 개별 발송 전부 끄고, ingest가 **방산 통합본**
      한 통을 KDEF_TELEGRAM_*로 발송(send_duni 가드, `unified_brief_publish.py --send-only`).
      CLAUDE_TELEGRAM_*·GPT_TELEGRAM_* 시크릿은 미사용 잔존. 주간정리 텔레(토, KDEF)는 유지.
      두 폼(방산 RSS판·건기 GPT판) 문구 '발행 → 대시보드'로 정정.

27. **아침 브리핑 일괄 앞당김 — 통합본 06시 완성 목표** (9/18): 사용자가 일찍 일어나
    통합본을 6시에 보도록 상류 전부를 미장 마감(서머타임 KST 05:00) 직후로 이동.
    - 크론(UTC): 제미나이 방산 20:40→**20:00**(05:00 KST) / RSS 수집 20:55→**20:05**(05:05) /
      건기 수집 21:10→**20:15**(05:15) / 건기 Gemini 폴백 22:40→**21:20**(06:20 KST,
      market-trend 06:30 Gemini와 10분 오프셋).
    - 루틴 발화 21:00→**20:00 UTC**(05:00 KST). 세션 내 마감도 이동: RSS inputs 05:25 트리거·
      05:50 스킵, 제미나이판 대기 05:50까지, 건기 inputs 05:35 트리거·06:10 스킵(폴백 06:20 대체).
    - 목표 완성 시각: 방산 통합본 ~06:00, 건기 통합본 ~06:30 (GitHub 크론 지연 시 세션
      수동 트리거가 보완). **주의: 미국 겨울시간(11월~3월)엔 마감이 06:00 KST라 전 일정이
      1시간 뒤로 밀려야 함 — 11월 초 재조정 필요.**

28. **주간정리 2종 정시성 — GAS 스케줄러 이관** (9/19): 토요일 크론(방산 11:50·건기 12:10)이
    매주 +4.5시간대로 밀려(실측 3주 연속 16:21~16:58 실행) 주간정리 텔레가 오후 5시에
    도착하던 문제. 아침 5종과 같은 방식으로 이관 — `gas/dispatch_proxy.gs`에
    `defweekly`/`conweekly` 라우트 + SCHEDULE 토 11:50/12:10 슬롯 추가. 크론은 안전망으로
    유지하되 두 워크플로에 guard 잡(이벤트 무관·자기 제외·600분 창, 24번 교훈 방식) 추가 —
    GAS가 정시에 쐈으면 늦은 크론은 스킵(중복 텔레 방지), 가드는 fail-open.
    **GAS 재붙여넣기 필요**(트리거는 저장된 최신 코드로 돌므로 저장만으로 적용,
    '배포 관리 → 새 버전'은 함께 해두면 깔끔). 운영 메모: 통합본 발행 push 뒤에
    defense_unified/construction_unified md를 다시 고치는 커밋을 만들면 ingest 가드가
    'md 변경'으로 보고 텔레를 재발송한다(9/19 시각 정정 커밋으로 KDEF 2통 실측) —
    표기 정정은 다음 날 반영하거나 발행 전에 끝낼 것.

29. **컨센 추적 유니버스 복구 — 네이버증권 개편 2탄 + 1개월 비교** (9/28): 9/18부터 KOSPI200·
    코스닥50이 0건이라 유니버스가 커버리지 175종목뿐이었다. 옛 PC 페이지 `entryJongmok`은
    **410(폐쇄)**, `sise_market_sum`은 stock.naver.com SPA로 302. 모바일 JSON API로 교체 —
    `m.stock.naver.com/api/index/KPI200/enrollStocks`(pageSize 100은 400 에러, 50 사용) ·
    `/api/stocks/marketValue/KOSDAQ`. 러너 실측 KOSPI200 201·코스닥50 50·합계 319.
    - **안전망이 못 잡은 이유**: 폴백 판정이 '전체 150종목 미만'이었는데 커버리지만으로 175라
      통과 → 부서진 유니버스가 캐시로 저장됨. 이제 **그룹별**(KOSPI200 150·코스닥 40 미만)로
      판정해 부족한 그룹만 직전 캐시로 채운다.
    - 화면 비교 기준 토글에 **1개월** 추가(주간/1개월/3개월, 필드 접미사 ''·'1'·'3').
    - 참고: 추적 시작은 7/6. 3Q26 분기 컨센은 8/13부터 저장돼 3개월전(7/6) 3Q 값은 원래 없다
      (연간 2026E·2027E는 7/6부터 있어 3개월 비교 가능).

30. **액티브 ETF 매매동향 — 휴장일에도 돌고 '가짜 매매'가 잡히던 문제** (10/5): 대체공휴일인
    10/5 에 09·10·11시 세 번 돌고 "매매"가 표시돼 사용자가 잡아냈다. 원인이 셋 겹쳐 있었다.
    - **기준일 워처가 눈이 멀어 있었다** — `watch.py` 가 보던 CU 구성종목 기준일은
      `finance.naver.com/item/coinfo.naver` 를 긁는데, 29번의 그 개편으로 신규 SPA 에
      리다이렉트되며 '기준' 표기가 사라졌다. **9/10 이후 전 스냅샷 base_date=""**,
      state.json 도 9/10 에 멈춤. 신규 front-api 에도 CU 기준일이 없다(etf/analysis·
      etf/component/list 응답 키 전수 확인 — 상장일과 성과기준일뿐).
    - **GAS 디스패치를 '수동'으로 보고 강제 실행하고 있었다** — 17번으로 GAS 가 매시 :17
      `workflow_dispatch` 로 쏘는데 워크플로가 `event_name == 'workflow_dispatch'` 만 보고
      `WATCH_FORCE=1` 을 걸어 **판정을 통째로 건너뛰었다**. 텔레그램 스텝은 이미
      `inputs.via != 'scheduler'` 로 구분하고 있었는데 워처 쪽만 빠져 있었다.
    - **안전망이 fail-open 으로 뚫려 있었다** — `same_base = bool(today_base and ...)` 라
      기준일이 빈 문자열이면 `bool("")` → False, 즉 "모르면 새 기준일"로 통과했다.
    - 고침 = **기준일에 기대지 않는 2단 게이트**. ① `watch.py` 는 거래일 게이트만
      (`/api/index/KOSPI/basic` 의 localTradedAt ≠ 오늘이면 스킵, market_flow 와 같은 방식,
      조회 실패는 fail-open, WATCH_FORCE 는 화면 버튼에만). ② `fetch_holdings.snapshot` 이
      직전 스냅샷과 **계약수 지문**을 비교해 같으면 **파일을 안 쓰고** changed=false →
      이후 스텝 전부 스킵. 비중·NAV 는 주가만 움직여도 바뀌므로 지문에서 뺀다.
      일부 ETF 수집 실패로 종목이 줄어든 것도 저장 안 함(가짜 '이탈' 방지). state.json 삭제.
    - **표기도 정직하게** — 기준일을 지어내지 않고 '구성 변화 감지 시각'을 적고, 바스켓이
      장 마감 뒤 갱신되므로 **여기 매매는 대개 직전 거래일의 것**이라고 화면·텔레에 명시.
      실측 근거: 10/2(금) 16:21 스냅샷 → 10/5(휴장) 11:21 스냅샷에서 20개 중 11개가 변했다.
      그 사이 거래일이 없으니 전부 금요일 매매다.
    - `tests/test_guards.py` 9개 신설(휴장일 스킵·force 우회·조회실패 fail-open·동일 바스켓
      미저장·비중만 변한 경우·실제 계약수 변동·부분 실패) + 워크플로에 실행 스텝.
    - **교훈**: 죽은 소스가 빈 문자열을 돌려줄 때 **그걸 '모름'이 아니라 '없음'으로 읽는
      코드는 조용히 반대로 동작한다.** 24번('이 일이 이미 됐나'를 물어야 한다)과 같은 부류다.

31. **네이버 증권 → Npay 증권 전면 개편 · 신규 front-api 지도** (9/22): 9/11 리다이렉트,
    9/18 410 폐기는 낱개 사고가 아니라 **서비스 전체가 Npay 증권으로 갈아엎어진** 결과였다
    (페이지 title 이 전부 `… - Npay 증권`). 러너에서 새 사이트를 크롤해 **앱이 호출하는
    axios url 274개 전량**을 번들에서 떠 확인한 것을 남긴다 — 다음에 또 뭐가 죽으면
    여기부터 볼 것.
    - **구조**: Next.js SPA. 화면은 `/domestic/…`(국내) · `/worldstock/…`(해외) ·
      `/marketindex/…`(환율·원자재·금리) 세 갈래. 데이터는 **`https://m.stock.naver.com/front-api`**
      베이스에 상대경로(`/market/investorTrend` 등)로 붙는다. 코드에 `/api/` 로 시작하는
      문자열만 뒤지면 **아무것도 안 나온다**(realtime 폴링 15개만 그 형태) — 첫 탐색에서
      이걸로 "새 API에 수급이 없다"고 잘못 결론냈다. `url:"…"` 패턴으로 긁을 것.
    - **살아 있는 것**: `/market/investorTrend`(외국인·기관·개인 × 순매수/매수/매도 금액
      + 매수·매도 수량. `marketType`=KOSPI|KOSDAQ|ALL, `periodType`=DAILY|WEEKLY|MONTHLY|
      THREE_MONTHLY. **날짜 파라미터는 없다** — fromDate/toDate/bizdate 다 무시하고 당일만),
      `/stock/domestic/trend`(종목별 일별 수급 + 외국인 보유주식수·보유비율, cursor 페이징,
      한 번에 40건 이상), `/market/tradingTrend/ranking`(투자자별 순매수 상위),
      `/stock/domestic/integration`(dealTrendInfo·programTrendInfo — 현행 수급 수집원),
      `/domestic/index/detail`, `/stock/index/periodChanges`(1d~10y 기준가).
      과거 일자 조회는 구 모바일 API `/api/index/{code}/trend?bizdate=` 가 계속 된다.
    - **영영 없어진 것 둘**: ① **국내 선물·파생** — url 274개 중 선물은
      `/stock/foreign/futures/price/list` 와 `/worldstock/nation/indexFutures/list` 뿐으로
      **둘 다 해외**다. `/domestic/futures/*` 화면도 404. 네이버가 국내 파생 서비스를 접었다.
      ② **기관 세부 7항목**(연기금·투신·보험 등) — 새 API의 투자자 구분은 외국인·기관·개인
      3개가 전부다. 두 가지는 대체 경로도 없다(KRX 는 프로그램 접근을 막고 — 러너·GAS 양쪽
      `400 LOGOUT` 실측 —, 한투 OpenAPI 에는 선물 투자자별 엔드포인트가 아예 없다).

32. **수급 리포트 — 선물 투자자별 자리를 베이시스로 교체** (9/22): 31번으로 '누가 샀나'는
    영영 못 쓰게 됐으니, **'선물이 현물보다 비싼가 싼가'** 로 같은 질문에 답하게 바꿨다.
    베이시스·괴리율은 차익 프로그램이 어느 쪽으로 걸리는지를 직접 설명하므로 화면에
    이미 있는 차익/비차익과 짝이 맞는다.
    - 가격은 **한투 OpenAPI**(이 모듈이 종목별 가집계로 이미 쓰던 곳)에서 받는다.
      `inquire-price`(현재가·mrkt_basis·이론가 hts_thpr·괴리율 dprt·미결제·잔존일) +
      `inquire-daily-fuopchartprice`·`inquire-daily-indexchartprice`(일별 소급).
    - **월물 단축코드를 박아두지 말 것** — 공식 문서의 `101W12` 형식은 지금 안 먹고
      (rt_cd=0 인데 output1 이 빈 채로 와서 실패인 줄도 모른다), 현행은 `A01`+연도끝자리+월
      (`A01612` = F 202612, 미니는 `A05…`). 그래서 근월물은 매번 한투 종목마스터
      `fo_idx_code_mts.mst.zip` 에서 이름이 `F YYYYMM` 인 것 중 가장 이른 것으로 읽는다.
    - **일별 소급은 날짜마다 '그날의 근월물'** 을 쓴다. 베이시스는 만기까지 남은 기간에
      비례해 커져서 한 월물로 쭉 그리면 레벨이 통째로 어긋난다(만기 = 분기 두 번째 목요일,
      실측 F 202612 의 futs_last_tr_date=20261210 과 일치). 그래도 교체일에는 계단이
      생기므로 화면에 그렇게 적어뒀다.
    - `td.r` 함정과 같은 부류 하나 더: 이중축 차트 우축 눈금이 `:,.0f` 라 베이시스처럼
      한 자릿수면 ±2.5 가 ±2 로 반올림돼 **거짓 눈금**이 된다 → 상한 10 미만이면 소수 1자리.
    - market_flow 에 테스트가 없었는데 `tests/test_basis.py` 11개 신설(만기 계산·월물 경계
      전환·베이시스 산식·빈 응답 예외) + market-flow.yml 에 실행 스텝. 야후 못 부르는
      valuation 과 같은 이유 — 한투는 키가 필요하고 컨테이너에서 네이버·거래소가 막혀 있다.

33. **매크로 데스크 신설** (10/11): "매크로를 잘 몰라서" 라는 요청에서 출발 — 숫자만
    띄우는 게 아니라 **숫자 옆에 '얼마면 무슨 뜻인가'** 를 같이 두는 페이지.
    `macro_desk/` + 사이드바 `📈 투자 > 📊 매크로.데스크`(기업.톺아보기 구분선 아래,
    시장.수급.동향 위). 매일 21:00 KST — GAS 시계 `macro` 슬롯이 정시, 크론은 안전망(guard).
    - **키 없이 도는 걸 1순위로** — yfinance 로 미국 금리 4종·달러/환율 4종·원자재·VIX.
      `FRED_API_KEY`(무료)를 넣으면 진짜 2년물·10년-2년 스프레드·기대인플레·실질금리 추가.
      **키가 없으면 '미국 2년물' 칸은 실제로 5년물(^FVX)** — yfinance 에 2년물이 없다.
      화면 ⓘ에 그렇게 적어뒀다(조용히 틀린 이름을 붙이지 않는다).
    - 변화 표기는 **금리 %p · 나머지 %** — 섞으면 "10년물이 6% 올랐다"로 읽힌다.
    - **발표 일정은 규칙과 확정일을 나눈다.** CPI·고용·ISM 은 '매월 n번째 요일' 규칙으로
      뽑고 화면에 `~`(추정일) 표시. **FOMC·금통위는 규칙이 없어 `fixed_dates.json` 에
      있을 때만 표시**하고 없으면 '일정 미확인' — 기관 공표일을 추측해 달력에 박으면
      틀린 날짜가 사실처럼 보인다(30번 교훈의 같은 부류).
    - `tests/test_calendar.py` 14개. **월말이 주말이면 다음 달로 넘어가 그 달 달력에서
      사라지던 버그를 테스트가 잡았다**(2026-02-28 토) → 직전 영업일로 당긴다.
    - 해석·기초는 코드가 아니라 `guide.yml` — 숫자는 매일 바뀌어도 해석 틀은 안 바뀐다.
      **유튜브는 영상 ID 대신 검색 링크**(영상은 내려가도 검색은 남는다), 기관 원문만 직접 링크.
    - 남은 것: 텔레그램 발송, FOMC·금통위 확정일 수집, 한국 국고채(ECOS 키).

34. **매크로 달력 — 이름만 있고 숫자가 없던 문제 + 직전치 소스 지도** (10/11): 첫 판은
    달력 칩에 **지표 이름만** 찍고 설명을 `title` 툴팁에 뒀다. `cursor:help` 때문에
    커서만 물음표로 바뀌고 화면에는 정보가 하나도 없었다(사용자 지적: "여기 물음표가
    뜨고 정보가 하나도 없어"). 국기 이모지도 윈도우에서 `us`·`KR` 글자로 떨어졌다.
    - **툴팁에만 정보를 두지 않는다** — 칩을 두 줄(이름 + 컨센/직전치)로 바꾸고, 누르면
      그 지표 해석 카드로 내려가게 했다. 좁은 칸에 다 못 넣으니 **'다가오는 발표(3주)'
      표**를 달력 위에 따로 뒀다(날짜·지표·직전 발표·컨센서스·최근 3회). 시세표 ⓘ도
      각주로 꺼냈다 — "2년물이 실은 5년물"은 안 보이면 그냥 틀린 표다.
    - **직전치 소스 = BLS 공개 API v1(키 불필요)**. CPI·코어CPI·PPI·취업자·실업률·임금.
      한도가 IP당 25회/일·요청당 50계열이라 **전 지표를 한 호출로** 받는다.
    - **러너 egress 지도**(실측): `api.bls.gov` 됨 · **`api.stlouisfed.org`(FRED 키
      경로) 됨** · **`fred.stlouisfed.org`(그래프·CSV) 막힘**(0.05초 `HTTP/2
      INTERNAL_ERROR`) · Census 키 필요 · BEA 타임아웃 · ISM 경로 없음.
      → **FRED 를 뭉떵그려 "안 된다"고 적으면 안 된다**: 키를 넣으면 소매판매·PCE·
      GDP·정책금리·한국 지표 직전치까지 채워진다. 화면에 🔑 안내로 적어뒀다.
    - **`urlopen(timeout=)` 은 이 차단을 못 잡는다** — 소켓 1회 작업 기준이라 응답이
      느리게 흘러오면 안 걸려 1차 프로브가 15분을 매달렸다. 도달성은 `curl --max-time`.
    - **확정일이 규칙보다 먼저다** — 규칙(`around 12`)은 근사라 어긋난다(2026년 9월 CPI
      규칙 10/12 vs BLS 실제 **10/14**). `fixed_dates.json` 에 있으면 그걸 쓰고 `~`를
      떼고, 없는 달은 규칙으로 돌아간다. 출처가 한 곳뿐인 날짜는 `tentative` 로 넣어
      `~`를 유지한다(금통위 10/22·11/26 — 한은 공식 일정 확인 필요).
    - **변화율을 못 구하면 '–'** — 지수 원값을 대신 찍어 `코어 337.8`(증가율 자리에
      지수 레벨)이 나온 버그를 실측으로 잡았다. 30번 교훈과 같은 부류: 모르는 것을
      '없음'이나 다른 값으로 바꿔 읽으면 조용히 반대로 동작한다.
    - **컨센서스는 무료 API 가 없다**(Investing·TradingEconomics 유료/차단) →
      `consensus.json` 에 적힌 것만 표시. 비면 '–'. 세션 웹서치로 채운다.
    - **폐기된 계열은 에러를 주지 않는다** — 러너 실측에서 한국 CPI 가 "직전 발표:
      2023년 11월" 로 찍혔다. `KORCPIALLMINMEI` 가 OECD MEI 폐기로 2023-11 에 멈췄는데
      FRED 는 그 옛 값을 계속 내준다. 3년 전 숫자를 어제 것처럼 보여주는 건 빈칸보다
      나쁘다 → `is_stale()`(월 130일·분기 230일·일 35일) 로 **날짜로만** 가린다.
      발표 지연은 살린다(10월에 8월분 CPI가 최신인 건 정상). **판정 기준을 두 군데
      박지 말 것** — 프로브에 130일을 따로 박았다가 분기 계열(한국 GDP 2분기)을
      죽었다고 적었다. 30번의 같은 교훈, 이번엔 빈 문자열이 아니라 **옛 값**이었다.
    - 한국 CPI 는 FRED 대체 계열 6개가 전부 죽었거나 멈춤 → **빈칸으로 둔다**
      (ECOS/KOSIS 키 필요). 살아 있는 한국 계열은 실업률·GDP 전기비, 그리고
      **국고채 장기 `IRLTLT01KRM156N`·3개월 `IR3TIB01KRM156N`** — 뒤 둘은 OECD 경유
      **월평균**이라 일별 시세표의 1D/1W 칸에 그냥 넣으면 거짓 라벨이 된다(미반영).
    - 테스트: `test_releases.py` 신설 31개(직전치 변환·BLS 기간 표기·also 합성·호출
      실패·폐기 계열 판정), `test_calendar.py` 14→19개(확정일 우선·tentative·미확인 fixed).

35. **매크로 데스크 — PPI 해석 카드 + 텔레그램 발송** (10/11, 전용 세션): PR #343.
    - **달력 PPI 칩이 CPI 설명으로 갔다**. 원인 셋: ① `config.yml` 의 `us_ppi` 가
      `guide: us_cpi` 를 가리켰고 ② `guide.yml` 지표 11개에 **PPI가 아예 없었고**
      ③ 가더라도 해석 카드·섹션이 둘 다 `<details>` 라 **접혀 있으면 앵커로 가도 안 열린다**
      (섹션 접은 상태는 localStorage 에 남으니 한 번 접으면 계속 그렇다).
      → PPI 카드 신설(최종수요 WPSFD4 기준·**PPI 서비스·의료 항목이 PCE 계산에 들어가
      PPI가 튀면 월말 PCE 예상치가 같이 오른다**는 점 포함), guide 연결 교정,
      **링크를 누르면 대상과 조상 `<details>` 를 전부 펼친다**. 클릭 경로에선
      preventDefault 를 **하지 않는다** — 펼치기만 해두면 브라우저가 이벤트 처리 뒤에
      점프하므로 iframe 안에서도 기본 동작이 맞다. 해시를 달고 들어온 경우만
      (브라우저가 펼치기 전에 점프를 끝낸 상태) 직접 스크롤한다.
    - **텔레그램 = 매크로_공부 방(`CONGPT_TELEGRAM_*`, `MACRO_TELEGRAM_*` 우선) 평일
      21:00 한 통** (`macro_desk/notify.py`): 오늘 숫자 + 앞으로 1주 발표 + 지금 구간 + 한 줄.
      - **"오늘 숫자"가 아니라 "직전 미국 장 종가"다** — 21:00 KST는 미 장 시작(22:30) 전이라
        그날 미국 움직임이 없다. 헤더에 그대로 적는다(안 적으면 거짓 라벨 — 34번 부류).
      - **평일만**: 토·일 21:00 숫자는 금요일 종가 그대로라 같은 메시지가 두 번 더 간다.
        월 21:00 = 금 종가, 화 = 월 종가 … 로 **월~금이 미국 5개 세션을 정확히 한 번씩** 덮는다.
      - **구간 판정은 규칙, 한 줄만 생성형**: `guide.yml` 에 `quote_reads` 절 신설 —
        위에서부터 처음 맞는 밴드 하나(`ge` 이상·`lt` 미만·조건 없으면 폴백)라 **순서가 곧
        규칙**. 값을 모르면 **아무 밴드도 고르지 않는다**(폴백으로 흘리면 '3% 미만' 이
        사실처럼 나간다 — 30번 부류). 한 줄은 그 판정만 근거로 Gemini
        (flash-lite→flash), **실패하면 한 줄만 빠지고 나머지는 그대로 발송**.
      - **FRED 키가 있으면 야후 `us2y`(실은 5년물)를 메시지에서 뺀다** — 진짜 2년물과
        나란히 서면 숫자 둘이 어긋나 보이는데 텔레그램엔 각주를 달 데가 없다.
      - 본문은 **평문**(서식 필요 없고 텔레그램이 맨 URL을 링크로 만든다 → HTML 400
        재시도 분기가 아예 필요 없다). 스프레드는 `unit: pp` 로 `+0.44%p`(`0.44%` 로 적으면
        수익률처럼 읽힌다).
      - **발송은 정시 실행에만** — `schedule` 또는 `inputs.via == 'scheduler'`(GAS 시계).
        화면 `🔄 지표 갱신` 버튼은 `via` 가 없어 빠진다(30번 교훈: 디스패치를 한 묶음으로
        보면 수동 갱신이 텔레그램을 쏜다). GAS `macro` 슬롯은 이미 via=scheduler 를 보내므로
        **GAS 변경 0**. 지금 한 통 받아보려면 Run workflow 의 `force_telegram` 체크 —
        발송 스텝 조건과 `--force`(주말 스킵) 둘을 같이 넘긴다.
      - `tests/test_notify.py` 23개(밴드 순서·경계·모르는 값·%p vs %·us2y 제외·키 없을 때
        한 줄만 빠짐·오래된 수집 경고). 워크플로 테스트 스텝에 추가 — **`discover` 금지**
        원칙 그대로 세 파일을 따로 돌린다.

36. **매크로 데스크 — 시계열 펼치기 + 칩/카드 라벨 정리 + 삼각형 크기** (10/11): PR #345.
    - **시세표 줄을 누르면 그 자리에 12개월 차트**(1M/3M/12M 전환). **추가 호출 0** —
      야후는 이미 400일, FRED 는 500일을 받아오고 `_changes()` 가 그걸 버리고 있었다.
      마지막 252 거래일만 남겨 저장하고, **데이터는 페이지에 박는다**(런타임 fetch 없음,
      48KB → ~110KB). x축은 거래일 등간격이라 차트 밑에 그렇게 적고 양 끝·가운데에
      진짜 날짜를 찍는다. **시계열이 없으면 누를 수 있는 줄을 아예 안 만든다** —
      수집이 한 번 더 돌기 전에는 series 가 없다(눌러도 안 되는 줄은 고장으로 보인다).
    - **날짜는 YYMMDD 고정폭을 이어 붙인 문자열 하나**. `["260110", …]` 로 담으면
      따옴표·쉼표가 날짜 수만큼 붙어 지표당 2KB가 넘는다 → 화면에서 `slice(i*6,i*6+6)`.
      야후는 `Close` **Series** 에 dropna 를 걸어 날짜와 값을 같이 솎는다 — 값만 솎으면
      **차트가 조용히 다른 날짜를 가리킨다**(길이 불일치는 `_series` 가 예외로 막는다).
    - **컨센과 직전치는 방향이 반대인 숫자인데 라벨 차이가 '컨센' 한 단어뿐이었다** —
      직전치를 아무 말 없이 찍어서 칩의 `전년 +5.4%` 가 이번 예상인지 지난 발표인지
      분간이 안 됐다(사용자 지적: "여기에 전년은 머야? 컨센 전년은 머고?").
      → 직전치에 **`직전` + 몇 월분**(`직전 8월 전년 +5.4%`), 그리고 칩을 눌러 내려간
      **해석 카드 맨 위에 숫자판**(컨센서스 / 직전 발표(기간) / 최근 3회). 밴드만 있고
      숫자가 없으면 "근원 3.5% 이상이면…" 을 읽고도 지금 얼마인지를 모른다.
    - **접는 삼각형이 작았다** — `▾`(U+25BE)는 이름 그대로 **small** triangle 인데
      11px·회색까지 겹쳤다. `▼`(U+25BC) 15px 로. 해석·기초 카드는 **브라우저 기본
      마커**라 CSS로 크기를 못 키운다 → 같은 글자 삼각형으로 통일(섹션만 키우면 따로 논다).
    - 덤으로 `guide.yml` 의 `**굵게**` 38군데가 화면에 별표로 그대로 찍히던 것 수정
      (`rich()` — esc 를 먼저 하므로 `<b>` 외 태그는 못 들어온다).
    - `tests/test_chart.py` 27개 + 워크플로 스텝. **검증은 Playwright 로 실제 클릭**까지 —
      컨테이너의 pip playwright 는 번들 브라우저 판이 달라 실행이 안 되므로
      `executable_path=/opt/pw-browsers/chromium-1194/chrome-linux/chrome` 를 준다.

37. **매크로 데스크 — 증가율 표기 YoY/MoM + 기간은 '8월분'** (10/11): PR #346.
    사용자 질문 "직전 발표 전년 +5.4% · 전월 +0.4% 는 직전 8월 발표에서 전년=YOY
    전월=MOM이란 얘기지?" 에서 출발 — **YoY/MoM 은 맞고 '8월 발표' 는 틀렸다.**
    - `_period_label` 의 `d` 는 BLS **관측 기간**(year+M08)이라 `2026년 8월` 은
      **대상 월**이고 발표는 9월 중순이다. 그냥 `8월` 로 적으면 "8월에 발표된" 으로
      읽힌다 → 월간은 **`8월분`** 으로. 분기는 `3분기` 만으로도 대상 기간으로 읽혀 그대로.
    - 증가율 라벨 `전년`·`전월` → **`YoY`·`MoM`**(분기 계열은 **`QoQ`**). 옛 라벨은
      무엇 대비인지는 맞지만 무엇을 재는지는 안 말해 "지난달 값" 으로 읽히기 쉬웠다.
      `consensus.json` 의 손으로 적는 텍스트도 같은 표기로 맞췄다.
    - 약어는 숫자판 밑에서 풀어주되 **그 카드에 실제로 나온 것만**(`legend()`).
      기간 설명은 일반형("오른쪽 기간은 발표일이 아니라 대상 기간") — "8월분의 발표는
      9월" 같은 월간 예시를 분기 지표(GDP) 카드에 붙이면 그 자리에서 틀린 말이 된다.
    - 일별 계열 칩이 `직전 2026-10-11 4.00%` 로 길어지던 것 → `직전 10/11`.
    - **표기는 다음 수집부터 반영된다** — `text`·`period` 는 `releases.summarize` 가
      **수집 때 계산해 payload 에 저장**한다. 빌드만 다시 해선 안 바뀐다(차트와 같은 가드).
    - test_chart 27→29개, test_releases 기대값 7곳 갱신.

38. **투자 공유 허브 + 달력 손질 + PPI 확정일** (10/12): PR #347.
    - **`static/invest.html` 신설** — 사용자가 "투자 9개를 독립 페이지로 굽자" 했는데
      **확인해 보니 9개 전부 이미 독립 페이지가 있었다**(대시보드는 iframe 으로 감쌀
      뿐이고 각 화면의 `🔗 새 창으로` 가 그걸 가리킨다). 진짜 빠진 건 페이지가 아니라
      **친구에게 줄 주소 하나**였다 → 투자 9개만 카드로 묶은 허브. `OWNER_ONLY_PAGES`
      에 없으므로 **공유 비번(`guest1009`)으로 열린다**(산출물에서 `OWNER=false` 확인).
      챗봇·톺아보기는 **다른 사이트라 가림막 바깥** — `외부` 배지와 안내문을 달았다.
      사이드바 투자 그룹에 `🔗 투자 모음(공유용)` 링크 추가.
      배경: `#press` 같은 **대시보드 뷰는 주인 비번 전용**이다 — 사이드바가 팀원
      메뉴까지 통째로 노출하기 때문(`gate.py` OWNER_ONLY_PAGES 에 index.html).
    - **달력 칸이 들쭉날쭉했던 건 `1fr` 때문** — `1fr` 은 사실 `minmax(auto,1fr)` 이라
      **칸 내용의 최소 너비가 제 몫보다 크면 그 열이 밀려 넓어진다**. 칩이 nowrap 이라
      긴 칩이 든 요일만 넓었다 → `repeat(5,minmax(0,1fr)) repeat(2,minmax(0,.5fr))`
      (평일 5칸 동일·주말 절반, 주말 일정은 18개월 196건 중 **0건**이라 안전).
      칩은 잘라내지 말고 접는다(`keep-all` + **`break-word`** — `anywhere` 는 아무 데나
      끊을 자리를 만들어 `~` 를 혼자 다음 줄로 떨어뜨렸다). 한글↔`~` 경계는
      **WORD JOINER(U+2060)** 로 막는다(줄바꿈 규칙상 끊을 수 있는 자리라 keep-all 로는 안 됨).
    - **PPI 가 10/14 로 틀렸다** — `fixed_dates.json` 에 11·12월만 있고 10월이 빠져
      규칙(`around: 14`)이 추정한 값이었다. BLS 공식 일정으로 **10/15(목)** 확인해 넣고,
      CPI·PPI 2027년 초(1/13·1/14·2/11·2/12)도 함께 채웠다. **고용보고서 2027년은
      BLS 가 아직 미공표라 넣지 않았다** — 규칙이 2027-01-01(신정)을 찍지만 추측해
      박으면 틀린 날짜가 사실처럼 보인다(33번 교훈). `_sources` 에 사정을 적어뒀다.

39. **컨센 추적 — QoQ/YoY 칼럼 + 확정 실적(A) 수집** (10/14): "2027E가 2026E 대비 YoY 얼마냐"를
    화면에서 바로 보이게. 분기 탭(3Q26 등)에 QoQ·YoY, 연간 탭에 YoY 칼럼 — 같은 스냅샷 내
    비교(기준 변경과 무관), 분모 적자면 흑전/적지, 분자만 적자면 적전 표기.
    - 분모가 없어서 수집을 넓혔다: 모바일 분기 API의 **실적(A) 분기**와 연간 그리드의
      **실적(A) 연도**를 `quarter_actual`/`annual_actual` kind로 함께 저장(스키마 변경 없음 —
      kind 값만 추가). 성장률은 실적(A) 우선, 실적 수집 전엔 같은 스냅샷의 컨센(E) 대비.
    - 내년E YoY(vs 올해E)는 기존 데이터로 즉시 표시. 3Q26 QoQ(vs 2Q26)·YoY(vs 3Q25)와
      올해E YoY(vs 2025A)는 실적이 처음 수집되는 다음 run부터. 엑셀에도 같은 칼럼 추가.
    - `tests/test_growth.py` 신설(가짜 네이버 응답으로 fetch_quarters A/E 분리·growth 산식·
      비분기 열 필터 검산 — 컨테이너는 네이버 차단이라 valuation과 같은 방식).

40. **컨센 추적 — fwd 분기 수집 (3Q26·4Q26·1Q27)** (10/15): 분기 E가 당분기 하나뿐이라
    '다음분기' 탭이 늘 비던 문제. 러너 프로브 2회로 소스 특정 — 모바일 분기 API는 E를
    당분기 1개만 주고(count 파라미터 무시), FnGuide는 러너 IP 차단. **이미 종목마다 여는
    컨센서스 탭(c1050001) 재무연월 그리드에 연간/분기 토글이 있고 분기 모드에 fwd 3개 E가
    전부 있다** → `scrape_wisereport()`가 한 페이지에서 연간+분기 둘 다 파싱.
    - **토글 상태는 세션에 들러붙는다**(한 종목에서 분기를 누르면 다음 종목 페이지도 분기로
      열림) — 종목마다 '연간 클릭→파싱→분기 클릭→파싱'으로 모드를 명시하고, 모드 판정은
      그리드에 03/06/09월 행이 있는지로 대기(_GRID_MODE_JS). 연간 kind에 비12월 행이
      섞이면 토글 회귀다.
    - E2E 검증은 러너에서 run_snapshot --limit 6 실측(삼성전자 3Q26E가 모바일 API 값과
      일치, 연간 혼입 0). 전체 run이 ~25분→토글 2회 추가로 늘어 timeout 35→60분.
    - 다음분기 탭·QoQ/YoY(4Q26 vs 3Q26E·4Q25A)·엑셀 다음분기 열이 첫 수집부터 채워지고,
      분기 시점 ▶로 4Q26 앵커(다음분기 1Q27)까지 이동 가능해진다.

41. **ETF 신호판 — RSI를 메인 지표로 추가** (10/13): 사용자 지정 규칙 그대로
    **RSI(14) 30 이하로 내려선 첫날 = 매수, 70을 위에서 아래로 뚫은 날 = 매도.**
    우선순위 ① RSI ② 스토캐스틱 ③ ADX — 화면(상단 'RSI 신호' 섹션·타일·표 RSI 열·
    10영업일 누적 맨 위·차트 ■ 마커)과 텔레그램(일간·일요 누적 맨 위) 모두 RSI가 먼저.
    - `etf_signal.rsi()`(Wilder, ADX와 같은 alpha=1/n 평활) + `cross_events(..., r)`의
      `rsi_buy`/`rsi_sell`. 30 아래 머무는 동안 매일 뜨지 않게 '내려선 첫날'만 이벤트.
    - 알림 플래그 `alert_rsi_buy/sell` = 이벤트 + 유동성(5억)만. 수급 필터 없음
      (과매도 구간은 개인이 받는 게 보통이라 '개인몰림 제외'를 걸면 대부분 지워진다).
      **등급(B 이상) 필터도 면제** — `etf_telegram._keep(s, flag)`가 RSI 플래그는 통과.
    - 백테스트(`backtest.py`)에 RSI 30이하 진입·70 하향이탈·30 상향복귀(참고) +
      ADX20 방향별 분리 추가. **아직 미실행** — etf-backtest.yml은 결과를 main에 push하므로
      main 머지 후 main에서 돌릴 것(브랜치에서 돌리면 브랜치 커밋이 main으로 간다).
      참고: 8/18 백테스트에서 같은 계열(스토캐스틱 과매도반등)은 초과수익 ≈ 0이었다.
    - `etf_signal/tests/test_rsi.py` 7개(극값·첫날만·70 하향이탈·횡보 무신호·차트 마커),
      etf-signal·etf-backtest 워크플로에서 매번 실행.
    - **백테스트 결과 → RSI 매도 강등 + 매수 '1주 단기' 표기** (10/15, 2023-10~2026-10·48종목):
      RSI 30 이하 진입 D+5 초과 **+0.92%p·승률 66%**(N=284, 판에서 최고) / D+20 −0.25%p →
      **1주 단기 반등용**. RSI 70 하향이탈은 D+5 +0.98%p·D+20 +1.04%p(N=670)로 **역방향** —
      스토캐스틱 과열이탈과 같은 이유(모멘텀 지속)로 `alert_rsi_sell` 삭제, `ev_rsi_sell`은
      표 '70↓참고' 배지·차트 마커로만. 30 상향복귀형은 D+20 −1.38%p로 진입형보다 못함.
      문구 정본은 `etf_telegram.RSI_BUY_NOTE` 하나(화면이 import). 이번 run은 KIS 토큰
      403으로 6종목(반도체3·로봇2·인터넷) 누락 — 토큰 발급이 다른 잡과 겹친 것으로 추정.

42. **매크로 데스크 '장 시작 전' + 비번 화면 안내** (10/15): PR #348·#353.
    - **개장전 코멘트를 화면에도** — `source_watcher` 가 한화 임혜윤 <개장전 5가지>를
      이미 받고 있었는데 **쏘기만 하고 본문을 안 남겼다**(`seen.json` 은 본 ID뿐).
      `source_watcher/premarket.py` 가 **텔레그램에 나간 글만** `state/premarket.json` 에
      적고(수집분 전부가 아니라 **보낸 것만** — 유튜브 3일 모음과 같은 원칙),
      매크로 데스크 맨 위 `🌅 장 시작 전` 섹션이 띄운다. 켜는 스위치는 `premarket: true`
      (태그 `개장전` 과 따로 두는 이유: 태그는 표시용, 이건 저장 여부를 가른다).
    - **이 데이터만 런타임 fetch 한다.** 매크로 페이지는 **저녁 9시 한 번** 구워지는데
      개장전 글은 **아침 7시대**에 온다 → 페이지에 박으면 아침에 열었을 때 반드시
      어제 글이 보인다. 파일만 따로 나르면 `deploy-pages` 09:10 배포부터 그날 글이 보여
      **GAS 슬롯 추가도 아침 재수집도 0**. 시계열(36번)은 페이지와 같은 주기라 박는 게
      맞았다 — **갱신 주기가 페이지와 다른 데이터만 런타임으로 뺀다**가 기준이다.
    - **시각은 `Intl` 로 KST 고정** — `new Date(...).getHours()` 는 보는 기기의 시간대라
      07:36 글이 컨테이너(UTC)에서 `10/14 22:36` 으로 찍혔다(실측). 못 읽으면 섹션을
      **접고** 안내문을 남긴다('불러오는 중…' 이 영영 떠 있으면 고장으로 보인다).
    - **키움 한지영 <장 시작 전 생각>은 채널 아이디 없이 잡는다.** 공개 검색으로 채널을
      확인할 수 없었고(사칭 다수) 추측해 넣으면 안 되는데, `source_watcher` 에 이미
      **구독 중인 방 전체를 훑는** `type: telegram_account`(조선 `ship_all` 이 쓰는 것)가
      있었다 → `match_any: ["장 시작 전 생각"]` 만으로 끝. 새 시크릿·새 코드 0,
      채널을 옮겨도 계속 잡힌다. 여러 방이 퍼나른 같은 글은 `dedupe_scope: premkt` 로
      한 번만. `push` 는 종류 기본값(`telegram*` → `full`)이라 본문 통째, `route` 가
      없으니 **한화와 같은 기본 봇**으로 간다 — 두 소스를 같은 모양으로 쓰려면
      **기본값을 먼저 확인할 것**(새 필드를 더할 일이 아니었다).
    - `record` 는 파일을 통째로 다시 쓴다 → **소스가 둘이 되는 순간** 한쪽을 적을 때
      다른 쪽 글이 날아가는지 테스트가 필요하다(`tests/test_premarket.py` 14개, 소스
      감시 워크플로가 `discover` 로 자동 포함).
    - **비번 화면 안내문**: 제목 아래 '비밀번호는 GS최 님에게 문의하세요.' 한 줄.
      같이 고친 것 — 오류 메시지를 `querySelector("p")` 로 잡고 있어 **안내문이 첫
      `<p>` 가 되자 오류가 뜰 때마다 안내문을 덮어썼다** → `p[data-err]`.
      `gate.py` 는 빌드 때 전 페이지에 주입되므로 `deploy-pages` 한 번으로 435개 반영.

43. **건기 전략 레이더 신설 — 신제품·CAPEX·M&A 누적 대시보드** (10/17): 건설기계 브리핑에서
    잡히는 뉴스 중 ① 신제품 출시 ② CAPEX(공장 신설·증설) ③ M&A·지분·장기 파트너십을
    따로 떼어 계속 쌓는 페이지(방산 수주 파이프라인/LNG FID와 같은 발상). 사용자 요청.
    - 데이터 정본 `static/construction_strategy/events.json` — **static 밑에 두는 이유:
      claude-brief-ingest 가 static 경로만 main 으로 나르므로** 세션 브랜치의 이벤트 추가가
      데이터째 main 에 보존된다. 렌더러 `construction_briefing/strategy_tracker_publish.py`
      → `static/construction_tracker.html`(카테고리 탭 필터·월 구분·근거 브리핑 링크 — lng/dc/defense_tracker 와 같은 *_tracker.html 주소 가족, 브리핑 인덱스 상단 📌 버튼).
    - 운영: 아침 루틴 [7.7] — 그날 건기 뉴스에서 세 분류 이벤트가 있으면 events.json 추가
      (같은 사건의 후속 보도는 새 줄 금지, 기존 항목 note 갱신) → 렌더 → 건기 3종 커밋에
      동승 → ingest 가 main 반영. 이벤트 없는 날은 무동작(억지로 채우지 않는다).
    - 사이드바 `🏗️ 글로벌건기.브리핑 > 📌 ┗건기.전략레이더`, build_static 복사,
      ingest 경로 2개 추가. 백필: 8/20~10/16 아카이브에서 19건 큐레이션(Fabick 인수·
      BHP-Liebherr·DX77/군산·DX300LC-9·CAT 인도 3종 등).
    - **딜러망 카테고리 추가** (10/17, PR #362): 사용자 요청 "각사 딜러망 확대도 —
      특히 HD건설기계·두산밥캣" → ③ 🏪 딜러망(cat=dealer) 신설(순서 신제품·CAPEX·
      딜러망·M&A). CAT-Fabick은 ma→dealer 재분류(M&A형 직영화 note 유지), 백필 5건
      추가(HD 아프리카·중남미/칠레 광산 거점/인니 부품망/Manitou 크로스-배지+북미
      딜러망 이원화, JCB 캔자스시티) — 총 24건. **두산밥캣 딜러망 뉴스는 아카이브에
      아직 0건** — 루틴 [7.7]에 'HD건기·두산밥캣 딜러망 건은 빠짐없이' 명시.

44. **방산 브리핑 조선 범위 규칙** (10/17, PR #363): 사용자 규칙 — 방산 브리핑의 조선은
    **글로벌 군함·잠수함·함정 MRO·해군 조달 수주전만** 다루고 **상선(LNG선·컨테이너선·
    탱커)·해양플랜트는 제외**(한화오션·HD현중도 방산 부문만). 종전엔 가드가 없어 한국어
    쿼리(한화오션·HD현대중공업)로 들어온 상선 기사가 해군·조선 섹션에 실렸다(10/16
    고망간강 화물창 건 실측). 반대로 군함 수주전은 전용 쿼리가 없어 TKMS 등 유니버스 밖
    경쟁사 낙찰 건은 우연히만 잡혔다. → NEWS_QUERIES에 함종·조달 축 영어 쿼리 추가
    (submarine/frigate/destroyer/warship/naval shipbuilding × contract/procurement/tender…),
    SYSTEM_PROMPT(제미나이판)·FORMAT_NOTE(RSS판 inputs)에 범위 규칙 명문화. 웹서치판·
    통합본은 트리거 프롬프트 [3]에 같은 규칙(통합 때 원 판에 섞인 상선 기사도 걸러냄).

45. **글로벌 수상함·잠수함 입찰 트래커 신설** (10/17): 방산 입찰·예산 트래커와 별도로,
    각국 해군 함정 수주전만 프로그램 단위로 추적하는 전용 대시보드(사용자 요청 — 44번
    조선 범위 규칙의 짝). `static/naval_tracker.json`(데이터 정본, 세션이 직접 큐레이션 —
    ingest가 main으로 나름) + `static/naval_tracker.html`(defense_tracker와 같은 런타임
    fetch 페이지, 렌더 스크립트 없음 — html 수정은 PR로만). 필드는 defense_tracker
    tenders와 동일 + `type`(수상함|잠수함|혼합, 페이지 상단 세그먼트 필터), 특정 입찰에
    안 붙는 판 구도 변화(TKMS-Navantia 연합 등)는 `landscape` 배열로 분리.
    - 운영: 아침 루틴 [6.7] — 그날 방산 3판에서 함정 수주전 보도를 프로그램 log에 추가
      (모르는 값은 '미정'/'—', 추정 금지 — 34번 교훈), 새 수주전은 programs 신설, [6.5]
      커밋에 동승. 이벤트 없는 날 무동작.
    - 백필 9개 프로그램(8/13~10/17 아카이브): 진행 — 태국 호위함(HD현중 우협 6,833억원·
      내각 승인 단계)·덴마크 프리깃(Babcock A140)·콜롬비아 현대화(한국 2사 접촉)·폴란드
      Orka·필리핀 잠수함(이상 한화오션 거론); 종료 — 캐나다 잠수함(TKMS 선정·한화오션
      탈락)·이탈리아 DDX(OSN €3.7bn)·독일 F126(취소)·KDDX(한화오션 7/31 본계약 8,380억원).
    - 진입점 3곳: 방산 브리핑 인덱스 2종(데일리·통합)의 ⚓ 알약 버튼(기존 📌 옆,
      `.trk+a.trk{margin-left:0}`), 사이드바 방산 서브메뉴 `⚓ ┗수상함·잠수함.입찰`,
      defense_tracker ↔ naval_tracker 상호 헤더 링크. build_static 복사·ingest 경로 추가.
    - **방산 입찰·예산 트래커와 중복 정리** (10/17 2차): defense_tracker.json의 함정 5건
      (이탈리아 DDX·캐나다 CPSP·폴란드 Orka·노르웨이·스웨덴 호위함)을 naval 쪽으로 이관·
      병합하고 tenders에서 제거(+태국 inbox 1건). 병합 과정에서 **naval 백필 오류 2건 교정**
      — 태국 호위함은 HD현중이 아니라 **한화오션**(9/10 아카이브 원문 재확인, 푸미폰함
      건조사; 10/16 신임 해군총장 재검토 지시로 난항 로그 추가), 폴란드 Orka는 '발표 대기'가
      아니라 **2025.11 Saab A26 기선정**(한화오션 탈락 — 브리핑들의 '폴란드 잠수함' 촉매
      거론과의 관계는 [상충]로 note에 남김). defense_tracker.html에 분리 안내문+⚓ 헤더
      링크(이쪽 방향이 빠져 있었음), defense_tracker_update.py Gemini 프롬프트에 함정 제외
      규칙 추가(안 막으면 inbox에 함정 건이 계속 쌓임).

46. **커버리지 기업 수급/기술적 지표 신설** (10/17): `coverage_flow/` — 조선·방산·건설기계
    커버리지 16 + 커버예정 5(동성화인텍·세진중공업·현대힘스·성광벤드·태광) = 21종목(`universe.csv`, 사용자 지정 목록, status 열로 구분)의 ① 외인·기관 순매수(5일 합산,
    **시총 대비 %** 로 정렬, 연속일수, 오늘 잠정) ② 기계적 수급 — 섹터 ETF 7개(`etf_universe.csv`:
    SOL 조선TOP3플러스·TIGER 조선TOP10·KODEX K조선TOP10·HANARO Fn조선해운·PLUS K방산·
    TIGER K방산&우주·KODEX 기계장비) **상장주수 변동 × 가격 × Top10 비중 = 패시브 추정(하한값)**
    + 액티브 ETF 계약수 변동(`etf_holdings/changes.json` 재사용) ③ RSI(14) 잠정/확정 + **1년
    백분위 극단**(하위·상위 5%) + 52주 위치. 다올 의료기기 수급 브리핑 형식을 따랐다.
    - 평일 장중 3회 **10:00 · 13:30 · 15:30** — GAS 시계 `covflow` 슬롯 3개가 정시(via=scheduler),
      `coverage-flow.yml` 크론은 안전망(guard: 슬롯 경계 11:45/14:30, 자기 제외·fail-open, 24번 방식).
      휴장일은 collect.py 가 네이버 지수 API 거래일로 스스로 생략(30번 방식).
    - 텔레는 평문 한 통. 봇 토큰 COVFLOW_TELEGRAM_BOT_TOKEN → TELEGRAM_BOT_TOKEN(수주공시 봇),
      채널 COVFLOW_TELEGRAM_CHAT_ID → TELEGRAM_CHAT_ID_PRIVATE. **공개채널(TELEGRAM_CHAT_ID)로는
      폴백하지 않는다**(첫 테스트가 공개채널로 간 뒤 사용자 요청으로 제외; 비공개 채널은 봇을
      관리자로 넣고 `-100…` ID 를 시크릿에). 발송은 정시 실행에만(schedule·via=scheduler·
      force_telegram) — 화면 `🔄 지금 수집` 은 페이지만.
    - 소스는 전부 한투 OpenAPI(일봉·투자자별·현재가/시총/상장주수/외인보유비율, etf_signal 과 같은
      키) + 네이버 etfAnalysis(ETF 비중, etf_holdings 와 같은 엔드포인트). 컨테이너에선 둘 다 못
      불러 `tests/test_metrics.py` 19개(슬롯·RSI 잠정/확정·백분위·5일 창·패시브 산식·상장주수
      직전값·액티브 필터·KIS 응답 변환·텔레 문안·렌더)로 검산, 워크플로가 매번 돈다.
    - **5일 창은 오늘 잠정 행 포함**(빼면 장중 3통이 전부 같아진다) · **패시브 직전값은 오늘이
      아닌 가장 최근 날짜**(같은 날 두 번째 슬롯도 전일 대비 = 하루 누적) · 첫 수집은 설정·환매
      비교 불가라 '다음 거래일부터' 로 적는다 · ETF 코드가 틀려 엉뚱한 종목이 오면 이름 키워드로
      걸러 오류 목록에 남긴다(조용히 섞이지 않게).
    - 사이드바 `🦿 업무자동화 > 📡 커버리지 기업 수급/기술적 지표`(피어그룹.Valuation 밑),
      산출물 `static/coverage_flow_report.html` + `coverage_flow/data/latest.json`(+history 30일).
      deploy-pages workflow_run·build_static 복사 추가. **GAS 재붙여넣기 필요**(WF covflow +
      SCHEDULE 3슬롯; '배포 관리 → 새 버전', 새 배포 금지).
    - **첫 실행 실측** (10/17 토, force): 종목 21/21·ETF 7/7·오류 0, 텔레 도착. 주식용
      inquire-price 가 ETF 에도 `lstn_stcn`(상장주수)·`hts_avls` 를 준다 — 첫 run 화면에
      상장주수가 비어 보인 건 per_etf 가 첫 수집 때 listed 를 안 실은 표시 문제였다(수정).
      프로브(`--probe-etf`)로 확인한 덤: KIS etfetn inquire-price 는 `etf_crcl_stcn`·
      `etf_cu_unit_scrt_cnt`(CU 50,000)·`etf_ntas_ttam`(순자산 억), 네이버 etfAnalysis 는
      `cumulativeNetInflowList`(1d/1w/1m 순유입 억, 기준일 하루 지연) 를 준다 → 순유입은
      ETF 표에 교차 확인 열로 추가(`metrics.parse_eok` 가 '1조 1,560억' 을 억으로).
      실측 버그 둘: rsi_pctl 0.0 을 `or 50` 이 '없음' 으로 읽어 1년 최저가 목록 중간으로
      갔던 것(30번 부류 — 0 은 값이다), 토요일 force 에서 금요일 종가가 '오늘 잠정' 으로
      붙던 것(거래일이 오늘일 때만 잠정 봉). 패시브 추정은 10/19(월) 첫 슬롯부터 채워진다.
    - **수주공시 폼도 바담 방으로** (10/17 저녁): 대시보드 '조선 수주공시 → 텔레' 폼이 늘 공개채널로
      가던 것을 비공개 바담 방 기본으로. dart-shiporder-bot.yml target 에 '비공개(바담)' 옵션
      (기본값) 추가 — chat_id 는 BADAM_TELEGRAM_CHAT_ID → COVFLOW_TELEGRAM_CHAT_ID 재사용(같은 방).
      app.js 폼이 target 을 명시해 보내므로 GAS 재붙여넣기 없이도 바담으로 가고, GAS 정본의
      기본값도 바담으로 맞춤. 공개채널은 Actions 에서 대상을 직접 고를 때만.
    - **텔레 = 본문 + 화면 캡쳐 앨범, 링크 없음** (10/17 저녁): 대시보드 주소(반비공개, 리네임
      운영)를 채널에 남기지 않으려 본문의 링크를 빼고 `capture.py`(Playwright, 수주공시 봇과
      같은 방식)가 페이지를 **섹션 3장**(`#cap-1` 제목+타일+①수급 / `#cap-2` ②기계적 수급 /
      `#cap-3` ③과매수·과매도)으로 찍어 `sendMediaGroup` 앨범으로 보낸다. 한 장(2000×6400)으로
      찍으면 텔레그램이 399×1280 으로 줄여 글자가 안 읽혔다(실측) — 장당 세로/가로 ≤ 3 유지.
      캡쳐 실패는 본문 발송을 막지 않는다(continue-on-error). 컨테이너 검증은
      `/opt/pw-browsers/chromium-*/chrome-linux/chrome` 을 executable_path 로(36번 교훈).
      사용자 대안 2안("링크는 두되 주소를 가리기")은 텔레그램이 링크 미리보기·탭 시 도메인을
      드러내 사실상 불가능해 채택하지 않았다.
    - **등락률·투자자별 5구간 + 메뉴명** (10/19 새벽): 사용자 요청으로 ① 등락률(오늘·1주·1개월·
      3개월·YTD — `metrics.returns`, 거래일 5/21/63 오프셋·전년 마지막 종가) 표와 ①-2 투자자별
      순매수(외인·기관·개인 × 오늘·5일·1개월·3개월·YTD — `metrics.flow_windows`) 표로 개편,
      '5일 외인+기관 시총 대비' 열 삭제(텔레 본문의 '사는 쪽/파는 쪽' 랭킹엔 그대로 씀).
      메뉴명 `📡 커버리지 수급 등`. **수급 이력 소스 프로브**(`--probe-flow`, 러너 2회):
      한투 inquire-investor 는 **30행**(≈1개월)뿐 → 3개월·YTD 는 네이버 구 모바일 API
      `/api/stock/{code}/trend?pageSize=60` — **pageSize 상한 60, page 무시, `bizdate=` 커서**로
      그 날짜 이전 60행씩 뒤로(실측 bizdate=20260720 → 7/16~4/20), front-api 쪽
      `/stock/domestic/trend?reutersCode=` 는 400. 네이버는 **순매수 수량**만 주므로 금액은
      수량×종가/1e8 **근사**(`kis.naver_trend_frame`), 같은 날짜는 한투 금액 우선
      (`kis.merge_investor`), 표 각주에 근사 명시. 전년 12/31 이전 행이 나올 때까지 긁어
      (`naver_investor_history`, 최대 8페이지) YTD 판정이 서게 한다. 네이버 실패 시 한투
      30행만으로 오늘·5일·1개월은 그대로. 이력이 모자라는 구간은 '–'(30번 교훈).
    - **화면 손질** (10/18): ① 등락률 표를 오늘·1주·1개월·3개월·YTD(거래일 5/21/63 오프셋, YTD 는 전년
      마지막 종가 대비) + **3개월 스파크라인**(인라인 SVG, 수집 때 `spark` 63개 종가를 payload 에 박음 —
      다음 수집부터 표시) 으로, '5일 외인+기관 시총대비' 열은 삭제(텔레·타일 순위에는 계속 사용).
      투자자별 순매수는 외인·기관·개인 × 오늘·5일·1개월·3개월·YTD. 넓은 화면은 `max-width:1180px`.
      섹션 순서 ① 등락률/수급 → **② 과매수·과매도** → **③ 기계적 수급(접힘 `<details>`)** —
      캡쳐는 details 를 전부 펼친 뒤 찍는다. 표 3개는 **조선(조선+조기)·방산·기계 묶음 헤더 행**
      (`build_report.grouped`), 묶음 안은 기존 정렬이되 **성광벤드·태광은 조선 묶음 맨 밑 고정**(사용자
      지정, `PIN_LAST`). 장 시작 전 run 은 외인 보유비율 0.00 도 None 으로(한투가 0 을 준다).
    - **조건부서식 음영** (10/19): 등락률·투자자별 순매수 표 셀에 엑셀식 음영 —
      열별 최대 |값| 대비 강도(`build_report.shade`/`col_caps`), 양수=초록·음수=빨강
      (.pos/.neg·스파크와 같은 서구식 체계 유지). 알파 0.08~0.34 — 다크모드·텔레 캡쳐
      축소에서도 켜짐/꺼짐이 구분되는 하한. 0·결측·열 전체 결측(cap 0)은 음영 없음.
    - **외인 보유비율 전일값 이월** (10/19): 장 전·휴장 run 에서 비던 외인보유를 직전
      latest.json 값으로 채운다(`collect.backfill_frgn`, LATEST 덮어쓰기 전에 읽음).
      이월분은 `frgn_pct_asof` 에 기준일을 남기고 화면에 `12.34% 10/16` 처럼 작게 병기
      (당일 실측은 날짜 없음), 연쇄 이월은 원 기준일 승계. **직전 값이 0 이면 이월 금지** —
      옛 코드가 남긴 '가짜 0'(장 전 한투 응답)과 진짜 0 을 소스가 구분해 주지 않아서,
      이월하면 모름이 0.00% 로 둔갑한다(30번 부류). 직전도 없으면 '–' 그대로.
    - **색 체계를 한국식으로 전환** (10/19, 바로 위 음영과 같은 날 두 세션이 충돌 — 이 쪽이 최종):
      사용자 요청 "좋은 거 빨강, 나쁜 거 파랑". 전역 `.pos`/`.neg` 를 **빨강/파랑**으로, 스파크라인·
      연속일수 배지·RSI 과매수/과매도·`shade` 음영도 같은 축(알파 0.08~0.45). 시총·상장주수처럼
      부호 없는 숫자는 색을 안 준다(`n(sign=False)`). 위 항목의 '서구식 초록/빨강' 서술은 폐기.
    - **수집 실패 가드 2단 + 수집 시각 표기** (10/19): 10:04 run 이 한투 토큰 403 으로 21종목 중
      2종목만 모은 화면을 바담 방에 보낸 뒤 사용자 규칙 — ① **오류가 하나라도 있으면 텔레그램 생략**
      (`notify.main`, 종목·ETF 오류 모두, status 에 skipped 사유. 페이지는 오류 목록과 함께 갱신되므로
      거기서 본다) ② 성공 종목이 **70% 미만**(`collect.enough`, `COVFLOW_MIN_OK_RATIO`)이면 latest.json·
      페이지도 덮어쓰지 않고 종료코드 2 — 직전 정상 페이지가 남고 run 은 실패로 찍혀 늦은 크론이
      재시도한다(guard 는 성공 run 만 센다). ① 등락률 표 위에 `📅 수집 시각 … · 장중 잠정/직전 거래일
      종가 기준` 한 줄(사용자 요청). 테스트 34 → 37개.
    - **표 정렬 = 시총 순** (10/19): 사용자 요청으로 세 표(등락률·투자자별 순매수·과매수/과매도)의
      묶음 안 정렬을 각자 기준(오늘 등락·외인 5일·RSI)에서 **시총 내림차순**(`build_report.mcap_key`)
      으로 통일. 성광벤드·태광 조선 맨 밑 고정은 유지.
    - **텔레 머리글 볼드** (10/19): 사용자 요청. `notify.compose_html` 이 평문(compose)의 첫 줄만
      `<b>` 로 감싸고 나머지는 전부 escape(LIG D&A 의 & 안전) → `parse_mode=HTML` 로 발송,
      텔레그램이 parse 오류를 돌려주면 평문으로 폴백. 테스트 38 → 39개.
    - **본문을 앨범 캡션으로 — 사진 밑에** (10/19): 사용자 요청 "텍스트가 이미지 밑에 붙게". 캡쳐가 있고
      본문(compose_html)이 **1,024자**(일반 봇 캡션 한도, `CAPTION_MAX`) 이내면 sendMediaGroup 첫 장
      캡션에 HTML 로 실어 한 덩어리로 보낸다(현재 ~650자). parse 거부 → 평문 캡션, 그래도 실패 →
      옛 방식(본문 따로 + 사진). 캡션 한도를 넘거나 캡쳐가 없으면 본문 따로. 테스트 39 → 40개.
    - **텔레 섹션 제목 볼드 + 이모티콘** (10/19): 사용자 지정 — 머리글 `[GS🎴 조선·방산·건기]`,
      `📈 사는 쪽` · `📉 파는 쪽` · `⚙️ 기계적 수급 (ETF/패시브)` 세 섹션 제목을 볼드
      (`notify.SECTION_HEADS` 접두어 매칭, compose_html). RSI 섹션은 요청에 없어 그대로.
    - **평일 16:00 하루 1회로 축소** (10/19, PR #404): "하루 3번은 너무 많다" — GAS covflow
      슬롯 3개 → 16:00 하나(재붙여넣기 필요), 크론 1개(16:05)·guard 15:30 이후 단일 창,
      decide_slot 은 상시 "16:00"(수동 수집도 같은 슬롯). 장 마감 후라 당일 수급이 사실상
      확정 집계. 같은 날 오전엔 KIS 토큰 발급 403(분당 1회 제한, market-flow 와 동시 시작)
      으로 19/21종목이 누락된 사고가 있었다 → token() 이 403 이면 20초씩 분 경계를 넘겨
      재발급(PR #395, etf_signal 에도 동일 적용 — 41번 백테스트 6종목 누락의 원인이 이것).
    - **하루 2회 — 13:00(장중) + 16:00(장 마감 후)** (10/20): 10/19 '하루 1회 16:00'(PR #404)에서 사용자
      요청으로 변경. `metrics.decide_slot` 은 **14:30 경계**(`SLOT_BOUNDARY`)로 13:00/16:00 슬롯을 가르고
      (수동 수집도 시각으로 슬롯에 붙음), 크론은 04:05·07:05 UTC 안전망, guard 는 현재 시각으로 슬롯을
      정해 창 시작(12:30/15:30 KST)부터 센다 — 13:05 크론이 14:30 을 넘겨 도착하면 16:00 슬롯 '정시 전'
      으로 버려지고 16:05 크론이 맡는다. GAS `covflow` hours [13, 16] — **재붙여넣기 필요**.
    - **섹터 요약 행** (10/20): 사용자 요청 — 등락률 표는 묶음 끝에 `조선 평균`(**단순평균**, None 제외,
      시총은 합계), 투자자별 순매수 표는 `조선 합계`(투자자×구간 **합계**). `build_report.agg`,
      `tr.sub` 스타일. 음영은 종목 열과 같은 cap 이라 합계 행은 포화되는 게 보통. 테스트 40 → 41개.
    - **장중 '오늘' 수급 = 한투 추정가집계** (10/20): 일별 투자자 API(inquire-investor)는 **장중엔 당일 행을
      0 으로 내준다**(10/19 11:00·13:35 전 종목 0, 15:35 에 11/21 채워짐 — 실측) → 화면·텔레 '오늘' 이 전부
      +0 이었다. 종목별 **외인기관 추정가집계**(`investor-trend-estimate`, HHPTJ04160200 — KRX 잠정 집계
      09:30·10:00·11:20·13:20·14:30)의 최신 시각 행으로 오늘 행을 채운다(`kis.parse_estimate` 느슨한 키
      매칭 → `metrics.apply_estimate`: 수량×현재가/1e8 근사, 개인 = −(외인+기관), **당일 행이 이미 0 이
      아니면 손대지 않음**). `flow.today_src` 에 `estimate HH:MM`/`daily`, 화면 각주·텔레 머리 줄에
      '가집계 HH:MM' 표기. 응답 키는 문서 기준이라 **`probe_estimate` 입력으로 러너에서 원본 확인 필요**
      — 키가 다르면 parse_estimate 만 손본다(실패 시 종전처럼 0/없음). 테스트 41 → 44개.
    - **텔레 RSI 섹션 볼드+🌡️ · 섹터 평균/합계 행 굵게** (10/20, PR #421): 사용자 요청. 요약 행 라벨이
      문단용 `.sub` 색 규칙(--muted)을 물려받아 회색으로 찍히던 것 교정, 굵기 800·위아래 진한 구분선.
      **글자 크기는 키우지 않는다** — 14px 로 올리자 투자자별 표의 종목 칸이 좁아져 'HD현대중공업' 이
      5줄로 쪼개졌다(실측). 16:17 앨범엔 요약 행이 이미 있었고 13:24 앨범(PR #416 머지 전)에 없었던 것.
    - **추가 방(DAOL 조선) 동시 발송** (10/20): 사용자 요청 "바담 방에다가 DAOL 조선 방에도". 시크릿
      `COVFLOW_TELEGRAM_CHAT_ID_EXTRA`(쉼표로 여러 개, 공개채널은 `@handle` 가능 — 같은 봇이 그 방에
      있어야; **미설정 시 워크플로 기본값 `@HI_GS`** = 공개채널 'DAOL 조선/기계/방산 | 최광식', 사용자 확정) → `notify.targets()` = 기본 방 + 추가 방(기본과 같은 ID·중복 제거). **추가 방은 공유용 2장**
      (`capture.SHARE_SECTIONS` `#cap-1a` 제목+타일+① 등락률 / `#cap-1b` ①-2 투자자별, 파일 `data/share_*.png`
      — `capture_*.png` 글롭과 섞이지 않게 접두어를 달리) + **캡션은 머리글 볼드 + 공유 링크**
      (`SHARE_URL` = gs-research-desk.github.io/coverage_flow_report.html)만. 기본 방(바담)은 종전 그대로
      3장+본문. 추가 방 실패는 종료코드를 안 바꾼다(바꾸면 늦은 크론 재시도로 바담에 두 통). 공유용
      그림이 없으면 추가 방도 기본 묶음 폴백. status.json `extra[]` 에 방별 결과.
      **→ 같은 날 저녁 단순화(PR #425)**: 사용자 확정 "이렇게 2개 이미지만 남기자 내일부터" — 앨범은
      **두 방 모두 2장**(`capture.SECTIONS` = `#cap-1a`·`#cap-1b` → capture_1·2.png)으로 통일, ② 과매수·
      과매도·③ 기계적 수급 캡쳐(capture_3)·share_* 파일·`--share` 플래그 삭제. 캡션만 다르다 — 바담 = 본문,
      DAOL 조선 = 머리글+링크. **→ 다시(PR #426, 사용자 "왜 글이 없어? 원래 그 글도 넣어, 2개 방에 다")**:
      두 방 모두 2장 + 같은 본문 캡션 + **맨 밑에 공유 링크 한 줄(PR #427, "양방 모두 밑에 링크")** —
      10/17 '바담에 링크 없음' 규칙 폐기(공유용 주소는 드러내도 되는 주소). share_caption/_deliver_share
      삭제 — 경로는 `_deliver` 하나. 캡션 한도는 `visible_len`(태그·이스케이프 제외) 기준.
    - **텔레 본문에서 RSI 섹션·각주 제거** (10/20 저녁, PR #428): 사용자 "rsi 이하는 빼자". 본문은
      사는 쪽/파는 쪽/오늘(잠정)/기계적 수급까지 + 맨 밑 공유 링크. RSI 극단은 화면 ② 표에만 남는다.
      `SECTION_HEADS` 에서 🌡️ 제거. 덤으로 캡션이 ~400자 줄어 1,024 한도 여유가 생겼다.
    - **11:30 · 16:00 으로 변경** (10/21, PR #429): 사용자 "11시30분 16시로 하자". `metrics.SLOTS`
      [("11:30","13:45"),("16:00","24:00")]·경계 13:45, 크론 02:35/07:05 UTC, guard 창 11:00/15:30 KST,
      GAS covflow 는 분이 달라 **두 줄**(11@:30, 16@:00 — FIRED 키가 wf@HH:MM 이라 따로 센다) —
      **재붙여넣기 필요**(GAS 스케줄러는 10/20 09:19 이후 멈춰 있어 어차피 복구가 필요한 상태).
    - **정시 발사를 GAS → Claude 예약 작업으로 이관** (10/26, PR #433): 사용자 "자동 발송 되게끔 바꿔야 함".
      GAS `tick` 이 10/20 09:19 이후 죽어 있는 동안 10/22·23 은 11:35 크론이 16:53 에 도착해 **11:30 분이
      통째로 빠졌다**(늦은 크론은 13:45 경계 때문에 16:00 슬롯으로 읽혀 그 슬롯만 처리, 16:05 크론은 guard 가
      스킵). → 이 클라우드 환경의 예약 작업 2개(평일 KST 11:32 / 16:02, `trig_01Ht8rHrhduJmpdmmJHeLz1w` /
      `trig_01Q6FbKD8DAFgby2siphnX2N`)가 **리포가 붙은 전용 세션 `session_01BBSTxgbzr2p9BsTdDR6dxj`
      (제목 '커버리지 수급 발송 스케줄러')에 묶여** `gh workflow run coverage-flow.yml --ref main
      -f via=scheduler` 로 쏘고 완료를 확인한다. 예약 세션엔 MCP 커넥터가 없어 **GitHub MCP 가 아니라 `gh`
      CLI**(환경 프록시 인증, dispatch 권한 실측)를 쓴다. 분을 :32/:02 로 둔 건 정각·반각 혼잡 회피.
      **첫 판(새 세션을 매번 여는 방식)은 10/26 11:32 첫 발사에서 실패** — 예약으로 열린 새 세션에는
      리포가 안 붙고 `add_repo` 도구도 없어 `gh` 가 403(테스트 발사 2회 실측). 리서치톤 예약과 같은
      `persistent_session_id` 방식만 된다(세션은 create_session 의 source_url 로 리포를 붙여 생성;
      예약의 세션 묶기는 사후 변경 불가라 예약을 새로 만든다). **전용 세션은 sonnet** — 리포가 붙으면
      이 CLAUDE.md(약 9만 토큰)가 매번 적재돼 fable 로는 한 번 깨우는 데 $1.9 가 들었다(실측), sonnet 은
      약 1/5. **fire_trigger(수동 발사)는 세션 묶기를 무시하고 새 세션을 연다**(리포 없음 → 403) — 묶인
      세션으로 가는 건 정시 발사뿐이라 검증은 정시 발사 결과로만 한다. 발사 메시지에 'TEST MODE' 가
      붙으면 `-f probe_estimate=true` 로 텔레 없는 프로브만 돈다.
      **GAS SCHEDULE 에서 covflow 두 줄 제거**(정본만 — Apps Script 재붙여넣기 전엔 옛 슬롯이 산다).
      크론 안전망(11:35/16:05)은 그대로.
      **첫 정시 발사 성공 + GAS 부활 중복** (10/26 16:00): 예약이 묶인 세션으로 들어가(발사 07:04Z,
      예약 07:02 에서 2분 지연) run 40283583968 이 두 방 모두 발송 성공. 그런데 **GAS tick 이 같은 날
      14:54 KST 부터 되살아나**(holdings :54/:19·market-flow 15:44 dispatch — 15:40 슬롯이 있는
      옛 SCHEDULE 이 돌고 있다는 뜻) 16:04:51 에 covflow 를 한 번 더 쐈고, 그 run 은 커밋 단계
      rebase 충돌로 죽어 텔레 중복을 **운 좋게** 면했다. → guard 를 `schedule || inputs.via ==
      'scheduler'` 로 넓혀 다른 시계의 정시 dispatch 도 같은 슬롯에 선행 성공 run 이 있으면 스킵
      (화면 버튼·force 는 그대로). 사용자가 GAS 를 재붙여넣으면 covflow 슬롯은 사라지지만, 가드가
      있으니 안 해도 두 번 안 간다. 다른 GAS 슬롯(시장수급 등)은 되살아난 옛 코드로 돌고 있다 —
      10/20 이후 바뀐 슬롯(수급 11:00/16:00 등)을 쓰려면 재붙여넣기 필요.
    - **공개방엔 링크 빼기** (10/28): 사용자 "공개방 DAOL 최광식에는 주소 남기지 말자". 맨 밑 공유 링크는
      기본 방(바담)만, 추가 방(@HI_GS 등)은 같은 2장 + 같은 본문에서 링크 줄만 뺀다(`notify.main`).
    - **지난 기록 보관** (10/28): 사용자 요청 "매일 4시 이후만, 한 달 지나면 월 2개". 16:00 슬롯·거래일
      수집이면 `build_report.write_archive` 가 그날 페이지를 `static/coverage_flow/<날짜>.html` 로 굽고
      (데이터를 박은 정적 페이지 — 화면이 나중에 바뀌어도 그날 모습 그대로), `archive_keep` 으로 정리:
      최근 31일 전부, 그 이전은 달마다 **15일 이전 마지막 거래일 · 월말** 두 개. 최신 페이지 맨 위(텔레 캡쳐
      영역 밖)에 날짜 고르기, 지난 기록 페이지엔 '← 최신 보기'. build_static 이 폴더째 복사. 크기는 장당
      ~88KB → 정상 상태 30여 장 ≈ 3MB. 10/20~10/27 은 history JSON(16:00) 6개로 소급 생성.
      덤으로 `.gitignore` 의 캡쳐 PNG 줄이 `\n…\n` 글자 그대로 들어가 무효였던 것 수정 — PNG 2장(~1.2MB)이
      매 run 커밋돼 git 이력에 쌓이고 있었다(10/26 rebase 충돌 파일에도 포함). 이제 잡 안에서만 쓰고 버린다.
    - **피팅 3사 → 기계 묶음** (10/28): 사용자 요청 "성광벤드·태광·하이록코리아도 기계로" —
      성광벤드·태광을 조기→기계로 재분류하고 하이록코리아(013030, 코스닥) 신규 추가(22종목).
      GROUPS 기계 = 건기+기계, '조선 묶음 맨 밑 고정'(PIN_LAST)은 폐기(장치만 잔존) —
      기계 묶음 안에서도 시총 내림차순. 하이록코리아 YTD·3개월 수급·스파크는 첫 수집부터.
    - **④ 위클리용 차트** (11/7): 사용자 요청 "위클리 '조선 수급' 꼭지처럼 4개 이미지". 리포트와 같은 모양
      (회사명 파랑 · 시가총액 십억원 좌축 검정 · 기관/외인 1년 누적 순매수 억원 우축 갈색/파랑 · 0 선 회색)을
      `build_report.WEEKLY_GROUPS`(지금은 조선 4사 — HD한국조선해양·삼성중공업·HD현대중공업·한화오션) 단위로
      2×2 섹션에 그린다. 데이터는 종목 클릭 차트와 같은 `series.json`, 그림은 화면에서 SVG → 캔버스 → PNG
      다운로드(장당 1200×820, 4개 한 장 2432×1672 — **리포에 이미지 파일을 쌓지 않는다**, 46번 PNG 교훈).
      SERIES 상수는 페이지 끝 스크립트가 정의하므로 그리기는 DOMContentLoaded 뒤(첫 판이 이 순서 때문에 빈 칸).
      묶음 추가 = WEEKLY_GROUPS 한 줄. 지난 기록 페이지엔 시계열이 없어 섹션도 없다.
      **용도 = DataGuide·Bloomberg 로 손으로 뽑던 리포트 차트의 대체**(사용자). PNG 에 `WEEKLY_DPI`(384)를
      pHYs 청크로 심는다 — 캔버스 PNG 는 해상도 정보가 없어 워드가 1px=1pt 로 읽어 4개 한 장이 가로 86cm 로
      붙었다(11/7 실측) → 384dpi 면 낱장 7.9cm. **2차(같은 날)**: 조선 8사(4사 + 대한조선·HD현대마린솔루션·
      HD현대마린엔진·한화엔진) + 맨 앞 **합산 칸**(시총 합 · 외인/기관 누적 순매수 합 — 화면이 공통 날짜 구간에서
      계산, 2종목 미만이면 칸 없음) = 9장을 **3×3 가로 한 장**(3664×2524, 24×17cm — PPT 16:9 용, 리포트의
      주가 INDEX 그림은 요청대로 제외). 열 수는 WEEKLY_GROUPS 의 cols. **합산 칸은 2×2 크기**(사용자 "합산이
      개별보다 컸으면") — 4열이면 둘레 8칸, 6열이면 20칸이 꼭 맞는다('한 장' 은 빈 칸을 행 우선으로 채우는
      배치기). **조선기자재 그룹**(같은 날): 유니버스 9(한국카본·동성화인텍·세진중공업·현대힘스·한화엔진·
      HD현대마린엔진·성광벤드·태광·하이록코리아) + `chart_universe.csv` **차트 전용 13**(오리엔탈정공·STX엔진·
      케이에스피·삼영엠텍·대양전기공업·한라IMS·인화정공·범한퓨얼셀·비엠티·케이프·일승·엔케이·대창솔루션 —
      세션이 추린 후보, 사용자 가지치기 전) = 22사, 6열. 차트 전용 종목은 `collect.collect_chart_only` 가
      시계열만 모은다(표·텔레 없음, 한투 종목명이 CSV 이름과 맞아야 담음 — 코드 오타가 엉뚱한 회사로 섞이지
      않게, 오류는 `chart_errors` 로 분리해 텔레 생략 판정에 안 섞임). 첫 수집(다음 거래일 11:32)부터 차트가
      생긴다. **에스엔시스(0008Z0, 2025-08-19 코스닥 상장, 삼성중공업 기전 분사)** 도 차트 전용 14번째로 —
      이름은 '에스앤시스'가 아니라 '에스엔시스'(사용자 정정), 코드는 KRX 신형 영숫자(KODEX K조선 0115D0 과
      같은 부류, 한투가 그대로 받는다). 23사. **첫 강제 수집(11/7 토, `collect_now` 입력 신설 — 휴장일
      강제 수집·텔레 없음)에서 14종목 전부 '이름 불일치 ('')'** — 주식용 inquire-price 는 `hts_kor_isnm` 을
      안 준다(ETF 의 이름 키워드 검사도 실은 `px.name or CSV 이름` 이라 늘 통과하고 있었다). 종목명은 일봉
      `inquire-daily-itemchartprice` 의 output1 에 있어 `fetch_ohlc` 가 `df.attrs["name"]` 으로 싣고 거기서
      검증한다. 숫자 차이 주의: 누적 순매수의 30거래일
      이전 구간은 네이버 수량 × 종가 근사라 DataGuide 금액과 몇 % 어긋날 수 있고, 시총은 현재 상장주수 기준.
    - **PPT 세미나용 글자·선 확대 + 조선기자재 묶음 정리** (11/7 저녁): 사용자 "ppt에 붙이면 글자가 너무 작고
      선이 얇다". `WEEKLY_JS` 의 `svg()` 에 크기표 `Z`(낱장/합산 2벌) — 제목 15→23px(합산 32), 축 11→16(20),
      범례 10.5→15(18), 선 1.6~2.4→3~4(합산 3.6~4.8), 0선 3→4(5), 여백·눈금도 같이. 눈금 수는 좌 6→5·우 8→6.
      **범례는 제목 폭을 재서 그 오른쪽에서 시작**(한글 1.05·영숫자 0.66 × 글자크기 + 26px) — 'HD현대마린솔루션'
      처럼 긴 이름이 범례와 겹치던 것. 검증은 Playwright 로 ⬇ 버튼을 눌러 PNG 를 받아 슬라이드 폭(1600px)으로
      줄여 봤다. 조선기자재 묶음에서 **한화엔진·HD현대마린엔진 제외**(조선 묶음에만) → 21사, 열 수 6→**5**
      (합산 2×2 + 21 = 25 = 5×5 꽉 참).
    - **피어그룹 주가흐름표 갤러리 페이지** (11/7 저녁, 별도 리포 ecos-fx-rates 의 산출물): 사이드바 📰 주보 >
      `📈 피어그룹.주가흐름표` 가 GitHub 파일 페이지로 나가던 것(사용자 "github로만 가는데")을
      `static/peer_price.html` 로 교체 — ecos-fx-rates `output/peer_price/` 의 PNG/SVG 8장(전체·p1·p2·섹션 5)을
      raw.githubusercontent 로 한 창에 띄우고 그림마다 ⬇ SVG/PNG(fetch→blob, raw 가 CORS * 라 가능). 리포엔
      그림 파일을 안 둔다. 갱신은 그 리포 Actions '피어그룹 주가 흐름 이미지' 수동 실행(페이지에 링크).
      build_static 복사 한 줄, 공유 등급(OWNER_ONLY 아님).
      **조선주 INDEX 는 별도 페이지** `static/ship_index.html`(같은 틀, 파일 4장 — 2×2 묶음 + ①②③) + 사이드바
      `📉 조선주.INDEX`(피어그룹.주가흐름표 바로 밑, 사용자 "주보 밑에 별도로 버튼"). 원본 ecos-fx-rates
      `peergroup/weekly_peer_index_image.py`(KOSPI vs 조선주 · 한국 조선 7사 · 한/중/일/싱, 12주전=100, 시총가중).
      **매일 1회 + 수동** (11/7 밤, 사용자 "1·2·3 모두 매일 한 번 + 수동"): ecos-fx-rates 의 `peergroup-price.yml`
      (엑셀)에 이미지 2종 생성 스텝을 합치고 `cron 10 22 * * *`(07:10 KST). 두 갤러리 페이지의 **🔄 지금 갱신**
      버튼은 GAS 기존 키 `peer`(= 그 워크플로)를 쏘므로 **GAS 변경 0**; 끝났는지는 raw PNG 의 Last-Modified 가
      바뀌는지로 보고 자동 새로고침(12분 감시). 3번(수급)은 평일 11:32·16:02 예약 발사 그대로.
    - **'🔄 차트만 지금 수집' 버튼** (11/7 밤): 사용자 "지금 수집 버튼은 ④ 바로 주변에 있고 이것만 돌리게 해야" →
      ④ 머리 밑에 버튼. `collect.py --charts-only` = WEEKLY_GROUPS 의 유니버스 종목(collect_stock, live=False)
      + chart_universe 만 다시 모아 **series.json 만** 갱신(latest·히스토리·ETF·텔레 불변, 휴장일 무관, 전부 실패면
      종료 2). 워크플로 입력 `charts_only`(문자열 'true' — boolean 입력에 GAS 가 문자열을 넘기는 혼선을 피함),
      GAS `buildInputs` 에 covflow 분기(**재붙여넣기 + '배포 관리 → 새 버전' 필요** — 그 전엔 버튼이 전체 수집을
      돌린다, 무해). 페이지 JS 는 GAS 에 POST 한 뒤 배포본의 자기 페이지 길이가 바뀌면 새로고침(12분 감시).
      상단 '🔄 지금 수집'(전체)은 그대로.
    - **합산 칸 2×2 → 가로 2칸** (11/7 밤): 사용자 "합산 그림이 다른 그림 4개 모은 정도인데 1.5~2배 정도가 적당,
      지금 쌓인 게 많다". 합산은 열 span 2·행 span 1(개별의 정확히 2배 면적), `dims` 는 [2W+G, H], Z 큰 글자판은
      세로가 개별과 같아 조금만 키운 값(t 27·ax 17·선 4.4~3.3). 열 수를 다시 짰다 — 조선 5열(합산 2 + 8 = 10칸 → 2행
      꽉 참, 6128×1672), 기자재 6열(2 + 21 = 23칸 → 4행, 빈 칸 1, 7360×3376). 배치기는 (열 span, 행 span) 일반형.
      덤: `🔄 차트만 지금 수집` 버튼이 `.wk-all` 모양을 빌려 써서 '한 장' 핸들러까지 받아 콘솔 오류(data-grid 없음)가
      나던 것 → 핸들러는 `.wk-all[data-grid]` 만.
    - **하루 1회 16:40 으로** (11/7 밤, 사용자 "장 끝나고 매일 4시반~5시"): 예약 작업 11:32(`trig_01Ht8rHrhduJmpdmmJHeLz1w`)
      **비활성**, 16:02(`trig_01Q6FbKD8DAFgby2siphnX2N`) → **16:42 KST 평일**(정각·반각 혼잡 회피). 크론 안전망은 17:05 KST
      하나(11:35 삭제). `metrics.SLOTS`·13:45 경계는 그대로(수동 수집을 오전에 누르면 11:30 슬롯으로 붙는다),
      SCHEDULE_TIME 표기·버튼 툴팁만 갱신. 아카이브(16:00 슬롯)는 영향 없음.
      **→ 오독이었다 — 11/9 2회 복구** (사용자 "11:30분에 텔레 안왔다 … 이거는 그림 얘기한거야"): '4시반~5시 한 번' 은
      ④ 위클리 차트 수집 얘기였지 텔레그램 발송 일정이 아니었다. 예약 11:32 재활성, 16:42 → **16:02** 원복, 크론 안전망
      11:35/16:05 원복, SCHEDULE_TIME·툴팁 원복. 차트 시계열은 전체 수집 때마다 같이 모이므로 16:02 run 이 장 마감 후
      차트도 갱신한다(별도 16:40 차트 작업은 두지 않음). 교훈: 발송 일정을 바꾸는 요청은 **무엇의** 일정인지 되물을 것.
      **→ 2차 정정 — '4시반~5시 한 번' 의 대상은 주보 데이터 4종** (11/9 오후, 사용자 "여기 4개 데이터 모으는거를 매일
      1번 하라는 얘기임 … 수급.그림이랑 업무.자동화의 📡 커버리지 수급 등은 다른거임"): 📰 주보 밑 피어그룹.주가변동표·
      주가.INDEX.비교(둘 다 ecos-fx-rates `peergroup-price.yml`)·수급.그림(coverage-flow `charts_only`)·컨센서스
      (ecos-fx-rates `consensus-chart.yml`)를 **장 마감 후 매일 한 번**. 정시 = 새 예약 작업 `trig_01VEqTcdRitLg6oWSSxQc8uQ`
      (평일 16:42 KST, 커버리지 수급 전용 세션에 묶음 — coverage-flow charts_only dispatch + ecos 두 워크플로 dispatch,
      ecos 쪽이 403 이면 조용히 크론에 맡김), 안전망 = ecos-fx-rates 크론 **16:40**(peergroup, 07:10 에서 이동 — 한국 종가
      당일·미국 전일, 토요일 run 이 금요일 미국 종가를 담는다)·**16:50**(consensus, 신설). 텔레 발송(11:32/16:02)과는 별개.
      위 '별도 16:40 차트 작업은 두지 않음' 은 이 정정으로 폐기.
    - **합산 칸 = 개별과 같은 비율로 1.5배** (11/7 밤, PR #532, 사용자 "가로로만 너무 길다 … 1.5~2배 크기로 같은 비율로"):
      가로 2칸 span 폐기. `WEEKLY_BIG`(1.5) 배로 개별 그림을 그대로 확대(글자·선도 같이 — 그리기는 개별 좌표계 W×H,
      바깥 크기만 키움). 한 장 PNG = 맨 위 띠(합산 왼쪽 + 오른쪽 빈 자리에 제목·축 설명·기준일·출처) + 아래 개별
      격자 — 조선 4열(8칸 2행, 4896×2934)·기자재 7열(21칸 3행). 화면도 같은 비율(`--bw` 너비, 모바일 100%).
    - **합산 2×2 + 두 묶음 모두 4열** (11/8 새벽, 사용자 "보고서에 두 묶음을 붙이면 차트 크기가 너무 다르다 — 여러 행으로
      가더라도 같은 크기로, 대표 차트 옆으로 작은 차트, 모음 너비를 더 키워"): 11/7 의 '맨 위 1.5배 띠' 폐기. 합산은
      왼쪽 위 2×2 칸(`WEEKLY_BIG`=2, 간격 포함 1216×836 → PNG 2432×1672, 개별 좌표계로 그려 scale), 개별은 그 오른쪽부터
      행 우선. 조선·기자재 **둘 다 4열**(조선 12칸 3행 4896×2524, 기자재 25칸 7행 4896×5932) — 같은 폭으로 붙이면 개별 칸
      크기가 같다. 화면은 `grid-column/row: span 2`(모바일은 auto). 한 장 PNG 에서 합산은 svg 태그를 벗기면 W×H 로
      돌아가므로 `<g scale>` 로 칸 크기에 맞춘다(첫 렌더에서 합산이 개별 크기로 찍힌 원인).
    - **방산 5사·건설기계 2사 묶음 추가** (11/8, 사용자 "방산도 건설기계도 같은 거"): WEEKLY_GROUPS 에 방산 수급(한화에어로·
      KAI·한화시스템·LIG D&A·현대로템, 9칸 3행)·건설기계 수급(두산밥캣·HD건설기계, 6칸 2행) — 같은 4열. 덤으로 잡은
      버그: SVG `<text>` 에 이름을 그대로 넣어 **'LIG D&A' 의 & 가 XML 을 깨뜨려** PNG 변환(이미지 로드)이 조용히 실패,
      방산 '한 장'·LIG 낱장 다운로드가 안 됐다 → `xml()` 이스케이프.
      **2차(같은 날)**: 빈 칸을 채우자는 사용자 요청 — 네이버 모바일 API(`m.stock.naver.com/api/stock/{code}/integration`
      의 totalInfos marketValue, 이 컨테이너에서 호출 가능)로 방산 부품사 시총 순위를 뽑아 보여주고 사용자 선택 **풍산·
      SNT다이내믹스**(방산 11칸 3행), 건기는 **진성티이씨·디와이파워**(8칸 2행 꽉 참). 넷 다 유니버스 밖이라
      chart_universe.csv 차트 전용(group 열 방산/건설기계). 참고로 '삼영컴텍'은 삼양컴텍(484590, 2,007억)이고 뺐다.
    - **④ 에 📋 복사** (11/10, 사용자 "index 등은 복사가 있는데 수급에는 왜 없니"): 칸마다 `📋 복사`(⬇ PNG 왼쪽), 묶음마다
      `📋 n개 한 장 복사`. `pngBlob()`(SVG→canvas→PNG+pHYs, Promise) 하나를 다운로드(`toPng`)와 클립보드(`copyPng`,
      ClipboardItem 에 Promise 그대로 — 사파리 제스처)가 같이 쓰고, 한 장 조립은 `composite(grid)` 로 분리. 클립보드
      미지원 브라우저는 복사 버튼을 지운다. Playwright 로 낱장(1200×820)·방산 한 장(4896×2524) 클립보드 확인.
    - **④ 는 공유용 주소에서 숨김** (11/7 밤, 사용자 "gs-research-desk.github.io/coverage_flow_report.html 에는 ④ 없어야").
      텔레 캡션 링크가 그 주소라서. WEEKLY_JS 가 `location.hostname === gs-research-desk.github.io` 이고 해시에
      `weekly` 가 없으면 `#weekly` 를 DOM 에서 제거. 본인용은 `#weekly` 해시(사이드바 🚢 수급.그림-조선)로 진입,
      원본 주소(gschoie.github.io/GS-DB2)·로컬은 항상 보인다. 캡쳐(capture.py)는 로컬 파일이라 영향 없음.
    - **💰 수급.그림 서브메뉴 — 묶음별 그림만** (11/8, 사용자 "조선/방산/건설기계 3개 서브 메뉴 … ①~③은 빼고 그림만"):
      사이드바 📰 주보 > `💰 수급.그림`(구 🚢 수급.그림-조선) 밑 🚢 조선(ship+parts) · 🛡️ 방산 · 🏗️ 건설기계 = 뷰 3개
      (`covweekly-ship/def/con`, iframe `coverage_flow_report.html#weekly-<key>[,<key>]`). WEEKLY_GROUPS 에 `key`
      (ship/parts/defense/construction) 를 두고 묶음마다 `<section class='wk-group' data-key>` 로 감싼다. WEEKLY_JS 는
      그 해시가 오면 **해당 묶음만 남기고 ④ 바깥(머리글·타일·①②③·지난 기록 바)과 ④ 제목·각주를 전부 감춘다**
      (`html.wk-only`) — 🔄 차트만 지금 수집 바와 묶음 제목(한 장 PNG)은 남김. 키가 하나도 안 맞으면 전부 보여준다(빈 화면 금지).
      📡 커버리지 수급 등 뷰(해시 없음)·`#weekly`·공유 주소 동작은 종전 그대로. **페이지는 빌드 산출물이라 coverage-flow 가
      다시 돌아야(charts_only 로 충분) 새 마크업이 배포된다.**
    - 2판 후보(미구현): 수급 × 컨센 변화 교차(kospi_consensus), 외국인 보유비율 1년 백분위,
      섹터 ETF 대비 상대강도, 수주 공시·실적일 이벤트 뱃지, 공매도(소스 확인 필요).

47. **피어그룹 Valuation — 회사 행 클릭 → 매출·영업이익·순이익·OPM·NPM 상세** (10/18):
    표의 회사 행을 클릭하면 그 자리에 재무 상세 패널(연간 + 분기, 지표는 행·기간은 열)이
    펼쳐진다. 연간은 HISTORY_YEARS(4)로 자르지 않고 **야후가 주는 전 기간**(보통 4~5개
    연도) + 올해E·내년E, 분기는 quarterly_income_stmt 가 주는 **최근 5개 안팎** + 0q·+1q
    컨센(기말은 마지막 확정 분기에서 3개월씩 굴려 라벨링). 데이터는 fetch 가
    `record["financials"]` 로 담고 build_static 의 payload 에 그대로 실린다.
    - **야후의 한계를 지어내지 않는다**: 영업이익 컨센 항목이 없어 E 줄의 영업이익·OPM 은
      공란, 분기 컨센도 0q·+1q 가 전부라 '내년 분기'는 담지 않는다(34번 교훈 부류).
      분기 확정치도 최근 5개 분기 안팎이 야후 무료 API 의 전부 — 작년 초 분기는 없을 수 있다.
    - 단위는 재무통화별: KRW·JPY 는 억, 그 외는 백만(패널 하단에 명기). OPM·NPM 은
      적자면 음수 그대로(빨강) — ROE 와 같은 원칙.
    - financials 가 없는 옛 스냅샷에서는 "수집 실행 후 새로고침" 폴백 문구 — **머지만으로는
      안 보이고 수집이 한 번 돌아야 패널이 채워진다**(37번과 같은 가드).
    - 검증: 단위테스트 6개(연간 전 기간+컨센 라벨·마진 산식·E 줄 영업이익 공란·분기
      라벨·분기 없음 폴백) + Playwright 실클릭(열림/닫힘/값 스케일/폴백 문구, 36번 방식).

48. **피어그룹 Valuation — 국내 종목 재무 상세를 네이버 분기 컨센으로 보강** (10/19): 47번
    패널의 국내(.KS/.KQ) 분기·연간E 를 네이버 기업실적분석(에프앤가이드) 값으로 교체.
    **새 요청 0** — 컨센 PER·PBR·ROE 덮어쓰기가 이미 읽던 그 페이지(read_tables 1회 공유)의
    분기 열(매출·영업이익·당기순이익, 억원)을 `naver_consensus.financial_rows()` 로 같이 파싱.
    - 분기는 네이버(확정 4~5개 + 당분기E, **영업이익·OPM 포함 — 야후엔 분기 영업이익 컨센이
      없다**)가 야후분을 대체하고, 네이버 범위 밖 미래 분기(다음분기E)만 야후 꼬리로 남긴다.
      연간E 도 해당 연도 줄을 네이버 값(영업이익 컨센 포함)으로 교체 — 네이버에 없는 내년E 는
      야후 유지. 행에 `src:"naver"`, 화면 열 머리글에 ᴺ 배지 + 안내문 분기(국내/해외).
    - **덤으로 잡은 잠재 버그**: `estimates()` 가 분기 열도 연도로 읽어 '최근 분기 실적'
      E 열의 PER 이 연간 컨센을 덮을 수 있었다 → `_column_period()` 로 분기 열 스킵.
    - 내년 분기 컨센은 이 표에 없다(WiseReport 분기 그리드엔 fwd 3개가 있으나 Playwright
      필요 — kospi_consensus 40번 방식). 필요해지면 kospi_consensus DB 재사용이 다음 후보.
    - 테스트 60→67개(파서 3 + 보강 4), Playwright 로 ᴺ 배지·국내/해외 안내문 분기 실클릭 검증.
    - **첫 run 실측 — ᴺ 이 통째로 죽어 있었다**: 전 국내 종목이 `read_tables` 에서
      "Import html5lib failed" → html5lib 설치 후에도 **"No tables found"**. 원인은
      파서가 아니라 **PC 페이지(item/main.naver) 자체가 Npay 개편(31번)으로 표 없는
      SPA 가 된 것** — 스냅샷 역추적으로 10/3 이전부터 naver=None, 기존 컨센 PER ᴺ
      덮어쓰기도 조용히 야후 산출값으로 돌아가 있었다(30번 부류: 예외를 삼키는 폴백은
      죽어도 티가 안 난다). → 소스를 **모바일 금융 JSON API**
      (`m.stock.naver.com/api/stock/{code}/finance/annual·quarter` — 같은 기업실적분석을
      JSON 으로, kospi_consensus fetch_quarters 가 쓰는 그 API)로 전면 교체.
      naver_consensus 는 이제 pd.read_html 을 안 쓴다(html5lib 는 requirements 에 잔존,
      무해). 값 단위는 억원, est 는 isConsensus 플래그. 수집 로그의
      '📊 네이버 컨센/분기 재무 적용' 줄이 살아있는지가 관측 지점.

49. **피어그룹 Valuation — 대시보드 뷰 전환 + 유럽 중앙값 + 소수 1자리** (10/19): 잔손질 3건.
    - **사이드바 새창 링크 → 대시보드 안 iframe 뷰**: 8/15 신설 때 `<a target="_blank">`로만
      달아 혼자 새창으로 나가던 것을 covflow 와 같은 `data-view="valuation"` 뷰로 전환
      (index.html 섹션 + app.js 제목·lazy src). `🔗 새 창으로` 는 섹션 헤더에 유지.
    - **유럽 중앙값**: 방산 유럽 피어(독일·영국·이탈리아·스웨덴)는 나라별 1곳씩이라 지역
      중앙값이 안 섰다 → `EUROPE_REGIONS` 합산 행을 지역 중앙값들 뒤·전체 중앙값 앞에
      (화면 JS + 엑셀, 2곳 미만 블록은 생략 — 조선 이탈리아 1·건기 스웨덴 1 은 안 뜬다).
    - 배수 표기 전 지표 소수 1자리(`0.0`) — 화면 fmt()·엑셀 number_format (PR #390).
    - **재무 상세 패널 달러 통일** (10/26): 회사 클릭 패널의 매출·영업이익·순이익을 로컬 통화
      (억원·억엔·백만 로컬) 대신 **전 종목 백만달러**로. fetch 가 재무통화→USD 환율
      (`financials.usd_rate`, 수집 시점 야후 환율)을 싣고 화면이 환산 — 네이버 보강분(억원)도
      같은 환율로 함께 환산된다. 환율을 못 구한 날·옛 스냅샷은 재무통화 그대로 + '환율 미수집'
      표기(폴백, 지어내지 않는다). 덤으로 잡은 라벨 버그: 야후 통화 라벨이 틀린 종목(두산밥캣형,
      배수 쪽은 이미 교정)이 패널에서는 'USD'로 찍히고 있었다 → `statements_in_quote` 플래그로
      실통화 기준 통일. 테스트 65→69개 + Playwright(환산값·폴백 문구) 검증.
      **기간별 환율** (10/26 추가, 사용자 "과거는 과거 환율로 했겠지?"): 첫 판은 전 기간을
      수집 시점 환율 하나로 환산했다 → 확정(A) 줄은 **그 기간 평균 환율**(연간 12개월·분기
      3개월 창, 손익 관행)을 행별 `fx` 로 싣고, 컨센(E)·창이 비는 기간만 수집 시점 환율
      폴백. 옛 스냅샷(행 fx 없음)은 usd_rate 폴백이라 깨지지 않는다. 테스트 70개.
      **국내 기업은 원화 십억원** (11/7): KRW 재무는 환산 없이 `/1e9` 십억원으로(사용자 요청
      — 달러 통일에서 국내만 예외), 해외만 백만달러 유지. 저장값이 전부 원 단위라 JS 분기
      하나로 끝(환율 미수집 폴백의 KRW 경로는 제거). 참고: 야후 컨센 출처는 S&P Global
      Market Intelligence(EPS·매출 추정/애널리스트 추천·목표가, 야후 공식 데이터 제공자
      문서 SLN2310 — 옛 Refinitiv/톰슨로이터 I/B/E/S 에서 교체됨).
    - **건기 일본 피어 보강** (11/10): 사용자 지적 "kubota kobelco takeuchi 빠져있다" —
      Kubota(6326.T)·Takeuchi(6432.T) 완성장비 일본에 추가(53종목). Kubota 는 농기계 주력이나
      미니 굴착기 1위라 두산밥캣 콤팩트 피어. **Kobelco 건설기계는 고베제철 100% 자회사라
      비상장 — 넣을 수 없다**(이마바리·JMU 와 같은 사유, companies.py 주석). 같은 날
      사용자 지적 2탄 "싱가포르 seatrium 이 없다" — **Seatrium(5E2.SI)** 조선사 싱가포르로
      추가(54종목). 옛 셈코프마린+케펠 O&M(2023 합병), 2024-05 20:1 병합으로 SGX 코드
      S51 → 5E2(야후도 5E2.SI — 옛 S51.SI 페이지는 병합 전 가격으로 멈춰 있다).
    - 화면·엑셀은 valuation.yml 이 다시 돌아야 반영(빌드 산출물 커밋 구조).

50. **화면 공유용 주소 — 새 창 링크를 gs-research-desk.github.io 로** (10/19): 사람들 앞에서 화면을
    공유할 때 주소창의 `gschoie.github.io/GS-DB2` 와 사이드바(팀원 메뉴)가 드러나는 문제.
    사용자 선택지 셋(GitHub 그대로 / GitHub 조직 주소 / Cloudflare) 중 **GitHub 조직 주소**.
    GitHub Pages 는 그대로 두고 **같은 `_site` 를 조직 리포에도 push 하는 이중 배포** — 외부 서비스 0.
    - 조직 `gs-research-desk` + 리포 `gs-research-desk/gs-research-desk.github.io`(public, Pages 는
      main 루트에서 자동) → 주소 `https://gs-research-desk.github.io/`. 워크플로 5종(deploy-pages·
      refresh-news/union/macro/reports)의 build 잡 끝에 `peaceiris/actions-gh-pages@v4`
      (external_repository·publish_branch main·**force_orphan** — 하루 7회+ 배포라 이력을 안 쌓는다,
      커밋 작성자는 github-actions[bot] — 조직 리포에 gschoie 가 안 남는다). 시크릿
      **`SHARE_DEPLOY_TOKEN`**(그 리포 Contents 쓰기 PAT)이 없으면 스텝을 건너뛴다 — **`secrets` 는 step
      `if` 에서 못 쓴다**(첫 머지 run 이 잡 0개·0초로 실패, 배포 5종 전부 멈춤) → 셸 스텝 출력(`steps.share.outputs.on`)으로 판정,
      실패해도 본 배포는 그대로(continue-on-error). 두 배포가 겹쳐도 force push 라 마지막 것이 남는다.
      시크릿 이름은 `SHARE_DEPLOY_TOKEN` 또는 `SHARE_DEPLOY_2_GS_RESEARCH_DESK`(사용자가 등록한 실제 이름,
      둘 중 있는 쪽 — `secrets.A || secrets.B`). 시크릿 이름은 대소문자를 가리지 않는다.
    - `static/app.js` `SHARE_SITE`/`shareUrl`/`shareLinks`: **`target=_blank` 인 같은 사이트
      링크만** 절대주소로 바꾼다(로드 때 1회 + 캡처 단계 click/auxclick 로 나중에 그려지는
      오늘의 요약 카드 링크까지). 대시보드 안 iframe(data-view)은 상대경로 그대로.
      조직 이름을 다르게 지으면 **`SHARE_SITE` 한 줄 + 워크플로 5곳의 external_repository** 를 고친다.
    - 외부 사이트 둘도 래퍼로: 챗봇 새 창 → `chat_full.html`(있던 것), 콜라보 레이더 →
      `collab_full.html` 신설(build_static 복사 목록에 추가). 주소창엔 공유용 주소만 보인다.
    - 공유 허브 `invest.html` 에 **아침 브리핑 3장**(방산 통합·건기 통합·친환경E/FDC) 추가 —
      공유 때 이 페이지를 공유용 주소로 띄워 두면 된다.
    - 비번 가림막(gate.py)은 산출물에 박혀 있어 공유용 주소에서도 그대로 — 단 localStorage 가
      origin 별이라 거기서 비번을 한 번 더 넣는다. `build_static.previous_payload()` 안전망은
      계속 github.io/GS-DB2 를 읽는다(원본 배포).
    - 왜 Cloudflare 가 아닌가: 8/18 의 CF Pages 프로젝트는 Access 상태·토큰 유효성을 컨테이너에서
      확인할 수 없고(pages.dev egress 차단) 외부 서비스 하나가 더 붙는다. 조직 주소는 GitHub 안에서 끝난다.
    - 검증: 스크래치 빌드를 Playwright 로 열어 open-new 22개·새 탭 링크 35개 전부 공유용 주소,
      동적 링크 클릭 시점 치환 확인. `cf-access-public-reports.yml` 은 11번에 '삭제'로 적혀 있지만
      실제로 남아 있다(수동 실행 전용, 무해).
    - **사용자 설치**: ① github.com → New organization(Free) 이름 `gs-research-desk`(이미 있으면 다른
      이름 → SHARE_SITE·external_repository 변경) ② 그 조직에 **public** 리포
      `gs-research-desk.github.io` 생성(README 하나로 초기화해 main 을 만든다) ③ Settings → Pages 에서
      Source=Deploy from a branch, main / (root) 확인 ④ Settings → Developer settings → Fine-grained
      PAT: Resource owner = 조직 gs-research-desk, 리포 그 하나, **Contents: Read and write** →
      GS-DB2 리포 시크릿 `SHARE_DEPLOY_TOKEN` ⑤ deploy-pages 를 Run workflow → 조직 리포에 커밋이
      생기고 몇 분 뒤 `https://gs-research-desk.github.io/invest.html` 이 열리면 끝.
      조직 멤버는 기본 비공개라 조직 페이지에 gschoie 가 안 보인다(확인: 조직 People → Private).

49. **DART 생산능력·생산실적·가동률 수집 신설** (10/19): `dart_capacity/` — config/companies.yaml 16개사
    (조선·조기·방산·건기, 대한조선은 종목코드 공란 → corpCode 이름 매칭). 파이프라인 fetch → extract →
    normalize(Claude) → dashboard. 워크플로 `dart-capacity.yml`(3·5·8·11월 20일 07:00 KST + 수동: codes·
    stage=fetch-extract|full·force). 사이드바 `🦿 업무자동화 > 🏭 전자공시 - 생산능력` + 🔄 수집 버튼
    (GAS `dartcap` 라우트, stage=full — **GAS 재붙여넣기 필요**), build_static 이 dashboard/index.html →
    `dart_capacity_report.html`, data/normalized/ → `dart_capacity/normalized/`(런타임 fetch) 복사.
    - **컨테이너는 OpenDART·DART 둘 다 프록시 403** → 실행은 러너에서만. 가짜 DART XML 테스트
      (`tests/test_extract.py` 4개·`tests/test_normalize.py` 3개)로 규칙을 검산한다.
    - **OpenDART document.xml 은 건당 ~30초** (200KB~1MB) — 직렬이면 41건에 20분(실측). 병렬 4로 받는다.
      원문 zip 은 actions/cache 만(리포 미포함). `[첨부정정]`은 014(파일 없음)로 오는 게 정상.
    - **main 에 없는 새 워크플로는 dispatch 가 404** — GitHub 가 색인하지 않는다. 브랜치 push 트리거를 임시로
      넣어 1회 돌려 등록시킨 뒤 제거했다(등록 후엔 브랜치 ref 로 dispatch 가능).
    - **표 선정 규칙(실측으로 다듬음)**: ① 표 본문은 **셀 하나가 통째로 지표명**(생산능력/생산실적/가동률(%))
      이거나 머리글에 있을 때만 — '생산능력 향상'(투자표 기대효과 셀)·'생산능력증가'는 제외. ② 제목은
      **가장 가까운 제목 줄의 마지막 소항목**으로 판정 — '다. 주요 원재료 및 생산능력 (1) 주요 원재료 등의
      현황' 에 원재료 표가 끌려오던 것 차단. '…입니다.' 로 끝나는 각주 문장은 제목이 아니다. ③ DART 는
      '(단위 : 백만원)' 과 '※ 각주' 를 **한 칸짜리 표**로 따로 둔다 → 표로 세지 않고 다음 표의 단위 /
      **바로 앞** 채택 표의 각주로 붙인다(다른 표를 지나왔으면 안 붙임 — 처음엔 문서 뒤쪽 각주 50개가
      두산밥캣 가동률 표에 붙었다). ④ 제목 여러 줄이 한 요소에 올 수 있어(두산밥캣 '…제외하였습니다.
      라. 생산실적 및 가동률 (1) 생산실적') 문맥은 **요소가 아니라 줄 단위**. ⑤ 표마다 뒤로 되짚는
      `find_all_previous` 는 큰 보고서에서 문서당 40초 → 한 번 훑는 버퍼 방식(400표 문서 5.8초).
    - **회사마다 표 모양이 다르다**: 한화에어로 = 능력·실적·가동률이 한 표(구분 열), **금액 기준 백만원**,
      사업보고서에 3개 연도 열(→ 연도별로 행을 쪼갠다, period 는 데이터 열 기간). 두산밥캣 = 능력/실적/
      가동률 3표, 단위 '대', 기간이 **제12기·제11기**(기수 → 보고 기간이 당기). HD현대중공업 = 능력(천GT·
      천BHP, 셀 안에 단위)·가동률(천M/H 가동가능/실제시간)·실적(백만원) 3표 + 개요 중복 1표 — 능력·실적
      단위가 달라 스키마에 `capacity_unit`/`production_unit` 을 두고 대시보드는 단위가 다르면 차트를
      나눈다(한 축 원칙). 정규화는 보고서당 모델 1회(표 전부를 한 번에 넘겨 (부문·제품·기간)으로 합치게).
    - **정규화 모델 = Gemini 무료 티어**(`GEMINI_API_KEY`, 다른 모듈과 같은 키): 사용자가 유료 Claude 키를
      원치 않아 전환(`DART_CAPACITY_PROVIDER=claude` + `ANTHROPIC_API_KEY` 면 Claude). 보고서당 1회, JSON 모드.
      **429 가 나면 같은 모델을 기다리지 말고 flash↔flash-lite 를 바로 교대**(한도 버킷이 따로다) — 처음엔
      같은 모델 65초×2 재시도로 39건에 60분이 걸려 타임아웃·결과 유실(커밋 스텝이 always 가 아니었다).
      교대 뒤 7분. 실측은 38/39 가 flash-lite 로 처리됐다.
    - **`canonical.py`(10/20)**: 모델이 보고서마다 부문·품목을 조금씩 다르게 적어('엔 진 기 계'/'엔진기계',
      '선박 (HD현대중공업㈜ 外)'/'선 박', 회사명이 괄호 안·밖·'회사: 품목'·'회사 / 품목') 대시보드 줄이
      801행으로 쪼개졌다 → all.json 을 묶을 때 회사별로 ① 비교 키(공백 제거·나열 구분자 통일·꼬리 '등' 제거,
      회사는 ㈜·법인 표지로 분리, 사명 변경 괄호는 무시) ② 최신 보고서 이름을 표시명으로 유사 줄 흡수
      ③ 같은 (줄, 기간) 행 병합(값은 '값이 있는 최신 보고서', 능력 천GT·실적 백만원이 한 행에, 단위 각각)
      → 266행. 원문 '-' 를 모델이 0 으로 적는 경우(두산밥캣 '국내')는 0/0 이면 없음으로.
    - 대시보드: 줄 키에 단위 제외, 비교표 열은 기간 일반형(2025 FY/1Q/H1/3Q — 회사별 '제12기' 표기는
      회사 카드 안에서만), **연간만/전체 토글(기본 연간)** — 분기 열은 누적이라 연간과 한 선에 놓으면 톱니.
    - 현재 상태: 3개사(HD현중·한화에어로·두산밥캣) 39건 정규화 완료, 대시보드 데이터 있음. 나머지 13개사는
      codes 비워 stage=full 로 실행(처리 장부로 증분). review.csv 엔 모델이 '중복 표라 생략' 메모를 남긴다.
    - 운영 메모: 3/20 크론은 사업보고서 마감(3/31) 전이라 그해 사업보고서는 5/20 실행에 잡힌다.
    - **원재료 매입·원재료 가격변동·제품 가격변동 주제 확장** (10/20): 같은 보고서의 '가. 원재료 매입(현황)',
      '나. 주요 원재료 등의 가격변동추이', '제품 가격변동추이' 표를 함께 추출(extract `topic` 필드 — TOPICS 순서가 곧
      우선순위: capacity → material_price → product_price → material. '가격변동 현황' 제목이 material 로 가던 것을 순서로
      막았다). 정규화 규칙·스키마는 `topics.py`(SPECS) 한 곳, 산출물 `data/normalized/<topic>/`, all.json 의 `topics` 키,
      대시보드 상단 주제 탭. 장부(processed.json)는 주제별로 따로 — `normalize --topics a,b --force` / 워크플로
      `topics` 입력으로 그 주제만 다시 돌린다(capacity 는 안 건드림).
      - **material 의 '회사' 칸은 `entity`(법인·사업소)** — 처음엔 `company` 로 받아 보고 회사명을 자회사 이름으로
        덮어썼다(한화에어로 줄이 '㈜쎄트렉아이' 로). 옛 파일은 rebuild 의 `migrate_row` 가 stock_code 로 회사명을 복원.
      - **모델 출력은 보고서마다 모양이 다르다**: 분기보고서는 '해당 회사' 열이 없어 entity 가 비고, 매입유형도 '' 와
        '원재료' 가 섞이고, 소계는 segment·purchase_type·item 아무 데나 온다. 모델에 규칙을 더 적는 것보다
        `canonicalize_topic`(쉼표·공백·㈜·'부문' 지운 키로 묶고 최신 접수의 표기로 통일, 같은 줄에 값이 하나뿐이면 빈 칸을
        거기로 합침)·`_fix_subtotal` 후처리가 확실하다. 모델이 null 을 준 문자열 칸은 '' 로 — None 이 정렬 키에
        섞이면 rebuild 가 통째로 죽는다(첫 run 실측).
      - **화면 손질** (10/20 저녁): 회사별 시계열의 보고 기간별 표(분기마다 한 줄)는 `<details>` 로 접은 채 시작,
        차트는 한 행에 2개(값 없는 차트는 안 그림). 대시보드 줄 키를 (segment, product) 에서 **표시 이름 + 단위**로 —
        모델이 같은 줄을 ('', '기타') / ('기타', '') / ('기타', '기타') 로 적어 '대한조선 › 기타' 가 세 줄이던 것.
        단위가 다른 '선박'(GT·천MH·백만원)은 그대로 따로 둔다. 주제 표가 없는 보고서의 '행 0' 판정이 장부에
        안 남아 매 run 다시 잡히던 것도 수정(PR #429 — 장부는 보고서마다 저장).

51. **수급 발송 평일 2회로 축소 — 11:00 / 16:00** (10/20): "하루 4번은 많다"는 요청.
    슬롯 체계를 1100/1600 둘로(decide_slot 경계 13:30), 옛 4회 키(1000/1300/1540/1640)는
    history 표기용으로만 유지 — 과거 일자 페이지는 옛 4회 배지로 그려진다(sched_badge가
    그 날의 슬롯 키로 신/구 체계를 판단). 크론 2개(UTC 02:00/07:00)·guard 2슬롯, GAS 시계
    flow 슬롯 [11,16]×:00 — **재붙여넣기 필요**. 16:00은 covflow GAS 슬롯과 같은 분이라
    한투 토큰 분당 1회 제한에 걸릴 수 있어 kis_token에 403 재시도(20초×5, PR #395와 동일)
    추가. 장중 곡선 저장 게이트는 1600 슬롯. 16:00 수치는 마감(15:30) 직후 잠정 누적이고
    거래소 확정은 저녁이므로 라벨은 '16:00 마감'(확정이라 적지 않는다).

51. **방산 브리핑이 중간선거-예산 축을 놓친 사고 → 예산 정치 상시 추적** (10/20): 10/20 장중
    K방산 급락(한화에어로 -10%대·한화시스템 -14%·현대로템 -12%)의 두 재료 중 '증권사 목표가
    하향 러시'는 전일 기사 인용까지 해놓고 "수급이 눌렀다"로 소화했고, **'미 중간선거(11/3)
    민주당 우세 → FY27 재정조정 $350bn 감액 리스크' 축은 아예 없었다**(사용자 지적). 원인 둘:
    ① 수집 쿼리에 예산-정치 교차축이 없었다(`"defense budget"` 단독으론 midterm/reconciliation
    기사가 빠짐) ② 세션 리서치가 가격 반응형(±5% 원인 추적)이라 미 방산이 -1~2%로 조용히
    빠진 날은 정책 재료를 검색하지 않았다. → defense_briefing_bot NEWS_QUERIES에 예산 정치
    쿼리 + 한국어 쿼리에 '방산주' 추가(RSS판 inputs도 같은 쿼리라 동시 보강), 트리거 루틴
    [2]에 "중간선거·FY27 예산 정치 매일 1회 검색 + 미·유럽 방산 동반 약세는 정치 재료를
    배제한 뒤에 차익으로 쓴다" 상시 항목 추가. 당일엔 웹서치판에 장중 보완 섹션으로 소급
    (통합본은 건드리지 않음 — 28번 재발송 함정). 참고 사실관계: FY27 $1.5조 = 세출 $1.15조 +
    재정조정 $350bn, 하원 Recon 3.0 통과분은 $60bn뿐·상원 표 부족, 헤그세스 "선거 무관 추진",
    탄약·방공은 초당적 축이라는 반론 병존(Defense Daily·Breaking Defense).

52. **증시 법칙 달력 신설** (10/28~29): "짝수해는 어느 달 조심, 10월 조심 11월 반등, 코스닥
    오르면 대주주 매도 언제부터" 같은 **격언·계절성을 날짜 위에 올린 페이지**.
    `market_calendar/` + 사이드바 `📈 투자 > 📊 시장.모니터링 > 📅 증시.법칙달력`(매크로.데스크 밑).
    - **1차 수집 `ADAGES.md`**(웹서치 12회, 출처 링크·신뢰도 ★ 표기): 핵심 발견 —
      **"짝수해"의 정체는 미국 선거 주기**(중간선거해 6·9월 약세, 10·11월 강세, 선거 후 6개월
      S&P 96% 상승, 코스피 10월말→연말 +6%, 짝수해 9월 코스피 낙폭 더 큼) · 코스피는
      세 기간(44/26/10년) 모두 **11월 최강·8~9월 최약**이고 **'5월에 팔아라'는 한국엔 안 맞음**
      (5월 +0.31%) · 대주주 양도세는 **종목당 50억 유지**, 판정 12/31 보유·T+2 라 2026 마감
      **12/28(월)**, 코스닥 개인 12월 -2,800억/1월 +3,600억 · 추석 후 5거래일 68% 상승이나
      **설은 반반** · 지방선거만 전후 모두 약세 · FOMC 전 24h 드리프트는 2011년 이후 약화.
      **못 찾은 것**(배당락 하락·윈도드레싱·북클로징)은 ★ 또는 미수록 — 통설만으로 안 넣는다.
    - **구조**: `rules.yml`(격언 정본, kind=month/cycle/window/pin/signal + conf 1~3) ·
      `dates.yml`(명절·선거·MSCI·KRX 휴장일, 미확인은 tentative) · `build_calendar.py`
      → `static/market_calendar_report.html` 에 **3년치 이벤트를 박고 '오늘'은 JS 가 KST 로**
      정한다 → **크론 0**(격언은 매일 안 바뀐다; 규칙·날짜 수정 때만 재빌드 → push 배포).
      FOMC 는 `macro_desk/fixed_dates.json` 을 그대로 읽는다(두 곳에 적지 않는다).
    - 화면: 지금 어디쯤인가(이번 달 격언 + 올해 주기 + 지나는 구간 + 45일) / 1년 띠(코스피·
      미국 월별 + **그 해의 4년 주기 줄**, 연도 버튼으로 2027·2028 미리보기) / 달력(구간 띠
      빨강·파랑·회색, 날짜 칩, 휴장 회색) / 격언 카드. 4년 주기 = `(year-2024)%4`.
    - 원칙은 매크로 데스크와 동일: 규칙 날짜는 코드, 공표 날짜는 파일, 추측은 안 적고 `~`.
      **창은 거래일 창이라 주말·휴장 칸엔 띠를 안 그린다**(첫 렌더에서 주말에 띠가 그려졌다).
      거래일 셈은 dates.yml 휴장일 기준이라 빠진 휴일이 있으면 하루 어긋남 → 창 끝 `≈`.
    - `tests/test_rules.py` 14개(T+2 마감·배당락·산타 구간·추석 창·둘째 목요일·K200 효력·
      4년 주기·선거 창·tentative 전파). Playwright 실클릭 검증(칩 → 카드 열림).
      이 컨테이너의 Chromium 은 `/opt/pw-browsers/chromium-1243/chrome-linux64/chrome`
      (번호·경로가 36번 때와 다르다 — glob 으로 찾을 것).

53. **불꽃 리서치 톤 신설 — 한화투자증권 리서치 게시판 톤 추적** (11/1): 다올 리서치톤(별도 리포
    `gschoie/DAOL-RESEARCH-TONE`)과 같은 골격을 이 리포 안에 `hanwha_research_tone/` 모듈로. 소스는
    공식 텔레그램이 없어 게시판 2개 — 기업·산업분석(`depth2_id=1002`) + 투자전략(`1003`). 2025-01-01 부터 백필.
    - **게시판 구조(러너 프로브 2회로 실측 — 컨테이너는 `service.hanwhawm.com:9090` 접속 불가)**: 목록은
      GET `list.cmd?depth2_id=…&mode=depth2&p=N`(10건/페이지, 1002 는 19,235건·1003 은 4,584건, 2025-01 은
      1002 p≈250·1003 p≈85), 행은 `ul.researchList li` 의 `view('seq','depth3','구분')` + 작성자·날짜·요약.
      상세 `view.cmd?…&seq=` 의 `div.researchCont` 에 본문 요약(몇 문단)과 `spJname`(관련 종목). **첨부 PDF 는
      로그인 전용** → 본문 요약이 분석 입력. 페이지가 메뉴 때문에 ~520KB 라 상세는 예산(초)으로 끊고 다음 run 이
      이어 받는다(4 스레드). 해외주식분석(anls19)·데일리/주간시황류(routine)는 톤 분석 제외.
    - 파이프라인: `collect.py`(목록 증분·백필 + 상세, `data/reports.json`·`bodies.json`) → `ai_analyze.py`
      (Gemini 구조화, 다올과 **같은 스키마** — 확신도·톤 라벨·문구 인용·TP 방향/사유·실적추정·투자포인트,
      `data/ai_analysis.json` 캐시, 429 는 모델 교대) → `build_tone.py`(기업/산업 타임라인·직전 TP 채움·
      투자포인트 diff·이벤트·섹터×애널 보드 → `data/tone_v2.json` + 대시보드 `static/hanwha_tone/`).
      TP·투자의견은 제목 `[코드/Buy]` 와 본문 정규식(`parse.extract_cover`)이 AI 값보다 우선.
    - 화면 `static/hanwha_tone_report.html`(런타임 fetch, 다올 보드와 같은 배치: 이벤트 2열 → 섹터×애널
      → 최근 발간 표 → 기업 모달에 TP 추이·문구·포인트). 사이드바 `🔥 리서치톤`(DAOL 리서치 톤 바로 밑, 사용자 지정 라벨),
      색은 한국식(상향 빨강·하향 파랑). 워크플로 `hanwha-tone.yml` 크론 07:10/07:35 KST(아침, 지연 안전망)
      + 22:00 AI 백필, 데이터 커밋백 → deploy-pages workflow_run. 시크릿은 기존 `GEMINI_API_KEY`
      (`HANWHA_GEMINI_API_KEY` 있으면 우선). 테스트 23개(제목·표지 파서·목록/상세 HTML·병합/이벤트).
    - **첫 백필 실측** (11/1, 한 run): 목록 3,080건(2025-01-02~) → 분석 대상 2,616건 상세 전부 수집(실패 0,
      ~14분). 본문 뒤에 푸터 JS ~9KB 가 섞여 들어왔고(`bodies.json` 40MB) 373건은 로그인 전용이라 본문이 빈 글
      → `parse.clean_body` 로 경계 문구에서 자르고(4.8MB), 빈 본문은 목록 요약만으로 분석(SCHEMA_VERSION 2 로
      재분석). TP 는 '30만 원'·'5.1만원'·'1만 2천 원' 한글 단위를 못 읽어 463/1,132 → 820/1,132 로 올렸다.
      직전가는 **목표주가 문장 ±160자 안에서만** 찾는다(BPS 16,422원을 직전가로 오인). 본문이 '유지'인데
      타임라인 직전 기록과 값이 다르면(그 사이 자료가 로그인 전용) 비교로 방향을 매기고 **'추정' 표식**을 단다
      — '유지'로 두면 TP 가 바뀐 사실이 화면에서 사라진다. 대괄호 시리즈 제목('9월의 기분'·'플레이북')은
      담당자의 최빈 섹터로 대체, 변형('철강/비철금속'→'철강/비철')은 `parse.SECTOR_ALIASES`.
    - **한경컨센서스 PDF 보강** (11/1 오후, `hankyung.py`): 사용자 "로그인 안 하고 보는 법 없나" → 러너 실측으로
      `consensus.hankyung.com/analysis/list?search_text=한화투자증권&sdate=&edate=&pagenum=80` 이 **증권사 필터**로
      동작하고 행마다 `analysis/downpdf?report_idx=` 가 **로그인 없이 진짜 PDF** 를 준다(열: 작성일·분류·제목·작성자·
      제공출처·첨부, 제목 칸은 같은 제목이 3번 반복 — 첫 앵커만). 네이버 금융 리서치는 Npay SPA 로 넘어가 표가 없다.
      월 단위 창으로 2025-01 부터 백필(1,447건) → 게시판 글과 **날짜 ±1일 + 담당자 + 종목코드/제목 토큰**(포함 관계 허용:
      한경 'FI Weekly' ↔ 게시판 '[FI Weekly] FOMC 프리뷰')으로 매칭(1,072건 — 한경이 안 싣는 글이 있어 100% 는 아니다,
      기업분석은 1,132 중 610) → PDF 앞 4쪽 텍스트를 `data/pdf_text/YYYY-MM.json`(월별 샤드, PDF 자체는 미저장)에.
      첫 run 918건(실패 0, 25분). 표지 정형문 `목표주가(유지): 30,000원` 은 방향 괄호 뒤 콜론 때문에 정규식이
      놓치고 있었다(본문 문장으로만 잡히던 것) → `parse._TP_PAT` 에 콜론 슬롯. AI 입력 우선순위 PDF > 게시판 본문 >
      요약(캐시 `src` 기록), 요약/본문으로 분석한 건은 **미분석이 다 끝난 뒤** PDF 로 재분석(업그레이드 후보).
      화면: 제목 옆 `PDF` 배지(한경 링크), 머리글 'PDF n건'. 워크플로에 `pypdf` + 보강 스텝(실패해도 계속).
    - AI 백필은 11/7 완료(2,531건, 대기 0 — 11/2 `gemini-2.5-flash-lite` 폐기 404 로 run 이 끊겨 폐기 모델은
      회전에서 빼도록 고침). 이후는 하루 신규분만. GAS 라우트·텔레그램은 아직 없다.
    - **아침 정시 발사 = Claude 예약 작업** (11/7, 사용자 "예약 작업으로 아침 8시 반 전에"): 07:10 크론이
      10:50~11:40 에 도착하던 문제. 커버리지 수급(46번)과 같은 방식 — 리포가 붙은 전용 세션
      `session_015Pd8bgJztQzb7FNiUY6hTL`('리서치톤(한화) 아침 수집 스케줄러', sonnet)에 예약 2개
      `trig_01UJtFdMbttR2dr6mxnLtJzr`(평일 07:38 KST)·`trig_01U2VuTAA8jYi7TM1T6nY2QW`(08:08, 그 사이 올라온
      글 보강)가 묶여 `gh workflow run hanwha-tone.yml --ref main -f ai_max=150` 을 쏜다. 크론 안전망은 그대로
      (텔레가 없어 중복 run 은 무해). fire_trigger 수동 발사는 세션 묶기를 무시하므로 검증은 정시 결과로.

54. **매매제한 컴플 체크 — GEMS → 대시보드 내장 도구** (11/2): 사이드바 `👥 DAOL.관리 > ⏳ 컴플(24H 매매제한).쳌`
    이 제미나이 Gem·ChatGPT 프로젝트 두 창을 열던 것을 `static/compliance/index.html`(새 창)로 교체.
    매매제한 지시(자료 A)·파워베이스 캡처(자료 B)·혼합 이미지를 Ctrl+V/드래그/사진 선택으로 올리면
    **판독은 AI, 대조·판정·집계는 고정 규칙**(`static/compliance/matcher.js`) — GEMS 처럼 AI 가 건수까지
    세면 판독 못 한 종목을 '일치'로 넘기거나 집계가 틀릴 수 있어서다(집계 합계 ≠ 행 수면 예외).
    - AI 는 브라우저에서 직접 호출: 기본 **Gemini**(`generateContent` + `responseJsonSchema`, 스키마 400 이면
      JSON 모드 재시도, 기본 모델 `gemini-pro-latest`, '모델 목록 불러오기'), 선택 Claude(`vendor/` 에 묶은
      공식 JS SDK — CDN 없이 동작). **키는 보는 사람 브라우저에만 저장**, 리포·서버 미경유(리포 공개).
    - 판정 규칙(지침): 코드 문자열·앞자리 0 보존(A 접두만 제거), 코드 우선, 이름 같고 코드 다르면 ❓,
      우선주는 별개, 같은 캡처 안 중복 ❓/캡처 간 겹침 1건, 적용 증거 없음·기간 상이 ❓, 판독불가·캡처 잘림이면
      '전체 일치' 선언 금지. 테스트 `compliance_check/matcher.test.js` 12개(`node --test compliance_check/`).
    - 원본 개발은 DAOL-Securities-Research-Center/DAOL-RESEARCH-TONE 브랜치(조직 권한 문제로 미푸시) —
      정본은 이제 이 리포. 같은 파일을 claude.ai 아티팩트로도 띄웠다(그쪽은 CSP 로 Gemini 불가, claude.ai 계정 판독).
    - 공유 비번으로 열린다(하위 폴더 index.html 은 주인 전용 아님). 빌드는 `build_static` copytree 한 줄.

52. **매크로 데스크 — 발표 결과 해석 자동 선택** (11/4): 사용자 "발표된 지표는 눌러서 내려가면 결과와
    간단한 해석". 해석 카드 맨 위에 **📌 이번 결과 해석** — 발표 숫자가 든 `guide.yml` read 밴드를
    규칙으로 골라(`metric`·`ge`·`gt`·`le`·`lt`, quote_reads 와 같은 어휘) 뜻과 **고른 숫자**를
    적고 밴드 목록엔 `◀ 지금`. 숫자는 `releases.summarize` 가 새로 남기는 `vals`(화면 자릿수로
    반올림, 보조 계열은 config `also.key` → `core_yoy`·`unemp_level`). 조건 없는 밴드(FOMC 성명서·
    점도표·근원 MoM)는 고르지 않고 이유 한 줄, GDP 밴드는 `ids: [us_gdp]`(한국 GDP 제외).
    **YAML 함정: 키를 `on:` 으로 썼다가 PyYAML 이 True 로 읽어 조건 20개가 전부 사라졌다** —
    `metric:` 으로. 덤: `tests/test_releases.py` 의 실패 판정이 파일 중간에 있어 그 뒤 검사는
    실패해도 통과로 나왔다 → 맨 끝으로. 다음 수집부터 보인다(옛 payload 엔 vals 없음).

55. **주보 메뉴에 '📊 컨센서스' 추가** (11/7): 사이드바 `✍️ 보고서.발간 > 📰 주보` 맨 아래(수급.그림-조선 밑).
    링크는 ecos-fx-rates `output/consensus/`(GitHub 폴더) — 커버리지 16종목 영업이익 컨센서스 최근 6개월 추이
    PNG(분기 4Q26·1Q27 / 연간 올해E·내년E). 생성기 `consensus/weekly_consensus_chart.py` 는 kospi_consensus DB 가
    아니라 FnGuide `wcomp.fnguide.com/CompanyInfo/getCnsTrendChart`(월말, 1년) + 네이버 WiseReport `cF5002`
    (분기 주간 13점·연간 월말 13점)를 이어 붙인다 — 트래커 DB 는 분기 fwd 컨센이 10/15 부터라 6개월이 안 된다.
    (참고: comp.fnguide.com 은 wcomp.fnguide.com 으로 이전, 옛 SVD_*.asp 는 404.) 갱신은 ecos-fx-rates Actions
    '커버리지 컨센서스 추이 이미지'.
    **갤러리 페이지로 교체** (같은 날 저녁, 사용자 "누르면 github가 뜬다 — html 에서 보고 다운받고/복사"):
    `static/consensus_chart.html`(peer_price.html 과 같은 틀) — raw.githubusercontent 로 분기·연간 PNG 를 띄우고
    그림마다 **📋 복사**(ClipboardItem image/png — 클립보드는 PNG 만 표준, blob Promise 를 그대로 넘겨야 사파리도
    제스처로 인정) · ⬇ PNG/SVG/CSV. 생성기는 SVG 도 함께 굽는다(`svg.fonttype=path` — 한글 폰트 없는 PC 에서도
    모양 유지). build_static 복사 한 줄, 공유 등급.

56. **애널리스트 집계(animsam09) 따라 만들기 — 뼈대** (11/7): 사용자 "이거 따라서 일단 뼈대를 만들자"
    (https://analyst-calendar.animsam09.workers.dev/ — Cloudflare Worker, 비번 가림막). 세션 네트워크에
    그 호스트를 허용하는 개인 환경 'GS-DB2'를 만들어 로그인 후 두 화면·탭 전부를 Playwright 로 떠서 구조를
    `analyst_calendar/README.md` 에 적고, 정적 뼈대를 `telegram_research_dashboard/static/analyst_calendar/`
    (index.html·style.css·app.js·data.json)에 만들었다. 사이드바 👥 DAOL.관리 › 활동관리.DAOL 바로 밑 `활동관리🔥`
    (새 창, 공유 비번으로 열림), build_static copytree 한 줄.
    - 원본 구조: **업무 집계**(탭 15개 — 업데이트·요약·발간/세미나/콜/리퀘/사내지원/NDR/콥데이 실적·커버리지·
      드랍 경고·발간 vs 계획·인뎁스 달력·기관별 집계·누락 후보; 요약 = 카드 6장 + DAOL 리서치본부 활동표)
      + **일정**(월/주/목록, 장부만/전체, 애널리스트 사이드 필터·미니달력, 확인 필요 모달, 설정 모달 —
      구글 캘린더 ICS 2종·기관명 분류 xlsx·애널리스트 규칙). 데이터는 Worker API(state/master/events/op).
    - 뼈대는 **data.json 명단 + 결정적 난수 일정**(xorshift)으로 돌아간다 — 숫자는 전부 가짜, 화면에
      '뼈대/샘플' 표식. 실데이터 연결 지점은 `loadData()`/`genEvents()` 둘뿐. 본문 미구현 탭(커버리지 전체
      목록·드랍 경고 목록·인뎁스 달력)은 점선 상자에 원본 구성을 적어 뒀다. 다음 단계 후보: GAS 가 구글
      캘린더 ICS 를 읽어 data.json 을 굽기(youtube_digest 와 같은 workflow_dispatch 경로), 인뎁스 달력은
      vacation_tracker/indepth.py 의 state 재사용.

57. **피어그룹 주가흐름표 — 방산·건설기계판 신설** (11/8): 사용자 "방산, 건설기계도 조선처럼". 생성기는
    ecos-fx-rates `peergroup/weekly_peer_price_image.py` 에 `--universe ship|defense|construction`
    (SHIP/DEFENSE/CONSTRUCTION_SECTIONS, 출력 `output/peer_price_defense/`·`peer_price_construction/`,
    전체·분할 p1/p2·섹션별 `01_…`, 같은 워크플로가 세 판 생성). 처음엔 세션의 ecos-fx-rates push 가
    자동 분류기에 막혀 패치로 떨궜다가, 사용자가 권한을 줘 main 에 직접 push(576d3fc) — 패치 파일은 삭제.
    참고: 별도 리포 작업은 `add_repo`(push) 승인이 필요하고, 거절되면 패치 → 승인 뒤 `git am` 이 통한다.
    - 대시보드: `static/peer_price.html` 하나가 `?u=` 로 세 유니버스(UNIVERSES 표 — 파일명은 생성기와
      일치해야 함, 상단 탭으로 전환). 사이드바 주보 `📈 피어그룹.주가흐름표` 밑 `🛡️ ┗피어주가.방산`·
      `🏗️ ┗피어주가.건기`(view peerdef/peercon). 🔄 지금 갱신은 GAS `peer` 그대로(세 판 동시).
    - 유니버스 결정(세션 추천, 사용자 가지치기 전): 방산 = 한국 체계 5(한화에어로·KAI·LIG D&A·한화시스템·
      현대로템) + 탄약/기동(풍산·SNT다이내믹스 신규) + 부체계(엠앤씨솔루션·아이쓰리시스템·퍼스텍·휴니드) +
      항공부품(켄코아·아스트) + 우주(쎄트렉아이·인텔리안·컨텍·제노코) / 기타(Elbit·Aselsan·HAL·BEL·MHI·KHI·
      IHI·AVIC 2·Embraer EMBJ — 2025-11 ERJ→EMBJ 티커 변경) / 지수·ETF(PLUS K방산·ITA·SHLD·EUAD) / 미국(프라임 7 + Kratos·AeroVironment +
      GE·Howmet·TransDigm·Curtiss-Wright) / 유럽(Rheinmetall·BAE·Thales·Leonardo·Saab·Hensoldt·Renk·
      Kongsberg + Airbus·Dassault + RR·Safran·MTU) / **글로벌 우주·위성**(11/9 사용자 "글로벌 우주/위성은 없네?" —
      발사체 Rocket Lab·Firefly·Intuitive Machines / 위성통신 AST SpaceMobile·Iridium·Viasat(EchoStar SATS 는 야후 이력 부족)·Eutelsat·SES / 관측 Planet·
      MDA Space / 부품 Redwire·Karman·OHB / 일본 ispace·Astroscale(QPS 5595.T 는 야후 무응답) + ETF UFO; 단 배치 좌 지수·한국·우주 / 우 미국·유럽·기타). **뺀 것**: Spirit Aero(보잉 인수 완료·상폐)·Triumph
      (사모 인수·상폐)·Subaru(FHI, 항공 비중 미미)·Bombardier(비즈젯)·하이즈항공·오르비텍(초소형).
      건기 = 지수(PAVE·구리·WTI·원달러) / OEM 한국 2(**HD건설기계** = 2026-01 인프라코어 흡수합병 후 사명, 042670 상폐)·미국/유럽(CAT·Volvo·Terex·
      Oshkosh·Manitowoc·Wacker Neuson·Manitou)·일본(Komatsu·Hitachi CM·Kubota·SHI·Takeuchi·Tadano)·
      중국(SANY·XCMG·Zoomlion·LiuGong·Lonking)·인도(Escorts Kubota·ACE·BEML) / 농기계(Deere·CNH·AGCO·대동)·
      광산(Sandvik·Epiroc·Metso·Weir)·렌탈(URI·**Sunbelt SUNB** = 舊Ashtead 2026-03 NYSE 1차 상장·Herc)·CAT딜러(Finning·Toromont) / 부품 한국 6
      (디와이파워·진성티이씨·대창단조·동일금속·흥국·우림피티에스) + KYB·Hengli. 옛 표의 '소형' 묶음
      (Deere·Sandvik·URI 혼재)은 농기계/광산/렌탈로 분해, Kubota 는 부품 → 일본 OEM.
    - **첫 실행(11/8) 실측 교정**: ERJ·EMBR3(둘 다 옛 티커→EMBJ)·302132.SZ AVIC Chengdu(전 구간 0.0% 고정값→
      AVIC Xi'an 000768.SZ)·AHT.L(→SUNB)·042670.KS(합병 상폐). 기준일은 **시총 있는 주식 섹션의 최신
      날짜**로 — 선물·환율(CL=F·KRW=X)은 일요일 봉이 있어 max 를 쓰면 일요일 날짜가 찍힌다.
    - **개별 섹션 카드는 접힌 채 시작** (11/9, 사용자 "개별은 다 접어두고 모아둔거만 펼쳐두기"): 카드를
      `<details class="card">` 로 — 모음 3장(전체·p1·p2)만 `open`, 파일명이 `01_…` 숫자 접두인 개별 섹션은 접힘.
      머리글(summary)의 복사·다운로드 버튼은 `preventDefault` 로 카드를 안 접고, 상단 점프 링크는 대상 카드를
      펼친 뒤 이동(접힌 채 앵커로 가면 그림이 안 보인다). `?u=defense,construction` 합본도 유니버스마다 같은 규칙.
    - **행 높이 확대** (11/10, 사용자 "행높이를 조금 늘려볼까? 차트 흐름이 보이게"): 생성기 `ROW_IN` 0.225→0.29in,
      스파크 열 6.6→7.6단위·선 1.4→1.7. 그 전엔 가로·세로가 한 단위(행 높이)에 묶여 있어 행만 키우면 표 전체가
      커졌다 → 가로 단위 `COL_IN`(0.225) 분리. 글자 크기(pt)는 그대로라 차트만 커 보인다. 세 판 공통.
    - **메뉴명 '주가변동표' + 2단 서브메뉴** (11/8, 사용자): 📰 주보 > `📈 피어그룹.주가변동표`(구 주가흐름표) 서브그룹 밑
      `🚢 조선/해운/에너지`(`peerprice`, ship) · `🛡️ 방산/기계`(`peerdefcon`, **두 판을 한 페이지에**). peer_price.html 의
      `?u=` 가 쉼표 목록(`defense,construction`)을 받아 유니버스별 카드를 이어 붙인다(카드 머리에 판 이름, 파일은 각자 dir —
      `url(f,ext,dir)`). 상단 탭도 두 개(조선·해운·에너지 / 방산·기계). 11/8 첫 판의 peerdef·peercon 뷰 2개는 이것으로 대체.

58. **주가 INDEX 갤러리 — 조선 ④ 추가 · 방산판 신설 · 묶음 메인/낱장 접힘** (11/8~9, PR #542·#546): 사용자 요청 순서대로.
    - **조선 ④ 조선 5사 vs 엔진 vs 조선기자재** (ecos-fx-rates `peergroup/weekly_peer_index_image.py` `CHAIN`): 2×2 오른쪽 아래
      각주 자리에 밸류체인 3단 시총가중 지수(조선 4사+대한조선 / 한화엔진·HD현대마린엔진·STX엔진 / 기자재 20사 = coverage_flow
      위클리 조선기자재 묶음에서 엔진 제외, HD현대마린솔루션은 어디에도 안 넣음), **각주는 그림 맨 아래 띠**(`NOTE_IN`, tight_layout
      rect). 묶음 파일명 `조선주_INDEX_3종` → **`4종`** — 옛 파일을 지우자 배포본 갤러리의 묶음 카드가 깨져 사용자가 바로 봤다.
      **생성기 파일명을 바꾸면 GS-DB2 페이지 머지·배포까지 한 흐름으로 끝낼 것**(그 사이 카드가 "그림을 불러오지 못했습니다").
    - **방산판** `peergroup/weekly_defense_index_image.py`(조선판을 import — 산식·그리기·저장 재사용, 같은 워크플로 ③-2 스텝,
      출력 `output/peer_price_defense/방산_INDEX_4종` + `DIDX1~4`): ① 체계 5사 ② 부체계 11사(풍산·SNT다이내믹스·엠앤씨솔루션·
      아이쓰리시스템·퍼스텍·휴니드·빅텍·코츠테크놀로지·한일단조·삼영컴텍·웨이브일렉트로닉스 — 세션 추천, 사용자 가지치기 전)
      ③ 한국 체계·부체계 vs 미국 프라임 7 vs 유럽 체계 8 ④ 드론(Kratos·AeroVironment) vs 엔진/부품 7 vs 항공(Airbus·Dassault·
      Embraer) — 글로벌 테마, 주가흐름표 DEFENSE_SECTIONS 와 같은 티커. 데모 실측 교정: 11개 범례는 3열, 긴 제목 축약, **각주는
      한 줄에 다 적으면 오른쪽으로 넘쳐 6줄**(`NOTE_LINES`).
    - 대시보드: `ship_index.html` 이 `?u=ship|defense`(peer_price.html 과 같은 UNIVERSES 방식, 상단 탭), 사이드바 📰 주보 >
      `⚔️ 주가.INDEX.비교` 서브그룹 `🚢 조선`(shipindex) / `🛡️ 방산`(defindex). **4종 묶음 카드가 메인(펼침·강조), 낱장 ①~④는
      `<details>` 접힘**(점프 링크·해시로 오면 펼침; 버튼은 summary 밖 — summary 안 버튼은 클릭마다 접힘이 토글된다).
    - 운영 주의: 수동 실행을 장중(09:11 KST)에 돌리면 야후가 그날 장중 봉을 마지막 값으로 줘 기준일이 당일로 찍힌다 —
      07:10 자동 실행은 전일 종가 기준. `.claude/settings.json`(프로젝트 권한 허용 목록) 도 같은 PR 에서 신설.

59. **주가 INDEX — 브랜드 색 지정 · 방산 ④ 우주 · '미국 체계' · 건설기계판** (11/9~10, PR #550·#552): 58번의 후속.
    - **선 색은 사용자 지정 브랜드 색**: 조선 ②(`SHIP_STYLE`) 한화 주황 `#F37321`(한화오션·한화엔진 점선) · 현대 초록 `#00A651`
      (HD현중, HD한국조선해양 옅은 초록, HD현대마린엔진 점선) · 삼성 파랑 `#1428A0` · 대한조선 검정. 방산 ①(`PRIME_COLORS`)
      한화에어로 주황·한화시스템 옅은 주황·KAI 하늘·LIG D&A 남색·로템 초록. 건기 HD건기 초록·두산밥캣 남색·한국 묶음 골드·중국 빨강.
    - 방산 ③ '미국 프라임' → **'미국 체계'**, ④ 에 **우주(15)** 추가 — 주가변동표 '글로벌 우주·위성' 묶음과 같은 티커(각주 7줄).
    - **건설기계판** `weekly_construction_index_image.py`(조선판 import, 워크플로 ③-3, `output/peer_price_construction/건설기계_INDEX_4종`
      + `CIDX1~4`): ① HD건기·두산밥캣·한국 부품사 6(시총가중 점선) ② 한국 2사 vs 미국(CAT·Terex·Oshkosh·Manitowoc)·중국 5·일본 6
      ③ 대형 OEM 8 — HD건기·CAT·Komatsu·Hitachi CM·SANY·XCMG·Zoomlion·LiuGong, **중국은 SANY 만 실선** ④ 두산밥캣·Deere·
      **Kobelco = 모회사 Kobe Steel(5406.T)**(건설기계 자회사 비상장 — 각주에 명시)·대동. 갤러리 `?u=construction`, 사이드바
      `⚔️ 주가.INDEX.비교 › 🏗️ 기계`(conindex).
      ④ 범례 5열이 그림 폭을 넘쳐(11/10 사용자 지적) 3열·2줄로(`ncol=3` — matplotlib 범례는 열 우선 채움).
    - 운영 메모: GitHub Pages deploy 가 'syncing_files' 에서 10분 멈춰 타임아웃하는 날이 있다(11/10 새벽 2회) — 같은 run 재시도는
      'Deployment cancelled' 로 또 죽고, 다음 커밋의 새 run 은 정상. 코드 문제가 아니므로 기다리거나 새 run 으로.

60. **컨센 추적 — 1만억 미만 종목 46개가 fwd 분기·연간에서 조용히 빠지던 버그** (11/9): 사용자 "조선 섹터에 왜
    한화엔진이 없지?". DB 역추적: 10/15(fwd 분기 수집 시작) 이후 한화엔진은 모바일 API 의 당분기(3Q26) 한 줄만 남고
    연간·4Q26·1Q27 이 전부 빠졌다 — 11/7 스냅샷 기준 유니버스 318 중 **46개**(세진중공업·한미반도체·두산로보틱스·
    HLB·한올바이오파마 … 전부 소형주)가 같은 상태. 원인은 `scrape.py` 의 '그리드 로딩 완료' 판정 세 곳
    (`_GRID_READY_JS`·`_GRID_MODE_JS`·`_parse_grid`)이 **만 단위 콤마숫자(`\d{2,},\d{3}`)** 존재를 기준으로 삼은
    것 — 매출·영업이익이 전부 1만억 미만이면(한화엔진 분기 최대 5,321.8) 그 숫자가 한 줄도 없어 wait_for_function 이
    타임아웃 → 빈 리스트 반환, 로그엔 아무것도 안 남는다(30번 부류: 모름을 없음으로). WiseReport 자체는 정상(curl 로
    `c1050001_data.aspx?flag=2&frq=0|1` 받으면 한화엔진 2026E 2,094 / 2027E 3,984 / 4Q26 661 / 1Q27 872 전부 있음).
    → 판정을 **기간 행 라벨 `20\d\d.(03|06|09|12)(A|E)` + 숫자 존재**로 교체(`_GRID_LOADED_RE` 한 곳). 다음 run 부터
    46개 종목의 연간·다음분기가 채워진다. 컨테이너 Playwright 는 WiseReport 가 502 를 돌려줘 E2E 불가(curl 은 됨) —
    검증은 러너 run 결과로. 참고: 분기 fwd 는 10/15 부터라 그 전 공백은 소급되지 않는다.

61. **주보 › 📐 ER (Earnings Revision) 신설** (11/10~11): 블룸버그 ER 차트를 무료 데이터로. 수집은 별도 리포
    ecos-fx-rates `consensus/er_snapshot.py` — 야후 애널리스트 추정(30·7일 EPS 상향/하향 건수·애널 수·컨센 EPS
    현재/7·30·60·90일 전)을 **그날 값만 주므로 매일 쌓는다**(`output/earnings_revision/er_history.csv`, 11/10 시작,
    과거 소급 불가). ER = (상향−하향)/애널 수×100. 57종목: 조선(커버리지 9 + Yangzijiang·CSSC·Seatrium)·방산(한국 5 +
    미국 체계 7 + 유럽 체계 8)·건기(두산밥캣·HD건설기계 + 해외 12, Kobelco = Kobe Steel). 화면 `static/er_report.html?s=조선|방산|건설기계`
    (raw CSV 런타임 fetch, 사이드바 주보 맨 아래 `📐 ER › 조선/방산/건설기계`).
    - **정시 발사 = Claude 예약** `trig_01P6GJWVbrRxjdAxnTCQBB5n`(평일 16:44 KST) → ecos-fx-rates 가 붙은 전용 세션
      `session_015Pd8bjcVg89M261LkD3259`(sonnet, 발사 1회 ≈ $0.1)이 **ER·피어그룹(peergroup-price)·컨센서스(consensus-chart)
      3개를 한 번에** dispatch. 첫날 17:10 크론이 아예 안 와서(11/11 — 같은 날 피어그룹 크론도 8시간 지연) 옮겼다. 각 리포 크론
      (ER 평일 17:20 · 피어그룹 16:40 · 컨센서스 16:50)은 안전망 — 같은 날 재실행은 덮어쓰기라 무해. 17:12 ER 단독 예약
      `trig_012TP2cZcMjXxqnykGyn9AxJ` 는 비활성(통합으로 대체). **예약 프롬프트는 그 예약이 묶인 세션에서만 고칠 수 있다**
      (다른 세션에서 update_trigger 는 거부 — 시각·활성만 변경 가능).
    - **묶인 세션은 발사 기록이 쌓일수록 비싸진다**: 커버리지 수급 세션은 11/11 기준 1회 $1.5~1.9(컨텍스트 40만+ 토큰,
      누적 ~$29). 무거워지면 새 세션을 만들어 예약을 새로 묶을 것.
    - 한계: 야후 커버 증권사가 블룸버그보다 적다(CSSC·HD현대마린엔진 1명, 두산밥캣 2명 등 — 화면 ⚠적음). 한국 종목은
      FnGuide 증권사별 추정으로 따로 계산하는 게 다음 후보.
    - 주보 4종 예약 `trig_01VEqTcdRitLg6oWSSxQc8uQ`(16:42, 커버리지 수급 세션)의 ecos dispatch 2건은 그 세션에 ecos 리포가
      없어 매번 '범위 밖'으로 건너뛴다(11/10 피어그룹 크론 00:46 KST 도착) → 위 16:44 예약이 대신 맡는다. 그 예약의
      수급 그림(charts_only)은 그대로 유효.

이후 작업은 git log와 이 파일을 갱신하며 이어간다.

62. **주보 › ✨ 이번주.튀는차트 신설** (11/11): 사용자 "매주 토요일 새벽(미국장 끝나는 시간) 주보 5종에서 특별하게
    튀는/변화된 차트를 꼽아서 — 의미 있는 변화가 있을 때만, 갯수 제한 없이". `weekly_highlights/` +
    사이드바 📰 주보 맨 위 `✨ 이번주.튀는차트`(뷰 wkhl, `static/weekly_highlights_report.html`).
    - **판정은 전부 규칙**(`rules.py`, 임계값 `TH` 한 곳) — 생성형이 '의미 있다'를 고르지 않는다. 표본이 모자라면 그
      규칙은 침묵(30번 교훈). 이유마다 score(|값|/임계)를 둬 큰 것부터. 주가: 1주 등락 ±8%(묶음 지수 ±6%) 또는 직전
      52주 비중복 주간수익률 대비 z ±2(둘 다 걸리면 한 줄) · 52주 신고가/신저가 · INDEX 그림은 선두 교체. 수급(coverage_flow
      series.json): 외인/기관 1주 순매수가 시총의 0.5% 이상·직전 주 대비 z ±2·1년 최대·1년 누적 부호 전환(50억 미만 무시).
      컨센: 영업이익 컨센 1주 ±5% · 1개월 ±15% · 흑자/적자 전환. ER(FY1·FY2만): |ER30| ≥ 60 · EPS 1M ±8% · 3M ±15% ·
      한 주 40pp, 애널 3명 이상. **11/11 실측으로 조정** — 컨센 3%/10%·EPS 5% 는 실적시즌에 16사 중 10사가 걸렸고,
      보잉 0Q 는 EPS 가 0 근처라 변화율이 −5,526% 로 터져 정렬을 독차지 → 부호 전환은 '전환'으로 따로, score 상한 8.
    - **종목 정의는 두 곳에 두지 않는다**: `catalog.py` 가 ecos-fx-rates(public) 생성기 모듈(weekly_peer_price_image ·
      weekly_*_index_image)을 그대로 import 해 섹션·그림 구성을 읽고(그 모듈들이 맨 위에서 matplotlib 를 import 하므로
      없으면 가짜 모듈을 꽂아 종목 정의만 읽는다), 수급 묶음은 coverage_flow.build_report.WEEKLY_GROUPS, 컨센 16사는
      ecos consensus 스크립트의 COMPANIES 리터럴(ast). 컨센·ER CSV 도 그 체크아웃(`_ecos/`, gitignore)에서 읽는다.
      생성기의 그림 구성(chart1~4)을 바꾸면 `catalog.index_charts` 도 같이.
    - **그림은 원본 PNG 를 빌리지 않고 같은 데이터로 페이지가 직접 그린다**(SVG) — 갤러리 PNG 는 토 16:40 갱신이라
      새벽에 보면 목요일 미국 종가 그림 + 금요일 숫자가 섞인다. 각 카드에 '원본 그림 ↗' 링크만.
      산출물 `static/weekly_highlights/<기준일>.json` + latest.json + index.json(기준일 고르기), 페이지가 런타임 fetch.
    - 시각: 정시 = Claude 예약 작업(토 07:12 KST, 커버리지 수급 전용 세션에 묶음 — `gh workflow run weekly-highlights.yml`),
      크론 토 08:40 KST 는 안전망. 같은 날 두 번 돌아도 같은 파일 덮어쓰기(멱등)라 guard 없음. 미국 겨울시간엔 마감이
      06:00 KST 라 07:12 면 야후 일봉이 나와 있다(여름 05:00).
    - 검증: 컨테이너는 야후 불가 → `build.py --demo`(시세만 가짜, 컨센·ER·수급은 실제)로 Playwright 렌더 확인, 러너
      실검증은 브랜치 임시 push 트리거로 1회(DART 49번 방식). 테스트 23개.
