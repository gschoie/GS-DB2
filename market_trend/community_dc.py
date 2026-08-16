# -*- coding: utf-8 -*-
"""커뮤니티 온도 2 — DC인사이드 주식 갤러리 수집·계량.

네이버 종토(community_naver.py)가 '종목별 관심'이라면, 디시는 '시장 전체의 분위기·밈'이다.
테마의 별명(마스가 같은 신조어)이 여기서 먼저 생기는 일이 많다. 날짜 json에
community_dc 키를 덧붙이는 후처리로 동작한다 — 네이버와 독립적으로 실패/성공한다.

무엇을 보나
  1. 개념글(추천글)  : '가장 인기 많은 글' 그 자체. 창 안의 추천 상위
  2. 제목 키워드     : 일반글 최신 샘플에서 급증 낱말 (trend_daily 토큰화 재사용)
  3. 갤러리 열기     : 글 작성 속도로 하루치 환산 — '주갤이 오늘 유난히 시끄러운가'
  4. 뜨는 글         : 시간당 조회 상위

갤러리 목록은 config.yml community_dc.galleries에서 관리한다. 갤러리 ID가 바뀌면
(디시는 종종 바꾼다) 그 파일만 고치면 된다. 잘못된 ID는 수집 0건으로 로그에 남는다.

  python community_dc.py            # 수집 → 계량 → 날짜 json에 병합 → 이력 저장
  python community_dc.py --check    # 수집·계량 통계만 출력(저장 없음)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter, Retry

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
import trend_daily  # 창 계산·토큰화·불용어·별칭 재사용  # noqa: E402

KST = timezone(timedelta(hours=9))
OUT_DIR = trend_daily.OUT_DIR
HISTORY_PATH = BASE_DIR / "state" / "community_dc_history.json"

LIST_URL = "https://gall.dcinside.com/{kind}/lists/?id={gid}&page={page}"
RECOMMEND_SUFFIX = "&exception_mode=recommend"

# 디시는 기본 파이썬 UA를 튕긴다 — 평범한 브라우저 UA로.
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
})
SESSION.mount("https://", HTTPAdapter(max_retries=Retry(
    total=3, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])))

HISTORY_DAYS = 21
BASELINE_DAYS = 7
MIN_BASELINE = 3


def fetch(url: str) -> str:
    r = SESSION.get(url, timeout=20)
    r.raise_for_status()
    return r.text  # 디시는 utf-8


def gallery_url(gallery: dict, page: int, recommend: bool = False) -> str:
    kind = "mgallery/board" if gallery.get("minor") else "board"
    url = LIST_URL.format(kind=kind, gid=gallery["id"], page=page)
    return url + (RECOMMEND_SUFFIX if recommend else "")


# ── 목록 파싱 ──────────────────────────────────────────────────────────────

def parse_list(html: str, gallery: dict) -> list[dict]:
    """갤러리 목록 한 페이지 → 글 목록. 공지·광고·설문 행은 버린다."""
    from bs4 import BeautifulSoup

    posts = []
    for tr in BeautifulSoup(html, "html.parser").select("tr.ub-content"):
        num = tr.select_one("td.gall_num")
        link = tr.select_one("td.gall_tit a")
        stamp = tr.select_one("td.gall_date")
        views = tr.select_one("td.gall_count")
        recommend = tr.select_one("td.gall_recommend")
        if not (num and link and stamp):
            continue
        if not num.get_text(strip=True).isdigit():
            continue  # 공지·설문·AD
        raw_time = stamp.get("title") or ""
        try:
            posted = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
        except ValueError:
            continue  # 목록 축약 시각뿐인 행(오늘이 아님)은 title 속성이 항상 있으므로 드묾

        def count_of(td) -> int:
            digits = re.sub(r"[^\d]", "", td.get_text()) if td else ""
            return int(digits) if digits else 0

        href = link.get("href", "")
        posts.append({
            "gallery": gallery["name"],
            "no": num.get_text(strip=True),
            "title": link.get_text(" ", strip=True),
            "posted": posted,
            "views": count_of(views),
            "recommend": count_of(recommend),
            "url": f"https://gall.dcinside.com{href}" if href.startswith("/") else href,
        })
    return posts


def collect_list(gallery: dict, start: datetime, end: datetime, max_pages: int,
                 delay: float, recommend: bool = False) -> tuple[list[dict], bool]:
    """창 안의 글을 최신부터 모은다. 네이버와 같은 정책 —
    창 끝 이후의 새 글 페이지는 수집 예산을 쓰지 않고 건너간다."""
    posts: list[dict] = []
    collected_pages = 0
    for page in range(1, max_pages * 4 + 1):
        try:
            page_posts = parse_list(fetch(gallery_url(gallery, page, recommend)), gallery)
        except requests.RequestException as exc:
            print(f"  ⚠ [{gallery['id']}{'·개념글' if recommend else ''}] p{page} 요청 실패: {exc}",
                  file=sys.stderr)
            break
        if not page_posts:
            break
        posts += [p for p in page_posts if start <= p["posted"] < end]
        if any(p["posted"] < start for p in page_posts):
            return posts, False
        if any(p["posted"] < end for p in page_posts):
            collected_pages += 1
        if collected_pages >= max_pages:
            break
        time.sleep(delay)
    return posts, len(posts) > 0


# ── 계량 ──────────────────────────────────────────────────────────────────

def load_history() -> dict:
    if not HISTORY_PATH.exists():
        return {"version": 1, "days": {}}
    history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    history.setdefault("days", {})
    return history


def save_history(history: dict) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(
        json.dumps(history, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def gallery_heat(gallery: dict, posts: list[dict], capped: bool,
                 start: datetime, end: datetime, history: dict, day: str) -> dict:
    """갤러리 하루 글 수(상한 시 작성 속도로 환산)와 평소 대비 배수."""
    from community_naver import estimate_window_count

    count = estimate_window_count(posts, start, end) if capped else len(posts)
    row = {"id": gallery["id"], "name": gallery["name"], "posts": count,
           "capped": capped, "burst": None, "base_daily": None}
    past = [e for stamp, e in sorted(history["days"].items()) if stamp < day][-BASELINE_DAYS:]
    if len(past) >= MIN_BASELINE:
        base_hits = sum(e.get("galleries", {}).get(gallery["id"], 0) for e in past)
        base_daily = base_hits / max(len(past), 1)
        row["burst"] = round(min(count / max(base_daily, 0.5), 99.0), 1)
        row["base_daily"] = round(base_daily, 1)
    return row


def title_keywords(posts: list[dict], cfg: dict, history: dict, day: str) -> list[dict]:
    """제목 급증 낱말 — 종토(community_naver)와 같은 산식·필터."""
    stopwords = {str(w).casefold() for w in (cfg.get("stopwords") or [])}
    aliases = trend_daily.alias_lookup(cfg)
    counts: dict[str, int] = {}
    for post in posts:
        tokens = trend_daily.tokenize(post["title"], stopwords, aliases)
        for term in {t for t in tokens if t}:
            counts[term] = counts.get(term, 0) + 1

    past = [e for stamp, e in sorted(history["days"].items()) if stamp < day][-BASELINE_DAYS:]
    ready = len(past) >= MIN_BASELINE
    total = max(len(posts), 1)
    max_share = float(cfg.get("max_doc_share") or 0.10)
    rows = []
    for term, count in counts.items():
        if count < 5:
            continue
        if total >= 50 and count / total > max_share:
            continue
        row = {"term": term, "count": count, "burst": None, "new": None}
        if ready:
            base_hits = sum(e.get("terms", {}).get(term, 0) for e in past)
            base_docs = sum(e.get("docs", 0) for e in past) or 1
            base_share = (base_hits + 0.5) / (base_docs + 1)
            row["burst"] = round(min((count / total) / base_share, 99.0), 1)
            row["new"] = base_hits <= 1
        rows.append(row)
    if ready:
        rows.sort(key=lambda r: (r["count"] ** 0.5) * ((r["burst"] or 0) + 1), reverse=True)
        rows = [r for r in rows if (r["burst"] or 0) >= 1.5]
    else:
        rows.sort(key=lambda r: r["count"], reverse=True)
    return rows[:15]


def pick_posts(recommended: list[dict], sampled: list[dict], now: datetime) -> tuple[list[dict], list[dict]]:
    """(개념글 추천 상위, 시간당 조회 상위)."""
    def pack(p: dict, extra: dict | None = None) -> dict:
        return {"gallery": p["gallery"], "title": p["title"], "views": p["views"],
                "recommend": p["recommend"], "url": p["url"],
                "time_kst": p["posted"].strftime("%m-%d %H:%M"), **(extra or {})}

    top = [pack(p) for p in sorted(recommended, key=lambda p: (-p["recommend"], -p["views"]))[:8]]
    rising = []
    for p in sampled:
        age_h = max((now - p["posted"]).total_seconds() / 3600, 0.5)
        rising.append((p["views"] / age_h, p))
    rising.sort(key=lambda x: -x[0])
    hot = [pack(p, {"views_per_hour": round(v, 1)}) for v, p in rising[:8] if p["views"] >= 200]
    return top, hot


# ── 실행 ──────────────────────────────────────────────────────────────────

def merge_into_day_json(day: str, block: dict) -> bool:
    merged = False
    for path in (OUT_DIR / f"{day}.json", OUT_DIR / "latest.json"):
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if path.name == "latest.json" and payload.get("date") != day:
            continue
        payload["community_dc"] = block
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        merged = True
    return merged


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description="DC인사이드 주식 갤러리 온도 수집")
    cli.add_argument("--check", action="store_true", help="수집·계량 통계만 — 저장 없음")
    args = cli.parse_args(argv)

    cfg = trend_daily.load_config()
    dcfg = cfg.get("community_dc") or {}
    galleries = dcfg.get("galleries") or []
    if not galleries:
        print("community_dc.galleries가 비어 있습니다 — config.yml 확인", file=sys.stderr)
        return 1
    max_pages = int(dcfg.get("max_pages") or 6)
    delay = float(dcfg.get("delay_sec") or 0.5)

    now = datetime.now(KST)
    start_utc, end_utc = trend_daily.day_window(now.astimezone(timezone.utc), cfg)
    start, end = start_utc.astimezone(KST), end_utc.astimezone(KST)
    day = end.strftime("%Y-%m-%d")
    print(f"커뮤니티 온도(디시) {day} · 창 {start:%m-%d %H:%M}~{end:%m-%d %H:%M} KST · 갤러리 {len(galleries)}개")

    heat_rows, sampled, recommended = [], [], []
    history = load_history()
    counts_by_gallery: dict[str, int] = {}
    for gallery in galleries:
        posts, capped = collect_list(gallery, start, end, max_pages, delay)
        rec_posts, _ = collect_list(gallery, start, end, max(2, max_pages // 3), delay, recommend=True)
        row = gallery_heat(gallery, posts, capped, start, end, history, day)
        heat_rows.append(row)
        counts_by_gallery[gallery["id"]] = row["posts"]
        sampled += posts
        recommended += rec_posts
        print(f"  [{gallery['name']}] 일반 {len(posts)}건{'(상한→ ≈' + format(row['posts'], ',') + ')' if capped else ''} · 개념글 {len(rec_posts)}건")

    if not sampled and not recommended:
        print("수집 0건 — 갤러리 ID 오류·차단·파서 깨짐 중 하나. 저장하지 않는다", file=sys.stderr)
        return 1

    keywords = title_keywords(sampled, cfg, history, day)
    top_recommended, top_rising = pick_posts(recommended, sampled, now)

    block = {
        "source": "DC인사이드",
        "galleries": heat_rows,
        "posts_sampled": len(sampled),
        "keywords": keywords,
        "top_recommended": top_recommended[:5],
        "top_rising": top_rising[:5],
    }

    if args.check:
        print("\n갤러리 열기:")
        for row in heat_rows:
            burst = f"{row['burst']}×" if row["burst"] is not None else "기준선 수집 중"
            print(f"  {row['name']:<12} {'≈' if row['capped'] else ''}{row['posts']:>5}건  {burst}")
        print("\n제목 키워드:", ", ".join(f"{r['term']}({r['count']})" for r in keywords[:10]))
        print("\n개념글 상위:")
        for p in top_recommended[:5]:
            print(f"  [{p['gallery']}] {p['title'][:50]} · 추천{p['recommend']} 조회{p['views']}")
        return 0

    term_counts = {r["term"]: r["count"] for r in keywords}
    history["days"][day] = {"docs": len(sampled), "galleries": counts_by_gallery, "terms": term_counts}
    for stale in sorted(history["days"])[:-HISTORY_DAYS]:
        del history["days"][stale]
    save_history(history)

    if merge_into_day_json(day, block):
        print(f"저장 완료: {day}.json·latest.json에 community_dc 병합 · 이력 {len(history['days'])}일")
    else:
        path = OUT_DIR / f"{day}.json"
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"date": day, "themes": [], "signals": {}, "stats": {},
                                    "meta": {"engine": "커뮤니티 단독"}, "community_dc": block},
                                   ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"트렌드 json 없음 — 디시 단독으로 {path.name} 생성")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
