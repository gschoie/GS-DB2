"""브리핑 페이지에 라이트/다크 테마와 ☀/🌙 토글을 끼워 넣는다.

**왜 주입 방식인가**: 브리핑 렌더러가 12개(방산 3판·통합·주간, 건기 4종, 에너지,
전략레이더, 유튜브 모음)인데 전부 팔레트를 각자 복사해 갖고 있었다. 렌더러에는
색을 `var(--gs-*)` 로 바꿔 두고, **변수 정의와 토글은 배포 때 한 번에** 넣는다.
`gate.py` 와 같은 자리(build_static 끝)에서 `_site/**/*.html` 을 훑으므로
**이미 커밋된 과거 브리핑 아카이브도 다음 배포부터 같이 바뀐다**.

대상 판별은 따로 표식을 두지 않고 **본문에 `var(--gs-` 가 있는 페이지**로 한다 —
렌더러가 색을 변수로 적었다는 것 자체가 "이 테마를 쓰겠다"는 뜻이다. 대시보드
본체·수급·매크로처럼 자기 색 체계를 가진 화면은 변수를 안 쓰므로 건드리지 않는다.

**기본값은 시스템 설정**(`prefers-color-scheme`) — 낮에 밝은 사무실이면 라이트,
밤이면 다크로 알아서 간다. 토글로 고르면 그 선택이 localStorage 에 남아 시스템
설정을 이긴다.

색은 눈대중이 아니라 명도대비를 계산해 골랐다. 종전 다크는 `#d8dee9`/`#0d1117`
= **14.0:1** 로, 흰 글자가 번져 보이는(halation) 구간이었다 → 본문 11.3:1 로 낮춤.
라이트는 12.4:1. 둘 다 WCAG AAA(7:1) 위이면서 과하지 않은 값이다.
"""

from __future__ import annotations

from pathlib import Path

MARKER = "<!--gs-theme-->"
USES_THEME = "var(--gs-"

# 다크 = 기본값, 라이트 = 시스템이 라이트이거나 사용자가 고른 경우.
# 두 벌을 같은 변수 이름으로 덮어쓰므로 렌더러는 한 번만 적으면 된다.
DARK_VARS = """--gs-bg:#161a21;--gs-ink:#c9d1dc;--gs-ink-strong:#e6ebf2;--gs-muted:#8e98a8;
--gs-line:#232e3f;--gs-line-strong:#2e3a4e;--gs-line-soft:#1f2834;
--gs-panel:#1c222c;--gs-hover:#1e2531;--gs-card:#1a2029;
--gs-accent:#d6b27a;--gs-accent2:#e8b756;--gs-link:#89b9ff;
--gs-up:#ff7b7b;--gs-down:#6ca6ff;--gs-mint:#7fd9b6;--gs-mint-line:#24443a;
--gs-violet:#d9a7ff;--gs-note-bg:#1c222c;--gs-note-line:#2e3a4e"""

LIGHT_VARS = """--gs-bg:#fbfbfa;--gs-ink:#32322e;--gs-ink-strong:#1b1b19;--gs-muted:#6b6b66;
--gs-line:#e3e3df;--gs-line-strong:#d5d5d0;--gs-line-soft:#eeeeea;
--gs-panel:#ffffff;--gs-hover:#f3f3f1;--gs-card:#ffffff;
--gs-accent:#7d6021;--gs-accent2:#8a6a26;--gs-link:#1a66b4;
--gs-up:#c62828;--gs-down:#1457a8;--gs-mint:#1f7a5c;--gs-mint-line:#cfe3da;
--gs-violet:#7b3fb0;--gs-note-bg:#f7f5ef;--gs-note-line:#e0d9c8"""

STYLE = f"""{MARKER}<style>
:root{{color-scheme:dark;{DARK_VARS}}}
/* 시스템이 라이트이고, 사용자가 다크로 고정하지 않았을 때 */
@media (prefers-color-scheme:light){{
  :root:not([data-gs-theme="dark"]){{color-scheme:light;{LIGHT_VARS}}}
}}
/* 사용자가 고른 값은 시스템 설정을 이긴다 */
:root[data-gs-theme="light"]{{color-scheme:light;{LIGHT_VARS}}}
:root[data-gs-theme="dark"]{{color-scheme:dark;{DARK_VARS}}}

#gs-theme-btn{{position:fixed;top:10px;right:12px;z-index:2147483646;
  width:34px;height:34px;border-radius:999px;cursor:pointer;
  border:1px solid var(--gs-line-strong);background:var(--gs-panel);color:var(--gs-ink);
  font:14px/1 'Pretendard','Apple SD Gothic Neo',sans-serif;
  display:flex;align-items:center;justify-content:center;padding:0;
  opacity:.5;transition:opacity .15s}}
#gs-theme-btn:hover{{opacity:1}}
@media print{{#gs-theme-btn{{display:none}}}}
</style>"""

# 토글: 자동 → 라이트 → 다크 → 자동. 고른 값은 이 기기에 남는다.
# iframe 안에서는 버튼을 감춘다 — 부모 창 버튼 하나로 충분하고, 같은 오리진이라
# localStorage 와 storage 이벤트로 안쪽 문서도 같이 따라 움직인다.
SCRIPT = """<script>
(function(){
 var K="gs_theme",ORDER=["auto","light","dark"],
     ICON={auto:"\\u25D1",light:"\\u2600",dark:"\\u263D"},
     NAME={auto:"\\uC2DC\\uC2A4\\uD15C \\uC124\\uC815\\uC744 \\uB530\\uB984",
           light:"\\uBC1D\\uAC8C \\uACE0\\uC815",dark:"\\uC5B4\\uB461\\uAC8C \\uACE0\\uC815"};
 function get(){try{var v=localStorage.getItem(K);return ORDER.indexOf(v)>=0?v:"auto"}catch(e){return "auto"}}
 function apply(v){
   var de=document.documentElement;
   if(v==="auto")de.removeAttribute("data-gs-theme");else de.setAttribute("data-gs-theme",v);
   var b=document.getElementById("gs-theme-btn");
   if(b){b.textContent=ICON[v];b.title="\\uD654\\uBA74 \\uBC1D\\uAE30: "+NAME[v]+" (\\uB20C\\uB7EC\\uC11C \\uBC14\\uAFC8)";}
 }
 apply(get());                       // 그려지기 전에 테마부터 맞춘다
 // 다른 탭·부모 창에서 바꾸면 이 문서도 따라간다(iframe 포함)
 window.addEventListener("storage",function(e){if(e.key===K)apply(get())});
 function mount(){
   if(window.self!==window.top)return;   // iframe 안에서는 버튼을 안 만든다
   var b=document.createElement("button");
   b.id="gs-theme-btn";b.type="button";b.setAttribute("aria-label","\\uD654\\uBA74 \\uBC1D\\uAE30 \\uBC14\\uAFC8");
   b.onclick=function(){
     var v=ORDER[(ORDER.indexOf(get())+1)%ORDER.length];
     try{localStorage.setItem(K,v)}catch(e){}
     apply(v);
   };
   document.body.appendChild(b);apply(get());
 }
 if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",mount);
 else mount();
})();
</script>"""


def uses_theme(html: str) -> bool:
    """렌더러가 `var(--gs-*)` 로 색을 적었는가 = 이 테마 대상인가."""
    return USES_THEME in html


def inject(html: str) -> str:
    """<head> 바로 뒤에 변수·버튼 스타일을, </body> 앞에 토글 스크립트를 넣는다.

    스타일을 먼저 넣는 이유: 변수가 없으면 첫 페인트에서 폴백 색(다크)이 번쩍인다.
    """
    if MARKER in html or not uses_theme(html):
        return html
    low = html.lower()
    head = low.find("<head")
    if head >= 0:
        close = html.find(">", head)
        if close >= 0:
            html = html[: close + 1] + STYLE + html[close + 1 :]
        else:
            html = STYLE + html
    else:
        html = STYLE + html
    end = html.lower().rfind("</body>")
    if end >= 0:
        return html[:end] + SCRIPT + html[end:]
    return html + SCRIPT


def apply_to_tree(root: Path) -> int:
    """배포 디렉터리 안의 .html 중 테마를 쓰는 페이지에 적용. 적용 개수를 돌려준다."""
    count = 0
    for path in sorted(root.rglob("*.html")):
        try:
            html = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        new = inject(html)
        if new != html:
            count += 1
            path.write_text(new, encoding="utf-8")
    return count
