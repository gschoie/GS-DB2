# -*- coding: utf-8 -*-
"""커뮤니티 온도 — 네이버 종목토론실(종토) 수집·계량.

텔레그램(리서치 채널)이 "전문가들이 뭘 말하나"라면, 종토는 "개미들이 뭘 쳐다보나"다.
trend_daily.py가 만든 날짜 json에 community 키를 덧붙이는 후처리로 동작한다.

무엇을 보나
  1. 글 수 급증   : 종목별 하루 글 수를 최근 7일 기준선과 비교(트렌드와 같은 배수 방식)
  2. 인기 글      : 공감·조회 상위 글
  3. 뜨는 글      : 조회수/경과시간(시간당 조회) 상위 — '조회수가 느는 글'의 1회 실행 근사
  4. 제목 키워드  : 급증 낱말 (trend_daily의 토큰화·불용어·별칭 재사용)

감시 종목(universe)은 관리가 필요 없다:
  config.yml aliases에 적힌 종목코드(조선·방산 등 관심종목) + 네이버 검색상위 30 +
  config community.extra_codes. 검색상위는 그 자체가 '오늘 개미가 검색한 종목' 신호라
  함께 기록한다.

  python community_naver.py            # 수집 → 계량 → 날짜 json에 병합 → 이력 저장
  python community_naver.py --check    # 수집·계량 통계만 출력(저장 없음)

네이버가 러너 IP를 튕기면 이 스크립트만 실패한다 — 워크플로에서 continue-on-error로
돌려 텔레그램 트렌드 리포트까지 죽이지 않는다.
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
import trend_daily  # 창 계산·토큰화·불용어·별칭·이력 방식 재사용  # noqa: E402

KST = timezone(timedelta(hours=9))
OUT_DIR = trend_daily.OUT_DIR
HISTORY_PATH = BASE_DIR / "state" / "community_history.json"

BOARD_URL = "https://finance.naver.com/item/board.naver?code={code}&page={page}"
READ_URL = "https://finance.naver.com/item/board_read.naver"
SEARCH_TOP_URL = "https://finance.naver.com/sise/lastsearch2.naver"

# market_flow/scrape.py와 같은 정책 — 네이버는 기본 UA면 Actions 러너에서도 잘 준다.
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
SESSION.mount("https://", HTTPAdapter(max_retries=Retry(
    total=3, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])))

HISTORY_DAYS = 21
BASELINE_DAYS = 7
MIN_BASELINE = 3


def decode_page(content: bytes) -> str:
    """네이버 금융은 페이지마다 인코딩이 다르다 — 검색상위는 euc-kr, 게시판은 utf-8.

    utf-8 엄격 디코드는 euc-kr 바이트에서 거의 반드시 실패하므로 판별기로 쓴다.
    (처음에 euc-kr로 강제했다가 게시판 제목이 '湲곕�ㅻ┝'처럼 깨진 사고의 재발 방지)
    """
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("cp949", errors="replace")


def fetch(url: str) -> str:
    r = SESSION.get(url, timeout=20)
    r.raise_for_status()
    return decode_page(r.content)


# ── 수집 대상 ──────────────────────────────────────────────────────────────

CODE_RE = re.compile(r"^\d{6}$")


def alias_codes(cfg: dict) -> dict[str, str]:
    """aliases의 종목코드 → 정식명. 관심종목 목록을 따로 관리하지 않기 위한 재사용."""
    table = {}
    for name, variants in (cfg.get("aliases") or {}).items():
        for v in (variants or []):
            if CODE_RE.fullmatch(str(v)):
                table[str(v)] = str(name)
    return table


def fetch_search_top() -> list[dict]:
    """네이버 검색상위 30 — '오늘 개미가 검색해 본 종목' 그 자체가 신호다."""
    html = fetch(SEARCH_TOP_URL)
    from bs4 import BeautifulSoup

    rows = []
    for a in BeautifulSoup(html, "html.parser").select("a.tltle"):  # 네이버의 오래된 오타 클래스
        m = re.search(r"code=(\d{6})", a.get("href", ""))
        if m:
            rows.append({"code": m.group(1), "name": a.get_text(strip=True), "rank": len(rows) + 1})
    return rows


def build_universe(cfg: dict, search_top: list[dict]) -> dict[str, str]:
    ccfg = cfg.get("community") or {}
    universe = dict(alias_codes(cfg))
    for row in search_top:
        universe.setdefault(row["code"], row["name"])
    for extra in (ccfg.get("extra_codes") or []):
        if isinstance(extra, dict):
            for code, name in extra.items():
                universe[str(code)] = str(name)
        elif CODE_RE.fullmatch(str(extra)):
            universe.setdefault(str(extra), str(extra))
    cap = int(ccfg.get("max_stocks") or 80)
    return dict(list(universe.items())[:cap])


# ── 종토 게시판 파싱 ───────────────────────────────────────────────────────

def parse_board(html: str, code: str) -> list[dict]:
    """게시판 목록 한 페이지 → 글 목록. 표 구조: 날짜·제목·글쓴이·조회·공감·비공감."""
    from bs4 import BeautifulSoup

    posts = []
    for tr in BeautifulSoup(html, "html.parser").select("table.type2 tr"):
        link = tr.select_one('td.title a[href*="board_read"]')
        tds = tr.find_all("td")
        if not link or len(tds) < 6:
            continue
        stamp = tds[0].get_text(strip=True)
        try:
            posted = datetime.strptime(stamp, "%Y.%m.%d %H:%M").replace(tzinfo=KST)
        except ValueError:
            continue

        def num(td) -> int:
            digits = re.sub(r"[^\d]", "", td.get_text())
            return int(digits) if digits else 0

        m = re.search(r"nid=(\d+)", link.get("href", ""))
        posts.append({
            "code": code,
            "nid": m.group(1) if m else "",
            "title": link.get_text(strip=True),
            "posted": posted,
            "views": num(tds[3]),
            "likes": num(tds[4]),
            "dislikes": num(tds[5]),
            "url": f"{READ_URL}?code={code}&nid={m.group(1)}" if m else "",
        })
    return posts


def collect_board(code: str, start: datetime, end: datetime,
                  max_pages: int, delay: float) -> tuple[list[dict], bool]:
    """창(start~end) 안의 글을 페이지 넘기며 모은다. (글 목록, 상한에 걸렸는지)

    게시판은 최신순이라 창 끝(end) 이후의 글은 건너뛰며 계속 가고, 창 시작(start)보다
    오래된 글이 나오면 그 게시판은 끝이다. end 상한이 없으면 다음날 새벽에 수동
    실행했을 때 이튿날 글이 전날 리포트에 섞인다.
    """
    posts: list[dict] = []
    collected_pages = 0
    # 창 끝(end) 이후의 새 글만 있는 페이지는 '건너가는 중'이므로 수집 예산(max_pages)을
    # 쓰지 않는다 — 정기 시각보다 늦게 돌리면 대형주는 새 글 몇 페이지를 지나야 창에
    # 닿기 때문이다. 무한히 파고들지 않게 절대 상한(max_pages×4)은 따로 둔다.
    for page in range(1, max_pages * 4 + 1):
        try:
            page_posts = parse_board(fetch(BOARD_URL.format(code=code, page=page)), code)
        except requests.RequestException as exc:
            print(f"  ⚠ [{code}] p{page} 요청 실패: {exc}", file=sys.stderr)
            break
        if not page_posts:
            break
        posts += [p for p in page_posts if start <= p["posted"] < end]
        if any(p["posted"] < start for p in page_posts):  # 창 시작을 지났다 — 끝
            return posts, False
        if any(p["posted"] < end for p in page_posts):
            collected_pages += 1
        if collected_pages >= max_pages:
            break
        time.sleep(delay)
    return posts, len(posts) > 0  # 페이지 상한까지 전부 창 안이면 잘렸을 수 있다


# ── 계량 ──────────────────────────────────────────────────────────────────

def estimate_window_count(posts: list[dict], window_start: datetime, window_end: datetime) -> int:
    """페이지 상한에 걸린 게시판의 창 전체 글 수를 '작성 속도'로 추정한다.

    대형주는 하루 수천 글이라 페이지 상한(100글)에 걸리는데, 그대로 100을 쓰면
    상한 걸린 종목이 전부 같은 값이 되어 급증 표가 무의미해진다. 대신 수집한
    글들이 몇 시간 만에 쌓였는지(속도)를 재서 창 전체로 환산한다 — 요청을 더
    쓰지 않고 진짜 규모를 얻고, 기준선 배수도 대형주까지 작동하게 된다.
    """
    if not posts:
        return 0
    times = sorted(p["posted"] for p in posts)
    covered_h = max((times[-1] - times[0]).total_seconds() / 3600, 0.25)
    window_h = (window_end - window_start).total_seconds() / 3600
    return min(round(len(posts) * window_h / covered_h), 99_999)

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


def stock_bursts(counts: dict[str, int], names: dict[str, str], capped: set[str],
                 history: dict, day: str) -> list[dict]:
    """종목별 글 수를 최근 7일 기준선과 비교 — trend_daily.spike_scores와 같은 사상."""
    past = [entry for stamp, entry in sorted(history["days"].items()) if stamp < day][-BASELINE_DAYS:]
    ready = len(past) >= MIN_BASELINE
    rows = []
    for code, count in counts.items():
        if count < 3:
            continue
        row = {"code": code, "name": names.get(code, code), "posts": count,
               "capped": code in capped, "burst": None, "base_daily": None}
        if ready:
            base_hits = sum(entry.get("stocks", {}).get(code, 0) for entry in past)
            base_daily = base_hits / max(len(past), 1)
            row["burst"] = round(min(count / max(base_daily, 0.5), 99.0), 1)
            row["base_daily"] = round(base_daily, 1)
        rows.append(row)
    if ready:
        rows.sort(key=lambda r: (r["burst"] or 0) * (r["posts"] ** 0.5), reverse=True)
        rows = [r for r in rows if (r["burst"] or 0) >= 1.5]
    else:
        rows.sort(key=lambda r: r["posts"], reverse=True)
    return rows


def title_keywords(posts: list[dict], cfg: dict, history: dict, day: str) -> list[dict]:
    """글 제목에서 급증 낱말. 본문은 안 긁는다 — 제목만으로 충분하고 요청이 수십 배 준다."""
    stopwords = {str(w).casefold() for w in (cfg.get("stopwords") or [])}
    aliases = trend_daily.alias_lookup(cfg)
    counts: dict[str, int] = {}
    for post in posts:
        tokens = trend_daily.tokenize(post["title"], stopwords, aliases)
        for term in {t for t in tokens if t}:
            counts[term] = counts.get(term, 0) + 1

    past = [entry for stamp, entry in sorted(history["days"].items()) if stamp < day][-BASELINE_DAYS:]
    ready = len(past) >= MIN_BASELINE
    total = max(len(posts), 1)
    max_share = float(cfg.get("max_doc_share") or 0.10)  # 상투어 구조 필터 — trend와 동일
    rows = []
    for term, count in counts.items():
        if count < 5:  # 종토는 도배가 많아 문턱을 텔레그램(3)보다 높인다
            continue
        if total >= 50 and count / total > max_share:
            continue
        row = {"term": term, "count": count, "burst": None, "new": None}
        if ready:
            base_hits = sum(entry.get("terms", {}).get(term, 0) for entry in past)
            base_docs = sum(entry.get("docs", 0) for entry in past) or 1
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


def pick_posts(posts: list[dict], names: dict[str, str], now: datetime) -> tuple[list[dict], list[dict]]:
    """(공감 상위, 시간당 조회 상위). 후자가 '조회수가 느는 글'의 1회 실행 근사다."""
    def pack(p: dict, extra: dict) -> dict:
        return {"code": p["code"], "name": names.get(p["code"], p["code"]), "title": p["title"],
                "views": p["views"], "likes": p["likes"], "url": p["url"],
                "time_kst": p["posted"].strftime("%m-%d %H:%M"), **extra}

    liked = [pack(p, {}) for p in sorted(posts, key=lambda p: (-p["likes"], -p["views"]))[:8]
             if p["likes"] >= 3]
    rising = []
    for p in posts:
        age_h = max((now - p["posted"]).total_seconds() / 3600, 0.5)
        rising.append((p["views"] / age_h, p))
    rising.sort(key=lambda x: -x[0])
    hot = [pack(p, {"views_per_hour": round(v, 1)}) for v, p in rising[:8] if p["views"] >= 100]
    return liked, hot


# ── 실행 ──────────────────────────────────────────────────────────────────

def merge_into_day_json(day: str, community: dict) -> bool:
    """trend_daily가 만든 날짜 json·latest.json에 community 키를 덧붙인다."""
    merged = False
    for path in (OUT_DIR / f"{day}.json", OUT_DIR / "latest.json"):
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if path.name == "latest.json" and payload.get("date") != day:
            continue  # 옛 latest에 오늘 커뮤니티를 붙이지 않는다
        payload["community"] = community
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        merged = True
    return merged


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description="네이버 종토 커뮤니티 온도 수집")
    cli.add_argument("--check", action="store_true", help="수집·계량 통계만 — 저장 없음")
    args = cli.parse_args(argv)

    cfg = trend_daily.load_config()
    ccfg = cfg.get("community") or {}
    max_pages = int(ccfg.get("max_pages") or 5)
    delay = float(ccfg.get("delay_sec") or 0.3)

    now = datetime.now(KST)
    start_utc, end_utc = trend_daily.day_window(now.astimezone(timezone.utc), cfg)
    start, end = start_utc.astimezone(KST), end_utc.astimezone(KST)
    day = end.strftime("%Y-%m-%d")
    print(f"커뮤니티 온도(종토) {day} · 창 {start:%m-%d %H:%M}~{end:%m-%d %H:%M} KST")

    search_top = fetch_search_top()
    universe = build_universe(cfg, search_top)
    print(f"감시 종목 {len(universe)}개 (관심 {len(alias_codes(cfg))} + 검색상위 {len(search_top)})")

    all_posts: list[dict] = []
    counts: dict[str, int] = {}
    capped: set[str] = set()
    for code in universe:
        posts, hit_cap = collect_board(code, start, end, max_pages, delay)
        if hit_cap:
            counts[code] = estimate_window_count(posts, start, end)
            capped.add(code)
        else:
            counts[code] = len(posts)
        all_posts += posts
    print(f"창 안의 글 {len(all_posts)}건 (페이지 상한에 걸린 종목 {len(capped)}개)")
    if not all_posts:
        print("수집 0건 — 네이버 차단 또는 파서 깨짐. 저장하지 않는다", file=sys.stderr)
        return 1

    history = load_history()
    bursts = stock_bursts(counts, universe, capped, history, day)
    keywords = title_keywords(all_posts, cfg, history, day)
    liked, hot = pick_posts(all_posts, universe, now)

    community = {
        "source": "네이버 종목토론실",
        "universe": len(universe),
        "posts": len(all_posts),
        "search_top": search_top[:10],
        "hot_stocks": bursts[:12],
        "keywords": keywords,
        "top_liked": liked[:5],
        "top_rising": hot[:5],
    }

    if args.check:
        print("\n글 수 상위 종목:")
        for row in bursts[:10]:
            burst = f"{row['burst']}×" if row["burst"] is not None else "기준선 수집 중"
            print(f"  {row['name']:<12} {row['posts']:>4}건  {burst}{' (상한)' if row['capped'] else ''}")
        print("\n제목 키워드:", ", ".join(f"{r['term']}({r['count']})" for r in keywords[:10]))
        print("\n공감 상위:")
        for p in liked[:5]:
            print(f"  [{p['name']}] {p['title'][:50]} · 공감{p['likes']} 조회{p['views']}")
        return 0

    # 이력 저장 (기준선). 낱말은 상위만 잘라 파일이 무한정 크지 않게.
    term_counts = {r["term"]: r["count"] for r in keywords}
    history["days"][day] = {"docs": len(all_posts), "stocks": counts, "terms": term_counts}
    for stale in sorted(history["days"])[:-HISTORY_DAYS]:
        del history["days"][stale]
    save_history(history)

    # 조각 파일 — 뒤이어 도는 트렌드 산출(trend_daily)이 읽어 Gemini 입력·날짜 json에 넣는다.
    trend_daily.PARTS_DIR.mkdir(parents=True, exist_ok=True)
    (trend_daily.PARTS_DIR / f"{day}-naver.json").write_text(
        json.dumps(community, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    if merge_into_day_json(day, community):
        print(f"저장 완료: 조각 + {day}.json·latest.json 병합 · 이력 {len(history['days'])}일")
    else:
        # 트렌드 산출 전(정상 순서)이거나 트렌드가 실패한 날 — 조각만 남긴다.
        print(f"저장 완료: 조각({day}-naver.json) · 이력 {len(history['days'])}일")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
