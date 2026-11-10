import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import parse as p


class TitleTests(unittest.TestCase):
    def test_company_with_code_and_opinion(self):
        r = p.parse_title('[화장품] 에이피알[278470/Buy] 4분기부터 다시 서프라이즈 일텐데요…')
        self.assertEqual((r['sector'], r['company'], r['code'], r['opinion']), ('화장품', '에이피알', '278470', 'Buy'))
        self.assertEqual(r['subject'], '4분기부터 다시 서프라이즈 일텐데요…')

    def test_industry_series_header(self):
        r = p.parse_title('[인터넷/게임] [2027년 산업전망] 확장에서 결실로')
        self.assertEqual(r['sector'], '인터넷/게임'); self.assertEqual(r['company'], '')
        self.assertEqual(r['subject'], '[2027년 산업전망] 확장에서 결실로')

    def test_overseas_flag(self):
        r = p.parse_title('[미국주식] [Earnings Flash] Amazon,com, Inc.')
        self.assertTrue(r['is_overseas'])

    def test_korean_opinion_normalised(self):
        r = p.parse_title('[조선] HD현대중공업[329180/매수] 수주 모멘텀')
        self.assertEqual(r['opinion'], 'Buy'); self.assertEqual(r['company'], 'HD현대중공업')

    def test_code_only(self):
        r = p.parse_title('[기계] 두산밥캣(241560) 북미 수요 점검')
        self.assertEqual((r['company'], r['code'], r['opinion']), ('두산밥캣', '241560', ''))

    def test_no_bracket(self):
        r = p.parse_title('BOJ, 매파적 동결로 추가 인상 예고')
        self.assertEqual(r['sector'], ''); self.assertEqual(r['subject'], 'BOJ, 매파적 동결로 추가 인상 예고')


class SectorTests(unittest.TestCase):
    def test_strategy_board(self):
        self.assertEqual(p.sector_from_record({'board': '1003', 'kind': '국내외 경제', 'title_sector': '경제분석'}), '전략·경제')

    def test_bracket_sector_wins(self):
        self.assertEqual(p.sector_from_record({'board': '1002', 'kind': '기업분석', 'title_sector': '화장품'}), '화장품')

    def test_series_bracket_is_not_sector(self):
        self.assertEqual(p.sector_from_record({'board': '1002', 'kind': '산업분석', 'title_sector': '2027년 산업전망'}), '산업분석')


class CoverTests(unittest.TestCase):
    def test_tp_with_direction_and_prior(self):
        c = p.extract_cover('에이피알 (278470) 투자의견 Buy (유지) 목표주가 180,000원 (하향) 기존 220,000원 ...')
        self.assertEqual((c['opinion'], c['opinion_change'], c['tp'], c['tp_prior'], c['tp_change']),
                         ('Buy', '유지', 180000, 220000, '하향'))

    def test_arrow_prior(self):
        c = p.extract_cover('목표주가 150,000원 → 170,000원 상향')
        self.assertEqual((c['tp'], c['tp_prior'], c['tp_change']), (170000, 150000, '상향'))

    def test_direction_inferred_from_prior(self):
        c = p.extract_cover('목표주가 90,000원 기존 100,000원')
        self.assertEqual(c['tp_change'], '하향')

    def test_nothing(self):
        c = p.extract_cover('산업 전망 자료입니다. 수요가 늘어납니다.')
        self.assertIsNone(c['tp']); self.assertEqual(c['opinion'], '')

    def test_tp_english(self):
        c = p.extract_cover('Rating: Buy  Target Price: 56,000')
        self.assertEqual((c['opinion'], c['tp']), ('Buy', 56000))


class KoreanUnitTests(unittest.TestCase):
    def test_man_won(self):
        self.assertEqual(p.extract_cover('동사에 대한 목표주가 30만 원을 유지합니다.')['tp'], 300000)
        c = p.extract_cover('투자의견 BUY, 목표주가 5.1만원 유지'); self.assertEqual((c['tp'], c['tp_change'], c['opinion']), (51000, '유지', 'Buy'))
        c = p.extract_cover('목표주가 1만 2천 원으로 상향하고 투자의견 BUY 유지'); self.assertEqual((c['tp'], c['tp_change'], c['opinion_change']), (12000, '상향', '유지'))

    def test_particle_and_parenthesis(self):
        self.assertEqual(p.extract_cover('목표주가를 8,300원으로 하향합니다.')['tp_change'], '하향')
        c = p.extract_cover('목표주가는 800,000원(-10,000원)으로 하향.'); self.assertEqual((c['tp'], c['tp_change']), (800000, '하향'))


class BodyAndSectorTests(unittest.TestCase):
    def test_clean_body_cuts_footer(self):
        body = '에이피알의 2026년 3분기 매출액은 7,731억원으로 컨센서스를 하회했다. 환손실 영향을 제외하면 양호하다.\n$(function(){\n보다 자세한 내용은 로그인 후 첨부파일을 통해 확인하세요.\nvar x=1;'
        self.assertEqual(p.clean_body(body), '에이피알의 2026년 3분기 매출액은 7,731억원으로 컨센서스를 하회했다. 환손실 영향을 제외하면 양호하다.')

    def test_clean_body_empty_when_only_disclaimer(self):
        self.assertEqual(p.clean_body('이 자료는 당사 리서치센터나 해당 부서가 신뢰할 만한 자료로 작성한 것이지만'), '')

    def test_canon_sector(self):
        self.assertEqual(p.canon_sector('철강/비철금속'), '철강/비철'); self.assertEqual(p.canon_sector('ESG & Transition'), 'ESG')
        self.assertEqual(p.canon_sector('은행'), '은행'); self.assertEqual(p.canon_sector('조선'), '조선')
        self.assertIsNone(p.canon_sector('9월의 기분')); self.assertIsNone(p.canon_sector('한화 업종별 월간 플레이북')); self.assertIsNone(p.canon_sector('기업분석'))


if __name__ == '__main__':
    unittest.main()
