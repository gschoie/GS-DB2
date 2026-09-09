"""근태 보고 감지·기록 검사 — 네트워크 없이 규칙만 검산한다."""

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from attendance import detect_attendance, open_campaign_month, record_hits  # noqa: E402
from rules import KST  # noqa: E402

SEP = datetime(2026, 9, 8, 10, 0, tzinfo=KST)
JAN = datetime(2027, 1, 4, 9, 0, tzinfo=KST)


class DetectTest(unittest.TestCase):
    def test_basic(self):
        hit = detect_attendance("근태 완벽합니다", SEP)
        self.assertEqual(hit["month"], "2026-09")
        self.assertFalse(hit["explicit"])

    def test_variants(self):
        for text in ("근태 이상 없습니다", "근태 이상무!", "근태 문제 없어요",
                     "근태 입력 완료했습니다", "이번달 근태 깨끗합니다", "근태 확인했습니다"):
            self.assertIsNotNone(detect_attendance(text, SEP), text)

    def test_spaced_and_dotted(self):
        self.assertIsNotNone(detect_attendance("근 태 완벽합니다", SEP))
        self.assertIsNotNone(detect_attendance("근.태. 이상없음", SEP))

    def test_explicit_month(self):
        hit = detect_attendance("8월 근태 이상 없습니다", SEP)
        self.assertEqual(hit["month"], "2026-08")
        self.assertTrue(hit["explicit"])

    def test_prev_year_rollover(self):
        # 1월에 "12월 근태" 보고 → 지난해 12월
        self.assertEqual(detect_attendance("12월 근태 완벽합니다", JAN)["month"], "2026-12")

    def test_not_reports(self):
        for text in ("근태 체크해 주세요", "근태 언제까지야?", "근태 확인 부탁해요",
                     "근태 완벽하게 해야 해", "완벽합니다", "오늘 뭐 먹지",
                     "근태 다 됐어?"):
            self.assertIsNone(detect_attendance(text, SEP), text)


def open_store(month="2026-08"):
    return {"months": {}, "campaigns": {month: {"status": "open"}}}


class RecordTest(unittest.TestCase):
    def hit(self, uid="1:100", name="이준범", month="2026-09", explicit=False):
        return {"name": name, "month": month, "explicit": explicit, "uid": uid,
                "text": "근태 완벽합니다", "msg_date": "2026-09-08T10:00+09:00"}

    def test_no_campaign_ignored(self):
        store = {"months": {}, "campaigns": {}}
        self.assertEqual(record_hits(store, [self.hit()]), [])
        self.assertEqual(store["months"], {})

    def test_closed_campaign_ignored(self):
        store = {"months": {}, "campaigns": {"2026-08": {"status": "closed"}}}
        self.assertEqual(record_hits(store, [self.hit()]), [])
        self.assertEqual(store["months"], {})

    def test_hit_lands_on_campaign_month(self):
        # 9월의 대화는 8월 근태 — 메시지 달이 아니라 열린 기간의 대상 월로 붙는다.
        store = open_store("2026-08")
        fresh = record_hits(store, [self.hit(month="2026-09")])
        self.assertEqual(len(fresh), 1)
        self.assertEqual(fresh[0]["month"], "2026-08")
        self.assertTrue(store["months"]["2026-08"]["이준범"]["checked"])
        self.assertNotIn("2026-09", store["months"])

    def test_explicit_month_also_lands_on_campaign_month(self):
        # "9월 근태 완벽"도 8월 체크 중이면 8월로 — 캠페인이 정본이다.
        store = open_store("2026-08")
        record_hits(store, [self.hit(month="2026-09", explicit=True)])
        self.assertTrue(store["months"]["2026-08"]["이준범"]["checked"])

    def test_same_uid_rescan_not_fresh(self):
        store = open_store()
        record_hits(store, [self.hit()])
        self.assertEqual(record_hits(store, [self.hit()]), [])

    def test_new_message_rechecks_after_manual_uncheck(self):
        store = open_store()
        store["months"]["2026-08"] = {"이준범": {"checked": False, "uid": "1:100",
                                                "text": "", "note": "", "msg_date": "",
                                                "source": "manual"}}
        fresh = record_hits(store, [self.hit(uid="1:200")])
        self.assertEqual(len(fresh), 1)
        self.assertTrue(store["months"]["2026-08"]["이준범"]["checked"])

    def test_note_survives_rescan(self):
        store = open_store()
        record_hits(store, [self.hit()])
        store["months"]["2026-08"]["이준범"]["note"] = "구두로도 확인"
        record_hits(store, [self.hit(uid="1:300")])
        self.assertEqual(store["months"]["2026-08"]["이준범"]["note"], "구두로도 확인")

    def test_open_campaign_month(self):
        self.assertIsNone(open_campaign_month({"months": {}, "campaigns": {}}))
        self.assertEqual(open_campaign_month(open_store("2026-08")), "2026-08")


if __name__ == "__main__":
    unittest.main()
