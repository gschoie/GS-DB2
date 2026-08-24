# -*- coding: utf-8 -*-
"""밸류에이션 대시보드가 훑을 종목 유니버스.

조선·방산·건설기계 핵심 종목만 담은 소수 정예 리스트다(피어그룹 100여개 전수 스캔은
야후 호출이 종목당 4~5회라 러너에서 오래 걸리고 스로틀에도 자주 걸린다).
종목을 늘리거나 빼려면 이 파일만 고치면 된다 — 수집·엑셀·화면이 모두 여기를 읽는다.

ticker 는 야후 파이낸스 심볼 그대로. (한국 KOSPI=.KS / KOSDAQ=.KQ,
독일=.DE, 영국=.L, 이탈리아=.MI, 스웨덴=.ST)
"""

TARGET_COMPANIES = [
    # ── 조선사 ────────────────────────────────────────────────
    {"industry": "조선", "sub": "조선사", "region": "한국", "name": "HD현대중공업", "ticker": "329180.KS"},
    {"industry": "조선", "sub": "조선사", "region": "한국", "name": "한화오션", "ticker": "042660.KS"},
    {"industry": "조선", "sub": "조선사", "region": "한국", "name": "삼성중공업", "ticker": "010140.KS"},
    {"industry": "조선", "sub": "조선사", "region": "한국", "name": "HD한국조선해양", "ticker": "009540.KS"},
    {"industry": "조선", "sub": "조선사", "region": "한국", "name": "대한조선", "ticker": "439260.KS"},
    {"industry": "조선", "sub": "조선사", "region": "한국", "name": "HJ중공업", "ticker": "097230.KS"},
    {"industry": "조선", "sub": "조선사", "region": "이탈리아", "name": "Fincantieri", "ticker": "FCT.MI"},

    # ── 조선 엔진/기자재 ──────────────────────────────────────
    {"industry": "조선", "sub": "엔진/기자재", "region": "한국", "name": "HD현대마린솔루션", "ticker": "443060.KS"},
    {"industry": "조선", "sub": "엔진/기자재", "region": "한국", "name": "HD현대마린엔진", "ticker": "071970.KS"},
    {"industry": "조선", "sub": "엔진/기자재", "region": "한국", "name": "한화엔진", "ticker": "082740.KS"},
    {"industry": "조선", "sub": "엔진/기자재", "region": "한국", "name": "한국카본", "ticker": "017960.KS"},
    {"industry": "조선", "sub": "엔진/기자재", "region": "한국", "name": "동성화인텍", "ticker": "033500.KQ"},

    # ── 방산 (한국) ───────────────────────────────────────────
    {"industry": "방산", "sub": "체계", "region": "한국", "name": "한국항공우주", "ticker": "047810.KS"},
    {"industry": "방산", "sub": "체계", "region": "한국", "name": "한화에어로스페이스", "ticker": "012450.KS"},
    {"industry": "방산", "sub": "체계", "region": "한국", "name": "LIG디펜스앤에어로스페이스", "ticker": "079550.KS"},
    {"industry": "방산", "sub": "체계", "region": "한국", "name": "한화시스템", "ticker": "272210.KS"},
    {"industry": "방산", "sub": "체계", "region": "한국", "name": "현대로템", "ticker": "064350.KS"},

    # ── 방산 (해외) ───────────────────────────────────────────
    {"industry": "방산", "sub": "체계", "region": "미국", "name": "Lockheed Martin", "ticker": "LMT"},
    {"industry": "방산", "sub": "체계", "region": "미국", "name": "Northrop Grumman", "ticker": "NOC"},
    {"industry": "방산", "sub": "체계", "region": "미국", "name": "General Dynamics", "ticker": "GD"},
    {"industry": "방산", "sub": "체계", "region": "미국", "name": "RTX", "ticker": "RTX"},
    {"industry": "방산", "sub": "조선/방산", "region": "미국", "name": "Huntington Ingalls", "ticker": "HII"},
    {"industry": "방산", "sub": "체계", "region": "독일", "name": "Rheinmetall", "ticker": "RHM.DE"},
    {"industry": "방산", "sub": "체계", "region": "영국", "name": "BAE Systems", "ticker": "BA.L"},
    {"industry": "방산", "sub": "항공", "region": "이탈리아", "name": "Leonardo", "ticker": "LDO.MI"},
    {"industry": "방산", "sub": "항공", "region": "스웨덴", "name": "Saab AB", "ticker": "SAAB-B.ST"},

    # ── 건설기계 (완성장비) ───────────────────────────────────
    {"industry": "건설기계", "sub": "완성장비", "region": "한국", "name": "HD건설기계", "ticker": "267270.KS"},
    {"industry": "건설기계", "sub": "완성장비", "region": "한국", "name": "두산밥캣", "ticker": "241560.KS"},
    {"industry": "건설기계", "sub": "완성장비", "region": "한국", "name": "대동", "ticker": "000490.KS"},
    {"industry": "건설기계", "sub": "완성장비", "region": "미국", "name": "Caterpillar", "ticker": "CAT"},
    {"industry": "건설기계", "sub": "완성장비", "region": "미국", "name": "Deere", "ticker": "DE"},
    {"industry": "건설기계", "sub": "완성장비", "region": "미국", "name": "CNH Industrial", "ticker": "CNH"},
    {"industry": "건설기계", "sub": "완성장비", "region": "일본", "name": "Komatsu", "ticker": "6301.T"},
    {"industry": "건설기계", "sub": "완성장비", "region": "일본", "name": "Hitachi CM", "ticker": "6305.T"},
    {"industry": "건설기계", "sub": "완성장비", "region": "스웨덴", "name": "Volvo", "ticker": "VOLV-B.ST"},
    {"industry": "건설기계", "sub": "완성장비", "region": "중국", "name": "삼일중공업(SANY)", "ticker": "600031.SS"},
    {"industry": "건설기계", "sub": "완성장비", "region": "중국", "name": "서공기계(XCMG)", "ticker": "000425.SZ"},

    # ── 건설기계 (부품·렌탈) ──────────────────────────────────
    {"industry": "건설기계", "sub": "부품", "region": "한국", "name": "진성티이씨", "ticker": "036890.KQ"},
    {"industry": "건설기계", "sub": "부품", "region": "한국", "name": "디와이파워", "ticker": "210540.KS"},
    {"industry": "건설기계", "sub": "부품", "region": "한국", "name": "대창단조", "ticker": "015230.KS"},
    {"industry": "건설기계", "sub": "렌탈", "region": "미국", "name": "United Rentals", "ticker": "URI"},
]
