"""DAOL 리서치 톤(daol-research-tone) 데이터·컨센 DB를 발간 보고서에 접목한다.

build_static이 빌드 시점에 호출한다.
1) 톤 보드가 AI로 분석해 둔 보고서별 필드(한줄 설명·투자포인트·TP 조정 논리·실적
   방향·애널 추정 vs 당시 컨센)를 다올 시절 보고서 행에 매칭해 `report["tone"]`으로 붙인다.
   매칭 키는 단축링크(양쪽 다 bit.ly)를 1순위, (기업명, KST 날짜 ±1일)을 폴백으로 쓴다.
2) 종목별 시장 스냅샷 `market`을 만든다 —
   · 타사 TP MAX/MIN/중앙값·커버 증권사 수: 톤 보드의 한경 에이셀 60일 수집분을
     증권사별 최신 1건으로 중복 제거해 계산
   · 올해E/내년E 영업이익 컨센: kospi_consensus 주간 스냅샷 DB(리포지토리에 커밋됨)
   · 나의 최신 연간 영업이익 추정: 톤 AI가 내 보고서 본문에서 뽑은 값(당해 연도만 —
     내년 추정은 톤 스키마에 없어 컨센만 표시된다)

push 빌드에서도 돌도록 표준 라이브러리만 쓴다. 톤 JSON을 못 가져오면
직전 배포본 → 리포지토리에 커밋된 _site 사본 순으로 폴백한다.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
TONE_V2_URL = "https://gschoie.github.io/DAOL-RESEARCH-TONE/daol_tone_v2.json"
TONE_V2_LOCAL = ROOT / "_site" / "daol_tone_v2.json"
CONSENSUS_DB = ROOT.parent / "kospi_consensus" / "data" / "consensus.db"


def _norm_link(url: str | None) -> str | None:
    """단축링크 비교용 정규화. 호스트만 소문자화한다(bit.ly 경로는 대소문자 구분)."""
    if not url:
        return None
    u = url.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    host, _, path = u.partition("/")
    host = host.lower().removeprefix("www.")
    return f"{host}/{path}" if path else host


def _kst_date(posted_at: str) -> str | None:
    try:
        return (datetime.fromisoformat(posted_at) + timedelta(hours=9)).date().isoformat()
    except (TypeError, ValueError):
        return None


def load_tone() -> dict | None:
    """톤 v2 JSON: env 오버라이드 → 톤 사이트 → 커밋된 _site 사본 순."""
    src = os.getenv("TONE_V2_SRC", "")
    if src and not src.startswith("http"):
        return json.loads(Path(src).read_text(encoding="utf-8"))
    for attempt in (src or TONE_V2_URL, None):
        if not attempt:
            break
        try:
            request = Request(attempt, headers={"User-Agent": "GSResearchDashboard/1.0"})
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except Exception as exc:  # noqa: BLE001 — 네트워크 실패는 폴백으로
            print(f"톤 JSON 가져오기 실패({exc}) — 폴백 사용")
    if TONE_V2_LOCAL.exists():
        return json.loads(TONE_V2_LOCAL.read_text(encoding="utf-8"))
    return None


def _tone_fields(record: dict) -> dict:
    """임베드할 보고서별 톤 필드만 추린다(용량 절약)."""
    annual = ((record.get("est_compare") or {}).get("annual")) or {}
    fields = {
        "one_line": (record.get("one_line") or "")[:120],
        "points": (record.get("points") or [])[:4],
        "tp_reasons": ((record.get("tp_event") or {}).get("reasons") or [])[:3],
        "tp_ev": ((record.get("tp_event") or {}).get("evidence") or "")[:600],
        "earn": record.get("earnings_direction") or "",
        "earn_ev": (record.get("earnings_evidence") or "")[:140],
        "est": {"label": annual.get("label"), "op": annual.get("op")}
               if (annual.get("op") or {}).get("our") else None,
        "conviction": record.get("conviction"),
        "tone_label": record.get("tone_label") or "",
    }
    return {key: value for key, value in fields.items() if value}


def _build_indexes(tone: dict) -> tuple[dict, dict]:
    by_link: dict[str, dict] = {}
    by_co_date: dict[tuple[str, str], dict] = {}
    for key, company in (tone.get("companies") or {}).items():
        for record in company.get("timeline") or []:
            if record.get("bundled"):  # 산업 인뎁스에서 합성된 종목 페이지 레코드
                continue
            for url in (record.get("source_url"), record.get("post_url"), record.get("pdf_url")):
                link = _norm_link(url)
                if link:
                    by_link.setdefault(link, record)
            if not key.startswith("IND:"):
                name = record.get("company") or company.get("name")
                if name and record.get("date"):
                    by_co_date.setdefault((name, record["date"]), record)
    return by_link, by_co_date


def _match(report: dict, by_link: dict, by_co_date: dict) -> dict | None:
    link = _norm_link(report.get("original_url"))
    if link and link in by_link:
        return by_link[link]
    day = _kst_date(report.get("posted_at") or "")
    if not day:
        return None
    base = datetime.fromisoformat(day)
    for name in report.get("company_names") or []:
        for offset in (0, -1, 1):  # 텔레그램 게시가 리포트 날짜와 하루 어긋나는 경우
            candidate = by_co_date.get((name, (base + timedelta(days=offset)).date().isoformat()))
            if candidate:
                return candidate
    return None


def _annual_consensus() -> dict[str, dict]:
    """kospi_consensus 최신 스냅샷에서 종목별 올해E/내년E 영업이익(억원)."""
    if not CONSENSUS_DB.exists():
        return {}
    year = (datetime.now(timezone.utc) + timedelta(hours=9)).year
    out: dict[str, dict] = {}
    with sqlite3.connect(CONSENSUS_DB) as conn:
        conn.row_factory = sqlite3.Row
        last = conn.execute("SELECT MAX(snapshot_date) d FROM consensus_snapshots").fetchone()["d"]
        if not last:
            return {}
        rows = conn.execute(
            "SELECT code, period, op_profit FROM consensus_snapshots "
            "WHERE snapshot_date=? AND kind='annual' AND op_profit IS NOT NULL", (last,))
        for row in rows:
            slot = {str(year): "this", str(year + 1): "next"}.get(row["period"][:4])
            if slot:
                entry = out.setdefault(row["code"], {"asof": last})
                entry[slot] = {"label": f"{row['period'][:4]}E", "op": row["op_profit"]}
    return {code: entry for code, entry in out.items() if "this" in entry or "next" in entry}


def _street_snapshot(company: dict) -> dict | None:
    """한경 에이셀 60일 수집분 → 증권사별 최신 TP로 중복 제거해 MAX/MIN/중앙값·커버 수."""
    items = ((company.get("street") or {}).get("items")) or []
    latest: dict[str, dict] = {}
    for item in sorted(items, key=lambda x: (x.get("date") or "", x.get("id") or 0)):
        if item.get("tp_new") and item.get("brokerage"):
            latest[item["brokerage"]] = item
    if not latest:
        return None
    prices = sorted(entry["tp_new"] for entry in latest.values())
    daol = ((company.get("street") or {}).get("stats") or {}).get("daol")
    snapshot = {
        "n": len(prices), "max": prices[-1], "min": prices[0],
        "median": prices[len(prices) // 2],
        "brokers": sorted(latest), "asof": max(e["date"] for e in latest.values()),
    }
    if daol:
        snapshot["daol"] = daol
        snapshot["daol_pct"] = round(100 * sum(1 for p in prices if p <= daol) / len(prices))
    return snapshot


def _my_estimate(company: dict) -> dict | None:
    """타임라인 최신 역순으로, AI가 뽑은 내 연간 영업이익 추정(당시 컨센 대비 포함)."""
    for record in reversed(company.get("timeline") or []):
        annual = ((record.get("est_compare") or {}).get("annual")) or {}
        op = annual.get("op") or {}
        if op.get("our"):
            return {"label": annual.get("label"), "op": op["our"], "cons_at": op.get("cons"),
                    "diff_at_pct": op.get("diff_pct"), "date": record.get("date")}
    return None


def _build_market(tone: dict) -> dict:
    consensus = _annual_consensus()
    market: dict[str, dict] = {}
    for key, company in (tone.get("companies") or {}).items():
        if key.startswith("IND:"):
            continue
        name = company.get("name")
        code = company.get("code") or key
        entry: dict = {}
        street = _street_snapshot(company)
        if street:
            entry["street"] = street
        if code in consensus:
            entry["cons"] = consensus[code]
        mine = _my_estimate(company)
        if mine:
            entry["mine"] = mine
        if name and entry:
            entry["code"] = code
            market[name] = entry
    return market


def attach_tone_market(reports: list[dict], previous_payload) -> dict:
    """보고서 리스트에 tone 필드를 부착하고 market 맵을 돌려준다.

    previous_payload: 톤 JSON을 전혀 못 구했을 때만 부르는 지연 폴백(현재 배포본).
    """
    tone = load_tone()
    if tone:
        by_link, by_co_date = _build_indexes(tone)
        matched = 0
        for report in reports:
            record = _match(report, by_link, by_co_date)
            if record:
                fields = _tone_fields(record)
                if fields:
                    report["tone"] = fields
                    matched += 1
        market = _build_market(tone)
        print(f"톤 접목: 보고서 {matched}건 매칭 · 시장 스냅샷 {len(market)}종목 "
              f"(톤 생성 {str(tone.get('generated_at') or '')[:16]})")
        return market

    prior = previous_payload() or {}
    prior_tone = {r.get("message_id"): r.get("tone")
                  for r in prior.get("reports") or [] if r.get("tone")}
    restored = 0
    for report in reports:
        fields = prior_tone.get(report.get("message_id"))
        if fields and "tone" not in report:
            report["tone"] = fields
            restored += 1
    market = prior.get("market") or {}
    print(f"톤 접목: 소스 없음 — 직전 배포본에서 {restored}건·시장 {len(market)}종목 보존")
    return market
