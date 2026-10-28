"""연차계획서(이미지 추출) 반영 검사 — 기간 묶기·교체 의미론·중복 생략."""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vacation_bot  # noqa: E402
from vacation_bot import _plan_spans  # noqa: E402

ROWS = [
    {"date": "2026.07.27", "kind": "종일"},
    {"date": "2026.07.28", "kind": "종일"},
    {"date": "2026.08.13", "kind": "오전"},
    {"date": "2026.10.26", "kind": "오전"},
    {"date": "2026.11.24", "kind": "종일"},
    {"date": "2026.11.25", "kind": "종일"},
    {"date": "2026.12.23", "kind": "종일"},
    {"date": "2026.12.24", "kind": "종일"},
    {"date": "2026.12.28", "kind": "오전"},
]


class SpanTest(unittest.TestCase):
    def test_grouping_and_kind(self):
        # 실사례(이다연 계획서 9행) — 연속 종일은 한 기간, 오전은 하루짜리 반차.
        spans = _plan_spans(ROWS)
        self.assertEqual([(s["start"], s["end"], s["kind"]) for s in spans], [
            ("2026-07-27", "2026-07-28", "연차"),
            ("2026-08-13", "2026-08-13", "오전반차"),
            ("2026-10-26", "2026-10-26", "오전반차"),
            ("2026-11-24", "2026-11-25", "연차"),
            ("2026-12-23", "2026-12-24", "연차"),
            ("2026-12-28", "2026-12-28", "오전반차"),
        ])

    def test_bad_rows_skipped(self):
        self.assertEqual(_plan_spans([{"date": "날짜아님", "kind": "종일"}]), [])


class ApplyTest(unittest.TestCase):
    def _run(self, store, payload):
        saved = {}
        with mock.patch.object(vacation_bot, "load_json", return_value=store), \
             mock.patch.object(vacation_bot, "save_json",
                               side_effect=lambda p, d: saved.update(d)), \
             mock.patch.dict(sys.modules, {"render_page": mock.MagicMock()}):
            vacation_bot.apply_plan(json.dumps(payload, ensure_ascii=False))
        return saved

    def test_apply_and_replace(self):
        store = {"entries": {}}
        self._run(store, {"name": "이다연", "rows": ROWS})
        plan_uids = [u for u, e in store["entries"].items()
                     if u.startswith("plan:이다연:") and not e.get("deleted")]
        self.assertEqual(len(plan_uids), 6)
        # 재등록: 11/24-25가 빠지고 12/28이 종일로 바뀐 새 계획 → 교체
        rows2 = [r for r in ROWS if not r["date"].startswith("2026.11")]
        rows2[-1] = {"date": "2026.12.28", "kind": "종일"}
        self._run(store, {"name": "이다연", "rows": rows2})
        e_nov = store["entries"]["plan:이다연:2026-11-24"]
        self.assertTrue(e_nov.get("deleted"))  # 빠진 날짜는 묘비
        e_dec = store["entries"]["plan:이다연:2026-12-28"]
        self.assertFalse(e_dec.get("deleted"))
        self.assertEqual(e_dec["kind"], "연차")  # 오전반차 → 연차로 갱신

    def test_telegram_duplicate_annotated(self):
        # 텔레그램으로 이미 잡힌 같은 이름·기간은 계획서가 중복 칩을 안 만들되,
        # 조용히 넘기지 않고 그 항목 메모에 '연차계획서에도 있음'을 단다(10/28 요청).
        store = {"entries": {"5:1": {"name": "이다연", "kind": "연차",
                                     "start": "2026-11-24", "end": "2026-11-25",
                                     "engine": "gemini", "note": "구두 확인"}}}
        self._run(store, {"name": "이다연", "rows": ROWS})
        self.assertNotIn("plan:이다연:2026-11-24", store["entries"])
        self.assertIn("plan:이다연:2026-07-27", store["entries"])
        note = store["entries"]["5:1"]["note"]
        self.assertIn(vacation_bot.PLAN_ALSO_MARK, note)
        self.assertIn("구두 확인", note)  # 기존 메모는 지우지 않는다
        # 재등록해도 표시는 한 번만.
        self._run(store, {"name": "이다연", "rows": ROWS})
        self.assertEqual(store["entries"]["5:1"]["note"].count(vacation_bot.PLAN_ALSO_MARK), 1)
        # 새 계획에서 그 날짜가 빠지면 표시도 걷힌다(낡은 표시 잔류 방지).
        rows2 = [r for r in ROWS if not r["date"].startswith("2026.11")]
        self._run(store, {"name": "이다연", "rows": rows2})
        self.assertEqual(store["entries"]["5:1"]["note"], "구두 확인")

    def test_missing_name_rejected(self):
        with self.assertRaises(SystemExit):
            self._run({"entries": {}}, {"name": "", "rows": ROWS})


if __name__ == "__main__":
    unittest.main()
