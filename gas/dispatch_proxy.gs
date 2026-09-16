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

const OWNER = 'gschoie', REPO = 'GS-DB2', REF = 'main';

// app.js 의 workflow 키 → .github/workflows/ 파일명.
const WF = {
  reports:   'refresh-reports.yml',    // 발간 보고서만 초경량 갱신 (2~3분)
  news:      'refresh-news.yml',       // 뉴스 수집 + 기사 제목·기업 보강
  union:     'refresh-union.yml',      // 현중 노조게시판
  consensus: 'kospi-consensus.yml',    // 코스피200 컨센 스냅샷
  flow:      'market-flow.yml',        // 시장 수급 동향
  trend:     'market-trend.yml',       // 시장관심.내러티브 (구독 채널 트렌드)
  etf:       'etf-signal.yml',         // ETF/섹터 신호
  holdings:  'etf-holdings.yml',       // 액티브 ETF 구성 변화
  valuation: 'valuation.yml',          // 밸류에이션 PER·PBR·ROE·PSR (야후 수집)
  dart:      'dart-shiporder-bot.yml', // 조선 수주공시 → 텔레그램 (입력 필요)
  recipe:    'recipe-bot.yml',         // 유튜브 요리 숏츠 → Notion 레시피 (입력 필요)
  vacation:  'vacation-tracker.yml',   // 휴가/출장 직접 기입 (entry 입력 필요)
};

// 워크플로별 추가 입력. 선언한 required 입력을 빠짐없이 채워야 422가 안 난다.
function buildInputs(key, body) {
  if (key === 'dart') return {
    dart_url: String(body.dart_url || ''),
    target:   String(body.target || '공개채널'), // required + choice
    comment:  String(body.comment || ''),
  };
  if (key === 'recipe') return { yt_url: String(body.yt_url || '') };
  // 휴가/출장: 기입 폼은 entry(JSON)와 함께 mode=add, '지금 수집' 버튼은 mode=run.
  if (key === 'vacation') return {
    mode: body.mode === 'run' ? 'run' : 'add',
    entry: String(body.entry || ''),
  };
  // 밸류에이션: 비워 두면 정기 수집, lookup 에 티커를 넣으면 임시 조회만 돈다.
  if (key === 'valuation') return {
    only:   String(body.only || ''),
    lookup: String(body.lookup || ''),
  };
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
    if (key === 'vacation' && body.mode !== 'run' && !body.entry) {
      return json({ ok: false, code: 400, wf: wf, error: 'entry가 비어 있습니다' });
    }

    return json(fireWorkflow(key, buildInputs(key, body)));
  } catch (err) {
    return json({ ok: false, code: 500, error: String(err) });
  }
}

/** 워크플로 하나를 workflow_dispatch로 발사한다. 웹앱(doPost)과 스케줄러(tick)가 같이 쓴다. */
function fireWorkflow(key, inputs) {
  const wf = WF[key];
  if (!wf) return { ok: false, code: 400, wf: null, error: 'unknown workflow key: ' + key };

  const token = PropertiesService.getScriptProperties().getProperty('GH_TOKEN');
  if (!token) return { ok: false, code: 500, wf: wf, error: 'GH_TOKEN 미설정' };

  const res = UrlFetchApp.fetch(
    `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${wf}/dispatches`,
    { method: 'post', contentType: 'application/json',
      headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json' },
      payload: JSON.stringify({ ref: REF, inputs: inputs || {} }),
      muteHttpExceptions: true });

  const code = res.getResponseCode();
  // 204만 성공. 실패 사유(GitHub 응답 본문)를 같이 돌려줘야 원인을 볼 수 있다.
  return code === 204
    ? { ok: true, code: code, wf: wf }
    : { ok: false, code: code, wf: wf, error: String(res.getContentText() || '').slice(0, 300) };
}

function json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

/** =====================================================================
 * 정시 발사 스케줄러 (2026-08-29 신설)
 * ---------------------------------------------------------------------
 * GitHub 무료 러너의 `schedule` 큐가 최대 몇 시간까지 밀린다(실측: market-trend
 * 평소 +19분, 8/27 +3시간 26분, 8/28 +8시간 1분). 시간에 민감한 워크플로는
 * 이 GAS 시계가 KST 기준으로 workflow_dispatch를 직접 쏜다(±5분).
 *
 * GitHub 크론은 지우지 않고 **안전망**으로 남긴다 — 각 워크플로의 `guard` 잡이
 * "최근에 dispatch로 이미 돌았으면" 뒤늦은 예약 실행을 건너뛴다.
 *
 * [설치 — 1회]
 *   1. 이 파일을 Apps Script 편집기에 붙여넣고 저장(Ctrl+S)
 *   2. 함수 선택창에서 installScheduler 골라 ▶ 실행 (권한 승인 + 5분 트리거 생성)
 *   3. 왼쪽 ⏰ 트리거 화면에 `tick · 시간 기반 · 5분` 1개가 보이면 끝
 *   ※ 트리거는 '저장된 최신 코드'로 도므로 웹앱 재배포 없이 바로 적용된다.
 *      (웹앱 doPost도 함께 바뀌었으니 '배포 관리 → 새 버전'도 해두면 깔끔)
 *
 * 스케줄을 바꿀 때는 아래 SCHEDULE 표만 고치고 저장하면 된다(트리거 재생성 불필요).
 * ===================================================================== */

const TZ = 'Asia/Seoul';
const GRACE_MIN = 60;   // 트리거가 밀리거나 실패해도 목표 시각 +60분까지는 따라 쏜다

// wf: 위 WF 매핑의 키 / hours·minute: KST 발사 시각 / days: daily·weekday·mon~sun
// inputs: 워크플로가 선언한 입력만 넣을 것 — 선언 안 된 키를 보내면 GitHub이 422로 거절한다
const SCHEDULE = [
  { wf: 'trend',     hours: [6],      minute: 30, days: 'daily',   label: '시장관심.내러티브' },
  // 일요일은 워크플로가 스스로 '월~금 누적' 모드로 바꾼다(mode 입력 기본값 auto)
  { wf: 'etf',       hours: [7],      minute: 0,  days: 'daily',   label: 'ETF/섹터 신호',
                     inputs: { via: 'scheduler' } },
  { wf: 'flow',      hours: [10, 13], minute: 0,  days: 'weekday', label: '시장 수급' },
  { wf: 'flow',      hours: [15],     minute: 40, days: 'weekday', label: '시장 수급(마감 잠정)' },
  { wf: 'flow',      hours: [16],     minute: 40, days: 'weekday', label: '시장 수급(확정)' },
  { wf: 'holdings',  hours: [9, 10, 11, 12, 13, 14, 15, 16],   // 장중~마감 직후까지만
                     minute: 17, days: 'weekday', label: '액티브ETF 매매동향',
                     inputs: { via: 'scheduler' } },
  { wf: 'consensus', hours: [17],     minute: 0,  days: 'fri,sat', label: '코스피200 컨센' },
];

/** 5분마다 도는 본체. 목표 시각을 지난 슬롯 중 오늘 아직 안 쏜 것을 발사한다. */
function tick() {
  const now = new Date();
  const today = Utilities.formatDate(now, TZ, 'yyyy-MM-dd');
  const dow = Number(Utilities.formatDate(now, TZ, 'u'));   // 1=월 … 7=일
  const nowMin = Number(Utilities.formatDate(now, TZ, 'H')) * 60 +
                 Number(Utilities.formatDate(now, TZ, 'm'));

  const props = PropertiesService.getScriptProperties();
  let fired = {};
  try { fired = JSON.parse(props.getProperty('FIRED') || '{}'); } catch (e) { fired = {}; }
  let changed = false;

  SCHEDULE.forEach(function (row) {
    if (!dayMatches_(row.days, dow)) return;
    row.hours.forEach(function (hour) {
      const target = hour * 60 + row.minute;
      // 창을 벗어난 슬롯은 건너뛴다 — 자정 넘어 옛 슬롯을 뒤늦게 쏘는 것을 막는다.
      if (nowMin < target || nowMin > target + GRACE_MIN) return;

      const slot = row.wf + '@' + pad2_(hour) + ':' + pad2_(row.minute);
      if (fired[slot] === today) return;          // 오늘 이 슬롯은 이미 쐈다

      const res = fireWorkflow(row.wf, row.inputs || {});
      Logger.log('%s %s → %s', slot, row.label || '', res.ok ? 'OK' : 'FAIL ' + res.error);
      if (res.ok) { fired[slot] = today; changed = true; }
      // 실패하면 기록하지 않는다 → 다음 틱에서 GRACE_MIN 안까지 자동 재시도
    });
  });

  if (changed) props.setProperty('FIRED', JSON.stringify(prune_(fired, today)));
}

function dayMatches_(spec, dow) {
  if (spec === 'daily') return true;
  if (spec === 'weekday') return dow >= 1 && dow <= 5;
  const map = { mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6, sun: 7 };
  // 'fri' 처럼 하나만 쓰거나 'fri,sat' 처럼 쉼표로 여러 요일을 쓸 수 있다
  return String(spec).toLowerCase().split(',').some(function (d) { return map[d.trim()] === dow; });
}

function pad2_(n) { return ('0' + n).slice(-2); }

/** 발사 기록은 어제치까지만 남긴다(스크립트 속성 용량 보호). */
function prune_(fired, today) {
  const cutoff = Utilities.formatDate(
    new Date(new Date().getTime() - 24 * 60 * 60 * 1000), TZ, 'yyyy-MM-dd');
  const keep = {};
  Object.keys(fired).forEach(function (k) { if (fired[k] >= cutoff) keep[k] = fired[k]; });
  return keep;
}

/** [설치] 편집기에서 1회 실행 — 5분 트리거를 만든다(중복 생성 방지 포함). */
function installScheduler() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'tick') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('tick').timeBased().everyMinutes(5).create();
  Logger.log('스케줄러 설치 완료 — 5분마다 tick 실행. 슬롯 %s개', SCHEDULE.length);
}

/** [점검] 지금 시각 기준으로 오늘 무엇이 언제 나가는지 로그로만 확인(발사 안 함). */
function previewSchedule() {
  const now = new Date();
  const dow = Number(Utilities.formatDate(now, TZ, 'u'));
  const fired = JSON.parse(PropertiesService.getScriptProperties().getProperty('FIRED') || '{}');
  Logger.log('지금(KST): %s', Utilities.formatDate(now, TZ, 'yyyy-MM-dd HH:mm (E)'));
  SCHEDULE.forEach(function (row) {
    row.hours.forEach(function (hour) {
      const slot = row.wf + '@' + pad2_(hour) + ':' + pad2_(row.minute);
      Logger.log('  %s %s · 오늘대상=%s · 마지막발사=%s',
        slot, row.label || '', dayMatches_(row.days, dow) ? 'Y' : 'n', fired[slot] || '-');
    });
  });
}

/** [수동] 슬롯 기록을 지워 같은 날 다시 쏠 수 있게 한다(테스트용). */
function resetFired() {
  PropertiesService.getScriptProperties().deleteProperty('FIRED');
  Logger.log('발사 기록 초기화 — 다음 tick에서 창 안의 슬롯을 다시 쏩니다.');
}

/** 편집기에서 1회 실행 — 권한 승인 + 매핑 확인용(실제 디스패치는 안 함). */
function testMapping() {
  Logger.log('키 %s개: %s', Object.keys(WF).length, Object.keys(WF).join(', '));
  Logger.log('GH_TOKEN 설정됨: %s',
    !!PropertiesService.getScriptProperties().getProperty('GH_TOKEN'));
  Logger.log(doPost({ postData: { contents: JSON.stringify({ workflow: 'nope' }) } }).getContent());
}
