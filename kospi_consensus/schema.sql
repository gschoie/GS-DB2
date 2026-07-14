-- KOSPI200 컨센서스(영업이익) 주간 스냅샷 저장 (tidy long 포맷)
-- 매주 한 번 append. 리비전 diff는 (code, kind, period)로 snapshot_date 간 비교.

CREATE TABLE IF NOT EXISTS consensus_snapshots (
  snapshot_date TEXT NOT NULL,          -- 추적 주차 기준일 (해당 주 월요일, YYYY-MM-DD)
  code          TEXT NOT NULL,          -- 종목코드 6자리
  name          TEXT NOT NULL,          -- 종목명
  kind          TEXT NOT NULL,          -- 'annual' | 'quarter'
  period        TEXT NOT NULL,          -- 'YYYY.MM' (연간=12월결산, 분기=해당분기말)
  sales         REAL,                   -- 매출액 컨센 (억원)
  op_profit     REAL,                   -- 영업이익 컨센 (억원)  ← 핵심
  net_profit    REAL,                   -- 당기순이익 컨센 (억원)
  captured_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (snapshot_date, code, kind, period)
);

CREATE INDEX IF NOT EXISTS idx_cs_series ON consensus_snapshots(code, kind, period, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_cs_date   ON consensus_snapshots(snapshot_date);

-- 유니버스 스냅샷 (주차별 KOSPI200 구성종목 기록)
CREATE TABLE IF NOT EXISTS universe (
  snapshot_date TEXT NOT NULL,
  code          TEXT NOT NULL,
  name          TEXT NOT NULL,
  PRIMARY KEY (snapshot_date, code)
);

-- 스냅샷 시점 종가 (주가 변동폭 계산용)
CREATE TABLE IF NOT EXISTS stock_prices (
  snapshot_date TEXT NOT NULL,
  code          TEXT NOT NULL,
  price_date    TEXT,          -- 실제 종가 기준일 (YYYY-MM-DD)
  close         REAL,          -- 종가 (원)
  PRIMARY KEY (snapshot_date, code)
);
