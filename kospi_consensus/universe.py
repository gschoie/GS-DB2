# -*- coding: utf-8 -*-
"""KOSPI200 구성종목 자동 크롤링 (네이버 금융)."""
import json
import os
import re

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "data", "universe.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 네이버 금융 KOSPI200 편입종목 리스트 (페이지네이션)
LIST_URL = "https://finance.naver.com/sise/entryJongmok.naver?type=KPI200&page={page}"
ROW_RE = re.compile(r'/item/main\.naver\?code=(\d{6})[^>]*>([^<]+)</a>')


def crawl(max_pages=30):
    """KOSPI200 코드→종목명 dict 반환 (편입 순서 보존)."""
    codes = {}
    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    for page in range(1, max_pages + 1):
        r = session.get(LIST_URL.format(page=page), timeout=10)
        r.encoding = "euc-kr"
        found = ROW_RE.findall(r.text)
        if not found:
            break
        for code, name in found:
            codes.setdefault(code, name.strip())
    return codes


def save(codes):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(codes, f, ensure_ascii=False, indent=2)


def load_or_crawl(refresh=False):
    """캐시가 있으면 로드, 없거나 refresh면 크롤 후 저장."""
    if not refresh and os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    codes = crawl()
    if codes:
        save(codes)
    return codes


if __name__ == "__main__":
    uni = load_or_crawl(refresh=True)
    print(f"KOSPI200: {len(uni)} 종목 크롤 완료 → {CACHE}")
    for c, n in list(uni.items())[:5]:
        print(" ", c, n)
