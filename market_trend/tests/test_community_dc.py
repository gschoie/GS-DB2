"""갤러리 온도(DC인사이드) 파서·렌더링 테스트 — 네트워크 없음, HTML 픽스처 사용."""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import community_dc  # noqa: E402
import build_report  # noqa: E402
import telegram_send  # noqa: E402

KST = timezone(timedelta(hours=9))

LIST_HTML = """
<table class="gall_list">
<tbody>
<tr class="ub-content us-post" data-no="999">
 <td class="gall_num">공지</td>
 <td class="gall_tit ub-word"><a href="/board/view/?id=stock_new2&no=999">공지사항</a></td>
 <td class="gall_date" title="2026-08-16 09:00:00">09:00</td>
 <td class="gall_count">10</td><td class="gall_recommend">0</td>
</tr>
<tr class="ub-content us-post" data-no="101">
 <td class="gall_num">101</td>
 <td class="gall_tit ub-word"><a href="/board/view/?id=stock_new2&no=101&page=1">존스법 통과 임박 &lt;b&gt;소식&lt;/b&gt;</a>
   <a class="reply_numbox"><span class="reply_num">[12]</span></a></td>
 <td class="gall_writer">ㅇㅇ</td>
 <td class="gall_date" title="2026-08-16 03:33:02">03:33</td>
 <td class="gall_count">1,540</td>
 <td class="gall_recommend">88</td>
</tr>
<tr class="ub-content us-post" data-no="100">
 <td class="gall_num">100</td>
 <td class="gall_tit ub-word"><a href="/board/view/?id=stock_new2&no=100">어제 산 종목 후기</a></td>
 <td class="gall_writer">ㅇㅇ</td>
 <td class="gall_date" title="2026-08-16 02:10:00">02:10</td>
 <td class="gall_count">230</td>
 <td class="gall_recommend">3</td>
</tr>
</tbody>
</table>
"""

GALLERY = {"id": "stock_new2", "name": "주식갤러리"}


class ParserTest(unittest.TestCase):
    def test_parse_list(self):
        posts = community_dc.parse_list(LIST_HTML, GALLERY)
        self.assertEqual(len(posts), 2)  # 공지 행 제외
        first = posts[0]
        self.assertIn("존스법", first["title"])
        self.assertEqual(first["views"], 1540)
        self.assertEqual(first["recommend"], 88)
        self.assertEqual(first["posted"].hour, 3)
        self.assertTrue(first["url"].startswith("https://gall.dcinside.com/board/view/"))
        self.assertEqual(first["gallery"], "주식갤러리")

    def test_gallery_url_minor(self):
        self.assertIn("/mgallery/board/", community_dc.gallery_url(
            {"id": "stockus", "name": "해외", "minor": True}, 1))
        self.assertIn("/board/", community_dc.gallery_url(GALLERY, 2))
        self.assertIn("exception_mode=recommend", community_dc.gallery_url(GALLERY, 1, recommend=True))


class RenderTest(unittest.TestCase):
    DC = {
        "source": "DC인사이드", "posts_sampled": 300,
        "galleries": [{"id": "stock_new2", "name": "주식갤러리", "posts": 4200,
                       "capped": True, "burst": 1.8, "base_daily": 2300.0}],
        "keywords": [{"term": "존스법", "count": 9, "burst": 7.0, "new": True}],
        "top_recommended": [{"gallery": "주식갤러리", "title": "개념글 <script>제목",
                             "views": 1540, "recommend": 88, "url": "https://x", "time_kst": "08-16 03:33"}],
        "top_viewed": [{"gallery": "주식갤러리", "title": "화제글", "views": 900,
                        "recommend": 2, "url": "https://y", "time_kst": "08-16 04:00"}],
    }

    def test_report_renders_dc(self):
        page = build_report.render_dc(self.DC)
        self.assertIn("갤러리 온도", page)
        self.assertIn("≈4,200", page)
        self.assertIn("존스법", page)
        self.assertIn("화제의 글", page)
        self.assertNotIn("<script>", page)  # 제목 이스케이프

    def test_telegram_includes_dc(self):
        payload = {"date": "2026-08-16", "stats": {}, "themes": [], "signals": {},
                   "community_dc": self.DC}
        msg = telegram_send.build_message(payload)
        self.assertIsNone(msg)  # 테마·신호·종토가 없으면 디시만으로는 발송하지 않는다
        payload["community"] = {"hot_stocks": [{"name": "한화오션", "posts": 55, "burst": None}]}
        msg = telegram_send.build_message(payload)
        self.assertIn("갤러리", msg)
        self.assertIn("존스법", msg)
        self.assertIn("개념글", msg)


if __name__ == "__main__":
    unittest.main()
