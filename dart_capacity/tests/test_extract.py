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
    assert whys == {"지역", "투자명"}, whys
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
