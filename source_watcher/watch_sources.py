"""등록된 소스를 훑어 새 글만 텔레그램으로 밀어내는 감시 봇.

소스마다 스크립트를 만들지 않는다. sources.yml에 몇 줄 추가하면 그것으로 끝이다.
새 소스를 붙이는 순서는 README를 볼 것.

    python watch_sources.py                 # 수집 → 새 글 발송 → 상태 저장
    python watch_sources.py --check         # 연결만 점검(발송·저장 없음)
    python watch_sources.py --dry-run       # 무엇이 나갈지 출력만
    python watch_sources.py --only mer      # 특정 소스만
    python watch_sources.py --seed          # 지금 글을 전부 '읽음' 처리(발송 없음)
    python watch_sources.py --test          # 발송 경로 점검 — 최신 글 1건 시험 발송

상태 파일(state/seen.json)이 중복 발송을 막는다. Actions 러너는 매번 새 컨테이너라
이 파일을 저장소에 커밋해 두어야 다음 실행이 무엇을 이미 보냈는지 안다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import adapters
import notify

BASE_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = BASE_DIR / "sources.yml"
STATE_PATH = BASE_DIR / "state" / "seen.json"
KST = timezone(timedelta(hours=9))

# 소스당 상태 파일에 남길 uid 수. 파일이 무한정 커지지 않게 하되,
# lookback 창보다 훨씬 넉넉해야 오래된 글이 '새 글'로 되살아나지 않는다.
SEEN_CAP = 300

# 채널 묶음(dedupe_scope)당 기억할 내용 지문 수. 글 하나가 지문 5개를 쓰므로
# 1500이면 최근 300건을 덮는다 — 채널 수십 개가 하루치를 퍼나르는 양보다 넉넉하다.
SCOPE_CAP = 1500

DEFAULTS = {
    "enabled": True,
    "max_per_run": 5,      # 한 번에 밀어낼 상한. 피드가 통째로 갱신돼도 폭주하지 않게.
    "lookback_hours": 48,  # 이보다 오래된 글은 미발송분이어도 보내지 않는다.
    "excerpt_chars": 600,
    "push": None,          # full | excerpt | hit (None이면 종류별 기본값)
    "match": None,         # 제목+본문에 걸 정규식(대소문자 무시)
    "exclude": None,
    "match_any": None,     # 낱말 목록(정규식 아님). 하나라도 걸리면 통과
    "exclude_any": None,   # 낱말 목록. 하나라도 걸리면 버림
    "dedupe_scope": None,  # 같은 값을 가진 소스끼리 내용 중복을 걸러낸다
    "hit_chars": 300,      # push: hit 에서 걸린 문장 한 줄의 길이 상한
    "max_hits": 3,         # push: hit 에서 보여줄 문장 수
    "route": None,         # 발송 봇 분기 — <ROUTE>_TELEGRAM_BOT_TOKEN/_CHAT_ID 로 보낸다
    "tags": [],
}


# ── 레지스트리 ─────────────────────────────────────────────────────────────

def expand_channels(entry: dict) -> list[dict]:
    """`channels:` 목록 하나를 채널별 소스로 펼친다.

    조선처럼 채널 수십 개를 같은 조건으로 훑을 때, 같은 블록을 수십 번 복사하지 않게
    하려는 것이다. 필터·태그·발송형식은 묶음에 한 번만 쓰고 채널만 줄줄이 나열한다.
    상태(seen)는 채널별로 갈라야 한 채널의 사고가 다른 채널로 번지지 않으므로,
    key는 `<묶음key>__<채널아이디>`로 자동 생성한다.
    """
    channels = entry.get("channels")
    if channels is None:
        return [entry]
    if not isinstance(channels, list):
        raise ValueError(f"channels는 목록이어야 합니다: {entry.get('key')!r}")

    parent = entry.get("key")
    if not parent:
        raise ValueError(f"key 없는 소스가 있습니다: {entry!r}")

    base = {name: value for name, value in entry.items() if name != "channels"}
    base.setdefault("type", "telegram")

    expanded = []
    for raw in channels:
        spec = {"channel": raw} if isinstance(raw, str) else dict(raw or {})
        channel = spec.pop("channel", None) or spec.pop("id", None) or spec.pop("url", None)
        if not channel:
            raise ValueError(f"[{parent}] channels 항목에 channel이 없습니다: {raw!r}")
        handle = adapters.normalize_channel(str(channel))
        source = {**base, **spec, "channel": channel}
        source["key"] = f"{parent}__{handle.casefold()}"
        source["name"] = spec.get("name") or handle
        # 묶음 안의 채널끼리는 같은 글을 퍼나르는 일이 잦다. 따로 끄지 않는 한 함께 중복을 건다.
        source.setdefault("dedupe_scope", parent)
        expanded.append(source)
    return expanded


def load_registry(path: Path = REGISTRY_PATH) -> list[dict]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - 환경 의존
        raise RuntimeError("PyYAML이 필요합니다: pip install pyyaml") from exc

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    defaults = {**DEFAULTS, **(raw.get("defaults") or {})}

    sources = []
    keys = set()
    for entry in raw.get("sources") or []:
        for expanded in expand_channels(entry):
            source = {**defaults, **expanded}
            key = source.get("key")
            if not key:
                raise ValueError(f"key 없는 소스가 있습니다: {entry!r}")
            if key in keys:
                raise ValueError(f"key가 중복됩니다: {key!r} (상태 파일이 섞입니다)")
            keys.add(key)
            source.setdefault("name", key)
            sources.append(source)
    return sources


# ── 상태 ──────────────────────────────────────────────────────────────────

def load_state(path: Path = STATE_PATH) -> dict:
    if not path.exists():
        return {"version": 1, "sources": {}}
    state = json.loads(path.read_text(encoding="utf-8"))
    state.setdefault("sources", {})
    return state


def save_state(state: dict, path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def remember(state: dict, key: str, uids: list[str], now: datetime, *, pushed: bool) -> None:
    entry = state["sources"].setdefault(key, {"seen": []})
    seen = [uid for uid in entry.get("seen", []) if uid not in set(uids)]
    entry["seen"] = (seen + uids)[-SEEN_CAP:]
    entry["last_run"] = now.isoformat()
    if pushed:
        entry["last_pushed"] = now.isoformat()


# ── 선별 ──────────────────────────────────────────────────────────────────

def keyword_groups(value) -> list[tuple[str, list[str]]]:
    """match_any/exclude_any를 (표시이름, 낱말들) 목록으로 정규화한다.

    두 가지 형태를 받는다. 낱말만 죽 나열하거나(표시이름 = 낱말 그 자체),
    회사 이름 아래에 별칭·종목코드를 묶거나. 뒤쪽이 조선 감시에 쓰는 형태다.

        match_any: [신조선가, 클락슨]
        match_any:
          한화오션: [한화오션, 대우조선해양, "042660"]
    """
    if not value:
        return []
    if isinstance(value, str):
        value = [value]
    if isinstance(value, dict):
        groups = []
        for label, terms in value.items():
            if terms is None:
                terms = [label]
            elif not isinstance(terms, (list, tuple)):
                terms = [terms]
            words = [str(term).strip() for term in terms if str(term).strip()]
            if words:
                groups.append((str(label), words))
        return groups
    return [(str(term).strip(), [str(term).strip()]) for term in value if str(term).strip()]


def any_pattern(value) -> str | None:
    """낱말 목록을 한 개의 OR 정규식으로. 낱말은 정규식이 아니라 글자 그대로 다룬다."""
    terms = [term for _, words in keyword_groups(value) for term in words]
    return "|".join(re.escape(term) for term in terms) or None


def hits(source: dict, item: adapters.Item) -> list[tuple[str, str]]:
    """match_any 중 실제로 걸린 (표시이름, 낱말)을 등장 순서로 돌려준다.

    알림 머리에 '어느 회사 때문에 왔는지'를 찍고, 본문에서 걸린 문장을 뽑는 데 쓴다.
    """
    haystack = item.text_for_match()
    found: list[tuple[int, str, str]] = []
    for label, words in keyword_groups(source.get("match_any")):
        for term in words:
            spot = re.search(re.escape(term), haystack, re.I)
            if spot:
                found.append((spot.start(), label, term))
    found.sort()

    seen: set[tuple[str, str]] = set()
    ordered: list[tuple[str, str]] = []
    for _, label, term in found:
        mark = (label, term.casefold())
        if mark in seen:
            continue
        seen.add(mark)
        ordered.append((label, term))
    return ordered


def keep(source: dict, item: adapters.Item) -> bool:
    """소스에 걸린 match/match_any(통과)와 exclude/exclude_any(차단)로 글을 거른다.

    한 채널이 여러 자료를 섞어 뿌릴 때(예: 데일리 + 종목 리포트) 원하는 것만 받기 위한 것.
    통과 조건이 둘 다 있으면 **하나만 걸려도** 통과한다(정규식이나 낱말이나 같은 자격).
    """
    haystack = item.text_for_match()
    passes = [rule for rule in (source.get("match"), any_pattern(source.get("match_any"))) if rule]
    if passes and not any(re.search(rule, haystack, re.I | re.S) for rule in passes):
        return False
    blocks = [rule for rule in (source.get("exclude"), any_pattern(source.get("exclude_any"))) if rule]
    if any(re.search(rule, haystack, re.I | re.S) for rule in blocks):
        return False
    return True


# ── 내용 중복 ──────────────────────────────────────────────────────────────
#
# uid(채널:글번호)로는 채널 A와 채널 B가 같은 글을 퍼나른 것을 구분하지 못한다.
# 조선 채널 수십 개를 붙이면 같은 리포트 요약이 하루에 대여섯 통씩 온다. 그래서
# 본문 내용 자체로 지문을 떠서 묶음(dedupe_scope) 단위로 한 번만 내보낸다.

FP_URL_RE = re.compile(r"https?://\S+")
FP_NOISE_RE = re.compile(r"[^0-9a-z가-힣]+")
FP_SHINGLE = 20
FP_COUNT = 5
FP_OVERLAP = 3


def fingerprints(item: adapters.Item) -> list[str]:
    """본문에서 지문 5개를 뜬다. 3개 이상 겹치면 같은 글로 본다.

    글 전체를 통으로 해싱하면 채널이 머리말 한 줄('[○○증권 조선]')만 붙여도 다른 글이
    되어 버린다. 그래서 링크·공백·문장부호를 걷어낸 본문에서 20자짜리 조각을 전부 뜬 뒤
    해시가 가장 작은 5개를 지문으로 삼는다(min-hash). 조각 선택이 내용에만 달려 있어
    머리말이 붙어 위치가 밀려도 같은 지문이 나온다. 과반(3개)이 겹칠 때만 중복으로
    치므로, 상투적인 고지 문구 한 줄이 우연히 겹치는 것으로는 진짜 새 글이 사라지지
    않는다.
    """
    text = FP_NOISE_RE.sub("", FP_URL_RE.sub("", item.body or "").casefold())
    if not text:
        return []

    def digest(chunk: str) -> str:
        return hashlib.sha1(chunk.encode("utf-8")).hexdigest()[:16]

    if len(text) <= FP_SHINGLE:
        return [digest(text)]
    shingles = {text[i:i + FP_SHINGLE] for i in range(len(text) - FP_SHINGLE + 1)}
    return sorted(digest(chunk) for chunk in shingles)[:FP_COUNT]


def scope_marks(state: dict, scope: str) -> list[str]:
    return state.setdefault("scopes", {}).setdefault(scope, {}).setdefault("seen", [])


def drop_duplicates(source: dict, items: list[adapters.Item], state: dict) -> tuple[list[adapters.Item], int]:
    """같은 묶음의 다른 채널이 이미 내보낸 글을 걸러낸다. (남은 글, 걸러낸 수)"""
    scope = source.get("dedupe_scope")
    if not scope:
        return items, 0

    marks = scope_marks(state, scope)
    known = set(marks)
    kept: list[adapters.Item] = []
    dropped = 0
    for item in items:
        signs = fingerprints(item)
        overlap = sum(1 for sign in signs if sign in known)
        if signs and overlap >= min(FP_OVERLAP, len(signs)):
            dropped += 1
            continue
        kept.append(item)
        known.update(signs)
        marks.extend(signs)
    del marks[:-SCOPE_CAP]  # 최근 것만 남긴다
    return kept, dropped


def within_lookback(source: dict, item: adapters.Item, now: datetime) -> bool:
    hours = source.get("lookback_hours") or 0
    if hours <= 0 or item.published_at is None:
        return True
    return item.published_at >= now - timedelta(hours=hours)


def select(source: dict, items: list[adapters.Item], state: dict, now: datetime) -> list[adapters.Item]:
    """발송 후보를 오래된 것 → 최신 순으로 돌려준다(읽는 순서가 자연스럽도록)."""
    seen = set(state["sources"].get(source["key"], {}).get("seen", []))
    fresh = [
        item
        for item in items
        if item.uid not in seen and keep(source, item) and within_lookback(source, item, now)
    ]
    fresh.sort(key=lambda item: (item.published_at or now, item.uid))
    return fresh


# ── 메시지 ────────────────────────────────────────────────────────────────

def clip(value: str, limit: int) -> str:
    value = value.strip()
    if limit <= 0 or len(value) <= limit:
        return value
    cut = value.rfind("\n", 0, limit)
    if cut < limit // 2:
        cut = value.rfind(" ", 0, limit)
    if cut <= 0:
        cut = limit
    return value[:cut].rstrip() + " …"


def route_credentials(source: dict) -> tuple[str | None, str | None]:
    """route가 걸린 소스의 봇 토큰·chat_id를 환경변수에서 찾는다.

    조선 알림(@gs_sb_bot)처럼 기존 방과 다른 봇으로 갈라 보낼 때 쓴다. `route: ship`이면
    SHIP_TELEGRAM_BOT_TOKEN / SHIP_TELEGRAM_CHAT_ID 를 읽는다. 시크릿이 아직 비어
    있으면 기본 봇으로 대신 보낸다 — 알림이 조용히 사라지는 것보다 낫다.
    """
    route = source.get("route")
    if not route:
        return None, None
    prefix = re.sub(r"[^0-9A-Za-z]+", "_", str(route)).upper().strip("_")
    token = os.environ.get(f"{prefix}_TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get(f"{prefix}_TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print(f"  ⚠ {prefix}_TELEGRAM_BOT_TOKEN/_CHAT_ID가 비어 기본 봇으로 보냅니다", file=sys.stderr)
        return None, None
    return token, chat_id


def push_mode(source: dict) -> str:
    mode = source.get("push")
    if mode:
        return mode
    # 텔레그램 글은 그 자체가 완성된 본문이라 통째로, RSS는 요약 + 원문 링크가 낫다.
    return "full" if str(source.get("type", "")).startswith("telegram") else "excerpt"


def hit_lines(body: str, terms: list[str], limit: int, max_hits: int) -> list[str]:
    """낱말이 걸린 줄만 뽑아 온다. 없으면 본문 앞머리로 대신한다.

    조선 코멘트는 대개 긴 데일리 안에 두어 줄로 섞여 있다. 전문을 통째로 보내면
    무엇 때문에 알림이 왔는지 찾느라 스크롤해야 하므로 걸린 줄만 보여준다.
    """
    picked: list[str] = []
    for line in (body or "").splitlines():
        line = line.strip()
        if not line or line in picked:
            continue
        if any(re.search(re.escape(term), line, re.I) for term in terms):
            picked.append(line)
        if len(picked) >= max_hits:
            break
    if not picked:
        head = clip(body or "", limit)
        return [head] if head else []
    return [clip(line, limit) for line in picked]


def highlight(line: str, terms: list[str]) -> str:
    """이스케이프한 줄에서 걸린 낱말만 굵게. 이스케이프 뒤에 칠해야 태그가 깨지지 않는다."""
    marked = notify.escape(line)
    for term in sorted(set(terms), key=len, reverse=True):
        needle = notify.escape(term)
        if not needle:
            continue
        marked = re.sub(f"({re.escape(needle)})", r"<b>\1</b>", marked, flags=re.I)
    return marked


def render(source: dict, item: adapters.Item) -> str:
    escape = notify.escape
    tags = source.get("tags") or []
    tag_line = " ".join(f"#{escape(str(tag))}" for tag in tags)
    mode = push_mode(source)
    # 한 소스가 여러 방을 훑을 때(telegram_account)는 소스 이름이 아니라 방 이름을 찍는다.
    label = item.origin or source["name"]

    if mode == "hit":
        found = hits(source, item)
        companies: list[str] = []
        for name, _ in found:
            if name not in companies:
                companies.append(name)
        terms = [term for _, term in found]

        head = "🕊️전보) " + (" · ".join(f"<b>{escape(name)}</b>" for name in companies) or "<b>키워드</b>")
        head += f"\n📡 {escape(label)}"
        if tag_line:
            head += f"  {tag_line}"
        if item.published_at:
            head += f"\n🕒 {item.published_at.astimezone(KST):%Y-%m-%d %H:%M} KST"

        lines = hit_lines(item.body, terms, source.get("hit_chars") or 300, source.get("max_hits") or 3)
        body = "\n⋯\n".join(highlight(line, terms) for line in lines)
    else:
        head = f"📌 <b>{escape(label)}</b>"
        if tag_line:
            head += f"  {tag_line}"
        if item.published_at:
            head += f"\n🕒 {item.published_at.astimezone(KST):%Y-%m-%d %H:%M} KST"

        if mode == "full":
            # 텔레그램 글은 제목을 본문 첫 줄에서 만든 것이라 제목 줄을 따로 붙이면 중복된다.
            # 길면 notify.split_chunks가 나눠 보내므로 여기서 자르지 않는다.
            body = escape(item.body)
        else:
            excerpt = clip(item.body, source.get("excerpt_chars") or 600)
            body = f"<b>{escape(item.title)}</b>"
            if excerpt:
                body += f"\n\n{escape(excerpt)}"

    parts = [head, body]
    if item.url:
        parts.append(f'🔗 <a href="{escape(item.url)}">원문 보기</a>')
    return "\n\n".join(part for part in parts if part.strip())


# ── 실행 ──────────────────────────────────────────────────────────────────

def run_source(source: dict, state: dict, now: datetime, args) -> int:
    label = f"[{source['key']}] {source['name']}"
    try:
        items = adapters.collect(source)
    except Exception as exc:  # 한 소스가 죽어도 나머지는 계속 돈다
        print(f"{label} ✗ 수집 실패: {exc}", file=sys.stderr)
        return 0

    print(f"{label} · {len(items)}건 수집")
    if args.check:
        # 필터가 전부 걸러내면 발송이 0건인데 로그만 봐서는 '수집 실패'와 구분이 안 된다.
        # 통과 건수를 같이 찍어 match/exclude를 손볼지 바로 판단할 수 있게 한다.
        kept = [item for item in items if keep(source, item)]
        filtered = any(source.get(rule) for rule in ("match", "exclude", "match_any", "exclude_any"))
        if filtered:
            print(f"  · 필터 통과 {len(kept)}/{len(items)}건")
            if items and not kept:
                print("  ⚠ 전부 걸러졌습니다 — sources.yml의 match/exclude를 확인하세요.")
        for item in (kept or items)[:3]:
            stamp = f"{item.published_at.astimezone(KST):%m-%d %H:%M}" if item.published_at else "날짜없음"
            labels = sorted({label for label, _ in hits(source, item)})
            mark = f" [{', '.join(labels)}]" if labels else ""
            print(f"    - {stamp} | {item.title[:60]}{mark}")
        return 0

    if args.test:
        # 발송 경로(토큰·chat_id·렌더링) 점검용. 새 글이 올라올 때까지 기다리지 않고
        # 최신 글 1건을 그대로 보낸다. 상태는 건드리지 않으므로 진짜 새 글은 나중에 또 온다.
        candidates = [item for item in items if keep(source, item)]
        if not candidates:
            print("  · 시험 발송할 글이 없습니다(필터 통과 0건)")
            return 0
        newest = max(candidates, key=lambda item: (item.published_at or now, item.uid))
        token, chat_id = route_credentials(source)
        notify.send(render(source, newest), token=token, chat_id=chat_id)
        print(f"  · [시험발송] {newest.title[:70]}")
        return 1

    known = source["key"] in state["sources"]
    if not known and not args.seed:
        # 첫 실행에서 피드 전체를 쏘면 수십 통이 한꺼번에 온다. 읽음 처리만 하고 다음 글부터 보낸다.
        remember(state, source["key"], [item.uid for item in items], now, pushed=False)
        print(f"  · 첫 실행 — {len(items)}건 읽음 처리만. 다음 글부터 발송합니다.")
        return 0

    candidates = select(source, items, state, now)
    if args.seed:
        remember(state, source["key"], [item.uid for item in items], now, pushed=False)
        print(f"  · seed — {len(items)}건 읽음 처리")
        return 0
    if not candidates:
        remember(state, source["key"], [], now, pushed=False)
        print("  · 새 글 없음")
        return 0

    fresh, duplicated = drop_duplicates(source, candidates, state)
    if duplicated:
        print(f"  · 다른 채널이 이미 보낸 같은 글 {duplicated}건 건너뜀")
    if not fresh:
        # 중복이라 안 보낸 글도 읽음 처리한다. 그러지 않으면 매 실행마다 다시 걸러야 한다.
        remember(state, source["key"], [item.uid for item in candidates], now, pushed=False)
        print("  · 보낼 새 글 없음")
        return 0

    limit = args.max if args.max is not None else (source.get("max_per_run") or 0)
    to_send = fresh[-limit:] if limit > 0 else fresh
    if len(to_send) < len(fresh):
        print(f"  · 새 글 {len(fresh)}건 중 최신 {len(to_send)}건만 발송(max_per_run) — 나머지는 읽음 처리")

    sent = 0
    token, chat_id = route_credentials(source) if not args.dry_run else (None, None)
    for item in to_send:
        if args.dry_run:
            print(f"  · [모의] {item.title[:70]}  {item.url}")
            sent += 1
            continue
        notify.send(render(source, item), token=token, chat_id=chat_id)
        print(f"  · 발송 {item.title[:70]}")
        sent += 1

    if not args.dry_run:
        # 상한에 걸려 못 보낸 글도 읽음 처리한다. 그러지 않으면 다음 실행에서 다시 밀려온다.
        remember(state, source["key"], [item.uid for item in candidates], now, pushed=sent > 0)
    return sent


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description="등록된 소스의 새 글을 텔레그램으로 발송한다")
    cli.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    cli.add_argument("--state", type=Path, default=STATE_PATH)
    cli.add_argument("--only", action="append", default=None, help="이 key만 실행(반복 지정 가능)")
    cli.add_argument("--check", action="store_true", help="연결 점검만 — 발송·상태 저장 없음")
    cli.add_argument("--dry-run", action="store_true", help="무엇이 나갈지 출력만")
    cli.add_argument("--seed", action="store_true", help="현재 글을 전부 읽음 처리(발송 없음)")
    cli.add_argument("--test", action="store_true",
                     help="발송 경로 점검 — 최신 글 1건을 상태 변경 없이 보낸다")
    cli.add_argument("--max", type=int, default=None, help="소스당 최대 발송 수 override")
    args = cli.parse_args(argv)

    now = datetime.now(timezone.utc)
    sources = load_registry(args.registry)
    if args.only:
        # channels로 펼친 소스는 묶음 key(ship_channels)로도, 개별 key로도 집을 수 있다.
        wanted = set(args.only)
        known = {source["key"] for source in sources} | {
            source["key"].split("__", 1)[0] for source in sources
        }
        unknown = wanted - known
        if unknown:
            print(f"알 수 없는 key: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
        # 콕 집어 실행한 것은 켜기 전 점검이 목적일 때가 많다. enabled: false여도 돌린다.
        active = [
            source for source in sources
            if source["key"] in wanted or source["key"].split("__", 1)[0] in wanted
        ]
        skipped = 0
    else:
        active = [source for source in sources if source.get("enabled")]
        skipped = len(sources) - len(active)
    print(f"소스 {len(active)}개 실행{f' (비활성 {skipped}개 건너뜀)' if skipped else ''} · {now.astimezone(KST):%Y-%m-%d %H:%M} KST")
    if not active:
        print("실행할 소스가 없습니다 — sources.yml에서 enabled: true 인지 확인하세요.")
        return 0

    # 발송이 일어날 수 있는 모드에서만 토큰을 요구한다. 없는 채로 돌면 첫 새 글에서
    # KeyError로 죽으므로, 수집 전에 무엇이 비었는지 알려주고 멈춘다.
    if not (args.check or args.dry_run or args.seed):
        missing = [name for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if not os.environ.get(name)]
        if missing:
            print(f"환경변수가 비었습니다: {', '.join(missing)} — 발송할 수 없습니다.", file=sys.stderr)
            print("점검만 하려면 --check 또는 --dry-run 을 쓰세요.", file=sys.stderr)
            return 2

    state = load_state(args.state)
    total = 0
    for source in active:
        total += run_source(source, state, now, args)

    if not (args.check or args.dry_run or args.test):
        save_state(state, args.state)
    print(f"완료 · {total}건 발송")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
