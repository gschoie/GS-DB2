"""배포본 전 페이지에 비밀번호 잠금을 끼워 넣는다.

비밀번호는 두 가지다.
  - **주인 비번**: 모든 화면. 사이드바가 있는 대시보드(index.html)와 팀원 개인정보가
    담긴 세 페이지(휴가·근태·발간계획)는 이 비번으로만 열린다.
  - **공유 비번**: 친구에게 주소를 줄 때 쓰는 비번. 리포트·브리핑 페이지만 열리고
    대시보드와 팀원 페이지는 막힌다.

GitHub Pages는 정적 호스팅이라 **서버에서 막을 방법이 없다**. 여기 잠금은
브라우저에서 도는 가림막이다 — 주소를 아는 사람이 개발자 도구로 소스를 뜨거나
data/JSON 파일을 직접 받으면 내용은 보인다. 비밀번호도 솔트 붙인 SHA-256으로만
넣어 두지만 짧은 비밀번호는 대입으로 풀린다. 공유 비번을 받은 친구가 주인 쪽
페이지를 억지로 보려 들면 막을 수 없다는 뜻이기도 하다.

즉 "주소가 흘러도 아무나 클릭 한 번으로 보지는 못하게" + "친구에게는 리포트만"
정도의 장치다. 진짜 로그인 벽이 필요하면 Cloudflare Access 같은 앞단이 필요하다
(2026-08 시도 → OTP가 번거로워 원복, CLAUDE.md 9·11번 참고).

페이지마다 <head> 맨 앞에 넣으므로 그려지기 전에 가린다. iframe 안에서도 같은
오리진의 localStorage를 보므로, 부모 창이 풀려 있으면 다시 묻지 않는다.
"""

from __future__ import annotations

from pathlib import Path

# sha256("GS-DB2|" + 비밀번호). 비밀번호를 바꾸려면 이 값을 다시 계산해 넣는다:
#   python3 -c "import hashlib;print(hashlib.sha256(('GS-DB2|'+'새비번').encode()).hexdigest())"
OWNER_HASH = "4c9b36a88f5d4509867ff909411501386428b8785635c8d759e34742792dda86"  # qwer1009
GUEST_HASH = "d17e494562f94f74f2a7d0397c1138f2524bd9ed47860e82f639334dab1b476a"  # guest1009
SALT = "GS-DB2|"
STORE_KEY = "gs_gate_v1"
REMEMBER_DAYS = 30
MARKER = "<!--gs-gate-->"

# 주인 비번으로만 열리는 페이지. index.html 은 사이드바가 있는 대시보드 본체라
# 여기 하나로 메뉴 전체가 가려진다. 나머지 셋은 팀원 이름·일정이 그대로 보인다.
OWNER_ONLY_PAGES = {
    "index.html",
    "vacation_report.html",
    "attendance_report.html",
    "indepth_report.html",
}

SNIPPET = """<!--gs-gate--><script>
(function(){
 var OH="__OWNER__",GH="__GUEST__",OWNER=__OWNERONLY__,SALT="__SALT__",K="__KEY__",MS=__DAYS__*864e5;
 // 저장된 값에서 등급을 읽는다: 주인이면 'owner', 친구면 'guest', 없거나 만료면 null.
 function level(){try{var v=JSON.parse(localStorage.getItem(K)||"null");
   if(!v||Date.now()-v.t>=MS)return null;
   return v.h===OH?"owner":v.h===GH?"guest":null}catch(e){return null}}
 function set(h){try{localStorage.setItem(K,JSON.stringify({h:h,t:Date.now()}))}catch(e){}}
 async function digest(s){
   var b=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(s));
   return [].map.call(new Uint8Array(b),function(x){return x.toString(16).padStart(2,"0")}).join("")}
 var lv=level();
 if(lv==="owner")return;                 // 주인은 전부 통과
 if(lv==="guest"&&!OWNER)return;         // 친구는 공유 페이지만 통과
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
     (OWNER?"이 화면은 주인 비밀번호가 필요합니다. ":"")+
     '이 기기에서는 __DAYS__일 동안 다시 묻지 않습니다.</p></form>';
   document.body.appendChild(w);
   var f=w.querySelector("form"),i=w.querySelector("input"),msg=w.querySelector("p");
   f.addEventListener("submit",async function(e){
     e.preventDefault();
     var h=await digest(SALT+i.value);
     if(h===OH||(h===GH&&!OWNER)){set(h);location.reload();return}
     msg.textContent=h===GH?"공유용 비밀번호로는 이 화면을 볼 수 없습니다."
                           :"비밀번호가 맞지 않습니다.";
     i.value="";i.focus()});
   i.focus()}
 if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",show);
 else show();
})();
</script>"""


def snippet(owner_only: bool = False) -> str:
    return (SNIPPET.replace("__OWNER__", OWNER_HASH).replace("__GUEST__", GUEST_HASH)
            .replace("__OWNERONLY__", "true" if owner_only else "false")
            .replace("__SALT__", SALT).replace("__KEY__", STORE_KEY)
            .replace("__DAYS__", str(REMEMBER_DAYS)))


def is_owner_only(relative_path: str) -> bool:
    """배포 디렉터리 기준 상대경로가 주인 전용 페이지인지."""
    parts = relative_path.replace("\\", "/").split("/")
    if len(parts) == 1 and parts[0] in OWNER_ONLY_PAGES:
        return True
    # 하위 폴더의 index.html 은 브리핑 모음 같은 공유 대상이라 주인 전용이 아니다.
    return parts[-1] in OWNER_ONLY_PAGES - {"index.html"}


def inject(html: str, owner_only: bool = False) -> str:
    """<head> 바로 뒤(없으면 맨 앞)에 끼운다. 이미 들어 있으면 그대로 둔다."""
    if MARKER in html:
        return html
    block = snippet(owner_only)
    low = html.lower()
    head = low.find("<head")
    if head >= 0:
        close = html.find(">", head)
        if close >= 0:
            return html[: close + 1] + block + html[close + 1 :]
    return block + html


def apply_to_tree(root: Path) -> tuple[int, int]:
    """배포 디렉터리 안의 .html 전부에 적용. (전체, 주인전용) 개수를 돌려준다."""
    count = owner = 0
    for path in sorted(root.rglob("*.html")):
        try:
            html = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        owner_only = is_owner_only(str(path.relative_to(root)))
        new = inject(html, owner_only)
        if new != html:
            count += 1
            owner += owner_only
            path.write_text(new, encoding="utf-8")
    return count, owner
