/* 애널리스트 집계 — 뼈대. data.json(명단) + 결정적 난수 일정으로 원본 화면 구조를 재현한다.
   실데이터 연결 지점은 loadData()/genEvents() 둘뿐이다. */
(function(){
'use strict';
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const n0=n=>n.toLocaleString('ko-KR');
const pad=n=>String(n).padStart(2,'0');
const iso=d=>`${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
const parseIso=s=>{const [y,m,d]=s.split('-').map(Number);return new Date(y,m-1,d);};
const addD=(d,n)=>{const x=new Date(d);x.setDate(x.getDate()+n);return x;};
const mondayOf=d=>{const x=new Date(d);const w=(x.getDay()+6)%7;x.setDate(x.getDate()-w);return x;};
const DOW=['일','월','화','수','목','금','토'];
const todayIso=()=>iso(new Date());
const KIND={sem:'세미나',corp:'기업',ndr:'NDR',etc:'기타',cday:'콥데이'};
const TABS=[['upd','⟳ 업데이트'],['sum','요약'],['pub','발간 실적'],['sem','세미나 실적'],['call','콜'],['req','리퀘'],['sup','사내지원'],['ndr','NDR'],['cday','콥데이'],['cov','커버리지'],['drop','드랍 경고'],['pvp','발간 vs 계획'],['idx','인뎁스 달력'],['inst','기관별 집계'],['miss','누락 후보']];

let D=null, EV=[], AN=[], sel=new Set();
let page=localStorage.getItem('ana_page')||'cal', view=localStorage.getItem('ana_view')||'month', mode='ledger';
let cursor=new Date(); cursor.setHours(0,0,0,0);
let tab=localStorage.getItem('ana_tab')||'sum', unlocked=false, q='';

/* ───── 데이터 ───── */
async function loadData(){
  const r=await fetch('data.json',{cache:'no-store'});
  D=await r.json();
  AN=D.analysts;
  AN.forEach(a=>sel.add(a.name));
  EV=genEvents();
}
// 결정적 난수(xorshift) — 같은 명단이면 늘 같은 샘플
function rng(seed){let x=seed>>>0||1;return()=>{x^=x<<13;x>>>=0;x^=x>>>17;x^=x<<5;x>>>=0;return x/4294967296;};}
function genEvents(){
  const out=[]; const r=rng(20261107);
  const y=D.year; const start=new Date(y,0,1), end=new Date(y,11,31);
  const inst=D.institutions, mgr=['김민수','이서연','박지훈','최유진','정우성','한지민','오세훈','윤아름','1명','2명'];
  const topics=['3Q 실적 리뷰','업황 점검','탑픽 교체','수급 점검','신규 커버리지','정기 세미나','기업현황 업데이트','퀀트 정기 세미나','NDR(복수기관)','IPO 준비'];
  let id=0;
  for(let d=new Date(start); d<=end; d=addD(d,1)){
    const w=d.getDay(); if(w===0||w===6) continue;
    AN.forEach(a=>{
      const base=a.part==='strat'?0.35:0.28;
      let k=0; while(r()<base&&k<3){
        const p=r();
        const kind=p<0.62?'sem':p<0.72?'ndr':p<0.80?'corp':p<0.86?'cday':'etc';
        const h=9+Math.floor(r()*8), mi=[0,30,15,45][Math.floor(r()*4)];
        const org=inst[Math.floor(r()*inst.length)], who=mgr[Math.floor(r()*mgr.length)];
        const chk=kind==='etc'?r()<0.8:r()<0.06;
        const title=kind==='sem'?`${org} ${who}`:kind==='ndr'?`${org} 외 ${1+Math.floor(r()*4)}곳`:kind==='cday'?`${['3Q26 온라인 준비','콥데이 ','기업설명회 '][Math.floor(r()*3)]}${org}`:kind==='corp'?`${org} 탐방`:['법인 AI','전체회의','면접','공부날: 인뎁스','외근','센터장님'][Math.floor(r()*6)];
        out.push({id:'e'+(id++),date:iso(d),time:`${pad(h)}:${pad(mi)}`,an:a.name,kind,title,org:kind==='etc'?'':org,who,
          memo:`-${a.sector} ${topics[Math.floor(r()*topics.length)]}-`,check:chk,ledger:!chk&&!a.ledgerExcluded,
          why:chk?(kind==='etc'?'기관을 알 수 없음(기업명일 수도 있음)':'점심 시간 일정 — 세미나인지 확인(애널리스트 규칙)'):''});
        k++;
      }
    });
  }
  return out;
}
const anOf=n=>AN.find(a=>a.name===n)||{color:'#999'};
const visible=e=>sel.has(e.an)&&(mode==='all'||e.ledger||e.check)&&(!q||(e.title+e.org+e.who+e.memo+e.an).toLowerCase().includes(q));
const evSort=(a,b)=>a.date.localeCompare(b.date)||a.time.localeCompare(b.time)||a.an.localeCompare(b.an);
function byDate(){const m={};EV.filter(visible).sort(evSort).forEach(e=>(m[e.date]=m[e.date]||[]).push(e));return m;}

/* ───── 공통 UI ───── */
function toast(t){const el=$('#toast');el.textContent=t;el.classList.add('on');clearTimeout(toast._t);toast._t=setTimeout(()=>el.classList.remove('on'),1800);}
function showModal(html){$('#modal').innerHTML=`<button class="x" id="mx" aria-label="닫기">✕</button>`+html;$('#overlay').classList.add('on');$('#mx').onclick=closeModal;}
function closeModal(){$('#overlay').classList.remove('on');}
$('#overlay').addEventListener('click',e=>{if(e.target.id==='overlay')closeModal();});
document.addEventListener('keydown',e=>{
  if(e.key==='Escape')return closeModal();
  if(e.target.matches('input,select,textarea'))return;
  if(e.key==='ArrowLeft'||e.key==='ArrowRight'){
    const dir=e.key==='ArrowLeft'?-1:1;
    if(page==='cal')navStep(dir); else {const i=TABS.findIndex(t=>t[0]===tab);setTab(TABS[(i+dir+TABS.length)%TABS.length][0]);}
  }
});
function setPage(p){page=p;localStorage.setItem('ana_page',p);document.body.classList.toggle('dash',p==='dash');$('#pgDash').classList.toggle('on',p==='dash');$('#pgCal').classList.toggle('on',p==='cal');if(p==='dash')drawDash();else render();}
$('#pgDash').onclick=()=>setPage('dash');$('#pgCal').onclick=()=>setPage('cal');
$('#sideBtn').onclick=()=>{if(matchMedia('(max-width:900px)').matches)document.body.classList.toggle('sideopen');else document.body.classList.toggle('sidehide');};
$('#scrim').onclick=()=>document.body.classList.remove('sideopen');
$('#lockBtn').onclick=()=>{unlocked=!unlocked;applyLock();toast(unlocked?'편집 잠금 해제(뼈대: 비번 없음)':'편집 잠금');};
function applyLock(){const b=$('#lockBtn');b.textContent=unlocked?'🔓 편집 중':'🔒 편집 잠금';b.classList.toggle('on',unlocked);$('#roBanner').classList.toggle('on',!unlocked&&page==='cal');$('#roBanner').textContent='읽기 전용 — 장부 넣기/빼기·설정 변경은 편집 잠금을 풀어야 합니다.';}
$('#setBtn').onclick=openSettings;
$('#xlsBtn').onclick=()=>toast('엑셀 내려받기는 뼈대에서 미구현');
$('#pdfBtn').onclick=()=>window.print();
$('#upBtn').onclick=()=>toast('자료 올리기는 뼈대에서 미구현');

/* ───── 일정 화면 ───── */
function navStep(dir){if(view==='month'){cursor=new Date(cursor.getFullYear(),cursor.getMonth()+dir,1);}else{cursor=addD(cursor,7*dir);}render();}
$('#prevBtn').onclick=()=>navStep(-1);$('#nextBtn').onclick=()=>navStep(1);
$('#todayBtn').onclick=()=>{cursor=new Date();cursor.setHours(0,0,0,0);render();};
$('#vMonth').onclick=()=>setView('month');$('#vWeek').onclick=()=>setView('week');$('#vList').onclick=()=>setView('list');
function setView(v){view=v;localStorage.setItem('ana_view',v);render();}
$('#mLedger').onclick=()=>{mode='ledger';render();};$('#mAll').onclick=()=>{mode='all';render();};
$('#evSearch').oninput=e=>{q=e.target.value.trim().toLowerCase();render();};
$('#selAll').onclick=()=>{AN.forEach(a=>sel.add(a.name));render();};
$('#selNone').onclick=()=>{sel.clear();render();};
$('#sideSearch').oninput=renderSide;
$('#ckBtn').onclick=openChecks;

function render(){
  ['vMonth','vWeek','vList'].forEach(id=>$('#'+id).classList.toggle('on',id==='v'+view[0].toUpperCase()+view.slice(1)));
  $('#mLedger').classList.toggle('on',mode==='ledger');$('#mAll').classList.toggle('on',mode==='all');
  const cnt=EV.filter(visible).length;
  const mLbl=`${cursor.getFullYear()}년 ${cursor.getMonth()+1}월`;
  $('#calHead').innerHTML=esc(mLbl)+(view==='list'?`<small>${n0(EV.filter(visible).filter(e=>e.date.startsWith(iso(cursor).slice(0,7))).length)}건</small>`:'');
  $('#viewBar').textContent=mode==='ledger'?'장부에 들어가는 일정만 표시 중(점선 = 확인 필요)':'빠진 일정까지 전체 표시 중(점선 = 확인 필요)';
  const need=EV.filter(e=>e.check).length;$('#ckLbl').textContent=`확인 필요 ${n0(need)}건`;
  renderSide();renderMini();
  const box=$('#viewBox');
  if(view==='month')box.innerHTML=renderMonth();else if(view==='week')box.innerHTML=renderWeek();else box.innerHTML=renderAgenda();
  bindChips(box);applyLock();
}
function evChip(e,opt={}){
  const a=anOf(e.an);
  return `<div class="ev ${e.check?'chk':''} ${opt.week?'wkev':''} ${e.kind==='cday'?'cdy':''}" data-id="${e.id}" style="--c:${a.color}" title="${esc(e.title+' · '+e.an)}">
    <span class="dot"></span><span class="tm">${e.time}</span><span class="k ${e.kind}">[${KIND[e.kind]}]</span><span class="t">${esc(e.title)}</span>${e.check?'<span class="ck">확인</span>':''}${e.kind==='cday'?'<span class="ck" style="color:#fff">콥데이</span>':''}
    ${opt.week?`<span class="who">${esc(e.an)}</span>`:''}</div>`;
}
function renderMonth(){
  const m=byDate(); const first=new Date(cursor.getFullYear(),cursor.getMonth(),1), last=new Date(cursor.getFullYear(),cursor.getMonth()+1,0);
  let d=mondayOf(first); const t=todayIso(); let cells='';
  const endW=mondayOf(last); const weeks=Math.round((endW-d)/864e5/7)+1;
  for(let w=0;w<weeks;w++){
    for(let i=0;i<5;i++){
      const dd=addD(d,w*7+i), k=iso(dd), list=m[k]||[]; const cur=dd.getMonth()===cursor.getMonth();
      const lbl=(dd.getDate()===1||(w===0&&i===0))?`${dd.getMonth()+1}월 ${dd.getDate()}`:String(dd.getDate());
      cells+=`<div class="cell ${cur?'cur':''} ${k===t?'today':''}" data-date="${k}"><div class="dn"><span>${lbl}</span></div>${list.slice(0,4).map(e=>evChip(e)).join('')}${list.length>4?`<button class="more" data-day="${k}">${list.length-4}개 더보기</button>`:''}</div>`;
    }
  }
  return `<div class="cal" style="--cols:5"><div class="dh">${['월','화','수','목','금'].map(x=>`<div>${x}</div>`).join('')}</div><div class="grid">${cells}</div></div>`;
}
function renderWeek(){
  const m=byDate(); const d=mondayOf(cursor), t=todayIso(); let head='',cells='';
  for(let i=0;i<5;i++){const dd=addD(d,i),k=iso(dd);head+=`<div>${DOW[dd.getDay()]}<br><span class="big" style="font-size:24px;color:var(--ink)">${dd.getDate()}</span></div>`;
    cells+=`<div class="cell wk ${k===t?'today':''}" data-date="${k}">${(m[k]||[]).map(e=>evChip(e,{week:true})).join('')||'<div class="empty">일정 없음</div>'}</div>`;}
  return `<div class="cal" style="--cols:5"><div class="dh">${head}</div><div class="grid">${cells}</div></div>`;
}
function renderAgenda(){
  const m=byDate(); const ym=iso(cursor).slice(0,7); const days=Object.keys(m).filter(k=>k.startsWith(ym)).sort();
  if(!days.length)return `<div class="agenda"><div class="empty">이 달에 표시할 일정이 없습니다.</div></div>`;
  return `<div class="agenda">${days.map(k=>{const dd=parseIso(k);return `<div class="aday"><div class="dl"><b>${dd.getDate()}</b><span>${dd.getMonth()+1}월, ${DOW[dd.getDay()]}</span></div><div class="rows">${m[k].map(e=>{const a=anOf(e.an);return `<div class="arow2 ev" data-id="${e.id}" style="--c:${a.color}"><span class="tm">${e.time}</span><span class="dot"></span><span class="badge ${e.check?'need':'ledger'}">${e.check?'확인 필요':e.ledger?'장부':'제외'}</span><span class="tt"><span class="k ${e.kind}" style="color:var(--k-${e.kind})">[${KIND[e.kind]}]</span><b>${esc(e.title)}</b><small>${esc(e.check?e.why:e.memo)}</small></span><span class="an">${esc(e.an)}</span></div>`;}).join('')}</div></div>`;}).join('')}</div>`;
}
function bindChips(root){
  $$('.ev[data-id]',root).forEach(el=>el.onclick=()=>openEvent(el.dataset.id));
  $$('.more',root).forEach(b=>b.onclick=()=>openDay(b.dataset.day));
}
function renderSide(){
  const qq=($('#sideSearch').value||'').trim();
  const list=$('#sideList'); const cntAll={},cntChk={};
  EV.forEach(e=>{cntAll[e.an]=(cntAll[e.an]||0)+1;if(e.check)cntChk[e.an]=(cntChk[e.an]||0)+1;});
  list.innerHTML=AN.filter(a=>!qq||a.name.includes(qq)).map(a=>`<div class="arow ${sel.has(a.name)?'on':''} ${a.ledgerExcluded?'excl':''}" data-an="${esc(a.name)}" style="--c:${a.color}"><span class="cb">${sel.has(a.name)?'✓':''}</span><span class="nm">${esc(a.name)}</span><span class="ct">${a.ledgerExcluded?'장부 제외 ':''}${n0(cntAll[a.name]||0)}${cntChk[a.name]?` · <b>!${n0(cntChk[a.name])}</b>`:''}</span></div>`).join('');
  $$('.arow',list).forEach(el=>el.onclick=()=>{const n=el.dataset.an;sel.has(n)?sel.delete(n):sel.add(n);render();});
  $('#sideCnt').textContent=`${sel.size}/${AN.length}명`;
  $('#sideInfo').innerHTML=`샘플 데이터 ${n0(EV.length)}건 · ${D.year}년 평일 · 색점 = 애널리스트 색<br>원본은 구글 캘린더(ICS) 2종을 10분마다 읽어 분류합니다.`;
}
function renderMini(){
  const y=cursor.getFullYear(),mo=cursor.getMonth();const first=new Date(y,mo,1);const has=new Set(EV.filter(visible).map(e=>e.date));const t=todayIso();
  let d=addD(first,-first.getDay());let rows='';
  for(let w=0;w<6;w++){rows+='<tr>';for(let i=0;i<7;i++){const dd=addD(d,w*7+i),k=iso(dd);rows+=`<td class="${dd.getMonth()!==mo?'dim':''} ${k===t?'today':''} ${has.has(k)?'has':''}" data-date="${k}"><span>${dd.getDate()}</span></td>`;}rows+='</tr>';}
  $('#mini').innerHTML=`<div class="mh"><span>${y}년 ${mo+1}월</span><button id="mPrev">‹</button><button id="mNext">›</button></div><table><tr>${DOW.map(x=>`<th>${x}</th>`).join('')}</tr>${rows}</table>`;
  $('#mPrev').onclick=()=>{cursor=new Date(y,mo-1,1);render();};$('#mNext').onclick=()=>{cursor=new Date(y,mo+1,1);render();};
  $$('#mini td').forEach(td=>td.onclick=()=>{cursor=parseIso(td.dataset.date);if(view==='month')cursor=new Date(cursor.getFullYear(),cursor.getMonth(),1);render();if(view==='month')openDay(td.dataset.date);});
}
function openEvent(id){
  const e=EV.find(x=>x.id===id);if(!e)return;const a=anOf(e.an);const dd=parseIso(e.date);
  showModal(`<h2><span style="color:${a.color}">●</span> ${esc(e.title)} <small>${e.date}(${DOW[dd.getDay()]}) ${e.time}</small></h2>
  <dl class="kv"><dt>분류</dt><dd><span class="k ${e.kind}">[${KIND[e.kind]}]</span> ${e.check?'<span class="badge need">확인 필요</span> '+esc(e.why):e.ledger?'<span class="badge ledger">장부</span> 장부에 들어가는 일정':'장부 제외'}</dd>
  <dt>담당</dt><dd>${esc(e.an)} · ${esc(a.dept)} · ${esc(a.sector)}</dd><dt>기관</dt><dd>${esc(e.org||'—')}${e.who?' · '+esc(e.who):''}</dd><dt>메모</dt><dd>${esc(e.memo)}</dd></dl>
  <div style="display:flex;gap:8px;margin-top:10px"><button class="primary" id="mLed" ${unlocked?'':'disabled'}>${e.ledger?'장부에서 빼기':'장부에 넣기'}</button><button class="ghost" id="mAn" ${unlocked?'':'disabled'}>담당 바꾸기</button><span class="hint2" style="align-self:center">${unlocked?'':'편집 잠금을 풀면 바꿀 수 있습니다'}</span></div>`);
  $('#mLed').onclick=()=>{e.ledger=!e.ledger;e.check=false;closeModal();render();toast('저장(뼈대: 새로고침하면 되돌아감)');};
  $('#mAn').onclick=()=>{const n=prompt('담당 애널리스트 이름',e.an);if(n&&AN.some(a=>a.name===n)){e.an=n;closeModal();render();}};
}
function openDay(k){
  const list=(byDate()[k]||[]);const dd=parseIso(k);
  showModal(`<h2>${dd.getMonth()+1}월 ${dd.getDate()}일 (${DOW[dd.getDay()]}) <small>${list.length}건</small></h2><div class="agenda" style="border:none;padding:0">${list.map(e=>{const a=anOf(e.an);return `<div class="arow2 ev" data-id="${e.id}" style="--c:${a.color}"><span class="tm">${e.time}</span><span class="dot"></span><span class="badge ${e.check?'need':'ledger'}">${e.check?'확인 필요':'장부'}</span><span class="tt"><span class="k" style="color:var(--k-${e.kind})">[${KIND[e.kind]}]</span><b>${esc(e.title)}</b><small>${esc(e.memo)}</small></span><span class="an">${esc(e.an)}</span></div>`;}).join('')||'<div class="empty">일정 없음</div>'}</div>`);
  bindChips($('#modal'));
}
function openChecks(){
  const list=EV.filter(e=>e.check&&sel.has(e.an)).sort(evSort).filter(e=>e.date>=iso(addD(new Date(),-21)));
  showModal(`<h2>확인 필요 <small>${n0(list.length)}건</small></h2><p class="sub">규칙으로 판정하지 못한 일정입니다. 눌러서 장부에 넣거나 빼 주세요(편집 잠금해제 필요).</p>
  ${list.slice(0,80).map(e=>{const a=anOf(e.an);const dd=parseIso(e.date);return `<div class="ckrow" data-id="${e.id}" style="--c:${a.color}"><span>${dd.getMonth()+1}/${dd.getDate()}(${DOW[dd.getDay()]})</span><span class="an">${esc(e.an)}</span><span>${esc(e.title)}<span class="why">${esc(e.why)}</span></span><span class="act2"><button class="ghost" data-op="in" ${unlocked?'':'disabled'}>장부</button><button class="ghost danger" data-op="out" ${unlocked?'':'disabled'}>빼기</button></span></div>`;}).join('')}${list.length>80?`<div class="empty">… 외 ${n0(list.length-80)}건</div>`:''}`);
  $$('.ckrow',$('#modal')).forEach(r=>{r.onclick=ev=>{const b=ev.target.closest('button');const e=EV.find(x=>x.id===r.dataset.id);if(b){e.check=false;e.ledger=b.dataset.op==='in';r.remove();render();}else openEvent(e.id);};});
}
function openSettings(){
  showModal(`<h2>⚙ 연결·설정</h2>
  <div class="setsec"><h3>① 구글 캘린더 연결 <span class="tag">뼈대</span></h3><p>구글 캘린더 → 설정 → 왼쪽 <b>애널 일정</b> → '캘린더 통합'의 <b>비공개 주소(iCal 형식)</b>를 복사해 붙여 넣으세요. 원본은 서버(Worker)가 10분 간격으로 읽어 분류합니다 — 뼈대는 정적 페이지라 저장되지 않습니다.</p>
  <div class="row"><input type="text" placeholder="https://calendar.google.com/calendar/ical/…/basic.ics"><button class="primary">연결</button><button class="ghost danger">연결 해제</button></div>
  <h3 style="margin-top:10px">DAOL 탐방 캘린더</h3><p>같은 방법으로 <b>DAOL 탐방</b> 캘린더의 비공개 주소를 넣으면 그 일정을 모두 <b>탐방(동반)</b>으로 분류해 장부에 더합니다.</p>
  <div class="row"><input type="text" placeholder="https://calendar.google.com/calendar/ical/…/basic.ics"><button class="primary">연결</button><button class="ghost danger">연결 해제</button></div></div>
  <div class="setsec"><h3>② 기관명 분류 <span class="tag">${n0(D.institutions.length)}곳(샘플)</span></h3><p>기관명 분류.xlsx(소속기관·성명·최종 수정일)를 올리면 매니저 이름으로 기관을 정합니다.</p><div class="row"><input type="file" disabled><button class="primary" disabled>올리기</button></div></div>
  <div class="setsec"><h3>③ 애널리스트 설정</h3><p>부서와 '내용 앞말'(예: 조기방 → -조기방 세미나-). 장부 제외에 체크하면 그 사람 일정은 장부에 넣지 않습니다.</p>
  <table><tr><th>애널리스트</th><th>부서</th><th>내용 앞말(섹터)</th><th>장부 제외</th><th>규칙</th></tr>${AN.map(a=>`<tr><td><span style="color:${a.color}">●</span> ${esc(a.name)}</td><td><input type="text" value="${esc(a.dept)}"></td><td><input type="text" value="${esc(a.sector)}"></td><td><input type="checkbox" ${a.ledgerExcluded?'checked':''}></td><td><button class="ghost">규칙 —</button></td></tr>`).join('')}</table></div>`);
}

/* ───── 업무 집계 ───── */
const MONTHS=[...Array(12)].map((_,i)=>i+1);
function counts(kind,year,fn){ // {name:{m:n}}
  const m={};AN.forEach(a=>m[a.name]={});
  EV.forEach(e=>{if(!e.date.startsWith(String(year)))return;if(fn?!fn(e):e.kind!==kind)return;if(!e.ledger&&!e.check)return;const mo=+e.date.slice(5,7);m[e.an][mo]=(m[e.an][mo]||0)+1;});
  return m;
}
function drawDash(){
  $('#dashUpdated').textContent=D.update_log.last_input;
  const s=$('#dashAn');if(s.options.length===1)AN.forEach(a=>{const o=document.createElement('option');o.value=o.textContent=a.name;s.appendChild(o);});
  $('#updBar').innerHTML=`사이트 업데이트 반영: ${D.update_log.areas.map(a=>esc(a.split(' · ')[0])).join(' · ')} <span class="hint2">(샘플)</span>`;
  $('#dashTabs').innerHTML=TABS.map(([k,l])=>`<button data-tab="${k}" class="${k===tab?'on':''} ${k==='upd'?'upd':''}">${l}</button>`).join('');
  $$('#dashTabs button').forEach(b=>b.onclick=()=>setTab(b.dataset.tab));
  const body=$('#dashBody');
  const f={upd:secUpd,sum:secSum,pub:()=>secMonthly('발간 실적','보고서 발간 건수입니다. 기업 = ②발간자료(기업분석) 줄 수, 산업·Weekly = ③산업자료·③투자전략자료.','corp',['전체','기업','기업(인뎁스)','산업','산업(인뎁스)','Weekly·Daily'],e=>e.kind==='corp'||e.kind==='etc'),
    sem:()=>secMonthly('세미나 실적','④영업활동 기록 건수입니다. 세미나 = 세미나1 + 국민연금(S1) + 우정사업본부(S2), NDR = 단독·단체 NDR. 링크공유는 뺐습니다.','sem',['세미나','국민연금(S1)','우정사업본부(S2)','NDR','콥데이','탐방','전체']),
    call:()=>secMonthly('콜','콜S·콜 기록 건수입니다(업데이트 파일 입력).','etc',['전체','콜S','콜']),
    req:()=>secMonthly('리퀘','리퀘스트S1·S2·리퀘스트 기록 건수입니다(업데이트 파일 입력).','etc',['전체','리퀘스트S1','리퀘스트S2','리퀘스트']),
    sup:()=>secMonthly('사내지원','타부서·계열사 지원 건수입니다(엑셀 \'타부서계열사지원\' 표 = 활동표 ④사내업무지원 칸). 올해 것만 있습니다.','etc',['사내지원'])+secSimple('경영진보고 — 월별',[['김지원',{6:2}],['박영도',{3:1,4:1,5:1,6:1,10:2}],['조병현',{3:2,6:3,7:1,10:1}]]),
    ndr:()=>`<div class="dropzone"><b>NDR 일정표 · '콥데이, NDR' 엑셀이나 일정표 사진을 여기에 끌어다 놓으세요</b><button class="primary" disabled>파일 고르기</button><small>여러 개 한 번에 · 연락처는 읽지 않음 · 사진은 글자를 읽어 확인 팝업을 띄운 뒤 등록 · 캡처는 Ctrl+V 로도 · 편집 비밀번호 — <b>뼈대: 미구현</b></small></div>`+secMonthly('NDR','NDR 건수입니다(같은 기업을 이어진 날에 돈 것을 한 건으로) — ④영업활동의 NDR 줄 + 위에 올린 NDR 일정표·장부 목록.','ndr',['NDR 전체','단독(NDR1)','단체(NDR2단체)'])+secInst(),
    cday:()=>secMonthly('콥데이','콥데이 건수입니다(기업·날짜마다 한 건) — 콥데이 캘린더 사이트 일정(담당 포함)과 엑셀 ④영업활동의 콥데이 줄을 같은 담당·같은 날로 맞대어 합쳤습니다.','cday',['콥데이 전체','엑셀에 있음','사이트에만','엑셀에만']),
    cov:secCov,drop:secDrop,pvp:secPvp,idx:()=>secTodo('인뎁스 달력','인뎁스 발간 계획을 달력 위에 올리는 탭. 이 리포의 <b>vacation_tracker/indepth.py</b>(📚 인뎁스.발간계획)가 같은 데이터를 이미 모으고 있어 그 state/indepth.json 을 읽으면 된다.'),
    inst:secInstTab,miss:secMiss}[tab];
  body.innerHTML=f?f():'';
  bindDash(body);
}
function setTab(k){tab=k;localStorage.setItem('ana_tab',k);drawDash();window.scrollTo({top:0});}
const yrChips=(y)=>[D.year,D.year-1,D.year-2].map(v=>`<button class="${v===y?'on':''}" data-y="${v}">${v}년</button>`).join('');
function tblHead(cols){return `<tr><th>애널리스트</th>${cols.map(c=>`<th>${c}</th>`).join('')}<th>합계</th></tr>`;}
function groupedRows(cnt,cols,fmt){
  const curM=new Date().getMonth()+1; let html='';
  D.parts.forEach(p=>{const ans=AN.filter(a=>a.part===p.id);html+=`<tr class="part"><td colspan="${cols.length+2}">${esc(p.name)}<small>${ans.length}명</small></td></tr>`;const sub=cols.map(()=>0);let subT=0;
    p.groups.forEach(g=>{const gs=ans.filter(a=>a.group===g);if(!gs.length)return;html+=`<tr class="grp"><td colspan="${cols.length+2}">${esc(g)}</td></tr>`;
      gs.forEach(a=>{const row=cnt[a.name]||{};let t=0;html+=`<tr><td class="nm" data-an="${esc(a.name)}">${esc(a.name)}${a.leader?' <span class="badge lead">팀장</span>':''}</td>`;cols.forEach((c,i)=>{const v=fmt?fmt(row,i):(row[i+1]||0);t+=v;sub[i]+=v;html+=`<td class="${v?'n':'z'} ${i+1>curM&&!fmt?'fut':''}" data-an="${esc(a.name)}" data-m="${i+1}">${v?n0(v):'·'}</td>`;});subT+=t;html+=`<td class="b"><b>${n0(t)}</b></td></tr>`;});});
    html+=`<tr class="sub"><td>${esc(p.name)} 소계</td>${sub.map(v=>`<td>${n0(v)}</td>`).join('')}<td>${n0(subT)}</td></tr>`;});
  const tot=cols.map((_,i)=>AN.reduce((s,a)=>s+((cnt[a.name]||{})[i+1]||0),0));
  html+=`<tr class="tot"><td>합계</td>${tot.map(v=>`<td>${n0(v)}</td>`).join('')}<td>${n0(tot.reduce((a,b)=>a+b,0))}</td></tr>`;
  return html;
}
function secMonthly(title,desc,kind,chips,fn){
  const y=secMonthly.y||D.year, qtr=secMonthly.q||false;
  const cnt=counts(kind,y,fn);
  let cols=MONTHS.map(m=>m+'월'), c2=cnt;
  if(qtr){cols=['1Q','2Q','3Q','4Q'];c2={};AN.forEach(a=>{c2[a.name]={};for(let qq=1;qq<=4;qq++)c2[a.name][qq]=[0,1,2].reduce((s,i)=>s+((cnt[a.name]||{})[(qq-1)*3+i+1]||0),0);});}
  return `<div class="card"><h2>${esc(title)} — ${y}년 ${qtr?'분기별':'월별'}</h2><p class="desc">${esc(desc)} 엑셀 원자료에서 직접 센 값이라 지난 연도도 볼 수 있습니다. <b>(뼈대: 샘플 일정으로 센 건수)</b></p>
  <div class="chips2">${yrChips(y)}<span class="sep"></span><button class="${qtr?'':'on'}" data-q="0">월별</button><button class="${qtr?'on':''}" data-q="1">분기별</button><span class="sep"></span>${chips.map((c,i)=>`<button class="${i===0?'on':''}">${esc(c)}</button>`).join('')}<label><input type="checkbox"> 구분별로 펼치기</label><span class="gsp"></span><span class="hint2">이름이나 숫자를 누르면 내역이 월별로 뜹니다</span></div>
  <table class="tb">${tblHead(cols)}${groupedRows(c2,cols)}</table><div class="foot">${new Date().getMonth()+1}월은 기준일까지 들어온 기록만 셉니다. 늦게 입력되는 기록이 있어 다음 자료에서 늘 수 있습니다.</div></div>`;
}
function secSimple(title,rows){return `<div class="card"><h2>${esc(title)}</h2><table class="tb">${tblHead(MONTHS.map(m=>m+'월'))}${rows.map(([n,r])=>{let t=0;return `<tr><td class="nm">${esc(n)}</td>${MONTHS.map(m=>{t+=r[m]||0;return `<td class="${r[m]?'':'z'}">${r[m]?n0(r[m]):'·'}</td>`;}).join('')}<td><b>${n0(t)}</b></td></tr>`;}).join('')}</table></div>`;}
function secTodo(title,desc){return `<div class="card"><h2>${esc(title)}</h2><div class="todo"><b>뼈대 — 본문 미구현.</b> ${desc}</div></div>`;}
function secUpd(){
  const u=D.update_log;
  return `<div class="card"><h2>업데이트 결과 요약</h2><p class="desc">마지막 입력 ${esc(u.last_input)}</p>
  <div class="updbox"><h3>🔄 이번 받기에서 바뀐 내역</h3><div><b>${esc(u.changed.label)}</b></div><div class="cnt3"><span>추가 ${u.changed.add}</span><span class="m">수정 ${u.changed.mod}</span><span class="d">삭제 ${u.changed.del}</span></div><div><b>삭제</b><ul>${u.changed.del_items.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div></div>
  <h3 style="margin:14px 0 4px">✅ 업데이트된 영역</h3><ul>${u.areas.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>
  <h3 style="margin:14px 0 4px">⬜ 되지 않은 영역</h3><ul>${u.pending.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>
  <h3 style="margin:14px 0 4px">⚠️ 확인 필요</h3><ul><li>캘린더 '확인 필요' 일정 ${n0(EV.filter(e=>e.check).length)}건 — 일정 화면에서 분류를 정하면 다음 받기에 들어감</li></ul>
  <div class="todo" style="margin-top:14px"><b>뼈대.</b> 원본은 여기서 업데이트 파일(활동표·커버리지·콜·리퀘·사내지원 엑셀)을 올리고 리퀘 줄을 붙여 넣습니다. 홈페이지 리포트·최종발간일자는 PC 수집기(tools/homepage_feed.py)가 매주 월 9시 자동.</div></div>`;
}
function secSum(){
  const y=D.year, cur=new Date().getMonth()+1;
  const pub=counts('corp',y,e=>e.kind==='corp'||e.kind==='etc'), sem=counts('sem',y,e=>e.kind==='sem'||e.kind==='ndr'||e.kind==='cday');
  const sum=(c,m)=>AN.reduce((s,a)=>s+(m?((c[a.name]||{})[m]||0):Object.values(c[a.name]||{}).reduce((x,v)=>x+v,0)),0);
  const cov=D.coverage, dw=D.drop_warn, dif=D.plan_vs_pub.filter(r=>r.kospi&&(r.kospi[0]!==r.kospi[1]||r.kosdaq[0]!==r.kosdaq[1])).length;
  const kpi=`<div class="kpis">
    <div class="kpi"><div class="lb">${y}년 발간</div><div class="v">${n0(sum(pub))}<small>건 · ${cur}월 ${n0(sum(pub,cur))}건</small></div><div class="sub">기업·산업·Weekly 보고서<br>작년 같은 기간 비교(뼈대: 없음)<br>전략팀 제외</div></div>
    <div class="kpi"><div class="lb">${y}년 세미나</div><div class="v">${n0(sum(sem))}<small>건 · ${cur}월 ${n0(sum(sem,cur))}건</small></div><div class="sub">NDR ${n0(sum(counts('ndr',y)))}건 · 콥데이 ${n0(sum(counts('cday',y)))}건</div></div>
    <div class="kpi"><div class="lb">코스피 커버리지</div><div class="v">${cov.kospi.now}<small>→ TO-BE ${cov.kospi.tobe}</small></div><div class="bar"><i style="width:${Math.min(100,cov.kospi.now/cov.kospi.goal*100)}%"></i></div><div class="sub">목표 ${cov.kospi.goal}개 이상 · ${cov.kospi.now>=cov.kospi.goal?'<b>넘음</b>':'미달'}</div></div>
    <div class="kpi"><div class="lb">코스닥 커버리지</div><div class="v">${cov.kosdaq.now}<small>→ TO-BE ${cov.kosdaq.tobe}</small></div><div class="bar"><i style="width:${Math.min(100,cov.kosdaq.now/cov.kosdaq.goal*100)}%"></i></div><div class="sub">목표 ${cov.kosdaq.goal}개 이상 · ${cov.kosdaq.now>=cov.kosdaq.goal?'<b>넘음</b>':'미달'}</div></div>
    <div class="kpi"><div class="lb">발간 vs 계획</div><div class="v red">${dif}<small>명 차이</small></div><div class="sub">발간 자료로 센 커버리지와 관리 계획이 다른 애널리스트</div></div>
    <div class="kpi"><div class="lb">드랍 경고</div><div class="v red">${dw.passed}<small>종목 지남 · ${dw.soon}종목 4주 안</small></div><div class="sub">${esc(dw.items.join(' · '))}<br>비고·퇴사·담당 바뀜·이미 드랍한 종목은 뺌</div></div></div>`;
  return kpi+actTable(pub,sem,y)+`<div class="hint2" style="margin-top:6px">※ 커버리지 인정은 12월~5월말일, 6~11월말일</div>`;
}
function actTable(pub,sem,y){
  const ndr=counts('ndr',y),cday=counts('cday',y),etc=counts('etc',y);
  const T=(c,a)=>Object.values(c[a.name]||{}).reduce((x,v)=>x+v,0);
  const cols=['가중건수','산업(인뎁스)','산업30+','산업20+','산업10+','산업9-','기업(인뎁스)','기업','Weekly','Daily','경영진','NPS 심화','ESG,NPS(공)','(가중합)','국민연금','우정사업본부','기관','(가중합)','NDR','콥데이','탐방(동반자수)','탐방(연금)','(가중합)','연기금','기관','국민연금','우정사업본부','기관','④'];
  let rows='';
  D.parts.forEach(p=>{AN.filter(a=>a.part===p.id).forEach((a,i)=>{const P=T(pub,a),S=T(sem,a),N=T(ndr,a),C=T(cday,a),E=T(etc,a);
    const v=[P,0,0,0,0,0,0,P,0,0,0,0,0, S*17,Math.round(S*.1),Math.round(S*.05),S, N*5,N,C,0,0, E*3,0,E, 0,0,0, Math.round(E/3)];
    rows+=`<tr><td class="pt">${i===0?esc(p.name):(a.group!=='팀장'&&AN.filter(x=>x.part===p.id&&x.group===a.group)[0]===a?esc(a.group):'')}</td><td class="nm">${esc(a.name)}${a.leader?' <span class="badge lead">팀장</span>':''}</td>${v.map((x,j)=>`<td class="${[0,7,13,17,22].includes(j)?'b':''} ${[13,17,22].includes(j)?'g':''}">${x?n0(x):'<span style="color:var(--line)">0</span>'}</td>`).join('')}</tr>`;});});
  return `<div class="card"><h2>DAOL 리서치본부 활동표 — ${y}년 · ${new Date().getMonth()+1}월</h2><p class="desc">엑셀 인쇄본 2페이지와 같은 표입니다(가산점 칸 제외). 위는 연간, 아래는 달 표. 이름을 누르면 그 사람 줄만 진하게 봅니다. <b>뼈대: 가중치·배점 없이 샘플 건수를 자리만 맞춰 넣었습니다.</b></p>
  <div class="chips2"><span class="lb">연간</span>${yrChips(y)}<span class="sep"></span><span class="lb">달</span>${MONTHS.slice().reverse().map(m=>`<button class="${m===new Date().getMonth()+1?'on':''}">${m}월</button>`).join('')}</div>
  <div class="actwrap"><table class="tb act"><tr><th class="sec" colspan="2">${y}년</th><th class="sec" colspan="13">Professional: 연 100개 이상 S, 80개 이상 A</th><th class="sec" colspan="4">Promotive ①세미나: 연300개+ 추천 (횟수)</th><th class="sec" colspan="5">②NDR: 연 100개 목표 (횟수)</th><th class="sec" colspan="3">③콜+리퀘 — 콜</th><th class="sec" colspan="3">리퀘</th><th class="sec">④사내업무지원</th></tr>
  <tr class="score"><td class="pt">배점</td><td></td>${['35%','10','2.5','2','1.5','1','3','1','0.5','0.1','5','30','15','35%','15%','2','2','1','10%','1','0.1','','','5%','1','0.1','1','0.5','5%'].map(x=>`<td>${x}</td>`).join('')}</tr>
  <tr><th>부문</th><th>애널리스트</th>${cols.map(c=>`<th>${esc(c)}</th>`).join('')}</tr>${rows}</table></div></div>`;
}
function secInst(){
  const m={};EV.filter(e=>e.kind==='ndr'&&e.date.startsWith(String(D.year))).forEach(e=>{const r=m[e.org]=m[e.org]||{n:0,m:{},last:'',cos:new Set()};r.n++;const mo=+e.date.slice(5,7);r.m[mo]=(r.m[mo]||0)+1;if(e.date>r.last)r.last=e.date;r.cos.add(anOf(e.an).sector);});
  const rows=Object.entries(m).sort((a,b)=>b[1].n-a[1].n);
  return `<div class="card"><h2>NDR 참석 기관별 — ${D.year}년 월별 <small class="hint2">${rows.length}개 기관 · 참석 ${n0(rows.reduce((s,r)=>s+r[1].n,0))}회</small></h2><p class="desc">위 NDR 에 들어온 기관을 기관마다 센 것입니다. 숫자 = 그 기관이 참석한 NDR 수.</p>
  <table class="tb"><tr><th>기관</th><th>참석한 NDR(기업)</th>${MONTHS.map(x=>`<th>${x}월</th>`).join('')}<th>합계</th><th>최근</th></tr>${rows.map(([k,r])=>`<tr><td class="nm">${esc(k)}</td><td class="muted" style="text-align:left">${esc([...r.cos].slice(0,4).join(', '))}</td>${MONTHS.map(x=>`<td class="${r.m[x]?'':'z'}">${r.m[x]||'·'}</td>`).join('')}<td><b>${r.n}</b></td><td class="muted">${r.last.slice(5).replace('-','/')}</td></tr>`).join('')}</table></div>`;
}
function secInstTab(){return `<div class="card"><h2>기관별 집계</h2><p class="desc">세미나·NDR 참석 기관별 집계(원본은 런타임 로드).</p></div>`+secInst();}
function secPvp(){
  const rows=D.plan_vs_pub;const f=v=>v==null?'-':n0(v);const dif=(a,b)=>a==null?'-':a-b===0?'0':`<span class="${a-b>0?'pos':'neg'}">${a-b>0?'+':'−'}${Math.abs(a-b)}</span>`;
  const T=k=>rows.reduce((s,r)=>s+(r[k]?r[k][0]:0),0),TP=k=>rows.reduce((s,r)=>s+(r[k]?r[k][1]:0),0);
  return `<div class="card"><h2>발간 vs 계획</h2><p class="desc"><b>현재</b> = ⓐ 발간 자료(Workflow)로 센 NPS 커버리지, <b>계획</b> = ⓑ 관리 계획의 '유지' 종목 수입니다. 차이 −는 계획엔 있는데 아직 발간 인정이 안 된 것, +는 계획에 없던 발간입니다.<br>숫자를 누르면 종목 목록, 차이를 누르면 어느 종목이 다른지 보입니다. <b>(뼈대: data.json 의 샘플 수)</b></p>
  <table class="tb"><tr><th>구분</th><th>담당애널</th><th>현재 코스피</th><th>코스닥</th><th>계획 코스피</th><th>코스닥</th><th>차이 코스피</th><th>코스닥</th><th style="text-align:left">비고</th></tr>
  ${rows.map((r,i)=>`<tr><td class="muted">${i===0?'재직':''}</td><td class="nm">${esc(r.name)}${anOf(r.name).leader?' <span class="badge lead">팀장</span>':''}</td><td>${r.kospi?f(r.kospi[0]):'-'}</td><td>${r.kosdaq?f(r.kosdaq[0]):'-'}</td><td>${r.kospi?f(r.kospi[1]):'-'}</td><td>${r.kosdaq?f(r.kosdaq[1]):'-'}</td><td>${r.kospi?dif(r.kospi[0],r.kospi[1]):'-'}</td><td>${r.kosdaq?dif(r.kosdaq[0],r.kosdaq[1]):'-'}</td><td class="muted" style="text-align:left">${esc(r.memo||'')}</td></tr>`).join('')}
  <tr class="tot"><td>합계</td><td></td><td>${T('kospi')}</td><td>${T('kosdaq')}</td><td>${TP('kospi')}</td><td>${TP('kosdaq')}</td><td></td><td></td><td></td></tr></table></div>`;
}
function secCov(){
  return `<div class="card"><h2>커버리지</h2><p class="desc">최종발간일자 파일(홈페이지 리포트) 기준 커버리지 종목 목록 · 업종별/애널리스트별 표 · 수동 추가 폼.</p>
  <div class="todo"><b>뼈대 — 본문 미구현.</b> 원본 구성: ① 최종발간일자 파일 안내 ② 수동 추가 폼(종목·종목코드·애널리스트·시장·날짜·메모) ③ 업종별 커버리지 표(코스피/코스닥 × 담당·업종·현재·TO-BE·비고) ④ 애널리스트별 표 ⑤ 커버리지 종목 전체 목록(드랍 경고 배지·비고). 이 리포에서는 <b>coverage_flow/universe.csv</b>·<b>hanwha_research_tone</b> 의 발간 파서가 소스 후보.</div>
  <table class="tb"><tr><th>담당</th><th>업종</th><th>코스피</th><th>코스닥</th><th>TO-BE</th></tr>${AN.filter(a=>a.part==='corp').map(a=>{const r=D.plan_vs_pub.find(x=>x.name===a.name);return `<tr><td class="nm">${esc(a.name)}</td><td class="muted" style="text-align:left">${esc(a.sector)}</td><td>${r&&r.kospi?r.kospi[0]:'-'}</td><td>${r&&r.kosdaq?r.kosdaq[0]:'-'}</td><td>${r&&r.kospi?r.kospi[1]:'-'}</td></tr>`;}).join('')}</table></div>`;
}
function secDrop(){
  const dw=D.drop_warn;
  return `<div class="card"><h2>커버리지 유지·드랍 경고</h2><p class="desc">드랍 경고 있는 법(기준일 ${todayIso().slice(2).replace(/-/g,'.')}) — 마지막 발간일 + 6개월 뒤가 '마감'. 마감이 지났거나 4주 안이면 경고.</p>
  <div class="chips2"><button class="on">전체 ${dw.passed+dw.soon+150}</button><button>경고 ${dw.passed+dw.soon}</button><span class="sep"></span><button class="on">지남 ${dw.passed}</button><button>4주 안 ${dw.soon}</button><button>드랍 예정</button><span class="sep"></span><button class="on">시장 전체</button><button>코스피</button><button>코스닥</button></div>
  <table class="tb"><tr><th style="text-align:left">종목명</th><th>담당</th><th>시장</th><th>최근 발간일</th><th>마감</th><th>상태</th><th style="text-align:left">비고</th></tr>${dw.items.map(x=>{const [nm,md]=x.split(' ');return `<tr><td class="nm">${esc(nm)}</td><td class="muted">최광식 <span class="badge lead">팀장</span></td><td>KOSPI</td><td class="muted">—</td><td>26.${md.replace('/','.')}</td><td><span class="badge need">마감 지남</span></td><td class="muted" style="text-align:left"></td></tr>`;}).join('')}</table>
  <div class="todo" style="margin-top:12px"><b>뼈대 — 종목 전체 목록 미구현.</b> 원본은 커버리지 종목 170여 개를 담당·시장·보유·발간·최근 발간·마감·상태·비고 열로 전부 나열하고, 애널리스트 칩(이름 옆 경고 수/전체)으로 거릅니다.</div></div>`;
}
function secMiss(){
  const cal=counts('sem',D.year), r=rng(7); const xl={};AN.forEach(a=>{xl[a.name]={};MONTHS.forEach(m=>{if((cal[a.name]||{})[m])xl[a.name][m]=Math.floor(r()*4);});});
  const cell=(row,i)=>(row[i+1]||0);
  return `<div class="card"><h2>누락 후보 — 세미나</h2><p class="desc">캘린더 세미나와 엑셀 ④영업활동 설명회(기관/법인) 줄을 짝지어 한쪽에만 있는 것을 모읍니다(세미나만 — NDR·리퀘스트·탐방·콥데이는 안 셉니다). 짝 = 같은 애널·같은 날이고 시각이 40분 안이거나 기관이 같은 줄. 캘린더에만 있으면 엑셀에 안 적었거나 날짜를 다르게 적은 것, 엑셀에만 있으면 캘린더에 안 올린 세미나입니다. <b>(뼈대: 엑셀 쪽은 난수)</b></p>
  <div class="chips2"><button class="on">월별</button><button>분기별</button><span class="sep"></span><button>다올자산 제외</button><span class="hint2" style="margin-left:8px">칸은 <span style="color:var(--accent)">캘린더에만</span> / <span style="color:var(--danger)">엑셀에만</span></span></div>
  <table class="tb"><tr><th>애널리스트</th>${MONTHS.map(m=>`<th>${m}월</th>`).join('')}<th>합계</th></tr>${AN.map(a=>{const c=cal[a.name]||{},x=xl[a.name]||{};let tc=0,tx=0;return `<tr><td class="nm">${esc(a.name)}${a.leader?' <span class="badge lead">팀장</span>':''}</td>${MONTHS.map(m=>{const cc=Math.round((c[m]||0)*0.15),xx=x[m]||0;tc+=cc;tx+=xx;return `<td class="${cc||xx?'n':'z'}">${cc||xx?`<span style="color:var(--accent)">${cc||'·'}</span>/<span style="color:var(--danger)">${xx||'·'}</span>`:'·'}</td>`;}).join('')}<td><b><span style="color:var(--accent)">${tc}</span>/<span style="color:var(--danger)">${tx}</span></b></td></tr>`;}).join('')}</table></div>`;
}
function bindDash(root){
  $$('.chips2 button[data-y]',root).forEach(b=>b.onclick=()=>{secMonthly.y=+b.dataset.y;drawDash();});
  $$('.chips2 button[data-q]',root).forEach(b=>b.onclick=()=>{secMonthly.q=b.dataset.q==='1';drawDash();});
  $$('.chips2 button:not([data-y]):not([data-q])',root).forEach(b=>b.onclick=()=>{$$('button',b.parentElement).forEach(x=>{});b.classList.toggle('on');toast('칩 필터는 뼈대에서 표시만');});
  $$('td.n[data-an]',root).forEach(td=>td.onclick=()=>openDetail(td.dataset.an,+td.dataset.m));
  $$('td.nm[data-an]',root).forEach(td=>td.onclick=()=>openDetail(td.dataset.an,0));
}
function openDetail(an,m){
  const y=secMonthly.y||D.year;const list=EV.filter(e=>e.an===an&&e.date.startsWith(String(y))&&(!m||+e.date.slice(5,7)===m)&&(e.ledger||e.check)).sort(evSort);
  showModal(`<h2>${esc(an)} <small>${y}년 ${m?m+'월':'전체'} · ${n0(list.length)}건</small></h2><div class="agenda" style="border:none;padding:0;max-height:70vh;overflow:auto">${list.map(e=>{const a=anOf(e.an);return `<div class="arow2 ev" data-id="${e.id}" style="--c:${a.color}"><span class="tm">${e.date.slice(5).replace('-','/')} ${e.time}</span><span class="dot"></span><span class="badge ${e.check?'need':'ledger'}">${e.check?'확인':'장부'}</span><span class="tt"><span class="k" style="color:var(--k-${e.kind})">[${KIND[e.kind]}]</span><b>${esc(e.title)}</b><small>${esc(e.memo)}</small></span><span class="an"></span></div>`;}).join('')||'<div class="empty">없음</div>'}</div>`);
  bindChips($('#modal'));
}

/* ───── 시작 ───── */
loadData().then(()=>{setPage(page);if(page==='dash'&&!sessionStorage.getItem('ana_upd_seen')){sessionStorage.setItem('ana_upd_seen','1');const h=secUpd();showModal(h.replace('<div class="card">','<div>'));}}).catch(e=>{document.body.insertAdjacentHTML('afterbegin',`<div class="todo" style="margin:16px">data.json 을 읽지 못했습니다: ${esc(e.message)}</div>`);});
})();
