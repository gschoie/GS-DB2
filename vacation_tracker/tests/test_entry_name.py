"""항목 귀속(이름) 검사 — 제3자 보고의 주인 귀속 포함 (10/14 실사례)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vacation_bot import resolve_entry_name  # noqa: E402


class ResolveNameTest(unittest.TestCase):
    def cand(self, by_me=False):
        return {"name": "이준범", "by_me": by_me,
                "text": "사수님 21-22 휴가시다"}

    def test_partner_reports_owner_schedule(self):
        # "팀장님 내일 연차시죠"(상대) → 계정 주인(최광식) 일정
        self.assertEqual(resolve_entry_name(self.cand(), {"who": "주인"}, "최광식"),
                         "최광식")

    def test_owner_tells_junior_own_schedule_third_person(self):
        # "사수님 21-22 휴가시다"를 계정 주인이 주니어에게 보냄(10/14 실사례) —
        # 3인칭 호칭이라도 who='주인'이면 owner 귀속.
        self.assertEqual(resolve_entry_name(self.cand(by_me=True), {"who": "주인"}, "최광식"),
                         "최광식")

    def test_partner_own_schedule_stays_partner(self):
        self.assertEqual(resolve_entry_name(self.cand(), {"who": "상대"}, "최광식"),
                         "이준범")

    def test_my_own_schedule_goes_to_owner(self):
        self.assertEqual(resolve_entry_name(self.cand(by_me=True), {"who": "본인"}, "최광식"),
                         "최광식")

    def test_partner_claiming_bonin_is_partner(self):
        # 상대 메시지의 who=본인 은 '보낸 사람 본인' = 대화 상대다.
        self.assertEqual(resolve_entry_name(self.cand(), {"who": "본인"}, "최광식"),
                         "이준범")

    def test_no_owner_configured_falls_back(self):
        self.assertEqual(resolve_entry_name(self.cand(), {"who": "주인"}, ""),
                         "이준범")
