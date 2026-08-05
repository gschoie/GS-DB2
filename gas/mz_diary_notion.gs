/** =====================================================================
 * mz일기 → Notion 기록기 (Google Apps Script 웹앱)
 * ---------------------------------------------------------------------
 * 대시보드의 "📔 mz일기" 뷰가 이 웹앱으로 POST {balance, returnPct, note} 를 보내면
 *  1) 매매노트가 있으면 Gemini(flash-lite, 무료)로 제목·개조식·종목 태그를 정리하고 (실패 시 휴리스틱)
 *  2) Notion API로 MZ일기 > 📔 잔고·매매노트 DB에 새 페이지를 만들어
 *     잔고(원)·수익률(%)·구분·종목 속성과 본문을 채운 뒤
 *  3) {ok, title, bullets, stocks, date, balance, returnPct, url} 을 돌려준다.
 *
 * [설치 — 1회] (리멤버 기록기와 동일한 절차)
 *  1. https://www.notion.so/profile/integrations 의 내부 통합 시크릿(ntn_...) 재사용 가능
 *  2. Notion에서 📔 잔고·매매노트 DB를 전체 페이지로 연 뒤 우상단 ⋯ → 연결(Connections)
 *     → 통합 추가 (이걸 안 하면 404 납니다)
 *  3. script.google.com 새 프로젝트에 이 파일 전체 붙여넣기
 *  4. 프로젝트 설정(⚙) → 스크립트 속성 추가:
 *       NOTION_TOKEN   = ntn_...   (필수 — 리멤버와 같은 값이어도 됨)
 *       GEMINI_API_KEY = AIza...   (선택 — 없으면 AI 정리 없이 원문 기반 저장)
 *  5. 편집기에서 testMzDiary 함수를 1회 실행해 권한 승인 + 동작 확인
 *  6. 배포 → 새 배포 → 유형 "웹 앱": 실행 계정 "나", 액세스 "모든 사용자" → /exec URL 복사
 *  7. 대시보드 "📔 mz일기" 뷰의 ⚙️ 연결 설정에 URL 저장
 *     (여러 기기에서 쓰려면 static/app.js 의 MZDIARY_ENDPOINT 상수에 넣고 커밋)
 *
 * [코드 수정 후] 배포 → 배포 관리 → ✏️ → 버전 "새 버전" → 배포 (URL은 그대로 유지됨)
 * ===================================================================== */

const NOTION_DB_ID = 'b1038d361b3845f09335972a2df97c13'; // MZ일기 > 📔 잔고·매매노트
const NOTION_VERSION = '2022-06-28';
const GEMINI_MODEL = 'gemini-flash-lite-latest';

function doGet() { return json_({ ok: true, app: 'mz-diary-notion' }); }

function doPost(e) {
  try {
    const body = JSON.parse((e.postData && e.postData.contents) || '{}');
    const balance = num_(body.balance);      // 잔고(평가금액, 원)
    const returnPct = num_(body.returnPct);  // 수익률(%)
    const note = String(body.note || '').trim(); // 매매노트
    if (balance === null && returnPct === null && !note)
      return json_({ ok: false, error: '잔고·수익률·매매노트 중 하나는 입력해 주세요.' });

    const date = Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd');
    const s = note
      ? structure_(note, date)
      : { title: '잔고기록 ' + date, bullets: [], stocks: [], ai: false };

    const page = createNotionPage_(s, note, date, balance, returnPct, notionToken_());
    return json_({
      ok: true, title: s.title, bullets: s.bullets, stocks: s.stocks, ai: s.ai,
      date: date, balance: balance, returnPct: returnPct, url: page.url || '',
    });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

function json_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}

function num_(v) {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(String(v).replace(/[,\s원%]/g, ''));
  return isFinite(n) ? n : null;
}

function notionToken_() {
  const token = PropertiesService.getScriptProperties().getProperty('NOTION_TOKEN');
  if (!token) throw new Error('스크립트 속성 NOTION_TOKEN 이 없습니다.');
  return token;
}

/* ---------- 1) 매매노트 구조화: Gemini 우선, 실패 시 휴리스틱 폴백 ---------- */
function structure_(text, date) {
  const key = PropertiesService.getScriptProperties().getProperty('GEMINI_API_KEY');
  if (key) {
    try {
      const prompt = [
        "당신은 개인 투자자의 '매매일지' 작성을 돕는 기록 보조 AI입니다.",
        "사용자가 입력한 매매노트를 'MZ일기' 데이터베이스의 새 페이지로 저장할 수 있도록 구조화하세요.",
        '',
        '규칙:',
        '1. 매매의 핵심(무엇을 왜 샀다/팔았다/관망했다)을 담은 간결한 제목(title)을 만드세요 (40자 이내).',
        '2. 본문은 가독성 있는 개조식으로 bullets 배열에 정리하세요 (2~8개).',
        '   매수/매도 가격·수량·이유·시황 판단·다음 계획 등 실무 정보는 빠뜨리지 말 것.',
        '3. 언급된 종목명·티커를 stocks 배열에 뽑으세요 (0~5개, 종목명 위주로 짧게).',
        '4. 반드시 아래 JSON 형식으로만 답하세요.',
        '{"title":"...","bullets":["...","..."],"stocks":["..."]}',
        '',
        '입력:',
        text,
      ].join('\n');
      const res = UrlFetchApp.fetch(
        'https://generativelanguage.googleapis.com/v1beta/models/' + GEMINI_MODEL + ':generateContent?key=' + key,
        {
          method: 'post', contentType: 'application/json', muteHttpExceptions: true,
          payload: JSON.stringify({
            contents: [{ parts: [{ text: prompt }] }],
            generationConfig: { temperature: 0.2, responseMimeType: 'application/json' },
          }),
        });
      if (res.getResponseCode() === 200) {
        const raw = JSON.parse(res.getContentText());
        const out = JSON.parse(raw.candidates[0].content.parts[0].text);
        const title = String(out.title || '').trim();
        const bullets = (out.bullets || []).map(function (b) { return String(b).trim(); }).filter(String).slice(0, 12);
        const stocks = (out.stocks || []).map(function (t) { return String(t).trim(); }).filter(String).slice(0, 5);
        if (title && bullets.length) return { title: title.slice(0, 80), bullets: bullets, stocks: stocks, ai: true };
      }
    } catch (err) { /* 아래 휴리스틱으로 폴백 */ }
  }
  const lines = text.split(/\r?\n/).map(function (l) { return l.trim(); }).filter(String);
  const title = (lines[0] || '매매노트 ' + date).slice(0, 40);
  const bullets = (lines.length > 1 ? lines.slice(1) : lines).slice(0, 12);
  return { title: title, bullets: bullets, stocks: [], ai: false };
}

/* ---------- 2) Notion 페이지 생성 ---------- */
function createNotionPage_(s, note, date, balance, returnPct, token) {
  const children = [para_('입력 날짜: ' + date, true)];
  const nums = [];
  if (balance !== null) nums.push('잔고(평가금액): ' + fmtWon_(balance));
  if (returnPct !== null) nums.push('수익률: ' + returnPct + '%');
  if (nums.length) children.push(para_(nums.join(' · '), true));
  s.bullets.forEach(function (b) {
    children.push({ object: 'block', type: 'bulleted_list_item', bulleted_list_item: { rich_text: rt_(b) } });
  });
  if (note) {
    children.push({ object: 'block', type: 'divider', divider: {} });
    children.push({
      object: 'block', type: 'toggle',
      toggle: { rich_text: rt_('원문'), children: chunk_(note).map(function (c) { return para_(c); }) },
    });
  }

  const payload = {
    parent: { database_id: NOTION_DB_ID },
    icon: { type: 'emoji', emoji: '📔' },
    properties: {
      Name: { title: rt_(s.title) },
      Date: { date: { start: date } },
      '구분': { select: { name: note ? '매매노트' : '잔고기록' } },
    },
    children: children,
  };
  if (balance !== null) payload.properties['잔고'] = { number: balance };
  // Notion percent 포맷은 0~1 소수를 기대 → 7.7(%) 입력이면 0.077로 저장
  if (returnPct !== null) payload.properties['수익률'] = { number: returnPct / 100 };
  if (s.stocks && s.stocks.length) {
    // multi_select 옵션 이름에 콤마는 불가 → 공백으로 치환
    payload.properties['종목'] = { multi_select: s.stocks.map(function (t) { return { name: t.replace(/,/g, ' ') }; }) };
  }

  const res = UrlFetchApp.fetch('https://api.notion.com/v1/pages', {
    method: 'post', contentType: 'application/json', muteHttpExceptions: true,
    headers: { Authorization: 'Bearer ' + token, 'Notion-Version': NOTION_VERSION },
    payload: JSON.stringify(payload),
  });
  const code = res.getResponseCode();
  if (code !== 200) throw new Error('Notion ' + code + ': ' + res.getContentText().slice(0, 300));
  return JSON.parse(res.getContentText());
}

function fmtWon_(n) {
  return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ',') + '원';
}
function rt_(t) { return [{ type: 'text', text: { content: String(t).slice(0, 1900) } }]; }
function para_(t, bold) {
  const r = rt_(t); if (bold) r[0].annotations = { bold: true };
  return { object: 'block', type: 'paragraph', paragraph: { rich_text: r } };
}
function chunk_(t) {
  const out = []; let s = String(t);
  while (s.length && out.length < 40) { out.push(s.slice(0, 1800)); s = s.slice(1800); }
  return out;
}

/* 편집기에서 1회 실행: 권한 승인 + Notion 연결 확인용 */
function testMzDiary() {
  const e = { postData: { contents: JSON.stringify({
    balance: 12345678,
    returnPct: 7.7,
    note: 'mz일기 기록기 테스트입니다.\n삼성전자 10주 매수, 조정 시 분할 매수 계획 — 확인 후 Notion에서 지워도 됩니다.',
  }) } };
  Logger.log(doPost(e).getContent());
}
