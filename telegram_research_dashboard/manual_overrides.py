"""수동 기업 배정 교정.

파서가 놓치거나 의미상 다른 기업으로 잡힌 기사를 여기에 계속 추가한다.
- 키: 뉴스 기사 제목(정확히 일치)
- 값: 그 기사에 배정할 표준 기업명 리스트

`apply_corrections.py`가 이 표를 읽어 DB에 반영한다. 여러 번 실행해도 안전하다.
새 교정거리는 아래 딕셔너리에 한 줄씩 추가하면 된다.
"""

from __future__ import annotations


# 제목 → 표준 기업명 리스트
TITLE_COMPANY_OVERRIDES: dict[str, list[str]] = {
    # 군산조선소를 제이오션에 넘긴 주체는 HD현대중공업이다(제이오션이 아님).
    "제이오션重, 군산조선소 물량 미리 확보": ["HD현대중공업"],
    # 삼성重 = 삼성중공업 (최성안 부회장 자사주 매입)
    "삼성重 최성안 부회장, 자사주 1만주 매입…책임경영 의지": ["삼성중공업"],
}

# 기사 URL → 표준 기업명 리스트 (제목이 바뀌어도 안정적으로 매칭된다)
URL_COMPANY_OVERRIDES: dict[str, list[str]] = {
    # 본문 주체는 엔진 메이커. 요약이 지주사(HD현대)만 잡아 놓쳤다.
    "https://buly.kr/APxMDmu": ["HD현대마린엔진", "한화엔진"],
    # 군산조선소를 넘긴 주체는 HD현대중공업 (본문에 제이오션·HJ중공업도 언급되나 주체 아님)
    "https://buly.kr/4bkLqrJ": ["HD현대중공업"],
    # 삼성重 = 삼성중공업 (자사주 매입)
    "https://buly.kr/AlmsBOC": ["삼성중공업"],
}

# 기사 URL → 내 코멘트 (자동 backfill이 놓치거나 직접 고칠 코멘트를 여기에 추가)
URL_COMMENT_OVERRIDES: dict[str, str] = {
}
