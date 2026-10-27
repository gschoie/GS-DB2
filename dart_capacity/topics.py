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
- segment·item·product 는 원문 글자를 쓰되 한글 낱말의 글자 사이 공백만 지워라('조 선'→'조선', '기 자 재'→'기자재'; 영문 'STEEL PLATE'·'Compact Equipment' 의 띄어쓰기는 그대로). 부문 이름의 꼬리 '부문'·'사업부문' 은 뗀다('조선부문'→'조선'). 회사·사업소가
  행을 가르면 entity 에 적는다(회사 자체는 쓰지 않는다 — 보고서 메타가 채운다). 설명형 셀(가격변동 원인·비고)은 note 에 요약한다.
- 관련 없는 표(매출액 표, 사업장 주소, 투자 계획)는 행을 만들지 말고 review 에 표 번호와 이유를 적어라.
- 숫자는 쉼표를 뺀 숫자형. '4,199,530(57.3%)' 처럼 금액과 비중이 한 칸이면 amount=4199530, share_pct=57.3."""

SPECS = {
    "material": {
        "label": "원재료 매입",
        "system": "당신은 DART 정기보고서의 '주요 원재료 매입 현황' 표(품목·매입액·비중·주요 매입처)를 공통 스키마로 옮기는 담당자다.\n" + COMMON_RULES +
                  "\n- 매입처만 있는 표(주요 매입처·특수관계·독과점)는 item 에 품목(없으면 ''), suppliers 에 매입처, amount=null 로 행을 만든다."
                  "\n- entity 는 표에 '해당 회사'·'회사'·'사업소' 열이 있을 때만 그 셀을 적고, 없으면 ''. 소계·합계 행은 item 에 '소계'/'합계' 로 적고"
                  " segment 는 그 소계가 속한 부문(총합계는 segment='합계', item='합계'), purchase_type 은 ''.",
        "schema": """## 출력 형식 (JSON 하나만)
{"rows": [ {행}, … ], "review": [ {"table": 표번호, "reason": "…"}, … ]}
행 = {"period": "YYYY-MM", "period_label": "열 머리글 그대로(없으면 '당기')", "segment": "", "entity": "", "purchase_type": "",
      "item": "", "amount": 숫자|null, "unit": "", "share_pct": 숫자|null, "suppliers": "", "note": "", "confidence": "high|low"}""",
        "fields": ["segment", "entity", "purchase_type", "item", "amount", "unit", "share_pct", "suppliers"],
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

_NUMERIC = {"amount", "share_pct", "price", "suppliers"}  # 문자열이 아닌 칸은 None 그대로
_PERIOD_RE = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
_SPACED = re.compile(r"(?<=[가-힣])\s+(?=[가-힣])")


_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")


def _tidy(s: str) -> str:
    """'조 선(특 수 선)' → '조선(특수선)' — 한글 사이 공백만. 모델이 붙여 쓴 영문('CompactEquipment')은 다시 띄운다."""
    return _CAMEL.sub(" ", _SPACED.sub("", (s or "").strip()))


_STR_FIELDS = ("segment", "entity", "purchase_type", "item", "product", "spec", "unit", "note", "period_label")


def migrate_row(row: dict, topic: str, company_name: str = "") -> dict:
    """저장된 행의 옛 모양을 현재 스키마로: material 의 옛 'company'(법인) → 'entity' + 회사명 복원, null 문자열 칸 → ''.
    rebuild 때 매번 적용되므로 모델을 다시 부르지 않아도 된다."""
    r = dict(row)
    if topic == "material" and "entity" not in r:
        r["entity"] = r.get("company") or ""
        if company_name:
            r["company"] = company_name
    for f in _STR_FIELDS:
        if r.get(f) is None:
            r[f] = ""
        elif isinstance(r[f], str):
            r[f] = _tidy(r[f]) if f not in ("note", "period_label") else r[f]
    if topic == "material":
        _fix_subtotal(r)
    return r


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
            # 모델이 null 로 비우는 문자열 칸(spec·segment 등)은 "" 로 — 정렬·중복 키가 None 과 섞이면 터진다
            row[f] = _tidy(v) if isinstance(v, str) else ("" if v is None and f not in _NUMERIC else v)
        _fix_subtotal(row)
        key = _row_key(row, topic)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out, review


def _s(v) -> str:
    """None·숫자를 정렬 가능한 문자열로."""
    return "" if v is None else str(v)


def _row_key(row: dict, topic: str) -> tuple:
    return (_s(row.get("period")), _s(row.get("segment")), _s(row.get("entity")) if topic == "material" else "",
            _s(row.get("item")) or _s(row.get("product")), _s(row.get("spec")), _s(row.get("purchase_type")))


_KEY_STRIP = re.compile(r"[\s,·/()\[\]㈜(주)㈔*]+|및|(사업)?부문|등$")


def _k(v) -> str:
    """비교용 키: 공백·쉼표·법인 표지를 지운다 — 'HD현대중공업㈜,HD현대엔진(유)' 과 'HD현대중공업㈜HD현대엔진(유)' 은 같은 법인 묶음."""
    return _KEY_STRIP.sub("", _s(v)).lower()


def canonicalize_topic(rows: list[dict], topic: str) -> list[dict]:
    """보고서마다 조금씩 다른 부문·품목·법인 표기를 회사 안에서 통일한다(최신 접수의 표기로). 입력은 바꾸지 않는다."""
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        key = (_s(r.get("stock_code")), _k(r.get("segment")), _k(r.get("entity")) if topic == "material" else "",
               _k(r.get("item")) or _k(r.get("product")), _k(r.get("spec")), _k(r.get("purchase_type")))
        groups.setdefault(key, []).append(r)
    # 분기보고서는 '해당 회사' 열이 없어 entity 가 비고 사업보고서에는 있다(매입유형도 마찬가지) → 같은 줄에
    # 값이 하나뿐이면 빈 쪽을 거기로 합친다. 값이 둘 이상이면 빈 쪽이 어디인지 모르니 그대로 둔다.
    for drop in ((2,), (5,), (2, 5)):               # entity · purchase_type · 둘 다 다른 경우
        by_line: dict[tuple, dict[tuple, tuple]] = {}
        for key in list(groups):
            line = tuple(v for i, v in enumerate(key) if i not in drop)
            by_line.setdefault(line, {})[tuple(key[i] for i in drop)] = key
        for ents in by_line.values():
            if len(ents) < 2:
                continue
            blank = tuple("" for _ in drop)
            named = [k for k in ents if k != blank]
            if blank in ents and len(named) == 1:
                groups[ents[named[0]]].extend(groups.pop(ents[blank]))
                continue
            # 표기가 둘 이상이라도 기간이 서로 안 겹치면(사업보고서 vs 분기보고서가 다르게 적은 것) 한 줄로 본다.
            # 같은 기간에 둘 다 있으면(한화오션 vs Philly Shipyard '강재,기자재,의장재등') 진짜 다른 줄이다.
            keys = list(ents.values())
            seen: set[str] = set(); disjoint = True
            for k in keys:
                ps = {_s(r.get("period")) for r in groups[k]}
                if ps & seen:
                    disjoint = False; break
                seen |= ps
            if disjoint:
                target = max(keys, key=lambda k: max(_s(r.get("source_rcept_no")) for r in groups[k]))
                for k in keys:
                    if k != target:
                        groups[target].extend(groups.pop(k))
    out: list[dict] = []
    fields = ("segment", "entity", "item", "product", "spec", "purchase_type")
    for grp in groups.values():
        ordered = sorted(grp, key=lambda r: _s(r.get("source_rcept_no")), reverse=True)   # 최신 접수 먼저
        disp = {}
        for f in fields:
            if any(f in r for r in ordered):
                disp[f] = next((r[f] for r in ordered if r.get(f)), ordered[0].get(f))   # 최신 중 값이 있는 표기
        out.extend({**r, **disp} for r in grp)
    return out


_SUBTOTAL = {"소계", "합계", "총계", "계"}


def _fix_subtotal(row: dict) -> None:
    """모델이 '소계' 를 segment·purchase_type·item 중 아무 데나 적는다 → item 으로 모으고 나머지 칸은 비운다.
    총합계(segment 가 합계이거나 부문 없이 합계)는 segment='합계', item='합계'."""
    words = [row.get(f, "") for f in ("item", "purchase_type", "segment")]
    if not any(w in _SUBTOTAL for w in words):
        return
    total = any(w in ("합계", "총계", "계") for w in words)
    seg = row.get("segment", "")
    if seg in _SUBTOTAL:
        seg = "합계" if total else ""
    elif not seg and total:
        seg = "합계"
    row["segment"] = seg
    row["item"] = "합계" if (total or seg == "합계") else "소계"
    if row.get("purchase_type") in _SUBTOTAL:
        row["purchase_type"] = ""


def dedupe_latest(rows: list[dict], topic: str) -> list[dict]:
    """같은 (회사, 줄, 기간) 이 여러 보고서에 겹치면 최신 접수(사업보고서 3개년 열 등)의 값을 남긴다."""
    best: dict[tuple, dict] = {}
    for r in canonicalize_topic(rows, topic):
        key = (_s(r.get("stock_code")),) + _row_key(r, topic)
        cur = best.get(key)
        if cur is None or _s(r.get("source_rcept_no")) > _s(cur.get("source_rcept_no")):
            best[key] = r
    return sorted(best.values(), key=lambda r: (_s(r.get("sector")), _s(r.get("company")), _s(r.get("segment")),
                                                _s(r.get("item")) or _s(r.get("product")), _s(r.get("spec")), _s(r.get("period"))))
