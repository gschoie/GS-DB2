"""배포본 전 페이지에 비밀번호 잠금을 끼워 넣는다.

GitHub Pages는 정적 호스팅이라 **서버에서 막을 방법이 없다**. 여기 잠금은
브라우저에서 도는 가림막이다 — 주소를 아는 사람이 개발자 도구로 소스를 뜨거나
data/JSON 파일을 직접 받으면 내용은 보인다. 비밀번호도 솔트 붙인 SHA-256으로만
넣어 두지만 짧은 비밀번호는 대입으로 풀린다.

즉 "주소가 흘러도 아무나 클릭 한 번으로 보지는 못하게" 하는 정도의 장치다.
진짜 로그인 벽이 필요하면 Cloudflare Access 같은 앞단이 필요하다(2026-08 시도 →
OTP가 번거로워 원복, CLAUDE.md 9·11번 참고).

페이지마다 <head> 맨 앞에 넣으므로 그려지기 전에 가린다. iframe 안에서도 같은
오리진의 localStorage를 보므로, 부모 창이 풀려 있으면 다시 묻지 않는다.
"""

from __future__ import annotations

from pathlib import Path

# sha256("GS-DB2|" + 비밀번호). 비밀번호를 바꾸려면 이 값을 다시 계산해 넣는다:
#   python3 -c "import hashlib;print(hashlib.sha256(('GS-DB2|'+'새비번').encode()).hexdigest())"
PASSWORD_HASH = "4c9b36a88f5d4509867ff909411501386428b8785635c8d759e34742792dda86"
SALT = "GS-DB2|"
STORE_KEY = "gs_gate_v1"
REMEMBER_DAYS = 30
MARKER = "<!--gs-gate-->"

SNIPPET = """<!--gs-gate--><script>
(function(){
 var H="__HASH__",SALT="__SALT__",K="__KEY__",MS=__DAYS__*864e5;
 function get(){try{var v=JSON.parse(localStorage.getItem(K)||"null");
   return v&&v.h===H&&Date.now()-v.t<MS}catch(e){return false}}
 function set(){try{localStorage.setItem(K,JSON.stringify({h:H,t:Date.now()}))}catch(e){}}
 async function digest(s){
   var b=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(s));
   return [].map.call(new Uint8Array(b),function(x){return x.toString(16).padStart(2,"0")}).join("")}
 if(get())return;                                   // 이미 푼 브라우저는 그대로 통과
 // crypto.subtle 은 https/localhost 에서만 있다. 없으면(평문 http·file://) 대조가
 // 불가능하므로 잠그지 않고 통과시킨다 — 못 들어가게 막는 것보다 낫다.
 if(!(window.crypto&&crypto.subtle))return;
 var de=document.documentElement;de.style.visibility="hidden";  // 그려지기 전에 가림
 function show(){
   // 문서는 계속 숨긴 채 가림막만 보이게 둔다(내용이 아예 안 그려진다).
   var w=document.createElement("div");
   w.setAttribute("style","visibility:visible;position:fixed;inset:0;z-index:2147483647;background:#f7f7f5;"+
     "display:flex;align-items:center;justify-content:center;padding:24px;"+
     "font-family:Pretendard,'Apple SD Gothic Neo','Malgun Gothic',sans-serif");
   w.innerHTML='<form style="background:#fff;border:1px solid #ededeb;border-radius:12px;'+
     'padding:28px 26px;width:min(340px,100%);box-shadow:0 10px 40px rgba(17,24,39,.08)">'+
     '<div style="font-size:13px;letter-spacing:.12em;color:#9ca3af;font-weight:700">GS RESEARCH DESK</div>'+
     '<h1 style="margin:6px 0 16px;font-size:20px;font-weight:800;color:#111827">비밀번호를 넣어 주세요</h1>'+
     '<input type="password" autocomplete="current-password" autofocus '+
     'style="width:100%;box-sizing:border-box;border:1px solid #ededeb;border-radius:8px;'+
     'padding:12px 13px;font-size:15px;font-family:inherit;color:#111827;background:#fff">'+
     '<p style="margin:9px 2px 0;min-height:18px;font-size:12.5px;color:#bd4335"></p>'+
     '<button type="submit" style="margin-top:12px;width:100%;border:0;border-radius:8px;'+
     'background:#2383e2;color:#fff;font:700 15px/1 inherit;padding:13px;cursor:pointer">들어가기</button>'+
     '<p style="margin:14px 2px 0;font-size:11.5px;color:#9ca3af;line-height:1.5">'+
     '이 기기에서는 __DAYS__일 동안 다시 묻지 않습니다.</p></form>';
   document.body.appendChild(w);
   var f=w.querySelector("form"),i=w.querySelector("input"),msg=w.querySelector("p");
   f.addEventListener("submit",async function(e){
     e.preventDefault();
     var h=await digest(SALT+i.value);
     if(h===H){set();location.reload();return}
     msg.textContent="비밀번호가 맞지 않습니다.";i.value="";i.focus()});
   i.focus()}
 if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",show);
 else show();
})();
</script>"""


def snippet() -> str:
    return (SNIPPET.replace("__HASH__", PASSWORD_HASH).replace("__SALT__", SALT)
            .replace("__KEY__", STORE_KEY).replace("__DAYS__", str(REMEMBER_DAYS)))


def inject(html: str) -> str:
    """<head> 바로 뒤(없으면 맨 앞)에 끼운다. 이미 들어 있으면 그대로 둔다."""
    if MARKER in html:
        return html
    block = snippet()
    low = html.lower()
    head = low.find("<head")
    if head >= 0:
        close = html.find(">", head)
        if close >= 0:
            return html[: close + 1] + block + html[close + 1 :]
    return block + html


def apply_to_tree(root: Path) -> int:
    """배포 디렉터리 안의 .html 전부에 적용하고 손본 개수를 돌려준다."""
    count = 0
    for path in sorted(root.rglob("*.html")):
        try:
            html = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        new = inject(html)
        if new != html:
            path.write_text(new, encoding="utf-8")
            count += 1
    return count
