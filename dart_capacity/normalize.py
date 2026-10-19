"""추출된 표 → 공통 스키마 JSON (Claude API).

  python normalize.py                 # data/extracted/*.json 중 미처리 보고서만
  python normalize.py --codes 329180  # 일부 회사만
  python normalize.py --force         # 처리 장부(data/processed.json) 무시하고 다시
  python normalize.py --rebuild       # 모델 호출 없이 data/normalized/*.json → all.json 만 다시 묶기

보고서 하나 = 모델 호출 하나(그 보고서의 채택 표 전부를 한 번에 넘겨 능력·실적·가동률 표를
부문/제품/기간으로 합치게 한다). 결과는 data/normalized/<코드>_<rcept_no>.json,
전체 묶음은 data/normalized/all.json(대시보드가 읽는 파일), 모호한 건 data/review.csv.

규칙(프롬프트에도 같은 말이 있다 — 두 곳을 같이 고칠 것):
  - 단위는 바꾸지 않는다. 표에 적힌 단위 그대로(척·CGT·톤·대·백만원·천GT·천M/H…).
  - period 는 **데이터 열의 기간**(보고서 접수 기간이 아님). 사업보고서 한 장에 3개 연도가 있으면 3개 행.
  - 모르는 값은 null. 지어내지 않는다. 합계(계·합계) 행도 segment='합계' 로 남긴다.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

from common import DART_VIEWER, EXTRACTED, NORMALIZED, REVIEW_CSV, DATA

PROCESSED = DATA / "processed.json"
MODEL = os.environ.get("DART_CAPACITY_MODEL", "claude-opus-5-5")
MAX_TABLE_ROWS = 60          # 이보다 큰 표는 모델에 안 넘기고 검토로(생산능력 표는 보통 30행 미만)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["rows", "review"],
    "properties": {
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["period", "period_label", "segment", "product", "unit",
                             "capacity", "production", "utilization_pct", "note", "basis",
                             "cumulative", "capacity_unit", "production_unit", "confidence"],
                "properties": {
                    "period": {"type": "string", "description": "데이터 기간의 기말 YYYY-MM (예: 2025년→2025-12, 2023년 3분기→2023-09, 제12기→사업연도 말)"},
                    "period_label": {"type": "string", "description": "표의 열 머리글 그대로 (예: '2023년 3분기', '제12기')"},
                    "segment": {"type": "string", "description": "사업부문 (없으면 '')"},
                    "product": {"type": "string", "description": "품목/제품군/사업소 등 하위 구분 (없으면 '')"},
                    "unit": {"type": "string", "description": "원문 단위 그대로. 능력·실적 단위가 다르면 능력 단위"},
                    "capacity": {"type": ["number", "null"]},
                    "production": {"type": ["number", "null"]},
                    "utilization_pct": {"type": ["number", "null"], "description": "% 숫자만 (79.72)"},
                    "note": {"type": "string", "description": "금액/수량/시간 기준, 누적 여부, 산출기준·각주 요지, (*1) 같은 주석 내용"},
                    "basis": {"type": "string", "enum": ["quantity", "amount", "hours", "other"],
                              "description": "능력·실적이 수량(척·대·톤·GT) / 금액(백만원·억원) / 시간(M/H) 중 무엇 기준인가"},
                    "cumulative": {"type": ["boolean", "null"], "description": "분기·반기 열이 연초 누적이면 true, 해당 분기만이면 false, 모르면 null"},
                    "capacity_unit": {"type": "string", "description": "능력 단위(unit 과 같으면 같은 값)"},
                    "production_unit": {"type": "string", "description": "실적 단위(능력과 다르면 — 예: 능력 천GT·실적 백만원)"},
                    "confidence": {"type": "string", "enum": ["high", "low"]},
                },
            },
        },
        "review": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["table", "reason"],
                "properties": {"table": {"type": "integer"}, "reason": {"type": "string"}},
            },
        },
    },
}

SYSTEM = """당신은 한국 상장사 정기보고서(DART)의 '생산능력 / 생산실적 / 가동률' 표를 공통 스키마로 옮기는 데이터 정리 담당자다.
규칙:
1. 단위를 바꾸지 마라. 표에 적힌 단위 그대로 적는다(척, CGT, 톤, 대, 백만원, 억원, 천GT, 천BHP, 천M/H …). 셀 안에 단위가 섞여 있으면(예 '12,467천 GT') 숫자 12467 과 단위 '천 GT' 로 나눈다.
2. period 는 데이터 열의 기간이다. 사업보고서 표에 2025년·2024년·2023년 세 열이 있으면 세 행을 만든다. 기말 YYYY-MM 으로: '2025년'→2025-12, '2024년 3분기'→2024-09, '2024년 반기'→2024-06, '2025년 1분기'→2025-03.
   '제N기' 는 사업연도 번호다. 이 보고서의 보고 기간(아래 period)이 당기이며 그 기수는 아래 fiscal_hint 를 따른다. 한 기 앞은 한 해 전.
3. 분기·반기보고서의 당기 열은 보통 연초부터의 누적이다. 표나 각주에 명시가 있으면 그대로, 없으면 cumulative=null.
4. 능력·실적·가동률이 서로 다른 표에 있으면 같은 (segment, product, period) 로 합쳐 한 행에 넣어라. 단위가 다르면 capacity_unit / production_unit 에 각각 적고 basis 는 능력 기준으로.
5. 모르는 값은 null. 추정·계산으로 채우지 마라(가동률이 비어 있어도 능력÷실적으로 만들지 않는다). '-' 는 null.
6. 합계 행(계·합계·소계)도 segment='합계'(또는 '<부문> 계') 로 남긴다. 회사 이름이 행에 있으면(연결 자회사별) product 에 넣는다.
7. 능력이 금액 기준(백만원 등)이면 basis='amount' 로 적고 note 에 '금액 기준' 을 쓴다. 가동률 산식·산출기준·(*1) 주석은 note 에 요약한다.
8. 생산능력·실적·가동률과 무관한 표(투자 계획, 사업장 주소, 원재료 매입)는 행을 만들지 말고 review 에 표 번호와 이유를 적어라. 숫자를 읽을 수 없거나 구조가 모호한 표도 review 로.
9. 숫자는 쉼표를 뺀 숫자형으로. 가동률 '79.72%'→79.72. 음수·괄호는 그대로 음수로."""


def _client():
    try:
        import anthropic
    except ImportError:
        sys.exit("anthropic 패키지가 없습니다: pip install anthropic")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY 환경변수가 없습니다.")
    return anthropic.Anthropic()


def fiscal_hint(meta: dict, tables: list[dict]) -> str:
    """'제12기' 같은 기수 표기가 있을 때 당기 기수를 알려 준다(표 머리글에서 가장 큰 기수 = 당기)."""
    import re
    nums = []
    for t in tables:
        for row in t["rows"][:2]:
            for c in row:
                m = re.match(r"제\s*(\d+)\s*기", c)
                if m:
                    nums.append(int(m.group(1)))
    if not nums:
        return "기수 표기 없음"
    return f"당기 = 제{max(nums)}기 = 보고 기간 {meta.get('period')} 이 속한 사업연도"


def build_prompt(meta: dict, tables: list[dict]) -> str:
    parts = [
        "## 보고서",
        f"- 회사: {meta['company']} ({meta['stock_code']}), 섹터: {meta.get('sector','')}",
        f"- 보고서: {meta['report_nm']} / report_type={meta.get('report_type')} / period={meta.get('period')} (보고 기간 기말)",
        f"- 접수번호: {meta['rcept_no']} / fiscal_hint: {fiscal_hint(meta, tables)}",
        "",
        "## 표",
    ]
    for i, t in enumerate(tables, 1):
        parts.append(f"### 표 {i}  [{' › '.join(t.get('section', []))}]")
        if t.get("headings"):
            parts.append("제목 줄: " + " | ".join(t["headings"][-3:]))
        if t.get("unit"):
            parts.append("단위 문구: " + t["unit"])
        for f in t.get("footnotes", []):
            parts.append("각주: " + f[:400])
        parts.append("```html")
        parts.append(t["html"])
        parts.append("```")
        parts.append("")
    return "\n".join(parts)


def call_model(client, meta: dict, tables: list[dict]) -> dict:
    import anthropic
    prompt = build_prompt(meta, tables)
    for attempt in range(1, 4):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=16000,
                system=SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            )
            break
        except anthropic.RateLimitError:
            wait = 20 * attempt
            print(f"  ! 429 — {wait}s 대기 후 재시도({attempt}/3)")
            time.sleep(wait)
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500 and attempt < 3:
                time.sleep(5 * attempt)
                continue
            raise
    else:
        raise RuntimeError("모델 호출 3회 실패")
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"모델이 응답을 거부했습니다: {getattr(resp, 'stop_details', None)}")
    text = next(b.text for b in resp.content if b.type == "text")
    out = json.loads(text)
    out["_usage"] = {"in": resp.usage.input_tokens, "out": resp.usage.output_tokens, "model": resp.model}
    return out


# ───────────────────── 후처리(모델 없이 테스트 가능) ─────────────────────
def finalize(meta: dict, result: dict) -> tuple[list[dict], list[dict]]:
    """모델 출력 → (저장할 행, 검토 행). 행에 보고서 메타를 붙이고 중복·빈 행을 거른다."""
    rows_out: list[dict] = []
    review: list[dict] = [{"rcept_no": meta["rcept_no"], "company": meta["company"], "table": r.get("table"),
                           "reason": r.get("reason", "")} for r in result.get("review", [])]
    seen: set[tuple] = set()
    for r in result.get("rows", []):
        if r.get("capacity") is None and r.get("production") is None and r.get("utilization_pct") is None:
            continue                                                  # 숫자가 하나도 없으면 행이 아니다
        if r.get("confidence") == "low":
            review.append({"rcept_no": meta["rcept_no"], "company": meta["company"], "table": None,
                           "reason": f"confidence=low: {r.get('segment')}/{r.get('product')} {r.get('period')} — {r.get('note','')[:80]}"})
            continue
        if not _valid_period(r.get("period", "")):
            review.append({"rcept_no": meta["rcept_no"], "company": meta["company"], "table": None,
                           "reason": f"period 형식 오류 '{r.get('period')}' ({r.get('period_label')})"})
            continue
        key = (r["period"], r.get("segment", ""), r.get("product", ""), r.get("unit", ""))
        if key in seen:
            continue                                                  # 같은 표가 개요·본문에 두 번 실린 경우
        seen.add(key)
        rows_out.append({
            "company": meta["company"], "stock_code": meta["stock_code"], "sector": meta.get("sector", ""),
            "period": r["period"], "period_label": r.get("period_label", ""),
            "report_type": meta.get("report_type", ""), "report_label": meta.get("report_nm", ""),
            "report_period": meta.get("period", ""), "rcept_dt": meta.get("rcept_dt", ""),
            "segment": r.get("segment", ""), "product": r.get("product", ""),
            "unit": r.get("unit", ""), "capacity_unit": r.get("capacity_unit") or r.get("unit", ""),
            "production_unit": r.get("production_unit") or r.get("unit", ""),
            "capacity": r.get("capacity"), "production": r.get("production"), "utilization_pct": r.get("utilization_pct"),
            "basis": r.get("basis", "other"), "cumulative": r.get("cumulative"),
            "source_rcept_no": meta["rcept_no"], "dart_url": DART_VIEWER.format(rcept_no=meta["rcept_no"]),
            "note": r.get("note", ""),
        })
    return rows_out, review


def _valid_period(p: str) -> bool:
    import re
    return bool(re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", p or ""))


def write_review(entries: list[dict]) -> None:
    """review.csv 는 (rcept_no, table, reason) 기준으로 중복 없이 누적."""
    existing: list[dict] = []
    if REVIEW_CSV.exists():
        with REVIEW_CSV.open(encoding="utf-8", newline="") as fh:
            existing = list(csv.DictReader(fh))
    keys = {(e["rcept_no"], str(e.get("table") or ""), e["reason"]) for e in existing}
    for e in entries:
        k = (e["rcept_no"], str(e.get("table") or ""), e["reason"])
        if k not in keys:
            existing.append({"rcept_no": e["rcept_no"], "company": e["company"], "table": e.get("table") or "",
                             "reason": e["reason"], "dart_url": DART_VIEWER.format(rcept_no=e["rcept_no"])})
            keys.add(k)
    with REVIEW_CSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["rcept_no", "company", "table", "reason", "dart_url"])
        w.writeheader()
        w.writerows(existing)


def rebuild_all() -> dict:
    rows: list[dict] = []
    reports = 0
    for f in sorted(NORMALIZED.glob("*.json")):
        if f.name == "all.json":
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        rows.extend(d.get("rows", []))
        reports += 1
    payload = {"generated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST"),
               "report_count": reports, "rows": rows}
    NORMALIZED.mkdir(parents=True, exist_ok=True)
    (NORMALIZED / "all.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return payload


def load_processed() -> dict:
    return json.loads(PROCESSED.read_text(encoding="utf-8")) if PROCESSED.exists() else {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", default="")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--rebuild", action="store_true", help="모델 호출 없이 all.json 만 다시")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    if args.rebuild:
        p = rebuild_all()
        print(f"all.json 재생성: 보고서 {p['report_count']}건, 행 {len(p['rows'])}개")
        return 0

    want = {c.strip() for c in args.codes.split(",") if c.strip()}
    processed = load_processed()
    files = sorted(EXTRACTED.glob("*.json"))
    todo = []
    for f in files:
        code, rcept = f.stem.split("_", 1)
        if want and code not in want:
            continue
        if rcept in processed and not args.force:
            continue
        todo.append(f)
    if args.limit:
        todo = todo[: args.limit]
    print(f"정규화 대상 {len(todo)}건 (전체 {len(files)}, 처리됨 {len(processed)})")
    if not todo:
        rebuild_all()
        return 0

    client = _client()
    NORMALIZED.mkdir(parents=True, exist_ok=True)
    review_all: list[dict] = []
    total_in = total_out = 0
    for f in todo:
        d = json.loads(f.read_text(encoding="utf-8"))
        meta, tables = d["meta"], d["tables"]
        small = [t for t in tables if len(t["rows"]) <= MAX_TABLE_ROWS]
        for i, t in enumerate(tables, 1):
            if len(t["rows"]) > MAX_TABLE_ROWS:
                review_all.append({"rcept_no": meta["rcept_no"], "company": meta["company"], "table": i,
                                   "reason": f"표가 너무 큼({len(t['rows'])}행) — 모델에 넘기지 않음"})
        if not small:
            review_all.append({"rcept_no": meta["rcept_no"], "company": meta["company"], "table": None,
                               "reason": "채택된 표 없음"})
            processed[meta["rcept_no"]] = {"at": dt.datetime.now().isoformat(timespec="seconds"), "rows": 0}
            continue
        try:
            result = call_model(client, meta, small)
        except Exception as exc:  # noqa: BLE001 — 한 보고서 실패가 전체를 막지 않게
            print(f"  ✗ {meta['company']} {meta['report_nm']} {meta['rcept_no']}: {exc}")
            review_all.append({"rcept_no": meta["rcept_no"], "company": meta["company"], "table": None, "reason": f"모델 호출 실패: {exc}"[:200]})
            continue
        rows, review = finalize(meta, result)
        review_all.extend(review)
        usage = result.get("_usage", {})
        total_in += usage.get("in", 0); total_out += usage.get("out", 0)
        (NORMALIZED / f.name).write_text(json.dumps({"meta": meta, "rows": rows, "model": usage.get("model", MODEL),
                                                     "normalized_at": dt.datetime.now().isoformat(timespec="seconds")},
                                                    ensure_ascii=False, indent=1), encoding="utf-8")
        processed[meta["rcept_no"]] = {"at": dt.datetime.now().isoformat(timespec="seconds"), "rows": len(rows), "model": usage.get("model", MODEL)}
        print(f"  ✓ {meta['company']} {meta['report_nm']} {meta['rcept_no']}: 행 {len(rows)}, 검토 {len(review)} (토큰 {usage.get('in',0)}/{usage.get('out',0)})")
        PROCESSED.write_text(json.dumps(processed, ensure_ascii=False, indent=1), encoding="utf-8")
    if review_all:
        write_review(review_all)
    p = rebuild_all()
    print(f"\nall.json: 보고서 {p['report_count']}건, 행 {len(p['rows'])}개 · 검토 {len(review_all)}건 · 토큰 in {total_in} / out {total_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
