# -*- coding: utf-8 -*-
"""통합 유니버스 = KOSPI200 + KOSDAQ 시총상위 50 + 리서치 커버리지.

각 종목: {name, market(코스피/코스닥), groups[...], status}
- KOSPI200 / KOSDAQ50: 네이버 자동 크롤링
- 커버리지: coverage.json(고정 목록, 코드·시장 사전 검증됨)
"""
import json
import os

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "data", "universe.json")
COVERAGE = os.path.join(BASE, "coverage.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 2026-09 네이버증권 개편: 옛 PC 페이지(entryJongmok=410 폐쇄, sise_market_sum=302 →
# stock.naver.com SPA)가 죽어 9/18부터 KOSPI200·코스닥50이 0건 → 커버리지만 남았다.
# 모바일 JSON API는 생존(러너 프로브 9/28 확인) — 분기 컨센과 같은 m.stock.naver.com.
MAPI = "https://m.stock.naver.com/api"
KOSPI200_API = MAPI + "/index/KPI200/enrollStocks?page={page}&pageSize={size}"
KOSDAQ_SUM_API = MAPI + "/stocks/marketValue/KOSDAQ?page=1&pageSize={size}"
KOSDAQ_TOP = 50
MIN_KOSPI200 = 150   # 이보다 적게 잡히면 크롤 고장으로 보고 직전 캐시의 해당 그룹을 쓴다


def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": "https://m.stock.naver.com/"})
    return s


def _items(j):
    """enrollStocks는 리스트, marketValue는 {stocks:[...]} — 둘 다 받는다."""
    rows = j.get("stocks", []) if isinstance(j, dict) else (j or [])
    return [(r["itemCode"], r["stockName"].strip()) for r in rows
            if r.get("itemCode") and r.get("stockName")]


def crawl_kospi200(page_size=100, max_pages=5):
    s = _session()
    codes = {}
    for page in range(1, max_pages + 1):
        r = s.get(KOSPI200_API.format(page=page, size=page_size), timeout=10)
        r.raise_for_status()
        found = _items(r.json())
        new = [(c, n) for c, n in found if c not in codes]
        for code, name in new:
            codes[code] = name
        if len(found) < page_size or not new:
            break
    return codes


def crawl_kosdaq50():
    """코스닥 시가총액 상위 50."""
    r = _session().get(KOSDAQ_SUM_API.format(size=KOSDAQ_TOP), timeout=10)
    r.raise_for_status()
    return dict(_items(r.json())[:KOSDAQ_TOP])


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


def _cached_group(cached, group):
    return {c: v["name"] for c, v in (cached or {}).items()
            if isinstance(v, dict) and group in v.get("groups", [])}


def _crawl_or_cache(fn, label, minimum, cached):
    """그룹별로 크롤하고, 부족(<minimum)·예외면 직전 캐시의 그 그룹으로 폴백.

    전체 종목 수로만 판정하면 커버리지(175)가 문턱을 넘겨 KOSPI200이 통째로
    빠져도 못 알아챈다(9/18~9/26 실제 사고) — 그래서 그룹 단위로 본다.
    """
    try:
        got = fn()
    except Exception as e:
        print(f"⚠ {label} 크롤 실패({e})")
        got = {}
    if len(got) >= minimum:
        return got
    old = _cached_group(cached, label)
    if len(old) > len(got):
        print(f"⚠ {label} 크롤 {len(got)}종목(부족) → 캐시 {len(old)}종목 사용")
        return old
    print(f"⚠ {label} 크롤 {len(got)}종목(부족) — 폴백할 캐시도 없음")
    return got


def build_universe(cached=None):
    uni = {}
    for code, name in _crawl_or_cache(crawl_kospi200, "KOSPI200", MIN_KOSPI200, cached).items():
        _add(uni, code, name, "코스피", "KOSPI200")
    for code, name in _crawl_or_cache(crawl_kosdaq50, "KOSDAQ50", KOSDAQ_TOP - 10, cached).items():
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
    def _cached():
        if os.path.exists(CACHE):
            with open(CACHE, encoding="utf-8") as f:
                return json.load(f)
        return {}

    if not refresh and os.path.exists(CACHE):
        data = _cached()
        # 구버전 캐시(code→name) 자동 재구성
        if data and isinstance(next(iter(data.values())), str):
            data = build_universe()
            save(data)
        return data

    # refresh: 크롤 시도. 네이버가 막거나 개편으로 소스가 죽으면, 크래시하지 말고
    # 그룹별로 직전 캐시(마지막 정상 유니버스)로 폴백한다.
    uni = build_universe(_cached())
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
