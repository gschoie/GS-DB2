const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const dateValue=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
const today=new Date(),weekAgo=new Date(today);weekAgo.setDate(today.getDate()-7);
const state={q:'',reportCompany:'',newsCompany:'',newsQ:'',reportType:'',weeklyFolder:'',pressStart:dateValue(weekAgo),pressEnd:dateValue(today),pressRows:[],reports:[],news:[],companies:[],reportCompanies:[]};
const fmtDate=s=>new Intl.DateTimeFormat('ko-KR',{year:'2-digit',month:'2-digit',day:'2-digit'}).format(new Date(s));
const won=n=>n?`${Number(n).toLocaleString()}원`:'—';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function localData(url){
 const data=window.__DASHBOARD_DATA__;if(!data)return null;
 const [path,raw='']=url.split('?'),params=new URLSearchParams(raw),q=(params.get('q')||'').toLocaleLowerCase(),nq=(params.get('nq')||'').toLocaleLowerCase(),company=params.get('company')||'',type=params.get('type')||'',weekly=params.get('weekly')||'';
 if(path==='/api/summary')return data.summary;
 if(path==='/api/companies')return data.companies;
 if(path==='/api/report-companies')return data.reportCompanies;
 const source=path==='/api/reports'?data.reports:path==='/api/news'?data.news:null;if(!source)return null;
 return source.filter(item=>{
   const haystack=`${item.title||''} ${item.companies_label||item.company_name||''}`.toLocaleLowerCase();
   const searchMatch=!q||haystack.includes(q),companyMatch=!company||(item.company_names||[]).includes(company);
   // 뉴스 키워드 검색(nq)은 제목·기업·코멘트·요약·언론사에 텔레그램 원문(newsTexts)까지 뒤진다 ("페루", "MLRS" 같은 본문 키워드용).
   const nqMatch=path!=='/api/news'||!nq||`${haystack} ${item.comment||''} ${item.summary||''} ${item.publisher||''} ${(data.newsTexts||{})[item.message_id]||''}`.toLocaleLowerCase().includes(nq);
   const typeMatch=path!=='/api/reports'||!type||item.report_type===type;
   const weeklyMatch=path!=='/api/reports'||!weekly||item.weekly_folder===weekly;
   return searchMatch&&companyMatch&&nqMatch&&typeMatch&&weeklyMatch;
 });
}
async function json(url){const local=localData(url);if(local!==null)return local;const r=await fetch(url);if(!r.ok)throw new Error(r.status);return r.json()}
function reportRow(r){const kind=r.report_type||'기업분석',kindClass=kind==='산업분석'?'industry':kind==='위클리'?'weekly':'';const names=(r.company_names?.length?r.company_names:String(r.companies_label||r.company_name||'').split(',').map(s=>s.trim())).filter(Boolean);const label=names.length?names.map(n=>`<button type="button" class="company-chip" data-company="${esc(n)}" title="${esc(n)} 자료만 모아보기">${esc(n)}</button>`).join(''):`<b>${esc(kind==='산업분석'||kind==='위클리'?'산업 자료':'기업 미확인')}</b>`;return `<div class="research-row"><small>${fmtDate(r.posted_at)}</small><div><div class="row-title"><span class="report-kind ${kindClass}">${esc(kind)}</span>${r.weekly_folder?`<span class="weekly-source">${esc(r.weekly_folder)}</span>`:''}${label}</div><p>${esc(r.title)}</p>${r.needs_review?'<span class="review">검토 필요</span>':''}${r.source_url?` <a href="${esc(r.source_url)}" target="_blank" rel="noopener">텔레그램 ↗</a>`:''}</div><span class="tag ${r.target_change==='상향'?'up':r.target_change==='하향'?'down':''}">${esc(r.target_change)}</span><span class="price">${won(r.target_price)}${r.target_price&&r.previous_target_price>=1000&&r.previous_target_price!==r.target_price?`<small class="prev-price">(직전 ${Number(r.previous_target_price).toLocaleString()})</small>`:''}</span></div>`}
function newsCard(n){return `<article class="news-card"><small>${fmtDate(n.posted_at)} · ${esc(n.industry||n.event_type)}</small><h3>${esc(n.title)}</h3><p class="tag">${esc(n.companies_label||n.company_name||'기업 미확인')}</p>${n.article_url?`<a href="${esc(n.article_url)}" target="_blank" rel="noopener">기사 원문 ↗</a>`:''}${n.source_url?` · <a href="${esc(n.source_url)}" target="_blank" rel="noopener">텔레그램 ↗</a>`:''}</article>`}
function newsTable(list){return `<div class="news-table-wrap"><table class="news-table"><colgroup><col class="date-col"><col class="company-col"><col><col class="publisher-col"><col class="comment-col"><col class="link-col"><col class="telegram-col"></colgroup><thead><tr><th>날짜</th><th>기업명</th><th>제목</th><th>출처(언론사)</th><th>내 코멘트</th><th>링크</th><th>텔레그램 링크</th></tr></thead><tbody>${list.map(n=>`<tr><td class="news-date">${fmtDate(n.posted_at)}</td><td><span class="company-label">${esc(n.companies_label||n.company_name||'기업 미확인')}</span></td><td class="news-title">${esc(n.title)}</td><td>${esc(pressPublisher(n))}</td><td class="news-comment">${n.comment?`<div class="comment-clip" title="${esc(n.comment)}">${esc(n.comment)}</div>`:'<span class="no-link">N/A</span>'}</td><td>${n.article_url?`<a class="table-link" href="${esc(n.article_url)}" target="_blank" rel="noopener" aria-label="기사 원문 열기">기사 ↗</a>`:'<span class="no-link">—</span>'}</td><td>${n.source_url?`<a class="table-link telegram-link" href="${esc(n.source_url)}" target="_blank" rel="noopener" aria-label="텔레그램 원문 열기">텔레그램 ↗</a>`:'<span class="no-link">—</span>'}</td></tr>`).join('')}</tbody></table></div>`}
function pressSector(n){const industry=n.industry||'',text=`${n.companies_label||n.company_name||''} ${n.title||''}`;if(industry==='조선'||['해양','LNG','가스선','컨테이너','탱커'].includes(industry))return '조선';if(industry==='방산')return '방산';if(industry==='기계'||industry==='건설기계')return '건설기계';if(/HD건설기계|현대건설기계|두산밥캣|두산인프라|디벨론|굴착기|건설기계/.test(text))return '건설기계';if(/한화오션|HD현대중공업|HD한국조선해양|삼성중공업|HD현대미포|K조선|HJ중공업|대한조선|조선|선박|VLCC|LNG선|컨테이너선/.test(text))return '조선';if(/KAI|한국항공우주|한화에어로|한화시스템|현대로템|LIG|풍산|방산|KF-21|K9|K2|천궁|자주포|전투기|미사일|고스트로보틱스|로봇개/.test(text))return '방산';return null}
function pressPublisher(n){if(n.publisher)return n.publisher;try{const host=new URL(n.article_url).hostname.replace(/^(www\.|m\.)/,'');const names={'yna.co.kr':'연합뉴스','news1.kr':'뉴스1','theguru.co.kr':'더구루','hankyung.com':'한국경제','mk.co.kr':'매일경제','sedaily.com':'서울경제','edaily.co.kr':'이데일리','mt.co.kr':'머니투데이','fnnews.com':'파이낸셜뉴스','chosun.com':'조선일보','joongang.co.kr':'중앙일보','donga.com':'동아일보','eurasiantimes.com':'EurAsian Times','reuters.com':'Reuters'};return Object.entries(names).find(([d])=>host===d||host.endsWith('.'+d))?.[1]||host}catch{return '미확인'}}
function isPressArticle(url){try{return !['t.me','telegram.me','www.t.me'].includes(new URL(url).hostname.toLowerCase())}catch{return false}}
function pressCompany(n){return n.companies_label||n.company_name||'기업 미확인'}
// 애널리스트 관점 중요도. A=투자판단 직결(수주·실적·수출·M&A·자사주 등), C=지역/정치/일반동향, B=그 외.
const IMP_A=/수주|수요|계약|낙찰|발주|신조|건조|인도|수출|매각|양수도|인수|합병|지분|증설|투자\s?계획|목표주가|투자의견|목표가|실적|영업이익|어닝|잠정실적|자사주|배당|유상증자|MRO|정비사업|잠수함|구축함|프리깃|호위함|KF-?21|FA-?50|천궁|자주포|K9|굴착기.*판매|조\s?원|억\s?달러|조원\s?규모/;
const IMP_C=/노조|파업|집회|도의회|시의회|국회|청원|규탄|촉구|건의|해명|논란|의혹|칼럼|기고|사설|부고|동정|인사\s|축사|방문|간담회|행사|위촉|선임\s|임명|루머|기대감|가능성|전망\s?…|주가\s?전망/;
function pressImportance(n){const t=`${pressCompany(n)} ${n.title||''}`;if(IMP_A.test(t))return'A';if(IMP_C.test(t))return'C';return'B'}
function sortPress(a,b){const sectorOrder={조선:0,방산:1,건설기계:2},sector=(sectorOrder[a.press_sector]??9)-(sectorOrder[b.press_sector]??9);if(sector)return sector;const ac=pressCompany(a),bc=pressCompany(b);if(ac==='기업 미확인'&&bc!=='기업 미확인')return 1;if(bc==='기업 미확인'&&ac!=='기업 미확인')return -1;const company=ac.localeCompare(bc,'ko');if(company)return company;const date=new Date(b.posted_at)-new Date(a.posted_at);return date||String(a.title).localeCompare(String(b.title),'ko')}
function renderPressTable(){const start=$('#press-start').value,end=$('#press-end').value;if(start>end){state.pressRows=[];$('#press-table').innerHTML='<p class="empty">시작일이 종료일보다 늦습니다.</p>';$('#press-count').textContent='0건';return}state.pressStart=start;state.pressEnd=end;
 // 보도기사 취합은 아카이브 검색어(newsQ)·기업 필터·통합검색(q)과 무관하게 전체 뉴스에서 날짜로만 거른다.
 // (state.news를 쓰면 아카이브에서 검색해 둔 상태일 때 날짜를 바꿔도 목록이 안 변하는 것처럼 보인다.)
 const list=(state.allNews||state.news).map(n=>({...n,press_sector:pressSector(n)})).filter(n=>{const day=dateValue(new Date(n.posted_at));return isPressArticle(n.article_url)&&n.press_sector&&day>=start&&day<=end}).sort(sortPress);state.pressRows=list;$('#press-count').textContent=`${list.length.toLocaleString()}건`;$('#press-table').innerHTML=list.length?`<div class="news-table-wrap"><table class="press-table"><colgroup><col class="sector-col"><col class="press-company-col"><col class="press-date-col"><col class="imp-col"><col><col class="publisher-col"><col class="press-link-col"></colgroup><thead><tr><th>섹터</th><th>기업명</th><th>기사일자</th><th>중요도</th><th>기사제목</th><th>출처(언론사)</th><th>기사링크</th></tr></thead><tbody>${list.map(n=>{const imp=pressImportance(n);return `<tr><td><span class="sector-label sector-${n.press_sector}">${n.press_sector}</span></td><td>${esc(pressCompany(n))}</td><td class="news-date">${fmtDate(n.posted_at)}</td><td><span class="imp-badge imp-${imp}">${imp}</span></td><td class="news-title">${esc(n.title)}</td><td>${esc(pressPublisher(n))}</td><td><a class="table-link" href="${esc(n.article_url)}" target="_blank" rel="noopener">기사 ↗</a></td></tr>`}).join('')}</tbody></table></div>`:'<p class="empty">선택한 기간에 해당하는 보도기사가 없습니다.</p>'}
function exportPressExcel(){if(!state.pressRows.length){alert('다운로드할 보도기사가 없습니다.');return}const cell=value=>`"${String(value??'').replace(/"/g,'""')}"`;const rows=[['섹터','기업명','기사일자','중요도','기사제목','출처(언론사)','기사링크'],...state.pressRows.map(n=>[n.press_sector,pressCompany(n),dateValue(new Date(n.posted_at)),pressImportance(n),n.title,pressPublisher(n),n.article_url])];const csv='\ufeff'+rows.map(row=>row.map(cell).join(',')).join('\r\n');const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'})),link=document.createElement('a');link.href=url;link.download=`보도기사_${state.pressStart}_${state.pressEnd}.csv`;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)}
/* ── DAOL 리서치 톤: 독립 프로그램(daol-research-tone)으로 분리 — iframe + 요약 fetch ── */
const TONE_SITE='https://gschoie.github.io/DAOL-RESEARCH-TONE/';
function loadToneFrame(){const f=$('#tone-frame');if(f&&!f.getAttribute('src'))f.src=TONE_SITE+'?t='+Date.now()}
async function fetchToneSummary(){const box=$('#tone-latest');if(!box)return;
 try{const r=await fetch(TONE_SITE+'tone_summary.json?t='+Date.now(),{cache:'no-store'});if(!r.ok)throw 0;
  const s=await r.json();box.innerHTML=(s.latest||[]).slice(0,6).map(overviewTone).join('')||'<p class="empty">톤 데이터가 없습니다.</p>'}
 catch{box.innerHTML=`<p class="empty">톤 보드에서 확인 → <a href="${TONE_SITE}" target="_blank" rel="noopener">daol-research-tone ↗</a></p>`}}
function miniRow(lead,body,href){return `<a class="mini-row" href="${esc(href||'#')}" target="_blank" rel="noopener">${lead}<div>${body}</div></a>`}
function overviewNews(n){return miniRow(`<small>${esc(fmtDate(n.posted_at))}</small>`,`<div class="mini-head"><b>${esc(n.companies_label||n.company_name||'기업 미확인')}</b></div><p>${esc(n.title)}</p>`,n.article_url||n.source_url)}
function overviewTone(r){const op=r.opinion&&!['명시 없음','없음',''].includes(r.opinion)?`<span class="tag">${esc(r.opinion)}</span>`:'';const tp=r.tp_dir==='상향'?'<span class="tag up">TP▲</span>':r.tp_dir==='하향'?'<span class="tag down">TP▼</span>':'';return miniRow(`<small>${esc(String(r.date||'').slice(5))}</small>`,`<div class="mini-head"><b>${esc(r.company||'')}</b> <span class="mini-sub">${esc(r.analyst||'')}</span>${op}${tp}</div><p>${esc(r.title||'')}</p>`,r.pdf_url||r.post_url)}
function overviewUnion(p){return miniRow(`<b class="rk">${p.rank}</b>`,`<p class="mini-title">${esc(p.title)}</p><small>주목도 ${p.score} · 조회 ${Number(p.views).toLocaleString()} · 댓글 ${p.comments}</small>`,p.url)}
function overviewMacro(x,i){return miniRow(`<b class="rk">${i+1}</b>`,`<p class="mini-title">${esc(x.title)}</p>`,x.url)}
const MACRO_ENDPOINT='https://script.google.com/macros/s/AKfycbxNClBzJoE35VSwcCNgMEJ_PvFCBphH87g4gq7xDiGXhO5x-fd-IMpNL6Ly0oURJzEN/exec';/* 네이버 Top5 실시간 JSON(GAS). 비면 배포 데이터만 사용 */
const decodeEnt=s=>{const t=document.createElement('textarea');t.innerHTML=s||'';return t.value};
async function fetchLiveMacro(){if(!MACRO_ENDPOINT)return;try{const r=await fetch(MACRO_ENDPOINT,{cache:'no-store'});if(!r.ok)return;const d=await r.json();const items=(d.global_economy||d.items||[]).map(x=>({title:decodeEnt(x.title),url:x.url}));if(items.length&&$('#macro-global'))$('#macro-global').innerHTML=items.slice(0,5).map(overviewMacro).join('')}catch{}}
async function load(){
 const reportQs=new URLSearchParams({q:state.q,company:state.reportCompany,type:state.reportType,weekly:state.weeklyFolder});
 const newsQs=new URLSearchParams({q:state.q,nq:state.newsQ,company:state.newsCompany});
 const [sum,reports,news,newsAll,companies,reportCompanies,weeklyReports]=await Promise.all([json('/api/summary'),json('/api/reports?'+reportQs),json('/api/news?'+newsQs),json('/api/news'),json('/api/companies'),json('/api/report-companies'),json('/api/reports?type=위클리')]);
 state.reports=reports;state.news=news;state.allNews=newsAll;state.companies=companies;state.reportCompanies=reportCompanies;
 $('#press-start').value=state.pressStart;$('#press-end').value=state.pressEnd;
 $('#updated-at').textContent=sum.updated_at?new Intl.DateTimeFormat('ko-KR',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(sum.updated_at)):'미확인';
 $('#weekly-all-count').textContent=`${weeklyReports.length}건`;$('#weekly-daol-count').textContent=`${weeklyReports.filter(r=>r.weekly_folder==='다올선박').length}건`;$('#weekly-kis-count').textContent=`${weeklyReports.filter(r=>r.weekly_folder==='한투시절').length}건`;$('#weekly-hi-count').textContent=`${weeklyReports.filter(r=>r.weekly_folder==='하이투자증권시절').length}건`;
 $('#latest-reports').innerHTML=reports.slice(0,5).map(reportRow).join('')||'<p class="empty">수집된 보고서가 없습니다.</p>';
 $('#report-table').innerHTML=reports.map(reportRow).join('')||'<p class="empty">조건에 맞는 보고서가 없습니다.</p>';
 $('#latest-news').innerHTML=news.slice(0,6).map(overviewNews).join('')||'<p class="empty">수집된 뉴스가 없습니다.</p>';
 fetchToneSummary();
 const unionTop=window.__DASHBOARD_DATA__?.union?.monthly||[];
 if($('#union-top'))$('#union-top').innerHTML=unionTop.slice(0,6).map(overviewUnion).join('')||'<p class="empty">노조게시판 데이터가 없습니다.</p>';
 const macro=window.__DASHBOARD_DATA__?.macro||{};
 if($('#macro-global'))$('#macro-global').innerHTML=(macro.global_economy||[]).slice(0,5).map(overviewMacro).join('')||'<p class="empty">매크로 데이터가 없습니다.</p>';
 fetchLiveMacro();
 const brief=$('#daily-brief');if(brief){const gm='https://gemini.google.com/app/dc1cee4fd9194007?usp=sharing';const body=macro.daily_brief?esc(macro.daily_brief).replace(/\n/g,'<br>'):'<span class="brief-empty">아직 핵심요약이 없습니다. GMN.글로벌방산 문서에 붙여넣으면 여기 표시됩니다.</span>';brief.innerHTML=`<div class="brief-head"><small>GEMINI · 오늘의 핵심요약</small><a href="${gm}" target="_blank" rel="noopener">Gemini 열기 →</a></div><div class="brief-body">${body}</div>`}
 const archive=news.reduce((all,n)=>{const d=new Date(n.posted_at),y=String(d.getFullYear()),m=`${String(d.getMonth()+1).padStart(2,'0')}월`;all[y]??={};all[y][m]??=[];all[y][m].push(n);return all},{});
 const years=Object.entries(archive).sort(([a],[b])=>b.localeCompare(a));
 $('#news-list').innerHTML=years.map(([year,months],yi)=>{const count=Object.values(months).reduce((sum,list)=>sum+list.length,0);return `<details class="year-group" ${yi===0||state.newsQ?'open':''}><summary><span>${year}년</span><em>${count.toLocaleString()}건</em></summary><div class="year-content">${Object.entries(months).sort(([a],[b])=>b.localeCompare(a)).map(([month,list],mi)=>`<details class="month-group" ${(yi===0&&mi===0)||state.newsQ?'open':''}><summary class="month-divider"><h3>${month}</h3><span>${list.length}건</span></summary>${newsTable(list)}</details>`).join('')}</div></details>`}).join('')||'<p class="empty">조건에 맞는 뉴스가 없습니다.</p>';
 const sortKo=list=>[...list].sort((a,b)=>a.name.localeCompare(b.name,'ko'));
 const reportOptions='<option value="">모든 기업</option>'+sortKo(reportCompanies).map(c=>`<option ${state.reportCompany===c.name?'selected':''}>${esc(c.name)}</option>`).join('');
 const newsOptions='<option value="">모든 기업</option>'+sortKo(companies).map(c=>`<option ${state.newsCompany===c.name?'selected':''}>${esc(c.name)}</option>`).join('');
 $('#report-company').innerHTML=reportOptions;$('#news-company').innerHTML=newsOptions;
 renderPressTable();
}
function loadUnionBoard(){const frame=$('#union-board-frame'),status=$('#union-board-status');status.textContent='최신 보고서를 불러오는 중';frame.onload=()=>status.textContent='현중 노조게시판 분석 보고서';frame.onerror=()=>status.textContent='hhiun_board_report.html 파일을 확인해 주세요';frame.src=`hhiun_board_report.html?t=${Date.now()}`}
const TASK_ROSTER=[['팀장',['최광식','이준범']],['지속가능(Sustainability)',['박영도','김지원','이정우','김진영']],['지능화(Intelligence)',['유지웅','고영민','김혜영','김연미','김상혁']],['휴먼/생체(Human)',['이지수','박종현']],['FDA',['이다연','임도영','박소현','한수빈']]];
const TASK_ITEMS_DEFAULT=['근태입력','휴가계획','자료제출','컴플라이언스','기타'],TASK_KEY='hi_tasklist_v1',TASK_ITEMS_KEY='hi_tasklist_items_v1',TASK_LAST_KEY='hi_tasklist_last_v1';
const TASK_ENDPOINT='https://script.google.com/macros/s/AKfycbwTX-Ld-ayqHgi97S0QiMYPsHfb2cjNwy66FyDYU6GBrS0kOgMH8KE220GPy3KRxcT3/exec';let taskPushT;
function taskItems(){try{const a=JSON.parse(localStorage.getItem(TASK_ITEMS_KEY));if(Array.isArray(a)&&a.length)return a}catch{}return TASK_ITEMS_DEFAULT.slice()}
function saveItems(a){try{localStorage.setItem(TASK_ITEMS_KEY,JSON.stringify(a))}catch{}taskPush()}
function fillTaskItems(desired){const sel=$('#task-item');if(!sel)return;const items=taskItems();let last=null;try{last=localStorage.getItem(TASK_LAST_KEY)}catch{}
 // 항목 우선순위: 명시 지정 > 화면에서 고른 값 > 마지막 사용 항목(재방문 시 근태입력으로 리셋 방지) > 첫 항목
 const cur=items.includes(desired)?desired:(items.includes(sel.value)?sel.value:(items.includes(last)?last:items[0]));sel.innerHTML=items.map(x=>`<option ${x===cur?'selected':''}>${esc(x)}</option>`).join('');try{localStorage.setItem(TASK_LAST_KEY,cur)}catch{}}
const taskAllNames=()=>TASK_ROSTER.flatMap(([,ns])=>ns);
function taskLoad(){try{return JSON.parse(localStorage.getItem(TASK_KEY))||{}}catch{return{}}}
function taskSave(s){try{localStorage.setItem(TASK_KEY,JSON.stringify(s))}catch{}taskPush()}
function taskBundle(){return{data:taskLoad(),items:taskItems()}}
function taskPush(){if(!TASK_ENDPOINT)return;clearTimeout(taskPushT);const status=$('#task-sync');if(status)status.textContent='저장 중…';taskPushT=setTimeout(()=>{fetch(TASK_ENDPOINT,{method:'POST',body:JSON.stringify(taskBundle())}).then(()=>{if(status)status.textContent='☁ 동기화됨'}).catch(()=>{if(status)status.textContent='이 기기에만 저장(동기화 실패)'})},600)}
async function taskPull(){if(!TASK_ENDPOINT)return false;const status=$('#task-sync');if(status)status.textContent='불러오는 중…';try{const r=await fetch(TASK_ENDPOINT,{cache:'no-store'});if(!r.ok)throw 0;const b=await r.json()||{};const remoteData=b.data&&typeof b.data==='object'?b.data:{};if(!Object.keys(remoteData).length&&Object.keys(taskLoad()).length){taskPush();if(status)status.textContent='☁ 이 기기 데이터 업로드됨';return false}if(b.data)localStorage.setItem(TASK_KEY,JSON.stringify(b.data));if(Array.isArray(b.items)&&b.items.length)localStorage.setItem(TASK_ITEMS_KEY,JSON.stringify(b.items));if(status)status.textContent='☁ 동기화됨';return true}catch{if(status)status.textContent='이 기기에만 저장(동기화 실패)'}return false}
function taskCurrentItem(){return $('#task-item')?.value||taskItems()[0]}
function renderTaskSummary(){const st=taskLoad()[taskCurrentItem()]||{},names=taskAllNames(),pending=names.filter(n=>!st[n]?.done);$('#task-summary').innerHTML=`완료 <b>${names.length-pending.length}</b> / ${names.length}`+(pending.length?` · 미응답: ${esc(pending.join(', '))}`:' · 전원 완료 🎉')}
function renderTaskList(desired){fillTaskItems(desired);const st=taskLoad()[taskCurrentItem()]||{};
 const body=TASK_ROSTER.map(([part,names])=>`<tr class="task-group"><td colspan="4">${esc(part)}</td></tr>`+names.map(n=>{const r=st[n]||{};return `<tr data-name="${esc(n)}"><td class="task-name">${esc(n)}</td><td class="task-done"><input type="checkbox" data-f="done" ${r.done?'checked':''}></td><td><input class="task-in" data-f="resp" placeholder="응답내용" value="${esc(r.resp||'')}"></td><td><input class="task-in" data-f="note" placeholder="비고" value="${esc(r.note||'')}"></td></tr>`}).join('')).join('');
 $('#task-table').innerHTML=`<table class="task-table"><thead><tr><th>이름</th><th>완료</th><th>응답내용</th><th>비고</th></tr></thead><tbody>${body}</tbody></table>`;
 $('#task-date').textContent=new Intl.DateTimeFormat('ko-KR',{year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());renderTaskSummary()}
function taskUpdate(name,field,value){const s=taskLoad(),it=taskCurrentItem();(s[it]=s[it]||{})[name]=s[it][name]||{};s[it][name][field]=value;taskSave(s);renderTaskSummary()}
function view(id){$$('.view,.nav').forEach(x=>x.classList.remove('active'));$('#'+id).classList.add('active');$(`.nav[data-view="${id}"]`).classList.add('active');$('#page-title').textContent={overview:'오늘의 리서치 흐름',reports:'발간 보고서',news:'뉴스.아카이브',press:'보도기사 취합','union-board':'현중 노조게시판',tone:'DAOL 리서치 톤',collab:'섹터 콜라보 레이더',tasklist:'수명 피드백 확인',dart:'조선 수주공시 → 텔레',etf:'ETF/섹터 신호 포착',holdings:'액티브 ETF 구성 변화',flow:'시장 수급 동향',consensus:'코스피200 컨센서스 추적',defense:'글로벌 방산 데일리 브리핑'}[id];if(id==='overview')fetchLiveMacro();if(id==='press')renderPressTable();if(id==='tone')loadToneFrame();if(id==='union-board')loadUnionBoard();if(id==='tasklist'){renderTaskList();taskPull().then(ok=>{if(ok)renderTaskList()})}if(id==='etf'){const f=$('#etf-frame');if(!f.getAttribute('src'))f.src='etf_signal_report.html?t='+Date.now()}if(id==='holdings'){const f=$('#holdings-frame');if(!f.getAttribute('src'))f.src='etf_holdings_report.html?t='+Date.now()}if(id==='flow'){const f=$('#flow-frame');if(!f.getAttribute('src'))f.src='market_flow_report.html?t='+Date.now()}if(id==='consensus'){const f=$('#consensus-frame');if(!f.getAttribute('src'))f.src='consensus_revision.html?t='+Date.now()}if(id==='defense'){const f=$('#defense-frame');if(!f.getAttribute('src'))f.src='defense_briefing_report.html?t='+Date.now()}if(id==='collab'){const f=$('#collab-frame');if(!f.getAttribute('src'))f.src=TONE_SITE+'daol_collab_radar.html?t='+Date.now()}}
const DISPATCH_ENDPOINT='https://script.google.com/macros/s/AKfycbzybp0b1W0wr9n2bfQsF1xblsaLdlu9oRtfH7xkbQrRYLaRpCwemhFRVLbk3rGnIO4zdQ/exec';
async function dispatchWorkflow(payload,status,btn){
 if(status)status.textContent='요청 중…';if(btn)btn.disabled=true;
 try{
  const r=await fetch(DISPATCH_ENDPOINT,{method:'POST',body:JSON.stringify(payload)});
  // GAS 프록시는 실패 시 {ok:false,code,wf}를 돌려준다(매핑 없는 workflow는 dart로 폴백돼 422).
  try{const d=await r.json();
   if(d&&d.ok===false){if(status)status.textContent=`⚠ 서버 거절 ${d.code||'?'} (${d.wf||'?'}) — GAS 프록시 매핑 확인 필요`;return false;}
  }catch{}
  return true;}
 catch(e){if(status)status.textContent='실패: '+e.message;return false;}
 finally{if(btn)btn.disabled=false}}
async function dispatchDart(){
 const url=($('#dart-url')?.value||'').trim(),comment=($('#dart-comment')?.value||'').trim(),status=$('#dart-status'),btn=$('#dart-send');
 if(!/dart\.fss\.or\.kr|rcpNo=|^\d{10,}$/.test(url)){status.textContent='⚠ DART 공시 링크를 넣어주세요';return}
 if(await dispatchWorkflow({workflow:'dart',dart_url:url,comment},status,btn)){
   status.textContent='✅ 요청됨 — 1~2분 뒤 텔레그램 확인';$('#dart-url').value='';$('#dart-comment').value='';}}
async function dispatchEtf(){
 const btn=$('#etf-refresh'),status=$('#etf-status');
 if(await dispatchWorkflow({workflow:'etf'},status,btn))
   status.textContent='✅ ETF 스캔 요청됨 — 몇 분 뒤 새로고침';}
async function dispatchHoldings(){
 const btn=$('#holdings-refresh'),status=$('#holdings-status');
 if(await dispatchWorkflow({workflow:'holdings'},status,btn))
   status.textContent='✅ 구성 스냅샷 요청됨 — 몇 분 뒤 새로고침';}
async function dispatchNews(){
 const btn=$('#news-refresh'),status=$('#news-status');
 if(await dispatchWorkflow({workflow:'news'},status,btn))
   status.textContent='✅ 뉴스 갱신 요청됨 — 몇 분 뒤 새로고침';}
async function dispatchReports(){
 // 발간 보고서만 초경량 갱신(refresh-reports.yml). 뉴스 보강·톤·매크로는 건너뜀.
 const btn=$('#reports-refresh'),status=$('#reports-status');
 if(await dispatchWorkflow({workflow:'reports'},status,btn))
   status.textContent='✅ 보고서 갱신 요청됨 — 2~3분 뒤 새로고침';}
async function dispatchUnion(){
 const btn=$('#union-refresh'),status=$('#union-refresh-status');
 if(await dispatchWorkflow({workflow:'union'},status,btn))
   status.textContent='✅ 노조게시판 갱신 요청됨 — 몇 분 뒤 새로고침';}
async function dispatchPressData(){
 // 보도기사는 뉴스에서 파생 → '데이터 갱신'은 뉴스 수집을 돌린다(끝나면 자동 반영).
 const btn=$('#press-data-refresh'),status=$('#press-data-status');
 if(await dispatchWorkflow({workflow:'news'},status,btn))
   status.textContent='✅ 뉴스 수집 요청됨 — 몇 분 뒤 새로고침하면 반영';}
function openGcal(e){
 // 아이폰/아이패드: 네이티브 캘린더 앱 대신 Chrome으로 연다(googlechromes:// 스킴).
 // PC는 기본 동작(새 탭)으로 그대로 둔다.
 if(/iPhone|iPod|iPad/i.test(navigator.userAgent)){
   e.preventDefault();
   window.location.href='googlechromes://calendar.google.com/calendar/u/0/r/week';
   return false;
 }
 return true;
}
async function dispatchConsensus(){
 const btn=$('#consensus-refresh'),status=$('#consensus-status');
 if(await dispatchWorkflow({workflow:'consensus'},status,btn))
   status.textContent='✅ 컨센 스냅샷 요청됨 — 몇 분 뒤 새로고침';}
async function dispatchFlow(){
 const btn=$('#flow-refresh'),status=$('#flow-status');
 if(await dispatchWorkflow({workflow:'flow'},status,btn))
   status.textContent='✅ 수급 수집 요청됨 — 몇 분 뒤 새로고침';}
$$('.nav').forEach(b=>b.onclick=()=>view(b.dataset.view));$$('[data-go]').forEach(b=>b.onclick=()=>view(b.dataset.go));
// 모바일(≤950px, 플라이아웃)에서 한 메뉴 그룹을 열면 나머지는 닫는다(겹침 방지).
$$('details.nav-group').forEach(d=>d.addEventListener('toggle',()=>{if(d.open&&window.innerWidth<=950)$$('details.nav-group').forEach(o=>{if(o!==d)o.open=false})}));
let timer;$('#search').oninput=e=>{clearTimeout(timer);timer=setTimeout(()=>{state.q=e.target.value;load()},250)};
$('#report-company').onchange=e=>{state.reportCompany=e.target.value;load()};
$('#news-company').onchange=e=>{state.newsCompany=e.target.value;load()};
let newsTimer;$('#news-search').oninput=e=>{clearTimeout(newsTimer);newsTimer=setTimeout(()=>{state.newsQ=e.target.value.trim();load()},250)};
$('#press-refresh').onclick=renderPressTable;
$('#press-start').onchange=renderPressTable;
$('#press-end').onchange=renderPressTable;
$('#press-data-refresh')?.addEventListener('click',dispatchPressData);
$('#press-export').onclick=exportPressExcel;
$('#union-board-refresh').onclick=loadUnionBoard;
$('#union-board-file').onchange=e=>{const file=e.target.files?.[0];if(!file)return;const frame=$('#union-board-frame');if(frame.dataset.objectUrl)URL.revokeObjectURL(frame.dataset.objectUrl);const url=URL.createObjectURL(file);frame.dataset.objectUrl=url;frame.src=url;$('#union-board-status').textContent=`${file.name} · ${(file.size/1024).toFixed(1)}KB`};
$('#dart-send')?.addEventListener('click',dispatchDart);
$('#etf-refresh')?.addEventListener('click',dispatchEtf);
$('#holdings-refresh')?.addEventListener('click',dispatchHoldings);
$('#news-refresh')?.addEventListener('click',dispatchNews);
$('#reports-refresh')?.addEventListener('click',dispatchReports);
$('#union-refresh')?.addEventListener('click',dispatchUnion);
$('#consensus-refresh')?.addEventListener('click',dispatchConsensus);
$('#flow-refresh')?.addEventListener('click',dispatchFlow);
$('#task-item')?.addEventListener('change',()=>renderTaskList());
$('#task-add')?.addEventListener('click',()=>{const name=(prompt('추가할 항목 이름')||'').trim();if(!name)return;const items=taskItems();if(items.includes(name)){alert('이미 있는 항목입니다.');return}items.push(name);saveItems(items);renderTaskList(name)});
$('#task-rename')?.addEventListener('click',()=>{const items=taskItems(),cur=taskCurrentItem(),name=(prompt('항목 이름 변경',cur)||'').trim();if(!name||name===cur)return;if(items.includes(name)){alert('이미 있는 항목입니다.');return}items[items.indexOf(cur)]=name;saveItems(items);const s=taskLoad();if(s[cur]){s[name]=s[cur];delete s[cur];taskSave(s)}renderTaskList(name)});
$('#task-del')?.addEventListener('click',()=>{const items=taskItems(),cur=taskCurrentItem();if(items.length<=1){alert('항목이 하나뿐이라 삭제할 수 없습니다.');return}if(!confirm(`[${cur}] 항목과 그 체크 내용을 삭제할까요?`))return;items.splice(items.indexOf(cur),1);saveItems(items);const s=taskLoad();delete s[cur];taskSave(s);renderTaskList(items[0])});
$('#task-table')?.addEventListener('change',e=>{const tr=e.target.closest('tr[data-name]');if(tr&&e.target.dataset.f==='done')taskUpdate(tr.dataset.name,'done',e.target.checked)});
$('#task-table')?.addEventListener('input',e=>{const tr=e.target.closest('tr[data-name]'),f=e.target.dataset.f;if(tr&&(f==='resp'||f==='note'))taskUpdate(tr.dataset.name,f,e.target.value)});
$('#task-reset')?.addEventListener('click',()=>{if(!confirm(`[${taskCurrentItem()}] 체크·응답·비고를 모두 지울까요?`))return;const s=taskLoad();delete s[taskCurrentItem()];taskSave(s);renderTaskList()});
$('#task-copy')?.addEventListener('click',()=>{const it=taskCurrentItem(),st=taskLoad()[it]||{},names=taskAllNames(),date=new Intl.DateTimeFormat('ko-KR').format(new Date());const pending=names.filter(n=>!st[n]?.done),lines=[`[${it}] ${date}`,`완료 ${names.length-pending.length}/${names.length}`];if(pending.length)lines.push(`미응답: ${pending.join(', ')}`);const detail=names.filter(n=>st[n]&&(st[n].resp||st[n].note)).map(n=>`· ${n}: ${[st[n].resp,st[n].note].filter(Boolean).join(' / ')}`);if(detail.length)lines.push('',...detail);const text=lines.join('\n');(navigator.clipboard?.writeText(text).then(()=>alert('요약을 복사했습니다.'),()=>prompt('아래 내용을 복사하세요',text)))||prompt('아래 내용을 복사하세요',text)});
$('#task-export')?.addEventListener('click',()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(taskLoad(),null,2)],{type:'application/json'}));a.download=`요청체크_${new Date().toISOString().slice(0,10)}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)});
$('#task-import')?.addEventListener('change',e=>{const f=e.target.files?.[0];if(!f)return;const rd=new FileReader();rd.onload=()=>{try{taskSave(JSON.parse(rd.result));renderTaskList();alert('불러왔습니다.')}catch{alert('JSON 파일을 읽지 못했습니다.')}};rd.readAsText(f)});
$$('[data-type]').forEach(button=>button.onclick=()=>{$$('[data-type]').forEach(x=>x.classList.remove('active'));button.classList.add('active');state.reportType=button.dataset.type;state.weeklyFolder='';if(state.reportType==='위클리')state.reportCompany='';$('#weekly-folders').hidden=state.reportType!=='위클리';$('#report-company').hidden=state.reportType==='위클리';$$('[data-weekly]').forEach(x=>x.classList.toggle('active',x.dataset.weekly===''));load()});
$$('[data-weekly]').forEach(button=>button.onclick=()=>{$$('[data-weekly]').forEach(x=>x.classList.remove('active'));button.classList.add('active');state.weeklyFolder=button.dataset.weekly;load()});
document.addEventListener('click',e=>{const chip=e.target.closest('.company-chip');if(!chip)return;state.reportCompany=chip.dataset.company;if(state.reportType==='위클리'){state.reportType='';state.weeklyFolder='';$$('[data-type]').forEach(x=>x.classList.toggle('active',x.dataset.type===''));$$('[data-weekly]').forEach(x=>x.classList.toggle('active',x.dataset.weekly===''));$('#weekly-folders').hidden=true;$('#report-company').hidden=false}view('reports');load()});
load().catch(e=>document.body.insertAdjacentHTML('beforeend',`<p class="empty">데이터를 불러오지 못했습니다: ${esc(e.message)}</p>`));
// URL 해시로 특정 뷰 바로 열기(예: /#tone → 리서치 톤을 별도 창으로). 로드 후 해시가 바뀌어도 반영.
function applyHashView(){const hashView=decodeURIComponent(location.hash.slice(1));if(hashView&&document.getElementById(hashView)?.classList.contains('view'))view(hashView)}
applyHashView();window.addEventListener('hashchange',applyHashView);
// 새 배포 감지: 오래 열어둔 탭이 빌드 시점 데이터에 얼어붙는 것 방지. 백그라운드 탭은 조용히 리로드, 보고 있으면 배너로 안내.
const LOADED_VERSION=window.__DASHBOARD_DATA__?.summary?.updated_at||'';
async function checkNewDeploy(){if(!LOADED_VERSION||!/^http/.test(location.protocol))return;try{const r=await fetch(`version.json?t=${Date.now()}`,{cache:'no-store'});if(!r.ok)return;const v=await r.json();if(!v.updated_at||v.updated_at<=LOADED_VERSION)return;if(document.hidden){location.reload();return}if($('#fresh-banner'))return;const b=document.createElement('div');b.id='fresh-banner';b.style.cssText='position:fixed;bottom:16px;right:16px;z-index:999;background:#1c2733;color:#fff;padding:10px 14px;border-radius:10px;box-shadow:0 4px 14px rgba(0,0,0,.35);font-size:13px;display:flex;gap:10px;align-items:center';b.innerHTML='새 데이터가 배포되었습니다.<button style="background:#3b82f6;color:#fff;border:0;border-radius:6px;padding:5px 10px;cursor:pointer">새로고침</button>';b.querySelector('button').onclick=()=>location.reload();document.body.appendChild(b)}catch{}}
setInterval(checkNewDeploy,15*60*1000);
