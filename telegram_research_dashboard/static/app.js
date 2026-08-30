const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const dateValue=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
const today=new Date(),weekAgo=new Date(today);weekAgo.setDate(today.getDate()-7);
const state={q:'',reportCompany:'',newsCompany:'',newsQ:'',reportType:'',weeklyFolder:'',pressStart:dateValue(weekAgo),pressEnd:dateValue(today),pressCompany:'',pressRows:[],reports:[],news:[],companies:[],reportCompanies:[],repFrom:'',repTo:'',repDays:0,repSort:''};
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
function reportRow(r){const kind=r.report_type||'기업분석',kindClass=kind==='산업분석'?'industry':kind==='위클리'?'weekly':'';const names=(r.company_names?.length?r.company_names:String(r.companies_label||r.company_name||'').split(',').map(s=>s.trim())).filter(Boolean);const label=names.length?names.map(n=>`<button type="button" class="company-chip" data-company="${esc(n)}" title="${esc(n)} 자료만 모아보기">${esc(n)}</button>`).join(''):`<b>${esc(kind==='산업분석'||kind==='위클리'?'산업 자료':'기업 미확인')}</b>`;const links=[r.source_url?`<a href="${esc(r.source_url)}" target="_blank" rel="noopener">텔레그램 ↗</a>`:'',r.original_url?`<a href="${esc(r.original_url)}" target="_blank" rel="noopener">리포트 ↗</a>`:''].filter(Boolean).join('')||'<span class="no-link">—</span>';const tag=r.target_change&&r.target_change!=='미확인'?`<span class="tag ${r.target_change==='상향'?'up':r.target_change==='하향'?'down':''}">${esc(r.target_change)}</span>`:'';return `<div class="research-row"><small>${fmtDate(r.posted_at)}</small><div class="row-title"><span class="report-kind ${kindClass}">${esc(kind)}</span>${r.weekly_folder?`<span class="weekly-source">${esc(r.weekly_folder)}</span>`:''}${label}</div><div class="row-main"><p>${esc(r.title)}</p>${r.needs_review?'<span class="review">검토 필요</span>':''}</div><div class="row-links">${links}</div><span class="price">${tag}${won(r.target_price)}${r.target_price&&r.previous_target_price>=1000&&r.previous_target_price!==r.target_price?`<small class="prev-price">(직전 ${Number(r.previous_target_price).toLocaleString()})</small>`:''}</span></div>`}
/* ── GS 산출물 표: DAOL 톤 보드의 pub-table 레이아웃 이식 ──
   행별 톤 필드(r.tone: one_line·points·tp_reasons·earn)는 빌드 때 tone_market.py가
   다올 톤 보드 데이터를 매칭해 붙이고, 종목별 시장 스냅샷(내 영업이익 추정 vs 컨센,
   타사 TP MAX/MIN/중앙값·커버 증권사 수)은 payload.market으로 내려온다. */
const MARKET=()=>window.__DASHBOARD_DATA__?.market||{};
const fmtEok=v=>v==null?'—':Math.abs(v)>=10000?(v/10000).toFixed(1).replace(/\.0$/,'')+'조':Math.round(v).toLocaleString()+'억';
const fmtTPman=v=>v==null?'—':v>=10000?(Math.round(v/100)/100).toLocaleString()+'만':Number(v).toLocaleString();
const yymmdd=s=>{const d=new Date(s);return `${String(d.getFullYear()).slice(2)}.${String(d.getMonth()+1).padStart(2,'0')}.${String(d.getDate()).padStart(2,'0')}`};
// 컨센·시장TP를 붙일 대상 종목. 태그가 2개 이상이어도 톤이 지목한 대표 종목(tone.co)이
// 태그 안에 있으면 그걸 쓴다 — 예: 한화에어로 2Q26 리뷰에 한화오션이 같이 태깅된 경우.
// 산업분석은 제외를 유지한다. 날짜 폴백 매칭이 같은 날 종목 노트에 잘못 걸릴 수 있어서다.
function singleCompany(r){const names=r.company_names||[];
 if(r.report_type!=='기업분석')return null;
 const co=r.tone?.co;
 return co&&names.includes(co)?co:(names.length===1?names[0]:null)}
function opConsCell(r){const name=singleCompany(r),m=name?MARKET()[name]:null;
 if(!m||(!m.cons&&!m.mine))return '<span class="no-link">—</span>';
 const yr=l=>String(l||'').slice(0,4),cons=m.cons||{},mine=m.mine,cy=cons.this,rows=[];
 if(cy){const match=mine&&yr(mine.label)===yr(cy.label);const diff=match&&cy.op?Math.round((mine.op/cy.op-1)*1000)/10:null;
  rows.push(`<span class="oc-line"><em>${yr(cy.label).slice(2)}E</em>${match?` 나 <b>${fmtEok(mine.op)}</b> · 컨 ${fmtEok(cy.op)}${diff!=null?` <i class="${diff>=0?'up':'down'}">${diff>0?'+':''}${diff}%</i>`:''}`:` 컨 ${fmtEok(cy.op)}`}</span>`)}
 if(cons.next)rows.push(`<span class="oc-line"><em>${yr(cons.next.label).slice(2)}E</em> 컨 ${fmtEok(cons.next.op)}</span>`);
 if(mine&&(!cy||yr(mine.label)!==yr(cy.label)))rows.push(`<span class="oc-line oc-stale"><em>${esc(mine.label||'')}</em> 나 ${fmtEok(mine.op)}</span>`);
 if(!rows.length)return '<span class="no-link">—</span>';
 const tip=[mine?`내 추정: ${mine.date} 리포트에서 추출${mine.diff_at_pct!=null?` (당시 컨센 대비 ${mine.diff_at_pct>0?'+':''}${mine.diff_at_pct}%)`:''}`:'',cons.asof?`컨센 스냅샷: ${cons.asof} (KOSPI 컨센 트래커, 억원)`:''].filter(Boolean).join('\n');
 return `<div class="oc-cell" title="${esc(tip)}">${rows.join('')}</div>`}
function streetCell(r){const name=singleCompany(r),st=name?(MARKET()[name]||{}).street:null;
 if(!st)return '<span class="no-link">—</span>';
 const tip=`타사 TP (한경 에이셀 60일 · ~${st.asof})\n${(st.brokers||[]).join(', ')}${st.daol?`\n다올 ${Number(st.daol).toLocaleString()}원${st.daol_pct!=null?` — 타사 ${st.n}곳 중 상위 ${100-st.daol_pct}%`:''}`:''}`;
 return `<div class="oc-cell" title="${esc(tip)}"><span class="oc-line">↑${fmtTPman(st.max)} · <b>중 ${fmtTPman(st.median)}</b> · ↓${fmtTPman(st.min)}</span><small>${st.n}개사 커버${st.daol?` · 다올 ${fmtTPman(st.daol)}`:''}</small></div>`}
function repRank(r,key){const t=r.tone||{};
 if(key==='tp')return ['상향','하향'].includes(r.target_change)?2:(r.target_price?1:0);
 if(key==='earn')return ['상향','하향'].includes(t.earn)?1:0;
 if(key==='pts')return (t.points||[]).length?1:0;
 if(key==='est')return t.est||MARKET()[singleCompany(r)]?.mine?1:0;
 return 0}
function reportTableRow(r){const t=r.tone||{},kind=r.report_type||'기업분석';
 const kindCell=kind==='위클리'?`<span class="rep-kind strat">위클리</span>${r.weekly_folder?`<div class="rep-sub">${esc(r.weekly_folder)}</div>`:''}`:kind==='산업분석'?'<span class="rep-kind ind">산업</span>':'<span class="rep-kind co">기업</span>';
 const names=(r.company_names?.length?r.company_names:String(r.companies_label||r.company_name||'').split(',').map(s=>s.trim())).filter(Boolean);
 // 위클리는 거의 전 커버리지가 언급돼 기업 칩이 노이즈 — 표기 생략.
 const company=kind==='위클리'?'<span class="no-link">—</span>':names.map(n=>`<button type="button" class="company-chip" data-company="${esc(n)}" title="${esc(n)} 자료만 모아보기">${esc(n)}</button>`).join('')||'<span class="no-link">—</span>';
 const dir=r.target_change,cls=dir==='상향'?'up':dir==='하향'?'down':'';
 let tp='<span class="no-link">—</span>';
 if(r.target_price){const prev=r.previous_target_price>=1000&&r.previous_target_price!==r.target_price?`<small>직전 ${Number(r.previous_target_price).toLocaleString()}</small>`:'';
  tp=`<span class="rep-tp ${cls}">${dir==='상향'?'▲':dir==='하향'?'▼':'●'} ${Number(r.target_price).toLocaleString()}원</span>${prev}`}
 else if(dir==='상향'||dir==='하향')tp=`<span class="rep-tp ${cls}">${dir==='상향'?'▲':'▼'} ${dir}</span>`;
 const reasons=(t.tp_reasons||[]).map(x=>`<i class="tp-reason">${esc(x)}</i>`).join('');
 const opinion=r.opinion?`<div class="rep-sub">${esc(r.opinion)}</div>`:'';
 const earn=['상향','하향'].includes(t.earn)?`<span class="${t.earn==='상향'?'pub-up':'pub-down'}" title="${esc(t.earn_ev||'')}">${t.earn==='상향'?'▲':'▼'}</span>`:'<span class="no-link">—</span>';
 const pts=(t.points||[]).length?t.points.slice(0,3).map(x=>`<span class="pt-chip">${esc(x)}</span>`).join(''):'<span class="no-link">—</span>';
 const url=r.original_url||r.source_url;
 const title=`${url?`<a class="rep-title" href="${esc(url)}" target="_blank" rel="noopener">${esc(r.title)}</a>`:`<span class="rep-title">${esc(r.title)}</span>`}${t.one_line?`<div class="rep-desc">${esc(t.one_line)}</div>`:''}${r.needs_review?'<span class="review">검토 필요</span>':''}`;
 const links=[r.source_url?`<a class="table-link telegram-link" href="${esc(r.source_url)}" target="_blank" rel="noopener">텔레그램 ↗</a>`:'',r.original_url?`<a class="table-link" href="${esc(r.original_url)}" target="_blank" rel="noopener">리포트 ↗</a>`:''].filter(Boolean).join('')||'<span class="no-link">—</span>';
 return `<tr><td>${kindCell}</td><td class="news-date">${yymmdd(r.posted_at)}</td><td class="rep-co">${company}</td><td class="rep-titlec">${title}</td><td class="rep-pts" data-th="투자포인트">${pts}</td><td class="rep-tpc" data-th="적정주가">${tp}${opinion}${reasons?`<div class="rep-rsn"${t.tp_ev?` title="TP 조정 근거 (톤 보드 AI 추출)&#10;${esc(t.tp_ev)}"`:''}>${reasons}</div>`:''}</td><td class="rep-earn" data-th="실적">${earn}</td><td class="rep-est" data-th="영업이익 나 vs 컨센">${opConsCell(r)}</td><td class="rep-street" data-th="시장 TP">${streetCell(r)}</td><td class="rep-links">${links}</td></tr>`}
function renderReportTable(){const box=$('#report-table');if(!box)return;
 const todayStr=dateValue(new Date());
 let from=state.repFrom,to=state.repTo||todayStr;
 if(!from&&state.repDays){const d=new Date();d.setDate(d.getDate()-state.repDays);from=dateValue(d)}
 let list=state.reports.filter(r=>{if(!from)return true;const day=dateValue(new Date(r.posted_at));return day>=from&&day<=to});
 if(state.repSort)list=[...list].sort((a,b)=>repRank(b,state.repSort)-repRank(a,state.repSort)||new Date(b.posted_at)-new Date(a.posted_at));
 const presets=[[0,'전체'],[7,'주간'],[30,'월간'],[90,'분기'],[180,'반기']];
 const bar=`<div class="rep-range"><input type="date" id="rep-from" value="${from||''}" max="${todayStr}"><span>~</span><input type="date" id="rep-to" value="${to}" max="${todayStr}">${presets.map(([d,l])=>`<button type="button" class="rep-preset${!state.repFrom&&state.repDays===d?' on':''}" data-days="${d}">${l}</button>`).join('')}<strong>${list.length.toLocaleString()}건${state.repSort?' · 정렬됨':''}</strong></div>`;
 const ind=k=>state.repSort===k?' ▼':'';
 box.innerHTML=bar+(list.length?`<div class="rep-wrap"><table class="rep-table"><colgroup><col class="c-kind"><col class="c-date"><col class="c-co"><col><col class="c-pts"><col class="c-tp"><col class="c-earn"><col class="c-est"><col class="c-street"><col class="c-links"></colgroup><thead><tr><th>구분</th><th>날짜${state.repSort?'':' ▼'}</th><th>기업</th><th>제목 · 설명</th><th id="th-rp-pts" class="th-sort" title="투자포인트 있는 것 우선">투자포인트${ind('pts')}</th><th id="th-rp-tp" class="th-sort" title="적정주가 변경 우선 정렬">적정주가${ind('tp')}</th><th id="th-rp-earn" class="th-sort" title="실적추정 방향 있는 것 우선">실적${ind('earn')}</th><th id="th-rp-est" class="th-sort" title="내 추정·컨센 있는 것 우선">영업이익 나 vs 컨센${ind('est')}</th><th title="타사 TP 최고/중앙/최저 · 커버 증권사 수 (한경 에이셀 60일)">시장 TP</th><th>링크</th></tr></thead><tbody>${list.map(reportTableRow).join('')}</tbody></table></div>`:'<p class="empty">조건에 맞는 보고서가 없습니다.</p>');
 const rf=$('#rep-from'),rt=$('#rep-to');
 const applyRange=()=>{state.repFrom=rf.value;state.repTo=rt.value;renderReportTable()};
 if(rf)rf.onchange=applyRange;if(rt)rt.onchange=applyRange;
 box.querySelectorAll('.rep-preset').forEach(b=>b.onclick=()=>{state.repFrom='';state.repTo='';state.repDays=+b.dataset.days;renderReportTable()});
 box.querySelectorAll('.th-sort').forEach(th=>th.onclick=()=>{const key={'th-rp-tp':'tp','th-rp-earn':'earn','th-rp-est':'est','th-rp-pts':'pts'}[th.id];if(!key)return;state.repSort=state.repSort===key?'':key;renderReportTable()})}
function newsCard(n){return `<article class="news-card"><small>${fmtDate(n.posted_at)} · ${esc(n.industry||n.event_type)}</small><h3>${esc(n.title)}</h3><p class="tag">${esc(n.companies_label||n.company_name||'기업 미확인')}</p>${n.article_url?`<a href="${esc(n.article_url)}" target="_blank" rel="noopener">기사 원문 ↗</a>`:''}${n.source_url?` · <a href="${esc(n.source_url)}" target="_blank" rel="noopener">텔레그램 ↗</a>`:''}</article>`}
function newsTable(list){return `<div class="news-table-wrap"><table class="news-table"><colgroup><col class="date-col"><col class="company-col"><col><col class="publisher-col"><col class="comment-col"><col class="link-col"><col class="telegram-col"></colgroup><thead><tr><th>날짜</th><th>기업명</th><th>제목</th><th>출처(언론사)</th><th>내 코멘트</th><th>링크</th><th>텔레그램 링크</th></tr></thead><tbody>${list.map(n=>`<tr><td class="news-date">${fmtDate(n.posted_at)}</td><td>${(n.company_names?.length?n.company_names:String(n.companies_label||n.company_name||'').split(',').map(s=>s.trim())).filter(Boolean).map(name=>`<button type="button" class="news-company-chip${state.newsCompany===name?' active':''}" data-company="${esc(name)}" title="${esc(name)} 뉴스만 보기 (다시 누르면 해제)">${esc(name)}</button>`).join('')||'<span class="company-label">기업 미확인</span>'}</td><td class="news-title">${esc(n.title)}</td><td>${esc(pressPublisher(n))}</td><td class="news-comment">${n.comment?`<div class="comment-clip" title="${esc(n.comment)}">${esc(n.comment)}</div>`:'<span class="no-link">N/A</span>'}</td><td>${n.article_url?`<a class="table-link" href="${esc(n.article_url)}" target="_blank" rel="noopener" aria-label="기사 원문 열기">기사 ↗</a>`:'<span class="no-link">—</span>'}</td><td>${n.source_url?`<a class="table-link telegram-link" href="${esc(n.source_url)}" target="_blank" rel="noopener" aria-label="텔레그램 원문 열기">텔레그램 ↗</a>`:'<span class="no-link">—</span>'}</td></tr>`).join('')}</tbody></table></div>`}
function pressSector(n){const industry=n.industry||'',text=`${n.companies_label||n.company_name||''} ${n.title||''}`;if(industry==='조선'||['해양','LNG','가스선','컨테이너','탱커'].includes(industry))return '조선';if(industry==='방산')return '방산';if(industry==='기계'||industry==='건설기계')return '건설기계';if(/HD건설기계|현대건설기계|두산밥캣|두산인프라|디벨론|굴착기|건설기계/.test(text))return '건설기계';if(/한화오션|HD현대중공업|HD한국조선해양|삼성중공업|HD현대미포|K조선|HJ중공업|대한조선|조선|선박|VLCC|LNG선|컨테이너선/.test(text))return '조선';if(/KAI|한국항공우주|한화에어로|한화시스템|현대로템|LIG|풍산|방산|KF-21|K9|K2|천궁|자주포|전투기|미사일|고스트로보틱스|로봇개/.test(text))return '방산';return null}
function pressPublisher(n){if(n.publisher)return n.publisher;try{const host=new URL(n.article_url).hostname.replace(/^(www\.|m\.)/,'');const names={'yna.co.kr':'연합뉴스','news1.kr':'뉴스1','theguru.co.kr':'더구루','hankyung.com':'한국경제','mk.co.kr':'매일경제','sedaily.com':'서울경제','edaily.co.kr':'이데일리','mt.co.kr':'머니투데이','fnnews.com':'파이낸셜뉴스','chosun.com':'조선일보','joongang.co.kr':'중앙일보','donga.com':'동아일보','eurasiantimes.com':'EurAsian Times','reuters.com':'Reuters'};return Object.entries(names).find(([d])=>host===d||host.endsWith('.'+d))?.[1]||host}catch{return '미확인'}}
function isPressArticle(url){try{return !['t.me','telegram.me','www.t.me'].includes(new URL(url).hostname.toLowerCase())}catch{return false}}
function pressCompany(n){return n.companies_label||n.company_name||'기업 미확인'}
function pressCompanyNames(n){return (n.company_names?.length?n.company_names:String(n.companies_label||n.company_name||'').split(',').map(s=>s.trim())).filter(Boolean)}
// 애널리스트 관점 중요도. A=투자판단 직결(수주·실적·수출·M&A·자사주 등), C=지역/정치/일반동향, B=그 외.
const IMP_A=/수주|수요|계약|낙찰|발주|신조|건조|인도|수출|매각|양수도|인수|합병|지분|증설|투자\s?계획|목표주가|투자의견|목표가|실적|영업이익|어닝|잠정실적|자사주|배당|유상증자|MRO|정비사업|잠수함|구축함|프리깃|호위함|KF-?21|FA-?50|천궁|자주포|K9|굴착기.*판매|조\s?원|억\s?달러|조원\s?규모/;
const IMP_C=/노조|파업|집회|도의회|시의회|국회|청원|규탄|촉구|건의|해명|논란|의혹|칼럼|기고|사설|부고|동정|인사\s|축사|방문|간담회|행사|위촉|선임\s|임명|루머|기대감|가능성|전망\s?…|주가\s?전망/;
function pressImportance(n){const t=`${pressCompany(n)} ${n.title||''}`;if(IMP_A.test(t))return'A';if(IMP_C.test(t))return'C';return'B'}
function sortPress(a,b){const sectorOrder={조선:0,방산:1,건설기계:2},sector=(sectorOrder[a.press_sector]??9)-(sectorOrder[b.press_sector]??9);if(sector)return sector;const ac=pressCompany(a),bc=pressCompany(b);if(ac==='기업 미확인'&&bc!=='기업 미확인')return 1;if(bc==='기업 미확인'&&ac!=='기업 미확인')return -1;const company=ac.localeCompare(bc,'ko');if(company)return company;const date=new Date(b.posted_at)-new Date(a.posted_at);return date||String(a.title).localeCompare(String(b.title),'ko')}
function renderPressTable(){const start=$('#press-start').value,end=$('#press-end').value;
 // 기업 칩 필터 중이면 해제 버튼("회사명 ✕")을 보여준다 — 재클릭 해제는 눈에 안 보여서.
 const clearBtn=$('#press-clear');if(clearBtn){clearBtn.hidden=!state.pressCompany;clearBtn.textContent=state.pressCompany?`${state.pressCompany} ✕`:''}
 if(start>end){state.pressRows=[];$('#press-table').innerHTML='<p class="empty">시작일이 종료일보다 늦습니다.</p>';$('#press-count').textContent='0건';return}state.pressStart=start;state.pressEnd=end;
 // 보도기사 취합은 아카이브 검색어(newsQ)·기업 필터·통합검색(q)과 무관하게 전체 뉴스에서 날짜로만 거른다.
 // (state.news를 쓰면 아카이브에서 검색해 둔 상태일 때 날짜를 바꿔도 목록이 안 변하는 것처럼 보인다.)
 const list=(state.allNews||state.news).map(n=>({...n,press_sector:pressSector(n)})).filter(n=>{const day=dateValue(new Date(n.posted_at));return isPressArticle(n.article_url)&&n.press_sector&&day>=start&&day<=end&&(!state.pressCompany||pressCompanyNames(n).includes(state.pressCompany))}).sort(sortPress);state.pressRows=list;$('#press-count').textContent=`${list.length.toLocaleString()}건${state.pressCompany?` · ${state.pressCompany}`:''}`;$('#press-table').innerHTML=list.length?`<div class="news-table-wrap"><table class="press-table"><colgroup><col class="sector-col"><col class="press-company-col"><col class="press-date-col"><col class="imp-col"><col><col class="publisher-col"><col class="press-link-col"></colgroup><thead><tr><th>섹터</th><th>기업명</th><th>기사일자</th><th>중요도</th><th>기사제목</th><th>출처(언론사)</th><th>기사링크</th></tr></thead><tbody>${list.map(n=>{const imp=pressImportance(n);return `<tr><td><span class="sector-label sector-${n.press_sector}">${n.press_sector}</span></td><td>${pressCompanyNames(n).map(name=>`<button type="button" class="press-company-chip${state.pressCompany===name?' active':''}" data-company="${esc(name)}" title="${esc(name)} 보도만 보기 (다시 누르면 해제)">${esc(name)}</button>`).join('')||'<span class="company-label">기업 미확인</span>'}</td><td class="news-date">${fmtDate(n.posted_at)}</td><td><span class="imp-badge imp-${imp}">${imp}</span></td><td class="news-title">${esc(n.title)}</td><td>${esc(pressPublisher(n))}</td><td><a class="table-link" href="${esc(n.article_url)}" target="_blank" rel="noopener">기사 ↗</a></td></tr>`}).join('')}</tbody></table></div>`:'<p class="empty">선택한 기간에 해당하는 보도기사가 없습니다.</p>'}
function exportPressExcel(){if(!state.pressRows.length){alert('다운로드할 보도기사가 없습니다.');return}const cell=value=>`"${String(value??'').replace(/"/g,'""')}"`;const rows=[['섹터','기업명','기사일자','중요도','기사제목','출처(언론사)','기사링크'],...state.pressRows.map(n=>[n.press_sector,pressCompany(n),dateValue(new Date(n.posted_at)),pressImportance(n),n.title,pressPublisher(n),n.article_url])];const csv='\ufeff'+rows.map(row=>row.map(cell).join(',')).join('\r\n');const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'})),link=document.createElement('a');link.href=url;link.download=`보도기사_${state.pressStart}_${state.pressEnd}.csv`;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)}
/* ── DAOL 리서치 톤: 독립 프로그램(daol-research-tone)으로 분리 — iframe + 요약 fetch ── */
const TONE_SITE='https://gschoie.github.io/DAOL-RESEARCH-TONE/';
function loadToneFrame(){const f=$('#tone-frame');if(f&&!f.getAttribute('src'))f.src=TONE_SITE+'?t='+Date.now()}
async function fetchToneSummary(){const box=$('#tone-latest');if(!box)return;
 try{const r=await fetch(TONE_SITE+'tone_summary.json?t='+Date.now(),{cache:'no-store'});if(!r.ok)throw 0;
  const s=await r.json();box.innerHTML=(s.latest||[]).slice(0,8).map(overviewTone).join('')||'<p class="empty">톤 데이터가 없습니다.</p>'}
 catch{box.innerHTML=`<p class="empty">톤 보드에서 확인 → <a href="${TONE_SITE}" target="_blank" rel="noopener">daol-research-tone ↗</a></p>`}}
function miniRow(lead,body,href){return `<a class="mini-row" href="${esc(href||'#')}" target="_blank" rel="noopener">${lead}<div>${body}</div></a>`}
function overviewNews(n){return `<a class="mini-line" href="${esc(n.article_url||n.source_url||'#')}" target="_blank" rel="noopener"><small>${esc(fmtDate(n.posted_at))}</small><b>${esc(n.companies_label||n.company_name||'기업 미확인')}</b><span>${esc(n.title)}</span></a>`}
function overviewReport(r){const kind=r.report_type||'기업분석',kindClass=kind==='산업분석'?'industry':kind==='위클리'?'weekly':'';const who=r.companies_label||r.company_name||(kind==='기업분석'?'기업 미확인':'산업 자료');const tag=r.target_change&&r.target_change!=='미확인'?`<span class="tag ${r.target_change==='상향'?'up':r.target_change==='하향'?'down':''}">${esc(r.target_change)}</span>`:'';return `<a class="mini-line" href="${esc(r.original_url||r.source_url||'#')}" target="_blank" rel="noopener"><small>${esc(fmtDate(r.posted_at))}</small><span class="report-kind ${kindClass}">${esc(kind)}</span><b>${esc(who)}</b><span>${esc(r.title)}</span>${tag}</a>`}
function overviewTone(r){const op=r.opinion&&!['명시 없음','없음',''].includes(r.opinion)?`<span class="tag">${esc(r.opinion)}</span>`:'';const tp=r.tp_dir==='상향'?'<span class="tag up">TP▲</span>':r.tp_dir==='하향'?'<span class="tag down">TP▼</span>':'';return `<a class="mini-line" href="${esc(r.pdf_url||r.post_url||'#')}" target="_blank" rel="noopener"><small>${esc(String(r.date||'').slice(5))}</small><b class="tone-co" data-co="${esc(r.company_key||r.company||'')}" title="리서치 톤에서 이 기업 분석 열기">${esc(r.company||'')}</b><span>${esc(r.title||'')}</span>${op}${tp}</a>`}
/* 오늘의요약 톤 패널: 기업명 클릭 → 리서치 톤 화면으로 전환해 해당 기업 팝업을 연다(해시 딥링크) */
document.addEventListener('click',e=>{const co=e.target.closest('#tone-latest .tone-co');if(!co||!co.dataset.co)return;e.preventDefault();e.stopPropagation();view('tone');const f=$('#tone-frame');if(f)f.src=TONE_SITE+'?t='+Date.now()+'#co='+encodeURIComponent(co.dataset.co)});
function overviewUnion(p){return `<a class="mini-line" href="${esc(p.url||'#')}" target="_blank" rel="noopener"><b class="rk-s">${p.rank}</b><span>${esc(p.title)}</span><small>조회 ${Number(p.views).toLocaleString()} · 댓글 ${p.comments}</small></a>`}
function overviewMacro(x,i){return miniRow(`<b class="rk">${i+1}</b>`,`<p class="mini-title">${esc(x.title)}</p>`,x.url)}
const MACRO_ENDPOINT='https://script.google.com/macros/s/AKfycbxNClBzJoE35VSwcCNgMEJ_PvFCBphH87g4gq7xDiGXhO5x-fd-IMpNL6Ly0oURJzEN/exec';/* 네이버 Top5 실시간 JSON(GAS). 비면 배포 데이터만 사용 */
const decodeEnt=s=>{const t=document.createElement('textarea');t.innerHTML=s||'';return t.value};
async function fetchLiveMacro(){if(!MACRO_ENDPOINT)return;try{const r=await fetch(MACRO_ENDPOINT,{cache:'no-store'});if(!r.ok)return;const d=await r.json();const items=(d.global_economy||d.items||[]).map(x=>({title:decodeEnt(x.title),url:x.url}));if(items.length&&$('#macro-global'))$('#macro-global').innerHTML=items.slice(0,7).map(overviewMacro).join('')}catch{}}
async function load(){
 const reportQs=new URLSearchParams({q:state.q,company:state.reportCompany,type:state.reportType,weekly:state.weeklyFolder});
 const newsQs=new URLSearchParams({q:state.q,nq:state.newsQ,company:state.newsCompany});
 const [sum,reports,news,newsAll,companies,reportCompanies,weeklyReports]=await Promise.all([json('/api/summary'),json('/api/reports?'+reportQs),json('/api/news?'+newsQs),json('/api/news'),json('/api/companies'),json('/api/report-companies'),json('/api/reports?type=위클리')]);
 state.reports=reports;state.news=news;state.allNews=newsAll;state.companies=companies;state.reportCompanies=reportCompanies;
 $('#press-start').value=state.pressStart;$('#press-end').value=state.pressEnd;
 $('#updated-at').textContent=sum.updated_at?new Intl.DateTimeFormat('ko-KR',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(sum.updated_at)):'미확인';
 $('#weekly-all-count').textContent=`${weeklyReports.length}건`;$('#weekly-daol-count').textContent=`${weeklyReports.filter(r=>r.weekly_folder==='다올선박').length}건`;$('#weekly-kis-count').textContent=`${weeklyReports.filter(r=>r.weekly_folder==='한투시절').length}건`;$('#weekly-hi-count').textContent=`${weeklyReports.filter(r=>r.weekly_folder==='하이투자증권시절').length}건`;
 $('#latest-reports').innerHTML=reports.slice(0,8).map(overviewReport).join('')||'<p class="empty">수집된 보고서가 없습니다.</p>';
 renderReportTable();
 $('#latest-news').innerHTML=news.slice(0,10).map(overviewNews).join('')||'<p class="empty">수집된 뉴스가 없습니다.</p>';
 fetchToneSummary();
 const unionTop=window.__DASHBOARD_DATA__?.union?.monthly||[];
 if($('#union-top'))$('#union-top').innerHTML=unionTop.slice(0,10).map(overviewUnion).join('')||'<p class="empty">노조게시판 데이터가 없습니다.</p>';
 const macro=window.__DASHBOARD_DATA__?.macro||{};
 if($('#macro-global'))$('#macro-global').innerHTML=(macro.global_economy||[]).slice(0,7).map(overviewMacro).join('')||'<p class="empty">매크로 데이터가 없습니다.</p>';
 fetchLiveMacro();
 const brief=$('#daily-brief');if(brief){const gm='https://gemini.google.com/app/dc1cee4fd9194007?usp=sharing';const body=macro.daily_brief?esc(macro.daily_brief).replace(/\n/g,'<br>'):'<span class="brief-empty">아직 핵심요약이 없습니다. GMN.글로벌방산 문서에 붙여넣으면 여기 표시됩니다.</span>';brief.innerHTML=`<div class="brief-head"><small>GEMINI · 오늘의 핵심요약</small><a href="${gm}" target="_blank" rel="noopener">Gemini 열기 →</a></div><div class="brief-body">${body}</div>`}
 const dbe=$('#defense-brief');if(dbe){const db=window.__DASHBOARD_DATA__?.defenseBrief;if(db&&db.summary){const body=db.summary.split('\n').map(l=>l.trim()).filter(Boolean).map(l=>l.startsWith('## ')?'━ '+l.replace(/^#+\s*/,'').split('—')[0].trim():l.replace(/^\*+\s+/,'• ')).join('\n');dbe.innerHTML=`<div class="brief-head"><small>🌍 글로벌 방산 데일리 브리핑${db.date?' · '+esc(db.date)+(d=>isNaN(d)?'':`(${'일월화수목금토'[d.getDay()]})`)(new Date(db.date+'T00:00:00')):''}</small><a href="defense_briefing_report.html" target="_blank" rel="noopener">전체 브리핑 →</a></div><div class="brief-body">${esc(body).replace(/\n/g,'<br>')}</div>`;dbe.style.display='';}else{dbe.style.display='none';}}
 const cbe=$('#claude-brief');if(cbe){const cb=window.__DASHBOARD_DATA__?.claudeBrief;if(cb&&cb.summary){const body=cb.summary.split('\n').map(l=>l.trim()).filter(Boolean).map(l=>l.startsWith('## ')?'━ '+l.replace(/^#+\s*/,'').split('—')[0].trim():l.replace(/^\*+\s+/,'• ')).join('\n');cbe.innerHTML=`<div class="brief-head"><small>🤖 Claude 방산 브리핑${cb.date?' · '+esc(cb.date)+(d=>isNaN(d)?'':`(${'일월화수목금토'[d.getDay()]})`)(new Date(cb.date+'T00:00:00')):''}</small><a href="claude_defense_report.html" target="_blank" rel="noopener">전체 브리핑 →</a></div><div class="brief-body">${esc(body).replace(/\n/g,'<br>')}</div>`;cbe.style.display='';}else{cbe.style.display='none';}}
 const nbe=$('#construction-brief');if(nbe){const nb=window.__DASHBOARD_DATA__?.constructionBrief;if(nb&&nb.summary){const body=nb.summary.split('\n').map(l=>l.trim()).filter(Boolean).map(l=>l.startsWith('## ')?'━ '+l.replace(/^#+\s*/,'').split('—')[0].trim():l.replace(/^\*+\s+/,'• ')).join('\n');nbe.innerHTML=`<div class="brief-head"><small>🏗️ 글로벌 건설기계 데일리 브리핑${nb.date?' · '+esc(nb.date)+(d=>isNaN(d)?'':`(${'일월화수목금토'[d.getDay()]})`)(new Date(nb.date+'T00:00:00')):''}</small><a href="construction_briefing_report.html" target="_blank" rel="noopener">전체 브리핑 →</a></div><div class="brief-body">${esc(body).replace(/\n/g,'<br>')}</div>`;nbe.style.display='';}else{nbe.style.display='none';}}
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
const TASK_ROSTER=[['팀장',['최광식','이준범']],['지속가능(Sustainability)',['박영도','김지원','이정우','김진영']],['지능화(Intelligence)',['유지웅','고영민','김혜영','김연미','김상혁']],['휴먼/생체(Human)',['이지수','박종현','이다연','임도영','박소현','한수빈']]];
const TASK_ITEMS_DEFAULT=['근태입력','휴가계획','자료제출','컴플라이언스','기타'],TASK_KEY='hi_tasklist_v1',TASK_ITEMS_KEY='hi_tasklist_items_v1',TASK_LAST_KEY='hi_tasklist_last_v1';
/* 서버 덮어쓰기 가드: 이 브라우저(도메인)가 서버 번들을 한 번이라도 받아본 뒤에만 push를 허용.
   도메인 이관 직후 빈 localStorage 상태에서의 조작이 GAS 사본을 빈 목록으로 덮던 사고(8/18) 방지. */
const SYNC_SEEDED_KEY='hi_sync_seeded_v1';
const syncSeeded=()=>{try{localStorage.setItem(SYNC_SEEDED_KEY,'1')}catch{}};
const TASK_ENDPOINT='https://script.google.com/macros/s/AKfycbwTX-Ld-ayqHgi97S0QiMYPsHfb2cjNwy66FyDYU6GBrS0kOgMH8KE220GPy3KRxcT3/exec';let taskPushT;
function taskItems(){try{const a=JSON.parse(localStorage.getItem(TASK_ITEMS_KEY));if(Array.isArray(a)&&a.length)return a}catch{}return TASK_ITEMS_DEFAULT.slice()}
function saveItems(a){try{localStorage.setItem(TASK_ITEMS_KEY,JSON.stringify(a))}catch{}taskPush()}
function taskArchived(){const a=taskLoad().__archived;return Array.isArray(a)?a.filter(x=>taskItems().includes(x)):[]}/* 보관함: 항목 이름 목록 — 기록(data)은 건드리지 않아 복원 시 그대로 */
function fillTaskItems(desired){const sel=$('#task-item');if(!sel)return;const items=taskItems(),arch=taskArchived(),active=items.filter(x=>!arch.includes(x));let last=null;try{last=localStorage.getItem(TASK_LAST_KEY)}catch{}
 // 항목 우선순위: 명시 지정 > 화면에서 고른 값 > 마지막 사용 항목(재방문 시 근태입력으로 리셋 방지) > 첫 활성 항목
 const cur=items.includes(desired)?desired:(items.includes(sel.value)?sel.value:(items.includes(last)?last:(active[0]||items[0])));
 const opt=x=>`<option ${x===cur?'selected':''}>${esc(x)}</option>`;
 sel.innerHTML=active.map(opt).join('')+(arch.includes(cur)?`<optgroup label="📦 보관함">${opt(cur)}</optgroup>`:'');
 const ab=$('#task-archive');if(ab)ab.textContent=arch.includes(cur)?'보관 해제':'보관';
 const box=$('#task-archive-box');if(box){box.style.display=arch.length?'':'none';const sum=box.querySelector('summary');if(sum)sum.textContent=`📦 보관함 (${arch.length})`;
  const list=$('#task-archive-list');if(list)list.innerHTML=arch.map(x=>`<span class="task-arch-pair"><button type="button" class="task-arch-item" data-arch-open="${esc(x)}"${x===cur?' style="font-weight:700"':''} title="지난 기록 열람">${esc(x)}</button><button type="button" class="task-arch-restore" data-arch-restore="${esc(x)}" title="진행 중 목록으로 복원">↩ 복원</button></span>`).join('')}
 try{localStorage.setItem(TASK_LAST_KEY,cur)}catch{}}
const taskAllNames=()=>TASK_ROSTER.flatMap(([,ns])=>ns);
function taskLoad(){try{return JSON.parse(localStorage.getItem(TASK_KEY))||{}}catch{return{}}}
function taskSave(s){try{localStorage.setItem(TASK_KEY,JSON.stringify(s))}catch{}taskPush()}
function taskBundle(){return{data:taskLoad(),items:taskItems(),todos:todoLoad(),todoGroups:todoGroups(),todoArchive:todoArchLoad()}}
function taskPush(statusSel){if(!TASK_ENDPOINT)return;
 if(!localStorage.getItem(SYNC_SEEDED_KEY)){const s=$(statusSel||'#task-sync');if(s)s.textContent='⚠ 서버 동기화 전 — 저장 보류(목록을 다시 열면 동기화됩니다)';return}
 clearTimeout(taskPushT);const status=$(statusSel||'#task-sync');if(status)status.textContent='저장 중…';taskPushT=setTimeout(()=>{fetch(TASK_ENDPOINT,{method:'POST',body:JSON.stringify(taskBundle())}).then(()=>{if(status)status.textContent='☁ 동기화됨'}).catch(()=>{if(status)status.textContent='이 기기에만 저장(동기화 실패)'})},600)}
async function taskPull(){if(!TASK_ENDPOINT)return false;const status=$('#task-sync');if(status)status.textContent='불러오는 중…';try{const r=await fetch(TASK_ENDPOINT,{cache:'no-store'});if(!r.ok)throw 0;const b=await r.json()||{};const remoteData=b.data&&typeof b.data==='object'?b.data:{};syncSeeded();if(!Object.keys(remoteData).length&&Object.keys(taskLoad()).length){taskPush();if(status)status.textContent='☁ 이 기기 데이터 업로드됨';return false}if(b.data)localStorage.setItem(TASK_KEY,JSON.stringify(b.data));if(Array.isArray(b.items)&&b.items.length)localStorage.setItem(TASK_ITEMS_KEY,JSON.stringify(b.items));if(Array.isArray(b.todos))localStorage.setItem(TODO_KEY,JSON.stringify(b.todos));if(Array.isArray(b.todoGroups))localStorage.setItem(TODO_GROUPS_KEY,JSON.stringify(b.todoGroups));if(Array.isArray(b.todoArchive))localStorage.setItem(TODO_ARCH_KEY,JSON.stringify(b.todoArchive));if(status)status.textContent='☁ 동기화됨';return true}catch{if(status)status.textContent='이 기기에만 저장(동기화 실패)'}return false}
function taskCurrentItem(){return $('#task-item')?.value||taskItems()[0]}
function renderTaskSummary(){const st=taskLoad()[taskCurrentItem()]||{},names=taskAllNames(),pending=names.filter(n=>!st[n]?.done);$('#task-summary').innerHTML=`완료 <b>${names.length-pending.length}</b> / ${names.length}`+(pending.length?` · 미응답: ${esc(pending.join(', '))}`:' · 전원 완료 🎉')}
let taskSortByName=false;
const TASK_RA=['이준범','김진영','김상혁','박소현','한수빈'];
function renderTaskList(desired){fillTaskItems(desired);const st=taskLoad()[taskCurrentItem()]||{};
 const row=n=>{const r=st[n]||{};return `<tr data-name="${esc(n)}"><td class="task-name"${TASK_RA.includes(n)?' style="color:#9aa0a6"':''}>${esc(n)}</td><td class="task-done"><input type="checkbox" data-f="done" ${r.done?'checked':''}></td><td><input class="task-in" data-f="resp" placeholder="응답내용" value="${esc(r.resp||'')}"></td><td><input class="task-in" data-f="note" placeholder="비고" value="${esc(r.note||'')}"></td></tr>`};
 const body=taskSortByName
  ?taskAllNames().slice().sort((a,b)=>a.localeCompare(b,'ko')).map(row).join('')
  :TASK_ROSTER.map(([part,names])=>`<tr class="task-group"><td colspan="4">${esc(part)}</td></tr>`+names.map(row).join('')).join('');
 $('#task-table').innerHTML=`<table class="task-table"><thead><tr><th class="task-sort" style="cursor:pointer;user-select:none" title="클릭하면 이름순 ↔ 팀 순서로 전환">이름 ${taskSortByName?'▲':'⇅'}</th><th>완료</th><th>응답내용</th><th>비고</th></tr></thead><tbody>${body}</tbody></table>`;
 $('#task-date').textContent=new Intl.DateTimeFormat('ko-KR',{year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());renderTaskSummary()}
function taskUpdate(name,field,value){const s=taskLoad(),it=taskCurrentItem();(s[it]=s[it]||{})[name]=s[it][name]||{};s[it][name][field]=value;taskSave(s);renderTaskSummary()}
/* ── TO-DO: 한 줄 할 일 + 체크 + 등록시각 + 이미지 첨부 + 그룹. 수명 피드백과 같은 GAS 번들(todos·todoGroups·todoArchive 필드)로 동기화 ── */
const TODO_KEY='hi_todo_v1',TODO_GROUPS_KEY='hi_todo_groups_v1',TODO_ARCH_KEY='hi_todo_archive_v1',TODO_IMG_MAX=4;/* 동기화 저장소 한도(실측 500KB) 보호 — 항목당 사진 4장 */
function todoLoad(){try{const a=JSON.parse(localStorage.getItem(TODO_KEY));if(Array.isArray(a))return a}catch{}return[]}
function todoSave(a){try{localStorage.setItem(TODO_KEY,JSON.stringify(a))}catch{}taskPush('#todo-sync');renderTodo()}
/* 보관함: 완료 항목을 지우지 않고 옮겨 두는 곳. 여기서 '보관항목 정리'를 눌러야 완전히 삭제된다 */
function todoArchLoad(){try{const a=JSON.parse(localStorage.getItem(TODO_ARCH_KEY));if(Array.isArray(a))return a}catch{}return[]}
function todoArchStore(a){try{localStorage.setItem(TODO_ARCH_KEY,JSON.stringify(a))}catch{}}
function todoArchSave(a){todoArchStore(a);taskPush('#todo-sync');renderTodo()}
/* 보관 공통: 고른 항목을 보관함 맨 앞으로 옮기고 진행 중 목록은 keep으로 교체(그룹·사진 유지) */
function todoArchiveMove(list,keep){if(!list.length)return;const now=Date.now();
 todoArchStore([...list.map(t=>{const o={...t,archTs:now};if(t.done&&!o.doneTs)o.doneTs=now;return o}),...todoArchLoad()]);
 todoSave(keep);/* 저장·동기화·재렌더는 todoSave가 한 번에 처리 */
 const status=$('#todo-sync');if(status)status.textContent=`📦 ${list.length}개 보관함으로 이동`}
function todoGroups(){try{const a=JSON.parse(localStorage.getItem(TODO_GROUPS_KEY));if(Array.isArray(a))return a.filter(x=>typeof x==='string'&&x.trim())}catch{}return[]}
function todoGroupsStore(a){try{localStorage.setItem(TODO_GROUPS_KEY,JSON.stringify(a))}catch{}}
const todoFmt=ts=>new Intl.DateTimeFormat('ko-KR',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(ts));
function todoShrink(file){/* 첨부 이미지: 긴 변 720px·JPEG 0.7 data URL로 압축(동기화 번들 용량 보호) */
 return new Promise((res,rej)=>{const url=URL.createObjectURL(file),img=new Image();
  img.onload=()=>{try{const M=720,s=Math.min(1,M/Math.max(img.width,img.height)),w=Math.max(1,Math.round(img.width*s)),h=Math.max(1,Math.round(img.height*s)),c=document.createElement('canvas');c.width=w;c.height=h;c.getContext('2d').drawImage(img,0,0,w,h);URL.revokeObjectURL(url);res(c.toDataURL('image/jpeg',.7))}catch(e){rej(e)}};
  img.onerror=()=>{URL.revokeObjectURL(url);rej(new Error('decode fail'))};img.src=url})}
const TODO_PEND=[];/* 추가 전 대기 중인 사진 data URL */
function renderTodoPend(){const box=$('#todo-previews');if(!box)return;box.innerHTML=TODO_PEND.map((d,i)=>`<span class="rp"><img src="${d}" alt="첨부 대기 사진"><button type="button" data-rmimg="${i}" title="제거">×</button></span>`).join('')}
async function addTodoImgs(files){const status=$('#todo-sync');
 for(const f of Array.from(files||[])){if(TODO_PEND.length>=TODO_IMG_MAX){if(status)status.textContent=`⚠ 사진은 항목당 ${TODO_IMG_MAX}장까지`;break}
  try{TODO_PEND.push(await todoShrink(f))}catch{if(status)status.textContent=`⚠ ${f.name||'이미지'} 은 읽지 못해 건너뜀`}}
 renderTodoPend()}
function todoLightbox(src){let ov=$('#todo-lightbox');
 if(!ov){ov=document.createElement('div');ov.id='todo-lightbox';ov.innerHTML='<img alt="첨부 사진 크게 보기">';ov.onclick=()=>ov.classList.remove('on');document.body.appendChild(ov);
  document.addEventListener('keydown',e=>{if(e.key==='Escape')ov.classList.remove('on')})}
 ov.querySelector('img').src=src;ov.classList.add('on')}
function fillTodoGroups(){const sel=$('#todo-group');if(!sel)return;const cur=sel.value;
 sel.innerHTML='<option value="">기본</option>'+todoGroups().map(g=>`<option value="${esc(g)}"${g===cur?' selected':''}>${esc(g)}</option>`).join('')}
const todoImgs=t=>(t.imgs||[]).map((d,k)=>`<img class="todo-thumb" src="${d}" alt="첨부 ${k+1}" title="클릭하면 크게 보기">`).join('');
function renderTodoArch(){const box=$('#todo-arch-list');if(!box)return;const a=todoArchLoad(),cnt=$('#todo-arch-count');
 if(cnt)cnt.textContent=a.length;
 if(!a.length){box.innerHTML='<p class="empty">보관한 항목이 없습니다. 체크한 뒤 <b>보관</b>을 누르면 여기로 옮겨집니다.</p>';return}
 const row=(t,i)=>{const imgs=todoImgs(t);
  return `<div class="todo-row arch" data-i="${i}"><span class="todo-text">${esc(t.text)}${imgs?`<span class="todo-thumbs">${imgs}</span>`:''}</span><span class="todo-ts" title="등록 ${todoFmt(t.ts)}">${t.doneTs?'✔':'📦'} ${todoFmt(t.doneTs||t.archTs||t.ts)}</span><button class="todo-restore" type="button" title="진행 중 목록으로 되돌리기">↩</button><button class="todo-arch-del" type="button" title="이 항목만 완전히 삭제">✕</button></div>`};
 const names=['기본',...todoGroups()],buckets=Object.fromEntries(names.map(n=>[n,[]]));
 a.forEach((t,i)=>{buckets[t.group&&names.includes(t.group)?t.group:'기본'].push([t,i])});
 box.innerHTML=names.filter(n=>buckets[n].length).map(n=>
  `<details class="todo-group" data-g="${esc(n)}" open><summary><span>${esc(n)}</span><em>${buckets[n].length}</em></summary>${buckets[n].map(([t,i])=>row(t,i)).join('')}</details>`).join('')}
function renderTodo(){renderTodoArch();const box=$('#todo-list');if(!box)return;fillTodoGroups();const a=todoLoad(),groups=todoGroups();
 if(!a.length&&!groups.length){box.innerHTML='<p class="empty">할 일을 한 줄 적고 ＋추가를 누르세요.</p>';return}
 const row=(t,i)=>{const imgs=todoImgs(t);
  return `<div class="todo-row${t.done?' done':''}" data-i="${i}"><span class="todo-grip" draggable="true" title="드래그해서 다른 그룹으로 이동">⠿</span><input type="checkbox" ${t.done?'checked':''}><span class="todo-text">${esc(t.text)}${imgs?`<span class="todo-thumbs">${imgs}</span>`:''}</span><span class="todo-ts"${t.doneTs?` title="완료 ${todoFmt(t.doneTs)}"`:''}>${todoFmt(t.ts)}</span><button class="todo-edit" type="button" title="내용 수정">✎</button><button class="todo-del" type="button" title="삭제">✕</button><button class="todo-arch-one" type="button" title="이 항목만 보관함으로 이동 (삭제 아님)">📦</button></div>`};
 const names=['기본',...groups],buckets=Object.fromEntries(names.map(n=>[n,[]]));
 a.forEach((t,i)=>{buckets[t.group&&names.includes(t.group)?t.group:'기본'].push([t,i])});
 box.innerHTML=names.map(n=>{const list=buckets[n],undone=list.filter(([t])=>!t.done).length;
  const grip=n==='기본'?'':`<span class="todo-g-grip" draggable="true" data-g="${esc(n)}" title="드래그해서 그룹 순서 변경">⠿</span>`;
  const tools=n==='기본'?'':`<span class="todo-g-tools"><button type="button" class="todo-g-ren" data-g="${esc(n)}" title="그룹 이름 변경">✎</button><button type="button" class="todo-g-del" data-g="${esc(n)}" title="그룹 삭제 (항목은 기본으로 이동)">✕</button></span>`;
  return `<details class="todo-group" data-g="${esc(n)}" open><summary>${grip}<span>${esc(n)}</span><em>${undone}/${list.length}</em>${tools}</summary>${list.map(([t,i])=>row(t,i)).join('')||'<p class="empty todo-empty">이 그룹에 할 일이 없습니다.</p>'}</details>`}).join('')}
function todoAdd(){const inp=$('#todo-input'),text=(inp?.value||'').trim();if(!text&&!TODO_PEND.length)return;
 const a=todoLoad(),g=$('#todo-group')?.value||'',t={text:text||'(사진 메모)',ts:Date.now(),done:false};
 if(g)t.group=g;if(TODO_PEND.length)t.imgs=TODO_PEND.slice();
 a.unshift(t);TODO_PEND.length=0;renderTodoPend();todoSave(a);inp.value='';inp.focus()}
async function todoPull(){if(!TASK_ENDPOINT)return false;const status=$('#todo-sync');if(status)status.textContent='불러오는 중…';try{const r=await fetch(TASK_ENDPOINT,{cache:'no-store'});if(!r.ok)throw 0;const b=await r.json()||{};syncSeeded();
 if(Array.isArray(b.todoGroups))todoGroupsStore(b.todoGroups);
 if(Array.isArray(b.todoArchive))todoArchStore(b.todoArchive);/* 서버에 보관함이 없으면 이 기기 보관함을 유지한다 */
 if(Array.isArray(b.todos)){localStorage.setItem(TODO_KEY,JSON.stringify(b.todos));if(status)status.textContent='☁ 동기화됨';return true}
 // 서버 번들에 아직 todos가 없으면 이 기기 목록을 올려 시드한다
 if(todoLoad().length||todoGroups().length)taskPush('#todo-sync');else if(status)status.textContent='☁ 동기화';return false}catch{if(status)status.textContent='이 기기에만 저장(동기화 실패)'}return false}
function view(id){$$('.view,.nav').forEach(x=>x.classList.remove('active'));$('#'+id).classList.add('active');$(`.nav[data-view="${id}"]`).classList.add('active');$('#page-title').textContent={todo:'TO-DO 체크리스트',overview:'오늘의 리서치 흐름',reports:'발간 보고서',news:'뉴스.아카이브',press:'보도기사 취합','union-board':'현중 노조게시판',tone:'DAOL 리서치 톤',chatbot:'DAOL 리서치와 챗봇',collab:'섹터 콜라보 레이더',tasklist:'수명 피드백 확인',dart:'조선 수주공시 → 텔레',recipe:'레시피 수집 → Notion',etf:'ETF/섹터.신호 포착',holdings:'액티브 ETF 구성 변화',flow:'시장 수급 동향',trend:'시장관심.내러티브',consensus:'코스피200 컨센서스 추적',defense:'글로벌 방산 데일리 브리핑',defweekly:'글로벌 방산 주간 정리',ytdigest:'방산 유튜브 3일 모음',vacation:'친구 휴가 일정',construction:'글로벌 건설기계 데일리 브리핑',conweekly:'글로벌 건설기계 주간 정리',remember:'리멤버 → Notion 기록',mzdiary:'MZ일기 · 잔고/매매노트'}[id];if(id==='overview')fetchLiveMacro();if(id==='press'){state.pressCompany='';renderPressTable()}if(id==='tone')loadToneFrame();if(id==='union-board')loadUnionBoard();if(id==='tasklist'){renderTaskList();taskPull().then(ok=>{if(ok)renderTaskList()})}if(id==='todo'){renderTodo();todoPull().then(ok=>{if(ok)renderTodo()})}if(id==='etf'){const f=$('#etf-frame');if(!f.getAttribute('src'))f.src='etf_signal_report.html?t='+Date.now()}if(id==='holdings'){const f=$('#holdings-frame');if(!f.getAttribute('src'))f.src='etf_holdings_report.html?t='+Date.now()}if(id==='flow'){const f=$('#flow-frame');if(!f.getAttribute('src'))f.src='market_flow_report.html?t='+Date.now()}if(id==='trend'){const f=$('#trend-frame');if(!f.getAttribute('src'))f.src='market_trend_report.html?t='+Date.now()}if(id==='consensus'){const f=$('#consensus-frame');if(!f.getAttribute('src'))f.src='consensus_revision.html?t='+Date.now()}if(id==='defense'){const f=$('#defense-frame');if(!f.getAttribute('src'))f.src='defense_briefing_report.html?t='+Date.now()}if(id==='defweekly'){const f=$('#defweekly-frame');if(!f.getAttribute('src'))f.src='defense_weekly_report.html?t='+Date.now()}if(id==='ytdigest'){const f=$('#ytdigest-frame');if(!f.getAttribute('src'))f.src='youtube_digest_report.html?t='+Date.now()}if(id==='vacation'){const f=$('#vacation-frame');if(!f.getAttribute('src'))f.src='vacation_report.html?t='+Date.now()}if(id==='construction'){const f=$('#construction-frame');if(!f.getAttribute('src'))f.src='construction_briefing_report.html?t='+Date.now()}if(id==='conweekly'){const f=$('#conweekly-frame');if(!f.getAttribute('src'))f.src='construction_weekly_report.html?t='+Date.now()}if(id==='collab'){const f=$('#collab-frame');if(!f.getAttribute('src'))f.src=TONE_SITE+'daol_collab_radar.html?t='+Date.now()}if(id==='chatbot'){const f=$('#chatbot-frame');if(!f.getAttribute('src'))f.src=TONE_SITE+'chat.html?t='+Date.now()}}
const DISPATCH_ENDPOINT='https://script.google.com/macros/s/AKfycbx3RjIjtlO2Z6fIYo2T3LhJrFg9Wp2hS7dMS3Is52-JVF1hizoCWewbQ1uM_v5sdhR2jw/exec';/* 갱신 버튼 → GitHub Actions 디스패치 GAS 웹앱 (gas/dispatch_proxy.gs). 아래 workflow 키는 그 파일의 WF 매핑과 1:1이어야 한다 */
async function dispatchWorkflow(payload,status,btn){
 if(status)status.textContent='요청 중…';if(btn)btn.disabled=true;
 try{
  const r=await fetch(DISPATCH_ENDPOINT,{method:'POST',body:JSON.stringify(payload)});
  // GAS 프록시는 실패 시 {ok:false,code,wf,error}를 돌려준다. error에 사유가 담기므로
  // 그대로 보여준다(매핑 누락·GH_TOKEN 미설정·GitHub 응답 본문 등).
  try{const d=await r.json();
   if(d&&d.ok===false){if(status)status.textContent=`⚠ 거절 ${d.code||'?'}${d.wf?` (${d.wf})`:''} — ${d.error||'GAS 프록시 매핑 확인 필요'}`;return false;}
  }catch{}
  return true;}
 catch(e){if(status)status.textContent='실패: '+e.message;return false;}
 finally{if(btn)btn.disabled=false}}
async function dispatchDart(){
 const url=($('#dart-url')?.value||'').trim(),comment=($('#dart-comment')?.value||'').trim(),status=$('#dart-status'),btn=$('#dart-send');
 if(!/dart\.fss\.or\.kr|rcpNo=|^\d{10,}$/.test(url)){status.textContent='⚠ DART 공시 링크를 넣어주세요';return}
 if(await dispatchWorkflow({workflow:'dart',dart_url:url,comment},status,btn)){
   status.textContent='✅ 요청됨 — 1~2분 뒤 텔레그램 확인';$('#dart-url').value='';$('#dart-comment').value='';}}
const REMEMBER_ENDPOINT='https://script.google.com/macros/s/AKfycbyerXB4W9QaOQJ_ZADATF5FadRtDiSQlT_LAWxPblYQ39bHjmE4LegFhfSb47n4aTj1/exec';/* 리멤버→Notion GAS 웹앱 (gas/remember_notion.gs). 비면 화면의 ⚙️ 연결 설정(localStorage) 사용 */
const REMEMBER_EP_KEY='remember_endpoint_v1';
function rememberEndpoint(){if(REMEMBER_ENDPOINT)return REMEMBER_ENDPOINT;try{return localStorage.getItem(REMEMBER_EP_KEY)||''}catch{return''}}
const REMEMBER_IMGS=[];/* {name,type,data(base64)} — 전송 전 대기 중인 사진 */
function shrinkImage(file){/* 긴 변 1600px JPEG로 축소. 디코드 실패(HEIC 등)면 4MB 이하 원본 그대로 */
 return new Promise((res,rej)=>{const url=URL.createObjectURL(file),img=new Image();
  img.onload=()=>{try{const M=1600,s=Math.min(1,M/Math.max(img.width,img.height)),w=Math.round(img.width*s),h=Math.round(img.height*s),c=document.createElement('canvas');c.width=w;c.height=h;c.getContext('2d').drawImage(img,0,0,w,h);URL.revokeObjectURL(url);const d=c.toDataURL('image/jpeg',.85);res({name:(file.name||'photo').replace(/\.[^.]+$/,'')+'.jpg',type:'image/jpeg',data:d.split(',')[1]})}catch(e){rej(e)}};
  img.onerror=()=>{URL.revokeObjectURL(url);if(file.size>4*1024*1024)return rej(new Error('too big'));const rd=new FileReader();rd.onload=()=>res({name:file.name||'photo',type:file.type||'application/octet-stream',data:String(rd.result).split(',')[1]});rd.onerror=rej;rd.readAsDataURL(file)};
  img.src=url})}
function renderRememberPreviews(){const box=$('#remember-previews');if(!box)return;box.innerHTML=REMEMBER_IMGS.map((im,i)=>`<span class="rp"><img src="data:${im.type};base64,${im.data}" alt="${esc(im.name)}" title="${esc(im.name)}"><button type="button" data-rmimg="${i}" title="제거">×</button></span>`).join('')}
async function addRememberPhotos(files){const status=$('#remember-status');for(const f of Array.from(files||[])){if(REMEMBER_IMGS.length>=8){status.textContent='⚠ 사진은 최대 8장까지';break}
  try{REMEMBER_IMGS.push(await shrinkImage(f))}catch{status.textContent=`⚠ ${f.name||'사진'} 은 읽지 못해 건너뜀`}}
 renderRememberPreviews()}
async function sendRemember(){
 const text=($('#remember-text')?.value||'').trim(),status=$('#remember-status'),btn=$('#remember-send'),box=$('#remember-result');
 if(!text&&!REMEMBER_IMGS.length){status.textContent='⚠ 기억할 내용을 입력하거나 사진을 첨부해 주세요';return}
 const ep=rememberEndpoint();
 if(!ep){status.textContent='⚠ 아래 ⚙️ 연결 설정에서 GAS 웹앱 URL을 먼저 저장해 주세요';const st=$('#remember-setup');if(st)st.open=true;return}
 status.textContent=REMEMBER_IMGS.length?`AI 정리 + 사진 ${REMEMBER_IMGS.length}장 업로드 중… (사진 장수에 따라 수십 초)`:'AI 정리 + Notion 저장 중… (10초 안팎)';btn.disabled=true;box.hidden=true;
 try{
  const r=await fetch(ep,{method:'POST',body:JSON.stringify({text,images:REMEMBER_IMGS})});
  const d=await r.json();
  if(!d.ok)throw new Error(d.error||'저장 실패');
  status.textContent=(d.ai?'✅ 저장 완료 (AI 정리)':'✅ 저장 완료 (원문 기반 — GEMINI_API_KEY 미설정)')+(d.imgFail?` · ⚠ 사진 ${d.imgFail}장 실패`:'');
  const bullets=(d.bullets||[]).map(b=>`  • ${esc(b)}`).join('\n');
  const tags=(d.tags||[]).length?`\n- 태그: ${esc(d.tags.join(', '))}`:'';
  const photos=d.imgOk?`\n- 사진: ${d.imgOk}장 첨부`:'';
  box.innerHTML=`📌 [GS_WRITING / 리멤버] 신규 페이지 생성 완료\n\n■ 페이지 제목: ${esc(d.title||'')}\n■ 생성 경로: GS_WRITING &gt; 리멤버 &gt; ${esc(d.title||'')}\n\n■ 본문 내용:\n- 입력 날짜: ${esc(d.date||'')}${tags}${photos}\n- 주요 내용:\n${bullets}`+(d.url?`\n\n<a href="${esc(d.url)}" target="_blank" rel="noopener">Notion에서 열기 ↗</a>`:'');
  box.hidden=false;$('#remember-text').value='';REMEMBER_IMGS.length=0;renderRememberPreviews();const fi=$('#remember-photos');if(fi)fi.value='';
 }catch(e){status.textContent='실패: '+e.message}
 finally{btn.disabled=false}}
const MZDIARY_ENDPOINT='https://script.google.com/macros/s/AKfycbzUhUwvnhmiz2qQz4NkJpSQgh2BuOpWcS7yPOXqQrBUFN40f6eIJW5i9Y_DV0gz3RekGQ/exec';/* MZ일기→Notion GAS 웹앱 (gas/mz_diary_notion.gs). 비면 화면의 ⚙️ 연결 설정(localStorage) 사용 */
const MZDIARY_EP_KEY='mzdiary_endpoint_v1';
function mzdiaryEndpoint(){if(MZDIARY_ENDPOINT)return MZDIARY_ENDPOINT;try{return localStorage.getItem(MZDIARY_EP_KEY)||''}catch{return''}}
const MZDIARY_IMGS=[];/* {name,type,data(base64)} — 전송 전 대기 중인 잔고·수익률 캡처 */
function renderMzdiaryPreviews(){const box=$('#mzdiary-previews');if(!box)return;box.innerHTML=MZDIARY_IMGS.map((im,i)=>`<span class="rp"><img src="data:${im.type};base64,${im.data}" alt="${esc(im.name)}" title="${esc(im.name)}"><button type="button" data-rmimg="${i}" title="제거">×</button></span>`).join('')}
async function addMzdiaryPhotos(files){const status=$('#mzdiary-status');for(const f of Array.from(files||[])){if(MZDIARY_IMGS.length>=5){status.textContent='⚠ 사진은 최대 5장까지';break}
  try{MZDIARY_IMGS.push(await shrinkImage(f))}catch{status.textContent=`⚠ ${f.name||'사진'} 은 읽지 못해 건너뜀`}}
 renderMzdiaryPreviews()}
async function sendMzDiary(){
 const note=($('#mzdiary-note')?.value||'').trim(),status=$('#mzdiary-status'),btn=$('#mzdiary-send'),box=$('#mzdiary-result');
 if(!note&&!MZDIARY_IMGS.length){status.textContent='⚠ 잔고·수익률 캡처를 첨부하거나 매매노트를 입력해 주세요';return}
 const ep=mzdiaryEndpoint();
 if(!ep){status.textContent='⚠ 아래 ⚙️ 연결 설정에서 GAS 웹앱 URL을 먼저 저장해 주세요';const st=$('#mzdiary-setup');if(st)st.open=true;return}
 status.textContent=MZDIARY_IMGS.length?`AI 정리 + 사진 ${MZDIARY_IMGS.length}장 업로드 중… (사진 장수에 따라 수십 초)`:'AI 정리 + Notion 저장 중… (10초 안팎)';btn.disabled=true;box.hidden=true;
 try{
  const r=await fetch(ep,{method:'POST',body:JSON.stringify({note,images:MZDIARY_IMGS})});
  const d=await r.json();
  if(!d.ok)throw new Error(d.error||'저장 실패');
  status.textContent=(d.ai?'✅ 저장 완료 (AI 정리)':'✅ 저장 완료')+(d.imgFail?` · ⚠ 사진 ${d.imgFail}장 실패`:'');
  const bullets=(d.bullets||[]).map(b=>`  • ${esc(b)}`).join('\n');
  const stocks=(d.stocks||[]).length?`\n- 종목: ${esc(d.stocks.join(', '))}`:'';
  const nums=[d.balance!=null?`잔고 ${Number(d.balance).toLocaleString('ko-KR')}원`:'',d.returnPct!=null?`수익률 ${d.returnPct}%`:''].filter(Boolean).join(' · ');
  const photos=d.imgOk?`\n- 사진: ${d.imgOk}장 첨부`:'';
  box.innerHTML=`📌 [MZ일기] 신규 페이지 생성 완료\n\n■ 페이지 제목: ${esc(d.title||'')}\n■ 생성 경로: MZ일기 &gt; ${esc(d.title||'')}\n\n■ 본문 내용:\n- 입력 날짜: ${esc(d.date||'')}${nums?`\n- ${esc(nums)} (캡처에서 AI 판독)`:''}${stocks}${photos}${bullets?`\n- 주요 내용:\n${bullets}`:''}`+(d.url?`\n\n<a href="${esc(d.url)}" target="_blank" rel="noopener">Notion에서 열기 ↗</a>`:'');
  box.hidden=false;$('#mzdiary-note').value='';MZDIARY_IMGS.length=0;renderMzdiaryPreviews();const fi=$('#mzdiary-photos');if(fi)fi.value='';
 }catch(e){status.textContent='실패: '+e.message}
 finally{btn.disabled=false}}
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
async function dispatchRecipe(){
 const url=($('#recipe-url')?.value||'').trim(),status=$('#recipe-status'),btn=$('#recipe-send');
 if(!/youtube\.com|youtu\.be/.test(url)){status.textContent='⚠ 유튜브 링크를 넣어주세요';return}
 if(await dispatchWorkflow({workflow:'recipe',yt_url:url},status,btn)){
   status.textContent='✅ 요청됨 — 1~2분 뒤 Notion 레시피북 확인';$('#recipe-url').value='';}}
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
async function dispatchTrend(){
 const btn=$('#trend-refresh'),status=$('#trend-status');
 if(await dispatchWorkflow({workflow:'trend'},status,btn))
   status.textContent='✅ 트렌드 산출 요청됨 — 몇 분 뒤 새로고침';}
// 클릭한 메뉴가 속하지 않은 그룹의 서브메뉴는 모두 닫는다.
function closeOtherNavGroups(el){const mine=el.closest?.('details.nav-group');$$('details.nav-group').forEach(o=>{if(o!==mine&&o.open){o.open=false;o.querySelectorAll('details.nav-subgroup').forEach(s=>s.open=false)}});}
$$('.nav').forEach(b=>b.onclick=()=>{closeOtherNavGroups(b);view(b.dataset.view)});$$('[data-go]').forEach(b=>b.onclick=()=>view(b.dataset.go));
// 한 메뉴 그룹을 열면 나머지 그룹의 서브메뉴는 닫는다(모바일·PC 공통, 아코디언).
$$('details.nav-group').forEach(d=>d.addEventListener('toggle',()=>{if(!d.open)return;$$('details.nav-group').forEach(o=>{if(o!==d&&o.open){o.open=false;o.querySelectorAll('details.nav-subgroup').forEach(s=>s.open=false)}})}));
// 같은 그룹 안의 하위 그룹(2단 서브메뉴)도 하나만 열리도록.
$$('details.nav-subgroup').forEach(d=>d.addEventListener('toggle',()=>{if(!d.open)return;$$('details.nav-subgroup').forEach(o=>{if(o!==d)o.open=false})}));
let timer;$('#search').oninput=e=>{clearTimeout(timer);timer=setTimeout(()=>{state.q=e.target.value;load()},250)};
$('#report-company').onchange=e=>{state.reportCompany=e.target.value;load()};
$('#news-company').onchange=e=>{state.newsCompany=e.target.value;load()};
let newsTimer;$('#news-search').oninput=e=>{clearTimeout(newsTimer);newsTimer=setTimeout(()=>{state.newsQ=e.target.value.trim();load()},250)};
$('#press-refresh').onclick=renderPressTable;
$('#press-clear').onclick=()=>{state.pressCompany='';renderPressTable()};
$('#press-start').onchange=renderPressTable;
$('#press-end').onchange=renderPressTable;
$('#press-data-refresh')?.addEventListener('click',dispatchPressData);
$('#recipe-send')?.addEventListener('click',dispatchRecipe);
$('#press-export').onclick=exportPressExcel;
$('#union-board-refresh').onclick=loadUnionBoard;
$('#union-board-file').onchange=e=>{const file=e.target.files?.[0];if(!file)return;const frame=$('#union-board-frame');if(frame.dataset.objectUrl)URL.revokeObjectURL(frame.dataset.objectUrl);const url=URL.createObjectURL(file);frame.dataset.objectUrl=url;frame.src=url;$('#union-board-status').textContent=`${file.name} · ${(file.size/1024).toFixed(1)}KB`};
$('#dart-send')?.addEventListener('click',dispatchDart);
$('#remember-send')?.addEventListener('click',sendRemember);
$('#remember-photos')?.addEventListener('change',e=>{addRememberPhotos(e.target.files);e.target.value=''});
$('#remember-previews')?.addEventListener('click',e=>{const b=e.target.closest('[data-rmimg]');if(!b)return;REMEMBER_IMGS.splice(+b.dataset.rmimg,1);renderRememberPreviews()});
$('#remember-endpoint-save')?.addEventListener('click',()=>{const v=($('#remember-endpoint')?.value||'').trim();if(!/^https:\/\/script\.google\.com\/.+\/exec$/.test(v)){alert('GAS 웹앱 /exec URL 형식이 아닙니다.');return}try{localStorage.setItem(REMEMBER_EP_KEY,v)}catch{}$('#remember-status').textContent='☁ URL 저장됨 — 이제 기록할 수 있습니다';const st=$('#remember-setup');if(st)st.open=false});
{const _rep=$('#remember-endpoint');if(_rep)_rep.value=rememberEndpoint();}
$('#mzdiary-send')?.addEventListener('click',sendMzDiary);
$('#mzdiary-photos')?.addEventListener('change',e=>{addMzdiaryPhotos(e.target.files);e.target.value=''});
$('#mzdiary-previews')?.addEventListener('click',e=>{const b=e.target.closest('[data-rmimg]');if(!b)return;MZDIARY_IMGS.splice(+b.dataset.rmimg,1);renderMzdiaryPreviews()});
$('#mzdiary-endpoint-save')?.addEventListener('click',()=>{const v=($('#mzdiary-endpoint')?.value||'').trim();if(!/^https:\/\/script\.google\.com\/.+\/exec$/.test(v)){alert('GAS 웹앱 /exec URL 형식이 아닙니다.');return}try{localStorage.setItem(MZDIARY_EP_KEY,v)}catch{}$('#mzdiary-status').textContent='☁ URL 저장됨 — 이제 기록할 수 있습니다';const st=$('#mzdiary-setup');if(st)st.open=false});
{const _mep=$('#mzdiary-endpoint');if(_mep)_mep.value=mzdiaryEndpoint();}
$('#etf-refresh')?.addEventListener('click',dispatchEtf);
$('#holdings-refresh')?.addEventListener('click',dispatchHoldings);
$('#news-refresh')?.addEventListener('click',dispatchNews);
$('#reports-refresh')?.addEventListener('click',dispatchReports);
$('#union-refresh')?.addEventListener('click',dispatchUnion);
$('#consensus-refresh')?.addEventListener('click',dispatchConsensus);
$('#flow-refresh')?.addEventListener('click',dispatchFlow);
$('#trend-refresh')?.addEventListener('click',dispatchTrend);
$('#todo-add')?.addEventListener('click',todoAdd);
$('#todo-input')?.addEventListener('keydown',e=>{if(e.key==='Enter')todoAdd()});
// 클립보드 이미지 붙여넣기(Ctrl+V) → 첨부 대기열로
$('#todo-input')?.addEventListener('paste',e=>{const files=[...(e.clipboardData?.items||[])].filter(it=>it.type&&it.type.startsWith('image/')).map(it=>it.getAsFile()).filter(Boolean);if(!files.length)return;e.preventDefault();addTodoImgs(files)});
$('#todo-photos')?.addEventListener('change',e=>{addTodoImgs(e.target.files);e.target.value=''});
$('#todo-previews')?.addEventListener('click',e=>{const b=e.target.closest('[data-rmimg]');if(!b)return;TODO_PEND.splice(+b.dataset.rmimg,1);renderTodoPend()});
$('#todo-group-add')?.addEventListener('click',()=>{const name=(prompt('추가할 그룹 이름')||'').trim();if(!name)return;const g=todoGroups();if(name==='기본'||g.includes(name)){alert('이미 있는 그룹입니다.');return}g.push(name);todoGroupsStore(g);taskPush('#todo-sync');renderTodo();const sel=$('#todo-group');if(sel)sel.value=name});
/* 일괄 보관: 체크한 항목을 한꺼번에 보관함으로(한 건씩은 각 줄의 📦) */
$('#todo-archive-done')?.addEventListener('click',()=>{const a=todoLoad(),done=a.filter(t=>t.done);if(!done.length){alert('체크된 항목이 없습니다. 한 건만 보관하려면 그 줄의 📦를 누르세요.');return}
 todoArchiveMove(done,a.filter(t=>!t.done))});
/* 보관항목 정리: 여기서만 완전 삭제된다 */
$('#todo-clear-arch')?.addEventListener('click',()=>{const a=todoArchLoad();if(!a.length){alert('보관함이 비어 있습니다.');return}
 if(!confirm(`보관함의 ${a.length}개 항목을 완전히 삭제할까요?\n삭제하면 되돌릴 수 없습니다.`))return;todoArchSave([])});
$('#todo-arch-list')?.addEventListener('click',e=>{
 const th=e.target.closest('.todo-thumb');if(th){todoLightbox(th.src);return}
 const a=todoArchLoad();
 const rs=e.target.closest('.todo-restore');if(rs){const i=+rs.closest('.todo-row').dataset.i,t=a[i];if(!t)return;a.splice(i,1);
  const{archTs,doneTs,...rest}=t;todoArchStore(a);todoSave([{...rest,done:false},...todoLoad()]);return}
 const del=e.target.closest('.todo-arch-del');if(!del)return;const i=+del.closest('.todo-row').dataset.i,t=a[i];if(!t)return;
 if(!confirm(`보관함에서 완전히 삭제할까요? — ${t.text}`))return;a.splice(i,1);todoArchSave(a)});
$('#todo-list')?.addEventListener('change',e=>{const row=e.target.closest('.todo-row');if(!row||e.target.type!=='checkbox')return;const a=todoLoad(),t=a[+row.dataset.i];if(!t)return;t.done=e.target.checked;if(t.done)t.doneTs=Date.now();else delete t.doneTs;todoSave(a)});
$('#todo-list')?.addEventListener('click',e=>{
 if(e.target.closest('.todo-g-grip')){e.preventDefault();return}/* 그립 클릭이 그룹 접힘 토글로 번지지 않게 */
 const th=e.target.closest('.todo-thumb');if(th){todoLightbox(th.src);return}
 const ren=e.target.closest('.todo-g-ren');if(ren){e.preventDefault();const cur=ren.dataset.g,name=(prompt('그룹 이름 변경',cur)||'').trim();if(!name||name===cur)return;const g=todoGroups();if(name==='기본'||g.includes(name)){alert('이미 있는 그룹입니다.');return}g[g.indexOf(cur)]=name;todoGroupsStore(g);todoArchStore(todoArchLoad().map(t=>t.group===cur?{...t,group:name}:t));todoSave(todoLoad().map(t=>t.group===cur?{...t,group:name}:t));const sel=$('#todo-group');if(sel)sel.value=name;return}
 const gd=e.target.closest('.todo-g-del');if(gd){e.preventDefault();const cur=gd.dataset.g;if(!confirm(`[${cur}] 그룹을 삭제할까요? 그룹의 할 일은 기본으로 이동합니다.`))return;todoGroupsStore(todoGroups().filter(x=>x!==cur));
  const ungroup=t=>{if(t.group!==cur)return t;const{group,...rest}=t;return rest};
  todoArchStore(todoArchLoad().map(ungroup));todoSave(todoLoad().map(ungroup));return}
 const ar=e.target.closest('.todo-arch-one');if(ar){const i=+ar.closest('.todo-row').dataset.i,a=todoLoad(),t=a[i];if(!t)return;a.splice(i,1);todoArchiveMove([t],a);return}
 const ed=e.target.closest('.todo-edit');if(ed){const row=ed.closest('.todo-row'),a=todoLoad(),t=a[+row.dataset.i];if(!t)return;
  const text=prompt('할 일 내용 수정',t.text);if(text===null)return;const tx=text.trim();let dirty=false;
  if(tx&&tx!==t.text){t.text=tx;dirty=true}
  const names=['기본',...todoGroups()];
  if(names.length>1){const cur=t.group&&names.includes(t.group)?t.group:'기본';
   const pick=prompt(`그룹 이동 — 번호를 입력하세요\n${names.map((n,k)=>`${k+1}. ${n}${n===cur?' ← 현재':''}`).join('\n')}`,String(names.indexOf(cur)+1));
   if(pick!==null){const g=names[Math.trunc(+pick.trim())-1];if(g&&g!==cur){if(g==='기본')delete t.group;else t.group=g;dirty=true}}}
  if(dirty)todoSave(a);return}
 const del=e.target.closest('.todo-del');if(!del)return;const row=del.closest('.todo-row'),a=todoLoad(),t=a[+row.dataset.i];if(!t)return;if(!confirm(`삭제할까요? — ${t.text}`))return;a.splice(+row.dataset.i,1);todoSave(a)});
// 드래그 앤 드랍으로 할 일을 다른 그룹에 떨어뜨려 이동
let TODO_DRAG=-1;
$('#todo-list')?.addEventListener('dragstart',e=>{const row=e.target.closest('.todo-row');if(!row)return;TODO_DRAG=+row.dataset.i;e.dataTransfer.effectAllowed='move';row.classList.add('dragging')});
$('#todo-list')?.addEventListener('dragend',()=>{TODO_DRAG=-1;$$('#todo-list .drop-hover,#todo-list .dragging').forEach(x=>x.classList.remove('drop-hover','dragging'))});
$('#todo-list')?.addEventListener('dragover',e=>{if(TODO_DRAG<0)return;const g=e.target.closest('.todo-group');if(!g)return;e.preventDefault();e.dataTransfer.dropEffect='move';$$('#todo-list .drop-hover').forEach(x=>{if(x!==g)x.classList.remove('drop-hover')});g.classList.add('drop-hover')});
$('#todo-list')?.addEventListener('drop',e=>{if(TODO_DRAG<0)return;const gEl=e.target.closest('.todo-group');if(!gEl)return;e.preventDefault();
 const name=gEl.dataset.g,a=todoLoad(),t=a[TODO_DRAG];TODO_DRAG=-1;if(!t)return;
 const cur=t.group&&['기본',...todoGroups()].includes(t.group)?t.group:'기본';
 if(name===cur){renderTodo();return}
 if(name==='기본')delete t.group;else t.group=name;todoSave(a)});
// 드래그로 그룹 순서 변경 — 그룹 헤더의 ⠿를 다른 그룹 위에 떨어뜨리면 그 위/아래로 이동 (기본 그룹은 맨 위 고정)
let TODO_G_DRAG='';
$('#todo-list')?.addEventListener('dragstart',e=>{const grip=e.target.closest('.todo-g-grip');if(!grip)return;TODO_G_DRAG=grip.dataset.g;e.dataTransfer.effectAllowed='move';grip.closest('.todo-group').classList.add('dragging')});
$('#todo-list')?.addEventListener('dragend',()=>{TODO_G_DRAG=''});
$('#todo-list')?.addEventListener('dragover',e=>{if(!TODO_G_DRAG)return;const g=e.target.closest('.todo-group');if(!g)return;e.preventDefault();e.dataTransfer.dropEffect='move';$$('#todo-list .drop-hover').forEach(x=>{if(x!==g)x.classList.remove('drop-hover')});if(g.dataset.g!==TODO_G_DRAG)g.classList.add('drop-hover')});
$('#todo-list')?.addEventListener('drop',e=>{if(!TODO_G_DRAG)return;const gEl=e.target.closest('.todo-group'),drag=TODO_G_DRAG;TODO_G_DRAG='';if(!gEl)return;e.preventDefault();
 const target=gEl.dataset.g;if(target===drag){renderTodo();return}
 const g=todoGroups().filter(x=>x!==drag);
 const r=gEl.getBoundingClientRect(),after=e.clientY>r.top+r.height/2;/* 상대 위치로 위/아래 판단 */
 g.splice(target==='기본'?0:g.indexOf(target)+(after?1:0),0,drag);
 todoGroupsStore(g);taskPush('#todo-sync');renderTodo()});
$('#task-item')?.addEventListener('change',()=>renderTaskList());
$('#task-add')?.addEventListener('click',()=>{const name=(prompt('추가할 항목 이름')||'').trim();if(!name)return;const items=taskItems();if(items.includes(name)){alert('이미 있는 항목입니다.');return}items.push(name);saveItems(items);renderTaskList(name)});
$('#task-rename')?.addEventListener('click',()=>{const items=taskItems(),cur=taskCurrentItem(),name=(prompt('항목 이름 변경',cur)||'').trim();if(!name||name===cur)return;if(items.includes(name)){alert('이미 있는 항목입니다.');return}items[items.indexOf(cur)]=name;saveItems(items);const s=taskLoad();if(s[cur]){s[name]=s[cur];delete s[cur]}if(Array.isArray(s.__archived)){const i=s.__archived.indexOf(cur);if(i>-1)s.__archived[i]=name}taskSave(s);renderTaskList(name)});
$('#task-del')?.addEventListener('click',()=>{const items=taskItems(),cur=taskCurrentItem();if(items.length<=1){alert('항목이 하나뿐이라 삭제할 수 없습니다.');return}if(!confirm(`[${cur}] 항목과 그 체크 내용을 삭제할까요?`))return;items.splice(items.indexOf(cur),1);saveItems(items);const s=taskLoad();delete s[cur];if(Array.isArray(s.__archived))s.__archived=s.__archived.filter(x=>x!==cur);taskSave(s);renderTaskList(items[0])});
$('#task-archive')?.addEventListener('click',()=>{const cur=taskCurrentItem(),s=taskLoad(),arch=Array.isArray(s.__archived)?s.__archived:[];const wasArch=arch.includes(cur);
 s.__archived=wasArch?arch.filter(x=>x!==cur):[...arch,cur];taskSave(s);
 renderTaskList(wasArch?cur:(taskItems().find(x=>!s.__archived.includes(x))||cur))});
$('#task-archive-list')?.addEventListener('click',e=>{const o=e.target.dataset.archOpen,r=e.target.dataset.archRestore;
 if(o)renderTaskList(o);
 else if(r){const s=taskLoad();s.__archived=(Array.isArray(s.__archived)?s.__archived:[]).filter(x=>x!==r);taskSave(s);renderTaskList(r)}});
$('#task-table')?.addEventListener('click',e=>{if(e.target.closest('th.task-sort')){taskSortByName=!taskSortByName;renderTaskList()}});
$('#task-table')?.addEventListener('change',e=>{const tr=e.target.closest('tr[data-name]');if(tr&&e.target.dataset.f==='done')taskUpdate(tr.dataset.name,'done',e.target.checked)});
$('#task-table')?.addEventListener('input',e=>{const tr=e.target.closest('tr[data-name]'),f=e.target.dataset.f;if(tr&&(f==='resp'||f==='note'))taskUpdate(tr.dataset.name,f,e.target.value)});
$('#task-reset')?.addEventListener('click',()=>{if(!confirm(`[${taskCurrentItem()}] 체크·응답·비고를 모두 지울까요?`))return;const s=taskLoad();delete s[taskCurrentItem()];taskSave(s);renderTaskList()});
$('#task-copy')?.addEventListener('click',()=>{const it=taskCurrentItem(),st=taskLoad()[it]||{},names=taskAllNames(),date=new Intl.DateTimeFormat('ko-KR').format(new Date());const pending=names.filter(n=>!st[n]?.done),lines=[`[${it}] ${date}`,`완료 ${names.length-pending.length}/${names.length}`];if(pending.length)lines.push(`미응답: ${pending.join(', ')}`);const detail=names.filter(n=>st[n]&&(st[n].resp||st[n].note)).map(n=>`· ${n}: ${[st[n].resp,st[n].note].filter(Boolean).join(' / ')}`);if(detail.length)lines.push('',...detail);const text=lines.join('\n');(navigator.clipboard?.writeText(text).then(()=>alert('요약을 복사했습니다.'),()=>prompt('아래 내용을 복사하세요',text)))||prompt('아래 내용을 복사하세요',text)});
$('#task-export')?.addEventListener('click',()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(taskLoad(),null,2)],{type:'application/json'}));a.download=`요청체크_${new Date().toISOString().slice(0,10)}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)});
$('#task-import')?.addEventListener('change',e=>{const f=e.target.files?.[0];if(!f)return;const rd=new FileReader();rd.onload=()=>{try{taskSave(JSON.parse(rd.result));renderTaskList();alert('불러왔습니다.')}catch{alert('JSON 파일을 읽지 못했습니다.')}};rd.readAsText(f)});
$$('[data-type]').forEach(button=>button.onclick=()=>{$$('[data-type]').forEach(x=>x.classList.remove('active'));button.classList.add('active');state.reportType=button.dataset.type;state.weeklyFolder='';if(state.reportType==='위클리')state.reportCompany='';$('#weekly-folders').hidden=state.reportType!=='위클리';$('#report-company').hidden=state.reportType==='위클리';$$('[data-weekly]').forEach(x=>x.classList.toggle('active',x.dataset.weekly===''));load()});
$$('[data-weekly]').forEach(button=>button.onclick=()=>{$$('[data-weekly]').forEach(x=>x.classList.remove('active'));button.classList.add('active');state.weeklyFolder=button.dataset.weekly;load()});
// 뉴스아카이브 기업 칩: 클릭 = 우상단 기업 필터 선택과 동일(같은 칩 재클릭 시 해제). 뉴스 화면에 머문다.
document.addEventListener('click',e=>{const chip=e.target.closest('.news-company-chip');if(!chip)return;state.newsCompany=state.newsCompany===chip.dataset.company?'':chip.dataset.company;load()});
// 보도기사 취합 기업 칩: 그 회사가 들어간 보도만 남긴다(재클릭 해제, 날짜 범위와 AND).
document.addEventListener('click',e=>{const chip=e.target.closest('.press-company-chip');if(!chip)return;state.pressCompany=state.pressCompany===chip.dataset.company?'':chip.dataset.company;renderPressTable()});
document.addEventListener('click',e=>{const chip=e.target.closest('.company-chip');if(!chip)return;state.reportCompany=chip.dataset.company;if(state.reportType==='위클리'){state.reportType='';state.weeklyFolder='';$$('[data-type]').forEach(x=>x.classList.toggle('active',x.dataset.type===''));$$('[data-weekly]').forEach(x=>x.classList.toggle('active',x.dataset.weekly===''));$('#weekly-folders').hidden=true;$('#report-company').hidden=false}view('reports');load()});
load().catch(e=>document.body.insertAdjacentHTML('beforeend',`<p class="empty">데이터를 불러오지 못했습니다: ${esc(e.message)}</p>`));
// URL 해시로 특정 뷰 바로 열기(예: /#tone → 리서치 톤을 별도 창으로). 로드 후 해시가 바뀌어도 반영.
function applyHashView(){const hashView=decodeURIComponent(location.hash.slice(1));if(hashView&&document.getElementById(hashView)?.classList.contains('view'))view(hashView)}
applyHashView();window.addEventListener('hashchange',applyHashView);
// 새 배포 감지: 오래 열어둔 탭이 빌드 시점 데이터에 얼어붙는 것 방지. 백그라운드 탭은 조용히 리로드, 보고 있으면 배너로 안내.
const LOADED_VERSION=window.__DASHBOARD_DATA__?.summary?.updated_at||'';
async function checkNewDeploy(){if(!LOADED_VERSION||!/^http/.test(location.protocol))return;try{const r=await fetch(`version.json?t=${Date.now()}`,{cache:'no-store'});if(!r.ok)return;const v=await r.json();if(!v.updated_at||v.updated_at<=LOADED_VERSION)return;if(document.hidden){location.reload();return}if($('#fresh-banner'))return;const b=document.createElement('div');b.id='fresh-banner';b.style.cssText='position:fixed;bottom:16px;right:16px;z-index:999;background:#1c2733;color:#fff;padding:10px 14px;border-radius:10px;box-shadow:0 4px 14px rgba(0,0,0,.35);font-size:13px;display:flex;gap:10px;align-items:center';b.innerHTML='새 데이터가 배포되었습니다.<button style="background:#3b82f6;color:#fff;border:0;border-radius:6px;padding:5px 10px;cursor:pointer">새로고침</button>';b.querySelector('button').onclick=()=>location.reload();document.body.appendChild(b)}catch{}}
setInterval(checkNewDeploy,15*60*1000);
