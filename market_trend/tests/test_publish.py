"""리포트 페이지·텔레그램 발송의 렌더링 테스트 (네트워크 없음)."""

import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import build_report  # noqa: E402
import telegram_send  # noqa: E402

PAYLOAD = {
    "date": "2026-08-13",
    "meta": {"window": "08-12 06:00~08-13 06:00 KST", "engine": "Gemini(flash)"},
    "stats": {"channels": 30, "messages": 500, "groups": 400},
    "one_liner": "한 줄 요약",
    "themes": [{
        "name": "조선 — MRO 기대", "narrative": "내러티브 문장.", "status": "new",
        "strength": 4, "keywords": ["존스법", "한화오션"],
        "evidence": [{"channel": "채널A", "quote": "인용문 <b>태그</b>"}],
    }],
    "signals": {
        "spikes": [{"term": "존스법", "count": 8, "burst": 12.3, "base_daily": 0.3, "new": True}],
        "top_posts": [{"channels": 5, "channel": "채널A", "head": "머리글", "url": "https://t.me/x/1", "time_kst": "08-13 01:00"}],
    },
}


class BuildReportTest(unittest.TestCase):
    def test_render_day_escapes_and_includes(self):
        page = build_report.render_day(PAYLOAD)
        self.assertIn("조선 — MRO 기대", page)
        self.assertIn("한 줄 요약", page)
        self.assertIn("존스법", page)
        # 발췌 속 HTML은 이스케이프되어야 한다(iframe 안 스크립트 주입 방지)
        self.assertNotIn("<b>태그</b>", page)
        self.assertIn("&lt;b&gt;태그&lt;/b&gt;", page)

    def test_render_day_no_llm(self):
        bare = {**PAYLOAD, "one_liner": None, "themes": []}
        page = build_report.render_day(bare)
        self.assertIn("계량 신호만", page)
        self.assertIn("존스법", page)


class TelegramSendTest(unittest.TestCase):
    def test_message_with_themes(self):
        msg = telegram_send.build_message(PAYLOAD)
        self.assertIn("시장관심.내러티브", msg)
        self.assertIn("조선 — MRO 기대", msg)
        self.assertIn("🆕", msg)
        self.assertIn("대시보드", msg)

    def test_message_falls_back_to_spikes(self):
        msg = telegram_send.build_message({**PAYLOAD, "themes": []})
        self.assertIn("급증 키워드", msg)
        self.assertIn("존스법", msg)

    def test_message_none_when_empty(self):
        self.assertIsNone(telegram_send.build_message(
            {**PAYLOAD, "themes": [], "signals": {"spikes": []}}))

    def test_split_chunks_on_theme_boundary(self):
        text = "\n\n".join(f"블록 {i} " + "가" * 500 for i in range(20))
        chunks = telegram_send.split_chunks(text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= telegram_send.CHUNK_LIMIT + 12 for c in chunks))
        self.assertTrue(chunks[0].endswith(f"(1/{len(chunks)})"))


if __name__ == "__main__":
    unittest.main()
