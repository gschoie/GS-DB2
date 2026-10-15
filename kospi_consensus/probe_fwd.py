# -*- coding: utf-8 -*-
"""4Q26(다음 분기) 컨센 소스 탐색 프로브 v2 — Playwright 렌더링 후 표 전수 덤프.

1차 결과: 모바일 API는 E=3Q26 하나뿐, FnGuide는 러너 차단.
→ 이미 종목마다 여는 와이즈리포트 페이지(c1050001/c1010001)를 JS 주입 후 뒤져
  분기(E) 그리드가 있는지 확인한다. 파악 후 이 파일과 consensus-probe.yml 삭제.
"""
import re
import sys

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
E_PAT = re.compile(r"20\d\d[./](?:03|06|09|12)\s*\(E\)")


def dump_tables(page, tag, click_text=None):
    if click_text:
        try:   # '분기' 토글 등 — 같은 텍스트 요소가 여럿이면 첫 번째
            page.get_by_text(click_text, exact=True).first.click(timeout=3000)
            page.wait_for_timeout(2500)
            print(f"  ('{click_text}' 클릭 성공)")
        except Exception as e:
            print(f"  ('{click_text}' 클릭 실패: {type(e).__name__})")
    for i, t in enumerate(page.query_selector_all("table")):
        tx = t.inner_text()
        es = sorted(set(E_PAT.findall(tx)))
        if not es:
            continue
        head = re.sub(r"\s+", " ", tx)[:450]
        print(f"  [{tag} 표#{i}] (E)={es}")
        print(f"    내용: {head}")


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(user_agent=UA,
                              extra_http_headers={"Referer": "https://finance.naver.com/"})
    page = ctx.new_page()
    for code in ("005930", "042660"):
        print(f"\n{'=' * 70}\n### {code} — c1050001 (컨센서스 탭, 현행 연간 수집 페이지)\n{'=' * 70}")
        page.goto(f"https://navercomp.wisereport.co.kr/company/c1050001.aspx?cmp_cd={code}&cn=",
                  wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(6000)
        dump_tables(page, "기본")
        dump_tables(page, "분기클릭후", click_text="분기")

        print(f"\n{'=' * 70}\n### {code} — c1010001 (기업현황 Financial Highlight)\n{'=' * 70}")
        page.goto(f"https://navercomp.wisereport.co.kr/company/c1010001.aspx?cmp_cd={code}&cn=",
                  wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(6000)
        dump_tables(page, "기본")
        dump_tables(page, "분기클릭후", click_text="분기")
    browser.close()

print("\n프로브 v2 완료")
