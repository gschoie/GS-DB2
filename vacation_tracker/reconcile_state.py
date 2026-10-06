"""경합 push 재시도용 상태 병합 — 줄 병합이 아니라 '일 단위'로 합친다.

push가 거절되면 내 커밋의 상태 JSON은 낡은 base 위에 만들어진 것이다. 이걸
`git pull --rebase -X theirs`로 줄 병합하면 그 사이 main에 실린 다른 run의
op(수동 체크 등)를 통째로 덮어쓴다 — 10/6 근태 수동 체크 3건 유실 사고의 원인.
(JSON에서 이웃한 이름들이 같은 diff 문맥에 걸려 충돌하고, theirs가 이긴다.)

대신: 내 run의 산출(ours)을 따로 떼어 두고 `git reset --hard origin/main`으로
최신 main에서 다시 시작한 뒤, 이 스크립트가 ours를 **키 단위**로 합쳐 넣는다.
규칙은 "다른 run이 이미 한 일(main)은 지키고, 내 run이 새로 알아낸 것만 보탠다":

- entries.json / indepth.json: uid 합집합. 충돌(양쪽에 같은 uid)은 main 우선
  — 수집은 아는 uid를 안 고치므로, 충돌의 다른 쪽은 op(수동 수정)다.
- attendance.json: campaigns는 main 우선(op 전용). months는 (월,이름) 합집합,
  충돌은 checked=어느 한쪽이라도 true, 본문·uid는 텔레그램 출처 우선
  (수동 토글엔 원문이 없다), note는 비어 있지 않은 쪽.
- state.json(chats): 합집합, 충돌은 last_id 큰 쪽 — 내 run이 읽은 지점을 잃으면
  같은 메시지를 다시 읽는다(무해하지만 낭비).

사용: python reconcile_state.py <ours_dir>   (ours_dir = 내 run의 state/*.json 사본,
작업 트리의 state/는 reset 직후라 main 본이다. 합친 결과를 작업 트리에 쓴다.)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_DIR = HERE / "state"


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def merge_uid_store(main: dict, ours: dict) -> dict:
    """entries.json·indepth.json — uid 합집합, 충돌은 main(op 수정) 우선."""
    merged = {"entries": dict(ours.get("entries") or {})}
    merged["entries"].update(main.get("entries") or {})
    # main에만 있는 그 밖의 키(혹시 모를 메타)도 지킨다.
    for key, value in main.items():
        if key != "entries":
            merged[key] = value
    return merged


def merge_attendance(main: dict, ours: dict) -> dict:
    merged = {
        "campaigns": main.get("campaigns") or ours.get("campaigns") or {},
        "months": {},
    }
    months = merged["months"]
    for month in sorted({*(ours.get("months") or {}), *(main.get("months") or {})}):
        o_rows = (ours.get("months") or {}).get(month, {})
        m_rows = (main.get("months") or {}).get(month, {})
        rows: dict = {}
        for name in {*o_rows, *m_rows}:
            o, m = o_rows.get(name), m_rows.get(name)
            if o is None or m is None:
                rows[name] = m or o
                continue
            # 충돌: 체크는 어느 쪽이든 true면 true, 본문은 텔레그램 출처 우선
            # (수동 토글엔 원문이 없다). 둘 다 같은 출처면 main(다른 run의 op) 우선.
            if o.get("source") == "telegram" and m.get("source") != "telegram":
                rich = o
            else:
                rich = m
            row = dict(rich)
            row["checked"] = bool(o.get("checked")) or bool(m.get("checked"))
            row["note"] = m.get("note") or o.get("note") or ""
            rows[name] = row
        months[month] = rows
    return merged


def merge_scan_state(main: dict, ours: dict) -> dict:
    merged = {"chats": {}}
    chats = merged["chats"]
    for src in (main.get("chats") or {}), (ours.get("chats") or {}):
        for key, chat in src.items():
            if key not in chats:
                chats[key] = dict(chat)
            else:
                if int(chat.get("last_id") or 0) > int(chats[key].get("last_id") or 0):
                    chats[key]["last_id"] = chat["last_id"]
                chats[key].setdefault("name", chat.get("name"))
    for key, value in main.items():
        if key != "chats":
            merged[key] = value
    return merged


MERGERS = {
    "entries.json": (merge_uid_store, {"entries": {}}),
    "indepth.json": (merge_uid_store, {"entries": {}}),
    "attendance.json": (merge_attendance, {"months": {}, "campaigns": {}}),
    "state.json": (merge_scan_state, {"chats": {}}),
}


def main(ours_dir: str) -> None:
    ours_path = Path(ours_dir)
    for fname, (merger, default) in MERGERS.items():
        ours_file = ours_path / fname
        if not ours_file.exists():
            continue
        main_doc = _load(STATE_DIR / fname, default)
        ours_doc = _load(ours_file, default)
        merged = merger(main_doc, ours_doc)
        (STATE_DIR / fname).write_text(
            json.dumps(merged, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8")
        print(f"[reconcile] {fname}: main+ours 병합")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("사용법: python reconcile_state.py <ours_dir>")
    main(sys.argv[1])
