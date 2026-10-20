"""topics.py — 원재료·가격 주제 후처리 검산(모델 호출 없음)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import topics as T  # noqa: E402

META = {"company": "HD현대중공업", "stock_code": "329180", "sector": "조선", "rcept_no": "20260320000859",
        "report_nm": "사업보고서 (2025.12)", "report_type": "annual", "period": "2025-12", "rcept_dt": "20260320"}


def test_material_rows():
    res = {"rows": [
        {"period": "", "period_label": "당기", "segment": "조 선", "entity": "HD현대중공업㈜", "purchase_type": "원재료",
         "item": "기 자 재", "amount": 3044288, "unit": "백만원", "share_pct": 50.2, "suppliers": "㈜포스코, 현대제철㈜ 外", "note": "", "confidence": "high"},
        {"period": "2025-12", "period_label": "당기", "segment": "합계", "entity": "", "purchase_type": "", "item": "",
         "amount": None, "unit": "", "share_pct": None, "suppliers": "", "note": "", "confidence": "high"},          # 값 없음 → 버림
        {"period": "2025-12", "period_label": "당기", "segment": "해양", "entity": "", "purchase_type": "", "item": "의장재",
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




def test_none_fields_do_not_break_keys():
    """모델이 spec·segment 를 null 로 주면 정렬 키에 None 이 섞여 rebuild 가 터졌다(실측)."""
    from topics import dedupe_latest, finalize_topic
    meta = {"rcept_no": "20250101000001", "company": "A", "stock_code": "000001", "sector": "조선",
            "period": "2024-12", "report_type": "annual", "report_nm": "사업보고서", "rcept_dt": "20250101"}
    res = {"rows": [
        {"segment": None, "product": "선박", "spec": None, "unit": "원", "price": 1.0, "period": "2024-12"},
        {"segment": "조선", "product": None, "spec": "A", "unit": "원", "price": 2.0, "period": "2023-12"},
    ], "review": []}
    rows, review = finalize_topic("product_price", meta, res)
    assert len(rows) == 2 and rows[0]["segment"] == "" and rows[0]["spec"] == ""
    raw = [{"stock_code": "000001", "sector": None, "company": "A", "segment": None, "product": "선박",
            "spec": None, "period": "2024-12", "source_rcept_no": "1", "price": 1},
           {"stock_code": "000001", "sector": "조선", "company": "A", "segment": None, "product": "선박",
            "spec": None, "period": "2024-12", "source_rcept_no": "2", "price": 9}]
    out = dedupe_latest(raw, "product_price")
    assert [r["price"] for r in out] == [9]                 # None 키끼리 같은 줄로 묶여 최신 접수만 남는다
    assert dedupe_latest(raw + rows, "product_price")       # 섞여도 정렬이 터지지 않는다


def test_migrate_old_material_rows():
    from topics import migrate_row
    old = {"company": "HD현대중공업㈜", "stock_code": "329180", "segment": "조선", "item": "강재", "spec": None, "amount": 1}
    r = migrate_row(old, "material", "HD현대중공업")
    assert r["entity"] == "HD현대중공업㈜" and r["company"] == "HD현대중공업" and r["spec"] == ""
    new = {"company": "HD현대중공업", "entity": "", "stock_code": "329180", "segment": "Compact Equipment"}
    assert migrate_row(new, "material", "X")["company"] == "HD현대중공업"      # 이미 새 모양이면 손대지 않는다
    assert migrate_row({"product": "CompactEquipment"}, "product_price")["product"] == "Compact Equipment"




def test_canonicalize_entity_spelling():
    from topics import dedupe_latest
    raw = [{"stock_code": "329180", "company": "HD현대중공업", "segment": "엔진기계", "entity": "HD현대중공업㈜HD현대엔진(유)",
            "item": "기타", "purchase_type": "원재료", "period": "2024-12", "source_rcept_no": "20250301", "amount": 1},
           {"stock_code": "329180", "company": "HD현대중공업", "segment": "엔진기계", "entity": "HD현대중공업㈜, HD현대엔진(유)",
            "item": "기타", "purchase_type": "원재료", "period": "2025-12", "source_rcept_no": "20260320", "amount": 2}]
    out = dedupe_latest(raw, "material")
    assert len(out) == 2 and {r["entity"] for r in out} == {"HD현대중공업㈜, HD현대엔진(유)"}   # 최신 표기로 통일 → 대시보드 한 줄



def test_subtotal_and_entity_merge():
    from topics import _fix_subtotal, dedupe_latest
    r = {"segment": "엔진기계", "purchase_type": "소계", "item": ""}; _fix_subtotal(r)
    assert (r["segment"], r["purchase_type"], r["item"]) == ("엔진기계", "", "소계")
    r = {"segment": "합계", "purchase_type": "", "item": ""}; _fix_subtotal(r)
    assert (r["segment"], r["item"]) == ("합계", "합계")
    r = {"segment": "소계", "purchase_type": "", "item": "소계"}; _fix_subtotal(r)
    assert (r["segment"], r["item"]) == ("", "소계")
    raw = [{"stock_code": "1", "company": "A", "segment": "조선", "entity": "", "item": "강재", "purchase_type": "원재료",
            "period": "2025-03", "source_rcept_no": "20250515", "amount": 1},
           {"stock_code": "1", "company": "A", "segment": "조선", "entity": "A㈜", "item": "강재", "purchase_type": "원재료",
            "period": "2024-12", "source_rcept_no": "20250320", "amount": 2}]
    out = dedupe_latest(raw, "material")
    assert {r["entity"] for r in out} == {"A㈜"}            # 분기(법인 열 없음)가 사업보고서의 법인 줄로 합쳐진다
    raw.append({"stock_code": "1", "company": "A", "segment": "조선", "entity": "B㈜", "item": "강재", "purchase_type": "원재료",
                "period": "2024-12", "source_rcept_no": "20250320", "amount": 3})
    assert {r["entity"] for r in dedupe_latest(raw, "material")} == {"", "A㈜", "B㈜"}   # 법인이 둘이면 빈 쪽은 못 정한다



def test_disjoint_period_variants_merge():
    from topics import dedupe_latest
    base = {"stock_code": "1", "company": "A", "segment": "엔진기계", "item": "엔진부품등", "amount": 1}
    raw = [{**base, "entity": "A㈜", "purchase_type": "", "period": "2023-12", "source_rcept_no": "20240301"},
           {**base, "entity": "A㈜,B(유)", "purchase_type": "원재료", "period": "2025-12", "source_rcept_no": "20260301"}]
    out = dedupe_latest(raw, "material")
    assert {(r["entity"], r["purchase_type"]) for r in out} == {("A㈜,B(유)", "원재료")}   # 기간이 안 겹치면 최신 표기로 한 줄
    raw.append({**base, "entity": "C㈜", "purchase_type": "원재료", "period": "2025-12", "source_rcept_no": "20260301"})
    assert len({r["entity"] for r in dedupe_latest(raw, "material")}) == 3           # 같은 기간에 둘이면 다른 줄 — 2023 의 A㈜ 는 어느 쪽인지 모르니 그대로

if __name__ == "__main__":
    test_material_rows()
    test_price_rows_and_dedupe()
    test_product_price_spec()
    test_none_fields_do_not_break_keys()
    test_migrate_old_material_rows()
    test_canonicalize_entity_spelling()
    test_subtotal_and_entity_merge()
    test_disjoint_period_variants_merge()
    print("ok — test_topics 8개 통과")
