import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hankyung as H

LIST = '''<table><tr><th>작성일</th><th>분류</th><th>제목</th><th>작성자</th><th>제공출처</th><th>첨부파일</th></tr>
<tr><td>2026-10-30</td><td>기업</td><td><a href="/analysis/downpdf?report_idx=653540"> 한화에어로스페이스(012450) 3Q26 Review: 기대치 하회. 이제는 용기를 낼 시점</a><span>한화에어로스페이스(012450) 3Q26 Review: 기대치 하회. 이제는 용기를 낼 시점</span><em>3Q26 Review: 기대치 하회.</em></td><td>채운샘</td><td>한화투자증권</td><td><a href="/analysis/downpdf?report_idx=653540">pdf</a></td></tr>
<tr><td>2026-10-30</td><td>시장</td><td><a href="/analysis/downpdf?report_idx=653505"> 한화 주간전략</a></td><td>투자전략팀</td><td>한화투자증권</td><td><a href="/analysis/downpdf?report_idx=653505">pdf</a></td></tr>
<tr><td>2026-10-30</td><td>기업</td><td><a href="/analysis/downpdf?report_idx=653531"> 한화에어로스페이스(012450) 3Q26: 그래도 믿는다</a></td><td>변용진, 이주원</td><td>iM증권</td><td><a href="/analysis/downpdf?report_idx=653531">pdf</a></td></tr>
</table>'''


class ParseTests(unittest.TestCase):
    def test_rows(self):
        rows = H.parse_list(LIST)
        self.assertEqual([r['idx'] for r in rows], ['653540', '653505', '653531'])
        r = rows[0]
        self.assertEqual((r['company'], r['code'], r['analyst'], r['broker']), ('한화에어로스페이스', '012450', '채운샘', '한화투자증권'))
        self.assertEqual(r['subject'], '3Q26 Review: 기대치 하회. 이제는 용기를 낼 시점')
        self.assertEqual(r['pdf_url'], 'https://consensus.hankyung.com/analysis/downpdf?report_idx=653540')
        self.assertEqual(rows[1]['company'], ''); self.assertEqual(rows[2]['broker'], 'iM증권')

    def test_month_windows(self):
        from datetime import date
        w = list(H.month_windows('2025-01-15', date(2025, 3, 10)))
        self.assertEqual(w, [('2025-01-15', '2025-01-31'), ('2025-02-01', '2025-02-28'), ('2025-03-01', '2025-03-10')])


class MatchTests(unittest.TestCase):
    def setUp(self):
        self.rows = [r for r in H.parse_list(LIST) if r['broker'] == '한화투자증권']
        self.index = {r['idx']: r for r in self.rows}

    def test_code_and_title_match(self):
        reports = {'1': {'id': '1', 'date': '2026-10-30', 'board': '1002', 'depth3': 'anls1', 'analyst': '채운샘', 'code': '012450',
                         'subject': '3Q26 Review: 기대치 하회. 이제는 용기를 낼 시점', 'title': 'x'},
                   '2': {'id': '2', 'date': '2026-10-30', 'board': '1003', 'depth3': 'rpt_m1', 'analyst': '투자전략팀', 'code': '',
                         'subject': '한화 주간전략', 'title': '[주식전략] 한화 주간전략'},
                   '3': {'id': '3', 'date': '2026-10-30', 'board': '1002', 'depth3': 'anls1', 'analyst': '김도하', 'code': '105560',
                         'subject': '상대적인 선호도가 높아지는 국면', 'title': 'x'}}
        n = H.match_all(reports, self.index)
        self.assertEqual(n, 2)
        self.assertEqual(reports['1']['hk']['idx'], '653540'); self.assertEqual(reports['2']['hk']['idx'], '653505')
        self.assertNotIn('hk', reports['3'])   # 한경에 없는 글은 매칭 없음(다른 글을 끌어오지 않는다)

    def test_date_too_far(self):
        rec = {'date': '2026-10-20', 'analyst': '채운샘', 'code': '012450', 'subject': '3Q26 Review'}
        self.assertEqual(H.match_score(rec, self.rows[0]), 0)

    def test_pdf_text_for(self):
        shards = {'2026-10': {'1': {'text': 'PDF 본문', 'ok': True}, '2': {'text': '', 'ok': False}}}
        self.assertEqual(H.pdf_text_for('1', '2026-10', shards), 'PDF 본문')
        self.assertEqual(H.pdf_text_for('2', '2026-10', shards), ''); self.assertEqual(H.pdf_text_for('9', '2026-10', shards), '')


class InputPriorityTests(unittest.TestCase):
    def test_pdf_first(self):
        import ai_analyze as A
        rec = {'date': '2026-10-30', 'analyst': 'a', 'kind': 'k', 'sector': 's', 'title': 't', 'summary': 'sum'}
        txt, src = A.build_input(rec, '본문' * 100, 'PDF 원문 ' * 60)
        self.assertEqual(src, 'pdf'); self.assertIn('[PDF 원문 발췌]', txt); self.assertIn('[게시판 본문]', txt)
        self.assertEqual(A.build_input(rec, '본문' * 100, '')[1], 'body'); self.assertEqual(A.build_input(rec, '', '')[1], 'summary')


if __name__ == '__main__':
    unittest.main()
