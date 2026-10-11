# -*- coding: utf-8 -*-
"""매크로 데스크 리포트 페이지.

static/macro_desk/<날짜>.json + config.yml + guide.yml → 단일 HTML.
출력: ../telegram_research_dashboard/static/macro_desk_report.html
구조·스타일은 market_flow / market_trend 와 같은 계열(820px, 라이트/다크 변수).

화면 구성(위에서부터)
  1. 지표판   — 금리·환율·원자재 현재값과 1D~12M 변화
  2. 달력     — 이번 달 + 다음 달 발표 일정 (규칙 추정일은 ~ 표시)
  3. 해석 카드 — 지표별 '숫자가 얼마면 무슨 뜻인가'
  4. 기초     — 처음 보는 사람이 먼저 알아야 할 것 + 자료 링크
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
from pathlib import Path

import yaml

import calendar_rules as cr
import releases as rl

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE.parent / "telegram_research_dashboard" / "static" / "macro_desk"
OUT = Path(os.environ.get(
    "MACRO_DESK_OUT",
    HERE.parent / "telegram_research_dashboard" / "static" / "macro_desk_report.html"))

WD = "월화수목금토일"
KST = dt.timezone(dt.timedelta(hours=9))
TONE = {"hot": ("neg", "⚠"), "warm": ("", "•"), "cool": ("pos", "✓")}
# 국기 이모지는 윈도우에서 안 그려져 'us'·'KR' 같은 **글자로 떨어진다** → 처음부터 글자 배지.
CC = {"US": "US", "KR": "KR"}


def esc(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def latest_payload() -> dict:
    files = sorted(DATA_DIR.glob("*.json")) if DATA_DIR.exists() else []
    if not files:
        return {}
    return json.loads(files[-1].read_text(encoding="utf-8"))


# ── 1. 지표판 ───────────────────────────────────────────────────────────────
def fmt_value(v: float, unit: str) -> str:
    if v is None:
        return "–"
    if unit == "pct":
        return f"{v:,.2f}%"
    if unit == "krw":
        return f"{v:,.1f}원"
    if unit == "usd":
        return f"${v:,.2f}"
    return f"{v:,.2f}"


def fmt_change(ch: dict, unit: str) -> str:
    """금리는 %p(절대차), 나머지는 %(비율)로 읽는 게 관행이다."""
    if not ch:
        return '<td class="na">–</td>'
    if unit == "pct":
        v, txt = ch["diff"], f'{ch["diff"]:+.2f}p'
    else:
        v, txt = ch["pct"], f'{ch["pct"]:+.2f}%'
    cls = "pos" if v > 0 else "neg" if v < 0 else ""
    return f'<td class="r {cls}">{txt}</td>'


def quote_table(cfg: dict, data: dict) -> str:
    blocks = []
    groups = list(cfg.get("quotes", []))
    if data.get("has_fred"):
        groups = groups + [{"group": "금리 파생(FRED)", "items": cfg.get("fred", [])}]

    for grp in groups:
        rows = ""
        for it in grp["items"]:
            q = data.get("quotes", {}).get(it["id"]) or data.get("fred", {}).get(it["id"])
            if not q:
                continue
            name = esc(it["name"])
            if it.get("key"):
                name = f"<b>{name}</b>"
            note = f'<span class="hint" title="{esc(it["note"])}">ⓘ</span>' if it.get("note") else ""
            cells = "".join(fmt_change(q.get(lbl), it["unit"]) for lbl, _ in
                            (("1D", 0), ("1W", 0), ("1M", 0), ("3M", 0), ("12M", 0)))
            rows += (f'<tr><th>{name}{note}</th>'
                     f'<td class="r v">{fmt_value(q.get("last"), it["unit"])}</td>{cells}</tr>')
        if rows:
            blocks.append(
                f'<p class="ctitle">{esc(grp["group"])}</p>'
                '<table><thead><tr><th></th><th class="r">현재</th>'
                '<th class="r">1D</th><th class="r">1W</th><th class="r">1M</th>'
                '<th class="r">3M</th><th class="r">12M</th></tr></thead>'
                f"<tbody>{rows}</tbody></table>")
    if not blocks:
        return '<p class="na">시세 데이터 없음 — 다음 수집부터 표시</p>'
    note = ("" if data.get("has_fred") else
            '<p class="note">FRED_API_KEY를 등록하면 <b>진짜 2년물·10년-2년 스프레드·'
            '기대인플레·실질금리</b>가 여기에 추가됩니다(무료 키).</p>')
    return "".join(blocks) + note


# ── 2. 달력 ────────────────────────────────────────────────────────────────
def chip(e: dict, rel: dict, cons: dict) -> str:
    """달력 칩 한 개 — **이름 + 직전치 두 줄**.

    전에는 이름만 찍고 설명을 title 툴팁에만 뒀다. 그래서 커서만 물음표로 바뀌고
    (`cursor:help`) 화면에는 정보가 하나도 없었다 — 툴팁은 모바일에서 아예 안 뜬다.
    이제 숫자를 본문에 쓰고, 누르면 그 지표의 해석 카드로 내려간다.
    """
    r = rel.get(e["id"]) or {}
    c = cons.get(e["id"]) or {}
    val = c.get("text") and f'컨센 {c["text"]}' or r.get("text") or ""
    sub = f'<span class="ev-v">{esc(val)}</span>' if val else ""
    est = '<i class="est" aria-label="발표일 추정">~</i>' if e.get("estimated") else ""
    href = f'#g-{esc(e["guide"])}' if e.get("guide") else "#cal-up"
    return (f'<a class="cal-ev {e["country"].lower()}" href="{href}">'
            f'<span class="ev-n"><i class="cc">{CC.get(e["country"], "")}</i>'
            f'{esc(e["name"])}{est}</span>{sub}</a>')


def month_grid(entries: list[dict], year: int, month: int, today: dt.date,
               rel: dict, cons: dict) -> str:
    ev = cr.month_events(entries, year, month)
    by_day: dict[int, list] = {}
    for e in ev:
        by_day.setdefault(e["date"].day, []).append(e)

    first = dt.date(year, month, 1)
    lead = (first.weekday() + 0) % 7            # 월요일 시작
    last = (dt.date(year + (month == 12), month % 12 + 1, 1) - dt.timedelta(days=1)).day

    cells = "".join('<div class="cal-cell empty"></div>' for _ in range(lead))
    for day in range(1, last + 1):
        d = dt.date(year, month, day)
        klass = "cal-cell"
        if d == today:
            klass += " today"
        if d.weekday() >= 5:
            klass += " wknd"
        chips = "".join(chip(e, rel, cons) for e in by_day.get(day, []))
        cells += f'<div class="{klass}"><span class="cal-d">{day}</span>{chips}</div>'

    head = "".join(f'<div class="cal-h">{w}</div>' for w in "월화수목금토일")
    return (f'<p class="ctitle">{year}년 {month}월</p>'
            f'<div class="cal">{head}{cells}</div>')


def upcoming(entries: list[dict], today: dt.date, rel: dict, cons: dict,
             days: int = 21) -> str:
    """다가오는 발표 표 — 달력 칸은 좁아 숫자가 잘린다. 읽을 수 있는 판을 따로 둔다.

    컨센서스는 무료 API 가 없어 `consensus.json` 에 있을 때만 채워진다 —
    비어 있으면 '–' 로 두고 지어내지 않는다.
    """
    end = today + dt.timedelta(days=days)
    ev = cr.month_events(entries, today.year, today.month)
    nxt_y, nxt_m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    ev += cr.month_events(entries, nxt_y, nxt_m)
    ev = [e for e in ev if today <= e["date"] <= end]
    if not ev:
        return '<p class="na">앞으로 3주 안에 예정된 발표가 없습니다.</p>'

    rows = ""
    for e in ev:
        r = rel.get(e["id"]) or {}
        c = cons.get(e["id"]) or {}
        d = e["date"]
        when = (f'{d.month}/{d.day}<span class="wd">({WD[d.weekday()]})</span>'
                + ('<i class="est">~</i>' if e.get("estimated") else ""))
        prev = (f'<b>{esc(r["text"])}</b><span class="pd"> · {esc(r["period"])}</span>'
                if r.get("text") else '<span class="na">–</span>')
        recent = (" → ".join(esc(x) for x in r.get("recent", [])) if r.get("recent")
                  else '<span class="na">–</span>')
        cs = esc(c["text"]) if c.get("text") else '<span class="na">–</span>'
        name = esc(e["name"])
        if e.get("guide"):
            name = f'<a href="#g-{esc(e["guide"])}">{name}</a>'
        tm = f'<span class="qtime">{esc(e["time"])}</span>' if e.get("time") else ""
        soon = "soon" if (d - today).days <= 3 else ""
        rows += (f'<tr class="{soon}"><td class="d">{when}</td>'
                 f'<td><i class="cc">{CC.get(e["country"], "")}</i>{name}{tm}</td>'
                 f'<td class="r">{prev}</td><td class="r">{cs}</td>'
                 f'<td class="r trend">{recent}</td></tr>')
    return ('<table class="up"><thead><tr><th>날짜</th><th>지표</th>'
            '<th class="r">직전 발표</th><th class="r">컨센서스</th>'
            '<th class="r">최근 3회</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def calendar_block(cfg: dict, today: dt.date, data: dict) -> str:
    entries = cfg.get("calendar", [])
    rel = data.get("releases") or {}
    cons = rl.load_consensus()
    nxt_y, nxt_m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)

    fixed = cr.load_fixed()
    missing = [e["name"] for e in entries if e.get("fixed") and not fixed.get(e["id"])]
    warn = ""
    if missing:
        warn = ('<p class="note warn">📌 <b>' + esc(" · ".join(missing)) +
                '</b> 은 기관이 공표하는 확정일이라 <b>추측해서 넣지 않았습니다</b>. '
                '공식 일정을 받아오면 달력에 자동으로 채워집니다.</p>')

    no_rel = [e["name"] for e in entries
              if not (e.get("release") or {}).get("series") and not e.get("fixed")]
    gap = ""
    if no_rel:
        gap = ('<p class="note">직전치 소스가 없는 지표: <b>' + esc(" · ".join(no_rel)) +
               '</b> — ISM 은 2022년 FRED 재배포가 중단돼 무료 경로가 없고, 한국 지표 일부는 '
               'ECOS 키가 있어야 받습니다. 숫자를 지어내지 않고 빈칸으로 둡니다.</p>')
    cons_note = ('<p class="note">컨센서스는 무료 API 가 없어 '
                 f'<b>{"등록된 값만" if cons else "아직 비어"}</b> 표시됩니다'
                 f'{f" (현재 {len(cons)}건)" if cons else ""}.</p>')

    return ('<p class="ctitle" id="cal-up">다가오는 발표 (3주)</p>'
            + upcoming(entries, today, rel, cons)
            + '<p class="note"><b>직전 발표</b>는 가장 최근에 실제로 나온 값입니다 — '
              '다음 발표 때 이 숫자와 비교해서 보면 됩니다. '
              '<b>최근 3회</b>는 흐름(가속·둔화)을 보기 위한 것입니다.</p>'
            + cons_note + gap
            + month_grid(entries, today.year, today.month, today, rel, cons)
            + month_grid(entries, nxt_y, nxt_m, today, rel, cons)
            + '<p class="note"><b>~</b> 가 붙은 날짜는 "매월 몇 번째 무슨 요일" 규칙으로 '
              '뽑은 <b>추정일</b>입니다 — 기관 공휴일·변경은 반영되지 않습니다. '
              '~ 없는 날짜는 기관이 공표한 확정일입니다. 칩을 누르면 해석 카드로 갑니다.</p>'
            + warn)


# ── 3. 해석 카드 ───────────────────────────────────────────────────────────
def indicator_cards(guide: dict) -> str:
    cards = []
    for gid, g in (guide.get("indicators") or {}).items():
        bands = "".join(
            f'<li class="band {TONE.get(b.get("tone"), ("", "•"))[0]}">'
            f'<span class="bmark">{TONE.get(b.get("tone"), ("", "•"))[1]}</span>'
            f'<b>{esc(b["band"])}</b><span>{esc(b["mean"])}</span></li>'
            for b in g.get("read", []))
        links = " · ".join(
            f'<a href="{esc(u)}" target="_blank" rel="noopener">{esc(t)}</a>'
            for t, u in g.get("links", []))
        if g.get("youtube"):
            q = esc(g["youtube"]).replace(" ", "+")
            links += (" · " if links else "") + (
                f'<a href="https://www.youtube.com/results?search_query={q}" '
                f'target="_blank" rel="noopener">▶ 영상 찾아보기</a>')
        cards.append(f"""
<details class="gcard" id="g-{esc(gid)}">
  <summary><b>{esc(g["name"])}</b>
    <span class="meta">{esc(g.get("agency", ""))} · {esc(g.get("freq", ""))}</span></summary>
  <p class="what">{esc(g.get("what", "")).replace(chr(10), "<br>")}</p>
  <p class="watch">👁 <b>볼 것</b> — {esc(g.get("watch", ""))}</p>
  <ul class="bands">{bands}</ul>
  <p class="mkt">📈 <b>시장 반응</b><br>{esc(g.get("market", "")).replace(chr(10), "<br>")}</p>
  <p class="kr">🇰🇷 <b>한국엔</b> — {esc(g.get("korea", ""))}</p>
  <p class="links">{links}</p>
</details>""")
    return "".join(cards)


# ── 4. 기초 ────────────────────────────────────────────────────────────────
def basics_block(guide: dict) -> str:
    out = []
    for b in guide.get("basics", []):
        yt = ""
        if b.get("youtube"):
            q = esc(b["youtube"]).replace(" ", "+")
            yt = (f'<a class="yt" href="https://www.youtube.com/results?search_query={q}" '
                  f'target="_blank" rel="noopener">▶ 영상 찾아보기</a>')
        out.append(f'<details class="bcard"><summary><b>{esc(b["title"])}</b></summary>'
                   f'<p>{esc(b.get("body", "")).replace(chr(10), "<br>")}</p>{yt}</details>')
    return "".join(out)


def build() -> Path:
    cfg = yaml.safe_load((HERE / "config.yml").read_text(encoding="utf-8"))
    guide = yaml.safe_load((HERE / "guide.yml").read_text(encoding="utf-8"))
    data = latest_payload()
    today = dt.datetime.now(KST).date()
    gen = data.get("generated_at", "")
    stale = ""
    if data.get("date") and data["date"] != today.isoformat():
        stale = (f'<span class="stale">· 최신 수집 {esc(data["date"])} '
                 f'(오늘 수집 전)</span>')

    html_out = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>매크로 데스크</title>
<style>
:root{{--bg:#fff;--fg:#1c2430;--muted:#6b7684;--line:#e5e8ec;--card:#f7f8fa;
--pos:#d64545;--neg:#3b6fd4;--accent:#2f6f4f;--warnbg:#fff8e6;--warnline:#e8c87a}}
@media(prefers-color-scheme:dark){{:root{{--bg:#14181f;--fg:#e6e9ee;--muted:#8b93a1;
--line:#2a313c;--card:#1b212b;--accent:#8fc7a5;--warnbg:#2b2718;--warnline:#5c4f27}}}}
*{{box-sizing:border-box}}
body{{margin:0;padding:18px 16px 48px;background:var(--bg);color:var(--fg);
font:14px/1.6 -apple-system,"Malgun Gothic","Apple SD Gothic Neo",sans-serif}}
.wrap{{max-width:820px;margin:0 auto}}
h1{{font-size:19px;margin:0 0 2px}} h2{{font-size:15px;margin:28px 0 8px}}
.sub{{color:var(--muted);font-size:12.5px;margin:0 0 16px}}
.stale{{color:var(--pos)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:12px 14px;margin:0 0 10px}}
.ctitle{{font-weight:700;font-size:13px;margin:4px 0 6px;color:var(--muted)}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin:0 0 14px}}
th,td{{padding:5px 6px;border-bottom:1px solid var(--line);text-align:left}}
thead th{{color:var(--muted);font-weight:600;font-size:11.5px;border-bottom:1.5px solid var(--line)}}
td.r,th.r{{text-align:right;font-variant-numeric:tabular-nums}}
td.v{{font-weight:700}}
.pos{{color:var(--pos)}} .neg{{color:var(--neg)}} .na{{color:var(--muted)}}
.hint{{color:var(--muted);font-size:11px;margin-left:3px;cursor:help}}
.note{{color:var(--muted);font-size:12px;margin:6px 0 0}}
.note.warn{{background:var(--warnbg);border:1px solid var(--warnline);
border-radius:8px;padding:8px 10px;color:var(--fg)}}
/* 달력 */
.cal{{display:grid;grid-template-columns:repeat(7,1fr);gap:3px;margin:0 0 14px}}
.cal-h{{text-align:center;font-size:11px;color:var(--muted);padding:2px 0}}
.cal-cell{{min-height:62px;border:1px solid var(--line);border-radius:6px;padding:3px 4px;
background:var(--bg)}}
.cal-cell.empty{{border:none;background:none}}
.cal-cell.wknd{{background:var(--card)}}
.cal-cell.today{{border-color:var(--accent);border-width:2px}}
.cal-d{{font-size:11px;color:var(--muted)}}
.cal-ev{{display:block;font-size:10px;line-height:1.3;margin-top:2px;padding:2px 3px;
border-radius:3px;background:rgba(59,111,212,.12);text-decoration:none;color:inherit;
overflow:hidden}}
.cal-ev:hover{{background:rgba(59,111,212,.26)}}
.cal-ev.kr{{background:rgba(214,69,69,.12)}}
.cal-ev.kr:hover{{background:rgba(214,69,69,.26)}}
.ev-n{{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.ev-v{{display:block;font-size:9.5px;color:var(--muted);font-variant-numeric:tabular-nums;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.cc{{display:inline-block;font-style:normal;font-size:8.5px;font-weight:700;letter-spacing:.3px;
border:1px solid var(--line);border-radius:3px;padding:0 2px;margin-right:3px;
color:var(--muted);vertical-align:1px}}
.est{{font-style:normal;color:var(--muted);margin-left:2px}}
/* 다가오는 발표 */
table.up td{{font-size:12.5px;vertical-align:top}}
table.up td.d{{white-space:nowrap;font-weight:700}}
table.up .wd,table.up .pd{{color:var(--muted);font-weight:400;font-size:11px}}
table.up .qtime{{display:block;color:var(--muted);font-size:10.5px}}
table.up tr.soon td{{background:var(--warnbg)}}
table.up .trend{{color:var(--muted);font-size:11.5px;white-space:nowrap}}
/* 해석 카드 */
.gcard,.bcard{{border:1px solid var(--line);border-radius:10px;background:var(--card);
padding:10px 12px;margin:0 0 8px}}
summary{{cursor:pointer;font-size:14px}}
summary .meta{{color:var(--muted);font-size:11.5px;font-weight:400;margin-left:6px}}
.what{{margin:8px 0}} .watch{{margin:6px 0;font-size:13px}}
.bands{{list-style:none;padding:0;margin:8px 0}}
.band{{display:grid;grid-template-columns:18px 170px 1fr;gap:6px;align-items:start;
padding:4px 0;border-top:1px dashed var(--line);font-size:12.5px}}
.band .bmark{{text-align:center}}
.mkt,.kr{{font-size:12.5px;margin:8px 0 0}}
.links{{margin:8px 0 0;font-size:12px}}
a{{color:inherit}} .yt{{font-size:12px}}
</style></head><body><div class="wrap">

<h1>📊 매크로 데스크</h1>
<p class="sub">금리·채권·환율과 월·분기 지표를 한 장에. 숫자 옆에 <b>“얼마면 무슨 뜻인지”</b>를 같이 둔다.<br>
🕘 매일 저녁 9시 갱신{f' · 실제 갱신 <b>{esc(gen)}</b>' if gen else ''} {stale}</p>

<h2>📈 지금 숫자</h2>
<div class="card">{quote_table(cfg, data)}</div>

<h2>🗓 발표 일정</h2>
<div class="card">{calendar_block(cfg, today, data)}</div>

<h2>🧭 지표 해석 — 얼마면 무슨 뜻인가</h2>
<p class="note">제목을 누르면 펼쳐집니다. 밴드는 <b>대략의 기준</b>이지 매매 신호가 아닙니다.</p>
{indicator_cards(guide)}

<h2>📚 기초 — 이것부터</h2>
{basics_block(guide)}

<p class="note">영상 링크는 특정 영상이 아니라 <b>검색 결과</b>로 겁니다 — 영상은 내려가도 검색은 남습니다.</p>
</div></body></html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html_out, encoding="utf-8")
    print(f"리포트 생성 → {OUT} ({len(html_out)//1024} KB)")
    return OUT


if __name__ == "__main__":
    build()
