"""시장관심.내러티브 리포트 페이지 생성.

static/market_trend/<날짜>.json 들을 모아 날짜 네비게이션이 달린 단일 HTML로 굽는다.
출력: ../telegram_research_dashboard/static/market_trend_report.html
대시보드 '투자 > 시장관심.내러티브' 메뉴가 이 파일을 iframe으로 띄운다.

구조·스타일은 market_flow/build_report.py와 같은 계열(820px, 라이트/다크 변수,
PAGES 임베드 + 이전/다음 버튼)로 맞춘다.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE.parent / "telegram_research_dashboard" / "static" / "market_trend"
OUT = HERE.parent / "telegram_research_dashboard" / "static" / "market_trend_report.html"

EMBED_DAYS = 30  # 페이지에 임베드할 최근 일수
WD = "월화수목금토일"


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def load_days() -> dict[str, dict]:
    days = {}
    if DATA_DIR.is_dir():
        for path in sorted(DATA_DIR.glob("????-??-??.json"))[-EMBED_DAYS:]:
            try:
                days[path.stem] = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                print(f"  ⚠ {path.name} 읽기 실패: {exc} — 건너뜀")
    return days


def strength_dots(value) -> str:
    n = max(0, min(int(value or 0), 5))
    return '<span class="dots">' + "●" * n + "○" * (5 - n) + "</span>"


def render_theme(i: int, theme: dict) -> str:
    badge = ('<span class="badge new">NEW</span>' if theme.get("status") == "new"
             else '<span class="badge">지속</span>')
    parts = [f'<div class="card theme"><div class="ctitle">{i}. {esc(theme.get("name", "(이름 없음)"))} '
             f'{badge} {strength_dots(theme.get("strength"))}</div>']
    if theme.get("narrative"):
        parts.append(f'<p class="narr">{esc(theme["narrative"])}</p>')
    if theme.get("keywords"):
        chips = "".join(f'<span class="kw">{esc(k)}</span>' for k in theme["keywords"])
        parts.append(f'<div class="kws">{chips}</div>')
    evidence = theme.get("evidence") or []
    if evidence:
        quotes = "".join(
            f'<li><b>{esc(ev.get("channel", "?"))}</b> — “{esc(ev.get("quote", ""))}”</li>'
            for ev in evidence
        )
        parts.append(f'<ul class="ev">{quotes}</ul>')
    parts.append("</div>")
    return "".join(parts)


def render_day(payload: dict) -> str:
    meta = payload.get("meta") or {}
    stats = payload.get("stats") or {}
    parts = []
    if payload.get("one_liner"):
        parts.append(f'<p class="oneliner">{esc(payload["one_liner"])}</p>')
    parts.append(
        f'<p class="sub">창 {esc(meta.get("window", ""))} · 채널 {stats.get("channels", "?")}개 · '
        f'글 {stats.get("messages", "?")}건(중복 접은 뒤 {stats.get("groups", "?")}건) · '
        f'{esc(meta.get("engine", ""))}</p>'
    )

    themes = payload.get("themes") or []
    if themes:
        parts += [render_theme(i, t) for i, t in enumerate(themes, start=1)]
    else:
        parts.append('<p class="note">이 날짜는 테마 합성 없이 계량 신호만 산출되었습니다.</p>')

    mood = payload.get("community_mood")
    if mood:
        parts.append(render_mood(mood))

    signals = payload.get("signals") or {}
    spikes = signals.get("spikes") or []
    if spikes:
        rows = []
        for row in spikes:
            burst = f"{row['burst']:.1f}×" if row.get("burst") is not None else "—"
            base = row["base_daily"] if row.get("base_daily") is not None else "—"
            flag = "🆕" if row.get("new") else ""
            rows.append(f"<tr><th>{esc(row.get('term'))}</th><td>{row.get('count', '')}</td>"
                        f"<td>{base}</td><td>{burst}</td><td>{flag}</td></tr>")
        parts.append(
            '<details class="appendix"><summary>부록 — 급증 키워드</summary>'
            '<div class="scroll"><table><thead><tr><th>키워드</th><th>오늘</th><th>평소</th>'
            '<th>배수</th><th></th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>"
        )
        if spikes[0].get("burst") is None:
            parts.append('<p class="note">기준선 수집 중 — 이력이 3일 쌓이면 평소 대비 배수가 나옵니다.</p>')
        parts.append("</details>")

    posts = signals.get("top_posts") or []
    if posts:
        items = []
        for post in posts:
            link = f' <a href="{esc(post["url"])}" target="_blank" rel="noopener">원문</a>' if post.get("url") else ""
            items.append(f'<li><b>[{post.get("channels", "?")}]</b> ({esc(post.get("channel", "?"))} · '
                         f'{esc(post.get("time_kst", ""))}) {esc(post.get("head", ""))}{link}</li>')
        parts.append('<details class="appendix"><summary>부록 — 여러 채널이 퍼나른 글</summary>'
                     '<ul class="posts">' + "".join(items) + "</ul></details>")

    community = payload.get("community")
    if community:
        parts.append(render_community(community))
    dc = payload.get("community_dc")
    if dc:
        parts.append(render_dc(dc))
    return "".join(parts)


def render_mood(mood: dict) -> str:
    """커뮤니티 무드 — Gemini가 개미 신호(종토·디시)를 읽고 매긴 정서 점수와 주목 종목."""
    score = int(mood.get("score") or 0)
    face = "🔥" if score >= 50 else "🙂" if score >= 10 else "😐" if score > -10 else "😟" if score > -50 else "🧊"
    parts = [f'<div class="card mood"><div class="ctitle">🐜 커뮤니티 무드 {face} '
             f'<span class="dots">{"+" if score > 0 else ""}{score}</span></div>']
    if mood.get("summary"):
        parts.append(f'<p class="narr">{esc(mood["summary"])}</p>')
    stocks = mood.get("hot_stocks") or []
    if stocks:
        items = []
        for s in sorted(stocks, key=lambda x: -(int(x.get("score") or 0))):
            sc = int(s.get("score") or 0)
            arrow = "📈" if sc >= 0 else "📉"
            items.append(f'<li>{arrow} <b>{esc(s.get("name"))}</b> ({"+" if sc > 0 else ""}{sc}) '
                         f'<span class="pmeta">{esc(s.get("reason", ""))}</span></li>')
        parts.append('<ul class="ev">' + "".join(items) + "</ul>")
    parts.append("</div>")
    return "".join(parts)


def render_community(community: dict) -> str:
    """커뮤니티 온도(네이버 종토) — 개미 관심 섹션. 트렌드(리서치 채널)와 성격이 달라 구분해 그린다."""
    parts = [f'<h2 class="commhead">🌡️ NAVER 종토방 온도 <span class="commsub">'
             f'종목 {community.get("universe", "?")}개 · '
             f'글 {community.get("posts", "?")}건</span></h2>']

    stocks = community.get("hot_stocks") or []
    if stocks:
        rows = []
        any_capped = False
        for row in stocks:
            burst = f"{row['burst']}×" if row.get("burst") is not None else "—"
            base = row["base_daily"] if row.get("base_daily") is not None else "—"
            # 상한에 걸린 대형주는 수집분의 작성 속도로 환산한 추정치 — ≈로 구분한다
            posts = f"≈{row.get('posts', 0):,}" if row.get("capped") else f"{row.get('posts', '')}"
            any_capped = any_capped or bool(row.get("capped"))
            rows.append(f"<tr><th>{esc(row.get('name'))}</th><td>{posts}</td>"
                        f"<td>{base}</td><td>{burst}</td></tr>")
        parts.append('<div class="card"><div class="ctitle">글 수 급증 종목</div><div class="scroll">'
                     '<table><thead><tr><th>종목</th><th>오늘 글</th><th>평소</th><th>배수</th></tr></thead>'
                     '<tbody>' + "".join(rows) + "</tbody></table></div>"
                     + ('<p class="note">≈ 글이 많아 일부만 수집한 종목 — 작성 속도로 하루치를 환산한 추정</p>'
                        if any_capped else "") + "</div>")

    keywords = community.get("keywords") or []
    if keywords:
        chips = "".join(
            f'<span class="kw">{esc(k["term"])} {k["count"]}'
            + (f' · {k["burst"]}×' if k.get("burst") is not None else "") + "</span>"
            for k in keywords[:12]
        )
        parts.append(f'<div class="card"><div class="ctitle">제목 급증 키워드</div><div class="kws">{chips}</div></div>')

    for label, key, meta in (("공감 상위 글", "top_liked", lambda p: f"공감 {p.get('likes', 0)} · 조회 {p.get('views', 0)}"),
                             ("조회 급상승 글", "top_rising", lambda p: f"시간당 {p.get('views_per_hour', 0)}회 · 조회 {p.get('views', 0)}")):
        posts = community.get(key) or []
        if not posts:
            continue
        items = []
        for p in posts:
            link = f' <a href="{esc(p["url"])}" target="_blank" rel="noopener">원문</a>' if p.get("url") else ""
            items.append(f'<li><b>[{esc(p.get("name"))}]</b> {esc(p.get("title", ""))} '
                         f'<span class="pmeta">({meta(p)}){link}</span></li>')
        parts.append(f'<div class="card"><div class="ctitle">{label}</div>'
                     '<ul class="posts">' + "".join(items) + "</ul></div>")

    ranks = community.get("search_top") or []
    if ranks:
        parts.append('<p class="note">네이버 검색상위: ' +
                     " · ".join(f"{r['rank']}.{esc(r['name'])}" for r in ranks[:10]) + "</p>")
    return "".join(parts)


def render_dc(dc: dict) -> str:
    """DC 갤러리 온도 — 시장 전체 분위기·밈. 종토(종목 관심)와 성격이 달라 따로 그린다."""
    parts = [f'<h2 class="commhead">🎮 갤러리 온도 <span class="commsub">'
             f'{esc(dc.get("source", ""))} · 샘플 {dc.get("posts_sampled", "?")}글</span></h2>']

    galleries = dc.get("galleries") or []
    if galleries:
        chips = []
        for g in galleries:
            posts = f"≈{g.get('posts', 0):,}" if g.get("capped") else f"{g.get('posts', 0):,}"
            burst = f" · {g['burst']}×" if g.get("burst") is not None else ""
            chips.append(f'<span class="kw">{esc(g.get("name"))} {posts}글{burst}</span>')
        parts.append(f'<div class="card"><div class="ctitle">갤러리 열기 (하루 글 수)</div>'
                     f'<div class="kws">{"".join(chips)}</div></div>')

    keywords = dc.get("keywords") or []
    if keywords:
        chips = "".join(
            f'<span class="kw">{esc(k["term"])} {k["count"]}'
            + (f' · {k["burst"]}×' if k.get("burst") is not None else "") + "</span>"
            for k in keywords[:12]
        )
        parts.append(f'<div class="card"><div class="ctitle">제목 급증 키워드</div><div class="kws">{chips}</div></div>')

    for label, key, meta in (("개념글 (추천 상위)", "top_recommended", lambda p: f"추천 {p.get('recommend', 0)} · 조회 {p.get('views', 0)}"),
                             ("화제의 글 (조회순)", "top_viewed", lambda p: f"조회 {p.get('views', 0)}")):
        posts = dc.get(key) or []
        if not posts:
            continue
        items = []
        for p in posts:
            link = f' <a href="{esc(p["url"])}" target="_blank" rel="noopener">원문</a>' if p.get("url") else ""
            items.append(f'<li><b>[{esc(p.get("gallery"))}]</b> {esc(p.get("title", ""))} '
                         f'<span class="pmeta">({meta(p)}){link}</span></li>')
        parts.append(f'<div class="card"><div class="ctitle">{label}</div>'
                     '<ul class="posts">' + "".join(items) + "</ul></div>")
    return "".join(parts)


def build() -> None:
    days = load_days()
    if not days:
        pages = {"empty": '<p class="note">아직 산출된 날이 없습니다 — 첫 실행 후 이 페이지가 채워집니다.</p>'}
        nav_dates = ["empty"]
        date_opts = ['<option value="empty">데이터 없음</option>']
    else:
        pages = {day: render_day(payload) for day, payload in days.items()}
        nav_dates = sorted(pages)
        date_opts = []
        for day in nav_dates:
            date = f"{day[5:7]}/{day[8:10]}"
            import datetime as _dt
            label = f"{date} ({WD[_dt.date.fromisoformat(day).weekday()]})"
            if day == nav_dates[-1]:
                label += " · 최신"
            date_opts.append(f'<option value="{day}">{label}</option>')

    pages_json = json.dumps(pages, ensure_ascii=False).replace("</", "<\\/")
    dates_json = json.dumps(nav_dates)

    page = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>시장관심.내러티브</title>
<style>
:root{{--bg:#fff;--fg:#1c2430;--muted:#6b7684;--line:#e5e8ec;--card:#f7f8fa;--accent:#2e6b4f}}
@media(prefers-color-scheme:dark){{:root{{--bg:#14181f;--fg:#e6e9ee;--muted:#8b93a1;
--line:#2a313c;--card:#1b212b;--accent:#7fc8a4}}}}
*{{box-sizing:border-box}}
body{{margin:0;padding:18px 16px 40px;background:var(--bg);color:var(--fg);
font:14px/1.6 -apple-system,"Malgun Gothic","Apple SD Gothic Neo",sans-serif}}
.wrap{{max-width:820px;margin:0 auto}}
h1{{font-size:19px;margin:0 0 2px}}
.sub{{color:var(--muted);font-size:12.5px;margin:2px 0 12px}}
.oneliner{{font-size:15.5px;font-weight:600;margin:14px 0 4px;padding:10px 14px;
border-left:3px solid var(--accent);background:var(--card);border-radius:0 8px 8px 0}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:14px;margin:10px 0}}
.ctitle{{font-size:14.5px;font-weight:700;margin:0 0 6px}}
.badge{{display:inline-block;font-size:10.5px;border:1px solid var(--line);border-radius:4px;
padding:1px 6px;color:var(--muted);vertical-align:1px}}
.badge.new{{color:#fff;background:var(--accent);border-color:var(--accent)}}
.dots{{color:var(--accent);letter-spacing:1px;font-size:11px;vertical-align:1px}}
.narr{{margin:6px 0}}
.kws{{margin:8px 0 2px}}
.kw{{display:inline-block;font-size:12px;background:var(--bg);border:1px solid var(--line);
border-radius:12px;padding:2px 9px;margin:2px 4px 2px 0;color:var(--muted)}}
.ev{{margin:8px 0 2px;padding-left:18px;font-size:12.5px;color:var(--muted)}}
.ev li{{margin:3px 0}}
.appendix{{margin:12px 0}}
.appendix summary{{cursor:pointer;font-size:13px;font-weight:600;color:var(--muted)}}
table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;margin-top:8px}}
th,td{{padding:5px 8px;border-bottom:1px solid var(--line);text-align:right;font-size:12.5px;
white-space:nowrap}}
tr th:first-child{{text-align:left;font-weight:600}}
thead th{{color:var(--muted);font-weight:600;font-size:11.5px}}
.posts{{margin:8px 0;padding-left:18px;font-size:12.5px}}
.posts li{{margin:5px 0}}
.posts a{{color:var(--accent)}}
.note{{font-size:12.5px;color:var(--muted);margin:8px 2px}}
.commhead{{font-size:16px;margin:26px 0 4px;padding-top:14px;border-top:1px solid var(--line)}}
.commsub{{font-size:12px;font-weight:400;color:var(--muted)}}
.pmeta{{font-size:11.5px;color:var(--muted)}}
.scroll{{overflow-x:auto}}
footer{{margin-top:28px;font-size:11.5px;color:var(--muted)}}
.nav{{display:flex;align-items:center;gap:8px;margin:10px 0 4px;position:sticky;top:0;
background:var(--bg);padding:6px 0;z-index:5}}
.nav button{{background:var(--card);color:var(--fg);border:1px solid var(--line);
border-radius:8px;padding:6px 14px;font-size:14px;cursor:pointer;line-height:1}}
.nav button:disabled{{opacity:.35;cursor:default}}
.nav select{{background:var(--card);color:var(--fg);border:1px solid var(--line);
border-radius:8px;padding:6px 8px;font-size:13px}}
.nav .hint{{margin-left:auto;font-size:11.5px;color:var(--muted)}}
</style></head><body><div class="wrap">
<h1>🧠 시장관심.내러티브</h1>
<p class="sub">구독 텔레그램 전 채널의 하루치에서 계량으로 추린 신호를 테마로 묶은 것 · 매일 06:30 갱신</p>
<div class="nav">
<button id="btn-prev" title="이전 날짜 (←)">◀</button>
<select id="sel-date">{"".join(date_opts)}</select>
<button id="btn-next" title="다음 날짜 (→)">▶</button>
<span class="hint">← → 키로도 이동</span>
</div>
<div id="day"></div>
<footer>신호: 급증 키워드(7일 기준선 대비) · 채널 간 전파 수 · min-hash 중복 접기 —
테마 합성만 Gemini · 과거 {len(nav_dates)}일 조회 가능 · GS Research Desk</footer>
</div>
<script>
var PAGES = {pages_json};
var DATES = {dates_json};
var idx = DATES.length - 1;
var sel = document.getElementById("sel-date");
var prev = document.getElementById("btn-prev");
var next = document.getElementById("btn-next");
function show(i) {{
  idx = Math.max(0, Math.min(i, DATES.length - 1));
  document.getElementById("day").innerHTML = PAGES[DATES[idx]];
  sel.value = DATES[idx];
  prev.disabled = idx === 0;
  next.disabled = idx === DATES.length - 1;
}}
prev.addEventListener("click", function () {{ show(idx - 1); }});
next.addEventListener("click", function () {{ show(idx + 1); }});
sel.addEventListener("change", function () {{ show(DATES.indexOf(sel.value)); }});
document.addEventListener("keydown", function (e) {{
  if (e.key === "ArrowLeft") show(idx - 1);
  else if (e.key === "ArrowRight") show(idx + 1);
}});
show(idx);
</script>
</body></html>"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"리포트 생성: {OUT} ({OUT.stat().st_size / 1024:.0f} KB, {len(days)}일 임베드)")


if __name__ == "__main__":
    build()
