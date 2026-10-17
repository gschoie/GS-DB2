#!/usr/bin/env python3
"""건기 전략 레이더 발행 도구 — 신제품·CAPEX·M&A/제휴 누적 대시보드.

건설기계 브리핑(데일리·GPT판)에서 잡히는 뉴스 가운데 ① 신제품 출시
② CAPEX(공장 신설·증설·생산능력 확대) ③ M&A·지분·장기 파트너십을
따로 떼어 계속 쌓는 페이지다 — 방산의 수주 파이프라인/국방예산,
에너지의 LNG FID처럼 '지나가면 잊히는 전략 이벤트'를 한 판에 모은다.

데이터 정본: telegram_research_dashboard/static/construction_strategy/events.json
  (static 밑에 두는 이유 — claude-brief-ingest 가 static 경로만 main 으로
   나르므로, 세션 브랜치에서 추가한 이벤트가 데이터째 main 에 보존된다.)
산출물:    telegram_research_dashboard/static/construction_strategy_report.html

세션 루틴 [7.7]: 그날 건기 뉴스에서 세 분류에 해당하는 이벤트가 있으면
events.json 에 추가(중복 금지 — 같은 사건의 후속 보도는 기존 항목 note 갱신)
→ 이 스크립트 실행 → 건기 3종 커밋에 함께 태운다. 이벤트가 없는 날은
아무것도 하지 않는다(빈 날을 억지로 채우지 않는다).

사용: python3 construction_briefing/strategy_tracker_publish.py
"""
from __future__ import annotations

import json
import html as html_mod
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
DASH_STATIC = REPO / "telegram_research_dashboard" / "static"
DATA = DASH_STATIC / "construction_strategy" / "events.json"
PAGE = DASH_STATIC / "construction_strategy_report.html"

CATS = {
    "product": ("🆕 신제품", "#6aa8ff"),
    "capex":   ("🏭 CAPEX", "#ffc46b"),
    "ma":      ("🤝 M&A·제휴", "#7ee29b"),
}


def esc(s: str) -> str:
    return html_mod.escape(str(s or ""), quote=True)


def load_events() -> list[dict]:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    events = [e for e in data.get("events", []) if e.get("cat") in CATS]
    # 최신순 — 같은 날짜는 입력 순서 유지
    return sorted(events, key=lambda e: e.get("date", ""), reverse=True)


def month_label(date_str: str) -> str:
    y, m = date_str[:4], date_str[5:7]
    return f"{y}년 {int(m)}월"


def row_html(e: dict) -> str:
    label, color = CATS[e["cat"]]
    d = e.get("date", "")
    try:
        wd = "월화수목금토일"[datetime.strptime(d, "%Y-%m-%d").weekday()]
        date_txt = f"{d[5:]}({wd})"
    except ValueError:
        date_txt = d
    note = f'<div class="note">{esc(e["note"])}</div>' if e.get("note") else ""
    links = []
    if e.get("ref"):
        links.append(f'<a href="{esc(e["ref"])}" target="_blank" rel="noopener">브리핑</a>')
    if e.get("url"):
        links.append(f'<a href="{esc(e["url"])}" target="_blank" rel="noopener">기사</a>')
    link_html = " · ".join(links)
    return (
        f'<tr class="ev" data-cat="{e["cat"]}">'
        f'<td class="d">{esc(date_txt)}</td>'
        f'<td><span class="badge" style="color:{color};border-color:{color}55">{label}</span></td>'
        f'<td class="co">{esc(e.get("company", ""))}</td>'
        f'<td class="tt">{esc(e.get("title", ""))}{note}</td>'
        f'<td class="lk">{link_html}</td></tr>'
    )


def build(events: list[dict]) -> str:
    counts = {k: sum(1 for e in events if e["cat"] == k) for k in CATS}
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    first = events[-1]["date"] if events else ""

    body_rows: list[str] = []
    cur_month = None
    for e in events:
        m = month_label(e["date"])
        if m != cur_month:
            body_rows.append(f'<tr class="mon"><td colspan="5">{esc(m)}</td></tr>')
            cur_month = m
        body_rows.append(row_html(e))

    tabs = ['<button class="tab active" data-cat="all">전체 <span>%d</span></button>' % len(events)]
    for k, (label, color) in CATS.items():
        tabs.append(
            f'<button class="tab" data-cat="{k}" style="color:{color}">{label} <span>{counts[k]}</span></button>'
        )

    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>건기 전략 레이더</title><style>
:root{{color-scheme:dark}}
body{{margin:0;padding:28px 24px 60px;background:#0d1117;color:#d8dee9;
  font-family:'Pretendard','Malgun Gothic','Apple SD Gothic Neo',sans-serif;line-height:1.65;font-size:14.5px}}
.wrap{{max-width:980px;margin:0 auto}}
h1{{font-size:20px;color:#e8edf5;margin:0 0 4px}}
.meta{{color:#8b96a8;font-size:12.5px;margin-bottom:16px}}
.tabs{{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0 10px}}
.tab{{background:#161d29;color:#d8dee9;border:1px solid #2c3a52;border-radius:999px;
  padding:6px 14px;font-size:13px;cursor:pointer}}
.tab span{{color:#8b96a8;font-size:12px;margin-left:2px}}
.tab.active{{border-color:#6aa8ff;background:#17243a}}
table{{border-collapse:collapse;width:100%;margin:10px 0;font-size:13.5px}}
td{{border-bottom:1px solid #1d2838;padding:8px 9px;text-align:left;vertical-align:top}}
tr.ev:hover td{{background:#131a26}}
tr.mon td{{color:#ffc46b;font-size:12.5px;font-weight:700;border-bottom:1px solid #3a3046;
  padding-top:18px;background:transparent}}
td.d{{white-space:nowrap;color:#8b96a8;width:64px}}
td.co{{white-space:nowrap;font-weight:600;color:#f0f4fa;max-width:190px;overflow-wrap:break-word;white-space:normal}}
td.tt{{min-width:280px}}
td.lk{{white-space:nowrap;font-size:12.5px}}
.badge{{display:inline-block;border:1px solid;border-radius:999px;padding:1px 9px;font-size:11.5px;white-space:nowrap}}
.note{{color:#8b96a8;font-size:12.5px;margin-top:3px}}
a{{color:#6aa8ff;text-decoration:none}}a:hover{{text-decoration:underline}}
.foot{{color:#8b96a8;font-size:12px;margin-top:22px;border-top:1px solid #1d2838;padding-top:10px}}
@media(max-width:640px){{td.lk{{display:none}}body{{padding:18px 12px 50px}}}}
</style></head><body><div class="wrap">
<h1>🧭 건기 전략 레이더 — 신제품 · CAPEX · M&amp;A</h1>
<div class="meta">건설기계 브리핑에서 잡힌 전략 이벤트 누적 ({esc(first)}~) · 갱신 {esc(now)} · 총 {len(events)}건</div>
<div class="tabs">{''.join(tabs)}</div>
<table><tbody>
{''.join(body_rows)}
</tbody></table>
<div class="foot">매일 아침 건기 브리핑(데일리·GPT판) 작성 때 해당 분류의 뉴스만 추려 쌓습니다 —
같은 사건의 후속 보도는 새 줄을 만들지 않고 기존 항목에 덧붙입니다. '브리핑' 링크는 그날의 근거 브리핑.</div>
</div>
<script>
document.querySelectorAll('.tab').forEach(function(b){{
  b.addEventListener('click',function(){{
    document.querySelectorAll('.tab').forEach(function(x){{x.classList.remove('active')}});
    b.classList.add('active');
    var c=b.dataset.cat;
    document.querySelectorAll('tr.ev').forEach(function(r){{
      r.style.display=(c==='all'||r.dataset.cat===c)?'':'none';
    }});
    // 비는 월 구분줄 숨김
    document.querySelectorAll('tr.mon').forEach(function(m){{
      var n=m.nextElementSibling,show=false;
      while(n&&!n.classList.contains('mon')){{if(n.style.display!=='none'){{show=true;break}}n=n.nextElementSibling}}
      m.style.display=show?'':'none';
    }});
  }});
}});
</script></body></html>
"""


def main() -> None:
    events = load_events()
    PAGE.write_text(build(events), encoding="utf-8")
    print(f"[전략레이더] construction_strategy_report.html 생성 (이벤트 {len(events)}건)")


if __name__ == "__main__":
    main()
