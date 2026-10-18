# -*- coding: utf-8 -*-
"""네이버 모바일 금융 JSON API에서 국내 종목의 컨센 지표·재무를 읽는다.

왜 모바일 API인가
-----------------
원래는 PC 종목 페이지(finance.naver.com/item/main.naver)의 '기업실적분석' 표를
pd.read_html 로 긁었다. Npay 증권 전면 개편(CLAUDE.md 31번)으로 옛 PC 페이지가
표 없는 SPA 로 바뀌며 죽었다 — 10/19 러너 실측 'No tables found', 스냅샷
역추적으로는 10/3 이전부터 naver=None. 모바일 JSON API
(m.stock.naver.com/api/stock/{code}/finance/annual·quarter)는 같은 표를 JSON 으로
주고, kospi_consensus.scrape.fetch_quarters 가 분기판을 지금도 쓰고 있다
(러너 생존 확인 10/15).

무엇을 가져오나
---------------
- estimates(): 연간 추정(E) 열의 PER·PBR·ROE — 국내 종목은 에프앤가이드 컨센이
  원본이라 야후 산출값을 이걸로 덮어쓴다(화면 ᴺ 표기). 확정(A) 지표는 건드리지
  않는다(41종목 전부 같은 산식이어야 피어 비교가 성립).
- financial_rows(): 연간·분기의 매출액·영업이익·당기순이익(억원 → 원 환산) —
  회사 행 클릭 상세 패널의 국내 보강용. 분기에는 야후에 없는 분기 영업이익
  컨센까지 실린다.

주의: 실패하면 빈 값(예외를 삼킨다). 호출 쪽이 야후 값으로 폴백하므로 화면이
비지는 않지만, 그만큼 죽어도 티가 안 난다(30번 교훈) — 수집 로그의
'📊 네이버 컨센/분기 재무 적용' 줄이 살아있는지가 관측 지점이다.
"""

from __future__ import annotations

import json
import re
from urllib.request import Request, urlopen

FINANCE_API = "https://m.stock.naver.com/api/stock/{code}/finance/{period}"

EOKWON = 1e8   # 표 단위: 억원 → 원

# 재무 상세용 행. '영업이익률' 행이 '영업이익'에 걸리지 않게 lookahead 로 자른다.
FIN_ROW_KEYS = [
    ("sales", r"^매출액"),
    ("op", r"^영업이익(?!률)"),
    ("ni", r"^당기순이익"),
]

# 컨센 지표 행. 'PER(배)'처럼 단위가 붙으므로 앞부분 일치로 본다.
METRIC_ROW_KEYS = [
    ("per", r"^PER"),
    ("pbr", r"^PBR"),
    ("roe", r"^ROE"),
]


def fetch_finance(code, period, timeout=15):
    """모바일 금융 API 호출 → financeInfo dict. (테스트에서 갈아끼우는 이음매)

    period 는 'annual' 또는 'quarter'. 재무 정보가 없는 종목(신규상장·스팩 등)은
    financeInfo 가 null 로 온다 → None.
    """
    request = Request(
        FINANCE_API.format(code=code, period=period),
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://m.stock.naver.com/"},
    )
    with urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))
    return (data.get("financeInfo") if isinstance(data, dict) else None) or None


def safe_fetch(code, period):
    """fetch_finance 의 예외 흡수판 — 실패 시 None (호출 쪽이 야후로 폴백)."""
    try:
        return fetch_finance(code, period)
    except Exception as exc:
        print(f"    · 네이버 재무 조회 실패({code}/{period}): {exc}")
        return None


def _number(value):
    if value is None:
        return None
    text = str(value).replace(",", "").replace("%", "").strip()
    if text in ("", "-", "nan", "N/A", "None"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _columns(info):
    """trTitleList → [(key, 연도, 월, 추정 여부)]. 기간 표기가 아닌 열은 버린다."""
    out = []
    for title in (info or {}).get("trTitleList") or []:
        key = title.get("key")
        match = re.match(r"^(20\d\d)\.(\d\d)", str(title.get("title", "")))
        if not key or not match:
            continue
        out.append((key, int(match.group(1)), int(match.group(2)),
                    title.get("isConsensus") == "Y"))
    return out


def _row(info, pattern):
    """rowList 에서 제목이 패턴에 처음 걸리는 행의 columns dict (없으면 None)."""
    for row in (info or {}).get("rowList") or []:
        if re.match(pattern, str(row.get("title", "")).strip()):
            return row.get("columns") or {}
    return None


def _value(columns, key):
    if not columns:
        return None
    return _number(((columns.get(key) or {}).get("value")))


# '안 넘겼다'와 '조회했는데 실패(None)'를 구분하는 보초값 — None 을 넘기면
# 다시 조회하지 않는다(실패를 두 번 두드리지 않게).
_UNSET = object()


def estimates(code, finance=_UNSET):
    """종목코드 → {연도: {'per':…, 'pbr':…, 'roe':…}} (연간 추정 열만).

    실패하면 빈 dict. 호출 쪽이 기존 산출(롤포워드)로 폴백한다.
    """
    info = finance if finance is not _UNSET else safe_fetch(code, "annual")
    if not info:
        return {}
    rows = {metric: _row(info, pattern) for metric, pattern in METRIC_ROW_KEYS}
    result = {}
    for key, year, _month, est in _columns(info):
        if not est:
            continue          # 확정 실적 열은 쓰지 않는다(우리 산식으로 계산)
        bucket = {}
        for metric, columns in rows.items():
            value = _value(columns, key)
            if value is not None:
                bucket[metric] = value
        if bucket:
            result[year] = bucket
    return result


def financial_rows(code, annual=_UNSET, quarter=_UNSET):
    """연간·분기의 매출·영업이익·당기순이익(억원 → 원 환산)을 기간별로 뽑는다.

    반환: {"quarterly": [...], "annual": [...]} — 각 행 {year, month, est, sales, op, ni}.
    실패하면 빈 목록 — 호출 쪽이 야후 값을 그대로 쓴다.
    """
    out = {"quarterly": [], "annual": []}
    for bucket, period, info in (("annual", "annual", annual),
                                 ("quarterly", "quarter", quarter)):
        if info is _UNSET:
            info = safe_fetch(code, period)
        if not info:
            continue
        rows = {field: _row(info, pattern) for field, pattern in FIN_ROW_KEYS}
        for key, year, month, est in _columns(info):
            entry = {"year": year, "month": month, "est": est}
            for field, columns in rows.items():
                value = _value(columns, key)
                entry[field] = value * EOKWON if value is not None else None
            if entry["sales"] is None and entry["op"] is None and entry["ni"] is None:
                continue
            out[bucket].append(entry)
        out[bucket].sort(key=lambda r: (r["year"], r["month"]))
    return out
