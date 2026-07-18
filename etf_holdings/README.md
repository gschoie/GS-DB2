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

## 배포 (GitHub Actions)
`.github/workflows/etf-holdings.yml` — 매일 KST 18:00 자동 + 수동(workflow_dispatch).
- 텔레그램: `ETF_TELEGRAM_BOT_TOKEN` / `ETF_TELEGRAM_CHAT_ID` (ETF섹터와 **동일 봇**).
- 스냅샷을 커밋해야 다음날 비교가 되므로 `snapshots/`도 함께 커밋한다.
- 봇 커밋은 on:push를 안 걸므로, 3시간 주기 deploy-pages 스케줄이 리포트를 반영.
- 대시보드 🔄 버튼: Apps Script 프록시에 `workflow:'holdings' → etf-holdings.yml` 매핑 추가 필요.

## 대시보드
`telegram_research_dashboard/static/index.html`(투자 서브메뉴 "🧩 액티브ETF.매매동향") +
`app.js`(view/dispatch) + `build_static.py`(리포트를 _site로 복사).
공개 URL: https://gschoie.github.io/GS-output-dashboard/etf_holdings_report.html
