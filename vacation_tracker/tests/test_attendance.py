"""근태 보고 감지·기록 검사 — 네트워크 없이 규칙만 검산한다."""

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from attendance import detect_attendance, record_hits  # noqa: E402
from rules import KST  # noqa: E402

SEP = datetime(2026, 9, 8, 10, 0, tzinfo=KST)
JAN = datetime(2027, 1, 4, 9, 0, tzinfo=KST)


class DetectTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(detect_attendance("근태 완벽합니다", SEP), {"month": "2026-09"})

    def test_variants(self):
        for text in ("근태 이상 없습니다", "근태 이상무!", "근태 문제 없어요",
                     "근태 입력 완료했습니다", "이번달 근태 깨끗합니다"):
            self.assertIsNotNone(detect_attendance(text, SEP), text)

    def test_spaced_and_dotted(self):
        self.assertIsNotNone(detect_attendance("근 태 완벽합니다", SEP))
        self.assertIsNotNone(detect_attendance("근.태. 이상없음", SEP))

    def test_explicit_month(self):
        self.assertEqual(detect_attendance("9월 근태 완벽합니다", SEP), {"month": "2026-09"})
        self.assertEqual(detect_attendance("8월 근태 이상 없습니다", SEP), {"month": "2026-08"})

    def test_prev_year_rollover(self):
        # 1월에 "12월 근태" 보고 → 지난해 12월
        self.assertEqual(detect_attendance("12월 근태 완벽합니다", JAN), {"month": "2026-12"})

    def test_not_reports(self):
        for text in ("근태 체크해 주세요", "근태 언제까지야?", "근태 확인 부탁해요",
                     "근태 완벽하게 해야 해", "완벽합니다", "오늘 뭐 먹지",
                     "근태 다 됐어?"):
            self.assertIsNone(detect_attendance(text, SEP), text)


class RecordTest(unittest.TestCase):
    def hit(self, uid="1:100", name="이준범", month="2026-09"):
        return {"name": name, "month": month, "uid": uid,
                "text": "근태 완벽합니다", "msg_date": "2026-09-08T10:00+09:00"}

    def test_new_hit_is_fresh_and_checked(self):
        store = {"months": {}}
        fresh = record_hits(store, [self.hit()])
        self.assertEqual(len(fresh), 1)
        self.assertTrue(store["months"]["2026-09"]["이준범"]["checked"])

    def test_same_uid_rescan_not_fresh(self):
        store = {"months": {}}
        record_hits(store, [self.hit()])
        fresh = record_hits(store, [self.hit()])
        self.assertEqual(fresh, [])

    def test_new_message_rechecks_after_manual_uncheck(self):
        store = {"months": {"2026-09": {"이준범": {"checked": False, "uid": "1:100",
                                                  "text": "", "msg_date": "", "source": "manual"}}}}
        fresh = record_hits(store, [self.hit(uid="1:200")])
        self.assertEqual(len(fresh), 1)
        self.assertTrue(store["months"]["2026-09"]["이준범"]["checked"])

    def test_already_checked_updates_quietly(self):
        store = {"months": {}}
        record_hits(store, [self.hit()])
        fresh = record_hits(store, [self.hit(uid="1:300")])  # 같은 달 재보고
        self.assertEqual(fresh, [])
        self.assertEqual(store["months"]["2026-09"]["이준범"]["uid"], "1:300")


if __name__ == "__main__":
    unittest.main()
