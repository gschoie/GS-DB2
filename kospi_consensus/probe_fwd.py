# -*- coding: utf-8 -*-
"""4Q26(다음 분기) 컨센 소스 탐색 프로브 (일회용, GitHub 러너에서 실행).

모바일 분기 API가 지금 E분기를 3Q26 하나만 줘서 '다음분기' 탭이 빈다.
후보 소스들을 러너 IP에서 직접 확인한다. 원인 파악 후 이 파일과
flow-probe 워크플로는 삭제할 것.
"""
import json
import re
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
S = requests.Session()
S.headers.update(UA)
CODES = ["005930", "042660", "012450"]   # 삼성전자 · 한화오션 · 한화에어로스페이스


def sec(t):
    print(f"\n{'=' * 70}\n### {t}\n{'=' * 70}")


sec("1) 모바일 분기 API — E분기가 정말 1개뿐인가")
for c in CODES:
    try:
        d = S.get(f"https://m.stock.naver.com/api/stock/{c}/finance/quarter",
                  headers={"Referer": "https://m.stock.naver.com/", **UA}, timeout=15).json()
        ts = ((d.get("financeInfo") or {}).get("trTitleList")) or []
        print(f"  {c}: " + " ".join(f"{t.get('title')}({t.get('isConsensus')})" for t in ts))
    except Exception as e:
        print(f"  {c}: 실패 {e}")

sec("2) 모바일/front-api 컨센 후보")
for url in (
        "https://m.stock.naver.com/api/stock/005930/consensus",
        "https://m.stock.naver.com/api/stock/005930/finance/quarter?count=10",
        "https://m.stock.naver.com/front-api/stock/consensus?code=005930",
        "https://api.stock.naver.com/stock/005930/consensus"):
    try:
        r = S.get(url, headers={"Referer": "https://m.stock.naver.com/", **UA}, timeout=15)
        body = r.text[:500].replace("\n", " ")
        print(f"GET {url}\n  status={r.status_code} bytes={len(r.content)}\n  앞부분: {body}")
    except Exception as e:
        print(f"GET {url}\n  실패: {e}")

sec("3) 와이즈리포트 — 이미 여는 페이지들에 분기(E) 표가 있나 (requests, JS 미주입 상태)")
for name, url in (
        ("컨센서스탭 c1050001", "https://navercomp.wisereport.co.kr/company/c1050001.aspx?cmp_cd=005930&cn="),
        ("기업현황 c1010001", "https://navercomp.wisereport.co.kr/company/c1010001.aspx?cmp_cd=005930&cn="),
        ("재무분석 c1030001", "https://navercomp.wisereport.co.kr/company/c1030001.aspx?cmp_cd=005930&cn=")):
    try:
        r = S.get(url, timeout=20)
        html = r.text
        qe = sorted(set(re.findall(r"20\d\d[./](?:03|06|09|12)\s*\(E\)", html)))
        print(f"[{name}] status={r.status_code} bytes={len(html)}  분기/연간(E) 표기: {qe[:12]}")
    except Exception as e:
        print(f"[{name}] 실패: {e}")

sec("3b) 와이즈리포트 분기 컨센 ajax 후보 (c1050001이 쓰는 데이터 호출)")
for url in (
        # 기업현황 Financial Highlight 데이터 (연결/분기: rpt=1? / finGubun / frq)
        "https://navercomp.wisereport.co.kr/company/ajax/cF1001.aspx?cmp_cd=005930&fin_typ=0&freq_typ=Q",
        "https://navercomp.wisereport.co.kr/company/ajax/cF1001.aspx?cmp_cd=005930&fin_typ=0&freq_typ=Y",
        # 컨센서스 추이 ajax
        "https://navercomp.wisereport.co.kr/company/ajax/c1050001_data.aspx?cmp_cd=005930"):
    try:
        r = S.get(url, headers={"Referer": "https://navercomp.wisereport.co.kr/company/c1010001.aspx?cmp_cd=005930", **UA}, timeout=20)
        html = r.text
        qe = sorted(set(re.findall(r"20\d\d[./](?:03|06|09|12)\s*\(E\)", html)))
        has_op = "영업이익" in html
        print(f"GET {url}\n  status={r.status_code} bytes={len(html)} 영업이익={has_op} (E)표기: {qe[:12]}")
    except Exception as e:
        print(f"GET {url}\n  실패: {e}")

sec("4) FnGuide 분기 컨센서스 (보통 fwd 4개 분기)")
for url in (
        "https://comp.fnguide.com/SVO2/ASP/SVD_Consensus.asp?pGB=1&gicode=A005930",
        "https://comp.fnguide.com/SVO2/ASP/SVD_main.asp?pGB=1&gicode=A005930"):
    try:
        r = S.get(url, timeout=20)
        html = r.text
        qe = sorted(set(re.findall(r"20\d\d[./](?:03|06|09|12)\s*\(E\)", html)))
        print(f"GET {url}\n  status={r.status_code} bytes={len(html)} 영업이익={'영업이익' in html} (E)표기: {qe[:16]}")
        if qe:
            i = html.find("영업이익")
            print("  '영업이익' 부근:", re.sub(r"\s+", " ", html[i - 200:i + 600])[:500])
    except Exception as e:
        print(f"GET {url}\n  실패: {e}")

print("\n프로브 완료")
