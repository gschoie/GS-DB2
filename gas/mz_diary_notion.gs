/** =====================================================================
 * mz일기 → Notion 기록기 (Google Apps Script 웹앱)
 * ---------------------------------------------------------------------
 * 대시보드의 "📔 mz일기" 뷰가 이 웹앱으로 POST {note, images[]} 를 보내면
 *  1) 잔고·수익률 캡처(base64)가 있으면 Gemini(flash-lite, 무료)가 캡처에서
 *     잔고(평가금액)·수익률 숫자를 판독하고 (실패해도 사진은 그대로 저장)
 *  2) 매매노트(시장 분위기 | 나의 판단)가 있으면 Gemini가 제목·개조식·종목 태그로
 *     정리하고 (실패 시 휴리스틱 폴백)
 *  3) 캡처를 Notion 파일 업로드 API로 올린 뒤
 *  4) Notion API로 MZ일기 > 📔 잔고·매매노트 DB에 새 페이지를 만들고
 *  5) {ok, title, bullets, stocks, date, balance, returnPct, url, imgOk, imgFail} 을 돌려준다.
 *
 * [설치 — 1회] (리멤버 기록기와 동일한 절차)
 *  1. https://www.notion.so/profile/integrations 의 내부 통합 시크릿(ntn_...) 재사용 가능
 *  2. Notion에서 📔 잔고·매매노트 DB를 전체 페이지로 연 뒤 우상단 ⋯ → 연결(Connections)
 *     → 통합 추가 (이걸 안 하면 404 납니다)
 *  3. script.google.com 새 프로젝트에 이 파일 전체 붙여넣기
 *  4. 프로젝트 설정(⚙) → 스크립트 속성 추가:
 *       NOTION_TOKEN   = ntn_...   (필수 — 리멤버와 같은 값이어도 됨)
 *       GEMINI_API_KEY = AIza...   (선택 — 없으면 AI 정리·숫자 판독 없이 저장)
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
    const note = String(body.note || '').trim();               // 매매노트 (시장 분위기 | 나의 판단)
    const images = Array.isArray(body.images) ? body.images.slice(0, 8) : []; // 잔고·수익률 캡처
    if (!note && !images.length)
      return json_({ ok: false, error: '잔고·수익률 캡처를 첨부하거나 매매노트를 입력해 주세요.' });

    const date = Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd');
    const nums = images.length ? readNumbers_(images[0]) : { balance: null, returnPct: null };
    const s = note
      ? structure_(note, date)
      : { title: '잔고기록 ' + date, bullets: [], stocks: [], ai: false };

    // 캡처 업로드 (한 장 실패해도 나머지는 계속)
    const token = notionToken_();
    const imgIds = []; let imgFail = 0;
    images.forEach(function (img) {
      try { imgIds.push(uploadImage_(img, token)); } catch (err) { imgFail++; }
    });

    const page = createNotionPage_(s, note, date, nums, imgIds, token);
    return json_({
      ok: true, title: s.title, bullets: s.bullets, stocks: s.stocks, ai: s.ai,
      date: date, balance: nums.balance, returnPct: nums.returnPct,
      url: page.url || '', imgOk: imgIds.length, imgFail: imgFail,
    });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

function json_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}

function notionToken_() {
  const token = PropertiesService.getScriptProperties().getProperty('NOTION_TOKEN');
  if (!token) throw new Error('스크립트 속성 NOTION_TOKEN 이 없습니다.');
  return token;
}

function geminiKey_() {
  return PropertiesService.getScriptProperties().getProperty('GEMINI_API_KEY');
}

function callGemini_(parts) {
  const key = geminiKey_();
  if (!key) return null;
  const res = UrlFetchApp.fetch(
    'https://generativelanguage.googleapis.com/v1beta/models/' + GEMINI_MODEL + ':generateContent?key=' + key,
    {
      method: 'post', contentType: 'application/json', muteHttpExceptions: true,
      payload: JSON.stringify({
        contents: [{ parts: parts }],
        generationConfig: { temperature: 0.2, responseMimeType: 'application/json' },
      }),
    });
  if (res.getResponseCode() !== 200) return null;
  const raw = JSON.parse(res.getContentText());
  return JSON.parse(raw.candidates[0].content.parts[0].text);
}

/* ---------- 1) 캡처에서 잔고·수익률 판독 (Gemini vision, 실패해도 무시) ---------- */
function readNumbers_(img) {
  try {
    const out = callGemini_([
      { text: [
        '이 이미지는 증권사 앱의 잔고(계좌 평가) 화면 캡처입니다.',
        '캡처에서 아래 두 값을 찾아 JSON으로만 답하세요. 확실하지 않으면 null 로 두세요.',
        '- balance: 총 평가금액(원, 숫자만 — 콤마·단위 제거)',
        '- returnPct: 총 수익률(%, 숫자만 — 예: 7.7, 손실이면 음수)',
        '{"balance":12345678,"returnPct":7.7}',
      ].join('\n') },
      { inline_data: { mime_type: String(img.type || 'image/jpeg'), data: String(img.data || '') } },
    ]);
    if (!out) return { balance: null, returnPct: null };
    const b = Number(out.balance), r = Number(out.returnPct);
    return {
      balance: isFinite(b) && out.balance !== null ? b : null,
      returnPct: isFinite(r) && out.returnPct !== null ? r : null,
    };
  } catch (err) { return { balance: null, returnPct: null }; }
}

/* ---------- 2) 매매노트 구조화: Gemini 우선, 실패 시 휴리스틱 폴백 ---------- */
function structure_(text, date) {
  try {
    const out = callGemini_([{ text: [
      "당신은 개인 투자자의 '매매일지' 작성을 돕는 기록 보조 AI입니다.",
      "사용자가 입력한 매매노트를 'MZ일기' 데이터베이스의 새 페이지로 저장할 수 있도록 구조화하세요.",
      "노트는 보통 '그때 시장 분위기'와 '나의 판단' 두 축으로 쓰여 있습니다.",
      '',
      '규칙:',
      '1. 매매의 핵심(무엇을 왜 샀다/팔았다/관망했다)을 담은 간결한 제목(title)을 만드세요 (40자 이내).',
      "2. 본문은 개조식으로 bullets 배열에 정리하되, '시장 분위기: …'와 '나의 판단: …'이",
      '   구분되게 정리하세요 (2~8개). 매수/매도 가격·수량·이유·다음 계획 등 실무 정보는 빠뜨리지 말 것.',
      '3. 언급된 종목명·티커를 stocks 배열에 뽑으세요 (0~5개, 종목명 위주로 짧게).',
      '4. 반드시 아래 JSON 형식으로만 답하세요.',
      '{"title":"...","bullets":["...","..."],"stocks":["..."]}',
      '',
      '입력:',
      text,
    ].join('\n') }]);
    if (out) {
      const title = String(out.title || '').trim();
      const bullets = (out.bullets || []).map(function (b) { return String(b).trim(); }).filter(String).slice(0, 12);
      const stocks = (out.stocks || []).map(function (t) { return String(t).trim(); }).filter(String).slice(0, 5);
      if (title && bullets.length) return { title: title.slice(0, 80), bullets: bullets, stocks: stocks, ai: true };
    }
  } catch (err) { /* 아래 휴리스틱으로 폴백 */ }
  const lines = text.split(/\r?\n/).map(function (l) { return l.trim(); }).filter(String);
  const title = (lines[0] || '매매노트 ' + date).slice(0, 40);
  const bullets = (lines.length > 1 ? lines.slice(1) : lines).slice(0, 12);
  return { title: title, bullets: bullets, stocks: [], ai: false };
}

/* ---------- 3) 캡처 업로드 (Notion File Upload API) ----------
 * img: {name, type, data(base64)} — 대시보드가 긴 변 1600px JPEG로 축소해 보냄.
 * 무료 워크스페이스는 파일당 5MiB 제한이라 축소본이면 충분하다. */
function uploadImage_(img, token) {
  const name = String(img.name || 'photo.jpg');
  const type = String(img.type || 'image/jpeg');
  const create = UrlFetchApp.fetch('https://api.notion.com/v1/file_uploads', {
    method: 'post', contentType: 'application/json', muteHttpExceptions: true,
    headers: { Authorization: 'Bearer ' + token, 'Notion-Version': NOTION_VERSION },
    payload: JSON.stringify({ mode: 'single_part', filename: name, content_type: type }),
  });
  if (create.getResponseCode() !== 200) throw new Error('upload-create ' + create.getResponseCode() + ': ' + create.getContentText().slice(0, 200));
  const up = JSON.parse(create.getContentText());

  const blob = Utilities.newBlob(Utilities.base64Decode(String(img.data || '')), type, name);
  const send = UrlFetchApp.fetch('https://api.notion.com/v1/file_uploads/' + up.id + '/send', {
    method: 'post', muteHttpExceptions: true,
    headers: { Authorization: 'Bearer ' + token, 'Notion-Version': NOTION_VERSION },
    payload: { file: blob }, // multipart/form-data 자동 구성
  });
  if (send.getResponseCode() !== 200) throw new Error('upload-send ' + send.getResponseCode() + ': ' + send.getContentText().slice(0, 200));
  return up.id;
}

/* ---------- 4) Notion 페이지 생성 ---------- */
function createNotionPage_(s, note, date, nums, imgIds, token) {
  const children = [para_('입력 날짜: ' + date, true)];
  const numLine = [];
  if (nums.balance !== null) numLine.push('잔고(평가금액): ' + fmtWon_(nums.balance));
  if (nums.returnPct !== null) numLine.push('수익률: ' + nums.returnPct + '%');
  if (numLine.length) children.push(para_(numLine.join(' · ') + ' (캡처에서 AI 판독)', true));
  s.bullets.forEach(function (b) {
    children.push({ object: 'block', type: 'bulleted_list_item', bulleted_list_item: { rich_text: rt_(b) } });
  });
  (imgIds || []).forEach(function (id) {
    children.push({ object: 'block', type: 'image', image: { type: 'file_upload', file_upload: { id: id } } });
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
  if (nums.balance !== null) payload.properties['잔고'] = { number: nums.balance };
  // Notion percent 포맷은 0~1 소수를 기대 → 7.7(%) 판독이면 0.077로 저장
  if (nums.returnPct !== null) payload.properties['수익률'] = { number: nums.returnPct / 100 };
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

/* 편집기에서 1회 실행: 권한 승인 + Notion 연결/사진 업로드 확인용 */
function testMzDiary() {
  const tinyPng = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';
  const e = { postData: { contents: JSON.stringify({
    note: '시장 분위기: 금리 인하 기대로 반도체 강세.\n나의 판단: 삼성전자 10주 매수, 조정 시 분할 매수 계획 — 확인 후 Notion에서 지워도 됩니다.',
    images: [{ name: 'test.png', type: 'image/png', data: tinyPng }],
  }) } };
  Logger.log(doPost(e).getContent());
}
