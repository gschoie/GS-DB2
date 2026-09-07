// 방산 브리핑 → 구글 문서 (NotebookLM 동기화용) — Google Apps Script 정본
//
// 매일 아침 GitHub(GS-DB2)에 쌓인 방산 브리핑 md 두 종(제미나이·클로드)의 최근
// 30일치를 고정된 구글 문서 하나에 통째로 덮어쓴다. NotebookLM은 구글 문서 소스에
// 한해 '동기화' 버튼으로 최신 내용을 다시 불러올 수 있으므로, 소스를 지웠다 다시
// 올릴 필요 없이 버튼 한 번이면 된다.
//
// 설치(1회) — 기존 봇 프로젝트에 섞지 말고 새 Apps Script 프로젝트를 쓸 것.
// (문서 권한이 새로 필요해서, 웹앱이 붙어 있는 프로젝트에 넣으면 재승인이 걸린다)
//   1. script.google.com → 새 프로젝트 → 이 파일 붙여넣기
//   2. updateNotebookLmDoc() 한 번 실행 → 권한 승인 → 실행 로그의 문서 주소 확인
//   3. installNotebookLmTrigger() 한 번 실행 → 매일 아침 8시대 자동 갱신
//   4. NotebookLM → 소스 추가 → Google Docs → 위 문서 선택
//      이후에는 NotebookLM에서 그 소스를 열고 '동기화'만 누르면 최신 30일치가 된다.
//
// 문서는 처음 실행할 때 스크립트가 직접 만들고, ID를 스크립트 속성(NOTEBOOKLM_DOC_ID)에
// 적어 둔다. 이미 있는 문서를 쓰고 싶으면 그 속성에 문서 ID를 미리 넣으면 된다.
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

// 메인 — 최근 30일치를 긁어 문서를 통째로 다시 쓴다.
function updateNotebookLmDoc() {
  const dates = recentDates_(NLM_DAYS);

  // 요청을 한꺼번에 만든다: 날짜 × 브리핑 종류. 없는 날(주말·장애)은 404로 오고 건너뛴다.
  const requests = [];
  const meta = [];
  dates.forEach(function (date) {
    NLM_SOURCES.forEach(function (source) {
      const req = {
        url: NLM_RAW_BASE + source.key + '/' + date + '.md',
        muteHttpExceptions: true
      };
      const token = NLM_PROPS.getProperty('GH_TOKEN');
      if (token) req.headers = { Authorization: 'Bearer ' + token };
      requests.push(req);
      meta.push({ date: date, source: source });
    });
  });
  const responses = UrlFetchApp.fetchAll(requests);

  // 날짜 내림차순(최신이 먼저) 그대로, 같은 날짜에는 두 브리핑을 나란히 담는다.
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

  if (chunks.length === 0) {
    Logger.log('가져온 브리핑이 없습니다 — 주소나 리포지토리 공개 여부를 확인하세요: ' + NLM_RAW_BASE);
    return;
  }

  const stamp = Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd HH:mm');
  const header = '방산 브리핑 모음 — 최근 ' + NLM_DAYS + '일\n'
    + '갱신: ' + stamp + ' KST · '
    + NLM_SOURCES.map(function (source) {
        return source.label + ' ' + counts[source.key] + '건';
      }).join(' · ') + '\n'
    + '이 문서는 매일 자동으로 다시 쓰입니다 — 직접 고치지 마세요.\n'
    + 'NotebookLM에서는 이 소스를 열고 [동기화]만 누르면 됩니다.\n\n';

  const doc = openOrCreateDoc_();
  doc.getBody().setText(header + chunks.join('\n\n'));
  doc.saveAndClose();
  Logger.log('문서 갱신 완료 — 브리핑 ' + chunks.length + '건: ' + doc.getUrl());
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

// 속성에 적힌 문서를 연다. 없거나 지워졌으면 새로 만들어 ID를 적어 둔다.
function openOrCreateDoc_() {
  const saved = NLM_PROPS.getProperty(NLM_DOC_ID_KEY);
  if (saved) {
    try {
      return DocumentApp.openById(saved);
    } catch (error) {
      Logger.log('저장된 문서(' + saved + ')를 열 수 없어 새로 만듭니다: ' + error);
    }
  }
  const doc = DocumentApp.create(NLM_DOC_TITLE);
  NLM_PROPS.setProperty(NLM_DOC_ID_KEY, doc.getId());
  Logger.log('새 문서를 만들었습니다 — NotebookLM 소스로 이 문서를 추가하세요: ' + doc.getUrl());
  return doc;
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
  Logger.log('매일 오전 8시대에 문서를 갱신합니다.');
}
