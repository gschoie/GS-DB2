# 액티브 ETF 매매동향 (etf_holdings)

국내 상장 **액티브 ETF**의 구성종목을 매일 스냅샷하고, 전일 대비 변화(신규 편입·이탈·실매매)를
감지해 텔레그램(ETF섹터와 동일 봇)과 대시보드로 알린다.

## 파이프라인
```
fetch_holdings.py  →  detect_changes.py  →  build_report.py  →  telegram_notify.py
   스냅샷 저장         전일 대비 변화 감지      HTML 리포트          변화시 알림
```
로컬 편의 실행: `python run.py`  (텔레그램 실제 발송은 `python run.py --send`)

## 데이터 소스
- **네이버 모바일 API** `m.stock.naver.com/api/stock/{code}/etfAnalysis` → 상위 10종목의
  계약수(stockCount)·비중(etfWeight). requests로 CI 안전.
- 한계: **Top10만** 제공(11위 이하 꼬리·완전 신규편입은 미포착). KRX 전체 PDF는 WAF 차단.
  해외종목 보유 ETF는 종목명·계약수만 제공(비중 '-').
- **구성 기준일**: CU당 구성종목은 KRX 장마감 기준일이 붙는다(예: 월요일 아침엔 아직 금요일치).
  `finance.naver.com/item/coinfo.naver?code=` 페이지에서 기준일을 파싱해 스냅샷·리포트·텔레그램에 표기.
  전일과 기준일이 같으면(=새 구성 미반영) 리포트에 경고 배너 표시(`same_base`).
- 향후: 운용사(삼성/미래에셋/타임폴리오/신한) 전체 PDF 컬렉터로 교체·보강 가능. 스냅샷/감지/리포트
  구조는 소스와 무관하게 동일.

## 변화 감지 로직 (핵심)
비중(%)은 주가로 매일 저절로 흔들리므로 그대로 쓰면 노이즈. 그래서:
- **계약수 ±%**: CU 자금유출입(설정·환매)을 중앙값 배수 f로 정규화해 뺀 **순수 매매** 강도.
- **액티브 비중 ±%p**: 전일 계약수를 오늘 단가로 평가한 '무매매 가정 비중'과 실제 비중의 차(주가 상쇄).
- 트리거: 액티브 비중변화 ≥ 1.0%p(≥5.0%p 강조) 또는 계약수변화 ≥ 30%, 그리고 Top10 진입·이탈.
- 임계값은 `detect_changes.py` 상단 상수(WEIGHT_PP_MIN / WEIGHT_PP_BIG / SHARE_PCT_MIN).

## 유니버스
`etf_universe.csv` (group,name,code,active,note). active=1만 수집.
- **TIMEFOLIO → TIME 리브랜딩**: 리스트의 "TIMEFOLIO ○○"는 전부 "TIME ○○"로 상장.
- "TIME 미국나스닥100 = TIMEFOLIO 미국나스닥100"(426030) 동일상품 → 1건으로 통합.
- active=0 6종은 네이버 표기 확인 필요(테크핵심소재·미국빅테크·미국주식성장·차이나전기차·K이노베이션·Fn성장).

## 실행 타이밍 — 2단 게이트 (2026-10-05 개편)

운용사 바스켓이 **몇 시에 갱신되는지 고정돼 있지 않아** 매시간 돌면서 "새 것일 때만"
처리한다. 원래는 CU 구성종목 **기준일**을 보고 판정했는데, 그 기준일을 긁던
`finance.naver.com/item/coinfo.naver`가 9/11 Npay 증권 개편으로 죽어
(신규 SPA 리다이렉트·'기준' 표기 소멸) 9/10 이후 계속 빈 값이었다. 신규 front-api 에도
CU 기준일이 없다(`etf/analysis`·`etf/component/list` 응답 키 전수 확인). **그래서 기준일에
기대지 않는 2단 게이트로 바꿨다.**

1. **거래일 게이트** (`watch.py check`) — `m.stock.naver.com/api/index/KOSPI/basic`의
   `localTradedAt`이 오늘이 아니면 휴장일로 보고 **아무것도 하지 않는다**(market_flow 와 동일 방식).
   조회 실패는 fail-open(일단 실행). `WATCH_FORCE=1`이면 휴장일에도 실행 — 화면 수동 버튼용.
2. **구성 지문 게이트** (`fetch_holdings.snapshot`) — 직전 스냅샷과 **계약수가 같으면
   파일을 쓰지 않고** `changed=false`를 내놓아 이후 스텝(감지·리포트·텔레그램·커밋)을 전부 건너뛴다.
   비중·NAV는 주가만 움직여도 매일 바뀌므로 지문에서 뺀다. 일부 ETF 수집 실패로 종목이
   줄었을 때도 저장하지 않는다(가짜 '이탈' 방지).

> **GAS 스케줄러를 강제 실행으로 보면 안 된다.** 8/29 정시성 이관 이후 GAS 가 매시 :17 에
> `workflow_dispatch`로 쏘는데, 워크플로가 `event_name == 'workflow_dispatch'`만 보고
> `WATCH_FORCE=1`을 걸어 **판정을 통째로 건너뛰고** 있었다(10/5 대체공휴일 09·10·11시 3회 실행).
> 지금은 `inputs.via != 'scheduler'`일 때만 강제한다.

**기준일 표기는 더 이상 없다.** 화면·텔레그램은 '구성 변화 감지 시각'을 적고, 바스켓이
장 마감 뒤 갱신되므로 **여기 매매는 대개 직전 거래일의 것**이라고 명시한다.

## 배포 (GitHub Actions)
`.github/workflows/etf-holdings.yml` — 매시간 KST 09~21시(월~금) 워처 + 수동(workflow_dispatch).
- 텔레그램: `ETF_TELEGRAM_BOT_TOKEN` / `ETF_TELEGRAM_CHAT_ID` (ETF섹터와 **동일 봇**).
- 스냅샷을 커밋해야 다음날 비교가 되므로 `snapshots/`도 함께 커밋한다.
- 봇 커밋은 on:push를 안 걸므로, 3시간 주기 deploy-pages 스케줄이 리포트를 반영.
- 대시보드 🔄 버튼: Apps Script 프록시에 `workflow:'holdings' → etf-holdings.yml` 매핑 추가 필요.

## 대시보드
`telegram_research_dashboard/static/index.html`(투자 서브메뉴 "🧩 액티브ETF.매매동향") +
`app.js`(view/dispatch) + `build_static.py`(리포트를 _site로 복사).
공개 URL: https://gschoie.github.io/GS-output-dashboard/etf_holdings_report.html
