import json
import os
import re
import sys
from pathlib import Path


def fail(message):
    print(f"::error::{message}")
    raise SystemExit(1)


def main():
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "_site/index.html")
    if not target.exists():
        fail(f"Deployment HTML does not exist: {target}")

    html = target.read_text(encoding="utf-8")
    marker = "window.__DASHBOARD_DATA__="
    start = html.find(marker)
    end = html.find(";</script>", start)
    if start < 0 or end < 0:
        fail("Embedded dashboard JSON was not found")

    try:
        data = json.loads(html[start + len(marker):end])
    except json.JSONDecodeError as exc:
        fail(f"Embedded dashboard JSON is invalid: {exc}")

    minimum_reports = int(os.getenv("MIN_DASHBOARD_REPORTS", "500"))
    minimum_news = int(os.getenv("MIN_DASHBOARD_NEWS", "5000"))
    minimum_tone = int(os.getenv("MIN_DAOL_TONE_REPORTS", "500"))
    summary = data.get("summary") or {}
    reports = data.get("reports") or []
    news = data.get("news") or []
    tone = data.get("tone") or {}

    checks = {
        "published reports": (len(reports), minimum_reports),
        "news archive": (len(news), minimum_news),
        "DAOL research tone": (int(tone.get("report_count") or 0), minimum_tone),
    }
    for label, (actual, minimum) in checks.items():
        if actual < minimum:
            fail(f"{label} data dropped to {actual}; minimum is {minimum}")

    if int(summary.get("reports") or 0) != len(reports):
        fail("Published report summary does not match the report list")
    if int(summary.get("news") or 0) != len(news):
        fail("News summary does not match the news list")

    required_patterns = {
        "published reports menu": r'id="reports"',
        "news archive menu": r'id="news"',
        "press coverage menu": r'id="press"',
        "DAOL research tone menu": r'data-view="tone"',
        "automation menu": r'<span>업무자동화</span>',
        # 메뉴 라벨은 자주 바뀌므로 'GEMS'가 들어간 그룹이 있는지만 확인한다(이름 변경에 안 깨지게).
        "GEMS menu": r'<span>[^<]*GEMS[^<]*</span>',
        "관리 menu": r'<span>관리</span>',
        "util links menu": r'<span>유틸\.링크</span>',
        "collapsed analyst report details": r'<details><summary>이달 발간 자료',
    }
    for label, pattern in required_patterns.items():
        if not re.search(pattern, html):
            fail(f"Required dashboard section is missing: {label}")

    if target.stat().st_size < 4_000_000:
        fail(f"Deployment HTML is unexpectedly small: {target.stat().st_size:,} bytes")

    print("Deployment safety checks passed")
    print(f"- Published reports: {len(reports):,}")
    print(f"- News archive: {len(news):,}")
    print(f"- DAOL research tone: {tone.get('report_count', 0):,}")
    print(f"- HTML size: {target.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
