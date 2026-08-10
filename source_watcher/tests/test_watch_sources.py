"""source_watcher 계약 테스트. 네트워크를 타지 않는다."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import adapters  # noqa: E402
import notify  # noqa: E402
import watch_sources as ws  # noqa: E402

NOW = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)


def make_args(**overrides) -> Namespace:
    base = dict(check=False, dry_run=False, seed=False, max=None)
    base.update(overrides)
    return Namespace(**base)


def make_source(**overrides) -> dict:
    source = {**ws.DEFAULTS, "key": "s1", "name": "테스트", "type": "rss", "url": "http://x"}
    source.update(overrides)
    return source


def item(uid: str, *, title="제목", body="본문", url="http://x/1", hours_ago=1) -> adapters.Item:
    return adapters.Item(
        uid=uid, title=title, body=body, url=url,
        published_at=NOW - timedelta(hours=hours_ago),
    )


class FeedParsingTest(unittest.TestCase):
    def test_rss_item_fields(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel>
          <title>메르의 블로그</title>
          <item>
            <title>환율 이야기</title>
            <link>https://blog.naver.com/ranto28/223</link>
            <description>&lt;p&gt;원달러가 &lt;b&gt;올랐다&lt;/b&gt;&lt;/p&gt;</description>
            <pubDate>Sun, 09 Aug 2026 22:30:00 +0900</pubDate>
            <guid>https://blog.naver.com/ranto28/223</guid>
          </item>
        </channel></rss>"""
        items = adapters.parse_feed(xml)
        self.assertEqual(len(items), 1)
        entry = items[0]
        self.assertEqual(entry.title, "환율 이야기")
        self.assertEqual(entry.url, "https://blog.naver.com/ranto28/223")
        self.assertEqual(entry.uid, "https://blog.naver.com/ranto28/223")
        # description의 HTML은 벗겨서 평문으로 들어와야 한다
        self.assertEqual(entry.body, "원달러가 올랐다")
        self.assertEqual(entry.published_at, datetime(2026, 8, 9, 13, 30, tzinfo=timezone.utc))

    def test_atom_entry_uses_alternate_link(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>Atom 글</title>
            <link rel="alternate" href="https://example.com/a"/>
            <id>tag:example.com,2026:1</id>
            <updated>2026-08-09T10:00:00Z</updated>
            <summary>요약</summary>
          </entry>
        </feed>"""
        entry = adapters.parse_feed(xml)[0]
        self.assertEqual(entry.url, "https://example.com/a")
        self.assertEqual(entry.uid, "tag:example.com,2026:1")
        self.assertEqual(entry.published_at, datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc))

    def test_feed_without_date_survives(self):
        xml = "<rss><channel><item><title>날짜 없음</title><link>http://a/1</link></item></channel></rss>"
        entry = adapters.parse_feed(xml)[0]
        self.assertIsNone(entry.published_at)


class TelegramParsingTest(unittest.TestCase):
    PAGE = """
    <div class="tgme_widget_message_wrap">
      <div class="tgme_widget_message" data-post="hanwha/1234">
        <div class="tgme_widget_message_text js-message_text">개장전 꼭 알아야할 5가지<br>1. 연준</div>
        <time datetime="2026-08-09T22:10:00+00:00"></time>
      </div>
    </div>
    <div class="tgme_widget_message_wrap">
      <div class="tgme_widget_message" data-post="hanwha/1235">
        <div class="tgme_widget_message_reply js-message_reply_text">원글 인용</div>
        <div class="tgme_widget_message_text js-message_text">종목 리포트</div>
        <time datetime="2026-08-09T23:00:00+00:00"></time>
      </div>
    </div>
    """

    def test_parses_uid_url_and_body(self):
        items = adapters.parse_telegram_page(self.PAGE, "hanwha")
        self.assertEqual([entry.uid for entry in items], ["hanwha:1234", "hanwha:1235"])
        self.assertEqual(items[0].url, "https://t.me/hanwha/1234")
        self.assertEqual(items[0].body, "개장전 꼭 알아야할 5가지\n1. 연준")
        self.assertEqual(items[0].title, "개장전 꼭 알아야할 5가지")

    def test_reply_quote_is_not_body(self):
        # 답글 인용문이 본문에 섞이면 원글 요약이 그대로 발송된다
        self.assertEqual(adapters.parse_telegram_page(self.PAGE, "hanwha")[1].body, "종목 리포트")

    def test_normalize_channel(self):
        for raw in ["@hanwha", "https://t.me/hanwha", "t.me/s/hanwha", "hanwha", "https://t.me/hanwha/"]:
            self.assertEqual(adapters.normalize_channel(raw), "hanwha", raw)


class RegistryTest(unittest.TestCase):
    def write(self, text: str) -> Path:
        path = Path(tempfile.mkdtemp()) / "sources.yml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_defaults_are_merged_and_overridable(self):
        path = self.write(
            "defaults:\n  max_per_run: 2\n"
            "sources:\n"
            "  - key: a\n    name: A\n    type: rss\n    url: http://a\n"
            "  - key: b\n    name: B\n    type: rss\n    url: http://b\n    max_per_run: 9\n"
        )
        a, b = ws.load_registry(path)
        self.assertEqual(a["max_per_run"], 2)
        self.assertEqual(b["max_per_run"], 9)
        self.assertTrue(a["enabled"])  # 기본값

    def test_duplicate_key_is_rejected(self):
        path = self.write(
            "sources:\n"
            "  - key: a\n    type: rss\n    url: http://a\n"
            "  - key: a\n    type: rss\n    url: http://b\n"
        )
        with self.assertRaises(ValueError):
            ws.load_registry(path)

    def test_missing_key_is_rejected(self):
        path = self.write("sources:\n  - name: 이름만\n    type: rss\n    url: http://a\n")
        with self.assertRaises(ValueError):
            ws.load_registry(path)

    def test_shipped_registry_loads(self):
        # 실제 sources.yml이 깨지면 봇이 통째로 죽는다
        sources = ws.load_registry(ws.REGISTRY_PATH)
        self.assertTrue(sources)
        for source in sources:
            self.assertIn(source["type"], adapters.COLLECTORS)


class SelectTest(unittest.TestCase):
    def state_with(self, seen: list[str]) -> dict:
        return {"version": 1, "sources": {"s1": {"seen": seen}}}

    def test_seen_items_are_dropped(self):
        source = make_source()
        picked = ws.select(source, [item("a"), item("b")], self.state_with(["a"]), NOW)
        self.assertEqual([entry.uid for entry in picked], ["b"])

    def test_match_and_exclude(self):
        source = make_source(match="개장전", exclude="광고")
        items = [item("a", title="개장전 5가지"), item("b", title="종목분석"),
                 item("c", title="개장전 광고")]
        picked = ws.select(source, items, self.state_with([]), NOW)
        self.assertEqual([entry.uid for entry in picked], ["a"])

    def test_lookback_filters_old_posts(self):
        source = make_source(lookback_hours=24)
        items = [item("old", hours_ago=100), item("new", hours_ago=2)]
        picked = ws.select(source, items, self.state_with([]), NOW)
        self.assertEqual([entry.uid for entry in picked], ["new"])

    def test_undated_items_survive_lookback(self):
        source = make_source(lookback_hours=24)
        undated = adapters.Item(uid="u", title="t", body="b", url="", published_at=None)
        self.assertEqual(len(ws.select(source, [undated], self.state_with([]), NOW)), 1)

    def test_ordered_oldest_first(self):
        source = make_source()
        items = [item("new", hours_ago=1), item("old", hours_ago=5)]
        picked = ws.select(source, items, self.state_with([]), NOW)
        self.assertEqual([entry.uid for entry in picked], ["old", "new"])


class StateTest(unittest.TestCase):
    def test_remember_caps_and_dedupes(self):
        state = {"version": 1, "sources": {}}
        ws.remember(state, "s1", [f"u{i}" for i in range(ws.SEEN_CAP + 50)], NOW, pushed=True)
        seen = state["sources"]["s1"]["seen"]
        self.assertEqual(len(seen), ws.SEEN_CAP)
        self.assertEqual(seen[-1], f"u{ws.SEEN_CAP + 49}")  # 최신이 남는다
        ws.remember(state, "s1", ["u10"], NOW, pushed=False)
        self.assertEqual(state["sources"]["s1"]["seen"].count("u10"), 1)

    def test_roundtrip(self):
        path = Path(tempfile.mkdtemp()) / "nested" / "seen.json"
        state = {"version": 1, "sources": {"s1": {"seen": ["한글uid"]}}}
        ws.save_state(state, path)
        self.assertEqual(ws.load_state(path), state)
        self.assertIn("한글uid", path.read_text(encoding="utf-8"))  # ensure_ascii=False

    def test_missing_state_file_is_empty(self):
        self.assertEqual(ws.load_state(Path(tempfile.mkdtemp()) / "none.json"), {"version": 1, "sources": {}})


class RunSourceTest(unittest.TestCase):
    def setUp(self):
        self.sent: list[str] = []
        self.collected: list[adapters.Item] = []
        self._collect, self._send = adapters.collect, notify.send
        adapters.collect = lambda source: list(self.collected)
        notify.send = lambda text, **kwargs: self.sent.append(text) or 1

    def tearDown(self):
        adapters.collect, notify.send = self._collect, self._send

    def test_first_run_seeds_without_sending(self):
        # 첫 실행에 피드 전체를 쏘면 수십 통이 한꺼번에 온다
        self.collected = [item("a"), item("b")]
        state = {"version": 1, "sources": {}}
        sent = ws.run_source(make_source(), state, NOW, make_args())
        self.assertEqual(sent, 0)
        self.assertEqual(self.sent, [])
        self.assertEqual(set(state["sources"]["s1"]["seen"]), {"a", "b"})

    def test_second_run_sends_only_new(self):
        state = {"version": 1, "sources": {"s1": {"seen": ["a"]}}}
        self.collected = [item("a"), item("b", title="새 글")]
        sent = ws.run_source(make_source(), state, NOW, make_args())
        self.assertEqual(sent, 1)
        self.assertIn("새 글", self.sent[0])
        self.assertIn("b", state["sources"]["s1"]["seen"])

    def test_capped_overflow_is_marked_seen(self):
        # 상한에 걸려 못 보낸 글을 읽음 처리하지 않으면 다음 실행에서 다시 밀려온다
        state = {"version": 1, "sources": {"s1": {"seen": []}}}
        self.collected = [item(f"u{i}", hours_ago=10 - i) for i in range(5)]
        sent = ws.run_source(make_source(max_per_run=2), state, NOW, make_args())
        self.assertEqual(sent, 2)
        self.assertEqual(set(state["sources"]["s1"]["seen"]), {f"u{i}" for i in range(5)})
        # 최신 2건이 발송된다
        self.assertEqual(len(self.sent), 2)

    def test_dry_run_reports_but_sends_nothing_and_keeps_state(self):
        # 발송 대상이 있는 상태에서 아무것도 나가지 않고 읽음 처리도 되지 않아야 한다
        state = {"version": 1, "sources": {"s1": {"seen": []}}}
        self.collected = [item("a"), item("b")]
        reported = ws.run_source(make_source(), state, NOW, make_args(dry_run=True))
        self.assertEqual(reported, 2)
        self.assertEqual(self.sent, [])
        self.assertEqual(state["sources"]["s1"]["seen"], [])

    def test_seed_marks_all_read_without_sending(self):
        state = {"version": 1, "sources": {"s1": {"seen": []}}}
        self.collected = [item("a"), item("b")]
        self.assertEqual(ws.run_source(make_source(), state, NOW, make_args(seed=True)), 0)
        self.assertEqual(self.sent, [])
        self.assertEqual(set(state["sources"]["s1"]["seen"]), {"a", "b"})

    def test_collect_failure_does_not_stop_run(self):
        def boom(source):
            raise RuntimeError("네트워크 실패")

        adapters.collect = boom
        state = {"version": 1, "sources": {"s1": {"seen": []}}}
        self.assertEqual(ws.run_source(make_source(), state, NOW, make_args()), 0)

    def test_check_mode_sends_nothing(self):
        self.collected = [item("a")]
        state = {"version": 1, "sources": {}}
        ws.run_source(make_source(), state, NOW, make_args(check=True))
        self.assertEqual(self.sent, [])
        self.assertEqual(state["sources"], {})


class RenderTest(unittest.TestCase):
    def test_excerpt_mode_has_title_and_link(self):
        source = make_source(type="rss", tags=["블로그"], excerpt_chars=20)
        text = ws.render(source, item("a", title="환율 이야기", body="가" * 100, url="http://a/1"))
        self.assertIn("<b>환율 이야기</b>", text)
        self.assertIn("#블로그", text)
        self.assertIn('<a href="http://a/1">', text)
        self.assertIn("…", text)  # 잘렸다

    def test_full_mode_does_not_repeat_title(self):
        source = make_source(type="telegram")
        body = "개장전 5가지\n1. 연준"
        text = ws.render(source, item("a", title="개장전 5가지", body=body))
        self.assertEqual(text.count("개장전 5가지"), 1)

    def test_body_html_is_escaped(self):
        source = make_source(type="telegram")
        text = ws.render(source, item("a", body="<b>주의</b> a<b"))
        self.assertIn("&lt;b&gt;주의&lt;/b&gt;", text)

    def test_kst_timestamp(self):
        source = make_source()
        entry = adapters.Item(uid="a", title="t", body="b", url="",
                              published_at=datetime(2026, 8, 9, 22, 10, tzinfo=timezone.utc))
        self.assertIn("2026-08-10 07:10 KST", ws.render(source, entry))


class ChunkTest(unittest.TestCase):
    def test_short_text_is_one_chunk(self):
        self.assertEqual(notify.split_chunks("짧은 글"), ["짧은 글"])

    def test_splits_on_paragraph_boundary(self):
        text = "\n\n".join(["가" * 100 for _ in range(10)])
        chunks = notify.split_chunks(text, limit=250)
        self.assertTrue(all(len(chunk) <= 250 for chunk in chunks))
        self.assertEqual("".join(chunks).replace("\n", ""), text.replace("\n", ""))

    def test_splits_unbroken_run(self):
        chunks = notify.split_chunks("가" * 1000, limit=100)
        self.assertTrue(all(len(chunk) <= 100 for chunk in chunks))
        self.assertEqual("".join(chunks), "가" * 1000)


class StripHtmlTest(unittest.TestCase):
    def test_br_and_block_tags_become_newlines(self):
        self.assertEqual(adapters.strip_html("<p>가</p><p>나</p>"), "가\n나")
        self.assertEqual(adapters.strip_html("가<br/>나"), "가\n나")

    def test_entities_and_nbsp(self):
        self.assertEqual(adapters.strip_html("A&amp;B&nbsp;C"), "A&B C")


if __name__ == "__main__":
    unittest.main(verbosity=2)
