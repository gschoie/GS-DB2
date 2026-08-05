# 시장 수급 동향 (market_flow)

NAVER 증권에서 KOSPI 수급(투자자별 · 프로그램 · K200 선물 매매)을 하루 4회 수집해
대시보드 리포트와 텔레그램 알림을 만든다. 단위: 현물·프로그램 억원, 선물은
페이지 표기 단위(보통 계약)를 `history.json`의 `futures_unit`에 기록.

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
- `investorDealTrendDay.naver?bizdate=&sosok=03` — K200 선물 투자자별(동일 템플릿, 탭만 다름).
  응답이 현물 확정치와 2일 이상 완전 일치하면 sosok 미적용으로 판단해 저장 생략(오염 방지)
- `programDealTrendDay.naver?bizdate=` — 일별 확정 프로그램(차익/비차익)
- `investorDealTrendTime.naver` / `programDealTrendTime.naver` — 분 단위 장중 누적
  (페이지당 10행, 하루 ~37페이지 → 10분 격자로 샘플링, `sosok=03`이면 선물 곡선)
- `m.stock.naver.com/api/index/KOSPI/basic` — 지수/등락률/휴장 판정 (JSON)

구 페이지는 EUC-KR 인코딩. bizdate 파라미터 없으면 데이터 행이 비어 있음에 주의.

## 파일

- `scrape.py` → `data/history.json` (60일 보관, 장중 곡선은 5일)
- `build_report.py` → `../telegram_research_dashboard/static/market_flow_report.html`
  (표준 라이브러리 + 인라인 SVG, 외부 의존 없음)
- `telegram_send.py` — gs_macro_get 봇 발송. 시크릿: `market_flow_TELEGRAM_BOT_TOKEN`, `market_flow_TELEGRAM_CHAT_ID`

배포는 커밋 → `deploy-pages.yml`의 workflow_run("시장 수급 동향")이 이어받는다.
대시보드에서는 📈 투자 → 💹 시장.수급.동향 (iframe).

## 리포트 구성 (현·선물)

외인·기관의 선물–현물 흐름을 같이 본다:

- **현·선물 포지셔닝 카드** — 당일 현물(확정 우선, 없으면 잠정 스냅샷) × 선물
  (확정 우선, 없으면 장중 곡선 마지막 점) 방향 조합을 4분면으로 해석
  (동반 매수=방향성 강세 / 현물 매수·선물 매도=헤지 / 현물 매도·선물 매수=숏커버 / 동반 매도=리스크 오프)
- **현물 vs 선물 20일 이중축 차트** — 외국인·기관 각각, 현물(바·좌축 억원)과
  선물(라인·우축 계약)을 0선 공유 대칭축으로 겹쳐 그림
- **장중 선물 누적 곡선** — 15:40 이후 수집분, 개인/외국인/기관
- 시그널 룰에 외국인 현·선물 조합 해석 추가 (선물 |800계약| 이상일 때만)

## 2차 확장 아이디어

- 한투 KIS API로 베이시스(선물-현물 괴리) 패널 추가 (etf_signal의 토큰 로직 재사용)
- KOSDAQ 확장, AI 한줄 코멘트(flash-lite)
