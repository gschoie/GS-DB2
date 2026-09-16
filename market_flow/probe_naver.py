# -*- coding: utf-8 -*-
"""네이버 수급 소스 진단 프로브 v2 (일회용, GitHub 러너에서 실행).

market-flow가 9/11부터 'lst_kos_info 블록을 찾지 못함'으로 전패 →
어떤 페이지가 어떻게 바뀌었는지 러너 IP에서 직접 확인한다.
"""
import re
import sys

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
S = requests.Session()
S.headers.update(UA)
BASE = "https://finance.naver.com/sise"


def sec(title):
    print(f"\n{'=' * 70}\n### {title}\n{'=' * 70}")


def fetch(url, enc="euc-kr"):
    try:
        r = S.get(url, timeout=30, allow_redirects=True)
        r.encoding = enc
        hist = " -> ".join(str(h.status_code) + " " + h.headers.get("Location", "")
                           for h in r.history)
        print(f"GET {url}\n  status={r.status_code} bytes={len(r.content)}"
              + (f"  redirects: {hist} -> {r.url}" if r.history else ""))
        return r
    except Exception as e:
        print(f"GET {url}\n  실패: {type(e).__name__}: {e}")
        return None


sec("1) sise_index.naver?code=KOSPI — 잠정 스냅샷 소스(현재 실패 지점)")
r = fetch(f"{BASE}/sise_index.naver?code=KOSPI")
if r is not None:
    html = r.text
    print(f"  'lst_kos_info' 등장 횟수: {html.count('lst_kos_info')}")
    print(f"  타이틀: {re.search(r'<title>(.*?)</title>', html, re.S).group(1).strip() if re.search(r'<title>(.*?)</title>', html, re.S) else '-'}")
    m = re.search(r'http-equiv=["\']?refresh["\']?[^>]*', html, re.I)
    print(f"  meta refresh: {m.group(0) if m else '없음'}")
    soup = BeautifulSoup(html, "lxml")
    print("  dl 클래스들:", sorted({" ".join(d.get("class", [])) for d in soup.find_all("dl")}))
    print("  table 클래스/요약:", [(" ".join(t.get("class", [])), t.get("summary", "")[:20])
                                  for t in soup.find_all("table")][:15])
    # '투자자'/'프로그램' 주변 텍스트로 새 위치 추정
    txt = soup.get_text(" ", strip=True)
    for kw in ("개인", "외국인", "기관", "프로그램", "차익"):
        i = txt.find(kw)
        print(f"  본문 '{kw}' 주변: …{txt[max(0, i - 40):i + 80]}…" if i >= 0 else f"  본문 '{kw}' 없음")
    print("  ---- HTML 본문 중 '투자자별 매매동향' 부근 원문 ----")
    i = html.find("투자자")
    print(html[max(0, i - 500):i + 3000] if i >= 0 else "  ('투자자' 문자열 자체가 없음)")

sec("2) 일별 확정 페이지들 — 아직 살아있나")
for name, url, ncols in (
        ("투자자별 일별", f"{BASE}/investorDealTrendDay.naver?bizdate=20260916&page=1", 10),
        ("프로그램 일별", f"{BASE}/programDealTrendDay.naver?bizdate=20260916&page=1", 9),
        ("K200선물 일별", f"{BASE}/investorDealTrendDay.naver?bizdate=20260916&sosok=03&page=1", 10),
        ("투자자별 시간대", f"{BASE}/investorDealTrendTime.naver?bizdate=20260916&page=1", 10),
        ("프로그램 시간대", f"{BASE}/programDealTrendTime.naver?bizdate=20260916&page=1", 9)):
    r = fetch(url)
    if r is None:
        continue
    soup = BeautifulSoup(r.text, "lxml")
    rows = []
    for tr in soup.select("table tr"):
        tds = tr.find_all("td")
        if len(tds) < ncols + 1:
            continue
        head = tds[0].get_text(strip=True)
        nums = [td.get_text(strip=True) for td in tds[1:ncols + 1]]
        if head:
            rows.append((head, nums))
    print(f"  [{name}] 파싱 행 수: {len(rows)} · 첫 행: {rows[0] if rows else '-'}")

sec("3) 모바일/신규 API 후보 — 잠정 스냅샷 대체 소스")
for url in (
        "https://m.stock.naver.com/api/index/KOSPI/basic",
        "https://m.stock.naver.com/api/index/KOSPI/majors",
        "https://m.stock.naver.com/api/index/KOSPI/trend/investor",
        "https://api.stock.naver.com/index/KOSPI/investorTrend",
        "https://m.stock.naver.com/front-api/marketIndex/investorTrend?category=index&reutersCode=KOSPI"):
    try:
        r = S.get(url, timeout=20,
                  headers={"Referer": "https://m.stock.naver.com/", **UA})
        body = r.text[:400].replace("\n", " ")
        print(f"GET {url}\n  status={r.status_code} bytes={len(r.content)}\n  본문 앞부분: {body}")
    except Exception as e:
        print(f"GET {url}\n  실패: {type(e).__name__}: {e}")

print("\n프로브 완료")
