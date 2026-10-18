# -*- coding: utf-8 -*-
"""coverage_flow_report.html → PNG 캡쳐 (텔레그램 첨부용).

링크 대신 그림을 보내는 이유(10/17 사용자 요청): 대시보드 주소(gschoie.github.io/GS-DB2)는
리네임으로 갈아타는 반(半)비공개 주소라 채널에 남기지 않는다. 그림은 주소를 드러내지 않는다.

자기완결 HTML 이라 file:// 로 연다(네트워크 0). 러너에선 playwright chromium 을 설치해 쓰고,
개발 컨테이너에선 /opt/pw-browsers 의 크로미움을 executable_path 로 준다(36번 교훈).
"""
from __future__ import annotations
import os, sys, glob

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PAGE = os.path.join(ROOT, "telegram_research_dashboard", "static", "coverage_flow_report.html")
OUT_PREFIX = os.path.join(HERE, "data", "capture")   # capture_1.png · capture_2.png · capture_3.png
WIDTH = 1000          # 표 9열이 줄바꿈 없이 들어가는 폭. 더 넓히면 글자가 작아져 폰에서 안 읽힌다.
SECTIONS = ("#cap-1", "#cap-2", "#cap-3")   # 제목+타일+① 등락·수급 / ② 과매수·과매도 / ③ 기계적 수급(접힘, 펼쳐 찍음)
# 한 장으로 찍으면 2000×6400 이 돼 텔레그램이 399×1280 으로 줄여 글자가 안 읽힌다(10/17 실측) —
# 섹션 3장으로 나눠 앨범(sendMediaGroup)으로 보낸다. 장당 세로가 가로의 2~3배 안쪽.


def _chromium_exe():
    """컨테이너 전용 폴백 — 러너엔 playwright install 이 깔아 둔 기본 브라우저가 있다."""
    if os.environ.get("PW_CHROMIUM"):
        return os.environ["PW_CHROMIUM"]
    for pat in ("/opt/pw-browsers/chromium-*/chrome-linux/chrome", "/opt/pw-browsers/chromium/chrome-linux/chrome"):
        hit = sorted(glob.glob(pat))
        if hit:
            return hit[-1]
    return None


def capture(page=PAGE, out_prefix=OUT_PREFIX, width=WIDTH):
    """섹션별 PNG 경로 목록을 돌려준다. 섹션 래퍼가 없는 옛 페이지면 전체 1장으로 폴백."""
    from playwright.sync_api import sync_playwright
    os.makedirs(os.path.dirname(out_prefix), exist_ok=True)
    outs = []
    with sync_playwright() as pw:
        kw = {}
        exe = _chromium_exe()
        if exe and not os.environ.get("CI"):
            kw["executable_path"] = exe
        b = pw.chromium.launch(**kw)
        pg = b.new_page(viewport={"width": width, "height": 900}, device_scale_factor=2)
        pg.goto("file://" + os.path.abspath(page))
        pg.wait_for_load_state("load")
        pg.evaluate("document.querySelectorAll('details').forEach(d => { d.open = true })")   # ③ 접힘 섹션도 펼쳐 찍는다
        for i, sel in enumerate(SECTIONS, 1):
            if pg.locator(sel).count() == 0:
                continue
            out = f"{out_prefix}_{i}.png"
            pg.locator(sel).screenshot(path=out)
            outs.append(out)
        if not outs:
            out = f"{out_prefix}_1.png"
            pg.screenshot(path=out, full_page=True)
            outs.append(out)
        b.close()
    return outs


if __name__ == "__main__":
    for p in capture(*(sys.argv[1:3])):
        print("captured", p, os.path.getsize(p), "bytes")
