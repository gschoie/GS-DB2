"""extract.py 표 선정 규칙 검산 — 가짜 DART XML (컨테이너는 OpenDART 차단).
한화에어로스페이스 2023 사업보고서 실측 구조를 본떴다(단위 표·각주 표·투자현황 표·사업장 표)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extract import extract_tables  # noqa: E402

DOC = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY>
<SECTION-1><TITLE ATOC="Y">II. 사업의 내용</TITLE>
<SECTION-2><TITLE ATOC="Y">3. 원재료 및 생산설비</TITLE>
<P>가. 주요 원재료</P>
<TABLE><TR><TH>품목</TH><TH>금액</TH></TR><TR><TD>후판</TD><TD>1,000</TD></TR></TABLE>
<P>나. 생산능력, 생산실적 및 가동률</P>
<TABLE><TR><TD></TD><TD>(단위 : 백만원)</TD></TR></TABLE>
<TABLE ACLASS="NORMAL"><TR><TH>사업부문</TH><TH>구 분</TH><TH>2023년</TH><TH>2022년</TH></TR>
<TR><TD ROWSPAN="3"><P>항공</P></TD><TD>생산능력</TD><TD>2,159,431</TD><TD>1,689,112</TD></TR>
<TR><TD>생산실적</TD><TD>1,721,548</TD><TD>1,290,113</TD></TR>
<TR><TD>가동률(%)</TD><TD>79.72</TD><TD>76.38</TD></TR></TABLE>
<TABLE><TR><TD>※ 항공 및 방산사업은 보안 관계상 수량 대신 금액으로 기재</TD></TR></TABLE>
<P>[한화에어로스페이스㈜ 방산부문] "시간당 생산실적×일일 가동가능시간×연간가동가능일수"로 정상가동률 기준으로 계산된 최대 생산가능금액입니다.</P>
<P>다. 생산설비의 현황 등</P>
<P>(1) 주요 사업장 현황</P>
<TABLE><TR><TH>지역</TH><TH>사업장</TH><TH>소재지</TH></TR><TR><TD>국내</TD><TD>창원1사업장</TD><TD>경남 창원시</TD></TR></TABLE>
<P>(2) 설비의 신설·매입 계획</P>
<TABLE><TR><TH>투자명</TH><TH>기간</TH><TH>총 소요자금</TH><TH>향후 기대효과</TH></TR>
<TR><TD>PW 엔진부품 제조설비 투자</TD><TD>2019~2024</TD><TD>25,360</TD><TD>생산능력 향상</TD></TR></TABLE>
</SECTION-2></SECTION-1>
<SECTION-1><TITLE>III. 재무에 관한 사항</TITLE>
<TABLE><TR><TD>매출액</TD><TD>100</TD></TR></TABLE>
</SECTION-1>
</BODY></DOCUMENT>"""


def test_picks_only_the_capacity_table():
    found, rejected = extract_tables(DOC)
    assert len(found) == 1, [t["headings"] for t in found]
    t = found[0]
    assert t["keyword_in"] == "table" and t["keywords"] == ["가동률", "생산능력", "생산실적"]
    assert t["section"][-1] == "3. 원재료 및 생산설비"
    assert t["headings"][-1] == "나. 생산능력, 생산실적 및 가동률"
    # 단위만 든 한 칸짜리 표는 표로 세지 않고 다음 표의 단위가 된다
    assert t["unit"] == "(단위 : 백만원)"
    # '※ …' 한 칸짜리 표는 직전 표의 각주
    assert t["footnotes"] == ["※ 항공 및 방산사업은 보안 관계상 수량 대신 금액으로 기재"]
    assert t["rows"][1] == ["항공", "생산능력", "2,159,431", "1,689,112"]
    # 앞 표(원재료) 제목은 문맥에 섞이지 않는다
    assert all("원재료" not in h for h in t["headings"])


def test_false_positives_go_to_rejected():
    found, rejected = extract_tables(DOC)
    # 사업장 현황 표: 멀리 있는 각주 문장('…입니다.')의 가동률은 제목이 아니다
    # 투자현황 표: '생산능력 향상'은 지표명 셀이 아니다
    whys = {r["rows"][0][0] for r in rejected}
    assert whys == {"지역", "투자명", "품목"}, whys      # 품목=원재료 표(제목 '가. 주요 원재료'는 매입·현황 낱말이 없어 탈락 후보)
    assert all(r["html"] == "" for r in rejected)           # 검토용이라 원문은 안 담는다
    assert all("토지" not in t["html"] and "투자명" not in t["html"] for t in found)


def test_html_preserved():
    found, _ = extract_tables(DOC)
    assert 'aclass="normal"' in found[0]["html"].lower()
    assert 'rowspan="3"' in found[0]["html"].lower()


if __name__ == "__main__":
    test_picks_only_the_capacity_table()
    test_false_positives_go_to_rejected()
    test_html_preserved()
    print("ok — test_extract 3개 통과")


# ── 10/19 실측 케이스 (두산밥캣·HD현대중공업) ──────────────────────────────
DOC2 = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY>
<SECTION-1><TITLE>II. 사업의 내용</TITLE>
<SECTION-2><TITLE>1. 사업의 개요</TITLE>
<P>다. 주요 원재료 및 생산능력<BR/>(1) 주요 원재료 등의 현황</P>
<TABLE><TR><TD></TD><TD>(단위 : 백만원)</TD></TR></TABLE>
<TABLE><TR><TH>사업부문</TH><TH>품목</TH><TH>매입액</TH></TR><TR><TD>조선</TD><TD>강재</TD><TD>6,067,774</TD></TR></TABLE>
<P>(2) 생산능력</P>
<TABLE><TR><TH>사업부문</TH><TH>품목</TH><TH>2025년</TH></TR><TR><TD>조선</TD><TD>선박</TD><TD>12,467천 GT(*1)</TD></TR></TABLE>
<TABLE><TR><TD>ㆍ선 박</TD><TD>: 도크의 최대 건조가능 용량 기준</TD></TR><TR><TD>ㆍ기 타</TD><TD>: 최대 생산능력 기준</TD></TR></TABLE>
<TABLE><TR><TD>주1) 일부 제품은 외주생산(OEM)입니다.</TD></TR></TABLE>
<P>(2) 생산능력 산출의 근거<BR/>각 공장별 연간 표준작업시간 기준으로 작성되었으며 주공장이 아닌 특수장비는 제외하였습니다.<BR/>라. 생산실적 및 가동률<BR/>(1) 생산실적</P>
<TABLE><TR><TD>(단위: 대)</TD></TR></TABLE>
<TABLE><TR><TH>제품군</TH><TH>사업소</TH><TH>제12기</TH></TR><TR><TD>Compact Equipment</TD><TD>해외</TD><TD>76,500</TD></TR></TABLE>
<P>마. 임직원 현황</P>
<TABLE><TR><TH>구분</TH><TH>인원</TH></TR><TR><TD>생산직</TD><TD>1,000</TD></TR></TABLE>
<TABLE><TR><TD>※ 상기 근속연수는 지원업무 담당 기간입니다.</TD></TR></TABLE>
</SECTION-2></SECTION-1></BODY></DOCUMENT>"""


def test_real_world_cases():
    found, rejected = extract_tables(DOC2)
    firsts = [(t["rows"][0][0], t["topic"]) for t in found]
    # 원재료 표는 상위 항목('다. 주요 원재료 및 생산능력')이 아니라 소항목('(1) 주요 원재료 등의 현황')로 판정
    # → 생산능력이 아니라 **원재료 매입** 주제(머리글 매입액)
    assert firsts == [("사업부문", "material"), ("사업부문", "capacity"), ("제품군", "capacity")], firsts
    mat, cap, prod = found
    assert mat["unit"] == "(단위 : 백만원)"
    assert cap["rows"][1][2] == "12,467천 GT(*1)"
    # 산출기준 2열 표 + 주1) 한 칸 표는 바로 뒤에 왔으니 능력표의 각주로 붙는다
    assert any("도크의 최대 건조가능 용량" in f for f in cap["footnotes"])
    assert any(f.startswith("주1)") for f in cap["footnotes"])
    # 한 요소에 줄바꿈으로 붙어 온 '라. 생산실적 및 가동률 / (1) 생산실적' 을 줄 단위로 읽어 제목으로 잡는다
    assert prod["keyword_in"] == "heading" and prod["keywords"] == ["생산실적"]
    assert prod["unit"] == "(단위: 대)"
    # 임직원 표 뒤의 ※ 각주는 다른 표를 지나왔으므로 생산실적 표에 붙지 않는다
    assert prod["footnotes"] == []


DOC3 = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY>
<SECTION-1><TITLE>II. 사업의 내용</TITLE>
<SECTION-2><TITLE>2. 주요 제품 및 서비스</TITLE>
<P>가. 주요 제품 등의 현황</P>
<TABLE><TR><TH>사업부문</TH><TH>품목</TH><TH>매출액</TH><TH>비중</TH></TR><TR><TD>조선</TD><TD>선박</TD><TD>12,000</TD><TD>70%</TD></TR></TABLE>
<P>나. 주요 제품 등의 가격변동추이</P>
<TABLE><TR><TD>(단위 : 백만달러/척)</TD></TR></TABLE>
<TABLE><TR><TH>품목</TH><TH>2025년</TH><TH>2024년</TH></TR><TR><TD>VLCC</TD><TD>130</TD><TD>128</TD></TR></TABLE>
</SECTION-2>
<SECTION-2><TITLE>3. 원재료 및 생산설비</TITLE>
<P>가. 주요 원재료 등의 현황</P>
<TABLE><TR><TD>(단위 : 백만원)</TD></TR></TABLE>
<TABLE><TR><TH>사업부문</TH><TH>품목</TH><TH>매입액</TH><TH>비중</TH><TH>주요 매입처</TH></TR><TR><TD>조선</TD><TD>후판</TD><TD>6,067,774</TD><TD>62%</TD><TD>포스코</TD></TR></TABLE>
<P>나. 주요 원재료의 가격변동 현황</P>
<P>(1) 가격변동추이</P>
<TABLE><TR><TH>품목</TH><TH>단위</TH><TH>2025년</TH><TH>2024년</TH></TR><TR><TD>후판</TD><TD>천원/톤</TD><TD>950</TD><TD>1,010</TD></TR></TABLE>
<P>(2) 가격변동 원인</P>
<TABLE><TR><TD>※ 후판 가격은 철광석 시세에 연동됩니다.</TD></TR></TABLE>
</SECTION-2></SECTION-1></BODY></DOCUMENT>"""


def test_material_and_price_topics():
    found, rejected = extract_tables(DOC3)
    got = [(t["topic"], t["rows"][1][0], t["unit"]) for t in found]
    assert got == [("product_price", "VLCC", "(단위 : 백만달러/척)"),
                   ("material", "조선", "(단위 : 백만원)"),
                   ("material_price", "후판", "")], got
    # '(1) 가격변동추이'처럼 주어 없는 소항목은 상위 제목 '원재료' 로 가른다 / 매출액 표(제품 현황)는 안 잡는다
    assert all(t["rows"][0][2] != "매출액" for t in found)
    assert found[2]["footnotes"] == ["※ 후판 가격은 철광석 시세에 연동됩니다."]


if __name__ == "__main__":
    test_real_world_cases()
    test_material_and_price_topics()
    print("ok — test_extract 실측 케이스 + 원재료·가격 주제 통과")
