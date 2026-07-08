# KOSPI200 컨센서스 트래커

KOSPI200 종목의 **영업이익 컨센서스**를 매주 스냅샷으로 저장하고 주간 리비전(상향/하향)을 추적한다.

추적 대상 (종목별):
- **이번분기** 영업이익 컨센 (가장 가까운 추정 E 분기)
- **연간 2026·2027·2028E** 영업이익 컨센
- (보너스) 매출액·당기순이익 컨센도 함께 저장

## 데이터 소스

| 항목 | 소스 |
|---|---|
| KOSPI200 유니버스 | `finance.naver.com/sise/entryJongmok.naver?type=KPI200` |
| 이번분기 영업이익 E | 모바일 JSON `m.stock.naver.com/api/stock/{code}/finance/quarter` (토큰불필요) |
| 연간 2026~2028E | 종목분석>컨센서스 탭 `c1050001.aspx` (Playwright 렌더링) |

> 연간 그리드 값은 JS로 수초 뒤 주입되므로, Playwright에서 "재무연월 표에 값이 등장할 때까지" 폴링 후 추출한다.

## 설치

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

> ⚠️ Python 3.13에서는 `greenlet==3.1.1` 고정 필요 (최신 3.5.x는 DLL 로드 실패).

## 사용

```bash
# 주간 스냅샷 (KOSPI200 전체, ~3-4분)
python run_snapshot.py

# 테스트 (앞 5종목)
python run_snapshot.py --limit 5

# 유니버스 갱신 후 실행 (분기 리밸런싱 반영)
python run_snapshot.py --refresh-universe

# 전주 대비 리비전 리포트 (2주치 스냅샷 필요)
python report.py --metric annual  --period 2026.12   # 연간 2026
python report.py --metric annual  --period 2027.12   # 연간 2027
python report.py --metric quarter                    # 이번분기
```

## 구성

```
universe.py      KOSPI200 코드+종목명 크롤 → data/universe.json
scrape.py        fetch_quarter() 모바일JSON · scrape_annual() Playwright
db.py / schema.sql   SQLite (data/consensus.db), consensus_snapshots (long 포맷)
run_snapshot.py  유니버스→스크랩→저장 (매주 1회)
report.py        snapshot_date 간 영업이익 컨센 diff → 상향/하향 랭킹
```

## 저장 스키마 (`consensus_snapshots`, tidy long)

```
snapshot_date | code | name | kind(annual/quarter) | period(YYYY.MM) | sales | op_profit | net_profit
```

매주 append. 리비전은 `(code, kind, period)`로 snapshot_date 간 비교.

## 주간 자동화

매주 1회(예: 금요일 장마감 후) `run_snapshot.py` 실행하도록 스케줄. 이후 `report.py` 또는
대시보드 정적 페이지 빌드로 상향/하향 종목을 확인한다.
