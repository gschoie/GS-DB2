"""등록된 소스를 훑어 새 글만 텔레그램으로 밀어내는 감시 봇.

소스마다 스크립트를 만들지 않는다. sources.yml에 몇 줄 추가하면 그것으로 끝이다.
새 소스를 붙이는 순서는 README를 볼 것.

    python watch_sources.py                 # 수집 → 새 글 발송 → 상태 저장
    python watch_sources.py --check         # 연결만 점검(발송·저장 없음)
    python watch_sources.py --dry-run       # 무엇이 나갈지 출력만
    python watch_sources.py --only mer      # 특정 소스만
    python watch_sources.py --seed          # 지금 글을 전부 '읽음' 처리(발송 없음)

상태 파일(state/seen.json)이 중복 발송을 막는다. Actions 러너는 매번 새 컨테이너라
이 파일을 저장소에 커밋해 두어야 다음 실행이 무엇을 이미 보냈는지 안다.
"""

from __future__ import annotations

import argparse
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

DEFAULTS = {
    "enabled": True,
    "max_per_run": 5,      # 한 번에 밀어낼 상한. 피드가 통째로 갱신돼도 폭주하지 않게.
    "lookback_hours": 48,  # 이보다 오래된 글은 미발송분이어도 보내지 않는다.
    "excerpt_chars": 600,
    "push": None,          # full | excerpt (None이면 종류별 기본값)
    "match": None,         # 제목+본문에 걸 정규식(대소문자 무시)
    "exclude": None,
    "tags": [],
}


# ── 레지스트리 ─────────────────────────────────────────────────────────────

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
        source = {**defaults, **entry}
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

def keep(source: dict, item: adapters.Item) -> bool:
    """소스에 걸린 match/exclude 정규식으로 글을 거른다.

    한 채널이 여러 자료를 섞어 뿌릴 때(예: 데일리 + 종목 리포트) 원하는 것만 받기 위한 것.
    """
    haystack = item.text_for_match()
    match = source.get("match")
    if match and not re.search(match, haystack, re.I | re.S):
        return False
    exclude = source.get("exclude")
    if exclude and re.search(exclude, haystack, re.I | re.S):
        return False
    return True


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


def push_mode(source: dict) -> str:
    mode = source.get("push")
    if mode:
        return mode
    # 텔레그램 글은 그 자체가 완성된 본문이라 통째로, RSS는 요약 + 원문 링크가 낫다.
    return "full" if source.get("type") == "telegram" else "excerpt"


def render(source: dict, item: adapters.Item) -> str:
    escape = notify.escape
    head = f"📌 <b>{escape(source['name'])}</b>"
    tags = source.get("tags") or []
    if tags:
        head += "  " + " ".join(f"#{escape(str(tag))}" for tag in tags)
    if item.published_at:
        head += f"\n🕒 {item.published_at.astimezone(KST):%Y-%m-%d %H:%M} KST"

    if push_mode(source) == "full":
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
        if source.get("match") or source.get("exclude"):
            print(f"  · 필터 통과 {len(kept)}/{len(items)}건")
            if items and not kept:
                print("  ⚠ 전부 걸러졌습니다 — sources.yml의 match/exclude를 확인하세요.")
        for item in (kept or items)[:3]:
            stamp = f"{item.published_at.astimezone(KST):%m-%d %H:%M}" if item.published_at else "날짜없음"
            print(f"    - {stamp} | {item.title[:60]}")
        return 0

    known = source["key"] in state["sources"]
    if not known and not args.seed:
        # 첫 실행에서 피드 전체를 쏘면 수십 통이 한꺼번에 온다. 읽음 처리만 하고 다음 글부터 보낸다.
        remember(state, source["key"], [item.uid for item in items], now, pushed=False)
        print(f"  · 첫 실행 — {len(items)}건 읽음 처리만. 다음 글부터 발송합니다.")
        return 0

    fresh = select(source, items, state, now)
    if args.seed:
        remember(state, source["key"], [item.uid for item in items], now, pushed=False)
        print(f"  · seed — {len(items)}건 읽음 처리")
        return 0
    if not fresh:
        remember(state, source["key"], [], now, pushed=False)
        print("  · 새 글 없음")
        return 0

    limit = args.max if args.max is not None else (source.get("max_per_run") or 0)
    to_send = fresh[-limit:] if limit > 0 else fresh
    if len(to_send) < len(fresh):
        print(f"  · 새 글 {len(fresh)}건 중 최신 {len(to_send)}건만 발송(max_per_run) — 나머지는 읽음 처리")

    sent = 0
    for item in to_send:
        if args.dry_run:
            print(f"  · [모의] {item.title[:70]}  {item.url}")
            sent += 1
            continue
        notify.send(render(source, item))
        print(f"  · 발송 {item.title[:70]}")
        sent += 1

    if not args.dry_run:
        # 상한에 걸려 못 보낸 글도 읽음 처리한다. 그러지 않으면 다음 실행에서 다시 밀려온다.
        remember(state, source["key"], [item.uid for item in fresh], now, pushed=sent > 0)
    return sent


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description="등록된 소스의 새 글을 텔레그램으로 발송한다")
    cli.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    cli.add_argument("--state", type=Path, default=STATE_PATH)
    cli.add_argument("--only", action="append", default=None, help="이 key만 실행(반복 지정 가능)")
    cli.add_argument("--check", action="store_true", help="연결 점검만 — 발송·상태 저장 없음")
    cli.add_argument("--dry-run", action="store_true", help="무엇이 나갈지 출력만")
    cli.add_argument("--seed", action="store_true", help="현재 글을 전부 읽음 처리(발송 없음)")
    cli.add_argument("--max", type=int, default=None, help="소스당 최대 발송 수 override")
    args = cli.parse_args(argv)

    now = datetime.now(timezone.utc)
    sources = load_registry(args.registry)
    if args.only:
        wanted = set(args.only)
        unknown = wanted - {source["key"] for source in sources}
        if unknown:
            print(f"알 수 없는 key: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
        sources = [source for source in sources if source["key"] in wanted]

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

    if not args.check and not args.dry_run:
        save_state(state, args.state)
    print(f"완료 · {total}건 발송")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
