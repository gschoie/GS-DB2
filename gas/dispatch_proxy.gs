/** =====================================================================
 * 대시보드 갱신 버튼 → GitHub Actions 디스패치 프록시 (Google Apps Script 웹앱)
 * ---------------------------------------------------------------------
 * 대시보드의 각 "갱신" 버튼이 이 웹앱으로 POST {workflow, ...} 를 보내면
 * GitHub REST API의 workflow_dispatch를 호출해 해당 워크플로를 돌린다.
 * PAT를 브라우저에 노출하지 않으려고 한 단계 끼워 넣은 것이다.
 *
 * 배포본이 이 파일보다 우선한다 — 이 파일은 저장소에 남기는 정본(사본)이다.
 * 고칠 때는 반드시 Apps Script 편집기에도 반영하고 "배포 관리 → 새 버전"까지
 * 해야 기존 /exec URL에 적용된다(저장만 하면 옛 코드가 계속 돈다).
 *
 * [설치 — 1회]
 *  1. script.google.com 새 프로젝트에 이 파일 전체 붙여넣기
 *  2. 프로젝트 설정(⚙) → 스크립트 속성 추가:
 *       GH_TOKEN = github_pat_...  (repo scope — actions:write 필요)
 *  3. 배포 → 새 배포 → 유형 "웹 앱": 실행 계정 "나", 액세스 "모든 사용자"
 *  4. /exec URL을 static/app.js 의 DISPATCH_ENDPOINT 상수에 넣고 커밋
 *
 * [WF 매핑 규칙]
 *  키는 app.js 의 dispatchWorkflow({workflow:'...'}) 인자와 1:1로 맞춘다.
 *  값은 .github/workflows/ 안에 실제로 있는 파일명이어야 한다.
 *  둘 중 하나라도 어긋나면 버튼이 조용히 죽으므로, 버튼을 새로 만들 때는
 *  app.js·이 파일·워크플로 파일 셋을 같이 확인할 것.
 * ===================================================================== */

const OWNER = 'gschoie', REPO = 'GS-output-dashboard', REF = 'main';

// app.js 의 workflow 키 → .github/workflows/ 파일명.
const WF = {
  reports:   'refresh-reports.yml',    // 발간 보고서만 초경량 갱신 (2~3분)
  news:      'refresh-news.yml',       // 뉴스 수집 + 기사 제목·기업 보강
  union:     'refresh-union.yml',      // 현중 노조게시판
  consensus: 'kospi-consensus.yml',    // 코스피200 컨센 스냅샷
  flow:      'market-flow.yml',        // 시장 수급 동향
  etf:       'etf-signal.yml',         // ETF/섹터 신호
  holdings:  'etf-holdings.yml',       // 액티브 ETF 구성 변화
  dart:      'dart-shiporder-bot.yml', // 조선 수주공시 → 텔레그램 (입력 필요)
  recipe:    'recipe-bot.yml',         // 유튜브 요리 숏츠 → Notion 레시피 (입력 필요)
};

// 워크플로별 추가 입력. 선언한 required 입력을 빠짐없이 채워야 422가 안 난다.
function buildInputs(key, body) {
  if (key === 'dart') return {
    dart_url: String(body.dart_url || ''),
    target:   String(body.target || '공개채널'), // required + choice
    comment:  String(body.comment || ''),
  };
  if (key === 'recipe') return { yt_url: String(body.yt_url || '') };
  return {};
}

function doPost(e) {
  try {
    const body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    const key = String(body.workflow || '');
    const wf = WF[key];

    // 매핑에 없는 키는 여기서 끊는다. 예전에는 dart로 폴백시켰는데, dart는
    // dart_url이 required라 엉뚱한 422가 나면서 원인을 가렸다.
    if (!wf) {
      return json({ ok: false, code: 400, wf: null,
                    error: 'unknown workflow key: ' + (key || '(빈 값)'),
                    known: Object.keys(WF) });
    }
    if (key === 'dart' && !body.dart_url) {
      return json({ ok: false, code: 400, wf: wf, error: 'dart_url이 비어 있습니다' });
    }
    if (key === 'recipe' && !body.yt_url) {
      return json({ ok: false, code: 400, wf: wf, error: 'yt_url이 비어 있습니다' });
    }

    const token = PropertiesService.getScriptProperties().getProperty('GH_TOKEN');
    if (!token) return json({ ok: false, code: 500, wf: wf, error: 'GH_TOKEN 미설정' });

    const res = UrlFetchApp.fetch(
      `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${wf}/dispatches`,
      { method: 'post', contentType: 'application/json',
        headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json' },
        payload: JSON.stringify({ ref: REF, inputs: buildInputs(key, body) }),
        muteHttpExceptions: true });

    const code = res.getResponseCode();
    // 204만 성공. 실패 사유(GitHub 응답 본문)를 같이 돌려줘야 원인을 볼 수 있다.
    return json(code === 204
      ? { ok: true, code: code, wf: wf }
      : { ok: false, code: code, wf: wf, error: String(res.getContentText() || '').slice(0, 300) });
  } catch (err) {
    return json({ ok: false, code: 500, error: String(err) });
  }
}

function json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

/** 편집기에서 1회 실행 — 권한 승인 + 매핑 확인용(실제 디스패치는 안 함). */
function testMapping() {
  Logger.log('키 %s개: %s', Object.keys(WF).length, Object.keys(WF).join(', '));
  Logger.log('GH_TOKEN 설정됨: %s',
    !!PropertiesService.getScriptProperties().getProperty('GH_TOKEN'));
  Logger.log(doPost({ postData: { contents: JSON.stringify({ workflow: 'nope' }) } }).getContent());
}
