# -*- coding: utf-8 -*-
"""장 시작 전 보관 검산.

꼭 잡아야 하는 것
  · **켠 소스만 적는다** — premarket: true 가 없는 소스까지 적으면 매크로 화면에
    조선 뉴스가 섞인다.
  · **같은 uid 는 덮어쓴다** — 채널에서 글을 고쳐 올리면 옛 판이 남아 봇과 화면이
    어긋난다.
  · **오래된 건 버린다** — 장 시작 전 글은 당일치만 쓸모가 있고, 안 버리면 파일이
    계속 자란다(커밋되는 파일이다).
  · **깨진 파일에 죽지 않는다** — 읽기 실패는 빈 목록이어야 화면이 섹션만 생략한다.
"""
import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import premarket  # noqa: E402

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 15, 7, 40, tzinfo=KST)
SRC = {"key": "hanwha_5things", "name": "한화 임혜윤 · 개장전 5가지", "premarket": True}


@dataclass
class Item:
    uid: str
    title: str = "제목"
    url: str = "https://t.me/lim_econ/1"
    body: str = "본문"
    published_at: datetime = None


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "premarket.json"

    def rec(self, src, items, now=NOW):
        return premarket.record(src, items, now, self.tmp)


class TestRecord(Base):
    def test_writes_only_when_enabled(self):
        self.assertEqual(self.rec({"key": "mer", "name": "메르"}, [Item("a")]), 0)
        self.assertFalse(self.tmp.exists())
        self.assertEqual(self.rec(SRC, [Item("a")]), 1)
        self.assertEqual(len(premarket.load(self.tmp)), 1)

    def test_empty_items_write_nothing(self):
        self.assertEqual(self.rec(SRC, []), 0)
        self.assertFalse(self.tmp.exists())

    def test_carries_the_fields_the_screen_needs(self):
        self.rec(SRC, [Item("a", title="5가지_10/15", url="u", body="① …")])
        got = premarket.load(self.tmp)[0]
        self.assertEqual(got["name"], SRC["name"])
        self.assertEqual(got["title"], "5가지_10/15")
        self.assertEqual(got["body"], "① …")
        self.assertEqual(got["url"], "u")
        self.assertEqual(got["uid"], "a")

    def test_same_uid_is_replaced_not_duplicated(self):
        self.rec(SRC, [Item("a", body="처음")])
        self.rec(SRC, [Item("a", body="고친 글")], NOW + timedelta(minutes=20))
        got = premarket.load(self.tmp)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["body"], "고친 글")

    def test_newest_first(self):
        self.rec(SRC, [Item("a", published_at=NOW - timedelta(days=1))])
        self.rec(SRC, [Item("b", published_at=NOW)])
        self.assertEqual([o["uid"] for o in premarket.load(self.tmp)], ["b", "a"])

    def test_old_entries_dropped(self):
        old = NOW - timedelta(days=premarket.KEEP_DAYS + 1)
        self.rec(SRC, [Item("old", published_at=old)], old)
        self.rec(SRC, [Item("new", published_at=NOW)])
        self.assertEqual([o["uid"] for o in premarket.load(self.tmp)], ["new"])

    def test_uses_published_at_when_present(self):
        self.rec(SRC, [Item("a", published_at=datetime(2026, 10, 15, 7, 36, tzinfo=KST))])
        self.assertTrue(premarket.load(self.tmp)[0]["at"].startswith("2026-10-15T07:36"))

    def test_falls_back_to_now_without_published_at(self):
        self.rec(SRC, [Item("a")])
        self.assertTrue(premarket.load(self.tmp)[0]["at"].startswith("2026-10-15T07:40"))

    def test_long_body_is_capped(self):
        self.rec(SRC, [Item("a", body="가" * (premarket.BODY_CAP + 500))])
        self.assertEqual(len(premarket.load(self.tmp)[0]["body"]), premarket.BODY_CAP)


class TestLoad(Base):
    def test_missing_file(self):
        self.assertEqual(premarket.load(self.tmp), [])

    def test_broken_json_does_not_raise(self):
        self.tmp.parent.mkdir(parents=True, exist_ok=True)
        self.tmp.write_text("{깨진", encoding="utf-8")
        self.assertEqual(premarket.load(self.tmp), [])

    def test_unexpected_shape(self):
        self.tmp.parent.mkdir(parents=True, exist_ok=True)
        self.tmp.write_text(json.dumps({"items": "문자열"}), encoding="utf-8")
        self.assertEqual(premarket.load(self.tmp), [])

    def test_row_without_date_is_dropped_on_next_write(self):
        self.tmp.parent.mkdir(parents=True, exist_ok=True)
        self.tmp.write_text(json.dumps({"items": [{"uid": "x"}]}), encoding="utf-8")
        self.rec(SRC, [Item("a")])
        self.assertEqual([o["uid"] for o in premarket.load(self.tmp)], ["a"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
