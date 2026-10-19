"""research_digest의 본문 파싱·표시 검사 — 실제 채널 형식(10/19 실측)을 가짜 본문으로 검산."""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import adapters
import research_digest as rd

SUMMARY_BODY = (
    "[✨ 리서치 요약] 쎄트렉아이 목표주가 하향 리포트 요약\n"
    "\n"
    "목표주가 하향 | 쎄트렉아이 | \"[혁신성장] 변동성에 대응하는 방법 - 기업\"\n"
    "목표주가 210,000원 >> 100,000원 | 투자의견 매수-유지 | 신한투자증권\n"
    "\n"
    "✅ 목표주가 하향 주요 요약\n"
    "- 3Q26 매출액 652억원(+29.3%) 전망\n"
)


def summary_item(body: str = SUMMARY_BODY) -> adapters.Item:
    return adapters.Item(
        uid="1:1", title=body.splitlines()[0], url="https://t.me/x/1", body=body,
        published_at=datetime(2026, 10, 18, 23, 0, tzinfo=timezone.utc), origin="epic AI",
    )


class SummaryDetailTest(unittest.TestCase):
    def test_parses_title_broker_tp(self):
        detail = rd.summary_detail(SUMMARY_BODY)
        self.assertEqual(detail["title"], "[혁신성장] 변동성에 대응하는 방법 - 기업")
        self.assertEqual(detail["company"], "쎄트렉아이")
        self.assertEqual(detail["broker"], "신한투자증권")
        self.assertEqual(detail["tp"], "목표주가 210,000원 → 100,000원")

    def test_curly_quotes_also_count(self):
        body = SUMMARY_BODY.replace('"[혁신성장] 변동성에 대응하는 방법 - 기업"',
                                    "“제목”")
        self.assertEqual(rd.summary_detail(body)["title"], "제목")

    def test_unknown_format_returns_none(self):
        self.assertIsNone(rd.summary_detail("제목 줄\n그냥 요약 문장들\n- 포인트"))
        self.assertIsNone(rd.summary_detail(""))

    def test_tp_line_alone_is_not_enough(self):
        # 리포트 제목(따옴표 칸)을 못 찾으면 None — 표시는 기존 첫 줄로 폴백한다
        body = "제목\n목표주가 10,000원 >> 9,000원 | 투자의견 매수 | 증권사"
        self.assertIsNone(rd.summary_detail(body))


class BuildDigestTest(unittest.TestCase):
    def setUp(self):
        self.groups = rd.ws.keyword_groups({"방산": ["쎄트렉아이"]})
        self.now = datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc)

    def test_summary_line_shows_report_title(self):
        text, count = rd.build_digest([summary_item()], self.groups, self.now)
        self.assertEqual(count, 1)
        self.assertIn("“[혁신성장] 변동성에 대응하는 방법 - 기업”", text)
        self.assertIn("신한투자증권", text)
        self.assertIn("목표주가 210,000원 → 100,000원", text)
        self.assertNotIn("리포트 요약", text.split("\n\n", 1)[1])  # 옛 표시 제목은 사라진다

    def test_fallback_keeps_old_title_when_body_unreadable(self):
        body = "[✨ 리서치 요약] 쎄트렉아이 목표주가 하향 리포트 요약\n형식이 바뀐 본문"
        text, count = rd.build_digest([summary_item(body)], self.groups, self.now)
        self.assertEqual(count, 1)
        self.assertIn("쎄트렉아이 목표주가 하향 리포트 요약", text)

    def test_list_entry_untouched(self):
        # 아침 목록 항목(분해된 한 줄)은 summary_detail을 타지 않는다
        item = adapters.Item(
            uid="2:2#0", title="쎄트렉아이 | 100,000 | 신한투자증권", url="",
            body="쎄트렉아이 | 100,000 | 신한투자증권",
            published_at=self.now, origin="summary",
        )
        text, count = rd.build_digest([item], self.groups, self.now)
        self.assertEqual(count, 1)
        self.assertIn("쎄트렉아이 | 100,000 | 신한투자증권", text)


if __name__ == "__main__":
    unittest.main()
