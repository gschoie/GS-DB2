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


def rich(v) -> str:
    """guide.yml 본문 → HTML. `**굵게**` 와 줄바꿈만 살린다.

    guide.yml 은 사람이 쓰는 글이라 강조를 별표로 적어 왔는데(38군데) 화면은
    esc 만 하고 그대로 찍어서 **헤드라인** 처럼 별표가 보였다. 별표를 지우는 게
    아니라 굵게로 바꾼다 — 글쓴이가 강조하려던 자리가 맞다.
    **esc 를 먼저** 하므로 아래 치환이 만드는 <b> 외의 태그는 들어올 수 없다.
    """
    out = esc(v)
    while "**" in out:
        a = out.index("**")
        b = out.find("**", a + 2)
        if b < 0:                       # 짝이 안 맞는 별표는 건드리지 않는다
            break
        out = out[:a] + "<b>" + out[a + 2:b] + "</b>" + out[b + 2:]
    return out.replace(chr(10), "<br>")


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


def all_quote_items(cfg: dict, data: dict) -> list[tuple[dict, dict]]:
    """(설정 항목, 수집값) 쌍 — 시세표와 차트 데이터가 **같은 목록**을 보게 한다."""
    groups = list(cfg.get("quotes", []))
    if data.get("has_fred"):
        groups = groups + [{"group": "금리 파생(FRED)", "items": cfg.get("fred", [])}]
    out = []
    for grp in groups:
        for it in grp["items"]:
            q = (data.get("quotes", {}).get(it["id"])
                 or data.get("fred", {}).get(it["id"]))
            if q:
                out.append((it, q))
    return out


def series_json(cfg: dict, data: dict) -> str:
    """차트용 데이터를 페이지에 **박아 넣는다**(런타임 fetch 없음).

    지표당 값 252개 + 날짜 문자열 1.5KB 정도라 페이지가 수십 KB 늘지만,
    배포 경로·CORS·캐시를 신경 쓸 일이 없고 iframe 안에서도 그냥 돈다.
    """
    out = {}
    for it, q in all_quote_items(cfg, data):
        s = q.get("series") or {}
        if s.get("v") and s.get("d"):
            out[it["id"]] = {"n": it["name"], "u": it["unit"],
                             "v": s["v"], "d": s["d"]}
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


def quote_table(cfg: dict, data: dict) -> str:
    blocks = []
    groups = list(cfg.get("quotes", []))
    if data.get("has_fred"):
        groups = groups + [{"group": "금리 파생(FRED)", "items": cfg.get("fred", [])}]

    for grp in groups:
        rows, notes = "", []
        for it in grp["items"]:
            q = data.get("quotes", {}).get(it["id"]) or data.get("fred", {}).get(it["id"])
            if not q:
                continue
            name = esc(it["name"])
            if it.get("key"):
                name = f"<b>{name}</b>"
            mark = ""
            if it.get("note"):
                # **툴팁만으로 두지 않는다** — 모바일에선 안 뜨고, "2년물이 실은 5년물"
                # 같은 주의는 안 보이면 그냥 틀린 표가 된다. 표 밑에 글로 적는다.
                notes.append(f'<b>{esc(it["name"])}</b> — {esc(it["note"])}')
                mark = f'<span class="hint">*{len(notes)}</span>'
            cells = "".join(fmt_change(q.get(lbl), it["unit"]) for lbl, _ in
                            (("1D", 0), ("1W", 0), ("1M", 0), ("3M", 0), ("12M", 0)))
            # 시계열이 있는 줄만 누를 수 있게 한다 — 수집이 한 번 더 돌기 전에는
            # series 가 없으므로, 눌러도 아무 일 없는 줄을 만들지 않는다.
            if (q.get("series") or {}).get("v"):
                tr = (f'<tr class="qrow" data-q="{esc(it["id"])}" tabindex="0" '
                      f'role="button" aria-expanded="false">')
                name += '<span class="spark">▸</span>'
            else:
                tr = "<tr>"
            rows += (f'{tr}<th>{name}{mark}</th>'
                     f'<td class="r v">{fmt_value(q.get("last"), it["unit"])}</td>{cells}</tr>')
        if rows:
            foot = "".join(f'<p class="fnote">*{i + 1} {n}</p>'
                           for i, n in enumerate(notes))
            blocks.append(
                f'<p class="ctitle">{esc(grp["group"])}</p>'
                '<table><thead><tr><th></th><th class="r">현재</th>'
                '<th class="r">1D</th><th class="r">1W</th><th class="r">1M</th>'
                '<th class="r">3M</th><th class="r">12M</th></tr></thead>'
                f"<tbody>{rows}</tbody></table>{foot}")
    if not blocks:
        return '<p class="na">시세 데이터 없음 — 다음 수집부터 표시</p>'
    # FRED 키 경로(api.stlouisfed.org)는 러너에서 열려 있음을 실측으로 확인했다 —
    # 막힌 건 그래프·CSV 호스트(fred.stlouisfed.org)뿐이다.
    note = ("" if data.get("has_fred") else
            '<p class="note">FRED_API_KEY(무료)를 등록하면 <b>진짜 2년물·10년-2년 스프레드·'
            '기대인플레·실질금리</b>가 여기에 추가되고, 아래 달력의 '
            '<b>소매판매·PCE·GDP·정책금리·한국 지표 직전치</b>도 함께 채워집니다.</p>')
    return "".join(blocks) + note


# ── 2. 달력 ────────────────────────────────────────────────────────────────
def _short_period(period: str | None) -> str:
    """'2026년 8월' → '8월' · '2026 2분기' → '2분기'. 칩 칸이 좁아 연도를 뗀다.

    직전 발표분은 거의 늘 올해라 연도가 자리만 차지한다. 모르면 빈 문자열 —
    '직전' 뒤에 괄호만 덜렁 남기지 않는다.
    """
    if not period:
        return ""
    p = period.strip()
    if len(p) == 10 and p[4] == "-" and p[7] == "-":   # 일별 계열의 ISO 날짜
        return f"{int(p[5:7])}/{int(p[8:10])}"
    return p.split("년")[-1].strip() or p


def chip(e: dict, rel: dict, cons: dict) -> str:
    """달력 칩 한 개 — **이름 + 직전치 두 줄**.

    전에는 이름만 찍고 설명을 title 툴팁에만 뒀다. 그래서 커서만 물음표로 바뀌고
    (`cursor:help`) 화면에는 정보가 하나도 없었다 — 툴팁은 모바일에서 아예 안 뜬다.
    이제 숫자를 본문에 쓰고, 누르면 그 지표의 해석 카드로 내려간다.
    """
    r = rel.get(e["id"]) or {}
    c = cons.get(e["id"]) or {}
    # **둘은 방향이 반대인 숫자다** — 컨센은 '이번에 이렇게 나올 것'(앞), 직전치는
    # '지난번에 이렇게 나왔다'(뒤). 전에는 직전치를 아무 말 없이 찍어서, 라벨 차이가
    # '컨센' 한 단어뿐이었다. 그래서 PPI 칩의 '전년 +5.4%' 가 이번 예상인지
    # 지난 발표인지 분간이 안 됐다 → 직전치에는 **몇 월분인지까지** 붙인다.
    if c.get("text"):                              # 앞을 보는 숫자가 있으면 그게 먼저
        val = f'컨센 {c["text"]}'
    elif r.get("text"):
        val = f'직전 {_short_period(r.get("period"))} {r["text"]}'.replace("  ", " ")
    else:
        val = ""
    sub = f'<span class="ev-v">{esc(val)}</span>' if val else ""
    est = '<i class="est" aria-label="발표일 추정">~</i>' if e.get("estimated") else ""
    body = (f'<span class="ev-n"><i class="cc">{CC.get(e["country"], "")}</i>'
            f'{esc(e["name"])}{est}</span>{sub}')
    if not e.get("guide"):              # 누를 데가 없으면 링크로 만들지 않는다
        return f'<span class="cal-ev {e["country"].lower()} flat">{body}</span>'
    return (f'<a class="cal-ev {e["country"].lower()}" href="#g-{esc(e["guide"])}">'
            f'{body}</a>')


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
    if fixed.get("_tentative"):
        warn += ('<p class="note">출처가 한 곳뿐이어서 <b>아직 확인이 필요한 날짜</b>는 '
                 '확정으로 표시하지 않고 <b>~</b> 로 둡니다 '
                 f'(현재 {len(fixed["_tentative"])}건 — 금통위).</p>')

    # 직전치가 비어 있는 이유를 **종류별로** 적는다 — '없다'와 '키가 없어 못 받는다'는
    # 사용자가 할 수 있는 일이 다르다(앞은 포기, 뒤는 키 등록으로 채워진다).
    none_src = [e["name"] for e in entries
                if not (e.get("release") or {}).get("series")]
    need_key = [e["name"] for e in entries
                if (e.get("release") or {}).get("src") == "fred" and e["id"] not in rel]
    gap = ""
    if none_src:
        gap += ('<p class="note">직전치 소스가 아예 없는 지표: <b>'
                + esc(" · ".join(none_src)) +
                '</b> — ISM 은 2022년에 재배포가 막혀 유료 외엔 경로가 없고, '
                '한국 수출입·금통위는 기관 발표를 직접 받아야 합니다. '
                '숫자를 지어내지 않고 빈칸으로 둡니다.</p>')
    if need_key:
        gap += ('<p class="note warn">🔑 <b>' + esc(" · ".join(need_key)) +
                '</b> 의 직전치는 <b>FRED 무료 키</b>(<code>FRED_API_KEY</code>)를 '
                '등록하면 자동으로 채워집니다. 물가·고용(CPI·PPI·고용보고서)은 '
                'BLS 공개 API 라 키 없이 이미 나옵니다.</p>')
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
# 약어는 **쓰는 자리에서 풀어준다** — 매크로를 처음 보는 사람이 읽는 페이지다.
# 본문에 실제로 나온 약어만 적는다(안 쓴 약어까지 늘어놓으면 그게 소음이다).
ABBR = [("YoY", "전년동월비 — 1년 전 같은 달 대비"),
        ("MoM", "전월비 — 바로 앞 달 대비"),
        ("QoQ", "전분기비 — 바로 앞 분기 대비")]


def legend(text: str) -> str:
    used = [f"<b>{k}</b> {v}" for k, v in ABBR if k in text]
    if not used:
        return ""
    # 기간 설명은 월·분기에 다 맞게 일반형으로 — '8월분의 발표는 9월' 같은 월간
    # 예시를 분기 지표(GDP) 카드에 붙이면 그 자리에서 틀린 말이 된다.
    return ('<p class="numtip">' + " · ".join(used)
            + ' · 오른쪽 기간은 발표일이 아니라 <b>대상 기간</b>입니다.</p>')


def guide_numbers(cfg: dict, rel: dict, cons: dict) -> dict:
    """guide id → 그 지표의 실제 숫자 블록.

    밴드만 있고 숫자가 없으면 "근원 3.5% 이상이면…" 을 읽고도 **지금 얼마인지**를
    모른다. 달력 칩에서 눌러 내려온 자리이므로 직전 발표(몇 월분인지 포함)와
    컨센을 **나란히, 각각 라벨을 달아** 둔다 — 둘은 방향이 반대인 숫자다.

    config 의 `guide:` 는 여러 지표가 한 카드를 가리킬 수 있어(ISM 제조업·서비스업)
    항목 이름을 같이 적는다. 없는 값은 줄을 통째로 빼고 '–' 로 채우지 않는다.
    """
    out: dict[str, list[str]] = {}
    for e in cfg.get("calendar", []):
        gid = e.get("guide")
        if not gid:
            continue
        r = rel.get(e["id"]) or {}
        c = cons.get(e["id"]) or {}
        if not (r.get("text") or c.get("text")):
            continue
        rows = ""
        if c.get("text"):
            when = esc(c["for"]) if c.get("for") else "다음 발표"
            rows += (f'<tr><th class="k cons">컨센서스</th><td class="v">{esc(c["text"])}</td>'
                     f'<td class="w">{when}</td></tr>')
        if r.get("text"):
            rows += (f'<tr><th class="k prev">직전 발표</th><td class="v">{esc(r["text"])}</td>'
                     f'<td class="w">{esc(r.get("period", ""))}</td></tr>')
            if r.get("recent"):
                trail = " → ".join(esc(x) for x in r["recent"])
                # unit_note 가 빈 지표가 많다 — 그대로 붙이면 '·' 만 덜렁 남는다
                note = (f'<span class="w"> · {esc(r["unit_note"])}</span>'
                        if r.get("unit_note") else "")
                rows += (f'<tr><th class="k">최근 3회</th>'
                         f'<td class="v trend" colspan="2">{trail}{note}</td></tr>')
        label = (f'<p class="numname">{esc(e["name"])}</p>'
                 if len([x for x in cfg.get("calendar", []) if x.get("guide") == gid]) > 1
                 else "")
        out.setdefault(gid, []).append(
            f'{label}<table class="nums">{rows}</table>'
            + legend((r.get("text") or "") + (c.get("text") or "")))
    return out


def indicator_cards(guide: dict, nums: dict | None = None) -> str:
    nums = nums or {}
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
  {"".join(nums.get(gid, []))}
  <p class="what">{rich(g.get("what", ""))}</p>
  <p class="watch">👁 <b>볼 것</b> — {esc(g.get("watch", ""))}</p>
  <ul class="bands">{bands}</ul>
  <p class="mkt">📈 <b>시장 반응</b><br>{rich(g.get("market", ""))}</p>
  <p class="kr"><i class="cc">KR</i><b>한국엔</b> — {esc(g.get("korea", ""))}</p>
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
                   f'<p>{rich(b.get("body", ""))}</p>{yt}</details>')
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
h1{{font-size:19px;margin:0 0 2px}} h2{{font-size:15px;margin:24px 0 8px}}
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
.hint{{color:var(--muted);font-size:10px;margin-left:2px;vertical-align:2px}}
.fnote{{color:var(--muted);font-size:11.5px;margin:-8px 0 12px}}
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
.cal-ev.flat:hover{{background:rgba(59,111,212,.12)}}
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
/* 섹션 접기 */
details.sec{{margin:0 0 4px}}
details.sec>summary{{list-style:none;cursor:pointer;display:flex;align-items:center;gap:6px;
padding:4px 0;border-bottom:1px solid var(--line)}}
details.sec>summary::-webkit-details-marker{{display:none}}
/* 삼각형은 CSS 이스케이프(\\25BE) 대신 글자로 넣는다 — 스타일이 f-string 안이라
   파이썬이 \\25 를 8진 이스케이프로 먹고 화면에 "BE" 두 글자가 찍힌다(실측).
   글자는 ▾(U+25BE)가 아니라 ▼(U+25BC)다 — 25BE 는 이름 그대로 SMALL triangle 로
   11px 회색과 겹쳐 "너무 작다"는 소리를 들었다. */
details.sec>summary::before{{content:"▼";color:var(--muted);font-size:15px;width:17px;
text-align:center;flex:none;transition:transform .12s}}
details.sec:not([open])>summary::before{{transform:rotate(-90deg)}}
details.sec>summary:hover::before{{color:var(--accent)}}
details.sec>summary h2{{margin:0;display:inline}}
details.sec>summary:hover h2{{color:var(--accent)}}
details.sec[open]>summary{{margin-bottom:8px}}
.gcard,.bcard{{border:1px solid var(--line);border-radius:10px;background:var(--card);
padding:10px 12px;margin:0 0 8px}}
summary{{cursor:pointer;font-size:14px}}
/* 카드(해석·기초)는 브라우저 기본 마커를 쓰고 있었다 — 기본 마커는 CSS 로 크기를
   못 키워서 섹션만 키우면 둘이 따로 보인다. 같은 글자 삼각형으로 통일한다. */
.gcard>summary,.bcard>summary{{list-style:none;display:flex;align-items:center;gap:7px}}
.gcard>summary::-webkit-details-marker,
.bcard>summary::-webkit-details-marker{{display:none}}
.gcard>summary::before,.bcard>summary::before{{content:"▼";color:var(--muted);
font-size:13px;width:15px;text-align:center;flex:none;transition:transform .12s}}
.gcard:not([open])>summary::before,
.bcard:not([open])>summary::before{{transform:rotate(-90deg)}}
.gcard>summary:hover::before,.bcard>summary:hover::before{{color:var(--accent)}}
summary .meta{{color:var(--muted);font-size:11.5px;font-weight:400;margin-left:6px}}
/* 시세표에서 누를 수 있는 줄 + 그 밑에 펼쳐지는 시계열 */
tr.qrow{{cursor:pointer}}
tr.qrow:hover th,tr.qrow:focus th{{color:var(--accent)}}
tr.qrow .spark{{color:var(--muted);font-size:10px;margin-left:5px;
display:inline-block;transition:transform .12s}}
tr.qrow[aria-expanded="true"] .spark{{transform:rotate(90deg);color:var(--accent)}}
tr.chartrow>td{{padding:0 0 10px}}
.chart{{border:1px solid var(--line);border-radius:10px;background:var(--card);padding:8px 10px}}
.chart .chead{{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px;margin-bottom:4px}}
.chart .ctit{{font-weight:600;font-size:13px}}
.chart .rng{{margin-left:auto;display:flex;gap:4px}}
.chart .rng button{{font:inherit;font-size:11.5px;padding:2px 8px;cursor:pointer;
border:1px solid var(--line);border-radius:999px;background:transparent;color:var(--muted)}}
.chart .rng button[aria-pressed="true"]{{color:var(--accent);border-color:var(--accent)}}
.chart svg{{width:100%;height:auto;display:block}}
.chart .gl{{stroke:var(--line);stroke-dasharray:3 3}}
.chart .ln{{fill:none;stroke:var(--accent);stroke-width:1.6}}
.chart .ax{{fill:var(--muted);font-size:10px}}
.chart .cfoot{{color:var(--muted);font-size:11px;margin:4px 0 0}}

/* 해석 카드 맨 위 숫자판 — 컨센(앞을 보는 숫자)과 직전 발표(뒤를 보는 숫자)를
   라벨을 달아 나란히. 색으로도 가른다: 컨센은 강조, 직전은 차분하게. */
table.nums{{width:100%;border-collapse:collapse;margin:2px 0 10px;font-size:12.5px}}
table.nums th,table.nums td{{padding:4px 6px;border-bottom:1px dashed var(--line);
text-align:left;vertical-align:top}}
table.nums th.k{{width:74px;font-weight:600;color:var(--muted);white-space:nowrap}}
table.nums th.k.cons{{color:var(--accent)}}
table.nums td.v{{font-weight:600}}
table.nums td.w,table.nums span.w{{color:var(--muted);font-weight:400;font-size:11.5px;
white-space:nowrap}}
table.nums td.trend{{font-weight:400;font-family:Georgia,serif}}
.numname{{margin:6px 0 0;font-size:12px;font-weight:600;color:var(--muted)}}
.numtip{{margin:-6px 0 10px;font-size:11.5px;color:var(--muted)}}
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

<details class="sec" id="s-now" open>
<summary><h2>📈 지금 숫자</h2></summary>
<div class="card">{quote_table(cfg, data)}</div>
</details>

<details class="sec" id="s-cal" open>
<summary><h2>🗓 발표 일정</h2></summary>
<div class="card">{calendar_block(cfg, today, data)}</div>
</details>

<details class="sec" id="s-read" open>
<summary><h2>🧭 지표 해석 — 얼마면 무슨 뜻인가</h2></summary>
<p class="note">제목을 누르면 펼쳐집니다. 밴드는 <b>대략의 기준</b>이지 매매 신호가 아닙니다.</p>
{indicator_cards(guide, guide_numbers(cfg, data.get("releases") or {}, rl.load_consensus()))}
</details>

<details class="sec" id="s-basic" open>
<summary><h2>📚 기초 — 이것부터</h2></summary>
{basics_block(guide)}
</details>

<p class="note">영상 링크는 특정 영상이 아니라 <b>검색 결과</b>로 겁니다 — 영상은 내려가도 검색은 남습니다.</p>
</div>
<script>
// 섹션 접은 상태를 브라우저에 기억해 둔다. 페이지는 매일 새로 구워지고 iframe 이 다시
// 로드되므로 기억하지 않으면 접어도 다음에 또 펼쳐져 있다. 저장이 막힌 환경(사생활 모드·
// 사이트 데이터 차단)에서는 accessor 가 던지므로 전부 try 로 감싼다 — 기억만 안 될 뿐
// 화면은 그대로 동작해야 한다.
(function(){{
  var KEY='macroSections';
  var state={{}};
  try{{ state=JSON.parse(localStorage.getItem(KEY)||'{{}}')||{{}}; }}catch(e){{}}
  document.querySelectorAll('details.sec').forEach(function(d){{
    if(state[d.id]===false) d.open=false;
    else if(state[d.id]===true) d.open=true;
    d.addEventListener('toggle',function(){{
      state[d.id]=d.open;
      try{{ localStorage.setItem(KEY,JSON.stringify(state)); }}catch(e){{}}
    }});
  }});
}})();

// 달력 칩·발표표의 지표명을 누르면 그 지표의 해석 카드로 내려간다. 그런데 카드도
// 섹션도 <details> 라서 **접혀 있으면 앵커로 가도 아무것도 안 보인다** — 링크를 눌렀는데
// 아무 일도 안 일어난 것처럼 느껴진다. 눌린 대상과 그 조상 <details> 를 전부 펼친다.
// 클릭 경로에서는 preventDefault 를 하지 않는다 — 펼치기만 해두면 브라우저가 이벤트
// 처리 뒤에 앵커로 점프하므로 iframe 안에서도 기본 동작이 그대로 맞는다.
// 주소에 해시를 달고 들어온 경우는 브라우저가 **펼치기 전에** 이미 점프를 끝냈으므로
// 그때만 직접 스크롤한다.
(function(){{
  function expand(id){{
    var el=document.getElementById(id);
    if(!el) return null;
    for(var n=el;n;n=n.parentElement){{ if(n.tagName==='DETAILS') n.open=true; }}
    return el;
  }}
  document.querySelectorAll('a[href^="#g-"]').forEach(function(a){{
    a.addEventListener('click',function(){{ expand(a.getAttribute('href').slice(1)); }});
  }});
  function jump(){{
    if(location.hash.indexOf('#g-')!==0) return;
    var el=expand(location.hash.slice(1));
    if(el) try{{ el.scrollIntoView({{block:'start'}}); }}catch(e){{}}
  }}
  jump();
  window.addEventListener('hashchange',jump);
}})();

// 시세표의 줄을 누르면 그 자리 바로 밑에 시계열을 편다. 데이터는 페이지에 박혀
// 있어(SERIES) 네트워크를 타지 않는다. x축은 **거래일 등간격** — 휴장일을 빈칸으로
// 두지 않는 흔한 방식이라 라벨에 실제 날짜를 찍어 그 점을 분명히 한다.
// 날짜는 YYMMDD 고정폭을 이어 붙인 문자열이라 i 번째는 slice(i*6,i*6+6).
(function(){{
var SERIES={series_json(cfg, data)};
var RANGES=[['1M',21],['3M',63],['12M',252]];
function fmtv(v,u){{
  if(u==='pct') return v.toFixed(2)+'%';
  if(u==='krw') return v.toLocaleString(undefined,{{minimumFractionDigits:1,maximumFractionDigits:1}})+'원';
  if(u==='usd') return '$'+v.toLocaleString(undefined,{{minimumFractionDigits:2,maximumFractionDigits:2}});
  return v.toLocaleString(undefined,{{minimumFractionDigits:2,maximumFractionDigits:2}});
}}
function fmtd(s){{ return s ? s.slice(0,2)+'/'+s.slice(2,4)+'/'+s.slice(4,6) : ''; }}
function draw(box,id,n){{
  var s=SERIES[id]; if(!s) return;
  var v=s.v.slice(-n), off=s.v.length-v.length;
  var date=function(i){{ return s.d.slice((off+i)*6,(off+i)*6+6); }};
  var lo=Math.min.apply(null,v), hi=Math.max.apply(null,v);
  // 전 구간이 같은 값이면 0으로 나눈다 — 가운데 수평선으로 그린다
  var span=(hi-lo)||1, L=52, R=812, T=12, B=128;
  var x=function(i){{ return v.length<2 ? (L+R)/2 : L+i*(R-L)/(v.length-1); }};
  var y=function(d){{ return (hi===lo) ? (T+B)/2 : B-(d-lo)*(B-T)/span; }};
  var pts=v.map(function(d,i){{ return x(i).toFixed(1)+','+y(d).toFixed(1); }}).join(' ');
  var g='';
  [hi,lo].forEach(function(d){{
    g+='<line class="gl" x1="'+L+'" y1="'+y(d).toFixed(1)+'" x2="'+R+'" y2="'+y(d).toFixed(1)+'"/>'
      +'<text class="ax" x="'+(L-6)+'" y="'+(y(d)+3.5).toFixed(1)+'" text-anchor="end">'+fmtv(d,s.u)+'</text>';
  }});
  var mid=Math.floor((v.length-1)/2);
  [[0,'start'],[mid,'middle'],[v.length-1,'end']].forEach(function(p){{
    if(p[0]<0) return;
    g+='<text class="ax" x="'+x(p[0]).toFixed(1)+'" y="144" text-anchor="'+p[1]+'">'+fmtd(date(p[0]))+'</text>';
  }});
  var last=v[v.length-1];
  box.querySelector('.cbody').innerHTML=
    '<svg viewBox="0 0 820 150" role="img" aria-label="'+s.n+' 시계열">'+g
    +'<polyline class="ln" points="'+pts+'"/>'
    +'<circle cx="'+x(v.length-1).toFixed(1)+'" cy="'+y(last).toFixed(1)+'" r="3" fill="var(--accent)"/>'
    +'</svg>';
  box.querySelector('.cfoot').textContent=
    '거래일 '+v.length+'개 · '+fmtd(date(0))+' → '+fmtd(date(v.length-1))
    +' · 최저 '+fmtv(lo,s.u)+' · 최고 '+fmtv(hi,s.u)
    +' · x축은 거래일 등간격(휴장일은 건너뜁니다)';
}}
function panel(id){{
  var s=SERIES[id];
  var td=document.createElement('td'); td.colSpan=7;
  var box=document.createElement('div'); box.className='chart';
  box.innerHTML='<div class="chead"><span class="ctit">'+s.n+'</span>'
    +'<span class="rng">'+RANGES.map(function(r,i){{
        return '<button type="button" data-n="'+r[1]+'" aria-pressed="'+(i===RANGES.length-1)+'">'+r[0]+'</button>';
      }}).join('')+'</span></div><div class="cbody"></div><p class="cfoot"></p>';
  box.querySelector('.rng').addEventListener('click',function(ev){{
    var b=ev.target.closest('button'); if(!b) return;
    box.querySelectorAll('.rng button').forEach(function(o){{ o.setAttribute('aria-pressed',o===b); }});
    draw(box,id,+b.dataset.n);
  }});
  td.appendChild(box);
  var tr=document.createElement('tr'); tr.className='chartrow'; tr.appendChild(td);
  return tr;
}}
document.querySelectorAll('tr.qrow').forEach(function(row){{
  function toggle(){{
    var open=row.getAttribute('aria-expanded')==='true';
    if(open){{ if(row.nextSibling && row.nextSibling.classList
                && row.nextSibling.classList.contains('chartrow')) row.nextSibling.remove();
               row.setAttribute('aria-expanded','false'); return; }}
    var id=row.dataset.q; if(!SERIES[id]) return;
    var tr=panel(id);
    row.parentNode.insertBefore(tr,row.nextSibling);
    row.setAttribute('aria-expanded','true');
    draw(tr.querySelector('.chart'),id,RANGES[RANGES.length-1][1]);
  }}
  row.addEventListener('click',toggle);
  row.addEventListener('keydown',function(e){{
    if(e.key==='Enter'||e.key===' '){{ e.preventDefault(); toggle(); }}
  }});
}});
}})();
</script>
</body></html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html_out, encoding="utf-8")
    print(f"리포트 생성 → {OUT} ({len(html_out)//1024} KB)")
    return OUT


if __name__ == "__main__":
    build()
