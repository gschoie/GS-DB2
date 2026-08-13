"""시장관심.내러티브 — 구독 채널 전체 글에서 어제~오늘의 시장 테마를 뽑는 일일 트렌드 봇.

동작은 3단으로 나뉜다. 토큰을 쓰는 것은 마지막 한 번뿐이다.

  A. 수집(파이썬) : 내 계정이 구독한 모든 채널의 지난 하루치(전일 06:00~당일 06:00 KST)
     글을 가져온다. source_watcher의 telegram_account 어댑터와 세션을 그대로 쓴다.
     ship_all과 달리 키워드로 거르지 않고 전체를 본다 — 트렌드는 모르던 낱말에서 나온다.
  B. 계량(파이썬) : 퍼나른 중복 글을 min-hash로 접되 '몇 채널이 실었나'(전파 수)를 남기고,
     낱말·두낱말(bigram) 빈도를 최근 7일 기준선과 비교해 급증(spike)을 계산한다.
     기준선은 state/trend_history.json에 매일 쌓인다.
  C. 합성(Gemini 1회) : B의 신호 + 대표 발췌만 넘겨 테마 3~6개의 이름·내러티브를 받는다.
     팩트는 전부 파이썬이 준 것만 쓰게 해 환각을 줄인다. 응답은 JSON으로 고정.

산출물
  telegram_research_dashboard/static/market_trend/<날짜>.md   사람이 읽는 아카이브
  telegram_research_dashboard/static/market_trend/latest.json  대시보드·텔레그램 발송용

    python trend_daily.py                # 수집 → 계량 → Gemini → 저장
    python trend_daily.py --check        # 수집·계량까지만 하고 통계 출력(토큰·저장 없음)
    python trend_daily.py --no-llm       # Gemini 없이 계량 신호만으로 리포트 저장
    python trend_daily.py --dry-run      # 전 과정 실행하되 파일 저장 없이 출력만
    python trend_daily.py --save-corpus corpus.jsonl   # 수집분을 파일로 (디버깅)
    python trend_daily.py --corpus corpus.jsonl        # 수집 대신 파일에서 (디버깅)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
# 수집 어댑터·중복 지문은 source_watcher 것을 그대로 쓴다. 복사하면 t.me 파싱이나
# min-hash 정책이 바뀔 때 두 곳을 고쳐야 하므로 import로 묶는다.
sys.path.insert(0, str(BASE_DIR.parent / "source_watcher"))
import adapters  # noqa: E402
from watch_sources import fingerprints  # noqa: E402

KST = timezone(timedelta(hours=9))
CONFIG_PATH = BASE_DIR / "config.yml"
STATE_PATH = BASE_DIR / "state" / "trend_history.json"
OUT_DIR = BASE_DIR.parent / "telegram_research_dashboard" / "static" / "market_trend"

HISTORY_DAYS = 21       # 이력 보관 일수 (기준선 7일 + 신조어 판정 여유)
BASELINE_DAYS = 7       # 급증 비교 창
HISTORY_TERM_CAP = 400  # 하루치 이력에 남길 낱말 수 — 파일이 무한정 크지 않게
MIN_BASELINE = 3        # 기준선이 이 일수 미만이면 '수집 중'으로 표시하고 빈도순으로만 순위


# ── 설정 ──────────────────────────────────────────────────────────────────

def load_config(path: Path = CONFIG_PATH) -> dict:
    import yaml

    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cfg.setdefault("window_hours", 24)
    cfg.setdefault("window_anchor_kst", 6)
    cfg.setdefault("min_chars", 25)
    cfg.setdefault("min_doc_count", 3)
    cfg.setdefault("max_msgs_per_chat", 400)
    cfg.setdefault("top_terms", 25)
    cfg.setdefault("top_posts", 15)
    cfg.setdefault("excerpt_chars", 180)
    cfg.setdefault("exclude_chats", [])
    cfg.setdefault("ad_patterns", [])
    cfg.setdefault("stopwords", [])
    cfg.setdefault("aliases", {})
    return cfg


def alias_lookup(cfg: dict) -> dict[str, str]:
    """{정식명: [별칭...]} → {별칭(casefold): 정식명}. 정식명 자신도 자기로 접힌다."""
    table: dict[str, str] = {}
    for canonical, variants in (cfg.get("aliases") or {}).items():
        canonical = str(canonical)
        names = [canonical] + [str(v) for v in (variants or [])]
        for name in names:
            table[name.casefold()] = canonical
    return table


# ── A. 수집 ───────────────────────────────────────────────────────────────

def day_window(now_utc: datetime, cfg: dict) -> tuple[datetime, datetime]:
    """'전일 06:00 ~ 당일 06:00 KST' 하루 창. 언제 실행해도 같은 날짜엔 같은 창이 나온다."""
    anchor = int(cfg["window_anchor_kst"])
    now_kst = now_utc.astimezone(KST)
    end_kst = now_kst.replace(hour=anchor, minute=0, second=0, microsecond=0)
    if end_kst > now_kst:
        end_kst -= timedelta(days=1)
    start_kst = end_kst - timedelta(hours=int(cfg["window_hours"]))
    return start_kst.astimezone(timezone.utc), end_kst.astimezone(timezone.utc)


def collect_corpus(cfg: dict, start: datetime, end: datetime) -> list[adapters.Item]:
    # 어댑터의 조회 창은 '지금부터 몇 시간 전'이라 창 시작까지 닿도록 넉넉히 잡고,
    # 정확한 하루 창은 아래에서 다시 자른다.
    hours = int((datetime.now(timezone.utc) - start).total_seconds() // 3600) + 2
    source = {
        "type": "telegram_account",
        "lookback_hours": hours,
        "per_chat_limit": int(cfg["max_msgs_per_chat"]),
        "exclude_chats": cfg.get("exclude_chats") or [],
    }
    items = adapters.collect(source)
    return [item for item in items if item.published_at and start <= item.published_at < end]


AD_FALLBACK = ["무료 체험", "리딩방", "수익 보장", "선착순", "입장하기", "VIP방"]
URL_RE = re.compile(r"https?://\S+")


def clean_corpus(items: list[adapters.Item], cfg: dict) -> list[adapters.Item]:
    """광고·초단문·링크뿐인 글을 버린다. 트렌드 통계를 흐리는 소음 제거."""
    patterns = [re.compile(p, re.I) for p in (cfg.get("ad_patterns") or AD_FALLBACK)]
    min_chars = int(cfg["min_chars"])
    kept = []
    for item in items:
        text = URL_RE.sub("", item.body or "").strip()
        if len(text) < min_chars:
            continue
        if any(p.search(item.body) for p in patterns):
            continue
        kept.append(item)
    return kept


# ── B-1. 중복 접기 + 전파 수 ───────────────────────────────────────────────

def group_duplicates(items: list[adapters.Item]) -> list[dict]:
    """퍼나른 같은 글을 한 묶음으로 접는다. 접기 전에 '몇 채널이 실었나'를 센다.

    이 전파 수가 트렌드의 핵심 신호다 — 채널 하나의 긴 글보다 열 채널이 퍼나른
    한 문단이 시장 관심을 더 잘 보여준다. 판정은 source_watcher와 같은 min-hash
    (지문 5개 중 3개 이상 겹치면 같은 글)를 쓴다.
    """
    groups: list[dict] = []
    fp_index: dict[str, int] = {}
    for item in sorted(items, key=lambda i: (i.published_at or datetime.min.replace(tzinfo=timezone.utc), i.uid)):
        signs = fingerprints(item)
        votes = Counter(fp_index[s] for s in signs if s in fp_index)
        best = votes.most_common(1)
        if signs and best and best[0][1] >= min(3, len(signs)):
            group = groups[best[0][0]]
            group["channels"].add(item.origin or "?")
            # 머리말이 덧붙은 판본이 있으면 더 긴(원문에 가까운) 쪽을 대표로 남긴다.
            if len(item.body or "") > len(group["rep"].body or ""):
                group["rep"] = item
        else:
            groups.append({"rep": item, "channels": {item.origin or "?"}})
            index = len(groups) - 1
            for sign in signs:
                fp_index.setdefault(sign, index)
    for group in groups:
        group["spread"] = len(group["channels"])
    return groups


# ── B-2. 토큰화 ────────────────────────────────────────────────────────────

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z&.\-]{1,}|[가-힣]{2,}|[0-9]{6}")  # 영단어·한글·종목코드
# 한글 낱말 꼬리의 조사 제거 — 형태소 분석기 없이 쓰는 거친 휴리스틱.
# '삼성전자가'→'삼성전자', '조선은'→'조선' 정도를 맞추는 게 목적이고, 과하게 자르지
# 않도록 자른 뒤 2자 이상 남을 때만 적용한다.
JOSA = sorted(
    ["으로부터", "에서는", "에서도", "이라는", "라는", "에게", "한테", "까지", "부터", "에서",
     "으로", "라고", "이라", "보다", "마다", "조차", "마저", "와의", "과의",
     "은", "는", "이", "가", "을", "를", "에", "의", "도", "와", "과", "로", "만"],
    key=len, reverse=True,
)
ENGLISH_STOP = {"the", "and", "for", "with", "from", "this", "that", "are", "was", "has", "have", "will", "not", "you"}


def strip_josa(word: str) -> str:
    for josa in JOSA:
        if word.endswith(josa) and len(word) - len(josa) >= 2:
            return word[: -len(josa)]
    return word


def tokenize(text: str, stopwords: set[str], aliases: dict[str, str]) -> list[str]:
    """본문 → 정규화된 낱말 나열(순서 보존, bigram용). 불용어는 빈 문자열로 남겨 자리 표시."""
    tokens: list[str] = []
    for raw in TOKEN_RE.findall(URL_RE.sub("", text)):
        word = strip_josa(raw) if re.fullmatch(r"[가-힣]+", raw) else raw
        # 조사를 뗀 형태로 못 찾으면 원형으로 한 번 더 — '삼전은'처럼 별칭+조사 대비
        canonical = aliases.get(word.casefold()) or aliases.get(raw.casefold()) or word
        folded = canonical.casefold()
        if len(canonical) < 2 or folded in stopwords or folded in ENGLISH_STOP:
            tokens.append("")  # bigram이 불용어를 건너뛰어 붙지 않게 자리만 남긴다
            continue
        tokens.append(canonical)
    return tokens


def term_sets(tokens: list[str]) -> tuple[set[str], set[str]]:
    """한 글에서 등장한 낱말·두낱말 집합. 횟수가 아니라 '등장 여부'만 센다 —
    한 글에서 열 번 말한 것보다 열 글에서 한 번씩 말한 것이 트렌드다."""
    unigrams = {t for t in tokens if t}
    bigrams = {
        f"{a} {b}"
        for a, b in zip(tokens, tokens[1:])
        if a and b and a != b
    }
    return unigrams, bigrams


def count_terms(groups: list[dict], cfg: dict, stopwords: set[str], aliases: dict[str, str]) -> tuple[Counter, Counter]:
    """묶음(=중복 접은 글) 단위 문서빈도와, 전파 수 가중 빈도를 함께 센다."""
    doc_counts: Counter = Counter()
    weighted: Counter = Counter()
    for group in groups:
        tokens = tokenize(group["rep"].body or "", stopwords, aliases)
        unigrams, bigrams = term_sets(tokens)
        for term in unigrams | bigrams:
            doc_counts[term] += 1
            weighted[term] += group["spread"]
    # 소음 억제: bigram은 최소 등장 수를 넘는 것만 남긴다(우연한 이웃 조합이 대부분이라)
    min_count = int(cfg["min_doc_count"])
    for term in [t for t in doc_counts if " " in t and doc_counts[t] < min_count]:
        del doc_counts[term]
        del weighted[term]
    return doc_counts, weighted


# ── B-3. 이력·급증 ─────────────────────────────────────────────────────────

def load_history(path: Path = STATE_PATH) -> dict:
    if not path.exists():
        return {"version": 1, "days": {}}
    history = json.loads(path.read_text(encoding="utf-8"))
    history.setdefault("days", {})
    return history


def save_history(history: dict, path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(history, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def remember_day(history: dict, day: str, doc_counts: Counter, total_docs: int) -> None:
    top = dict(doc_counts.most_common(HISTORY_TERM_CAP))
    history["days"][day] = {"docs": total_docs, "terms": top}
    for stale in sorted(history["days"])[:-HISTORY_DAYS]:
        del history["days"][stale]


def spike_scores(doc_counts: Counter, total_docs: int, history: dict, day: str, cfg: dict) -> list[dict]:
    """오늘 문서점유율을 최근 7일 기준선과 비교해 급증 배수를 계산한다.

    절대 빈도가 아니라 '평소 대비'가 트렌드다 — '시장'은 매일 수백 번 나오므로
    기준선 비교가 자동으로 눌러 준다(불용어 사전을 무한정 키울 필요가 없는 이유).
    이력이 MIN_BASELINE일 미만이면 배수 없이 빈도순으로만 순위를 매긴다(콜드 스타트).
    """
    past = [entry for stamp, entry in sorted(history["days"].items()) if stamp < day][-BASELINE_DAYS:]
    min_count = int(cfg["min_doc_count"])
    baseline_ready = len(past) >= MIN_BASELINE

    rows: list[dict] = []
    for term, count in doc_counts.items():
        if count < min_count:
            continue
        row = {"term": term, "count": count, "burst": None, "base_daily": None, "new": None}
        if baseline_ready:
            base_hits = sum(entry["terms"].get(term, 0) for entry in past)
            base_docs = sum(entry["docs"] for entry in past) or 1
            # 라플라스 평활 — 기준선 0인 신조어가 무한대가 되지 않게 하되 크게 튀게 둔다
            base_share = (base_hits + 0.5) / (base_docs + 1)
            today_share = count / max(total_docs, 1)
            row["burst"] = min(today_share / base_share, 99.0)
            row["base_daily"] = round(base_hits / max(len(past), 1), 1)
            row["new"] = base_hits <= 1
        rows.append(row)

    if baseline_ready:
        rows.sort(key=lambda r: math.sqrt(r["count"]) * math.log1p(r["burst"]), reverse=True)
        # 평소에도 늘 나오는 낱말(배수 ≈ 1 이하)은 트렌드가 아니다
        rows = [r for r in rows if r["burst"] >= 1.5]
    else:
        rows.sort(key=lambda r: r["count"], reverse=True)
    return rows[: int(cfg["top_terms"])]


# ── B-4. 발췌 ──────────────────────────────────────────────────────────────

def clip(value: str, limit: int) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[:limit].rstrip() + "…"


def term_variants(term: str, cfg: dict) -> list[str]:
    """정식명으로 접힌 낱말은 별칭까지 함께 찾아야 원문에서 발췌가 잡힌다."""
    variants = [term]
    for canonical, alias_list in (cfg.get("aliases") or {}).items():
        if str(canonical) == term:
            variants += [str(v) for v in (alias_list or [])]
    return variants


def excerpts_for(term: str, groups: list[dict], cfg: dict, limit: int = 3) -> list[dict]:
    """낱말이 걸린 묶음을 전파 수 순으로 골라, 걸린 줄만 잘라 온다."""
    needles = [re.compile(re.escape(v), re.I) for v in term_variants(term, cfg)]
    words = term.split(" ")  # bigram은 두 낱말이 같은 글에 있으면 인정
    picked = []
    for group in sorted(groups, key=lambda g: (-g["spread"], -(len(g["rep"].body or "")))):
        body = group["rep"].body or ""
        hit_line = None
        for line in body.splitlines():
            if any(n.search(line) for n in needles) or (len(words) > 1 and all(w.casefold() in line.casefold() for w in words)):
                hit_line = line.strip()
                break
        if hit_line is None and len(words) > 1 and all(w.casefold() in body.casefold() for w in words):
            hit_line = body.strip().splitlines()[0]
        if hit_line is None:
            continue
        picked.append({
            "channel": group["rep"].origin or "?",
            "spread": group["spread"],
            "quote": clip(hit_line, int(cfg["excerpt_chars"])),
            "url": group["rep"].url,
        })
        if len(picked) >= limit:
            break
    return picked


def top_spread_posts(groups: list[dict], cfg: dict) -> list[dict]:
    """여러 채널이 퍼나른 글 상위 — 그 자체가 '오늘 시장이 돌려본 글' 목록이다."""
    ranked = sorted(groups, key=lambda g: (-g["spread"], -(len(g["rep"].body or ""))))
    posts = []
    for group in ranked[: int(cfg["top_posts"])]:
        if group["spread"] < 2 and len(posts) >= 5:
            break  # 전파가 없는 글은 상위 몇 개만 채우고 만다
        posts.append({
            "channels": group["spread"],
            "channel": group["rep"].origin or "?",
            "head": clip(group["rep"].body or "", int(cfg["excerpt_chars"])),
            "url": group["rep"].url,
            "time_kst": group["rep"].published_at.astimezone(KST).strftime("%m-%d %H:%M")
            if group["rep"].published_at else "",
        })
    return posts


# ── C. Gemini 합성 ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = """너는 한국 주식시장을 다루는 리서치 어시스턴트다.
입력은 사용자가 구독한 텔레그램 리서치·뉴스 채널들의 지난 하루치 글에서 계량으로 추출한
신호다: 급증 키워드(평소 7일 대비 배수), 여러 채널이 퍼나른 글, 대표 발췌.

이 신호를 묶어 '어제~오늘 시장의 테마(내러티브)'를 3~6개 정리하라. 규칙:
- 입력에 있는 사실만 쓴다. 입력에 없는 사건·수치를 지어내지 않는다.
- 급증 키워드를 기계적으로 나열하지 말고, 서로 연결되는 것끼리 하나의 테마로 묶는다.
- 테마 이름은 짧고 구체적으로(예: "조선 — 미 함정 MRO 기대 재점화").
- narrative는 1~3문장. 무엇이, 왜 지금, 시장이 어떻게 반응하는지.
- status: 기준선 대비 처음 보이면 "new", 이어지는 얘기면 "ongoing".
- strength: 신호 강도 1~5 (전파 수·급증 배수·관련 키워드 수 기준).
- evidence에는 입력 발췌에서 고른 근거를 채널 이름과 함께 1~3개.
- 광고·리딩방 홍보로 보이는 신호는 무시한다.

반드시 아래 형태의 JSON만 출력한다(설명·마크다운 금지):
{"one_liner": "오늘 시장 관심 한 줄 요약",
 "themes": [{"name": "...", "narrative": "...", "status": "new|ongoing",
             "strength": 3, "keywords": ["..."],
             "evidence": [{"channel": "...", "quote": "..."}]}]}"""


def build_llm_input(day: str, stats: dict, spikes: list[dict], posts: list[dict], term_excerpts: dict) -> str:
    lines = [f"날짜: {day}", f"코퍼스: 채널 {stats['channels']}개, 글 {stats['messages']}건(중복 접은 뒤 {stats['groups']}건)", ""]
    lines.append("## 급증 키워드 (오늘 언급 글 수 · 7일 하루평균 · 배수 · 신규 여부)")
    for row in spikes:
        burst = f"{row['burst']:.1f}배" if row["burst"] is not None else "기준선 수집 중"
        flag = " [신규]" if row.get("new") else ""
        lines.append(f"- {row['term']}: {row['count']}건 · 평소 {row['base_daily'] if row['base_daily'] is not None else '?'}건 · {burst}{flag}")
        for ex in term_excerpts.get(row["term"], []):
            lines.append(f"    · ({ex['channel']}, {ex['spread']}개 채널) \"{ex['quote']}\"")
    lines.append("")
    lines.append("## 여러 채널이 퍼나른 글 (전파 수 순)")
    for post in posts:
        lines.append(f"- [{post['channels']}개 채널] ({post['channel']}) \"{post['head']}\"")
    return "\n".join(lines)


def synthesize(day: str, llm_input: str) -> tuple[dict, str]:
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client()  # GEMINI_API_KEY 환경변수 사용
    config = genai_types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=0.4,
        max_output_tokens=8192,
        response_mime_type="application/json",
    )
    # 방산 브리핑과 같은 폴백 정책 — 무료 티어 쿼터로 데일리가 끊기지 않게
    primary = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    models = list(dict.fromkeys([primary, "gemini-flash-lite-latest"]))
    import time as _time

    for model in models:
        for attempt in range(2):
            try:
                response = client.models.generate_content(model=model, contents=llm_input, config=config)
                text = (response.text or "").strip()
                if text:
                    usage = getattr(response, "usage_metadata", None)
                    if usage:
                        print(f"[Gemini:{model}] in={usage.prompt_token_count} out={usage.candidates_token_count}")
                    return json.loads(text), model
            except json.JSONDecodeError as exc:
                print(f"[Gemini:{model}] JSON 파싱 실패(시도 {attempt + 1}): {exc}", file=sys.stderr)
            except Exception as exc:
                print(f"[Gemini:{model}] 오류(시도 {attempt + 1}): {exc}", file=sys.stderr)
            _time.sleep(30 * (attempt + 1))
    raise RuntimeError("Gemini 호출 모두 실패 — --no-llm으로 계량 신호만이라도 낼 수 있습니다")


# ── 산출물 ─────────────────────────────────────────────────────────────────

WEEKDAY_KO = "월화수목금토일"


def render_markdown(day: str, result: dict | None, spikes: list[dict], posts: list[dict],
                    stats: dict, meta: dict) -> str:
    date = datetime.strptime(day, "%Y-%m-%d")
    lines = [f"# 시장관심.내러티브 — {day} ({WEEKDAY_KO[date.weekday()]})", ""]
    if result and result.get("one_liner"):
        lines += [f"> {result['one_liner']}", ""]
    lines += [
        f"_창 {meta['window']} · 채널 {stats['channels']}개 · 글 {stats['messages']}건"
        f"(중복 접은 뒤 {stats['groups']}건) · {meta['engine']}_",
        "",
    ]

    for i, theme in enumerate((result or {}).get("themes") or [], start=1):
        strength = int(theme.get("strength") or 0)
        badge = "🆕" if theme.get("status") == "new" else "〰️"
        lines.append(f"## {i}. {theme.get('name', '(이름 없음)')}  {badge} {'●' * strength}{'○' * max(0, 5 - strength)}")
        if theme.get("narrative"):
            lines += ["", theme["narrative"]]
        if theme.get("keywords"):
            lines += ["", "- 관련: " + " · ".join(str(k) for k in theme["keywords"])]
        for ev in theme.get("evidence") or []:
            lines.append(f"- ({ev.get('channel', '?')}) “{ev.get('quote', '')}”")
        lines.append("")

    lines += ["## 부록 — 계량 신호", "", "### 급증 키워드", "",
              "| 키워드 | 오늘 | 평소(7일 평균) | 배수 | |", "|---|---|---|---|---|"]
    for row in spikes:
        burst = f"{row['burst']:.1f}×" if row["burst"] is not None else "—"
        base = row["base_daily"] if row["base_daily"] is not None else "—"
        flag = "🆕" if row.get("new") else ""
        lines.append(f"| {row['term']} | {row['count']} | {base} | {burst} | {flag} |")
    if spikes and spikes[0]["burst"] is None:
        lines += ["", f"_기준선 수집 중 — 이력이 {MIN_BASELINE}일 쌓이면 '평소 대비 배수'가 나온다._"]

    lines += ["", "### 여러 채널이 퍼나른 글", ""]
    for post in posts:
        link = f" [원문]({post['url']})" if post.get("url") else ""
        lines.append(f"- **[{post['channels']}]** ({post['channel']} · {post['time_kst']}) {post['head']}{link}")
    return "\n".join(lines) + "\n"


def write_outputs(day: str, markdown: str, payload: dict, out_dir: Path = OUT_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{day}.md").write_text(markdown, encoding="utf-8")
    (out_dir / "latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


# ── 코퍼스 저장/복원 (디버깅) ──────────────────────────────────────────────

def dump_corpus(items: list[adapters.Item], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps({
                "uid": item.uid, "origin": item.origin, "url": item.url, "body": item.body,
                "published_at": item.published_at.isoformat() if item.published_at else None,
            }, ensure_ascii=False) + "\n")


def read_corpus(path: Path) -> list[adapters.Item]:
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        items.append(adapters.Item(
            uid=raw["uid"], title=adapters.first_line(raw.get("body") or ""), url=raw.get("url") or "",
            body=raw.get("body") or "", origin=raw.get("origin"),
            published_at=datetime.fromisoformat(raw["published_at"]) if raw.get("published_at") else None,
        ))
    return items


# ── 실행 ──────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description="구독 채널 하루치에서 시장 테마·내러티브를 뽑는다")
    cli.add_argument("--check", action="store_true", help="수집·계량까지만 — 토큰·저장 없음")
    cli.add_argument("--no-llm", action="store_true", help="Gemini 없이 계량 신호만으로 저장")
    cli.add_argument("--dry-run", action="store_true", help="파일 저장 없이 결과 출력만")
    cli.add_argument("--corpus", type=Path, help="수집 대신 jsonl 파일에서 읽는다(디버깅)")
    cli.add_argument("--save-corpus", type=Path, help="수집분을 jsonl로 저장(디버깅)")
    args = cli.parse_args(argv)

    cfg = load_config()
    now = datetime.now(timezone.utc)
    start, end = day_window(now, cfg)
    day = end.astimezone(KST).strftime("%Y-%m-%d")
    window_label = (f"{start.astimezone(KST):%m-%d %H:%M}~{end.astimezone(KST):%m-%d %H:%M} KST")
    print(f"시장관심.내러티브 {day} · 창 {window_label}")

    # A. 수집
    if args.corpus:
        raw_items = read_corpus(args.corpus)
        raw_items = [i for i in raw_items if i.published_at and start <= i.published_at < end] or raw_items
    else:
        raw_items = collect_corpus(cfg, start, end)
    if args.save_corpus:
        dump_corpus(raw_items, args.save_corpus)
        print(f"코퍼스 저장: {args.save_corpus} ({len(raw_items)}건)")

    items = clean_corpus(raw_items, cfg)
    if not items:
        print("창 안에 글이 없습니다 — 세션·구독 채널·창 설정을 확인하세요", file=sys.stderr)
        return 1

    # B. 계량
    groups = group_duplicates(items)
    stats = {
        "channels": len({i.origin for i in items}),
        "messages": len(items),
        "groups": len(groups),
    }
    print(f"채널 {stats['channels']}개 · 글 {stats['messages']}건 → 중복 접은 뒤 {stats['groups']}건")

    stopwords = {str(w).casefold() for w in (cfg.get("stopwords") or [])}
    aliases = alias_lookup(cfg)
    doc_counts, weighted = count_terms(groups, cfg, stopwords, aliases)

    history = load_history()
    spikes = spike_scores(doc_counts, len(groups), history, day, cfg)
    posts = top_spread_posts(groups, cfg)
    term_excerpts = {row["term"]: excerpts_for(row["term"], groups, cfg) for row in spikes}

    if args.check:
        print("\n급증 키워드 상위:")
        for row in spikes[:15]:
            burst = f"{row['burst']:.1f}×" if row["burst"] is not None else "기준선 수집 중"
            print(f"  {row['term']:<20} {row['count']:>3}건  {burst}{'  🆕' if row.get('new') else ''}")
        print("\n전파 상위 글:")
        for post in posts[:8]:
            print(f"  [{post['channels']}] ({post['channel']}) {post['head'][:70]}")
        return 0

    # C. 합성
    result, engine = None, "계량 신호만(--no-llm)"
    if not args.no_llm:
        llm_input = build_llm_input(day, stats, spikes, posts, term_excerpts)
        print(f"Gemini 입력 {len(llm_input):,}자")
        result, model = synthesize(day, llm_input)
        engine = f"Gemini({model})"

    meta = {"window": window_label, "engine": engine, "generated_at": now.astimezone(KST).isoformat(timespec="minutes")}
    markdown = render_markdown(day, result, spikes, posts, stats, meta)
    payload = {
        "date": day, "meta": meta, "stats": stats,
        "one_liner": (result or {}).get("one_liner"),
        "themes": (result or {}).get("themes") or [],
        "signals": {"spikes": spikes, "top_posts": posts},
    }

    if args.dry_run:
        print("\n" + markdown)
        return 0

    write_outputs(day, markdown, payload)
    remember_day(history, day, doc_counts, len(groups))
    save_history(history)
    print(f"저장 완료: {OUT_DIR / (day + '.md')} · latest.json · 이력 {len(history['days'])}일")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
