"""원재료 매입 · 원재료 가격변동 · 제품 가격변동 — 주제별 정규화 규칙(프롬프트·출력 형식·후처리).

생산능력(capacity)은 normalize.py 의 원래 경로가 맡고, 여기 세 주제는 같은 모델 호출 틀에
system 프롬프트와 행 스키마만 바꿔 끼운다. 산출물은 data/normalized/<topic>/<코드>_<rcept_no>.json,
all.json 에는 주제 이름 키로 묶인다(대시보드 주제 탭).
"""
from __future__ import annotations

import re

from common import DART_VIEWER

COMMON_RULES = """공통 규칙:
- 단위를 바꾸지 마라. 표·단위 문구·셀 안의 단위를 그대로 적는다('원/TON', 'USD', '백만$', '천원/대', '백만원').
  '1,130,000원' 처럼 셀에 단위가 섞여 있으면 숫자와 단위를 나눈다. '$3.38' → 3.38 + '$/리터'(단위 문구가 있으면 그것).
- period 는 데이터 열의 기간이다. 열이 2025년·2024년·2023년이면 행 셋. 기말 YYYY-MM: '2025년'→2025-12,
  '2024년 3분기'→2024-09, '반기'→-06, '1분기'→-03. '제N기' 는 fiscal_hint 의 당기 기수를 따르고 한 기 앞은 한 해 전.
  열이 기간을 안 적은 표(당기 매입 현황 등)는 보고서 period 를 쓴다.
- 모르는 값·'-'·'해당없음' 은 null. 추정·계산으로 채우지 마라. 합계·소계 행은 segment='합계' 로 남긴다.
- segment·item·product 는 원문 글자를 쓰되 글자 사이 공백은 지워라('조 선'→'조선', '기 자 재'→'기자재'). 회사·사업소가
  행을 가르면 company 에 적는다. 설명형 셀(가격변동 원인·비고)은 note 에 요약한다.
- 관련 없는 표(매출액 표, 사업장 주소, 투자 계획)는 행을 만들지 말고 review 에 표 번호와 이유를 적어라.
- 숫자는 쉼표를 뺀 숫자형. '4,199,530(57.3%)' 처럼 금액과 비중이 한 칸이면 amount=4199530, share_pct=57.3."""

SPECS = {
    "material": {
        "label": "원재료 매입",
        "system": "당신은 DART 정기보고서의 '주요 원재료 매입 현황' 표(품목·매입액·비중·주요 매입처)를 공통 스키마로 옮기는 담당자다.\n" + COMMON_RULES +
                  "\n- 매입처만 있는 표(주요 매입처·특수관계·독과점)는 item 에 품목(없으면 ''), suppliers 에 매입처, amount=null 로 행을 만든다.",
        "schema": """## 출력 형식 (JSON 하나만)
{"rows": [ {행}, … ], "review": [ {"table": 표번호, "reason": "…"}, … ]}
행 = {"period": "YYYY-MM", "period_label": "열 머리글 그대로(없으면 '당기')", "segment": "", "company": "", "purchase_type": "",
      "item": "", "amount": 숫자|null, "unit": "", "share_pct": 숫자|null, "suppliers": "", "note": "", "confidence": "high|low"}""",
        "fields": ["segment", "company", "purchase_type", "item", "amount", "unit", "share_pct", "suppliers"],
        "value_keys": ["amount", "share_pct", "suppliers"],
    },
    "material_price": {
        "label": "원재료 가격변동",
        "system": "당신은 DART 정기보고서의 '주요 원재료 등의 가격변동추이' 표를 공통 스키마로 옮기는 담당자다.\n" + COMMON_RULES +
                  "\n- '가격변동 원인' 같은 설명 표는 같은 품목 행의 note 에 붙이고, 품목이 안 맞으면 segment 행 하나로 price=null, note 에 요약.",
        "schema": """## 출력 형식 (JSON 하나만)
{"rows": [ {행}, … ], "review": [ {"table": 표번호, "reason": "…"}, … ]}
행 = {"period": "YYYY-MM", "period_label": "열 머리글 그대로", "segment": "", "item": "", "unit": "", "price": 숫자|null,
      "note": "", "confidence": "high|low"}""",
        "fields": ["segment", "item", "unit", "price"],
        "value_keys": ["price"],
    },
    "product_price": {
        "label": "제품 가격변동",
        "system": "당신은 DART 정기보고서의 '주요 제품 등의 가격변동추이' 표를 공통 스키마로 옮기는 담당자다.\n" + COMMON_RULES +
                  "\n- 선종·모델 규격('320,000 DWT', 'S590', '소형')은 spec 에, 제품군·품목은 product 에. 출처(Clarksons 등)는 note 에.",
        "schema": """## 출력 형식 (JSON 하나만)
{"rows": [ {행}, … ], "review": [ {"table": 표번호, "reason": "…"}, … ]}
행 = {"period": "YYYY-MM", "period_label": "열 머리글 그대로", "segment": "", "product": "", "spec": "", "unit": "",
      "price": 숫자|null, "note": "", "confidence": "high|low"}""",
        "fields": ["segment", "product", "spec", "unit", "price"],
        "value_keys": ["price"],
    },
}
TOPIC_ORDER = list(SPECS)

_PERIOD_RE = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
_SPACED = re.compile(r"(?<=[가-힣])\s+(?=[가-힣])")


def _tidy(s: str) -> str:
    """'조 선(특 수 선)' → '조선(특수선)' — 한글 사이 공백만."""
    return _SPACED.sub("", (s or "").strip())


def finalize_topic(topic: str, meta: dict, result: dict) -> tuple[list[dict], list[dict]]:
    """모델 출력 → (저장 행, 검토). 값이 하나도 없는 행·confidence low·기간 형식 오류는 검토로."""
    spec = SPECS[topic]
    out: list[dict] = []
    review = [{"rcept_no": meta["rcept_no"], "company": meta["company"], "table": r.get("table"),
               "reason": f"[{topic}] {r.get('reason', '')}"} for r in result.get("review", [])]
    seen: set[tuple] = set()
    for r in result.get("rows", []):
        if all(r.get(k) in (None, "", []) for k in spec["value_keys"]):
            continue
        if r.get("confidence") == "low":
            review.append({"rcept_no": meta["rcept_no"], "company": meta["company"], "table": None,
                           "reason": f"[{topic}] confidence=low: {r.get('segment')}/{r.get('item') or r.get('product')} {r.get('period')}"})
            continue
        period = r.get("period") or meta.get("period", "")
        if not _PERIOD_RE.fullmatch(period or ""):
            review.append({"rcept_no": meta["rcept_no"], "company": meta["company"], "table": None,
                           "reason": f"[{topic}] period 형식 오류 '{r.get('period')}' ({r.get('period_label')})"})
            continue
        row = {"company": meta["company"], "stock_code": meta["stock_code"], "sector": meta.get("sector", ""),
               "topic": topic, "period": period, "period_label": r.get("period_label", ""),
               "report_type": meta.get("report_type", ""), "report_label": meta.get("report_nm", ""),
               "report_period": meta.get("period", ""), "rcept_dt": meta.get("rcept_dt", ""),
               "source_rcept_no": meta["rcept_no"], "dart_url": DART_VIEWER.format(rcept_no=meta["rcept_no"]),
               "note": r.get("note", "")}
        for f in spec["fields"]:
            v = r.get(f)
            row[f] = _tidy(v) if isinstance(v, str) else v
        key = (period, row.get("segment", ""), row.get("company", "") if topic == "material" else "",
               row.get("item", "") or row.get("product", ""), row.get("spec", ""), row.get("purchase_type", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out, review


def dedupe_latest(rows: list[dict], topic: str) -> list[dict]:
    """같은 (회사, 줄, 기간) 이 여러 보고서에 겹치면 최신 접수(사업보고서 3개년 열 등)의 값을 남긴다."""
    best: dict[tuple, dict] = {}
    for r in rows:
        key = (r.get("stock_code"), r.get("segment", ""), r.get("company", "") if topic == "material" else "",
               r.get("item", "") or r.get("product", ""), r.get("spec", ""), r.get("purchase_type", ""), r.get("period", ""))
        cur = best.get(key)
        if cur is None or r.get("source_rcept_no", "") > cur.get("source_rcept_no", ""):
            best[key] = r
    return sorted(best.values(), key=lambda r: (r.get("sector", ""), r.get("company", ""), r.get("segment", ""),
                                                r.get("item", "") or r.get("product", ""), r.get("spec", ""), r.get("period", "")))
