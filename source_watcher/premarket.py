# -*- coding: utf-8 -*-
"""장 시작 전 코멘트 보관 — 텔레그램으로 나간 글을 화면에서도 보게 한다.

watch_sources 는 받아서 **쏘기만** 하고 본문을 남기지 않았다(seen.json 은 본 ID뿐).
그래서 개장전 코멘트를 매크로 데스크에 띄우려면 본문을 따로 적어 둬야 한다.

**텔레그램에 나간 것만 적는다**(`to_send`). 수집한 것 전부가 아니라 실제로 보낸 것만
남겨야 봇에 온 것과 화면이 어긋나지 않는다 — 유튜브 3일 모음에서 쓴 원칙과 같다.

소스는 `sources.yml` 에서 `premarket: true` 로 켠다. 태그(`개장전`)가 아니라 별도
필드인 이유: 태그는 화면 표시용이라 누가 바꿔도 되는 값이고, 이건 **저장 여부**를
가르는 스위치라 뜻이 섞이면 안 된다.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PATH = BASE_DIR / "state" / "premarket.json"

# 장 시작 전 글은 당일에만 쓸모가 있다. 며칠치만 남겨 파일이 무한정 자라지 않게 한다
# (화면은 보통 맨 위 한두 건만 본다).
KEEP_DAYS = 7
# 본문이 아주 긴 글(블룸버그 5가지 전문 등)도 있어 상한을 둔다. 잘릴 때는 원문 링크로.
BODY_CAP = 6000


def load(path: Path = PATH) -> list[dict]:
    """최신 글이 앞. 파일이 없거나 깨졌으면 빈 목록(화면은 섹션을 통째로 생략한다)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


def _at(item, now: datetime) -> str:
    when = getattr(item, "published_at", None) or now
    return when.isoformat()


def record(source: dict, items: list, now: datetime, path: Path = PATH) -> int:
    """보낸 글을 보관 파일에 더한다. 더해진 건수를 돌려준다.

    같은 uid 가 다시 오면 **새 내용으로 덮어쓴다** — 채널에서 글을 고쳐 올리는 일이
    있어서, 오래된 판을 남겨두면 화면과 봇이 어긋난다.
    """
    if not source.get("premarket") or not items:
        return 0

    keep_after = now - timedelta(days=KEEP_DAYS)
    kept = []
    for old in load(path):
        try:
            if datetime.fromisoformat(old["at"]) < keep_after:
                continue
        except (KeyError, TypeError, ValueError):
            continue                      # 날짜를 못 읽는 줄은 버린다(되살릴 근거가 없다)
        kept.append(old)

    fresh_uids = {getattr(it, "uid", None) for it in items}
    kept = [o for o in kept if o.get("uid") not in fresh_uids]

    added = [{
        "uid": item.uid,
        "key": source["key"],
        "name": source.get("name") or source["key"],
        "title": (item.title or "").strip(),
        "url": item.url or "",
        "body": (item.body or "").strip()[:BODY_CAP],
        "at": _at(item, now),
    } for item in items]

    merged = sorted(kept + added, key=lambda o: o.get("at", ""), reverse=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"items": merged}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return len(added)
