# -*- coding: utf-8 -*-
"""네이버 금융 '기업실적분석'에서 국내 종목의 컨센서스 PER·PBR·ROE를 읽는다.

왜 필요한가
-----------
야후는 국내 종목의 컨센으로 EPS·매출만 준다. 그래서 컨센 PBR·ROE는 우리가
이익잉여금 롤포워드로 자체 산출해 왔다(화면에 `*` 표기). 반면 네이버가 싣는
에프앤가이드 컨센은 **추정 PER·PBR·ROE를 그대로** 준다 — 국내 종목은 이쪽이
원본이고, 국내 증권사 추정치라 시장에서 통용되는 값과도 맞는다.

확정(A) 지표는 건드리지 않는다. 그건 41종목 전부 같은 산식(기말시총÷순이익)으로
계산해야 피어 비교가 성립하기 때문이다. 여기서 가져오는 건 컨센(E)뿐이다.

주의: 표 구조가 바뀌면 조용히 빈 값이 된다(예외를 삼키고 None). 호출 쪽에서
값이 없으면 기존 롤포워드 산출로 자동 폴백하므로 화면이 비지는 않는다.
"""

from __future__ import annotations

import io
import re
from urllib.request import Request, urlopen

import pandas as pd

NAVER_ITEM = "https://finance.naver.com/item/main.naver?code={code}"

# 네이버 표의 행 이름 → 우리가 쓰는 키. 'PER(배)' 처럼 단위가 붙어 있어 부분일치로 본다.
ROW_KEYS = [
    ("per", ("PER",)),
    ("pbr", ("PBR",)),
    ("roe", ("ROE",)),
]

YEAR_PATTERN = re.compile(r"(20\d{2})\.(\d{2})")


def read_tables(code, timeout=20):
    """네이버 종목 페이지의 표들을 DataFrame 목록으로. (테스트에서 갈아끼우는 이음매)"""
    request = Request(
        NAVER_ITEM.format(code=code),
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com/"},
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read()
    # 네이버는 EUC-KR(cp949)로 내려준다.
    html = raw.decode("cp949", errors="replace")
    return pd.read_html(io.StringIO(html))


def _column_year(column):
    """열 머리글 → (연도, 추정치 여부). '2026.12(E)' → (2026, True)"""
    parts = column if isinstance(column, tuple) else (column,)
    text = " ".join(str(p) for p in parts)
    match = YEAR_PATTERN.search(text)
    if not match:
        return None, False
    return int(match.group(1)), "(E)" in text.replace(" ", "")


def _number(value):
    if value is None:
        return None
    text = str(value).replace(",", "").replace("%", "").strip()
    if text in ("", "-", "nan", "N/A"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _pick_table(tables):
    """PER 행을 가진 '기업실적분석' 표를 고른다."""
    for table in tables:
        if table is None or table.empty or table.shape[1] < 2:
            continue
        labels = table.iloc[:, 0].astype(str)
        if labels.str.contains("PER").any() and labels.str.contains("ROE").any():
            return table
    return None


def estimates(code, tables=None):
    """종목코드 → {연도: {'per':…, 'pbr':…, 'roe':…}} (추정치 열만).

    실패하면 빈 dict. 호출 쪽이 기존 산출로 폴백한다.
    """
    try:
        frames = tables if tables is not None else read_tables(code)
    except Exception as exc:
        print(f"    · 네이버 컨센 조회 실패({code}): {exc}")
        return {}

    table = _pick_table(frames or [])
    if table is None:
        return {}

    labels = table.iloc[:, 0].astype(str)
    result = {}
    for position, column in enumerate(table.columns):
        year, is_estimate = _column_year(column)
        if not year or not is_estimate:
            continue          # 확정 실적 열은 쓰지 않는다(우리 산식으로 계산)
        bucket = {}
        for key, needles in ROW_KEYS:
            match = labels.str.contains(needles[0], regex=False)
            if not match.any():
                continue
            value = _number(table.iloc[match.idxmax(), position])
            if value is not None:
                bucket[key] = value
        if bucket:
            result[year] = bucket
    return result
