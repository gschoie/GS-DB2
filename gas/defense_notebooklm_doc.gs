// 방산 브리핑 → 구글 문서 (NotebookLM 동기화용) — Google Apps Script 정본
//
// 매일 아침 GitHub(GS-DB2)에 쌓인 방산 브리핑 md 두 종(제미나이·클로드)을 구글
// 문서로 만든다. NotebookLM은 구글 문서 소스에 한해 '동기화' 버튼으로 최신 내용을
// 다시 불러올 수 있으므로, 소스를 지웠다 다시 올릴 필요 없이 버튼 한 번이면 된다.
//
// 문서는 두 벌을 유지한다.
//   1) 최근 30일 롤링 문서 — 매일 통째로 덮어쓴다. '요즘 동향' 질문용.
//   2) 월간 누적 문서 — '방산 브리핑 YYYY-MM' 문서를 매일 '이달 1일~오늘'로
//      다시 쓴다. 달이 바뀌면 새 문서가 생기고 지난달 문서는 더는 손대지 않아
//      그대로 보존된다(영구 아카이브). 매달 1일에 새 문서를 NotebookLM 소스로
//      한 번만 추가하면 된다.
//
// 설치(1회) — 기존 봇 프로젝트에 섞지 말고 새 Apps Script 프로젝트를 쓸 것.
// (문서 권한이 새로 필요해서, 웹앱이 붙어 있는 프로젝트에 넣으면 재승인이 걸린다)
//   1. script.google.com → 새 프로젝트 → 이 파일 붙여넣기
//   2. 편집기 왼쪽 '서비스(Services)'의 + → 'Drive API' 추가(식별자 Drive 그대로)
//      — 한 달치 텍스트가 커서 DocumentApp.setText 로는 실패한다. Drive 로 통째 교체한다.
//   3. updateNotebookLmDoc() 한 번 실행 → 권한 승인 → 실행 로그의 문서 주소 확인
//   4. installNotebookLmTrigger() 한 번 실행 → 매일 아침 8시대 자동 갱신
//   5. NotebookLM → 소스 추가 → Google Docs → 두 문서(30일 롤링 + 이달 월간) 선택
//      이후에는 NotebookLM에서 소스를 열고 '동기화'만 누르면 최신이 된다.
//
// 문서는 처음 실행할 때 스크립트가 직접 만들고, ID를 스크립트 속성에 적어 둔다
// (롤링: NOTEBOOKLM_DOC_ID, 월간: NOTEBOOKLM_DOC_ID_YYYY-MM). 이미 있는 문서를
// 쓰고 싶으면 해당 속성에 문서 ID를 미리 넣으면 된다.
// 리포지토리가 공개라 토큰 없이 raw 주소를 읽는다. 비공개로 바꾸면 스크립트 속성에
// GH_TOKEN 을 넣을 것 — 있으면 자동으로 붙여 보낸다.

const NLM_PROPS = PropertiesService.getScriptProperties();
const NLM_DOC_ID_KEY = 'NOTEBOOKLM_DOC_ID';
const NLM_DOC_TITLE = '방산 브리핑 최근 30일 (NotebookLM 동기화용 — 자동 생성)';
const NLM_DAYS = 30;
const NLM_RAW_BASE = 'https://raw.githubusercontent.com/gschoie/GS-DB2/main/'
  + 'telegram_research_dashboard/static/';
// 브리핑 두 종 — 대시보드 static 폴더 이름과 같아야 한다.
const NLM_SOURCES = [
  { key: 'defense_daily', label: '글로벌 방산 브리핑 (제미나이)' },
  { key: 'claude_defense', label: 'Claude 방산 브리핑' }
];

// 메인 — 트리거가 매일 이 함수 하나만 부른다. 롤링 30일 문서와 이달 월간 문서를
// 차례로 갱신한다. 한쪽이 실패해도 다른 쪽은 마저 쓴다.
function updateNotebookLmDoc() {
  try {
    updateRollingDoc_();
  } catch (error) {
    Logger.log('30일 문서 갱신 실패: ' + error);
  }
  try {
    updateMonthlyDoc_();
  } catch (error) {
    Logger.log('월간 문서 갱신 실패: ' + error);
  }
}

// 1) 최근 30일 롤링 문서 — 매일 창이 하루씩 밀린다.
function updateRollingDoc_() {
  const built = buildDocText_(recentDates_(NLM_DAYS), '최근 ' + NLM_DAYS + '일');
  if (!built) {
    Logger.log('30일 문서: 가져온 브리핑이 없습니다 — 주소나 리포지토리 공개 여부를 확인하세요.');
    return;
  }
  const docId = ensureDoc_(NLM_DOC_ID_KEY, NLM_DOC_TITLE);
  writeDocText_(docId, built.text);
  Logger.log('30일 문서 갱신 — 브리핑 ' + built.count + '건: '
    + 'https://docs.google.com/document/d/' + docId);
}

// 2) 이달 누적 문서 — 매일 '1일~오늘'로 다시 쓴다. 달이 바뀌면 이 함수가 새 문서를
// 만들고, 지난달 문서는 다시는 건드리지 않으므로 완결본으로 남는다.
function updateMonthlyDoc_() {
  const month = Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM');
  const built = buildDocText_(monthDates_(), month + ' 월간 누적');
  if (!built) {
    Logger.log('월간 문서(' + month + '): 아직 가져올 브리핑이 없습니다.');
    return;
  }
  const key = NLM_DOC_ID_KEY + '_' + month;
  const isNew = !NLM_PROPS.getProperty(key);
  const docId = ensureDoc_(key, '방산 브리핑 ' + month + ' (NotebookLM용 — 자동 생성)');
  writeDocText_(docId, built.text);
  Logger.log('월간 문서(' + month + ') 갱신 — 브리핑 ' + built.count + '건: '
    + 'https://docs.google.com/document/d/' + docId);
  if (isNew) {
    Logger.log('▶ 새 달 문서입니다 — NotebookLM에 소스로 한 번 추가해 주세요.');
  }
}

// 날짜 목록의 브리핑을 긁어 문서 본문을 만든다. 하나도 없으면 null.
function buildDocText_(dates, rangeLabel) {
  // 요청을 한꺼번에 만든다: 날짜 × 브리핑 종류. 없는 날(장애 등)은 404로 오고 건너뛴다.
  const requests = [];
  const meta = [];
  const token = NLM_PROPS.getProperty('GH_TOKEN');
  dates.forEach(function (date) {
    NLM_SOURCES.forEach(function (source) {
      const req = {
        url: NLM_RAW_BASE + source.key + '/' + date + '.md',
        muteHttpExceptions: true
      };
      if (token) req.headers = { Authorization: 'Bearer ' + token };
      requests.push(req);
      meta.push({ date: date, source: source });
    });
  });
  const responses = UrlFetchApp.fetchAll(requests);

  const counts = {};
  NLM_SOURCES.forEach(function (source) { counts[source.key] = 0; });
  const chunks = [];
  responses.forEach(function (response, index) {
    if (response.getResponseCode() !== 200) return;
    const text = response.getContentText().trim();
    if (!text) return;
    const item = meta[index];
    counts[item.source.key]++;
    chunks.push('━━━━━ ' + item.date + ' · ' + item.source.label + ' ━━━━━\n\n' + text);
  });
  if (chunks.length === 0) return null;

  const stamp = Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd HH:mm');
  const header = '방산 브리핑 모음 — ' + rangeLabel + '\n'
    + '갱신: ' + stamp + ' KST · '
    + NLM_SOURCES.map(function (source) {
        return source.label + ' ' + counts[source.key] + '건';
      }).join(' · ') + '\n'
    + '이 문서는 매일 자동으로 다시 쓰입니다 — 직접 고치지 마세요.\n'
    + 'NotebookLM에서는 이 소스를 열고 [동기화]만 누르면 됩니다.\n\n';
  return { text: header + chunks.join('\n\n'), count: chunks.length };
}

// 문서 내용을 통째로 교체한다. 한 달치는 수십만 자라 DocumentApp.setText 가
// 'Service Documents failed' 로 죽는다 — Drive API 미디어 업로드는 크기에 안전하고,
// text/plain 을 올리면 구글 문서 내용으로 자동 변환된다.
function writeDocText_(docId, text) {
  if (typeof Drive === 'undefined') {
    throw new Error("Drive API 서비스가 없습니다. 편집기 왼쪽 '서비스' + 에서 "
      + "'Drive API'(식별자 Drive)를 추가한 뒤 다시 실행하세요.");
  }
  Drive.Files.update({}, docId, Utilities.newBlob(text, 'text/plain'));
}

// 오늘(KST)부터 거꾸로 days일치 날짜 문자열. 최신이 먼저다.
function recentDates_(days) {
  const dates = [];
  const now = Date.now();
  for (let i = 0; i < days; i++) {
    dates.push(Utilities.formatDate(new Date(now - i * 24 * 3600 * 1000),
      'Asia/Seoul', 'yyyy-MM-dd'));
  }
  return dates;
}

// 이달 1일부터 오늘(KST)까지. 최신이 먼저다.
function monthDates_() {
  const today = Number(Utilities.formatDate(new Date(), 'Asia/Seoul', 'd'));
  return recentDates_(today);
}

// 속성 key 에 적힌 문서 ID를 돌려준다. 없거나 지워졌으면 새로 만들어 ID를 적어 둔다.
function ensureDoc_(key, title) {
  const saved = NLM_PROPS.getProperty(key);
  if (saved) {
    try {
      DocumentApp.openById(saved);  // 살아 있는지 확인만
      return saved;
    } catch (error) {
      Logger.log('저장된 문서(' + saved + ')를 열 수 없어 새로 만듭니다: ' + error);
    }
  }
  const doc = DocumentApp.create(title);
  NLM_PROPS.setProperty(key, doc.getId());
  Logger.log('새 문서를 만들었습니다 — NotebookLM 소스로 이 문서를 추가하세요: ' + doc.getUrl());
  return doc.getId();
}

// 갱신 트리거를 건다. 한 번만 실행하면 된다(여러 번 눌러도 중복되지 않는다).
// 브리핑 두 종이 아침 6시~7시대에 나오므로 8시대로 잡는다.
function installNotebookLmTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (trigger) {
    if (trigger.getHandlerFunction() === 'updateNotebookLmDoc') {
      ScriptApp.deleteTrigger(trigger);
    }
  });
  ScriptApp.newTrigger('updateNotebookLmDoc').timeBased().everyDays(1).atHour(8).create();
  Logger.log('매일 오전 8시대에 문서(30일 롤링 + 이달 월간)를 갱신합니다.');
}
