/** =====================================================================
 * 리멤버 → Notion 기록기 (Google Apps Script 웹앱)
 * ---------------------------------------------------------------------
 * 대시보드의 "💿 리멤버.기록" 뷰가 이 웹앱으로 POST {text:"..."} 를 보내면
 *  1) Gemini(flash-lite, 무료)로 제목·개조식 요약·태그를 구조화하고 (실패 시 휴리스틱)
 *  2) Notion API로 GS_WRITING > 리멤버 DB에 새 페이지를 만든 뒤
 *  3) {ok, title, bullets, tags, date, url} 을 돌려준다.
 *
 * [설치 — 1회]
 *  1. https://www.notion.so/profile/integrations 에서 내부 통합(Internal) 생성
 *     → 워크스페이스 "GS_WRITING" 선택 → 시크릿(ntn_...) 복사
 *  2. Notion에서 💿 리멤버 DB를 전체 페이지로 연 뒤 우상단 ⋯ → 연결(Connections)
 *     → 방금 만든 통합 추가 (이걸 안 하면 404 납니다)
 *  3. script.google.com 새 프로젝트에 이 파일 전체 붙여넣기
 *  4. 프로젝트 설정(⚙) → 스크립트 속성 추가:
 *       NOTION_TOKEN   = ntn_...   (필수)
 *       GEMINI_API_KEY = AIza...   (선택 — 없으면 AI 정리 없이 원문 기반 저장)
 *  5. 편집기에서 testRemember 함수를 1회 실행해 권한 승인 + 동작 확인
 *  6. 배포 → 새 배포 → 유형 "웹 앱": 실행 계정 "나", 액세스 "모든 사용자" → /exec URL 복사
 *  7. 대시보드 "💿 리멤버.기록" 뷰의 ⚙️ 연결 설정에 URL 저장
 *     (여러 기기에서 쓰려면 static/app.js 의 REMEMBER_ENDPOINT 상수에 넣고 커밋)
 * ===================================================================== */

const NOTION_DB_ID = '3ad57951c40c80128a6ec5d826196836'; // GS_WRITING > 💿 리멤버 (구 리멤버2026)
const NOTION_VERSION = '2022-06-28';
const GEMINI_MODEL = 'gemini-flash-lite-latest';

function doGet() { return json_({ ok: true, app: 'remember-notion' }); }

function doPost(e) {
  try {
    const body = JSON.parse((e.postData && e.postData.contents) || '{}');
    const text = String(body.text || '').trim();
    if (!text) return json_({ ok: false, error: '내용이 비어 있습니다.' });

    const date = Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd');
    const s = structure_(text);
    const page = createNotionPage_(s, text, date);
    return json_({ ok: true, title: s.title, bullets: s.bullets, tags: s.tags, ai: s.ai, date: date, url: page.url || '' });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

function json_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}

/* ---------- 1) 구조화: Gemini 우선, 실패 시 휴리스틱 폴백 ---------- */
function structure_(text) {
  const key = PropertiesService.getScriptProperties().getProperty('GEMINI_API_KEY');
  if (key) {
    try {
      const prompt = [
        "당신은 'GS_WRITING' 워크스페이스 관리 및 기록 보조 AI입니다.",
        "사용자가 입력한 기록을 '리멤버' 상위 페이지 하위의 새 페이지로 저장할 수 있도록 구조화하세요.",
        '',
        '규칙:',
        '1. 입력의 핵심 주제를 명확히 나타내는 간결한 페이지 제목(title)을 만드세요 (40자 이내).',
        '2. 본문은 가독성 있는 개조식으로 bullets 배열에 정리하세요 (2~8개, 세부 수치·고유명사·연락처 등 실무 정보는 빠뜨리지 말 것).',
        '3. 분류용 키워드 태그(tags)를 1~3개 뽑으세요 (한글 위주, 짧게).',
        '4. 반드시 아래 JSON 형식으로만 답하세요.',
        '{"title":"...","bullets":["...","..."],"tags":["..."]}',
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
        const tags = (out.tags || []).map(function (t) { return String(t).trim(); }).filter(String).slice(0, 3);
        if (title && bullets.length) return { title: title.slice(0, 80), bullets: bullets, tags: tags, ai: true };
      }
    } catch (err) { /* 아래 휴리스틱으로 폴백 */ }
  }
  const lines = text.split(/\r?\n/).map(function (l) { return l.trim(); }).filter(String);
  const title = (lines[0] || '메모').slice(0, 40);
  const bullets = (lines.length > 1 ? lines.slice(1) : lines).slice(0, 12);
  return { title: title, bullets: bullets, tags: [], ai: false };
}

/* ---------- 2) Notion 페이지 생성 ---------- */
function createNotionPage_(s, rawText, date) {
  const token = PropertiesService.getScriptProperties().getProperty('NOTION_TOKEN');
  if (!token) throw new Error('스크립트 속성 NOTION_TOKEN 이 없습니다.');

  const children = [para_('입력 날짜: ' + date, true)];
  s.bullets.forEach(function (b) {
    children.push({ object: 'block', type: 'bulleted_list_item', bulleted_list_item: { rich_text: rt_(b) } });
  });
  children.push({ object: 'block', type: 'divider', divider: {} });
  children.push({
    object: 'block', type: 'toggle',
    toggle: { rich_text: rt_('원문'), children: chunk_(rawText).map(function (c) { return para_(c); }) },
  });

  const payload = {
    parent: { database_id: NOTION_DB_ID },
    icon: { type: 'emoji', emoji: '💿' },
    properties: { Name: { title: rt_(s.title) } },
    children: children,
  };
  if (s.tags && s.tags.length) {
    // multi_select 옵션 이름에 콤마는 불가 → 공백으로 치환
    payload.properties.Tags = { multi_select: s.tags.map(function (t) { return { name: t.replace(/,/g, ' ') }; }) };
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
function testRemember() {
  const e = { postData: { contents: JSON.stringify({ text: '리멤버 기록기 테스트입니다.\n첫 배포 승인용 실행 — 확인 후 Notion에서 지워도 됩니다.' }) } };
  Logger.log(doPost(e).getContent());
}
