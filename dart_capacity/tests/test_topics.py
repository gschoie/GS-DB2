"""topics.py — 원재료·가격 주제 후처리 검산(모델 호출 없음)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import topics as T  # noqa: E402

META = {"company": "HD현대중공업", "stock_code": "329180", "sector": "조선", "rcept_no": "20260320000859",
        "report_nm": "사업보고서 (2025.12)", "report_type": "annual", "period": "2025-12", "rcept_dt": "20260320"}


def test_material_rows():
    res = {"rows": [
        {"period": "", "period_label": "당기", "segment": "조 선", "company": "HD현대중공업㈜", "purchase_type": "원재료",
         "item": "기 자 재", "amount": 3044288, "unit": "백만원", "share_pct": 50.2, "suppliers": "㈜포스코, 현대제철㈜ 外", "note": "", "confidence": "high"},
        {"period": "2025-12", "period_label": "당기", "segment": "합계", "company": "", "purchase_type": "", "item": "",
         "amount": None, "unit": "", "share_pct": None, "suppliers": "", "note": "", "confidence": "high"},          # 값 없음 → 버림
        {"period": "2025-12", "period_label": "당기", "segment": "해양", "company": "", "purchase_type": "", "item": "의장재",
         "amount": 10, "unit": "백만원", "share_pct": None, "suppliers": "", "note": "", "confidence": "low"},        # → 검토
    ], "review": [{"table": 2, "reason": "매출 표"}]}
    rows, review = T.finalize_topic("material", META, res)
    assert len(rows) == 1 and rows[0]["period"] == "2025-12"            # 기간 없는 당기 표는 보고서 기간
    assert rows[0]["segment"] == "조선" and rows[0]["item"] == "기자재"   # 한글 사이 공백 제거
    assert rows[0]["topic"] == "material" and rows[0]["dart_url"].endswith("20260320000859")
    assert [x["reason"] for x in review] == ["[material] 매출 표", "[material] confidence=low: 해양/의장재 2025-12"]


def test_price_rows_and_dedupe():
    res = {"rows": [
        {"period": "2025-12", "period_label": "2025년", "segment": "조선", "item": "STEEL PLATE", "unit": "원/TON", "price": 914000, "note": "", "confidence": "high"},
        {"period": "2024-12", "period_label": "2024년", "segment": "조선", "item": "STEEL PLATE", "unit": "원/TON", "price": 958500, "note": "", "confidence": "high"},
    ], "review": []}
    rows, _ = T.finalize_topic("material_price", META, res)
    older = {**rows[1], "price": 999, "source_rcept_no": "20250318000897"}      # 옛 보고서의 2024년 값
    merged = T.dedupe_latest(rows + [older], "material_price")
    assert [(r["period"], r["price"]) for r in merged] == [("2024-12", 958500), ("2025-12", 914000)]   # 최신 보고서 우선


def test_product_price_spec():
    res = {"rows": [{"period": "2025-12", "period_label": "2025년", "segment": "조선", "product": "CRUDE OIL TANKER", "spec": "320,000 DWT",
                     "unit": "백만$", "price": 128.0, "note": "", "confidence": "high"}], "review": []}
    rows, _ = T.finalize_topic("product_price", META, res)
    assert rows[0]["spec"] == "320,000 DWT" and rows[0]["unit"] == "백만$" and rows[0]["price"] == 128.0


if __name__ == "__main__":
    test_material_rows()
    test_price_rows_and_dedupe()
    test_product_price_spec()
    print("ok — test_topics 3개 통과")
