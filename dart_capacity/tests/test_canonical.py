"""canonical.py — 줄 이름 통일·병합 검산 (10/20 실측 사례)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from canonical import canonicalize, line_key, _same_line  # noqa: E402


def row(rc, period, seg, prod, cap=None, cu="", prod_v=None, pu="", ut=None, note=""):
    return {"stock_code": "329180", "company": "HD현대중공업", "sector": "조선", "source_rcept_no": rc, "period": period,
            "segment": seg, "product": prod, "capacity": cap, "capacity_unit": cu, "production": prod_v,
            "production_unit": pu, "utilization_pct": ut, "unit": cu or pu, "note": note}


def test_spacing_and_company_suffix_merge():
    rows = [
        row("2026", "2025-12", "조선", "선박 (HD현대중공업㈜)", cap=12467, cu="천 GT", ut=100.4),
        row("2026", "2025-12", "조선", "선박 (HD현대중공업㈜ 外)", prod_v=12463099, pu="백만원"),
        row("2025", "2024-12", "조 선", "선 박", cap=10000, cu="천GT"),
        row("2025", "2024-12", "엔 진 기 계", "선박엔진 (HD현대중공업㈜)", cap=16000, cu="천 BHP"),
        row("2026", "2025-12", "엔진기계", "선박엔진 (HD현대중공업㈜)", cap=16000, cu="천 BHP"),
        row("2026", "2025-12", "엔진기계", "선박엔진 (HD현대엔진(유))", cap=982, cu="천 BHP"),
    ]
    out = canonicalize(rows)
    lines = sorted({(r["segment"], r["product"]) for r in out})
    # 선박 3가지 표기 → 한 줄(최신 이름), 엔진기계 두 사업소는 괄호 회사가 달라 따로
    assert lines == [("엔진기계", "선박엔진 (HD현대엔진(유))"), ("엔진기계", "선박엔진 (HD현대중공업㈜)"),
                     ("조선", "선박 (HD현대중공업㈜)")], lines
    ship = {r["period"]: r for r in out if r["product"] == "선박 (HD현대중공업㈜)"}
    # 같은 기간의 능력(천GT)·실적(백만원) 행이 한 행으로, 단위는 각각
    assert ship["2025-12"]["capacity"] == 12467 and ship["2025-12"]["production"] == 12463099
    assert ship["2025-12"]["capacity_unit"] == "천 GT" and ship["2025-12"]["production_unit"] == "백만원"
    assert ship["2025-12"]["utilization_pct"] == 100.4 and sorted(ship["2025-12"]["sources"]) == ["2026"]
    assert ship["2024-12"]["capacity"] == 10000


def test_latest_report_wins_and_fills_gaps():
    rows = [
        row("2025", "2024-12", "조선", "선박", cap=10000, cu="천GT", ut=95.0),
        row("2026", "2024-12", "조선", "선박", cap=10000, cu="천GT"),        # 최신 보고서엔 가동률이 없음 → 옛 값으로 채움
    ]
    out = canonicalize(rows)
    assert len(out) == 1 and out[0]["utilization_pct"] == 95.0 and out[0]["sources"] == ["2026", "2025"]


def test_company_outside_parentheses_and_renames():
    from canonical import display
    k1 = line_key({"segment": "방산", "product": "한화에어로스페이스㈜: 자주포, 장갑차, 발사대, 탄약/유도무기류 및 항법장치 등"})
    k2 = line_key({"segment": "방산", "product": "자주포, 장갑차, 발사대, 탄약ㆍ유도무기류 및 항법장치 등"})
    assert k1[1] == k2[1] == "자주포,장갑차,발사대,탄약,유도무기류및항법장치" and k1[2].startswith("한화에어로스페이스")
    assert _same_line(k1, k2)
    k3 = line_key({"segment": "산업용장비", "product": "한화세미텍㈜(구.한화정밀기계㈜) 및 해외생산법인 (칩마운터, 공작기계 등)"})
    k4 = line_key({"segment": "산업용장비", "product": "한화정밀기계㈜ 및 해외생산법인 / 칩마운터, 공작기계 등"})
    assert k3[1] == k4[1] == "칩마운터,공작기계" and _same_line(k3, k4)      # 사명 변경 전후 — ㈜ 토큰 공유
    assert display("엔 진 기 계") == "엔진기계" and display("합    계") == "합계"
    assert display("엔진류, 기계설비 등 (HD현대엔진(유))") == "엔진류, 기계설비 등 (HD현대엔진(유))"
    assert display("상선 조립 및 건조 등") == "상선 조립 및 건조 등"
    assert display("MaterialHandling (국내)") == "Material Handling (국내)"
    k5 = line_key({"segment": "시큐리티", "product": "한화비전㈜(舊. 한화테크윈㈜) 및해외생산법인 / 감시장비 등"})
    k6 = line_key({"segment": "시큐리티", "product": "한화비전㈜ 및 해외생산법인 (감시장비 등)"})
    assert k5[1] == k6[1] == "감시장비" and _same_line(k5, k6)


def test_keys():
    assert line_key({"segment": "엔 진 기 계", "product": "선박엔진 등 (HD현대중공업㈜)"}) == ("엔진기계", "선박엔진", "HD현대중공업㈜")
    assert _same_line(("방산", "자주포,장갑차,발사대,탄약,유도무기류및항법장치", ""), ("방산", "자주포,장갑차,발사대,탄약", ""))
    assert not _same_line(("조선", "선박", ""), ("해양플랜트", "해상구조물", ""))


if __name__ == "__main__":
    test_spacing_and_company_suffix_merge()
    test_latest_report_wins_and_fills_gaps()
    test_keys()
    test_company_outside_parentheses_and_renames()
    print("ok — test_canonical 4개 통과")
