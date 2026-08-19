# -*- coding: utf-8 -*-
"""signals.json → etf_signal_report.html (GS Research Desk 톤 매칭, 자기완결 HTML).
매 실행 시 signals.json을 history/{asof}.json으로 아카이브하고,
과거 일자를 ◀▶ 네비게이션으로 조회 (최근 MAX_DAYS일 임베드)."""
import os, json, glob, html, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
HIST_DIR = os.path.join(HERE, "history")
MAX_DAYS = 15  # 네비게이션으로 볼 수 있는 과거 일수(페이지 용량 상한)
# 예약 시각. .github/workflows/etf-signal.yml 의 cron(0 22 * * * = KST 07:00)과 맞춰 둘 것.
SCHEDULE_TIME = "매일 오전 7시"

def sched_badge(actual):
    """'정기 업데이트 예약 시각 · 실제로 돌아간 시각'을 함께 보여준다.
    GitHub Actions 대기열 지연으로 실제 실행은 예약보다 늦는 경우가 많아, 예약 시각만
    적으면 안 돈 것처럼 보인다."""
    act = f' · 실제 갱신 <b>{esc(actual)}</b>' if actual else ""
    return (f'<span class="sched">🕙 정기 업데이트 <b>{SCHEDULE_TIME}</b>(한국시간){act}'
            f'<span class="schedq"> — 대기열 지연으로 예약보다 늦을 수 있음</span></span>')
WD = "월화수목금토일"

def esc(s): return html.escape(str(s))

def fmt_day(iso):
    """'2026-08-12' → '8/12(수)'. 날짜 형식이 아니면 원문 그대로."""
    try:
        t = datetime.date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{t.month}/{t.day}({WD[t.weekday()]})"

def reasons(s):
    r = []
    if s["ev_trend"]:
        r.append("＋DI가 −DI 상향돌파 · 추세 전환")
    if s["stoch_oversold"]:
        r.append("Stochastic 과매도 반등 · 골든크로스")
    elif s["ev_stoch"]:
        r.append("Stochastic 골든크로스")
    if s["flow"] == "쌍끌이":
        r.append("외인·기관 동반 순매수")
    return r

def reasons_sell(s):
    """매도 경고 사유. 과열이탈은 백테스트에서 방향이 반대여서 매도에서 뺐으므로
    여기서 사유로 쓰지 않는다(표에는 참고 배지로 남는다)."""
    r = []
    if s.get("ev_trend_dead"):
        r.append("＋DI가 −DI 하향이탈 · 추세 꺾임")
    if s.get("dist"):
        r.append("외인·기관 동반 순매도")
    return r

def reasons_adx(s):
    """추세 강도 신호 사유. 20 = 확인, 25 = 강력(더 센 신호)."""
    up = s.get("adx_up")
    dirn = "상승추세" if up else "하락추세"
    r = []
    if s.get("adx_stage") == 2:
        r.append(f"ADX 25 상향돌파 · {dirn} 강화(강력)")
    elif s.get("adx_stage") == 1:
        r.append(f"ADX 20 상향돌파 · {dirn} 확립(확인)")
    if up and s.get("flow") == "쌍끌이":
        r.append("외인·기관 동반 순매수")
    if not up and s.get("dist"):
        r.append("외인·기관 동반 순매도")
    return r

def flow_badge(flow):
    m = {"쌍끌이": ("쌍끌이 ↑", "b-buy"), "개인몰림": ("개인몰림 ⚠", "b-warn"),
         "중립": ("중립", "b-mut"), "수급없음": ("–", "b-mut")}
    label, cls = m.get(flow, (flow, "b-mut"))
    return f'<span class="badge {cls}">{esc(label)}</span>'

def trend_badge(s):
    if s["up_trend"]:
        return f'<span class="badge b-buy">▲ 상승추세</span>'
    if s.get("down_trend"):
        return f'<span class="badge b-down">▼ 하락추세</span>'
    if s["pdi"] < s["ndi"]:
        return f'<span class="badge b-down">▽ 하락</span>'
    return f'<span class="badge b-mut">– 중립</span>'

def sv(v):
    """정렬용 data-v: None은 nan으로(항상 맨 아래로 밀림)."""
    return "nan" if v is None else v

def num(v):
    if v is None: return '<span class="mut">–</span>'
    sign = "+" if v > 0 else ("" if v == 0 else "−")
    cls = "pos" if v > 0 else ("neg" if v < 0 else "mut")
    return f'<span class="{cls}">{sign}{abs(v):,}</span>'

def name_link(s):
    """ETF 이름을 네이버 금융 해당 종목 차트로 연결한다."""
    name = esc(s["name"])
    code = str(s.get("code") or "")
    if not code:
        return name
    return (f'<a class="etf-link" href="https://finance.naver.com/item/fchart.naver?code={esc(code)}"'
            f' target="_blank" rel="noopener">{name}</a>')

RET_COLS = [("ret_1d", "1D", "전일 대비"), ("ret_1w", "WoW", "1주 전 대비"),
            ("ret_1m", "MoM", "1개월 전 대비")]
# YoY(ret_1y)는 스캔에서 함께 저장하지만 이력이 쌓일 때까지 화면에는 넣지 않는다.


def pct(v):
    if v is None:
        return '<span class="mut">–</span>'
    sign = "+" if v > 0 else ("" if v == 0 else "−")
    cls = "pos" if v > 0 else ("neg" if v < 0 else "mut")
    return f'<span class="{cls}">{sign}{abs(v):.1f}%</span>'


def dbar(v, scale):
    """0을 가운데 두고 좌우로 뻗는 막대. scale은 그 열의 최대 절대값."""
    if v is None or not scale:
        return '<span class="dbar"></span>'
    w = min(abs(v) / scale, 1.0) * 50
    side = "left:50%" if v >= 0 else f"right:50%"
    cls = "up" if v >= 0 else "dn"
    return f'<span class="dbar"><i class="{cls}" style="{side};width:{w:.1f}%"></i></span>'


def ret_scale(sig):
    """열별 막대 정규화용 최대 절대값. 열마다 변동폭이 달라 함께 쓰면 1D가 안 보인다."""
    return {k: max([abs(s[k]) for s in sig if s.get(k) is not None] or [1])
            for k, _, _ in RET_COLS}


def ret_cells(s, scale):
    """본표에 들어가는 1D·WoW·MoM 칸. scale이 없으면(구버전 데이터) 칸 자체를 안 만든다."""
    if not scale:
        return ""
    return "".join(
        f'<td class="c ret" data-v="{sv(s.get(k))}">{dbar(s.get(k), scale[k])}'
        f'<span class="rv">{pct(s.get(k))}</span></td>'
        for k, _, _ in RET_COLS)


def ret_headers(scale):
    if not scale:
        return ""
    return "".join(f'<th class="c" data-type="num" title="{esc(t)}">{h}</th>'
                   for _, h, t in RET_COLS)


SPARKS = {}   # code → 최근 종가. 아카이브는 용량 때문에 history를 빼고 저장하므로
              # 최신 payload에서 한 번 채워 전 페이지가 같이 쓴다(차트 모달과 동일한 방식).


def mini_spark(s, w=54, h=16):
    """최근 60거래일 종가 스파크라인. 숫자만으로는 안 보이는 '모양'을 같이 준다.

    과거 일자를 조회해도 시계열은 최신 것을 쓴다 — 아카이브에 종가가 없기 때문이며,
    기존 '추세' 차트 모달도 같은 방식이다."""
    cl = (SPARKS.get(str(s.get("code") or "")) or [])[-60:]
    if len(cl) < 5:
        return ""
    mn, mx = min(cl), max(cl)
    rng = (mx - mn) or 1
    n = len(cl)
    pts = " ".join(f"{i/(n-1)*(w-2)+1:.1f},{h-1-(v-mn)/rng*(h-2):.1f}" for i, v in enumerate(cl))
    cls = "sp-up" if cl[-1] >= cl[0] else "sp-dn"
    return (f'<svg class="spark {cls}" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'aria-hidden="true"><polyline points="{pts}"/></svg>')


def returns_block(sig, day):
    """수익률 섹션 머리 — 그룹 평균 WoW 랭킹.

    종목별 수익률은 아래 전체 신호판에 열로 합쳐져 있고, 여기서는 '어느 섹터가
    셌는지'만 먼저 보여준다."""
    if not any(s.get("ret_1w") is not None for s in sig):
        return ""   # 구버전 아카이브에는 수익률이 없다

    # 그룹 평균 WoW — 종목을 훑기 전에 어느 섹터가 셌는지 먼저 보이게
    g = {}
    for s in sig:
        if s.get("ret_1w") is not None:
            g.setdefault(s["group"], []).append(s["ret_1w"])
    gavg = sorted(((k, sum(v) / len(v), len(v)) for k, v in g.items()),
                  key=lambda x: -x[1])
    gmax = max([abs(v) for _, v, _ in gavg] or [1])
    gitems = "".join(
        f'<li><span class="gn">{esc(k)}</span>{dbar(v, gmax)}'
        f'<span class="gv">{pct(round(v, 1))}</span><small>{n}종목</small></li>'
        for k, v, n in gavg)

    return f"""
<h2>{day}의 수익률 <small style="font:400 12px Inter;color:#8b918e">— 그룹 평균 WoW · 센 섹터부터</small></h2>
<details class="grp" open><summary>그룹 평균 WoW ({len(gavg)}개 그룹) — 종목을 훑기 전에 어느 섹터가 셌는지</summary>
<ul class="gbars">{gitems}</ul></details>
"""


LOGIC_DOC = """
<details class="logic">
<summary>📐 이 판이 신호를 고르는 방식 — 지표·필터·등급·백테스트 (클릭해서 펼치기)</summary>
<div class="logic-body">

<p><b>전제.</b> 모든 계산은 <b>전일 확정 종가</b>로 한다. 스캔이 도는 아침 7시엔 당일 봉이
없고, 장중 값으로 계산하면 오후에 뒤집히는 신호가 나온다. 대신 신호는 하루 늦게 잡힌다.</p>

<details class="sec"><summary>1. 무엇을 신호로 보는가 — 3종류</summary>
<ul>
<li><b>⚡ 추세 강도</b> · ADX가 20을 상향돌파하면 <b>확인</b>, 25를 넘으면 <b>강력</b>.
ADX는 방향이 없는 강도 지표라 방향은 ＋DI/−DI로 정한다. <b>맨 위에 두는 이유</b>는
'추세가 진짜인가'가 '무엇이 교차했나'보다 먼저이기 때문이다 — 교차만 보면 힘없는
횡보장 신호에 휘둘린다.</li>
<li><b>★ 매수</b> · ＋DI가 −DI를 상향돌파(추세 전환)하거나, Stochastic %K가 %D를
<b>25 미만</b>에서 상향돌파(과매도 반등)한 날.</li>
<li><b>▼ 매도</b> · ＋DI가 −DI를 하향이탈(추세 꺾임)한 날. <b>과열이탈은 매도에서 뺐다</b>
— 아래 백테스트 참고.</li>
</ul>
</details>
<details class="sec"><summary>2. 왜 걸러내는가 — 필터</summary>
<ul>
<li><b>유동성</b> · 20일 평균 거래대금 5억 미만은 제외. 신호가 맞아도 못 산다.</li>
<li><b>수급 역방향</b> · 매수는 <b>개인몰림</b>(개인만 사고 외인·기관은 파는 중) 제외,
매도는 <b>쌍끌이</b>(외인·기관 동반 순매수) 제외. 주포와 반대로 가는 신호를 뺀다.</li>
<li><b>과열이탈은 매도에서 제외</b> · 백테스트 결과 매도 신호로서 방향이 반대였다(아래 4번).
감지는 계속하되 표에 참고 배지로만 남긴다.</li>
</ul>
</details>
<details class="sec"><summary>3. 신뢰도 등급 — A / B / C</summary>
<p>신호를 지우는 대신 <b>등급</b>을 매긴다. 하드 필터는 왜 빠졌는지 알 수 없지만,
등급은 다 보여주면서 우선순위만 정한다. 아래 근거가 있을 때마다 점수를 더한다.</p>
<table class="logic-tb">
<tr><th>근거</th><th>점수</th><th>뜻</th></tr>
<tr><td>거래대금 급증(20일 평균 1.5배↑)</td><td>25</td><td>실제 수급이 붙었는가</td></tr>
<tr><td>상대강도 상위 30%(하락신호는 하위 30%)</td><td>20</td><td>남들보다 더 갔는가</td></tr>
<tr><td>ADX 추세 방향 일치</td><td>20</td><td>추세가 신호를 뒷받침하는가</td></tr>
<tr><td>52주 신고가권(하락신호는 신저가권)</td><td>15</td><td>가격 구조상 어디인가</td></tr>
<tr><td>변동성 수축 후 확장</td><td>10</td><td>큰 움직임의 초입인가</td></tr>
<tr><td>외인·기관 연속 순매수/매도 4일↑</td><td>10</td><td>수급이 지속되는가</td></tr>
</table>
<p><b>A</b> 55점↑ · <b>B</b> 30점↑ · <b>C</b> 그 미만.
<b>텔레그램은 B 이상만</b> 보낸다 — 28일간 매수 신호가 138건(하루 4.9건)이라
전부 보내면 알림이 무의미해진다. 이 판에는 C까지 전부 표시된다.</p>
</details>
<details class="sec"><summary>4. 백테스트 — 어느 신호가 실제로 돈이 됐나</summary>
<p>2023-08 ~ 2026-08, 53종목, 표본 3.7만 봉. 진입은 <b>신호 다음 봉 종가</b>(신호 당일
매수는 불가능하므로). 측정 구간이 상승장이라 아무 신호나 +로 나오므로,
<b>기준선</b>(같은 기간 아무 날이나 매수: D+5 +0.41% · D+20 +1.50%) 대비 <b>초과수익</b>만 본다.
매수는 초과가 +여야, 매도는 −여야 유효하다.</p>
<table class="logic-tb">
<tr><th>신호</th><th>D+5 초과</th><th>D+20 초과</th><th>N</th><th>판정</th></tr>
<tr><td>ADX 25 돌파</td><td>+0.73%p</td><td>+1.34%p</td><td>583</td><td>✅ 뚜렷(승률 59%)</td></tr>
<tr><td>ADX 20 돌파</td><td>+0.37%p</td><td>+1.27%p</td><td>705</td><td>✅ 뚜렷</td></tr>
<tr><td>추세골든 ＋DI↑</td><td>+0.13%p</td><td>−0.02%p</td><td>1,685</td><td>⚪ 기준선 수준</td></tr>
<tr><td>과매도반등 %K↑&lt;25</td><td>−0.01%p</td><td>−0.28%p</td><td>1,893</td><td>❌ 무효 → C 고정</td></tr>
<tr><td>추세데드 ＋DI↓</td><td>−0.15%p</td><td>−0.43%p</td><td>1,709</td><td>🔸 매도로 약하게 유효</td></tr>
<tr><td>과열이탈 %K↓&gt;75</td><td>+0.14%p</td><td>+0.91%p</td><td>2,282</td><td>❌ 역방향 → 매도 제외</td></tr>
</table>
<p>이 결과로 두 가지를 바꿨다. <b>과열이탈을 매도에서 뺐고</b>(경고 후 오히려 더 올랐다),
<b>과매도반등 단독 신호는 C 고정</b>이다(텔레그램은 B 이상만 보내므로 발송되지 않는다).
과매도반등은 직전까지 매수 알림의 70%를 차지했다.</p>
<p><b>측정의 한계</b> — 수급 필터(개인몰림·쌍끌이)는 과거 재현이 안 돼 '필터 전 원신호'
기준이다. 현재 유니버스 종목만 봐서 생존 편향이 있고, 거래비용 미반영, 구간이 겹쳐
표본이 독립이 아니다. 측정 구간 3년이 상승장이라 <b>하락장에서는 결과가 다를 수 있다.</b></p>
</details>
<details class="sec"><summary>5. 상대강도는 무엇 대비인가</summary>
<p>시장지수가 아니라 <b>이 판의 56개 ETF 자체</b>가 비교군이다. 실제로 이 안에서
고르기 때문에 비교군으로 더 적절하고, 지수 API를 새로 붙이지 않아도 된다.
표시값은 백분위(0~100)이며 100에 가까울수록 유니버스에서 강하다.</p>
</details>
<details class="sec"><summary>6. 한계 — 알고 쓰자</summary>
<ul>
<li>등급 배점(25/20/20/15/10/10)은 아직 <b>경험칙</b>이다. 백테스트로 신호 유형은
검증했지만 배점 가중치까지 최적화하지는 않았다. 실제로 거래대금 급증은 추세골든에는
도움이 됐지만(D+20 +0.75%p) 과매도반등에는 오히려 해로웠다(−1.16%p).</li>
<li>임계값(25/75, ADX 20/25, 거래대금 1.5배)은 통상값을 쓴 것이며 이 유니버스에
최적화하지 않았다.</li>
<li>매매 신호가 아니라 <b>관심 종목을 좁히는 도구</b>다.</li>
</ul>
</details>

</div>
</details>
"""



def grade_badge(s):
    """A/B/C 신뢰도 등급. 등급이 없는 구버전 데이터면 표시하지 않는다."""
    g = s.get("grade")
    if not g:
        return ""
    return (f'<span class="grade g-{g.lower()}" title="신뢰도 {s.get("conviction", 0)}점 '
            f'— 상단 로직 설명 참고">{g}</span>')


def why_line(s):
    """등급 점수를 만든 근거들. 왜 이 신호가 셌는지/약했는지 그대로 보여준다."""
    why = s.get("conviction_why") or []
    if not why:
        return '<p class="why none-why">뒷받침 근거 없음 — 크로스 단독 신호</p>'
    return '<p class="why">' + " · ".join(f'<span>{esc(w)}</span>' for w in why) + '</p>'


def extra_meta(s):
    """카드 하단에 확인 지표를 덧붙인다(값이 있을 때만)."""
    out = []
    # 급증했을 때는 위 근거 칩이 이미 보여주므로 여기선 뺀다(중복 방지)
    if s.get("vol_ratio") is not None and not s.get("vol_surge"):
        out.append(f'거래대금 <span class="mut">{s["vol_ratio"]}배</span>')
    if s.get("rs_1m") is not None:
        out.append(f'RS {s["rs_1m"]}')
    if s.get("from_high") is not None:
        out.append(f'52주고 대비 {s["from_high"]:+.1f}%')
    return (" · " + " · ".join(out)) if out else ""


def day_html(payload, is_latest):
    """하루치 본문(네비게이션으로 교체되는 부분)."""
    sig = payload["signals"]
    scanned = len(sig)
    alerts = [s for s in sig if s["alert"]]
    sells = [s for s in sig if s.get("alert_sell")]
    # 강력(25↑)을 확인(20↑)보다 앞에 — 맨 위 섹션이라 확신도 높은 것부터 보이게
    adxs = sorted([s for s in sig if s.get("alert_adx")],
                  key=lambda x: (-(x.get("adx_stage") or 0), not x.get("adx_up")))
    n_buy = sum(1 for s in sig if s["flow"] == "쌍끌이")
    n_warn = sum(1 for s in sig if s["flow"] == "개인몰림")
    asof = sig[0]["asof"] if sig else "—"
    day = "오늘" if is_latest else "당일"

    def cards(rows, kind):
        """kind: 'buy'(골든크로스) | 'sell'(데드크로스) | 'adx'(추세 강도)"""
        if not rows:
            msg = {"buy": "이날 새로 뜬 매수 신호가 없습니다. (조정·횡보 국면일 가능성)",
                   "sell": "이날 새로 뜬 매도 경고가 없습니다.",
                   "adx": "이날 ADX 20·25를 새로 돌파한 종목이 없습니다."}[kind]
            return f'<p class="none">{msg}</p>'
        out = ""
        for s in rows:
            why = {"buy": reasons, "sell": reasons_sell, "adx": reasons_adx}[kind]
            rs = " · ".join(why(s)) or "신호 발생"
            # 추세 강도 카드는 방향(상승/하락)과 강도(확인/강력)로 색을 나눈다
            cls = kind
            if kind == "adx":
                cls += " adx-down" if not s.get("adx_up") else ""
                cls += " strong" if s.get("adx_stage") == 2 else ""
            out += f'''
      <article class="alert-card {cls}">
        <div class="ac-head"><span class="ac-title">{grade_badge(s)}<b>{name_link(s)}</b><button class="btn-chart" data-code="{esc(s.get("code") or "")}" title="최근 120거래일 가격 · 신호 발생 시점">추세</button></span><small>{esc(s["group"])} · {s["close"]:,}원</small></div>
        <p>{esc(rs)}</p>
        {why_line(s)}
        <div class="ac-meta">ADX {s["adx"]} · %K {s["k"]}/{s["d"]} · {flow_badge(s["flow"])}{extra_meta(s)}</div>
      </article>'''
        return out

    # 전체 표 — 매수 알림 → 매도 경고 → 추세강도 → 나머지, 각 그룹 내부는 스캔순
    def row_order(x):
        s = x[1]
        rank = 0 if s["alert"] else (1 if s.get("alert_sell") else
                                     (2 if s.get("alert_adx") else 3))
        return (rank, x[0])

    # 수익률 열은 데이터가 있을 때만 붙인다(구버전 아카이브 호환)
    rscale = ret_scale(sig) if any(s.get("ret_1w") is not None for s in sig) else None
    ret_heads = ret_headers(rscale)

    rows_sorted = sorted(enumerate(sig), key=row_order)
    trs = ""
    for _, s in rows_sorted:
        flag = '<span class="star">★ 매수</span>' if s["alert"] else ""
        if s.get("alert_sell"):
            flag += '<span class="skull">▼ 매도</span>'
        if s.get("alert_adx"):
            lv = 25 if s.get("adx_stage") == 2 else 20
            flag += f'<span class="bolt">⚡ ADX{lv}</span>'
        if not s["liquid"]:
            flag += '<span class="lowliq">저유동성</span>'
        stoch_ev = ""
        if s["stoch_oversold"]: stoch_ev = '<span class="mini gold">과매도반등</span>'
        elif s.get("stoch_overbought"): stoch_ev = '<span class="mini dead">과열이탈</span>'
        elif s["ev_stoch"]: stoch_ev = '<span class="mini gold">골든</span>'
        elif s.get("ev_stoch_dead"): stoch_ev = '<span class="mini dead">데드</span>'
        cls = "hl" if s["alert"] else ("hs" if s.get("alert_sell")
                                       else ("ha" if s.get("alert_adx")
                                             else ("dim" if not s["liquid"] else "")))
        adx_ev = ""
        if s.get("adx_stage") == 2: adx_ev = '<span class="mini bolt2">25↑강력</span>'
        elif s.get("adx_stage") == 1: adx_ev = '<span class="mini bolt1">20↑</span>'
        # 정렬용 원시값(표시값이 아닌 실제 숫자/랭크)
        tr_rank = 2 if s["up_trend"] else (0 if s["pdi"] < s["ndi"] else 1)
        fl_rank = {"쌍끌이": 3, "중립": 2, "수급없음": 1, "개인몰림": 0}.get(s["flow"], 2)
        fg_rank = (3 if s["alert"] else (2 if s.get("alert_sell") else
                                         (1 if s.get("alert_adx") else 0))) + (0 if s["liquid"] else -1)
        trs += f'''
      <tr class="{cls}">
        <td class="etf" data-v="{esc(s["name"])}"><div class="etf-row"><b>{name_link(s)}</b><button class="btn-chart" data-code="{esc(s.get("code") or "")}" title="최근 120거래일 가격 · 신호 발생 시점">추세</button></div><div class="etf-sub"><small>{esc(s["group"])}</small>{mini_spark(s, 46, 13)}</div></td>
        <td class="r" data-v="{s["close"]}">{s["close"]:,}</td>
        {ret_cells(s, rscale)}
        <td class="c" data-v="{s["adx"]}">{s["adx"]} {adx_ev}<small class="di">{s["pdi"]}/{s["ndi"]}</small></td>
        <td class="c" data-v="{tr_rank}">{trend_badge(s)}</td>
        <td class="c" data-v="{s["k"]}">{s["k"]}/{s["d"]} {stoch_ev}</td>
        <td class="c" data-v="{fl_rank}">{flow_badge(s["flow"])}</td>
        <td class="r" data-v="{sv(s["for5"])}">{num(s["for5"])}</td>
        <td class="r" data-v="{sv(s["org5"])}">{num(s["org5"])}</td>
        <td class="c flags" data-v="{fg_rank}">{flag}</td>
      </tr>'''

    return f"""
{LOGIC_DOC if is_latest else ""}
<p class="sub">신호 기준일(전일 확정) <b>{esc(asof)}</b><br>
{sched_badge(payload.get("generated_at"))}<br>
ADX(추세) + Stochastic Slow(타이밍) + 수급(외인·기관·개인 5일 순매수, 억원). 신호는 장중 흔들림을 피해 <b>전일 확정 종가</b>로 계산.</p>

<section class="stats">
  <article><small>스캔 종목</small><strong>{scanned}</strong></article>
  <article><small>{day} 매수 신호</small><strong class="g">{len(alerts)}</strong></article>
  <article><small>{day} 매도 경고</small><strong class="r">{len(sells)}</strong></article>
  <article><small>{day} 추세 강도</small><strong class="b">{len(adxs)}</strong></article>
  <article><small>외인·기관 쌍끌이</small><strong class="g">{n_buy}</strong></article>
  <article><small>개인몰림 경계</small><strong class="w">{n_warn}</strong></article>
</section>

<h2>{day}의 추세 강도 <small style="font:400 12px Inter;color:#8b918e">— ADX 20 돌파(확인) · 25 돌파(강력) · 방향은 DI로 판정</small></h2>
<div class="alerts">{cards(adxs, "adx")}</div>

<h2>{day}의 매수 신호 <small style="font:400 12px Inter;color:#8b918e">— 새로 뜬 골든크로스 · 개인몰림 제외 · 유동성 확보 종목</small></h2>
<div class="alerts">{cards(alerts, "buy")}</div>

<h2>{day}의 매도 경고 <small style="font:400 12px Inter;color:#8b918e">— 새로 뜬 데드크로스 · 쌍끌이 제외 · 유동성 확보 종목</small></h2>
<div class="alerts">{cards(sells, "sell")}</div>

{returns_block(sig, day)}

<h2>전체 신호판 ({scanned}) <small style="font:400 12px Inter;color:#8b918e">— 수익률·지표·수급 한 표 · 헤더 클릭으로 정렬 · 종목명 아래 곡선은 <b>최근 60거래일</b> 주가</small></h2>
<div class="tablewrap"><table class="board">
<thead><tr>
<th data-type="text">ETF</th><th class="r" data-type="num">종가</th>
{ret_heads}
<th class="c" data-type="num">ADX<br>+DI/−DI</th><th class="c" data-type="num">추세</th>
<th class="c" data-type="num">%K/%D</th><th class="c" data-type="num">수급</th>
<th class="r" data-type="num" title="외국인 5일 순매수(억원)">외인5D</th><th class="r" data-type="num" title="기관 5일 순매수(억원)">기관5D</th><th class="c" data-type="num">플래그</th>
</tr></thead>
<tbody>{trs}</tbody>
</table></div>
"""


def archive(payload):
    """signals.json을 history/{asof}.json으로 보관 (같은 기준일은 최신으로 덮어씀).
    차트용 history 시계열은 용량이 커서 아카이브에서는 뺀다(차트는 항상 최신 데이터로 표시)."""
    sig = payload.get("signals") or []
    if not sig:
        return
    asof = sig[0].get("asof") or ""
    if len(asof) != 10:
        return
    slim = dict(payload)
    slim["signals"] = [{k: v for k, v in s.items() if k != "history"} for s in sig]
    os.makedirs(HIST_DIR, exist_ok=True)
    with open(os.path.join(HIST_DIR, f"{asof}.json"), "w", encoding="utf-8") as f:
        json.dump(slim, f, ensure_ascii=False)


def build(payload):
    global SPARKS
    SPARKS = {str(s.get("code")): ((s.get("history") or {}).get("close") or [])
              for s in (payload.get("signals") or []) if s.get("code")}
    archive(payload)
    hist = {}
    for p in sorted(glob.glob(os.path.join(HIST_DIR, "*.json"))):
        d = os.path.splitext(os.path.basename(p))[0]
        hist[d] = p
    nav_dates = sorted(hist)[-MAX_DAYS:]
    if not nav_dates:  # history가 없으면 현재 payload 단독
        sig = payload.get("signals") or []
        d = sig[0]["asof"] if sig else "—"
        nav_dates = [d]
        pages = {d: day_html(payload, True)}
        gens = {d: (payload.get("generated_at") or "")[:10]}
    else:
        pages, gens = {}, {}
        for d in nav_dates:
            with open(hist[d], encoding="utf-8") as f:
                pl = json.load(f)
            pages[d] = day_html(pl, is_latest=(d == nav_dates[-1]))
            gens[d] = (pl.get("generated_at") or "")[:10]   # 그날 스캔이 돌아간 날짜

    # 라벨은 'DATA 기준일 → 스캔일' 형태. 기준일은 전일 확정이라 스캔일보다 하루 이상
    # 이르기 때문에, 둘을 같이 보여주지 않으면 최신인데도 옛날 날짜로 보인다.
    date_opts = []
    for d in nav_dates:
        label = f"{fmt_day(d)} DATA"
        g = gens.get(d) or ""
        if g and g != d:
            label += f" → {fmt_day(g)}"
        if d == nav_dates[-1]:
            label += " 최신"
        date_opts.append(f'<option value="{d}">{esc(label)}</option>')

    pages_json = json.dumps(pages, ensure_ascii=False).replace("</", "<\\/")
    dates_json = json.dumps(nav_dates)

    # 차트 데이터: 최신 payload의 history만 사용(과거 일자 조회 중에도 차트는 최신 시계열)
    charts = {}
    for s in payload.get("signals") or []:
        h = s.get("history")
        if h and s.get("code"):
            charts[s["code"]] = {"name": s["name"], **h}
    charts_json = json.dumps(charts, ensure_ascii=False).replace("</", "<\\/")

    return TEMPLATE.format(nav_opts="".join(date_opts), pages_json=pages_json,
                           dates_json=dates_json, ndays=len(nav_dates),
                           charts_json=charts_json)

TEMPLATE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ETF/섹터 신호 포착 · GS Research Desk</title>
<style>
:root{{--bg:#f3f4f1;--ink:#17211d;--muted:#6c746f;--line:#dfe2dc;--card:#fff;
--green:#173f35;--lime:#d9f272;--red:#bd4335}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);
font-family:Inter,Pretendard,"Noto Sans KR",sans-serif;padding:28px 30px 60px}}
.eyebrow{{font-size:10px;font-weight:800;letter-spacing:1.6px;color:#758079;margin:0 0 7px}}
h1{{font:500 30px Georgia,"Noto Serif KR",serif;margin:0}}
.sub{{color:var(--muted);font-size:12px;margin:8px 0 0;line-height:1.6}}
.sub b{{color:#445049}}
.sched{{display:inline-block;background:#eef2ec;border:1px solid var(--line);border-radius:4px;
padding:3px 9px;margin:3px 0;font-size:11px;color:#5b6660}}
.sched b{{color:#2c3a34}}
.schedq{{color:#8b918e}}
@media(max-width:620px){{.schedq{{display:none}}}}
.stats{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin:22px 0 8px}}
.stats article{{background:var(--card);border:1px solid var(--line);padding:18px 20px}}
.stats small{{color:var(--muted);font-size:11px;font-weight:700;letter-spacing:.04em}}
.stats strong{{font:500 32px Georgia;display:block;margin:8px 0 0}}
.stats .g{{color:#286342}}.stats .w{{color:#8a661c}}.stats .r{{color:#a43c31}}
.stats .b{{color:#2b5f8a}}
h2{{font:600 18px Georgia,"Noto Serif KR",serif;margin:30px 0 12px}}
.alerts{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}}
.alert-card{{background:#fff;border:1px solid var(--line);border-left:4px solid var(--green);padding:15px 17px}}
.alert-card.sell{{border-left-color:var(--red)}}
.alert-card.adx{{border-left-color:#2b5f8a}}
.alert-card.adx.adx-down{{border-left-color:#b06a2c}}
.alert-card.adx.strong{{border-left-width:7px}}
.ac-head{{display:flex;justify-content:space-between;align-items:baseline;gap:10px}}
.ac-title{{display:inline-flex;align-items:center;gap:8px}}
.ac-head b{{font-size:15px}}.ac-head small{{color:var(--muted);font-size:11px;white-space:nowrap}}
.alert-card p{{margin:9px 0;font-size:13px;color:#2c3a34;line-height:1.5}}
.ac-meta{{font-size:11px;color:var(--muted);display:flex;gap:8px;align-items:center;flex-wrap:wrap}}
.none{{color:var(--muted);background:#fff;border:1px solid var(--line);padding:22px;text-align:center}}
.tablewrap{{overflow-x:auto;border:1px solid var(--line);background:#fff;margin-top:4px}}
table{{width:100%;min-width:900px;border-collapse:collapse}}
th{{background:#f5f7f3;border-bottom:1px solid #cfd5cf;color:#68736d;font-size:10px;
font-weight:700;letter-spacing:.04em;text-align:left;padding:11px 12px;white-space:nowrap}}
th.c{{text-align:center}}th.r{{text-align:right}}
th.sortable{{cursor:pointer;user-select:none}}th.sortable:hover{{color:#2c3a34}}
th.sortable::after{{content:"⇅";opacity:.32;font-size:9px;margin-left:4px;font-weight:400}}
th.sortable[data-dir=asc]::after{{content:"▲";opacity:.85}}
th.sortable[data-dir=desc]::after{{content:"▼";opacity:.85}}
td{{border-bottom:1px solid #eef1ec;padding:10px 12px;font-size:13px;vertical-align:middle}}
td.c{{text-align:center}}td.r{{text-align:right;font-family:Georgia}}
tbody tr:hover{{background:#fafbf8}}tbody tr.hl{{background:#fbfdf4}}
tbody tr.hl:hover{{background:#f6faea}}tbody tr.dim td{{color:#98a09a}}
tbody tr.hs{{background:#fdf7f5}}tbody tr.hs:hover{{background:#fbefeb}}
tbody tr.ha{{background:#f6f9fc}}tbody tr.ha:hover{{background:#eef4fa}}
.etf b{{font-size:13px;display:block}}.etf small{{color:var(--muted);font-size:10px}}
.etf-link{{color:inherit;text-decoration:none;border-bottom:1px solid transparent}}
.etf-link:hover{{color:#286342;border-bottom-color:#286342}}
.di{{display:block;color:#9aa19d;font-size:10px;font-family:Georgia}}
.badge{{display:inline-block;border-radius:11px;padding:3px 9px;font-size:10px;font-weight:700;white-space:nowrap}}
.b-buy{{background:#e3f3e7;color:#286342}}.b-warn{{background:#fff1cf;color:#765c19}}
.b-down{{background:#f8e9e6;color:#a43c31}}.b-mut{{background:#edf1ed;color:#61706a}}
.mini{{display:inline-block;font-size:9px;font-weight:700;padding:2px 5px;border-radius:4px;margin-left:3px}}
.mini.gold{{background:#fff4d6;color:#8a661c}}
.mini.dead{{background:#f8e3e0;color:#a43c31}}
.logic{{background:#fff;border:1px solid var(--line);border-left:4px solid var(--green);
padding:14px 18px;margin:18px 0 6px}}
.logic>summary{{cursor:pointer;font:600 14px Georgia,"Noto Serif KR",serif;color:#2c3a34}}
.logic-body{{font-size:12.5px;line-height:1.75;color:#3c4842;margin-top:10px}}
.logic-body .sec{{border-top:1px solid #eef1ec;padding:7px 0}}
.logic-body .sec:first-of-type{{border-top:0}}
.logic-body .sec>summary{{cursor:pointer;font:600 13px Georgia,"Noto Serif KR",serif;
color:#1f2b26;list-style:none;padding:2px 0}}
.logic-body .sec>summary::before{{content:"▸ ";color:#8b918e}}
.logic-body .sec[open]>summary::before{{content:"▾ "}}
.logic-body .sec>summary::-webkit-details-marker{{display:none}}
.logic-body .sec[open]{{padding-bottom:10px}}
.logic-body p{{margin:6px 0}}.logic-body ul{{margin:6px 0;padding-left:18px}}
.logic-body li{{margin:3px 0}}
.logic-tb{{border-collapse:collapse;margin:8px 0;min-width:0;width:auto}}
.logic-tb th,.logic-tb td{{border:1px solid #e6eae4;padding:5px 10px;font-size:11.5px;text-align:left}}
.logic-tb th{{background:#f5f7f3;color:#5b6660;white-space:nowrap}}
.logic-tb td:nth-child(2){{text-align:center;font-family:Georgia}}
.grade{{display:inline-block;width:17px;height:17px;line-height:17px;text-align:center;
border-radius:4px;font-size:10px;font-weight:800;margin-right:6px;cursor:help}}
.g-a{{background:#173f35;color:#d9f272}}.g-b{{background:#dfe9df;color:#2c3a34}}
.g-c{{background:#eef1ec;color:#98a09a}}
.why{{margin:6px 0;font-size:11px;color:#5b6660;display:flex;flex-wrap:wrap;gap:4px 6px}}
.why span{{background:#f2f5f0;border-radius:3px;padding:1px 6px}}
.why.none-why{{color:#a9afab;font-style:italic;display:block}}
.spark{{vertical-align:middle;overflow:visible}}
.spark polyline{{fill:none;stroke-width:1.3;vector-effect:non-scaling-stroke}}
.spark.sp-up polyline{{stroke:#2e7d4f}}.spark.sp-dn polyline{{stroke:#bd4335}}
table.rets td{{padding:7px 10px}}table.rets .sparkcell{{width:60px}}
.dbar{{display:block;position:relative;height:7px;background:#f1f4f0;border-radius:2px;margin:0 0 3px}}
.dbar::before{{content:"";position:absolute;left:50%;top:-1px;bottom:-1px;width:1px;background:#d5dcd4}}
.dbar i{{position:absolute;top:0;bottom:0;border-radius:2px}}
.dbar i.up{{background:#7fb894}}.dbar i.dn{{background:#e29b91}}
.rv{{font-size:12px;font-family:Georgia;white-space:nowrap}}
.grp{{background:#fff;border:1px solid var(--line);padding:10px 14px;margin:4px 0 10px}}
.grp summary{{cursor:pointer;font-size:12px;font-weight:700;color:#5b6660}}
/* 순위표는 위에서 아래로 읽어야 흐름이 끊기지 않는다. 여러 열로 흩으면
   가로로 읽게 돼 '센 섹터부터'가 사라지므로, 폰과 PC 모두 한 줄 세로로 둔다. */
.gbars{{list-style:none;margin:10px 0 2px;padding:0;
display:block;max-width:720px}}
.gbars li{{display:grid;grid-template-columns:130px 1fr 58px 46px;align-items:center;
gap:10px;font-size:12px;padding:2px 0}}
.gbars .gn{{color:#445049;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.gbars .gv{{text-align:right;font-family:Georgia}}
.gbars small{{color:#9aa19d;text-align:right}}
.gbars .dbar{{margin:0}}
@media(max-width:620px){{.gbars li{{grid-template-columns:88px 1fr 48px}} .gbars small{{display:none}}}}
.mini.bolt1{{background:#e7eef6;color:#2b5f8a}}
.mini.bolt2{{background:#d9e6f3;color:#1d4e75;font-weight:800}}
.pos{{color:#286342}}.neg{{color:#a43c31}}.mut{{color:#a9afab}}
.flags{{white-space:nowrap}}.star{{color:#5a7a1e;font-size:10px;font-weight:800}}
.skull{{color:#a43c31;font-size:10px;font-weight:800;margin-left:5px}}
.bolt{{color:#2b5f8a;font-size:10px;font-weight:800;margin-left:5px}}
.lowliq{{display:inline-block;margin-left:5px;color:#9a8650;font-size:9px;border:1px solid #e0d8bf;border-radius:4px;padding:1px 4px}}
.legend{{margin-top:14px;color:var(--muted);font-size:11px;line-height:1.9}}
.legend b{{color:#445049}}
.nav{{display:flex;align-items:center;gap:8px;margin:16px 0 0;position:sticky;top:0;
background:var(--bg);padding:8px 0;z-index:5}}
.nav button{{background:var(--card);color:var(--ink);border:1px solid var(--line);
padding:7px 15px;font-size:13px;cursor:pointer;line-height:1}}
.nav button:disabled{{opacity:.35;cursor:default}}
.nav button:not(:disabled):hover{{border-color:#758079}}
.nav select{{background:var(--card);color:var(--ink);border:1px solid var(--line);
padding:7px 9px;font-size:12px}}
.nav .hint{{margin-left:auto;font-size:10px;color:#9aa19d}}
.etf-row{{display:flex;align-items:center;justify-content:space-between;gap:8px}}
.btn-chart{{background:#eef3ec;color:#3d554a;border:1px solid #d3dcd2;border-radius:10px;
padding:2px 8px;font-size:10px;font-weight:700;cursor:pointer;white-space:nowrap;line-height:1.5}}
.btn-chart:hover{{background:#e3f3e7;border-color:#8fae9c;color:#286342}}
#modal-bg{{display:none;position:fixed;inset:0;background:rgba(23,33,29,.45);z-index:50;
align-items:center;justify-content:center;padding:20px}}
.modal{{background:#fff;border:1px solid var(--line);max-width:780px;width:100%;
padding:18px 22px 16px;box-shadow:0 12px 40px rgba(23,33,29,.22)}}
.modal-head{{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin-bottom:10px}}
.modal-head b{{font:600 16px Georgia,"Noto Serif KR",serif}}
#modal-x{{background:none;border:none;font-size:18px;color:#8b918e;cursor:pointer;line-height:1}}
#modal-x:hover{{color:#17211d}}
.chart{{width:100%;height:auto;display:block}}
.grid{{stroke:#e9ede7;stroke-width:1}}
.ax{{font:10px Georgia;fill:#8b918e}}
.pline{{fill:none;stroke:#173f35;stroke-width:1.6}}
.mk-t{{fill:#2e7d4f;cursor:help}}.mk-s{{fill:#c98a1e;cursor:help}}
.mk-dt{{fill:#bd4335;cursor:help}}.mk-ds{{fill:#8e5ba6;cursor:help}}
.chart-legend{{margin:10px 0 0;font-size:11px;color:var(--muted);line-height:1.8}}
.chart-legend .lg-t{{color:#2e7d4f}}.chart-legend .lg-s{{color:#c98a1e}}
.chart-legend .lg-dt{{color:#bd4335}}.chart-legend .lg-ds{{color:#8e5ba6}}
@media(max-width:1180px){{.stats{{grid-template-columns:repeat(3,1fr)}}}}
@media(max-width:620px){{body{{padding:20px 12px 50px}}.stats{{grid-template-columns:1fr 1fr}}
table{{min-width:760px}}}}
</style></head><body>
<p class="eyebrow">ETF · SECTOR SIGNAL</p>
<h1>ETF/섹터 신호 포착</h1>
<div class="nav">
<button id="btn-prev" title="이전 기준일 (←)">◀</button>
<select id="sel-date">{nav_opts}</select>
<button id="btn-next" title="다음 기준일 (→)">▶</button>
<span class="hint">← → 키로도 이동 · 과거 {ndays}일 조회</span>
</div>
<div id="day"></div>

<p class="legend">
<b>추세</b> +DI&gt;−DI &amp; ADX&gt;20 = 상승추세, −DI&gt;+DI &amp; ADX&gt;20 = 하락추세 ·
<b>과매도반등</b> Stochastic %K가 %D를 25 미만에서 상향돌파 · <b>과열이탈</b> %K가 %D를 75 초과에서 하향이탈 ·
<b>쌍끌이</b> 외인+기관 5일 동반 순매수 · <b>개인몰림</b> 개인만 순매수(외인·기관 이탈) = 경계 ·
<b>★매수</b> 오늘 새 골든크로스 + 개인몰림 아님 + 20일 거래대금 5억↑ ·
<b>▼매도</b> 오늘 새 데드크로스 + 쌍끌이 아님 + 20일 거래대금 5억↑<br>
<b>⚡추세 강도</b> ADX가 <b>20</b>을 상향돌파하면 추세 확립(확인), <b>25</b>를 상향돌파하면 추세 강화(강력).
ADX는 방향이 없는 강도 지표라 방향은 +DI/−DI로 판정한다(＋DI&gt;−DI = 상승, −DI&gt;＋DI = 하락).
크로스 신호와 별개이므로 같은 날 함께 뜰 수 있다.<br>
수급 단위: 억원 · 매매가 아닌 <b>참고용 신호</b>입니다.<br>
<b>정렬</b> 헤더를 클릭하면 해당 열 기준으로 정렬(다시 클릭 시 오름/내림 전환). 값 없음(–)은 항상 맨 아래.<br>
<b>추세 버튼</b> 종목별 최근 120거래일 가격 차트와 과거 신호 발생 시점(▲ 추세 골든크로스 · ● 과매도 반등 · ▼ 추세 데드크로스 · ◆ 과열 이탈)을 보여줍니다.
</p>

<div id="modal-bg"><div class="modal">
<div class="modal-head"><b id="modal-title"></b><button id="modal-x" title="닫기 (Esc)">✕</button></div>
<div id="modal-body"></div>
</div></div>
<script>
function initSort(){{
  // 로직 설명 안에도 표가 있어 '#day table'은 그쪽을 먼저 잡는다 — 데이터 표만 지정.
  var table = document.querySelector('#day table.board');
  if(!table) return;
  var tbody = table.tBodies[0];
  var ths = table.tHead.rows[0].cells;
  var cur = -1, dir = 1;
  function val(td, type){{
    var v = td.getAttribute('data-v');
    if(type === 'num'){{
      var n = parseFloat(v);
      return isNaN(n) ? null : n;
    }}
    return (v || td.textContent).trim().toLowerCase();
  }}
  Array.prototype.forEach.call(ths, function(th, i){{
    var type = th.getAttribute('data-type');
    if(!type) return;
    th.classList.add('sortable');
    th.addEventListener('click', function(){{
      dir = (cur === i) ? -dir : 1;
      cur = i;
      Array.prototype.forEach.call(ths, function(x){{ x.removeAttribute('data-dir'); }});
      th.setAttribute('data-dir', dir > 0 ? 'asc' : 'desc');
      var rows = Array.prototype.slice.call(tbody.rows);
      rows.sort(function(a, b){{
        var av = val(a.cells[i], type), bv = val(b.cells[i], type);
        if(av === null && bv === null) return 0;
        if(av === null) return 1;   // 값 없음은 방향과 무관하게 맨 아래
        if(bv === null) return -1;
        if(av < bv) return -dir;
        if(av > bv) return dir;
        return 0;
      }});
      rows.forEach(function(r){{ tbody.appendChild(r); }});
    }});
  }});
}}
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
  initSort();
}}
prev.addEventListener("click", function () {{ show(idx - 1); }});
next.addEventListener("click", function () {{ show(idx + 1); }});
sel.addEventListener("change", function () {{ show(DATES.indexOf(sel.value)); }});
document.addEventListener("keydown", function (e) {{
  if (e.key === "ArrowLeft") show(idx - 1);
  else if (e.key === "ArrowRight") show(idx + 1);
}});
show(idx);

/* ── 종목별 시계열 신호 차트 (추세 버튼 → 모달) ── */
var CHARTS = {charts_json};
var mbg = document.getElementById('modal-bg');
document.addEventListener('click', function (e) {{
  var b = e.target.closest ? e.target.closest('.btn-chart') : null;
  if (b) openChart(b.getAttribute('data-code'));
}});
mbg.addEventListener('click', function (e) {{ if (e.target === mbg) closeChart(); }});
document.getElementById('modal-x').addEventListener('click', closeChart);
document.addEventListener('keydown', function (e) {{ if (e.key === 'Escape') closeChart(); }});
function closeChart() {{ mbg.style.display = 'none'; }}
function openChart(code) {{
  var c = CHARTS[code];
  var title = document.getElementById('modal-title');
  var body = document.getElementById('modal-body');
  if (!c) {{
    title.textContent = '시계열 데이터 없음';
    body.innerHTML = '<p class="none">아직 이력이 없습니다. 다음 스캔부터 차트가 표시됩니다.</p>';
  }} else {{
    title.textContent = c.name + ' · 최근 ' + c.dates.length + '거래일 (' + c.dates[0] + ' ~ ' + c.dates[c.dates.length - 1] + ')';
    body.innerHTML = renderChart(c);
  }}
  mbg.style.display = 'flex';
}}
function renderChart(c) {{
  var W = 700, H = 310, L = 56, R = 14, T = 18, B = 34;
  var n = c.close.length;
  var mn = Math.min.apply(null, c.close), mx = Math.max.apply(null, c.close);
  if (mx === mn) mx = mn + 1;
  var pad = (mx - mn) * 0.07; mn -= pad; mx += pad;
  function X(i) {{ return L + (W - L - R) * (n <= 1 ? 0 : i / (n - 1)); }}
  function Y(v) {{ return T + (H - T - B) * (1 - (v - mn) / (mx - mn)); }}
  var pts = '';
  for (var i = 0; i < n; i++) pts += (i ? ' ' : '') + X(i).toFixed(1) + ',' + Y(c.close[i]).toFixed(1);
  var s = '<svg viewBox="0 0 ' + W + ' ' + H + '" class="chart" role="img">';
  for (var g = 0; g <= 4; g++) {{
    var v = mn + (mx - mn) * g / 4, y = Y(v).toFixed(1);
    s += '<line x1="' + L + '" y1="' + y + '" x2="' + (W - R) + '" y2="' + y + '" class="grid"/>';
    s += '<text x="' + (L - 6) + '" y="' + (+y + 3) + '" class="ax" text-anchor="end">' + Math.round(v).toLocaleString() + '</text>';
  }}
  var step = Math.max(1, Math.round(n / 6));
  for (var i = 0; i < n; i += step)
    s += '<text x="' + X(i).toFixed(1) + '" y="' + (H - 10) + '" class="ax" text-anchor="middle">' + c.dates[i].slice(5) + '</text>';
  s += '<polyline points="' + pts + '" class="pline"/>';
  (c.t || []).forEach(function (i) {{
    var x = X(i).toFixed(1), y = Y(c.close[i]);
    s += '<path d="M' + x + ' ' + (y + 6).toFixed(1) + ' l5 9 h-10 z" class="mk-t">' +
         '<title>' + c.dates[i] + ' · 추세 골든크로스(+DI가 −DI 상향돌파) · ' + c.close[i].toLocaleString() + '원</title></path>';
  }});
  (c.s || []).forEach(function (i) {{
    var x = X(i).toFixed(1), y = Y(c.close[i]);
    s += '<circle cx="' + x + '" cy="' + (y - 10).toFixed(1) + '" r="4.5" class="mk-s">' +
         '<title>' + c.dates[i] + ' · 과매도 반등(Stochastic 골든크로스) · ' + c.close[i].toLocaleString() + '원</title></circle>';
  }});
  (c.dt || []).forEach(function (i) {{
    var x = X(i).toFixed(1), y = Y(c.close[i]);
    s += '<path d="M' + x + ' ' + (y - 6).toFixed(1) + ' l5 -9 h-10 z" class="mk-dt">' +
         '<title>' + c.dates[i] + ' · 추세 데드크로스(+DI가 −DI 하향이탈) · ' + c.close[i].toLocaleString() + '원</title></path>';
  }});
  (c.ds || []).forEach(function (i) {{
    var x = X(i).toFixed(1), y = Y(c.close[i]);
    s += '<path d="M' + x + ' ' + (y + 7).toFixed(1) + ' l5 5 l-5 5 l-5 -5 z" class="mk-ds">' +
         '<title>' + c.dates[i] + ' · 과열 이탈(Stochastic 데드크로스) · ' + c.close[i].toLocaleString() + '원</title></path>';
  }});
  s += '</svg>';
  s += '<p class="chart-legend"><span class="lg-t">▲</span> 추세 골든크로스(+DI가 −DI 상향돌파, 라인 아래) · ' +
       '<span class="lg-s">●</span> 과매도 반등(Stochastic %K↑%D, 라인 위)<br>' +
       '<span class="lg-dt">▼</span> 추세 데드크로스(+DI가 −DI 하향이탈, 라인 위) · ' +
       '<span class="lg-ds">◆</span> 과열 이탈(Stochastic %K↓%D, 라인 아래) · 마커에 마우스를 올리면 날짜·가격 표시</p>';
  return s;
}}
</script>
</body></html>"""

if __name__ == "__main__":
    with open(os.path.join(HERE, "signals.json"), encoding="utf-8") as f:
        payload = json.load(f)
    out = build(payload)
    # 출력 경로: 환경변수 ETF_REPORT_OUT 우선(워크플로가 대시보드 static으로 지정), 없으면 로컬
    dest = os.getenv("ETF_REPORT_OUT", os.path.join(HERE, "etf_signal_report.html"))
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(out)
    print("생성:", dest, f"({len(out)} bytes)")
