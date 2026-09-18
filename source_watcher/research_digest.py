"""커버리지 리서치 요약 아침 모음 — 낱개 알림이 아니라 하루 한 통.

요약 채널(@ked_epic_ai)에는 증권사 보고서를 "[✨ 리서치 요약] 기업명 …" 형태로 요약해 올리는
글이 하루 수십 건 흐른다. 이 스크립트는 매일 아침(08:50 KST 목표 — 채널의 아침 목록이 ~08:40에 올라온다) 그 채널의 지난 하루치에서
요약 글만 골라, 커버리지 산업(조선·방산·기계)에 해당하는 것만 추려 한 통으로 보낸다.

ship_all(조선 염탐)과의 관계: 저쪽은 걸리는 즉시 낱개 알림, 여기는 '보고서 요약'
표식이 붙은 글만 모아 아침 브리핑. 같은 세션·같은 어댑터를 쓰고 발송 봇도 같다(spying).

커버리지 낱말은 sources.yml의 x_ship_keywords(조선·방산·건설기계)에
x_research_digest_extra(기계 등 추가분)를 합쳐 쓴다 — 목록 관리는 그 파일 한 곳에서.

    python research_digest.py             # 수집 → 모아서 발송 → 상태 저장
    python research_digest.py --dry-run   # 무엇이 나갈지 출력만
    python research_digest.py --force     # 오늘 이미 보냈어도 다시 보낸다

하루 한 번 가드: state/research_digest.json에 마지막 발송 시각을 남기고, 같은 날(KST)
두 번째 실행은 건너뛴다. 그래서 GAS 스케줄러(정시)와 GitHub 크론(안전망)이 겹쳐도
한 통만 나간다 — 크론이 몇 시간 늦게 도착하는 날의 안전망이다(CLAUDE.md 17번 교훈).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import adapters
import notify
import watch_sources as ws

BASE_DIR = Path(__file__).resolve().parent
STATE_PATH = BASE_DIR / "state" / "research_digest.json"
KST = timezone(timedelta(hours=9))

# 보고서 글의 표식. 채널이 두 형태로 올린다:
#   ① "[✨ 리서치 요약] 기업명 …"        — 장중 낱개 요약
#   ② "[✨ 리서치] 심층 분석 보고서" 등    — 아침(자정~8시 발간분) 번호 목록 한 통
# ①만 보다가 ②를 통째로 놓쳐 아침 발간분이 한 건도 안 잡혔었다(9/18 발견).
MARKER_RE = re.compile(r"\[\s*✨\s*리서치|리서치\s*요약")
# 제목 표시용으로 벗겨낼 머리말
MARKER_STRIP_RE = re.compile(r"\[\s*✨\s*리서치[^\]]*\]|리서치\s*요약")
# 목록 글(②)의 항목: "1. 산업 | [조선] 제목 | SK증권" — 다음 번호 전까지가 한 항목
ENTRY_RE = re.compile(r"^\s*\d{1,2}\.\s+(.+?)(?=^\s*\d{1,2}\.\s|\Z)", re.M | re.S)
# 제목 정규화용 — 같은 요약이 여러 채널로 퍼날라진 것을 접는다.
TITLE_NOISE_RE = re.compile(r"[^0-9a-z가-힣]+")

DEFAULT_WINDOW_HOURS = 24
MAX_WINDOW_HOURS = 48   # 어제 크론이 통째로 죽었어도 이틀치까지만 몰아 보낸다


def load_coverage() -> tuple[list[tuple[str, list[str]]], list[str]]:
    """sources.yml에서 커버리지 낱말 묶음과 '요약이 올라오는 채널' 목록을 읽는다."""
    import yaml

    raw = yaml.safe_load((BASE_DIR / "sources.yml").read_text(encoding="utf-8")) or {}
    coverage: dict = {}
    coverage.update(raw.get("x_ship_keywords") or {})
    coverage.update(raw.get("x_research_digest_extra") or {})
    if not coverage:
        raise RuntimeError("sources.yml에서 커버리지 낱말을 찾지 못했습니다 (x_ship_keywords)")

    channels = [str(c) for c in (raw.get("x_research_digest_channels") or []) if str(c).strip()]
    if not channels:
        raise RuntimeError("sources.yml에 x_research_digest_channels가 비어 있습니다")
    return ws.keyword_groups(coverage), channels


def coverage_labels(groups: list[tuple[str, list[str]]], text: str) -> list[str]:
    """글에 걸린 커버리지 묶음 이름을 등장 순서로. 비어 있으면 커버리지 밖 보고서다."""
    found: list[tuple[int, str]] = []
    for label, words in groups:
        spots = [m.start() for term in words for m in [re.search(re.escape(term), text, re.I)] if m]
        if spots:
            found.append((min(spots), label))
    found.sort()
    ordered: list[str] = []
    for _, label in found:
        if label not in ordered:
            ordered.append(label)
    return ordered


def title_key(title: str) -> str:
    """퍼나른 같은 요약을 접기 위한 제목 지문. 표식·이모지·문장부호를 걷어낸다."""
    value = MARKER_STRIP_RE.sub("", title.casefold())
    return TITLE_NOISE_RE.sub("", value)


def explode_entries(items: list[adapters.Item]) -> list[adapters.Item]:
    """목록 글(번호 목록 2건 이상)은 보고서 항목별로 쪼갠다. 낱개 요약 글은 그대로.

    아침 '[✨ 리서치] 심층 분석 보고서' 한 통에 여러 산업 보고서가 섞여 있어,
    글 단위로 매칭하면 조선 한 건 때문에 제약·ESG까지 딸려 오거나 제목이
    '심층 분석 보고서'로만 찍힌다. 항목 단위로 갈라야 커버리지 것만 제목째 뽑힌다.
    """
    exploded: list[adapters.Item] = []
    for item in items:
        entries = [" ".join(chunk.split()) for chunk in ENTRY_RE.findall(item.body or "")]
        entries = [entry for entry in entries if len(entry) >= 8]
        if len(entries) < 2:
            exploded.append(item)
            continue
        for order, entry in enumerate(entries):
            exploded.append(adapters.Item(
                uid=f"{item.uid}#{order}", title=entry, url=item.url, body=entry,
                published_at=item.published_at, origin=item.origin,
            ))
    return exploded


def load_digest_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_digest_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def pick_window_hours(state: dict, now: datetime, override: float | None) -> float:
    """지난 발송 이후를 창으로 잡되, 오래 죽어 있었어도 이틀치까지만."""
    if override:
        return override
    last_raw = state.get("last_sent_at")
    if not last_raw:
        return DEFAULT_WINDOW_HOURS
    try:
        last = datetime.fromisoformat(last_raw)
    except ValueError:
        return DEFAULT_WINDOW_HOURS
    hours = (now - last).total_seconds() / 3600
    return min(max(hours, 1.0), MAX_WINDOW_HOURS)


def collect_reports(window_hours: float, channels: list[str]) -> list[adapters.Item]:
    # 요약 글은 지정 채널(x_research_digest_channels)에서만 올라온다.
    # include_chats로 좁히면 다른 방은 히스토리를 아예 요청하지 않아 스캔이 몇 초로 끝난다.
    source = {
        "lookback_hours": window_hours,
        "include_chats": channels,
    }
    items = adapters.collect_telegram_account(source)
    return [item for item in items if MARKER_RE.search(item.title or "")]


def build_digest(items: list[adapters.Item], groups: list[tuple[str, list[str]]],
                 now: datetime) -> tuple[str, int]:
    """모음 메시지 본문과 건수를 만든다. 커버리지 밖 요약은 여기서 걸러진다."""
    escape = notify.escape
    picked: dict[str, dict] = {}   # title_key → {item, labels, channels}
    for item in sorted(explode_entries(items), key=lambda it: (it.published_at or now, it.uid)):
        labels = coverage_labels(groups, item.text_for_match())
        if not labels:
            continue
        key = title_key(item.title)
        if key in picked:
            picked[key]["channels"].add(item.origin or "")
            continue
        picked[key] = {"item": item, "labels": labels, "channels": {item.origin or ""}}

    stamp = f"{now.astimezone(KST):%m/%d %H:%M}"
    head = (f"🗂️ <b>커버리지 리서치 요약 모음</b> · {stamp} KST\n"
            f"조선·방산·기계 보고서 {len(picked)}건")
    if not picked:
        return head + " — 지난 하루 새 요약 없음", 0

    lines = []
    for entry in picked.values():
        item, labels = entry["item"], entry["labels"]
        when = f"{item.published_at.astimezone(KST):%H:%M}" if item.published_at else "?"
        title = MARKER_STRIP_RE.sub("", item.title).strip(" []✨-·:") or item.title
        line = f"• <b>[{escape(labels[0])}]</b> {escape(title)}"
        extra = len(entry["channels"]) - 1
        meta = f"{when}" + (f" · {extra + 1}개 채널" if extra > 0 else "")
        if item.url:
            line += f'\n   <a href="{escape(item.url)}">원문</a> · {meta}'
        else:
            line += f"\n   {meta}"
        lines.append(line)
    return head + "\n\n" + "\n".join(lines), len(picked)


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description="커버리지 리서치 요약을 하루 한 통으로 모아 보낸다")
    cli.add_argument("--dry-run", action="store_true", help="발송·상태 저장 없이 출력만")
    cli.add_argument("--force", action="store_true", help="오늘 이미 보냈어도 다시 보낸다")
    cli.add_argument("--window-hours", type=float, default=None, help="조회 창 크기 override")
    args = cli.parse_args(argv)

    now = datetime.now(timezone.utc)
    state = load_digest_state()

    last_raw = state.get("last_sent_at")
    if last_raw and not (args.force or args.dry_run):
        try:
            last_kst = datetime.fromisoformat(last_raw).astimezone(KST)
            if last_kst.date() == now.astimezone(KST).date():
                # GAS 스케줄러가 정시에 쏘고 GitHub 크론이 몇 시간 늦게 또 오는 날의 가드
                print(f"오늘({last_kst:%H:%M}) 이미 발송 — 건너뜁니다. 다시 보내려면 --force")
                return 0
        except ValueError:
            pass

    groups, channels = load_coverage()
    window = pick_window_hours(state, now, args.window_hours)
    print(f"조회 창 {window:.1f}시간 · 커버리지 묶음 {len(groups)}개 · 대상 채널 {', '.join(channels)}")

    items = collect_reports(window, channels)
    print(f"리서치 표식 글 {len(items)}건 수집")
    for item in items:
        # 매칭 진단용 — '왜 안 잡혔지?'가 나오면 이 목록부터 본다
        print(f"  · {item.title[:70]}")

    text, count = build_digest(items, groups, now)
    if args.dry_run:
        print("--- 발송 내용(모의) ---")
        print(re.sub(r"<[^>]+>", "", text))
        return 0

    token, chat_id = ws.route_credentials({"route": "spying"})
    notify.send(text, token=token, chat_id=chat_id)
    print(f"발송 완료 · 커버리지 보고서 {count}건")

    save_digest_state({"last_sent_at": now.isoformat(), "last_count": count})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
