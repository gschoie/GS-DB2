# -*- coding: utf-8 -*-
"""통합 유니버스 = KOSPI200 + KOSDAQ 시총상위 50 + 리서치 커버리지.

각 종목: {name, market(코스피/코스닥), groups[...], status}
- KOSPI200 / KOSDAQ50: 네이버 자동 크롤링
- 커버리지: coverage.json(고정 목록, 코드·시장 사전 검증됨)
"""
import json
import os
import re

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "data", "universe.json")
COVERAGE = os.path.join(BASE, "coverage.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

KOSPI200_URL = "https://finance.naver.com/sise/entryJongmok.naver?type=KPI200&page={page}"
KOSDAQ_SUM_URL = "https://finance.naver.com/sise/sise_market_sum.naver?sosok=1&page=1"
KOSPI200_RE = re.compile(r'/item/main\.naver\?code=(\d{6})[^>]*>([^<]+)</a>')
MKTCAP_RE = re.compile(r'/item/main\.naver\?code=(\d{6})"[^>]*class="tltle"[^>]*>([^<]+)</a>')
KOSDAQ_TOP = 50


def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def crawl_kospi200(max_pages=30):
    s = _session()
    codes = {}
    for page in range(1, max_pages + 1):
        r = s.get(KOSPI200_URL.format(page=page), timeout=10)
        r.encoding = "euc-kr"
        found = KOSPI200_RE.findall(r.text)
        if not found:
            break
        for code, name in found:
            codes.setdefault(code, name.strip())
    return codes


def crawl_kosdaq50():
    """코스닥 시가총액 상위 50."""
    s = _session()
    r = s.get(KOSDAQ_SUM_URL, timeout=10)
    r.encoding = "euc-kr"
    rows = MKTCAP_RE.findall(r.text)
    return {c: n.strip() for c, n in rows[:KOSDAQ_TOP]}


def load_coverage():
    try:
        with open(COVERAGE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _add(uni, code, name, market, group, status=None):
    e = uni.get(code)
    if e is None:
        uni[code] = {"name": name, "market": market, "groups": [group], "status": status}
        return
    if group not in e["groups"]:
        e["groups"].append(group)
    if not e.get("market"):
        e["market"] = market
    if status:
        e["status"] = status


def build_universe():
    uni = {}
    for code, name in crawl_kospi200().items():
        _add(uni, code, name, "코스피", "KOSPI200")
    for code, name in crawl_kosdaq50().items():
        _add(uni, code, name, "코스닥", "KOSDAQ50")
    for code, meta in load_coverage().items():
        _add(uni, code, meta.get("name", code), meta.get("market"), "커버리지",
             meta.get("status"))
    return uni


def save(uni):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(uni, f, ensure_ascii=False, indent=1)


def load_or_crawl(refresh=False):
    """캐시가 있으면 로드, 없거나 refresh면 재구성 후 저장.

    반환: {code: {name, market, groups, status}}
    """
    if not refresh and os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            data = json.load(f)
        # 구버전 캐시(code→name) 자동 재구성
        if data and isinstance(next(iter(data.values())), str):
            data = build_universe()
            save(data)
        return data
    uni = build_universe()
    if uni:
        save(uni)
    return uni


if __name__ == "__main__":
    uni = load_or_crawl(refresh=True)
    from collections import Counter
    mk = Counter(v["market"] for v in uni.values())
    gp = Counter(g for v in uni.values() for g in v["groups"])
    print(f"통합 유니버스: {len(uni)} 종목  → {CACHE}")
    print("  시장:", dict(mk))
    print("  그룹:", dict(gp))
