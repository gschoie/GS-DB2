/** =====================================================================
 * [시험용] KRX 파생 투자자별 매매동향 — GAS(구글 IP)에서 열리는지 확인
 * ---------------------------------------------------------------------
 * 배경: 2026-09-18 네이버가 옛 수급 페이지를 410 으로 폐기하면서 K200 선물
 * 투자자별 수급이 끊겼다. 대체 경로를 찾았으나
 *   · 네이버 신규 SPA — 선물 화면 자체가 없음(/domestic/futures → 404)
 *   · 한투 OpenAPI — 선물 '투자자별' 엔드포인트가 아예 없음(공식 샘플로 확인)
 *   · KRX — GitHub 러너에서 400 LOGOUT (현물 대조군도 동일 → 러너 IP 차단으로 판단)
 * 세 번째가 IP 문제라면 **구글 IP에서 도는 GAS 는 통과할 수 있다.**
 * 이 파일은 그걸 확인만 한다(저장 안 함, 발송 안 함).
 *
 * [사용법]
 *  1. Apps Script 아무 프로젝트에 이 파일 내용을 붙여넣는다(새 파일로 만들어도 됨)
 *  2. 실행 드롭다운에서 testKrx 선택 → ▶
 *  3. 실행 로그를 그대로 복사해서 알려주면 된다
 * 확인이 끝나면 이 파일은 지운다.
 * ===================================================================== */

var KRX_JSON = 'https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd';
var KRX_MENU = 'https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201030104';

function testKrx() {
  // 1) 메뉴 페이지를 먼저 열어 세션 쿠키를 받는다(브라우저와 같은 순서).
  var cookie = '';
  try {
    var pre = UrlFetchApp.fetch(KRX_MENU, {
      muteHttpExceptions: true, followRedirects: true,
      headers: { 'User-Agent': UA_() }
    });
    var raw = pre.getAllHeaders()['Set-Cookie'];
    if (raw) {
      raw = (raw instanceof Array) ? raw : [raw];
      cookie = raw.map(function (c) { return String(c).split(';')[0]; }).join('; ');
    }
    Logger.log('메뉴 %s · 쿠키 %s', pre.getResponseCode(), cookie || '(없음)');
  } catch (e) {
    Logger.log('메뉴 열기 실패: %s', e);
  }

  var today = Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyyMMdd');
  var from = Utilities.formatDate(new Date(Date.now() - 10 * 864e5), 'Asia/Seoul', 'yyyyMMdd');

  // 2) 후보를 여러 개 던져 무엇이 통하는지 한 번에 본다.
  //    현물(02203)은 대조군 — 이것도 막히면 '내 파라미터 문제'가 아니라 접근 차단이다.
  var cases = [
    ['선물 투자자별 12901', {
      bld: 'dbms/MDC/STAT/standard/MDCSTAT12901',
      inqTpCd: '1', trdVolVal: '1', askBid: '3', prodId: 'KRDRVFUK2I',
      strtDd: from, endDd: today, share: '1', money: '1' }],
    ['선물 투자자별 12901(금액)', {
      bld: 'dbms/MDC/STAT/standard/MDCSTAT12901',
      inqTpCd: '1', trdVolVal: '2', askBid: '3', prodId: 'KRDRVFUK2I',
      strtDd: from, endDd: today, share: '1', money: '1' }],
    ['현물 투자자별 02203(대조군)', {
      bld: 'dbms/MDC/STAT/standard/MDCSTAT02203',
      inqTpCd: '1', trdVolVal: '2', askBid: '3', mktId: 'STK',
      strtDd: from, endDd: today, share: '1', money: '1' }]
  ];

  cases.forEach(function (c) {
    var name = c[0], payload = c[1];
    try {
      var h = { 'User-Agent': UA_(), 'Referer': KRX_MENU,
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json, text/javascript, */*; q=0.01' };
      if (cookie) h['Cookie'] = cookie;
      var r = UrlFetchApp.fetch(KRX_JSON, {
        method: 'post', payload: payload, headers: h,
        muteHttpExceptions: true, followRedirects: true
      });
      var body = r.getContentText().slice(0, 320).replace(/\s+/g, ' ');
      Logger.log('\n[%s] %s\n  %s', name, r.getResponseCode(), body);
    } catch (e) {
      Logger.log('\n[%s] 예외: %s', name, e);
    }
  });
  Logger.log('\n※ 200 + {"output":[...]} 가 보이면 성공. LOGOUT 이면 GAS 도 막힌 것.');
}

function UA_() {
  return 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
         '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';
}
