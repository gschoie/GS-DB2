# -*- coding: utf-8 -*-
"""증시 법칙 달력 — 격언·계절성을 날짜 위에 올린 페이지.

rules.yml(격언·통계) + dates.yml(명절·선거·휴장일) + macro_desk/fixed_dates.json(FOMC)
→ 3년치 이벤트를 계산해 HTML 하나에 박는다. '오늘'은 **화면 JS 가 보는 시각으로** 정하므로
페이지는 규칙·날짜가 바뀔 때만 다시 구우면 된다(크론 없음 — 격언은 매일 안 바뀐다).

출력: ../telegram_research_dashboard/static/market_calendar_report.html

날짜 원칙(macro_desk 와 같다)
  · 규칙으로 뽑는 것(둘째 목요일·T+2 마감)은 코드가, 기관 공표·음력·선거는 dates.yml 이.
  · 출처가 한 곳뿐이거나 미공표면 tentative → 화면에 ~.
  · 거래일 셈은 dates.yml 의 KRX 휴장일로 — 빠진 휴일이 있으면 창이 하루 어긋난다.
    그래서 창 끝은 '≈' 로 적는다(통계 자체가 ±1일을 가를 만큼 정밀하지 않다).
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = Path(os.environ.get(
    "MARKET_CAL_OUT",
    ROOT / "telegram_research_dashboard" / "static" / "market_calendar_report.html"))
FOMC_FILE = ROOT / "macro_desk" / "fixed_dates.json"

WD = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
PHASES = ["election", "post", "midterm", "pre"]          # (year-2024) % 4
PHASE_KO = {"election": "미국 대선해(4년차)", "post": "대선 다음 해(1년차)",
            "midterm": "미국 중간선거해(2년차)", "pre": "대선 전 해(3년차)"}
CATEGORY = {"month": "월별 계절성", "cycle": "4년 주기(짝수해)", "window": "구간",
            "pin": "날짜 이벤트", "signal": "달력 밖 신호"}


def esc(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def phase_of(year: int) -> str:
    return PHASES[(year - 2024) % 4]


# ── 거래일 ─────────────────────────────────────────────────────────────────
class TradingDays:
    """주말 + dates.yml 휴장일만 안다. 모르는 휴일은 거래일로 센다(→ 창이 하루 어긋날 수 있다)."""

    def __init__(self, holidays: set[dt.date]):
        self.h = holidays

    def is_td(self, d: dt.date) -> bool:
        return d.weekday() < 5 and d not in self.h

    def prev(self, d: dt.date) -> dt.date:
        """d 이하 가장 가까운 거래일."""
        while not self.is_td(d):
            d -= dt.timedelta(days=1)
        return d

    def next(self, d: dt.date) -> dt.date:
        while not self.is_td(d):
            d += dt.timedelta(days=1)
        return d

    def shift(self, d: dt.date, n: int) -> dt.date:
        """거래일 n개 이동(d 자신은 세지 않는다). n=0 이면 d 를 거래일로 맞춘 값."""
        if n == 0:
            return d
        step = 1 if n > 0 else -1
        left = abs(n)
        while left:
            d += dt.timedelta(days=step)
            if self.is_td(d):
                left -= 1
        return d


def nth_weekday(year: int, month: int, n: int, wd: int) -> dt.date:
    d = dt.date(year, month, 1)
    k = 0
    while True:
        if d.weekday() == wd:
            k += 1
            if k == n:
                return d
        d += dt.timedelta(days=1)


# ── 로드 ───────────────────────────────────────────────────────────────────
def load() -> tuple[dict, dict, list[str]]:
    rules = yaml.safe_load((HERE / "rules.yml").read_text(encoding="utf-8"))["rules"]
    dates = yaml.safe_load((HERE / "dates.yml").read_text(encoding="utf-8"))
    fomc: list[str] = []
    if FOMC_FILE.exists():
        try:
            fomc = json.loads(FOMC_FILE.read_text(encoding="utf-8")).get("dates", {}).get("fomc", [])
        except Exception:
            fomc = []
    return rules, dates, fomc


def _d(v) -> dt.date:
    return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v))


# ── 이벤트 계산 ─────────────────────────────────────────────────────────────
def build_events(rules: list[dict], dates: dict, fomc: list[str], years: list[int]) -> dict:
    hol = {_d(x) for ys in dates.get("krx_holidays", {}).values() for x in ys}
    td = TradingDays(hol)
    holidays = [dict(h, start=_d(h["start"]), end=_d(h["end"])) for h in dates.get("holidays", [])]
    elections = [dict(e, date=_d(e["date"])) for e in dates.get("elections", [])]

    months, windows, pins = [], [], []

    def win(rule, start, end, tone, label=None, tentative=False, approx=True):
        windows.append({"id": rule["id"], "start": start.isoformat(), "end": end.isoformat(),
                        "tone": tone, "label": label or rule["name"], "conf": rule["conf"],
                        "market": rule.get("market", ""), "tentative": tentative, "approx": approx})

    def pin(rule, day, label=None, tentative=False):
        pins.append({"id": rule["id"], "date": day.isoformat(), "tone": rule["tone"],
                     "label": label or rule["name"], "conf": rule["conf"], "tentative": tentative})

    for year in years:
        ph = phase_of(year)
        last_td = td.prev(dt.date(year, 12, 31))
        first_td = td.next(dt.date(year, 1, 1))

        for r in rules:
            k = r["kind"]
            if k == "month":
                for m in r["months"]:
                    months.append({"id": r["id"], "year": year, "month": m, "market": r["market"],
                                   "tone": r["tone"], "label": r["name"], "conf": r["conf"], "cycle": False})
            elif k == "cycle":
                if ph == r["phase"]:
                    for m in r["months"]:
                        months.append({"id": r["id"], "year": year, "month": m, "market": "CYCLE",
                                       "tone": r["tone"], "label": r["name"], "conf": r["conf"], "cycle": True})
            elif k == "window":
                a = r["anchor"]
                b, af = int(r.get("before_td", 0)), int(r.get("after_td", 0))
                tone = r["tone"]
                t_before = {"weak_then_strong": "weak", "strong_then_weak": "strong"}.get(tone, tone)
                t_after = {"weak_then_strong": "strong", "strong_then_weak": "weak"}.get(tone, tone)
                if a == "yearend":
                    end = td.shift(last_td, -2)              # T+2 결제 → 마지막 거래일 2거래일 전
                    win(r, td.shift(end, -b), end, t_before)
                elif a == "yearstart":
                    win(r, first_td, td.shift(first_td, af - 1), t_after)
                elif a.startswith("holiday:"):
                    hid = a.split(":", 1)[1]
                    for h in holidays:
                        if h["id"] != hid or h["start"].year != year:
                            continue
                        tent = bool(h.get("tentative"))
                        pre_end = td.prev(h["start"] - dt.timedelta(days=1))
                        post_start = td.next(h["end"] + dt.timedelta(days=1))
                        if b:
                            win(r, td.shift(pre_end, -(b - 1)), pre_end, t_before,
                                f'{h["name"]} 전 {b}거래일', tent)
                        if af:
                            win(r, post_start, td.shift(post_start, af - 1), t_after,
                                f'{h["name"]} 후 {af}거래일', tent)
                        win(r, h["start"], h["end"], "closed", f'{h["name"]} 연휴', tent, approx=False)
                elif a.startswith("election:"):
                    eid = a.split(":", 1)[1]
                    for e in elections:
                        if e["id"] != eid or e["date"].year != year:
                            continue
                        tent = bool(e.get("tentative"))
                        if b:
                            pre_end = td.prev(e["date"] - dt.timedelta(days=1))
                            win(r, td.shift(pre_end, -(b - 1)), pre_end, t_before,
                                f'{e["name"]} 전 {b}거래일', tent)
                        if af:
                            post = td.next(e["date"] + dt.timedelta(days=1))
                            win(r, post, td.shift(post, af - 1), t_after,
                                f'{e["name"]} 후 {af}거래일', tent)
                        pin(r, e["date"], e["name"], tent)
            elif k == "pin":
                rule = r["rule"]
                if isinstance(rule, dict) and "nth_weekday" in rule:
                    n, wd, ms = rule["nth_weekday"]
                    for m in ms:
                        day = nth_weekday(year, m, int(n), WD[wd])
                        if r["id"].startswith("kr_"):
                            day = td.prev(day)              # 휴장이면 직전 거래일
                        pin(r, day)
                elif rule == "yearend_t2":
                    pin(r, td.shift(last_td, -2))
                elif rule == "yearend_exdiv":
                    pin(r, td.shift(last_td, -1))
                elif rule == "k200_effective":
                    for m in (6, 12):
                        q = td.prev(nth_weekday(year, m, 2, WD["thu"]))
                        pin(r, td.next(q + dt.timedelta(days=1)))
                elif rule == "msci":
                    for ms in dates.get("msci", []):
                        for key, lab in (("announce", "MSCI 리뷰 발표"), ("effective", "MSCI 반영")):
                            day = _d(ms[key])
                            if day.year == year:
                                pin(r, day, lab, bool(ms.get("tentative")))
                elif rule == "fomc":
                    for s in fomc:
                        day = _d(s)
                        if day.year == year:
                            pin(r, day, "FOMC")
                            pin(r, day - dt.timedelta(days=1), "FOMC 전날")
                elif rule == "santa":
                    nxt_first = td.next(dt.date(year + 1, 1, 1))
                    win(r, td.shift(last_td, -4), td.shift(nxt_first, 1), "strong",
                        "산타 랠리 구간", approx=False)

    cards = []
    for r in rules:
        cards.append({k: r.get(k, "") for k in ("id", "kind", "name", "saying", "stat", "note", "tone", "conf", "market")})
        cards[-1]["category"] = CATEGORY.get(r["kind"], r["kind"])

    return {"years": years, "phases": {y: phase_of(y) for y in years}, "phase_ko": PHASE_KO,
            "holidays": sorted(h.isoformat() for h in hol if h.year in years),
            "months": months, "windows": sorted(windows, key=lambda w: w["start"]),
            "pins": sorted(pins, key=lambda p: p["date"]), "cards": cards,
            "built": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M"),
            "holidays_note": "거래일 창은 dates.yml 의 KRX 휴장일 기준 — 빠진 휴일이 있으면 하루 어긋날 수 있어 ≈ 로 적는다"}


# ── HTML ───────────────────────────────────────────────────────────────────
def render(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return r"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>증시 법칙 달력</title>
<style>
:root{--bg:#fff;--fg:#1c2430;--muted:#6b7684;--line:#e5e8ec;--card:#f7f8fa;
--up:#d64545;--dn:#3b6fd4;--vol:#b8860b;--accent:#2f6f4f;--warnbg:#fff8e6;--warnline:#e8c87a;
--upbg:rgba(214,69,69,.12);--dnbg:rgba(59,111,212,.12);--volbg:rgba(184,134,11,.14);--infobg:rgba(107,118,132,.12);--closedbg:rgba(107,118,132,.22)}
@media(prefers-color-scheme:dark){:root{--bg:#14181f;--fg:#e6e9ee;--muted:#8b93a1;--line:#2a313c;--card:#1b212b;
--accent:#8fc7a5;--warnbg:#2b2718;--warnline:#5c4f27;--upbg:rgba(214,69,69,.22);--dnbg:rgba(59,111,212,.22);--volbg:rgba(184,134,11,.24)}}
*{box-sizing:border-box}
body{margin:0;padding:18px 16px 48px;background:var(--bg);color:var(--fg);font:14px/1.6 -apple-system,"Malgun Gothic","Apple SD Gothic Neo",sans-serif}
.wrap{max-width:860px;margin:0 auto}
h1{font-size:19px;margin:0 0 2px} h2{font-size:15px;margin:0}
.sub{color:var(--muted);font-size:12.5px;margin:0 0 14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:0 0 10px}
.ctitle{font-weight:700;font-size:13px;margin:4px 0 6px;color:var(--muted)}
.note{color:var(--muted);font-size:12px;margin:6px 0 0}
.note.warn{background:var(--warnbg);border:1px solid var(--warnline);border-radius:8px;padding:8px 10px;color:var(--fg)}
details.sec{margin:0 0 4px}
details.sec>summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:6px;padding:4px 0;border-bottom:1px solid var(--line)}
details.sec>summary::-webkit-details-marker{display:none}
details.sec>summary::before{content:"▼";color:var(--muted);font-size:11px;width:12px;flex:none;transition:transform .12s}
details.sec:not([open])>summary::before{transform:rotate(-90deg)}
details.sec[open]>summary{margin-bottom:8px}
.badge{display:inline-block;font-size:10.5px;padding:0 6px;border-radius:9px;margin-right:4px;vertical-align:1px;font-weight:700}
.b-strong{background:var(--upbg);color:var(--up)} .b-weak{background:var(--dnbg);color:var(--dn)}
.b-vol{background:var(--volbg);color:var(--vol)} .b-info{background:var(--infobg);color:var(--muted)}
.b-closed{background:var(--closedbg);color:var(--muted)}
.stars{color:#c99a2e;font-size:11px;letter-spacing:1px}
.tent{color:var(--muted);font-weight:400}
/* 지금 */
.now{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media(max-width:640px){.now{grid-template-columns:1fr}}
.now h3{font-size:13px;margin:0 0 6px;color:var(--muted)}
.now ul{margin:0;padding-left:0;list-style:none} .now li{padding:5px 0;border-top:1px dashed var(--line);font-size:13px}
.now li:first-child{border-top:none}
.now .when{color:var(--muted);font-size:11.5px;margin-left:4px}
.say{color:var(--muted);font-size:12px;display:block}
/* 12개월 띠 */
.strip{display:grid;grid-template-columns:72px repeat(12,minmax(0,1fr));gap:2px;font-size:11px;margin:4px 0}
.strip .lab{color:var(--muted);font-size:11px;padding:4px 2px;white-space:nowrap}
.strip .m{border-radius:4px;padding:3px 2px;text-align:center;min-height:36px;line-height:1.25;background:var(--card);border:1px solid var(--line);overflow:hidden}
.strip .m.strong{background:var(--upbg);border-color:transparent} .strip .m.weak{background:var(--dnbg);border-color:transparent}
.strip .m.cur{outline:2px solid var(--accent)}
.strip .m small{display:block;color:var(--muted);font-size:9.5px}
.strip .m .v{font-weight:700}
.ysel{display:flex;gap:6px;align-items:center;margin:0 0 6px}
.ysel button,.calnav button{border:1px solid var(--line);background:var(--bg);color:var(--fg);border-radius:6px;padding:2px 10px;cursor:pointer;font-size:12.5px}
.ysel button.on,.calnav button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
/* 달력 */
.calnav{display:flex;gap:6px;align-items:center;margin:0 0 6px} .calnav b{font-size:14px;margin:0 6px}
.cal{display:grid;grid-template-columns:repeat(5,minmax(0,1fr)) repeat(2,minmax(0,.55fr));gap:3px;margin:0 0 10px}
.cal-h{text-align:center;font-size:11px;color:var(--muted);padding:2px 0}
.cal-cell{min-height:64px;border:1px solid var(--line);border-radius:6px;padding:2px 3px 3px;background:var(--bg);position:relative}
.cal-cell.empty{border:none;background:none} .cal-cell.wknd{background:var(--card)}
.cal-cell.today{border-color:var(--accent);border-width:2px}
.cal-cell.hol{background:var(--closedbg)}
.cal-d{font-size:11px;color:var(--muted)}
.band{display:block;height:4px;border-radius:2px;margin:2px 0 0}
.band.strong{background:var(--up)} .band.weak{background:var(--dn)} .band.info{background:var(--muted)} .band.closed{background:transparent}
.band.vol{background:var(--vol)}
.bandlab{display:block;font-size:9.5px;line-height:1.2;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chip{display:block;font-size:10px;line-height:1.25;margin-top:2px;padding:1px 3px;border-radius:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer;color:inherit;text-decoration:none}
.chip.vol{background:var(--volbg)} .chip.info{background:var(--infobg)} .chip.strong{background:var(--upbg)} .chip.weak{background:var(--dnbg)}
.legend{font-size:11.5px;color:var(--muted)} .legend i{display:inline-block;width:14px;height:4px;border-radius:2px;vertical-align:middle;margin:0 3px 0 8px}
/* 카드 */
.gcard{border:1px solid var(--line);border-radius:10px;background:var(--card);padding:10px 12px;margin:0 0 8px}
.gcard summary{cursor:pointer;font-size:14px} .gcard summary .meta{color:var(--muted);font-size:11.5px;font-weight:400;margin-left:6px}
.gcard p{margin:6px 0 0;font-size:13px} .gcard .q{font-style:italic;color:var(--muted)}
.cat{font-weight:700;font-size:13px;color:var(--muted);margin:14px 0 6px}
a{color:inherit}
</style></head><body><div class="wrap">
<h1>📅 증시 법칙 달력</h1>
<p class="sub">격언과 계절성을 날짜 위에 올렸다. <b>통계는 평균이지 예언이 아니다</b> — 방향과 반복 여부만 보고, 크기는 믿지 말 것.
<span id="today-line"></span></p>

<details class="sec" id="s-now" open><summary><h2>🔭 지금 어디쯤인가</h2></summary>
<div class="card"><div id="now" class="now"></div></div>
</details>

<details class="sec" id="s-year" open><summary><h2>📊 1년 띠 — 월별 계절성 + 올해의 주기</h2></summary>
<div class="card">
<div class="ysel" id="ysel"></div>
<div id="strip"></div>
<p class="note">위 두 줄은 매년 같은 평균(코스피 1980~2024 / S&amp;P 1950~), 셋째 줄은 <b>그 해의 4년 주기 위치</b>에서만 켜진다.
짝수해 = 미국 선거해. 강세 <span class="badge b-strong">빨강</span> 약세 <span class="badge b-weak">파랑</span>. 칸을 누르면 그 달 달력으로.</p>
</div></details>

<details class="sec" id="s-cal" open><summary><h2>🗓 달력 — 구간과 날짜</h2></summary>
<div class="card">
<div class="calnav"><button id="cprev">◀</button><b id="ctitle"></b><button id="cnext">▶</button><button id="ctoday">오늘</button></div>
<div id="cal"></div>
<p class="legend">띠: <i style="background:var(--up)"></i>강세 기대 <i style="background:var(--dn)"></i>약세 주의 <i style="background:var(--muted)"></i>표시만 · 칩: <span class="badge b-vol">변동성</span><span class="badge b-info">일정</span> · 회색 칸 = 휴장 · ~ = 미확정 날짜 · 창 끝은 거래일 셈이라 ≈</p>
<p class="note" id="calnote"></p>
</div></details>

<details class="sec" id="s-rules" open><summary><h2>📜 격언과 근거</h2></summary>
<p class="note">★★★ 긴 표본에서 여러 기관 일관 · ★★ 한 기관이거나 기간 따라 갈림 · ★ 사례·속설. 숫자는 출처마다 표본이 달라 어긋난다 — 상세와 출처 링크는 <code>market_calendar/ADAGES.md</code>.</p>
<div id="cards"></div>
</details>

<p class="note">빌드 <span id="built"></span> · 규칙 <code>market_calendar/rules.yml</code> · 날짜 <code>dates.yml</code>(명절·선거·휴장) · FOMC 는 매크로 데스크 확정일을 그대로 읽는다.</p>
</div>
<script id="data" type="application/json">__PAYLOAD__</script>
<script>
(function(){
const D=JSON.parse(document.getElementById('data').textContent);
const $=s=>document.querySelector(s);
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const pad=n=>String(n).padStart(2,'0');
const iso=d=>d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());
const WD='월화수목금토일';
// 오늘은 KST 로 고정 — 보는 기기의 시간대로 하면 새벽에 날짜가 하루 어긋난다
const kst=new Date(new Date().toLocaleString('en-US',{timeZone:'Asia/Seoul'}));
const today=new Date(kst.getFullYear(),kst.getMonth(),kst.getDate());
const T=iso(today);
const stars=n=>'<span class="stars">'+'★'.repeat(n)+'</span>';
const tone=t=>({strong:'강세',weak:'약세',vol:'변동성',info:'일정',closed:'휴장'}[t]||t);
const badge=t=>'<span class="badge b-'+t+'">'+tone(t)+'</span>';
const tent=p=>p.tentative?'<span class="tent">~</span>':'';
const fmt=s=>{const [y,m,d]=s.split('-').map(Number);const dd=new Date(y,m-1,d);return m+'/'+d+'('+WD[(dd.getDay()+6)%7]+')'};
const cardOf={};D.cards.forEach(c=>cardOf[c.id]=c);
const sayOf=id=>cardOf[id]?'<span class="say">“'+esc(cardOf[id].saying)+'”</span>':'';

let selYear=D.years.includes(today.getFullYear())?today.getFullYear():D.years[0];
let calY=selYear, calM=today.getMonth()+1;
$('#today-line').innerHTML='오늘 <b>'+T+'</b> · '+selYear+'년은 <b>'+(selYear%2?'홀수해':'짝수해')+' — '+esc(D.phase_ko[D.phases[selYear]])+'</b>';
$('#built').textContent=D.built;

// ── 지금 ──
function renderNow(){
  const y=today.getFullYear(),m=today.getMonth()+1;
  const ms=D.months.filter(x=>x.year===y&&x.month===m);
  const act=D.windows.filter(w=>w.start<=T&&T<=w.end&&w.tone!=='closed');
  const lim=new Date(today);lim.setDate(lim.getDate()+45);const L=iso(lim);
  const up=D.pins.filter(p=>p.date>=T&&p.date<=L);
  const upw=D.windows.filter(w=>w.start>T&&w.start<=L&&w.tone!=='closed');
  const li=(t,b,s)=>'<li>'+badge(t)+b+(s?' '+s:'')+'</li>';
  let a='<div><h3>이번 달('+m+'월)의 계절성</h3><ul>';
  a+=ms.length?ms.map(x=>li(x.tone,(x.cycle?'<b>올해 주기</b> · ':x.market==='KR'?'코스피 · ':'미국 · ')+esc(x.label)+' '+stars(x.conf),sayOf(x.id))).join(''):'<li>이 달에 걸린 월별 격언 없음</li>';
  a+='</ul><h3 style="margin-top:10px">지금 지나는 구간</h3><ul>';
  a+=act.length?act.map(w=>li(w.tone,esc(w.label)+tent(w)+' <span class="when">'+fmt(w.start)+'~'+fmt(w.end)+(w.approx?'≈':'')+'</span> '+stars(w.conf),sayOf(w.id))).join(''):'<li>없음</li>';
  a+='</ul></div>';
  let b='<div><h3>앞으로 45일</h3><ul>';
  const items=[...upw.map(w=>({d:w.start,h:li(w.tone,esc(w.label)+tent(w)+' <span class="when">'+fmt(w.start)+'~'+fmt(w.end)+(w.approx?'≈':'')+'</span> '+stars(w.conf),sayOf(w.id))})),
               ...up.map(p=>({d:p.date,h:li(p.tone,esc(p.label)+tent(p)+' <span class="when">'+fmt(p.date)+'</span> '+stars(p.conf))}))].sort((x,y)=>x.d<y.d?-1:1);
  b+=items.length?items.map(x=>x.h).join(''):'<li>없음</li>';
  b+='</ul></div>';
  $('#now').innerHTML=a+b;
}

// ── 1년 띠 ──
function renderStrip(){
  $('#ysel').innerHTML='연도 '+D.years.map(y=>'<button data-y="'+y+'" class="'+(y===selYear?'on':'')+'">'+y+'</button>').join('')+' <span class="note" style="margin:0 0 0 8px">'+esc(D.phase_ko[D.phases[selYear]])+'</span>';
  $('#ysel').querySelectorAll('button').forEach(b=>b.onclick=()=>{selYear=+b.dataset.y;calY=selYear;calM=(selYear===today.getFullYear())?today.getMonth()+1:1;renderStrip();renderCal()});
  const rows=[['코스피','KR'],['미국','US'],['올해 주기','CYCLE']];
  let h='<div class="strip"><div class="lab"></div>'+Array.from({length:12},(_,i)=>'<div class="lab" style="text-align:center">'+(i+1)+'월</div>').join('')+'</div>';
  for(const [lab,mk] of rows){
    h+='<div class="strip"><div class="lab">'+lab+'</div>';
    for(let m=1;m<=12;m++){
      const xs=D.months.filter(x=>x.year===selYear&&x.month===m&&x.market===mk);
      const t=xs.find(x=>x.tone==='strong')?'strong':xs.find(x=>x.tone==='weak')?'weak':'';
      const cur=(selYear===today.getFullYear()&&m===today.getMonth()+1)?' cur':'';
      const txt=xs.length?xs.map(x=>'<span class="v">'+tone(x.tone)+'</span><small>'+esc(x.label.replace(/^(코스피는|미국|중간선거해|대선 전 해|대선해)\s*/,''))+'</small>').join(''):'';
      h+='<div class="m '+t+cur+'" data-m="'+m+'" title="'+esc(xs.map(x=>x.label).join(' / '))+'">'+txt+'</div>';
    }
    h+='</div>';
  }
  $('#strip').innerHTML=h;
  $('#strip').querySelectorAll('.m').forEach(c=>c.onclick=()=>{calY=selYear;calM=+c.dataset.m;renderCal();document.getElementById('s-cal').open=true;document.getElementById('s-cal').scrollIntoView({behavior:'smooth'})});
}

// ── 달력 ──
function renderCal(){
  const y=calY,m=calM;
  $('#ctitle').textContent=y+'년 '+m+'월';
  const first=new Date(y,m-1,1),lead=(first.getDay()+6)%7,last=new Date(y,m,0).getDate();
  const closedSet=new Set(D.holidays);D.windows.filter(w=>w.tone==='closed').forEach(w=>{for(let d=new Date(w.start+'T00:00');iso(d)<=w.end;d.setDate(d.getDate()+1))closedSet.add(iso(d))});
  let h='<div class="cal">'+'월화수목금토일'.split('').map(w=>'<div class="cal-h">'+w+'</div>').join('');
  for(let i=0;i<lead;i++)h+='<div class="cal-cell empty"></div>';
  const mlist=D.months.filter(x=>x.year===y&&x.month===m);
  for(let d=1;d<=last;d++){
    const dd=new Date(y,m-1,d),s=iso(dd),wk=(dd.getDay()+6)%7;
    const trading=wk<5&&!closedSet.has(s);
    let k='cal-cell';if(s===T)k+=' today';if(wk>=5)k+=' wknd';if(closedSet.has(s))k+=' hol';
    let inner='<span class="cal-d">'+d+'</span>';
    for(const w of D.windows){
      if(!trading||w.tone==='closed'||s<w.start||s>w.end)continue;   // 창은 거래일 창 — 주말·휴장엔 안 그린다
      const lab=(s===w.start||wk===0)?'<span class="bandlab" title="'+esc(w.label)+'">'+esc(w.label)+(w.tentative?'~':'')+'</span>':'';
      inner+='<span class="band '+w.tone+'" title="'+esc(w.label)+' '+w.start+'~'+w.end+'"></span>'+lab;
    }
    for(const p of D.pins){ if(p.date!==s)continue;
      inner+='<a class="chip '+p.tone+'" href="#g-'+esc(p.id)+'" title="'+esc(p.label)+'">'+esc(p.label)+(p.tentative?'~':'')+'</a>';
    }
    h+='<div class="'+k+'">'+inner+'</div>';
  }
  h+='</div>';
  $('#cal').innerHTML=h;
  const t=mlist.length?'이 달의 월별 격언: '+mlist.map(x=>badge(x.tone)+(x.cycle?'올해 주기 · ':x.market==='KR'?'코스피 · ':'미국 · ')+esc(x.label)+' '+stars(x.conf)).join(' &nbsp; '):'이 달에 걸린 월별 격언 없음';
  $('#calnote').innerHTML=t;
  $('#cal').querySelectorAll('a.chip').forEach(a=>a.onclick=()=>{const el=document.getElementById(a.getAttribute('href').slice(1));if(el){el.open=true;document.getElementById('s-rules').open=true}});
}
function step(n){let y=calY,m=calM+n;if(m<1){m=12;y--}if(m>12){m=1;y++}if(!D.years.includes(y))return;calY=y;calM=m;renderCal()}
$('#cprev').onclick=()=>step(-1);$('#cnext').onclick=()=>step(1);
$('#ctoday').onclick=()=>{calY=today.getFullYear();calM=today.getMonth()+1;if(!D.years.includes(calY)){calY=D.years[0];calM=1}renderCal()};

// ── 카드 ──
function renderCards(){
  const cats=[...new Set(D.cards.map(c=>c.category))];
  let h='';
  for(const cat of cats){
    h+='<div class="cat">'+esc(cat)+'</div>';
    for(const c of D.cards.filter(x=>x.category===cat)){
      h+='<details class="gcard" id="g-'+esc(c.id)+'"><summary>'+badge(c.tone==='weak_then_strong'?'weak':c.tone==='strong_then_weak'?'strong':c.tone)+'<b>'+esc(c.name)+'</b><span class="meta">'+stars(c.conf)+(c.market?' · '+esc(c.market):'')+'</span></summary>';
      h+='<p class="q">“'+esc(c.saying)+'”</p><p><b>근거</b> — '+esc(c.stat)+'</p>'+(c.note?'<p class="note">'+esc(c.note)+'</p>':'')+'</details>';
    }
  }
  $('#cards').innerHTML=h;
}
renderNow();renderStrip();renderCal();renderCards();
// 섹션 접은 상태 기억(매크로 데스크와 같은 방식)
try{const K='mcalSections',st=JSON.parse(localStorage.getItem(K)||'{}')||{};
  document.querySelectorAll('details.sec').forEach(d=>{if(st[d.id]===false)d.open=false;d.addEventListener('toggle',()=>{st[d.id]=d.open;try{localStorage.setItem(K,JSON.stringify(st))}catch(e){}})})}catch(e){}
})();
</script>
</body></html>""".replace("__PAYLOAD__", payload)


def build(years: list[int] | None = None) -> Path:
    rules, dates, fomc = load()
    if years is None:
        y0 = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).year
        years = sorted({2026, y0, y0 + 1, y0 + 2})
        years = [y for y in years if y >= 2026][:3] if len(years) > 3 else years
    data = build_events(rules, dates, fomc, years)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(data), encoding="utf-8")
    print(f"리포트 생성 → {OUT} ({OUT.stat().st_size // 1024} KB) · 월 {len(data['months'])} 창 {len(data['windows'])} 핀 {len(data['pins'])}")
    return OUT


if __name__ == "__main__":
    build()
