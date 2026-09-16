/**
 * 매크로 섹션봇 슬롯 트리거 — GitHub 크론 유실 우회로.
 *
 * 배경: Macro_Section_Get 리포의 schedule 크론이 워크플로 편집 후 재등록 유실로
 * 슬롯을 통째로 빼먹는다(2026-08-27 KST 07:00·10:30 연속 미발화, state=active인데
 * 이벤트 0건). GAS 시간 트리거는 분 단위로 안정적이므로, 슬롯 시작마다 여기서
 * workflow_dispatch(mode=serve-slot)를 쏘아 잡을 깨운다. 잡은 러너 안에서
 * 10분 간격으로 6개 섹션을 순차 발송한다. GitHub 크론은 백업으로 남아 있고,
 * 봇의 90분 중복 가드가 이중 발송을 걸러준다.
 *
 * 설치(1회):
 *  1) dispatch_proxy와 같은 Apps Script 프로젝트에 이 파일을 새 파일로 추가
 *     (같은 프로젝트라야 GH_TOKEN 스크립트 속성을 재사용한다).
 *  2) 프로젝트 설정(톱니바퀴)에서 시간대가 '서울'인지 확인 — 트리거가 이 시간대를 따른다.
 *  3) 함수 선택에서 installMacroTriggers 를 한 번 실행하고 권한을 승인한다.
 *  4) 좌측 '트리거' 메뉴에 fireMacroSlot 4개가 생겼으면 완료.
 *  ※ 웹앱 재배포는 필요 없다(트리거는 배포와 무관).
 *  ※ GH_TOKEN이 fine-grained PAT이면 Macro_Section_Get 리포에도 actions:write
 *     권한이 있어야 한다(classic repo 스코프면 그대로 동작).
 *
 * 시각은 GAS 특성상 지정 분 ±15분 안에서 발화한다(예: 07:00 → 06:45~07:15).
 */
const MACRO_OWNER = 'gschoie';
const MACRO_REPO = 'Macro_Section_Get';
const MACRO_WORKFLOW = 'macro-section-bot.yml';
const MACRO_SLOTS = [[7, 0], [10, 30], [15, 0], [21, 0]]; // KST [시, 분]

function fireMacroSlot() {
  const token = PropertiesService.getScriptProperties().getProperty('GH_TOKEN');
  if (!token) throw new Error('GH_TOKEN 미설정 — dispatch_proxy와 같은 프로젝트에 넣었는지 확인');
  const res = UrlFetchApp.fetch(
    'https://api.github.com/repos/' + MACRO_OWNER + '/' + MACRO_REPO +
      '/actions/workflows/' + MACRO_WORKFLOW + '/dispatches',
    {
      method: 'post',
      contentType: 'application/json',
      headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json' },
      payload: JSON.stringify({ ref: 'main', inputs: { mode: 'serve-slot' } }),
      muteHttpExceptions: true,
    });
  const code = res.getResponseCode();
  Logger.log('macro dispatch: %s %s', code, res.getContentText());
  if (code >= 300) {
    throw new Error('dispatch 실패 ' + code +
      ' — GH_TOKEN이 Macro_Section_Get에 actions:write 권한이 있는지 확인');
  }
}

function installMacroTriggers() {
  // 기존 매크로 트리거를 지우고 다시 설치한다(중복 방지, 재실행 안전).
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'fireMacroSlot') ScriptApp.deleteTrigger(t);
  });
  MACRO_SLOTS.forEach(function (slot) {
    ScriptApp.newTrigger('fireMacroSlot')
      .timeBased().everyDays(1).atHour(slot[0]).nearMinute(slot[1]).create();
  });
  Logger.log('설치 완료: 트리거 %s개', MACRO_SLOTS.length);
}
