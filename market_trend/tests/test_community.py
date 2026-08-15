"""커뮤니티 온도(네이버 종토) 파서·계량 테스트 — 네트워크 없음, HTML 픽스처 사용."""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import community_naver  # noqa: E402
import build_report  # noqa: E402
import telegram_send  # noqa: E402
import trend_daily  # noqa: E402

KST = timezone(timedelta(hours=9))

BOARD_HTML = """
<table class="type2">
<tr><th>날짜</th><th>제목</th><th>글쓴이</th><th>조회</th><th>공감</th><th>비공감</th></tr>
<tr onmouseover="">
 <td><span>2026.08.15 21:05</span></td>
 <td class="title"><a href="/item/board_read.naver?code=042660&nid=12345&st=&sw=&page=1">MRO 대박 가즈아</a></td>
 <td><span>개미1</span></td><td><span>1,234</span></td><td><strong>56</strong></td><td><strong>7</strong></td>
</tr>
<tr onmouseover="">
 <td><span>2026.08.15 20:00</span></td>
 <td class="title"><a href="/item/board_read.naver?code=042660&nid=12344">존스법 통과되면?</a></td>
 <td><span>개미2</span></td><td><span>567</span></td><td><strong>12</strong></td><td><strong>3</strong></td>
</tr>
<tr><td colspan="6">광고 행 — 링크 없음</td></tr>
</table>
"""

SEARCH_HTML = """
<table class="type_5">
<tr><td><a class="tltle" href="/item/main.naver?code=005930">삼성전자</a></td></tr>
<tr><td><a class="tltle" href="/item/main.naver?code=042660">한화오션</a></td></tr>
</table>
"""


class ParserTest(unittest.TestCase):
    def test_parse_board(self):
        posts = community_naver.parse_board(BOARD_HTML, "042660")
        self.assertEqual(len(posts), 2)
        first = posts[0]
        self.assertEqual(first["title"], "MRO 대박 가즈아")
        self.assertEqual(first["views"], 1234)
        self.assertEqual(first["likes"], 56)
        self.assertEqual(first["nid"], "12345")
        self.assertEqual(first["posted"].hour, 21)
        self.assertIn("code=042660", first["url"])

    def test_parse_search_top(self):
        from bs4 import BeautifulSoup  # noqa: F401 — bs4 필요 검증
        import re
        rows = []
        for a in __import__("bs4").BeautifulSoup(SEARCH_HTML, "html.parser").select("a.tltle"):
            m = re.search(r"code=(\d{6})", a.get("href", ""))
            if m:
                rows.append({"code": m.group(1), "name": a.get_text(strip=True)})
        self.assertEqual(rows[0], {"code": "005930", "name": "삼성전자"})
        self.assertEqual(rows[1]["name"], "한화오션")

    def test_decode_page_utf8_and_euckr(self):
        # 게시판(utf-8)과 검색상위(euc-kr)를 같은 판별기로 처리한다
        self.assertEqual(community_naver.decode_page("기다림은 배신하지 않는다".encode("utf-8")),
                         "기다림은 배신하지 않는다")
        self.assertEqual(community_naver.decode_page("삼성전자".encode("cp949")), "삼성전자")

    def test_alias_codes_from_config(self):
        codes = community_naver.alias_codes(trend_daily.load_config())
        self.assertEqual(codes.get("042660"), "한화오션")
        self.assertEqual(codes.get("005930"), "삼성전자")
        self.assertGreater(len(codes), 10)


class SignalTest(unittest.TestCase):
    def _history(self, per_day):
        return {"days": {f"2026-08-{i+1:02d}": entry for i, entry in enumerate(per_day)}}

    def test_stock_burst_over_baseline(self):
        history = self._history([{"stocks": {"042660": 10, "005930": 100}, "docs": 500}] * 7)
        rows = community_naver.stock_bursts(
            {"042660": 55, "005930": 105}, {"042660": "한화오션", "005930": "삼성전자"},
            set(), history, "2026-08-15")
        names = [r["name"] for r in rows]
        self.assertIn("한화오션", names)          # 5.5× 급증
        self.assertNotIn("삼성전자", names)       # 평소 수준은 탈락
        self.assertAlmostEqual(rows[0]["burst"], 5.5, places=1)

    def test_cold_start_by_count(self):
        rows = community_naver.stock_bursts({"042660": 55}, {"042660": "한화오션"},
                                            set(), {"days": {}}, "2026-08-15")
        self.assertIsNone(rows[0]["burst"])
        self.assertEqual(rows[0]["posts"], 55)


class RenderTest(unittest.TestCase):
    COMMUNITY = {
        "source": "네이버 종목토론실", "universe": 40, "posts": 800,
        "search_top": [{"code": "005930", "name": "삼성전자", "rank": 1}],
        "hot_stocks": [{"code": "042660", "name": "한화오션", "posts": 55,
                        "capped": False, "burst": 5.5, "base_daily": 10.0}],
        "keywords": [{"term": "존스법", "count": 12, "burst": 8.0, "new": True}],
        "top_liked": [{"code": "042660", "name": "한화오션", "title": "인기글 <b>제목</b>",
                       "views": 1234, "likes": 56, "url": "https://x", "time_kst": "08-15 21:05"}],
        "top_rising": [],
    }

    def test_report_renders_community(self):
        page = build_report.render_community(self.COMMUNITY)
        self.assertIn("커뮤니티 온도", page)
        self.assertIn("한화오션", page)
        self.assertIn("존스법", page)
        self.assertNotIn("<b>제목</b>", page)  # 제목 이스케이프

    def test_telegram_includes_community(self):
        payload = {"date": "2026-08-15", "stats": {}, "themes": [], "signals": {},
                   "community": self.COMMUNITY}
        msg = telegram_send.build_message(payload)
        self.assertIsNotNone(msg)  # 테마 없어도 커뮤니티가 있으면 보낸다
        self.assertIn("커뮤니티 온도", msg)
        self.assertIn("한화오션 5.5×", msg)


if __name__ == "__main__":
    unittest.main()
