"""dart_capacity 공통 — 경로·설정·보고서 인덱스."""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "config" / "companies.yaml"
DATA = BASE / "data"
RAW = DATA / "raw"
EXTRACTED = DATA / "extracted"
NORMALIZED = DATA / "normalized"
REPORTS_INDEX = DATA / "reports.json"      # fetch 가 찾은 정기보고서 목록(누적)
REVIEW_CSV = DATA / "review.csv"

DART_VIEWER = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

_REPORT_RE = re.compile(r"(사업보고서|반기보고서|분기보고서)\s*\((\d{4})\.(\d{2})\)")


def load_companies() -> list[dict]:
    with CONFIG.open(encoding="utf-8") as fh:
        rows = yaml.safe_load(fh)["companies"]
    out = []
    for row in rows:
        out.append({
            "sector": str(row["sector"]),
            "name": str(row["name"]),
            "stock_code": str(row.get("stock_code") or "").strip(),
            "aliases": [str(a) for a in (row.get("aliases") or [])],
        })
    return out


def parse_report_name(report_nm: str) -> dict:
    """'[기재정정]사업보고서 (2024.12)' → type/period/corrected."""
    m = _REPORT_RE.search(report_nm or "")
    if not m:
        return {"report_type": "", "period": "", "corrected": "정정" in (report_nm or "")}
    kind, year, month = m.group(1), m.group(2), m.group(3)
    report_type = {"사업보고서": "annual", "반기보고서": "half", "분기보고서": "quarter"}[kind]
    label = {"annual": "사업보고서", "half": "반기", "quarter": f"{'1Q' if month == '03' else '3Q'}"}[report_type]
    return {
        "report_type": report_type,
        "period": f"{year}-{month}",          # 보고 기준 월(기말)
        "period_label": f"{year}.{month} {label}",
        "corrected": "정정" in report_nm,
    }


def load_index() -> dict[str, dict]:
    if REPORTS_INDEX.exists():
        with REPORTS_INDEX.open(encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def save_index(index: dict[str, dict]) -> None:
    REPORTS_INDEX.parent.mkdir(parents=True, exist_ok=True)
    rows = dict(sorted(index.items(), key=lambda kv: (kv[1].get("stock_code", ""), kv[0])))
    with REPORTS_INDEX.open("w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)
