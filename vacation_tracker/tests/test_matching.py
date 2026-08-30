"""친구 이름 → 대화 매칭 계약 테스트 (네트워크 없음)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vacation_bot import pick_dialog

DIRECTORY = {
    "이준범다리": "E1",   # 대화명에 '다리' 수식어가 붙는 관행
    "다리박영도": "E2",   # 앞에 붙어도 잡혀야 한다
    "김지원": "E3",       # 수식어 없는 정확 일치
    "이정우다리": "E4",
    "이정우회사": "E5",   # 동명 2개지만 '다리' 붙은 쪽 우선
    "최민수다리": "E7",
    "최민수형다리": "E8",  # '다리'도 2개 → 보류
    "한수빈(디엘)다리": "E6",
}


class Matching(unittest.TestCase):
    def test_exact(self):
        entity, _ = pick_dialog("김지원", DIRECTORY)
        self.assertEqual(entity, "E3")

    def test_suffix_dari(self):
        entity, how = pick_dialog("이준범", DIRECTORY)
        self.assertEqual(entity, "E1")
        self.assertIn("포함 일치", how)

    def test_prefix_dari(self):
        entity, _ = pick_dialog("박영도", DIRECTORY)
        self.assertEqual(entity, "E2")

    def test_decorated(self):
        entity, _ = pick_dialog("한수빈", DIRECTORY)
        self.assertEqual(entity, "E6")

    def test_spaces_ignored(self):
        entity, _ = pick_dialog("이 준범", DIRECTORY)
        self.assertEqual(entity, "E1")

    def test_ambiguous_prefers_dari(self):
        entity, how = pick_dialog("이정우", DIRECTORY)
        self.assertEqual(entity, "E4")
        self.assertIn("다리 우선", how)

    def test_two_dari_is_held(self):
        entity, how = pick_dialog("최민수", DIRECTORY)
        self.assertIsNone(entity)
        self.assertIn("보류", how)

    def test_missing(self):
        entity, how = pick_dialog("없는사람", DIRECTORY)
        self.assertIsNone(entity)
        self.assertIn("없습니다", how)


if __name__ == "__main__":
    unittest.main()
