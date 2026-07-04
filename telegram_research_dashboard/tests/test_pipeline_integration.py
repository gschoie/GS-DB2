"""seed -> db -> build_static 전체 경로가 스키마/공유 모듈 변경에도 안 깨지는지 확인하는 스모크 테스트.

이 테스트가 실패하면 article_metadata.py/db.py/schema.sql 같은 공유 모듈을 쓰는
build_static.py 등 소비자 어딘가가 깨졌다는 뜻이다.
"""
from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path


class PipelineIntegrationTest(unittest.TestCase):
    def setUp(self):
        # sqlite3 커넥션은 `with connect() as conn`으로 커밋만 되고 닫히지 않아
        # Windows에서 임시 디렉토리 삭제 시 파일 잠금이 걸릴 수 있어 ignore_cleanup_errors를 쓴다.
        self.tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmpdir.cleanup)

        self.output_path = Path(self.tmpdir.name) / "output.html"
        env_patch = {
            "DATABASE_PATH": str(Path(self.tmpdir.name) / "test.db"),
            "DASHBOARD_OUTPUT": str(self.output_path),
        }
        self._old_env = {key: os.environ.get(key) for key in env_patch}
        os.environ.update(env_patch)
        self.addCleanup(self._restore_env)

        import build_static
        import seed

        # OUTPUT은 build_static 모듈 로드 시점에 한 번 계산되므로 env 반영을 위해 재로딩한다.
        self.build_static = importlib.reload(build_static)
        self.seed = importlib.reload(seed)

    def _restore_env(self):
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_seed_through_build_static_produces_valid_dashboard(self):
        self.seed.seed()
        result_path = self.build_static.build()

        self.assertEqual(result_path, self.output_path)
        html = self.output_path.read_text(encoding="utf-8")

        marker = "window.__DASHBOARD_DATA__="
        start = html.index(marker) + len(marker)
        end = html.index(";</script>", start)
        data = json.loads(html[start:end])

        self.assertGreater(len(data["reports"]), 0)
        self.assertGreater(len(data["news"]), 0)
        self.assertEqual(data["summary"]["reports"], len(data["reports"]))
        self.assertEqual(data["summary"]["news"], len(data["news"]))
        for report in data["reports"]:
            self.assertIn("company_names", report)
        for article in data["news"]:
            self.assertIn("company_names", article)


if __name__ == "__main__":
    unittest.main()
