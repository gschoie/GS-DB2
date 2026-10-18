"""extract.py 표 선정 규칙 검산 — 가짜 DART XML (컨테이너는 OpenDART 차단)."""
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
<P>나. 생산 및 설비</P>
<P>(1) 생산능력</P>
<P>(단위 : 척)</P>
<TABLE ACLASS="NORMAL"><TR><TH>사업부문</TH><TH>2024년</TH></TR><TR><TD><P>조선</P></TD><TD>50</TD></TR></TABLE>
<P>(2) 생산실적 및 가동률</P>
<TABLE><TR><TH>구분</TH><TH>실적</TH><TH>가동률</TH></TR><TR><TD>조선</TD><TD>45</TD><TD>90%</TD></TR></TABLE>
<P>다. 생산설비의 현황</P>
<P>당사는 울산에 본사를 두고 있으며 생산설비 현황은 다음과 같습니다. 이 문장은 길어서 제목이 아니며 가동률이라는 낱말이 들어 있어도 제목으로 치지 않아야 합니다. 그러나 문단 자체는 문맥으로 남는다.</P>
<TABLE><TR><TH>구분</TH><TH>장부가액</TH></TR><TR><TD>토지</TD><TD>10</TD></TR></TABLE>
</SECTION-2></SECTION-1>
<SECTION-1><TITLE>III. 재무에 관한 사항</TITLE>
<TABLE><TR><TD>매출액</TD><TD>100</TD></TR></TABLE>
</SECTION-1>
</BODY></DOCUMENT>"""


def test_picks_capacity_tables_only():
    tables = extract_tables(DOC)
    assert len(tables) == 2, [t["headings"] for t in tables]
    cap, prod = tables
    assert cap["keywords"] == ["생산능력"] and cap["keyword_in"] == "heading"
    assert cap["unit"] == "(단위 : 척)"
    assert cap["rows"] == [["사업부문", "2024년"], ["조선", "50"]]
    assert cap["section"][-1] == "3. 원재료 및 생산설비"
    assert "가동률" in prod["keywords"] and "생산실적" in prod["keywords"]
    assert prod["keyword_in"] == "table"
    # 앞 표 이후의 문맥만 — 원재료 제목이 생산능력 표 문맥에 섞이지 않는다
    assert all("원재료" not in h for h in cap["headings"])
    # 긴 본문 문단(가동률 포함)은 제목으로 치지 않으므로 생산설비 현황 표는 안 뽑힌다
    assert all("토지" not in t["html"] for t in tables)


def test_nested_and_html_preserved():
    tables = extract_tables(DOC)
    assert 'aclass="normal"' in tables[0]["html"].lower()
    assert "<p>조선</p>" in tables[0]["html"].lower()


if __name__ == "__main__":
    test_picks_capacity_tables_only()
    test_nested_and_html_preserved()
    print("ok — test_extract 2개 통과")
