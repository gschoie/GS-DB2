import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_tone as B
from ai_analyze import SCHEMA_VERSION

def rec(i, d, **kw):
    base = {'id': str(i), 'date': d, 'board': '1002', 'depth3': 'anls1', 'kind': '기업분석', 'title': f'[화장품] 에이피알[278470/Buy] 제목{i}',
            'analyst': '한유정', 'sector': '화장품', 'company': '에이피알', 'code': '278470', 'opinion': 'Buy', 'scope': '기업', 'summary': ''}
    base.update(kw); return base

def ai(**kw):
    r = {'report_scope': '기업', 'company': '에이피알', 'code': '278470', 'opinion': 'Buy',
         'tp': {'direction': '없음', 'value': None, 'prior': None, 'reasons': [], 'evidence': ''},
         'earnings': {'direction': '없음', 'evidence': ''}, 'conviction': 4, 'tone_label': '긍정',
         'strong_phrases': ['강하다'], 'hedge_phrases': [], 'negative_phrases': [],
         'investment_points': [{'label': '북미 확장', 'summary': 's'}], 'one_line': 'ok',
         'estimates': {'quarter_label': '3Q26', 'quarter_op': None, 'quarter_eps': None, 'year_op': None, 'year_eps': None}}
    for k, v in kw.items():
        if isinstance(v, dict): r[k].update(v)
        else: r[k] = v
    return {'v': SCHEMA_VERSION, 'result': r}


class MergeTests(unittest.TestCase):
    def test_regex_tp_beats_ai_value(self):
        r = rec(1, '2026-10-30', body_tp={'tp': 180000, 'tp_prior': 220000, 'tp_change': '하향', 'opinion': 'Buy'})
        m = B.merge_report(r, ai(tp={'direction': '하향', 'value': 170000, 'reasons': ['실적추정'], 'evidence': 'e'}), 'body')
        self.assertEqual(m['tp_event']['value'], 180000); self.assertEqual(m['tp_event']['prior'], 220000)
        self.assertEqual(m['tp_event']['display'], '220,000원 → 180,000원'); self.assertEqual(m['tp_event']['reasons'], ['실적추정'])

    def test_industry_report_has_no_tp(self):
        r = rec(2, '2026-10-30', scope='산업', company='', code='', title='[화장품] 산업 전망', body_tp={'tp': 100000, 'tp_prior': None, 'tp_change': ''})
        self.assertIsNone(B.merge_report(r, None, '')['tp_event'])

    def test_prior_from_timeline_and_events(self):
        a = B.merge_report(rec(1, '2026-01-10', body_tp={'tp': 100000, 'tp_prior': None, 'tp_change': ''}), ai(conviction=2, tone_label='신중'), 'b')
        b = B.merge_report(rec(2, '2026-03-10', body_tp={'tp': 120000, 'tp_prior': None, 'tp_change': '상향'}), ai(conviction=4, investment_points=[{'label': '유럽', 'summary': ''}]), 'b')
        c = B.merge_report(rec(3, '2026-05-10', opinion='Hold', body_tp={'tp': 120000, 'tp_prior': None, 'tp_change': ''}), ai(opinion='Hold', conviction=4), 'b')
        tl = [a, b, c]
        B.fill_tp_priors(tl); B.attach_point_diffs(tl)
        self.assertEqual(b['tp_event']['prior'], 100000); self.assertEqual(c['tp_event']['direction'], '유지')
        ev, st = B.timeline_events('278470', '에이피알', tl)
        types = [e['type'] for e in ev]
        self.assertIn('TP 상향', types); self.assertIn('톤 급변↑', types); self.assertIn('투자포인트 변화', types); self.assertIn('의견 변경', types)
        self.assertEqual(st[0]['type'], 'TP 유지')

    def test_company_key_industry(self):
        m = B.merge_report(rec(5, '2026-01-01', scope='산업', company='', code='', sector='전략·경제', board='1003'), None, '')
        self.assertEqual(B.company_key(m), ('IND:전략·경제', '전략·경제', ''))


if __name__ == '__main__':
    unittest.main()
