"""normalize.py 후처리 검산 — 모델 호출 없이(가짜 모델 출력)."""
import csv
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import normalize as N  # noqa: E402

META = {"company": "HD현대중공업", "stock_code": "329180", "sector": "조선", "rcept_no": "20260320000859",
        "report_nm": "사업보고서 (2025.12)", "report_type": "annual", "period": "2025-12", "rcept_dt": "20260320"}


def fake_result():
    row = lambda **kw: {"period": "2025-12", "period_label": "2025년", "segment": "조선", "product": "선박", "unit": "천GT",
                        "capacity": 12467, "production": 12463099, "utilization_pct": 100.4, "note": "능력 천GT·실적 백만원",
                        "basis": "quantity", "cumulative": False, "capacity_unit": "천GT", "production_unit": "백만원",
                        "confidence": "high", **kw}
    return {"rows": [
        row(),
        row(),                                                   # 개요·본문 중복 → 한 번만
        row(period="2024-12", period_label="2024년", capacity=10000),
        row(segment="해양플랜트", product="해양플랜트설비", capacity=None, production=None, utilization_pct=None),  # 숫자 없음 → 버림
        row(segment="엔진기계", confidence="low"),                # → 검토
        row(segment="블록", period="2025년"),                      # period 형식 오류 → 검토
    ], "review": [{"table": 7, "reason": "투자 계획 표"}]}


def test_finalize():
    rows, review = N.finalize(META, fake_result())
    assert [(r["segment"], r["period"]) for r in rows] == [("조선", "2025-12"), ("조선", "2024-12")]
    r0 = rows[0]
    assert r0["source_rcept_no"] == "20260320000859" and r0["dart_url"].endswith("20260320000859")
    assert r0["capacity_unit"] == "천GT" and r0["production_unit"] == "백만원"
    assert r0["company"] == "HD현대중공업" and r0["sector"] == "조선" and r0["report_label"] == "사업보고서 (2025.12)"
    reasons = [x["reason"] for x in review]
    assert reasons[0] == "투자 계획 표" and review[0]["table"] == 7
    assert any(s.startswith("confidence=low") for s in reasons)
    assert any("period 형식 오류" in s for s in reasons)
    assert len(review) == 3


def test_review_csv_and_all_json(tmp: Path):
    N.REVIEW_CSV = tmp / "review.csv"
    N.NORMALIZED = tmp / "normalized"
    N.NORMALIZED.mkdir()
    N.write_review([{"rcept_no": "1", "company": "A", "table": 2, "reason": "x"}])
    N.write_review([{"rcept_no": "1", "company": "A", "table": 2, "reason": "x"},
                    {"rcept_no": "1", "company": "A", "table": None, "reason": "y"}])
    with N.REVIEW_CSV.open(encoding="utf-8") as fh:
        got = list(csv.DictReader(fh))
    assert [(g["table"], g["reason"]) for g in got] == [("2", "x"), ("", "y")]       # 중복 없이 누적
    rows, _ = N.finalize(META, fake_result())
    (N.NORMALIZED / "329180_20260320000859.json").write_text(json.dumps({"meta": META, "rows": rows}), encoding="utf-8")
    p = N.rebuild_all()
    assert p["report_count"] == 1 and len(p["rows"]) == 2 and (N.NORMALIZED / "all.json").exists()


def test_prompt_has_fiscal_hint_and_html():
    tables = [{"section": ["3. 원재료 및 생산설비"], "headings": ["(1) 생산능력"], "unit": "(단위: 대)",
               "footnotes": ["주1) OEM 포함"], "rows": [["제품군", "사업소", "제12기", "제11기"]], "html": "<table><tr><td>x</td></tr></table>"}]
    meta = {**META, "company": "두산밥캣", "stock_code": "241560"}
    assert "당기 = 제12기" in N.fiscal_hint(meta, tables)
    p = N.build_prompt(meta, tables)
    assert "<table>" in p and "단위 문구: (단위: 대)" in p and "각주: 주1) OEM 포함" in p
    assert N.fiscal_hint(META, [{"rows": [["사업부문", "2025년"]]}]) == "기수 표기 없음"


if __name__ == "__main__":
    test_finalize()
    with tempfile.TemporaryDirectory() as d:
        test_review_csv_and_all_json(Path(d))
    test_prompt_has_fiscal_hint_and_html()
    print("ok — test_normalize 3개 통과")
