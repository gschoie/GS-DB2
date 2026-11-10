import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collect as C

LIST_HTML = '''<ul class="researchList">
<li> <div class="tit anls2"> <img alt="x" class="thumnail_img" src="/img/research/default/anls2_01.jpg"/> <a href="javascript:view('66858', 'anls2', '산업분석');"> [인터넷/게임] [2027년 산업전망] 확장에서 결실로 </a> <img alt="새글" src="/img/common/new.gif"/> <p class="cont_txt">2027년 인터넷/SW 산업은 &amp; 수익성 개선.</p> </div> <div class=""> <p class="info"> <span class="gubun">산업분석</span> 김소혜 <span class="date">2026.10.30</span></p> </div> </li>
<li> <div class="tit anls1"> <a href="javascript:view('66857', 'anls1', '기업분석');"> [화장품] 에이피알[278470/Buy] 4분기부터 다시 서프라이즈 일텐데요… </a> <p class="cont_txt">에이피알의 3분기 매출액은 7,731억원.</p> </div> <div class=""> <p class="info"> <span class="gubun">기업분석</span> 한유정 <span class="date">2026.10.30</span></p> </div> </li>
<li> <div class="tit rpt_m1"> <a href="javascript:view('66847', 'rpt_m1', '주식전략');"> [주간 파생시황] 2026년 10월 26일~29일 </a> <p class="cont_txt">주간 파생 시황자료를 발간합니다.</p> </div> <div class=""> <p class="info"> <span class="gubun">주식전략</span> 투자전략팀 <span class="date">2026.10.30</span></p> </div> </li>
</ul>'''

DETAIL_HTML = '''<div class="researchDetail"> <div class="researchTit"> <div id="boardTitle"> [화장품] 에이피알[278470/Buy] 제목 </div></div>
<div class="researchCont"> <table><tbody><tr><td><p><strong>기대치를 하회한 3분기</strong></p></td></tr>
<tr><td><span>에이피알의 2026년 3분기 매출액은 7,731억원(+100.3% YoY)으로 컨센서스를 하회했다.<BR>투자의견 Buy, 목표주가 180,000원(기존 220,000원)을 하향한다.</span></td></tr></tbody></table>&nbsp;</div>
<!-- 홈페이지 개편 2차 --> <div class="fileTable"></div>
<script> var spJname="NHN,카카오게임즈"; var spJcode="181710,293490"; </script>'''


class ListTests(unittest.TestCase):
    def test_parse_list(self):
        items = C.parse_list(LIST_HTML)
        self.assertEqual([x['id'] for x in items], ['66858', '66857', '66847'])
        self.assertEqual(items[0]['analyst'], '김소혜'); self.assertEqual(items[0]['date'], '2026-10-30')
        self.assertEqual(items[0]['summary'], '2027년 인터넷/SW 산업은 & 수익성 개선.')
        self.assertEqual(items[1]['kind'], '기업분석'); self.assertEqual(items[2]['analyst'], '투자전략팀')

    def test_enrich(self):
        items = C.parse_list(LIST_HTML)
        r = C.enrich({**items[1], 'board': '1002'})
        self.assertEqual((r['sector'], r['company'], r['code'], r['opinion'], r['scope']), ('화장품', '에이피알', '278470', 'Buy', '기업'))
        s = C.enrich({**items[2], 'board': '1003'})
        self.assertEqual(s['sector'], '전략·경제'); self.assertTrue(s['routine']); self.assertEqual(s['scope'], '전략')
        i = C.enrich({**items[0], 'board': '1002'})
        self.assertEqual(i['scope'], '산업'); self.assertEqual(i['sector'], '인터넷/SW')


class DetailTests(unittest.TestCase):
    def test_parse_detail(self):
        d = C.parse_detail(DETAIL_HTML)
        self.assertIn('기대치를 하회한 3분기', d['body'])
        self.assertIn('목표주가 180,000원(기존 220,000원)', d['body'])
        self.assertNotIn('<', d['body'])
        self.assertEqual(d['related'], [('NHN', '181710'), ('카카오게임즈', '293490')])

    def test_cover_from_body(self):
        import parse as P
        cov = P.extract_cover(C.parse_detail(DETAIL_HTML)['body'])
        self.assertEqual((cov['opinion'], cov['tp'], cov['tp_prior'], cov['tp_change']), ('Buy', 180000, 220000, '하향'))

    def test_wanted(self):
        self.assertFalse(C.wanted({'date': '2024-12-31', 'depth3': 'anls1'}, '2025-01-01'))
        self.assertFalse(C.wanted({'date': '2026-01-01', 'depth3': 'anls19'}, '2025-01-01'))
        self.assertTrue(C.wanted({'date': '2026-01-01', 'depth3': 'anls1'}, '2025-01-01'))


if __name__ == '__main__':
    unittest.main()
