import unittest

from article_metadata import enrich_news_item
from parser import classify, extract_companies, identify_companies, parse_news, parse_news_items, parse_report


class ForeignCompanyClassificationTest(unittest.TestCase):
    def test_weapon_systems_map_to_listed_companies(self):
        cases = {
            "Indonesia Pulls Out Of KF-21 Co-Production": "한국항공우주",
            "Poland receives first batch of K9 howitzers": "한화에어로스페이스",
            "Norway signs K2 tank deal": "현대로템",
            "Malaysia orders more FA-50 light fighters": "한국항공우주",
            "Philippines eyes T-50 trainer jets": "한국항공우주",
            "Saudi Arabia in talks for M-SAM air defense": "LIG D&A",
            "Poland to buy Chunmoo MLRS": "한화에어로스페이스",
        }
        for text, company in cases.items():
            with self.subTest(text=text):
                self.assertIn(company, identify_companies(text))

    def test_english_company_names_map_to_korean(self):
        cases = {
            "Hanwha Aerospace wins export order": "한화에어로스페이스",
            "Hyundai Rotem unveils new platform": "현대로템",
            "LIG Nex1 secures missile contract": "LIG넥스원",
            "Korea Aerospace Industries expands line": "한국항공우주",
            "Hanwha Ocean lands FLNG deal": "한화오션",
        }
        for text, company in cases.items():
            with self.subTest(text=text):
                self.assertIn(company, identify_companies(text))

    def test_weapon_system_variants_map_to_listed_companies(self):
        cases = {
            "South Korea K9MH Mobile Howitzer raises fire rate": "한화에어로스페이스",
            "Poland receives first K2PL tanks": "현대로템",
            "Estonia orders more K239 Chunmoo systems": "한화에어로스페이스",
            "Poland becomes a rocket manufacturer — Homar-K signed": "한화에어로스페이스",
            "Australia selects Redback IFV": "한화에어로스페이스",
            "천궁-II 이라크 수출 본격 협의": "LIG D&A",
            "KAI Surion helicopter fleet grows": "한국항공우주",
        }
        for text, company in cases.items():
            with self.subTest(text=text):
                self.assertIn(company, identify_companies(text))

    def test_short_codes_do_not_false_match(self):
        # K21 보병전투차, AK9, K200, K239는 K2/K9 자주포·전차로 오탐하면 안 된다.
        self.assertEqual(identify_companies("K21 IFV was displayed"), [])
        self.assertEqual(identify_companies("The AK9 rifle jammed"), [])
        self.assertEqual(identify_companies("K200 series update"), [])
        # K239는 K2(현대로템)가 아니라 천무(한화에어로스페이스)로만 잡혀야 한다.
        self.assertEqual(identify_companies("K239 launcher trial"), ["한화에어로스페이스"])

    def test_korean_name_wins_over_foreign_fallback(self):
        # 한국 정식사명이 있으면 무기체계 폴백은 개입하지 않는다.
        result = identify_companies("한화오션이 K9 관련 부품을 공급한다")
        self.assertEqual(result, ["한화오션"])

    def test_legacy_company_names_map_to_current_listed_names(self):
        # 개명 전 구사명이 담긴 과거 보고서도 현재 상장사명으로 연결된다.
        cases = {
            "현대미포조선 3Q19 리뷰": "HD현대미포",
            "대우조선해양 3Q21 리뷰: LNG선 단납기 슬롯 프리미엄": "한화오션",
            "두산인프라코어: 중국 탈피": "HD현대인프라코어",
            "HSD엔진: 기다리던 흑전": "한화엔진",
            "두산엔진: 가벼워진 엔진": "한화엔진",
            "한진중공업: 독자생존에 성공한다면": "HJ중공업",
            "삼강엠앤티: 2021 수주를 주목": "SK오션플랜트",
            "현대일렉트릭 서프라이즈": "HD현대일렉트릭",
            "두산중공업: 연말 수주": "두산에너빌리티",
            "세진중공업: 쇼티지에서 비롯된 호실적": "세진중공업",
            "현대중공업 그룹 사업계획 컨퍼런스콜 후기": "HD현대중공업",
            "한국조선해양 중간지주 밸류에이션": "HD한국조선해양",
        }
        for text, company in cases.items():
            with self.subTest(text=text):
                self.assertIn(company, identify_companies(text))


class ParserForeignRegressionTest(unittest.TestCase):
    def test_summary_post_with_wrong_title_still_tags_from_body(self):
        body = """방산 🛫 Indonesia Pulls Out Of KF-21 Co-Production, Could Acquire Jets Directly From South Korea
출처: EurAsian Times"""
        self.assertIn("한국항공우주", extract_companies(body))



class ParserTest(unittest.TestCase):
    def test_report_target_change(self):
        result = parse_report("[테스트전자]\n기존 목표주가 80,000원 → 목표주가 100,000원\n투자의견 BUY")
        self.assertEqual(result["company_name"], "테스트전자")
        self.assertEqual(result["previous_target_price"], 80000)
        self.assertEqual(result["target_price"], 100000)
        self.assertEqual(result["target_change"], "상향")

    def test_news(self):
        text = "[테스트중공업] 유럽 수주 계약 체결\nhttps://example.com/a"
        self.assertEqual(classify(text), "news")
        self.assertEqual(parse_news(text)["event_type"], "수주")

    def test_unknown_text_is_preserved_for_review(self):
        self.assertEqual(classify("오늘 시장 메모"), "unclassified")

    def test_hi_gs_compliance_report(self):
        text = """탱커 수주, 한화오션의 FLNG 진출
http://bit.ly/example
조선/기계/방산 | 최광식 | DAOL투자증권
✅ 컴플라이언스 승인을 득한 보고서입니다."""
        self.assertEqual(classify(text), "report")
        result = parse_report(text)
        self.assertEqual(result["company_name"], "한화오션")
        self.assertEqual(result["securities_firm"], "다올투자증권")
        self.assertEqual(result["analyst"], "최광식")

    def test_multi_company_report_is_industry_and_keeps_each_company(self):
        text = """HD현대중공업, 한화오션, 삼성중공업 수주 점검
조선/기계/방산 | 최광식 | DAOL투자증권
✅ 컴플라이언스 승인을 득한 보고서입니다."""
        result = parse_report(text)
        self.assertEqual(result["report_type"], "산업분석")
        self.assertEqual(set(result["companies"]), {"HD현대중공업", "한화오션", "삼성중공업"})

    def test_sector_hashtag_is_not_a_company(self):
        text = """⛴ #조선 「업황과 주가의 괴리가 메꿔지기 시작」
조선/기계/방산 | 최광식 | DAOL투자증권
✅ 컴플라이언스 승인을 득한 보고서입니다."""
        result = parse_report(text)
        self.assertEqual(result["companies"], [])
        self.assertEqual(result["report_type"], "산업분석")

    def test_target_price_in_manwon_units(self):
        # "적정주가 104만원", "TP 3.5만원" 같은 만원 단위 표기를 원 단위로 환산한다.
        result = parse_report("[HD현대중공업]\n적정PER 23배로 적정주가 104만원으로 상향\n보고서")
        self.assertEqual(result["target_price"], 1_040_000)
        self.assertEqual(result["target_change"], "상향")
        result = parse_report("[두산밥캣]\n커버리지 개시: 적정주가 6.6만원\n보고서")
        self.assertEqual(result["target_price"], 66_000)
        # 단위가 깨져 1,000원 미만이 되는 오파싱은 TP로 저장하지 않는다.
        self.assertIsNone(parse_report("[테스트전자]\n목표주가 45 언급\n보고서")["target_price"])

    def test_bundle_report_splits_company_sections(self):
        # 산업자료 + 기업 리뷰 2개가 한 텔레그램 글에 묶인 형식 (2026-07-21 엔진2사)
        text = """⚙️ #엔진2사 「엔진 초호황!, 주가는 반토막?」
☞ https://bit.ly/ENGINE2Q26PRE
▶️ Issue: 주가 낙폭 너무 큰 엔진2사 강력 추천. 2Q26 및 하반기 프리뷰
▶️ Pitch
- 강력 매수 기회
▶️ 한화엔진 「중국 없이도 벌써 1.4조원 수주. 올해 신기록 경신 확실시」
> TP: 91,000원으로 19% 하향
> 수주: 1.43조원으로 작년의 1.77조원을 넘기는 추세
▶️ HD현대마린엔진 「심하다, 계열사 없이 중국으로만도 벌써 작년 수주 넘김」
> TP: 144,000원 견지. 상승여력 무려 172%
---------------------------------------------------------------
🎴 조선/기계/방산 | 최광식 | DAOL투자증권
✅ 컴플라이언스 승인을 득한 보고서입니다."""
        result = parse_report(text)
        self.assertEqual(result["report_type"], "산업분석")
        # 엄브렐러 행에는 서로 다른 기업의 TP가 섞여 남지 않는다.
        self.assertIsNone(result["target_price"])
        sections = result["sections"]
        self.assertEqual([s["company"] for s in sections], ["한화엔진", "HD현대마린엔진"])
        self.assertEqual(sections[0]["target_price"], 91000)
        self.assertEqual(sections[0]["target_change"], "하향")
        self.assertEqual(sections[1]["target_price"], 144000)
        self.assertEqual(sections[1]["target_change"], "유지")

    def test_single_company_title_stays_company_report_despite_peer_mentions(self):
        # 제목 해시태그가 기업 하나면 본문에 피어(HD현대 등)가 언급돼도 기업분석이다.
        text = """🚢 #한국카본 「방산 양산, SUPER+ 개시, SB 등 호재 가득」
▶️ Pitch:
> NO96 Super+ 수주로 삼성과 HD현대만의 Q를 돌파
- 적정주가 61,000원으로 +7% 상향
✅ 컴플라이언스 승인을 득한 보고서입니다."""
        result = parse_report(text)
        self.assertEqual(result["report_type"], "기업분석")
        self.assertEqual(result["target_price"], 61000)
        self.assertEqual(result["target_change"], "상향")
        self.assertEqual(result["sections"], [])

    def test_weekly_folders_follow_brokerage_markers(self):
        cases = (
            ("⚓ 주시뉴스\nhttp://bit.ly/DOS700\nDAOL투자증권 최광식", "다올선박"),
            ("⚓️ 주시뉴스\nhttp://bit.ly/KISS610\n한국투자증권 최광식", "한투시절"),
            ("⚓ 주시 뉴스\n조선/기계/방산 | 최광식 | 하이투자증권", "하이투자증권시절"),
            ("⚓ 주시뉴스\n조선/기계/방산 | 최광식 | ktb투자증권", "다올선박"),
        )
        for text, folder in cases:
            with self.subTest(folder=folder):
                result = parse_report(text)
                self.assertEqual(result["report_type"], "위클리")
                self.assertEqual(result["weekly_folder"], folder)

    def test_brokerage_channel_names_are_not_companies(self):
        for text in ("[다올 시황 김지현] 시장 메모", "[상상인선박기계] 조선 코멘트"):
            with self.subTest(text=text):
                self.assertEqual(parse_report(text)["companies"], [])

    def test_hi_gs_daily_news_splits_links(self):
        text = """[다올투자증권 조선/기계/방산 최광식]
6/25(목) 데일리뉴스
조선
HD현대중공업, 우루과이 군함 입찰 참여
https://example.com/ship
방산
한화시스템, 천궁-II 중동 확장
https://example.com/defense"""
        self.assertEqual(classify(text), "news")
        items = parse_news_items(text)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["industry"], "조선")
        self.assertEqual(items[0]["company_name"], "HD현대중공업")
        self.assertEqual(items[1]["industry"], "방산")

    def test_markdown_link_and_source_line_are_cleaned(self):
        text = """[제이오션중공업-HD현대중공업 군산조선소 자산 양수도 본계약 체결]
• 신규 프로젝트 법인이 출범함
출처: 전북제일신문
[https://example.com/news?id=1](https://example.com/news?id=1)"""
        item = parse_news_items(text)[0]
        self.assertEqual(item["title"], "[제이오션중공업-HD현대중공업 군산조선소 자산 양수도 본계약 체결]")
        self.assertEqual(item["article_url"], "https://example.com/news?id=1")

    def test_link_only_news_uses_article_title_and_classifies_company(self):
        item = parse_news_items("https://example.com/link-only")[0]
        enrich_news_item(item, lambda _url: "한화오션, 신규 FLNG 수주 계약 체결")
        self.assertEqual(item["title"], "한화오션, 신규 FLNG 수주 계약 체결")
        self.assertEqual(item["companies"], ["한화오션"])
        self.assertEqual(item["company_name"], "한화오션")
        self.assertEqual(item["event_type"], "기타")

    def test_link_only_news_keeps_placeholder_when_fetch_fails(self):
        item = parse_news_items("https://example.com/link-only")[0]
        enrich_news_item(item, lambda _url: None)
        self.assertEqual(item["title"], "기사 제목 미확인")

    def test_alias_is_normalized_even_when_article_fetch_fails(self):
        item = parse_news_items("삼성重 최성안 부회장, 자사주 1만주 매입…책임경영 의지\nhttps://buly.kr/example")[0]
        item["company_name"], item["companies"] = None, []
        enrich_news_item(item, lambda _url: None)
        self.assertEqual(item["company_name"], "삼성중공업")
        self.assertEqual(item["companies"], ["삼성중공업"])

    def test_comment_title_is_replaced_and_company_comes_from_article_body(self):
        item = parse_news_items("오오..\nhttps://example.com/article")[0]
        enrich_news_item(item, lambda _url: {
            "title": "최성안 부회장, 자사주 1만주 추가 매입",
            "text": "삼성중공업은 책임경영 실천의 일환이라고 밝혔다.",
        })
        self.assertEqual(item["title"], "최성안 부회장, 자사주 1만주 추가 매입")
        self.assertEqual(item["company_name"], "삼성중공업")

    def test_full_quoted_title_and_title_company_override_related_news(self):
        item = parse_news_items("美 ITC, 두산밥캣\nhttps://example.com/article")[0]
        enrich_news_item(item, lambda _url: {
            "title": "美 ITC, 두산밥캣 '특허침해 혐의' 조사 착수…철저한 '법적 대응' 예고",
            "description": "두산밥캣 특허 분쟁 기사",
            "text": "기사 하단 관련 뉴스: LIG D&A 해성 검토",
        })
        self.assertEqual(item["companies"], ["두산밥캣"])

    def test_korean_comment_stuck_to_url_is_not_part_of_url(self):
        item = parse_news_items("https://buly.kr/4bi1ueA오오~")[0]
        self.assertEqual(item["article_url"], "https://buly.kr/4bi1ueA")

    def test_summary_post_uses_korean_headline_not_channel_signature(self):
        text = """> 방산 🛫 Indonesia Pulls Out Of KF-21 Co-Production, Could Acquire Jets Directly From South Korea: Reports
> 인도네시아 KF-21 공동 생산 철회, 한국으로부터 직접 도입 가능성 제기

출처: EurAsian Times
링크: [[https://www.eurasiantimes.com/indonesia-pulls-out-of-kf-21-co-production-could-acquire-jets-directly-from-south-korea-reports/](https://www.eurasiantimes.com/indonesia-pulls-out-of-kf-21-co-production-could-acquire-jets-directly-from-south-korea-reports/)]

* 인도네시아 국방부 대변인, 공동 생산 계획 중단 공식화
-----------------------------------------------------------
🎴 조선/기계/방산 | 최광식 | DAOL투자증권"""
        item = parse_news_items(text)[0]
        self.assertEqual(item["title"], "인도네시아 KF-21 공동 생산 철회, 한국으로부터 직접 도입 가능성 제기")
        self.assertEqual(item["company_name"], "한국항공우주")
        self.assertEqual(item["publisher"], "EurAsian Times")
        self.assertNotIn("최광식", item["title"])

    def test_company_aliases_use_canonical_korean_names(self):
        kai = parse_news_items("KAI, KF-21 양산 확대\nhttps://example.com/kai")[0]
        samsung = parse_news_items("삼성重 최성안 부회장, 자사주 1만주 매입…책임경영 의지\nhttps://example.com/shi")[0]
        self.assertEqual(kai["company_name"], "한국항공우주")
        self.assertEqual(samsung["company_name"], "삼성중공업")


if __name__ == "__main__":
    unittest.main()
