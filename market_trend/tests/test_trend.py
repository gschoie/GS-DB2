"""네트워크·LLM 없이 도는 계량 로직 테스트.

config.yml이 실제로 파싱되는지도 함께 검사한다 — 설정을 잘못 고치면
워크플로가 수집 전에 여기서 멈춘다.
"""

import sys
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE.parent / "source_watcher"))

import trend_daily  # noqa: E402
import adapters  # noqa: E402

KST = timezone(timedelta(hours=9))


def make_item(uid, body, origin="채널A", hours_ago=1):
    return adapters.Item(
        uid=uid, title=body[:30], url=f"https://t.me/x/{uid}", body=body, origin=origin,
        published_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
    )


class ConfigTest(unittest.TestCase):
    def test_config_parses(self):
        cfg = trend_daily.load_config()
        self.assertGreater(len(cfg["stopwords"]), 50)
        # 불용어는 전부 문자열이어야 한다(YAML 오타로 dict가 섞이는 사고 방지)
        self.assertTrue(all(isinstance(w, str) for w in cfg["stopwords"]))
        self.assertIn("한화오션", cfg["aliases"])

    def test_alias_lookup_folds_variants(self):
        table = trend_daily.alias_lookup(trend_daily.load_config())
        self.assertEqual(table["대우조선해양"], "한화오션")
        self.assertEqual(table["042660"], "한화오션")
        self.assertEqual(table["한화오션"], "한화오션")


class WindowTest(unittest.TestCase):
    def test_window_before_and_after_anchor(self):
        cfg = {"window_hours": 24, "window_anchor_kst": 6}
        # 06:30 KST 실행 → 전일 06:00~당일 06:00
        now = datetime(2026, 8, 13, 6, 30, tzinfo=KST)
        start, end = trend_daily.day_window(now.astimezone(timezone.utc), cfg)
        self.assertEqual(end.astimezone(KST).hour, 6)
        self.assertEqual(end.astimezone(KST).day, 13)
        self.assertEqual((end - start), timedelta(hours=24))
        # 05:00 KST 실행 → 창 끝은 어제 06:00 (미래로 넘어가지 않는다)
        now = datetime(2026, 8, 13, 5, 0, tzinfo=KST)
        _, end = trend_daily.day_window(now.astimezone(timezone.utc), cfg)
        self.assertEqual(end.astimezone(KST).day, 12)


class TokenizeTest(unittest.TestCase):
    def setUp(self):
        self.cfg = trend_daily.load_config()
        self.stop = {str(w).casefold() for w in self.cfg["stopwords"]}
        self.aliases = trend_daily.alias_lookup(self.cfg)

    def test_strip_josa(self):
        self.assertEqual(trend_daily.strip_josa("삼성전자가"), "삼성전자")
        self.assertEqual(trend_daily.strip_josa("조선은"), "조선")
        self.assertEqual(trend_daily.strip_josa("한화오션"), "한화오션")
        # 떼면 2자 미만이 되는 것은 떼지 않는다
        self.assertEqual(trend_daily.strip_josa("금리"), "금리")

    def test_alias_and_stopword(self):
        tokens = trend_daily.tokenize("대우조선해양이 오늘 급등", self.stop, self.aliases)
        self.assertIn("한화오션", tokens)
        self.assertNotIn("오늘", [t for t in tokens if t])   # 불용어
        self.assertNotIn("급등", [t for t in tokens if t])   # 상투어

    def test_verbal_endings_dropped(self):
        tokens = trend_daily.tokenize("존스법이 급등했다 예상됨 좋아요 그렇죠", self.stop, self.aliases)
        alive = [t for t in tokens if t]
        self.assertEqual(alive, ["존스법"])  # 서술형(~다/~요/~죠/~됨)은 전부 걸러진다
        # 별칭 정식명은 어미 필터의 보호를 받는다 (해당 어미 종목명은 없지만 계약으로 고정)
        tokens = trend_daily.tokenize("한화오션 간다", self.stop, self.aliases)
        self.assertIn("한화오션", [t for t in tokens if t])
        self.assertNotIn("간다", tokens)

    def test_bigram_not_across_stopword(self):
        tokens = ["존스법", "", "개정"]
        _, bigrams = trend_daily.term_sets(tokens)
        self.assertEqual(bigrams, set())  # 불용어 자리를 건너뛰어 붙지 않는다
        _, bigrams = trend_daily.term_sets(["존스법", "개정"])
        self.assertEqual(bigrams, {"존스법 개정"})


class DedupeTest(unittest.TestCase):
    def test_forwarded_post_folds_with_spread(self):
        body = "조선업 신조선가 지수가 3주 연속 상승했다. " * 5
        items = [
            make_item("1:1", body, origin="채널A"),
            make_item("2:9", "[퍼옴]\n" + body, origin="채널B"),   # 머리말 붙은 판본
            make_item("3:3", "전혀 다른 반도체 소식이다. HBM 수요가 늘고 있다. " * 5, origin="채널C"),
        ]
        groups = trend_daily.group_duplicates(items)
        self.assertEqual(len(groups), 2)
        spread = {g["rep"].body[:5]: g["spread"] for g in groups}
        self.assertIn(2, spread.values())


class SpikeTest(unittest.TestCase):
    def _history(self, term_per_day):
        days = {}
        for i, terms in enumerate(term_per_day):
            days[f"2026-08-{i+1:02d}"] = {"docs": 100, "terms": terms}
        return {"version": 1, "days": days}

    def test_cold_start_ranks_by_count(self):
        cfg = {"min_doc_count": 3, "top_terms": 10}
        rows = trend_daily.spike_scores(Counter({"조선": 10, "관세": 5}), 200,
                                        {"days": {}}, "2026-08-13", cfg)
        self.assertEqual(rows[0]["term"], "조선")
        self.assertIsNone(rows[0]["burst"])

    def test_generic_word_dropped_by_doc_share(self):
        # 하루 글의 10% 넘게 등장하는 낱말은 상투어 — 목록에 없어도 자동 탈락
        cfg = {"min_doc_count": 3, "top_terms": 10}
        rows = trend_daily.spike_scores(Counter({"가능성": 60, "존스법": 8}), 200,
                                        {"days": {}}, "2026-08-13", cfg)
        terms = [r["term"] for r in rows]
        self.assertNotIn("가능성", terms)   # 30% 점유 → 탈락
        self.assertIn("존스법", terms)      # 4% 점유 → 생존

    def test_new_term_spikes_over_common_term(self):
        cfg = {"min_doc_count": 3, "top_terms": 10}
        history = self._history([{"조선": 20}] * 7)  # '조선'은 평소에도 매일 20건
        today = Counter({"조선": 22, "존스법": 8})
        rows = trend_daily.spike_scores(today, 100, history, "2026-08-13", cfg)
        terms = [r["term"] for r in rows]
        self.assertIn("존스법", terms)
        self.assertTrue(rows[0]["term"] == "존스법")     # 신조어가 위로
        self.assertTrue(next(r for r in rows if r["term"] == "존스법")["new"])
        self.assertNotIn("조선", terms)                  # 평소와 같은 수준은 급증이 아니다


class RenderTest(unittest.TestCase):
    def test_markdown_renders_without_llm(self):
        spikes = [{"term": "존스법", "count": 8, "burst": 12.3, "base_daily": 0.3, "new": True}]
        posts = [{"channels": 4, "channel": "채널A", "head": "머리글", "url": "https://t.me/x/1", "time_kst": "08-13 07:00"}]
        md = trend_daily.render_markdown(
            "2026-08-13", None, spikes, posts,
            {"channels": 30, "messages": 500, "groups": 400},
            {"window": "…", "engine": "계량 신호만", "generated_at": "…"},
        )
        self.assertIn("존스법", md)
        self.assertIn("시장관심.내러티브", md)

    def test_markdown_renders_themes(self):
        result = {"one_liner": "한 줄", "themes": [{
            "name": "조선 — MRO", "narrative": "내러티브.", "status": "new",
            "strength": 4, "keywords": ["존스법"], "evidence": [{"channel": "A", "quote": "인용"}],
        }]}
        md = trend_daily.render_markdown("2026-08-13", result, [], [],
                                         {"channels": 1, "messages": 1, "groups": 1},
                                         {"window": "…", "engine": "Gemini", "generated_at": "…"})
        self.assertIn("조선 — MRO", md)
        self.assertIn("🆕", md)


if __name__ == "__main__":
    unittest.main()
