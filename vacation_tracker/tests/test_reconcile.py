"""경합 상태 병합 검산 — 10/6 수동 체크 유실 사고의 재현 포함."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reconcile_state import merge_attendance, merge_scan_state, merge_uid_store  # noqa: E402


def att_row(checked=True, source="manual", text="", uid="", note=""):
    return {"checked": checked, "source": source, "text": text, "uid": uid,
            "note": note, "msg_date": "2026-10-06T15:14+09:00"}


class AttendanceMergeTest(unittest.TestCase):
    def test_lost_manual_checks_survive(self):
        # 10/6 사고 재현: main에는 박소현 수동 체크, 내 run(낡은 base)에는 김혜영만.
        # 줄 병합이면 박소현이 날아갔다 — 키 병합은 둘 다 지킨다.
        main = {"campaigns": {"2026-09": {"status": "open"}},
                "months": {"2026-09": {"박소현": att_row()}}}
        ours = {"campaigns": {"2026-09": {"status": "open"}},
                "months": {"2026-09": {"김혜영": att_row()}}}
        merged = merge_attendance(main, ours)
        self.assertIn("박소현", merged["months"]["2026-09"])
        self.assertIn("김혜영", merged["months"]["2026-09"])

    def test_collision_telegram_text_wins_but_checked_is_or(self):
        main = {"campaigns": {}, "months": {"2026-09": {
            "이지수": att_row(checked=True, source="manual")}}}
        ours = {"campaigns": {}, "months": {"2026-09": {
            "이지수": att_row(checked=False, source="telegram",
                              text="근태 완료했습니다~", uid="1:2")}}}
        row = merge_attendance(main, ours)["months"]["2026-09"]["이지수"]
        self.assertEqual(row["source"], "telegram")
        self.assertEqual(row["text"], "근태 완료했습니다~")
        self.assertTrue(row["checked"])  # 어느 한쪽이라도 true면 true

    def test_collision_same_source_main_wins_note_kept(self):
        main = {"campaigns": {}, "months": {"2026-09": {
            "유지웅": att_row(note="구두 확인")}}}
        ours = {"campaigns": {}, "months": {"2026-09": {"유지웅": att_row()}}}
        row = merge_attendance(main, ours)["months"]["2026-09"]["유지웅"]
        self.assertEqual(row["note"], "구두 확인")

    def test_campaign_main_wins(self):
        # 내 run 도중 main에서 마감됐으면 마감이 정본이다.
        main = {"campaigns": {"2026-09": {"status": "closed"}}, "months": {}}
        ours = {"campaigns": {"2026-09": {"status": "open"}}, "months": {}}
        self.assertEqual(merge_attendance(main, ours)["campaigns"]["2026-09"]["status"],
                         "closed")


class UidStoreMergeTest(unittest.TestCase):
    def test_union_and_main_wins_collision(self):
        main = {"entries": {"a": {"done": True}, "b": {"done": False}}}
        ours = {"entries": {"a": {"done": False}, "c": {"done": False}}}
        merged = merge_uid_store(main, ours)
        self.assertTrue(merged["entries"]["a"]["done"])  # op 수정(main) 우선
        self.assertIn("b", merged["entries"])
        self.assertIn("c", merged["entries"])  # 내 run의 신규


class ScanStateMergeTest(unittest.TestCase):
    def test_last_id_max(self):
        main = {"chats": {"1": {"name": "이준범", "last_id": 100}}}
        ours = {"chats": {"1": {"name": "이준범", "last_id": 120},
                          "group:9": {"name": "시니어방", "last_id": 5}}}
        merged = merge_scan_state(main, ours)
        self.assertEqual(merged["chats"]["1"]["last_id"], 120)
        self.assertIn("group:9", merged["chats"])


if __name__ == "__main__":
    unittest.main()
