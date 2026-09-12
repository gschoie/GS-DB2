"""발간 계획 프리필터·기록 검사 — 네트워크 없이 규칙만 검산한다."""

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from indepth import is_candidate, is_strong, pick_indepth_candidates, record  # noqa: E402
from rules import KST  # noqa: E402

T0 = datetime(2026, 9, 10, 10, 0, tzinfo=KST)


def tl(*msgs):
    """(out, text) 나열 → 10분 간격 타임라인."""
    return [{"id": i + 1, "out": out, "text": text, "dt": T0 + timedelta(minutes=10 * i)}
            for i, (out, text) in enumerate(msgs)]


class CandidateTest(unittest.TestCase):
    def test_positive(self):
        for text in ("인뎁스 다음주까지 마무리하겠습니다", "커버리지 개시 준비 중입니다",
                     "15일로 발간 타겟해보겠습니다", "자료 초안 거의 다 썼습니다",
                     "보고서 작성 중이라 늦어요", "산업자료 하나 내려고요",
                     "이니시 준비하고 있습니다"):
            self.assertTrue(is_candidate(text), text)

    def test_spaced(self):
        self.assertTrue(is_candidate("인 뎁스 준비중"))
        self.assertTrue(is_candidate("발.간 미루겠습니다"))

    def test_negative(self):
        for text in ("점심 뭐 먹을까요", "자료 좀 보내주세요", "회의 자료 받았습니다",
                     "9/15 휴가 다녀오겠습니다"):
            self.assertFalse(is_candidate(text), text)

    def test_strong_subset(self):
        self.assertTrue(is_strong("인뎁스 언제 나와?"))
        self.assertFalse(is_strong("자료 초안 거의 다 썼습니다"))  # 넓은 키워드는 폴백 제외


class PickTest(unittest.TestCase):
    def test_keyword_message_picked(self):
        picked = pick_indepth_candidates(tl((False, "인뎁스 다음주 발간하겠습니다")))
        self.assertEqual([p["index"] for p in picked], [0])

    def test_my_question_grabs_replies(self):
        timeline = tl((True, "인뎁스 언제 나올 것 같아?"),
                      (False, "다음주 금요일까지 마무리하겠습니다"),
                      (False, "주제는 조선 기자재입니다"),
                      (False, "그리고 점심 같이 하실래요?"))
        picked = {p["index"]: p["trigger"] for p in pick_indepth_candidates(timeline)}
        self.assertEqual(picked.get(0), "keyword")
        self.assertEqual(picked.get(1), "context")
        self.assertEqual(picked.get(2), "context")
        self.assertNotIn(3, picked)  # 답 2건까지만

    def test_reply_window(self):
        timeline = tl((True, "인뎁스 언제 나와?"))
        late = {"id": 99, "out": False, "text": "다음주요", "dt": T0 + timedelta(hours=20)}
        picked = pick_indepth_candidates(timeline + [late])
        self.assertEqual([p["index"] for p in picked], [0])  # 12시간 지난 답은 제외


class RecordTest(unittest.TestCase):
    def entry(self, uid="1:100"):
        return {"uid": uid, "name": "이준범", "topic": "조선", "kind": "인뎁스",
                "target": "2026-09-19", "target_text": "", "needs_review": False,
                "engine": "gemini", "text": "인뎁스 다음주 금요일 발간",
                "note": "", "done": False,
                "msg_date": "2026-09-10T10:00+09:00", "detected_at": "2026-09-12T09:00+09:00"}

    def test_new_recorded(self):
        store = {"entries": {}}
        fresh = record(store, [self.entry()])
        self.assertEqual(len(fresh), 1)
        self.assertIn("1:100", store["entries"])

    def test_known_uid_untouched(self):
        store = {"entries": {}}
        record(store, [self.entry()])
        store["entries"]["1:100"]["done"] = True  # 수동 수정
        fresh = record(store, [self.entry()])
        self.assertEqual(fresh, [])
        self.assertTrue(store["entries"]["1:100"]["done"])  # 재수집이 덮지 않는다


if __name__ == "__main__":
    unittest.main()
