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

from rules import KST, detect_kind, pick_candidates, rule_extract  # noqa: E402

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
- 날짜를 도저히 못 정하면 vacation=true라도 start=null로 두라(사람이 확인한다).
- 일부 메시지에는 (맥락)으로 직전 대화가 붙어 있다. '나'는 계정 주인이다.
  맥락의 질문(예: "출장 언제야?")에 대한 날짜 답변이면 보낸 사람의 자리 비움 보고로
  vacation=true로 판정하고, 종류(kind)는 맥락에서 찾아라.
- note에는 장소·목적 같은 부가 정보(예: "카자흐스탄 출장")를 짧게 담아라."""


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


def pick_dialog(name: str, directory: dict[str, object]) -> tuple[object | None, str]:
    """이름으로 대화 상대를 고른다. 정확 일치 → 포함 일치(대화명에 '다리' 같은 수식어가
    붙는 관행 때문: '이준범 다리'도 '이준범'으로 잡힌다). 포함 후보가 여럿이면
    엉뚱한 사람을 잡지 않도록 보류하고 경고만 남긴다 — config에 username으로 확정할 것.
    """
    key = "".join(str(name).split()).casefold()
    if key in directory:
        return directory[key], "정확 일치"
    hits = sorted(k for k in directory if key in k)
    if len(hits) == 1:
        return directory[hits[0]], f"포함 일치 '{hits[0]}'"
    if not hits:
        return None, "대화 목록에 이 이름이 들어간 1:1 대화가 없습니다"
    # 여럿이면 '다리'가 붙은 쪽을 우선한다 — 친구 대화명에 다리를 붙이는 관행.
    dari = [k for k in hits if "다리" in k]
    if len(dari) == 1:
        return directory[dari[0]], f"포함 일치(다리 우선) '{dari[0]}'"
    return None, f"이름이 들어간 대화가 {len(hits)}개라 보류: {', '.join(hits[:5])}"


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
            if friend.get("scan") is False:
                continue  # 기입 폼 전용 이름(본인 등) — 대화 수집 없음
            try:
                if friend.get("chat_id"):
                    entity = await client.get_entity(int(friend["chat_id"]))
                elif friend.get("username"):
                    entity = await client.get_entity(str(friend["username"]).lstrip("@"))
                elif friend.get("phone"):
                    entity = await client.get_entity(str(friend["phone"]))
                else:
                    entity, how = pick_dialog(name, directory)
                    if entity is None:
                        raise LookupError(f"{how} (config에 username을 적으면 확정됩니다)")
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
            # min_id로 지난번 이후 새 메시지만. 첫 실행은 lookback 창으로 제한.
            # 내 메시지도 모아 둔다 — "출장 언제야?"(내 질문) → "9/15-9/18"(친구 답)처럼
            # 키워드와 날짜가 갈라진 문답을 맥락으로 잡기 위해서다.
            timeline: list[dict] = []
            async for message in client.iter_messages(entity, limit=per_chat_limit,
                                                      min_id=last_id):
                newest_id = max(newest_id, message.id)
                posted = message.date if message.date.tzinfo else message.date.replace(tzinfo=timezone.utc)
                if last_id == 0 and posted < since:
                    break  # 최신순 순회 — 창을 벗어나면 끝
                timeline.append({"id": message.id, "out": bool(message.out),
                                 "text": (message.message or "").strip(), "dt": posted})
            timeline.reverse()  # 시간순으로
            if include_own:
                for item in timeline:
                    item["out"] = False  # 내 보고도 후보로 (이름은 이 대화의 친구로 붙는다)
            picked = pick_candidates(timeline)
            for pick in picked:
                msg = timeline[pick["index"]]
                context_lines = [
                    f"{'나' if prev['out'] else name}: {prev['text'][:120]}"
                    for prev in timeline[max(0, pick["index"] - 10):pick["index"]]
                    if prev["text"]
                ]
                candidates.append({
                    "uid": f"{entity.id}:{msg['id']}",
                    "name": name,
                    "text": msg["text"],
                    "msg_date": msg["dt"].astimezone(KST).isoformat(timespec="minutes"),
                    "context": "\n".join(context_lines),
                    "kind_hint": pick["kind_hint"],
                    "trigger": pick["trigger"],
                })
            chat_state["last_id"] = newest_id
            print(f"  · {name}: 후보 {len(picked)}건 (마지막 메시지 id {newest_id})")
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
        block = (f"[{index}] {cand['name']} · {stamp.strftime('%Y-%m-%d')}"
                 f"({WEEKDAY_KO[stamp.weekday()]}) {stamp.strftime('%H:%M')}")
        if cand.get("context"):
            block += f"\n(맥락)\n{cand['context']}"
        block += f"\n(대상 메시지) {cand['text']}"
        lines.append(block)
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
            # 맥락 후보는 키워드가 상대 질문 쪽에 있다 — 종류를 맥락에서 가져온다.
            if cand.get("kind_hint") and detect_kind(cand["text"]) is None:
                entry["kind"] = cand["kind_hint"]
        display_text = cand["text"]
        if cand.get("trigger") == "context" and cand.get("context"):
            display_text = f"{cand['context'].splitlines()[-1]} → {cand['text']}"
        entry.update(uid=cand["uid"], name=cand["name"], text=display_text,
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


def _apply_op(op: str, body: dict) -> None:
    """페이지에서 온 삭제·메모 수정 한 건을 entries.json에 반영하고 페이지 재생성."""
    uid = str(body.get("uid") or "").strip()
    if not uid:
        raise SystemExit("uid가 비어 있습니다")
    store = load_json(ENTRIES_PATH, {"entries": {}})
    entry = store["entries"].get(uid)
    if entry is None:
        # 이미 지워졌거나 uid가 틀림 — 실패로 죽지 않고 페이지만 다시 굽는다(멱등).
        print(f"[경고] uid를 찾지 못했습니다: {uid} — 변경 없음")
    elif op == "delete":
        store["entries"].pop(uid)
        print(f"삭제: {entry.get('name')} {entry.get('start')}~{entry.get('end')} ({uid})")
    elif op == "note":
        entry["note"] = str(body.get("note") or "").strip()
        print(f"메모 수정: {entry.get('name')} ({uid}) → {entry['note']!r}")
    elif op == "kind":
        kind = str(body.get("kind") or "").strip()
        if not kind:
            raise SystemExit("kind가 비어 있습니다")
        entry["kind"] = kind
        print(f"종류 수정: {entry.get('name')} ({uid}) → {kind}")
    else:
        raise SystemExit(f"알 수 없는 op: {op!r}")
    save_json(ENTRIES_PATH, store)
    from render_page import build_page

    build_page(store)


def add_manual(raw: str) -> None:
    """대시보드 기입 폼에서 온 항목 한 건을 entries.json에 붙이고 페이지를 다시 굽는다.

    입력(JSON): {"name","start","end","kind","note"} — end 비면 하루짜리.
    수집과 무관하므로 텔레그램 세션·Gemini가 필요 없다.
    """
    try:
        body = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"entry가 JSON이 아닙니다: {exc}")

    # 같은 경로로 삭제·메모 수정도 받는다 — {"op":"delete"|"note","uid":...,"note":...}.
    # GAS 라우트를 안 바꾸려고 add에 op를 얹었다(entry만 있으면 통과).
    op = str(body.get("op") or "").strip()
    if op:
        return _apply_op(op, body)

    name = str(body.get("name") or "").strip()
    start = str(body.get("start") or "").strip()
    if not name or not start:
        raise SystemExit("name과 start(YYYY-MM-DD)는 필수입니다")
    try:
        datetime.strptime(start, "%Y-%m-%d")
        end = str(body.get("end") or "").strip() or start
        datetime.strptime(end, "%Y-%m-%d")
    except ValueError as exc:
        raise SystemExit(f"날짜 형식이 틀렸습니다(YYYY-MM-DD): {exc}")
    if end < start:
        start, end = end, start

    now = datetime.now(KST)
    note = str(body.get("note") or "").strip()
    store = load_json(ENTRIES_PATH, {"entries": {}})
    uid = f"manual:{now.strftime('%Y%m%d%H%M%S')}"
    store["entries"][uid] = {
        "name": name,
        "start": start,
        "end": end,
        "kind": str(body.get("kind") or "휴가").strip() or "휴가",
        "note": note,
        "text": note or "직접 기입",
        "needs_review": False,
        "engine": "manual",
        "msg_date": now.isoformat(timespec="minutes"),
        "detected_at": now.isoformat(timespec="minutes"),
    }
    save_json(ENTRIES_PATH, store)
    from render_page import build_page

    build_page(store)
    print(f"직접 기입: {name} {start}~{end} {store['entries'][uid]['kind']}")


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
    parser.add_argument("--add", metavar="JSON", help='직접 기입 {"name","start","end","kind","note"}')
    args = parser.parse_args()

    if args.check:
        check()
    elif args.add is not None:
        add_manual(args.add)
    elif args.rebuild_page:
        from render_page import build_page

        build_page(load_json(ENTRIES_PATH, {"entries": {}}))
    else:
        run(dry_run=args.dry_run, probe=args.probe)


if __name__ == "__main__":
    main()
