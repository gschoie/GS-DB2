"""친구 휴가 일정 추적 봇.

config.yml에 지정한 친구들과의 1:1 텔레그램 대화를 내 계정 세션(Telethon)으로 훑어
"휴가 갑니다"류 보고를 잡아낸다. 잡은 메시지는 Gemini(폴백: 규칙 파서)로
{이름, 시작일, 종료일, 종류}로 구조화해 state/entries.json에 쌓고,
대시보드 페이지(vacation_report.html)를 굽고, 새로 잡힌 건만 텔레그램으로 알린다.

세션은 source_watcher와 같은 것을 쓴다 — 워크플로가 state/session.enc를 풀어
TELEGRAM_SESSION_STRING으로 넘긴다. 기기 정보(DEVICE_INFO)도 같은 값이어야
텔레그램이 '새 기기 로그인'으로 오인해 세션을 끊지 않는다.

실행 모드
    (기본)          수집 → 추출 → 상태 갱신 → 페이지 → 텔레그램
    --dry-run       수집·추출까지만. 상태·페이지 안 건드리고 결과만 출력
    --check         네트워크 없이 config·환경변수 점검
    --probe         접속해서 친구가 실제 대화로 매칭되는지 확인 (메시지 안 읽음)
    --rebuild-page  entries.json만으로 페이지 재생성 (네트워크 불필요)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
# 로그인(cloud_login.py)·소스 감시와 같은 기기 정보를 써야 세션이 안정된다.
sys.path.insert(0, str(ROOT / "source_watcher"))

from rules import KST, is_candidate, rule_extract  # noqa: E402

CONFIG_PATH = HERE / "config.yml"
STATE_PATH = HERE / "state" / "state.json"
ENTRIES_PATH = HERE / "state" / "entries.json"

GEMINI_SYSTEM_PROMPT = """너는 텔레그램 대화에서 '자리 비움 보고'(휴가·연차·반차·출장·샵투어 등)를
추려 정리하는 비서다.
입력은 번호가 붙은 메시지 목록이다. 각 메시지에는 보낸 사람, 보낸 시각(KST, 요일 포함), 본문이 있다.

메시지마다 아래를 판정해 JSON 배열로만 답하라(설명 금지):
[{"i": <메시지 번호>, "vacation": true|false, "start": "YYYY-MM-DD"|null,
  "end": "YYYY-MM-DD"|null, "kind": "연차|반차|오전반차|오후반차|휴가|출장|해외출장|병가|휴무|기타",
  "note": "짧은 메모(선택)"}]

판정 기준:
- vacation=true는 '보낸 사람 본인이 자리를 비운다는 보고'만. 남 얘기, 과거 회상,
  질문("휴가 언제 가?"), 일반 잡담은 false.
- "내일", "다음주 수요일" 같은 상대 날짜는 그 메시지의 보낸 시각을 기준으로 계산한다.
- 종료일이 없으면 end=start(하루짜리). "3일간"이면 시작일 포함 3일.
- 날짜를 도저히 못 정하면 vacation=true라도 start=null로 두라(사람이 확인한다)."""


# ── 설정·상태 ──────────────────────────────────────────────────────────────

def load_config() -> dict:
    import yaml

    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    friends = config.get("friends") or []
    if not friends:
        raise SystemExit("config.yml의 friends가 비어 있습니다 — 추적할 친구를 등록하세요.")
    for friend in friends:
        if isinstance(friend, str):  # 이름만 적은 축약형 허용
            continue
        if not friend.get("name"):
            raise SystemExit(f"friends 항목에 name이 없습니다: {friend!r}")
    # 축약형(문자열)을 dict로 통일한다.
    config["friends"] = [{"name": f} if isinstance(f, str) else f for f in friends]
    return config


def load_json(path: Path, fallback: dict) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"[경고] {path.name} 파싱 실패 — 새로 시작합니다", file=sys.stderr)
    return dict(fallback)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8")


# ── 수집 (Telethon) ────────────────────────────────────────────────────────

def _session():
    raw = os.environ.get("TELEGRAM_SESSION_STRING", "").strip()
    if raw:
        from telethon.sessions import StringSession

        return StringSession(raw)
    # 로컬 시험용 — source_watcher의 세션 파일을 같이 쓴다.
    return str(ROOT / "source_watcher" / "state" / "telegram_account.session")


async def _dialog_directory(client, max_chats: int = 500) -> dict[str, object]:
    """1:1 대화 상대의 '표시 이름' → 엔티티. username 없이 이름만으로 친구를 찾는 용도.

    표시 이름은 성+이름을 공백 없이 붙여 비교한다("이 준범"·"이준범" 모두 매칭).
    """
    from telethon.tl.types import User

    directory: dict[str, object] = {}
    async for dialog in client.iter_dialogs(limit=max_chats):
        entity = dialog.entity
        if not isinstance(entity, User) or getattr(entity, "bot", False):
            continue
        full = f"{getattr(entity, 'first_name', '') or ''}{getattr(entity, 'last_name', '') or ''}"
        key = "".join(full.split()).casefold()
        if key:
            directory.setdefault(key, entity)
    return directory


async def _scan(config: dict, state: dict, probe: bool = False) -> list[dict]:
    from adapters import DEVICE_INFO  # source_watcher와 단일 정본
    from telethon import TelegramClient

    api_id = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    if not api_id or not api_hash:
        raise SystemExit("TELEGRAM_API_ID/TELEGRAM_API_HASH가 필요합니다 (my.telegram.org 발급).")

    lookback_days = int(config.get("lookback_days") or 14)
    per_chat_limit = int(config.get("per_chat_limit") or 200)
    include_own = bool(config.get("include_own_messages"))
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    client = TelegramClient(_session(), int(api_id), api_hash, **DEVICE_INFO)
    await client.connect()
    candidates: list[dict] = []
    try:
        if not await client.is_user_authorized():
            raise SystemExit(
                "텔레그램 계정 세션이 없습니다 — '텔레그램 계정 로그인' 워크플로로 먼저 로그인하세요."
            )
        chats = state.setdefault("chats", {})
        # username·chat_id가 없는 친구는 대화 목록의 표시 이름으로 찾는다 — 한 번만 훑는다.
        directory: dict[str, object] = {}
        if any(not (f.get("username") or f.get("chat_id") or f.get("phone"))
               for f in config["friends"]):
            directory = await _dialog_directory(client, int(config.get("max_chats") or 500))
        for friend in config["friends"]:
            name = friend["name"]
            try:
                if friend.get("chat_id"):
                    entity = await client.get_entity(int(friend["chat_id"]))
                elif friend.get("username"):
                    entity = await client.get_entity(str(friend["username"]).lstrip("@"))
                elif friend.get("phone"):
                    entity = await client.get_entity(str(friend["phone"]))
                else:
                    entity = directory.get("".join(str(name).split()).casefold())
                    if entity is None:
                        raise LookupError("대화 목록에 이 이름의 1:1 대화가 없습니다 "
                                          "(텔레그램 표시 이름과 다르면 config에 username을 적으세요)")
            except Exception as exc:
                print(f"[경고] '{name}' 대화를 못 찾았습니다: {exc}", file=sys.stderr)
                continue

            chat_key = str(entity.id)
            shown = getattr(entity, "first_name", "") or getattr(entity, "title", "") or "?"
            if probe:
                print(f"  · {name} ↔ 텔레그램 '{shown}' (id={entity.id}) 매칭 확인")
                continue

            chat_state = chats.setdefault(chat_key, {})
            chat_state["name"] = name
            last_id = int(chat_state.get("last_id") or 0)
            newest_id = last_id
            scanned = 0
            # min_id로 지난번 이후 새 메시지만. 첫 실행은 lookback 창으로 제한.
            async for message in client.iter_messages(entity, limit=per_chat_limit,
                                                      min_id=last_id):
                newest_id = max(newest_id, message.id)
                posted = message.date if message.date.tzinfo else message.date.replace(tzinfo=timezone.utc)
                if last_id == 0 and posted < since:
                    break  # 최신순 순회 — 창을 벗어나면 끝
                if message.out and not include_own:
                    continue  # 내가 보낸 메시지는 기본 제외 (친구의 '보고'만)
                text = (message.message or "").strip()
                if not text or not is_candidate(text):
                    continue
                scanned += 1
                candidates.append({
                    "uid": f"{entity.id}:{message.id}",
                    "name": name,
                    "text": text,
                    "msg_date": posted.astimezone(KST).isoformat(timespec="minutes"),
                })
            chat_state["last_id"] = newest_id
            print(f"  · {name}: 후보 {scanned}건 (마지막 메시지 id {newest_id})")
    finally:
        await client.disconnect()
    return candidates


# ── 추출 (Gemini → 규칙 폴백) ──────────────────────────────────────────────

WEEKDAY_KO = "월화수목금토일"


def _gemini_extract(candidates: list[dict]) -> dict[int, dict] | None:
    """후보 전체를 한 번에 판정한다. 실패하면 None — 규칙 파서가 받는다."""
    if not os.environ.get("GEMINI_API_KEY"):
        return None
    try:
        from google import genai
        from google.genai import types as genai_types
    except ImportError:
        return None

    lines = []
    for index, cand in enumerate(candidates):
        stamp = datetime.fromisoformat(cand["msg_date"])
        lines.append(f"[{index}] {cand['name']} · {stamp.strftime('%Y-%m-%d')}"
                     f"({WEEKDAY_KO[stamp.weekday()]}) {stamp.strftime('%H:%M')}\n{cand['text']}")
    payload = "\n\n".join(lines)

    client = genai.Client()
    config = genai_types.GenerateContentConfig(
        system_instruction=GEMINI_SYSTEM_PROMPT,
        temperature=0.1,
        max_output_tokens=4096,
        response_mime_type="application/json",
    )
    primary = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    models = list(dict.fromkeys([primary, "gemini-flash-lite-latest"]))
    import time

    for model in models:
        for attempt in range(2):
            try:
                response = client.models.generate_content(model=model, contents=payload,
                                                          config=config)
                rows = json.loads((response.text or "").strip())
                result = {}
                for row in rows if isinstance(rows, list) else []:
                    if isinstance(row, dict) and isinstance(row.get("i"), int):
                        result[row["i"]] = row
                print(f"[Gemini:{model}] {len(result)}건 판정")
                return result
            except Exception as exc:
                print(f"[Gemini:{model}] 오류(시도 {attempt + 1}): {exc}", file=sys.stderr)
                time.sleep(30 * (attempt + 1))
    return None


def extract(candidates: list[dict]) -> list[dict]:
    """후보 → 확정 항목. Gemini가 '보고 아님'이라 한 건은 버린다."""
    verdicts = _gemini_extract(candidates) if candidates else {}
    entries: list[dict] = []
    for index, cand in enumerate(candidates):
        msg_dt = datetime.fromisoformat(cand["msg_date"])
        verdict = (verdicts or {}).get(index)
        if verdict is not None:
            if not verdict.get("vacation"):
                continue
            start = verdict.get("start")
            entry = {
                "kind": str(verdict.get("kind") or "휴가"),
                "start": start,
                "end": verdict.get("end") or start,
                "note": str(verdict.get("note") or ""),
                "needs_review": not start,
                "engine": "gemini",
            }
        else:  # Gemini 불가·실패 — 규칙 파서로라도 잡아둔다
            entry = rule_extract(cand["text"], msg_dt)
            entry["note"] = ""
        entry.update(uid=cand["uid"], name=cand["name"], text=cand["text"],
                     msg_date=cand["msg_date"],
                     detected_at=datetime.now(KST).isoformat(timespec="minutes"))
        entries.append(entry)
    return entries


# ── 텔레그램 알림 ──────────────────────────────────────────────────────────

def notify(new_entries: list[dict]) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("[알림] TELEGRAM_BOT_TOKEN/CHAT_ID 미설정 — 발송 생략(대시보드 전용)")
        return
    import notify as watcher_notify  # source_watcher의 발송기 재사용 (분할·재시도 포함)

    lines = [f"🏖️ <b>휴가 보고 감지</b> ({len(new_entries)}건)", ""]
    for entry in sorted(new_entries, key=lambda e: (e.get("start") or "9999", e["name"])):
        lines.append(f"<b>{watcher_notify.escape(entry['name'])}</b> — {span_label(entry)}")
        snippet = entry["text"][:120]
        lines.append(f"└ \"{watcher_notify.escape(snippet)}\"")
        lines.append("")
    lines.append('전체 일정: <a href="https://gschoie.github.io/GS-DB2/vacation_report.html">대시보드</a>')
    watcher_notify.send("\n".join(lines), token=token, chat_id=chat_id)
    print(f"[알림] {len(new_entries)}건 발송")


def span_label(entry: dict) -> str:
    if not entry.get("start"):
        return f"{entry.get('kind', '휴가')} (날짜 미상 — 확인 필요)"
    start = datetime.fromisoformat(entry["start"])
    label = f"{start.strftime('%m/%d')}({WEEKDAY_KO[start.weekday()]})"
    end_raw = entry.get("end") or entry["start"]
    if end_raw != entry["start"]:
        end = datetime.fromisoformat(end_raw)
        label += f"~{end.strftime('%m/%d')}({WEEKDAY_KO[end.weekday()]})"
    return f"{label} {entry.get('kind', '휴가')}"


# ── 실행 ───────────────────────────────────────────────────────────────────

def run(dry_run: bool = False, probe: bool = False) -> None:
    config = load_config()
    state = load_json(STATE_PATH, {"chats": {}})
    if probe:
        asyncio.run(_scan(config, state, probe=True))
        return

    candidates = asyncio.run(_scan(config, state))
    print(f"후보 {len(candidates)}건")
    entries = extract(candidates)

    store = load_json(ENTRIES_PATH, {"entries": {}})
    known = store["entries"]
    new_entries = [entry for entry in entries if entry["uid"] not in known]
    print(f"확정 {len(entries)}건, 그중 신규 {len(new_entries)}건")

    if dry_run:
        for entry in entries:
            print(f"  - {entry['name']} {span_label(entry)} [{entry['engine']}] :: {entry['text'][:60]}")
        return

    for entry in entries:
        known[entry["uid"]] = {k: v for k, v in entry.items() if k != "uid"}
    save_json(ENTRIES_PATH, store)
    save_json(STATE_PATH, state)

    from render_page import build_page

    build_page(store)
    if new_entries:
        notify(new_entries)


def check() -> None:
    config = load_config()
    print(f"친구 {len(config['friends'])}명 등록: " + ", ".join(f["name"] for f in config["friends"]))
    for name in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION_STRING",
                 "GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        print(f"  {name}: {'설정됨' if os.environ.get(name) else '없음'}")
    print("config·환경변수 점검 끝 (네트워크 미사용)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rebuild-page", action="store_true")
    args = parser.parse_args()

    if args.check:
        check()
    elif args.rebuild_page:
        from render_page import build_page

        build_page(load_json(ENTRIES_PATH, {"entries": {}}))
    else:
        run(dry_run=args.dry_run, probe=args.probe)


if __name__ == "__main__":
    main()
