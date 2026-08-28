"""SQLite 데이터와 화면 자산을 한 개의 독립 HTML 파일로 묶는다."""

from __future__ import annotations

import json
import os
import shutil
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from db import connect, initialize
from parser import APPROVED_COMPANIES
from tone_market import attach_tone_market


ROOT = Path(__file__).resolve().parent
OUTPUT = Path(os.getenv("DASHBOARD_OUTPUT", ROOT.parent / "GS_최광식_리서치_대시보드.html"))


def records(conn, sql: str) -> list[dict]:
    return [dict(row) for row in conn.execute(sql).fetchall()]


def previous_payload() -> dict:
    """캐시 일부가 유실되면 현재 배포본의 정상 섹션을 보존한다."""
    try:
        # 2026-08-18 Cloudflare Pages + Access 이관. 로그인 벽 때문에 서비스 토큰
        # (Zero Trust Service Token) 헤더가 있어야 통과한다 — 없으면 로그인 HTML이
        # 내려와 marker 미발견 → 빈 dict 폴백(안전망만 비활성, 빌드는 계속).
        headers = {"User-Agent": "GSResearchDashboard/1.0", "Cache-Control": "no-cache"}
        access_id = os.environ.get("CF_ACCESS_CLIENT_ID", "")
        access_secret = os.environ.get("CF_ACCESS_CLIENT_SECRET", "")
        if access_id and access_secret:
            headers["CF-Access-Client-Id"] = access_id
            headers["CF-Access-Client-Secret"] = access_secret
        request = Request("https://gschoie.github.io/GS-DB2/", headers=headers)
        with urlopen(request, timeout=30) as response:
            html = response.read().decode("utf-8", errors="replace")
        marker = "window.__DASHBOARD_DATA__="
        start = html.index(marker) + len(marker)
        end = html.index(";</script>", start)
        return json.loads(html[start:end])
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def build() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    initialize()
    with connect() as conn:
        summary = dict(conn.execute("""SELECT
          (SELECT COUNT(*) FROM reports) reports,
          (SELECT COUNT(*) FROM news_articles) news,
          (SELECT COUNT(*) FROM reports WHERE target_change='상향') upgrades,
          ((SELECT COUNT(*) FROM reports WHERE needs_review=1) +
           (SELECT COUNT(*) FROM news_articles WHERE needs_review=1) +
           (SELECT COUNT(*) FROM telegram_messages m WHERE NOT EXISTS
             (SELECT 1 FROM reports r WHERE r.message_id=m.id) AND NOT EXISTS
             (SELECT 1 FROM news_articles n WHERE n.message_id=m.id))) reviews""").fetchone())
        summary["updated_at"] = datetime.now(timezone(timedelta(hours=9))).isoformat()
        reports = records(conn, """SELECT r.*,m.posted_at,m.source_url,
          COALESCE((SELECT group_concat(c.name, ', ') FROM report_companies rc
            JOIN companies c ON c.id=rc.company_id WHERE rc.report_id=r.id),r.company_name) companies_label
          FROM reports r JOIN telegram_messages m ON m.id=r.message_id ORDER BY m.posted_at DESC""")
        news = records(conn, """SELECT n.*,m.posted_at,m.source_url,
          COALESCE((SELECT group_concat(c.name, ', ') FROM news_companies nc
            JOIN companies c ON c.id=nc.company_id WHERE nc.news_id=n.id),n.company_name) companies_label
          FROM news_articles n JOIN telegram_messages m ON m.id=n.message_id ORDER BY m.posted_at DESC""")
        companies = records(conn, """SELECT c.name,COUNT(*) mentions FROM (
          SELECT company_id FROM report_companies UNION ALL SELECT company_id FROM news_companies
          ) x JOIN companies c ON c.id=x.company_id GROUP BY c.id,c.name
          ORDER BY mentions DESC,c.name""")
        report_companies = records(conn, """SELECT c.name,COUNT(*) mentions FROM report_companies rc
          JOIN reports r ON r.id=rc.report_id JOIN companies c ON c.id=rc.company_id
          WHERE r.report_type!='위클리' AND c.name NOT LIKE '%투자증권%'
          GROUP BY c.id,c.name ORDER BY mentions DESC,c.name""")
        for report in reports:
            report["company_names"] = [row[0] for row in conn.execute(
                """SELECT c.name FROM report_companies rc JOIN companies c ON c.id=rc.company_id
                   WHERE rc.report_id=? ORDER BY c.name""", (report["id"],)
            )]
        for article in news:
            article["company_names"] = [row[0] for row in conn.execute(
                """SELECT c.name FROM news_companies nc JOIN companies c ON c.id=nc.company_id
                   WHERE nc.news_id=? ORDER BY c.name""", (article["id"],)
            )]

    if not reports:
        prior = previous_payload()
        reports = prior.get("reports") or []
        if reports:
            summary["reports"] = len(reports)
            summary["upgrades"] = sum(r.get("target_change") == "상향" for r in reports)
            print(f"현재 배포본에서 보고서 {len(reports):,}건 보존")

    # 표시용 기업명은 승인된 상장사 화이트리스트로만 남긴다(파서 폴백 노이즈 제거).
    # KAI·현대마린엔진 같은 구명칭은 표준명으로 통일한 뒤 필터링한다.
    aliases = {"KAI": "한국항공우주", "현대마린엔진": "HD현대마린엔진"}
    canonical = lambda name: aliases.get(name, name)
    approved = set(APPROVED_COMPANIES)
    for item in reports + news:
        kept = [n for n in dict.fromkeys(canonical(name) for name in item.get("company_names", []) if name) if n in approved]
        item["company_names"] = kept
        item["companies_label"] = ", ".join(kept) if kept else None
        item["company_name"] = item["companies_label"]
    company_counts = Counter(name for item in reports + news for name in item["company_names"])
    companies = [{"name": name, "mentions": count} for name, count in sorted(company_counts.items(), key=lambda x: (-x[1], x[0]))]
    report_counts = Counter(name for item in reports if item.get("report_type") != "위클리" for name in item["company_names"])
    report_companies = [{"name": name, "mentions": count} for name, count in sorted(report_counts.items(), key=lambda x: (-x[1], x[0]))]

    # DAOL 톤 보드(AI 분석)·컨센 DB 접목: 보고서별 tone 필드 + 종목별 시장 스냅샷(market).
    # 기업명 정규화(위 화이트리스트) 이후에 돌아야 톤 데이터의 표준명과 맞아떨어진다.
    market = attach_tone_market(reports, previous_payload)

    # 뉴스 키워드 검색(nq)용 텔레그램 원문. 메시지 단위로 중복 제거해 임베드한다(약 +2MB).
    with connect() as conn:
        news_texts = {str(row["id"]): row["text"] for row in conn.execute(
            "SELECT id,text FROM telegram_messages "
            "WHERE id IN (SELECT DISTINCT message_id FROM news_articles)")}

    # DAOL 리서치 톤은 별도 리포(gschoie/daol-research-tone)로 독립 — 화면은 iframe,
    # overview 패널은 그쪽 tone_summary.json을 런타임에 가져온다(여기 임베드 없음).
    union_path = ROOT / "data" / "hhiun_top.json"
    union = json.loads(union_path.read_text(encoding="utf-8")) if union_path.exists() else {"monthly": []}
    macro_path = ROOT / "data" / "macro.json"
    macro = json.loads(macro_path.read_text(encoding="utf-8")) if macro_path.exists() else {}
    # 방산 데일리 브리핑: static/defense_daily/<날짜>.md 최신본에서 위 2꼭지
    # (인트로 + '오늘의 핵심 요약')만 잘라 overview 카드에 굽는다. 두 번째 '## '(주요 주가 동향) 직전까지.
    defense_brief = {}
    ddir = ROOT / "static" / "defense_daily"
    md_files = sorted(ddir.glob("*.md")) if ddir.is_dir() else []
    if md_files:
        latest = md_files[-1]
        md_lines = latest.read_text(encoding="utf-8").splitlines()
        heads = [i for i, line in enumerate(md_lines) if line.startswith("## ")]
        end = heads[1] if len(heads) >= 2 else len(md_lines)
        summary_md = "\n".join(md_lines[:end]).strip()
        if summary_md:
            defense_brief = {"date": latest.stem, "summary": summary_md}
    # Claude 방산 브리핑(2탄): static/claude_defense/<날짜>.md — 같은 방식으로 요약 카드용 절단
    claude_brief = {}
    cdir = ROOT / "static" / "claude_defense"
    cmd_files = sorted(cdir.glob("????-??-??.md")) if cdir.is_dir() else []
    if cmd_files:
        latest = cmd_files[-1]
        md_lines = latest.read_text(encoding="utf-8").splitlines()
        heads = [i for i, line in enumerate(md_lines) if line.startswith("## ")]
        end = heads[1] if len(heads) >= 2 else len(md_lines)
        summary_md = "\n".join(md_lines[:end]).strip()
        if summary_md:
            claude_brief = {"date": latest.stem, "summary": summary_md}
    # 건설기계 브리핑: static/construction_daily/<날짜>.md — 같은 방식으로 요약 카드용 절단
    construction_brief = {}
    ndir = ROOT / "static" / "construction_daily"
    nmd_files = sorted(ndir.glob("????-??-??.md")) if ndir.is_dir() else []
    if nmd_files:
        latest = nmd_files[-1]
        md_lines = latest.read_text(encoding="utf-8").splitlines()
        heads = [i for i, line in enumerate(md_lines) if line.startswith("## ")]
        end = heads[1] if len(heads) >= 2 else len(md_lines)
        summary_md = "\n".join(md_lines[:end]).strip()
        if summary_md:
            construction_brief = {"date": latest.stem, "summary": summary_md}
    payload = json.dumps(
        {"summary": summary, "reports": reports, "news": news, "companies": companies,
         "reportCompanies": report_companies, "newsTexts": news_texts, "market": market,
         "union": union, "macro": macro, "defenseBrief": defense_brief,
         "claudeBrief": claude_brief, "constructionBrief": construction_brief},
        ensure_ascii=False, separators=(",", ":"),
    ).replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
    javascript = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    html = html.replace('<link rel="stylesheet" href="/styles.css">', f"<style>{css}</style>")
    html = html.replace(
        '<script src="/app.js"></script>',
        f"<script>window.__DASHBOARD_DATA__={payload};</script>\n<script>{javascript}</script>",
    )
    OUTPUT.write_text(html, encoding="utf-8")
    # 데이터가 HTML에 통째로 박히는 구조라 오래 열어둔 탭은 옛 데이터를 계속 보여준다.
    # 열린 탭이 새 배포를 감지할 수 있게 빌드 시각만 담은 작은 파일을 함께 배포한다.
    (OUTPUT.parent / "version.json").write_text(
        json.dumps({"updated_at": summary["updated_at"]}), encoding="utf-8"
    )
    # 리서치 톤·챗봇 새 창 래퍼 — 주소창에 톤 사이트 주소 대신 대시보드 주소만 보이게
    for wrapper in ("tone_full.html", "chat_full.html"):
        wrapper_src = ROOT / "static" / wrapper
        if wrapper_src.exists():
            shutil.copy2(wrapper_src, OUTPUT.parent / wrapper)
    union_report = ROOT / "static" / "hhiun_board_report.html"
    if union_report.exists():
        shutil.copy2(union_report, OUTPUT.parent / "hhiun_board_report.html")
    etf_report = ROOT / "static" / "etf_signal_report.html"
    if etf_report.exists():
        shutil.copy2(etf_report, OUTPUT.parent / "etf_signal_report.html")
    holdings_report = ROOT / "static" / "etf_holdings_report.html"
    if holdings_report.exists():
        shutil.copy2(holdings_report, OUTPUT.parent / "etf_holdings_report.html")
    consensus_report = ROOT / "static" / "consensus_revision.html"
    if consensus_report.exists():
        shutil.copy2(consensus_report, OUTPUT.parent / "consensus_revision.html")
    flow_report = ROOT / "static" / "market_flow_report.html"
    if flow_report.exists():
        shutil.copy2(flow_report, OUTPUT.parent / "market_flow_report.html")
    trend_report = ROOT / "static" / "market_trend_report.html"
    if trend_report.exists():
        shutil.copy2(trend_report, OUTPUT.parent / "market_trend_report.html")
    trend_dir = ROOT / "static" / "market_trend"
    if trend_dir.is_dir():
        shutil.copytree(trend_dir, OUTPUT.parent / "market_trend", dirs_exist_ok=True)
    consensus_xlsx = ROOT / "static" / "consensus_full.xlsx"
    if consensus_xlsx.exists():
        shutil.copy2(consensus_xlsx, OUTPUT.parent / "consensus_full.xlsx")
    valuation_report = ROOT / "static" / "valuation_report.html"
    if valuation_report.exists():
        shutil.copy2(valuation_report, OUTPUT.parent / "valuation_report.html")
    valuation_xlsx = ROOT / "static" / "valuation_full.xlsx"
    if valuation_xlsx.exists():
        shutil.copy2(valuation_xlsx, OUTPUT.parent / "valuation_full.xlsx")
    defense_index = ROOT / "static" / "defense_briefing_report.html"
    if defense_index.exists():
        shutil.copy2(defense_index, OUTPUT.parent / "defense_briefing_report.html")
    defense_dir = ROOT / "static" / "defense_daily"
    if defense_dir.is_dir():
        shutil.copytree(defense_dir, OUTPUT.parent / "defense_daily", dirs_exist_ok=True)
    weekly_index = ROOT / "static" / "defense_weekly_report.html"
    if weekly_index.exists():
        shutil.copy2(weekly_index, OUTPUT.parent / "defense_weekly_report.html")
    weekly_dir = ROOT / "static" / "defense_weekly"
    if weekly_dir.is_dir():
        shutil.copytree(weekly_dir, OUTPUT.parent / "defense_weekly", dirs_exist_ok=True)
    construction_index = ROOT / "static" / "construction_briefing_report.html"
    if construction_index.exists():
        shutil.copy2(construction_index, OUTPUT.parent / "construction_briefing_report.html")
    construction_dir = ROOT / "static" / "construction_daily"
    if construction_dir.is_dir():
        shutil.copytree(construction_dir, OUTPUT.parent / "construction_daily", dirs_exist_ok=True)
    construction_weekly_index = ROOT / "static" / "construction_weekly_report.html"
    if construction_weekly_index.exists():
        shutil.copy2(construction_weekly_index, OUTPUT.parent / "construction_weekly_report.html")
    construction_weekly_dir = ROOT / "static" / "construction_weekly"
    if construction_weekly_dir.is_dir():
        shutil.copytree(construction_weekly_dir, OUTPUT.parent / "construction_weekly", dirs_exist_ok=True)
    youtube_index = ROOT / "static" / "youtube_digest_report.html"
    if youtube_index.exists():
        shutil.copy2(youtube_index, OUTPUT.parent / "youtube_digest_report.html")
    youtube_dir = ROOT / "static" / "youtube_digest"
    if youtube_dir.is_dir():
        shutil.copytree(youtube_dir, OUTPUT.parent / "youtube_digest", dirs_exist_ok=True)
    claude_index = ROOT / "static" / "claude_defense_report.html"
    if claude_index.exists():
        shutil.copy2(claude_index, OUTPUT.parent / "claude_defense_report.html")
    claude_dir = ROOT / "static" / "claude_defense"
    if claude_dir.is_dir():
        shutil.copytree(claude_dir, OUTPUT.parent / "claude_defense", dirs_exist_ok=True)
    print(f"생성 완료: {OUTPUT} ({OUTPUT.stat().st_size / 1024 / 1024:.1f} MB)")
    return OUTPUT


if __name__ == "__main__":
    build()
