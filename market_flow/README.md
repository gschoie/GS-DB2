# 시장 수급 동향 (market_flow)

NAVER 증권에서 KOSPI 수급(투자자별 · 프로그램 매매)을 하루 4회 수집해
대시보드 리포트와 텔레그램 알림을 만든다. 단위: 억원.

## 스케줄 (평일, KST · `.github/workflows/market-flow.yml`)

| 시각 | 성격 |
| --- | --- |
| 10:00 | 장중 1차 스냅샷 (잠정) |
| 13:00 | 장중 2차 스냅샷 (잠정) |
| 15:40 | 마감 직후 잠정 + 장중 곡선 수집 |
| 16:40 | 거래소 확정치 + 장중 곡선 갱신 |

GitHub Actions cron 지연(5~15분)은 슬롯 경계를 넉넉히 잡아 흡수한다
(`scrape.py: decide_slot`). 휴장일은 모바일API `localTradedAt`이 오늘이 아니면
수집·발송·커밋을 모두 생략한다.

## 데이터 소스 (finance.naver.com/sise)

- `sise_index.naver?code=KOSPI` — 장중 잠정: 개인/외국인/기관 + 차익/비차익/전체 (`lst_kos_info`)
- `investorDealTrendDay.naver?bizdate=` — 일별 확정 투자자별(기관 세부 포함, 매 실행 ~30영업일 백필)
- `programDealTrendDay.naver?bizdate=` — 일별 확정 프로그램(차익/비차익)
- `investorDealTrendTime.naver` / `programDealTrendTime.naver` — 분 단위 장중 누적
  (페이지당 10행, 하루 ~37페이지 → 10분 격자로 샘플링)
- `m.stock.naver.com/api/index/KOSPI/basic` — 지수/등락률/휴장 판정 (JSON)

구 페이지는 EUC-KR 인코딩. bizdate 파라미터 없으면 데이터 행이 비어 있음에 주의.

## 파일

- `scrape.py` → `data/history.json` (60일 보관, 장중 곡선은 5일)
- `build_report.py` → `../telegram_research_dashboard/static/market_flow_report.html`
  (표준 라이브러리 + 인라인 SVG, 외부 의존 없음)
- `telegram_send.py` — gs_macro_get 봇 발송. 시크릿: `market_flow_TELEGRAM_BOT_TOKEN`, `market_flow_TELEGRAM_CHAT_ID`

배포는 커밋 → `deploy-pages.yml`의 workflow_run("시장 수급 동향")이 이어받는다.
대시보드에서는 📈 투자 → 💹 시장.수급.동향 (iframe).

## 2차 확장 아이디어

- 한투 KIS API로 외국인 선물 순매수·베이시스 패널 추가 (etf_signal의 토큰 로직 재사용)
- KOSDAQ 확장, AI 한줄 코멘트(flash-lite)
