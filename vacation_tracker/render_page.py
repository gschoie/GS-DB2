"""entries.json → 대시보드 페이지(vacation_report.html).

표준 라이브러리만 쓴다. 다른 리포트 페이지들과 같은 다크 테마.
"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from rules import KST

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "telegram_research_dashboard" / "static" / "vacation_report.html"

WEEKDAY_KO = "월화수목금토일"

PAGE_CSS = """
:root{color-scheme:dark}
body{margin:0;padding:28px 24px 60px;background:#0d1117;color:#d8dee9;
  font-family:'Pretendard','Malgun Gothic','Apple SD Gothic Neo',sans-serif;line-height:1.7;font-size:15px}
.wrap{max-width:900px;margin:0 auto}
h1{font-size:21px;color:#e8edf5;margin:0 0 4px}
.meta{color:#8b96a8;font-size:12.5px;margin-bottom:22px}
h2{font-size:16.5px;color:#7fb4ff;margin:30px 0 10px;padding-bottom:6px;border-bottom:1px solid #223046}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{padding:8px 10px;border-bottom:1px solid #1c2534;text-align:left;vertical-align:top}
th{color:#8b96a8;font-weight:600;font-size:12.5px}
tr.today td{background:#14202f}
.badge{display:inline-block;padding:1px 8px;border-radius:20px;font-size:12px;
  background:#1d2a3d;color:#9fc1ff;border:1px solid #2c3a52;white-space:nowrap}
.badge.review{background:#3d2626;color:#ffb3b3;border-color:#5a3535}
.src{color:#8b96a8;font-size:12.5px}
.name{font-weight:700;color:#e8edf5;white-space:nowrap}
.empty{color:#8b96a8;padding:18px 0}
"""


def _span(entry: dict) -> str:
    if not entry.get("start"):
        return "날짜 미상"
    start = datetime.fromisoformat(entry["start"])
    text = f"{start.strftime('%m/%d')}({WEEKDAY_KO[start.weekday()]})"
    end_raw = entry.get("end") or entry["start"]
    if end_raw != entry["start"]:
        end = datetime.fromisoformat(end_raw)
        days = (end - start).days + 1
        text += f" ~ {end.strftime('%m/%d')}({WEEKDAY_KO[end.weekday()]}) · {days}일"
    return text


def _row(entry: dict, today: str) -> str:
    start, end = entry.get("start"), entry.get("end") or entry.get("start")
    active = ' class="today"' if start and start <= today <= (end or start) else ""
    badge = ('<span class="badge review">확인 필요</span>' if entry.get("needs_review")
             else f'<span class="badge">{html.escape(str(entry.get("kind") or "휴가"))}</span>')
    note = html.escape(str(entry.get("note") or ""))
    msg_date = str(entry.get("msg_date") or "")[:16].replace("T", " ")
    source = html.escape(str(entry.get("text") or "")[:140])
    return (f"<tr{active}><td class=\"name\">{html.escape(str(entry.get('name') or '?'))}</td>"
            f"<td>{_span(entry)}</td><td>{badge}</td>"
            f"<td>{note}<div class=\"src\">{msg_date} · “{source}”</div></td></tr>")


def build_page(store: dict) -> Path:
    entries = list((store.get("entries") or {}).values())
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")

    dated = sorted((e for e in entries if e.get("start")),
                   key=lambda e: (e["start"], e.get("name") or ""))
    upcoming = [e for e in dated if (e.get("end") or e["start"]) >= today]
    past = [e for e in dated if (e.get("end") or e["start"]) < today][::-1]  # 최근 순
    review = [e for e in entries if not e.get("start")]

    def table(rows: list[dict]) -> str:
        if not rows:
            return '<p class="empty">기록 없음</p>'
        body = "".join(_row(e, today) for e in rows)
        return ("<table><thead><tr><th>이름</th><th>기간</th><th>종류</th><th>메모 · 원문</th>"
                f"</tr></thead><tbody>{body}</tbody></table>")

    doc = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>친구 휴가 일정</title><style>{PAGE_CSS}</style></head>
<body><div class="wrap">
<h1>🏖️ 친구 휴가 일정</h1>
<p class="meta">지정한 친구들과의 텔레그램 1:1 대화에서 휴가 보고를 자동으로 잡아 정리 ·
갱신 {now.strftime('%Y-%m-%d %H:%M')} KST · 총 {len(entries)}건</p>
<h2>다가오는 휴가 ({len(upcoming)}건)</h2>
{table(upcoming)}
<h2>지난 휴가 ({len(past)}건)</h2>
{table(past)}
"""
    if review:
        doc += f"<h2>확인 필요 — 날짜를 못 읽은 보고 ({len(review)}건)</h2>\n{table(review)}\n"
    doc += "</div></body></html>\n"

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(doc, encoding="utf-8")
    print(f"페이지 생성: {OUT_PATH}")
    return OUT_PATH
