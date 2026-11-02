// 실행: node --test compliance_check/
const test = require("node:test");
const assert = require("node:assert");
const M = require("../telegram_research_dashboard/static/compliance/matcher.js");
const S = M.STATUS;

const ins = (name, code = null, extra = {}) =>
  Object.assign({ name, code, action: "지정", period: null, legible: true, source: "A", note: null }, extra);
const ref = (name, code = null, extra = {}) =>
  Object.assign(
    { name, code, status: "적용", period: null, registered_at: null, legible: true, source: "B-1", file_index: 1, note: null },
    extra
  );
const run = (instructions, reflected, extra = {}) =>
  M.compare(Object.assign({ check_date: "2026.10.31", instructions, reflected, capture_issues: [] }, extra));
const byName = (res, n) => res.rows.find((r) => r.name === n);

test("코드 정규화: 앞자리 0 보존, A 접두 제거", () => {
  assert.strictEqual(M.normCode("005930"), "005930");
  assert.strictEqual(M.normCode("A005930"), "005930");
  assert.strictEqual(M.normCode(" 0001A0 "), "0001A0");
  assert.strictEqual(M.normCode("-"), null);
});

test("전체 일치 (지시는 이름만, 반영은 코드 포함)", () => {
  const names = ["기아", "현대모비스", "HL만도", "현대건설", "현대제철", "GS건설", "키움증권", "에이피알", "효성중공업", "대덕전자", "DL이앤씨"];
  const res = run(names.map((n) => ins(n)), names.map((n, i) => ref(n, String(i).padStart(6, "0"))));
  assert.strictEqual(res.verdict, "✅ 전체 일치");
  assert.strictEqual(res.counts.instructed, 11);
  assert.strictEqual(res.counts.match, 11);
  assert.match(M.renderText(res), /✅ 전체 일치 — 이상 없음/);
});

test("누락·초과", () => {
  const res = run([ins("기아"), ins("현대모비스")], [ref("기아", "000270"), ref("현대차", "005380")]);
  assert.strictEqual(byName(res, "현대모비스").status, S.MISSING);
  assert.strictEqual(byName(res, "현대차").status, S.EXTRA);
  assert.strictEqual(res.verdict, "🚨 이상 발견");
  assert.strictEqual(res.rows[0].status, S.MISSING); // 이상 종목 우선 정렬
});

test("우선주는 다른 종목", () => {
  const res = run([ins("삼성전자")], [ref("삼성전자우", "005935")]);
  assert.strictEqual(byName(res, "삼성전자").status, S.MISSING);
  assert.strictEqual(byName(res, "삼성전자우").status, S.EXTRA);
});

test("종목명 같고 코드 다르면 확인필요, 두 코드 병기", () => {
  const res = run([ins("기아", "000270")], [ref("기아", "000271")]);
  assert.strictEqual(res.rows.length, 1);
  assert.strictEqual(res.rows[0].status, S.CHECK);
  assert.strictEqual(res.rows[0].code, "000270 / 000271");
});

test("코드 같고 이름 다르면 확인필요", () => {
  const res = run([ins("기아", "000270")], [ref("기아차", "000270")]);
  assert.strictEqual(res.rows[0].status, S.CHECK);
});

test("적용 증거 없음·기간 상이는 확인필요", () => {
  const res = run(
    [ins("기아"), ins("GS건설", null, { period: "2026.10.31~2026.11.01" })],
    [ref("기아", null, { status: "불명" }), ref("GS건설", null, { period: "2026-10-31 ~ 2026-11-02" })]
  );
  assert.strictEqual(byName(res, "기아").status, S.CHECK);
  assert.strictEqual(byName(res, "GS건설").status, S.CHECK);
});

test("같은 캡처 안 중복은 확인필요, 다른 캡처 간 겹침은 1건", () => {
  const res = run(
    [ins("기아"), ins("현대건설")],
    [ref("기아"), ref("기아"), ref("현대건설", null, { file_index: 1 }), ref("현대건설", null, { file_index: 2 })]
  );
  assert.strictEqual(res.rows.length, 2);
  assert.strictEqual(byName(res, "기아").status, S.CHECK);
  assert.strictEqual(byName(res, "현대건설").status, S.MATCH);
});

test("판독불가 → 검증 미완료, 이상과 동시면 병기", () => {
  let res = run([ins("기아")], [ref("기아"), ref(null, null, { legible: false })]);
  assert.strictEqual(res.verdict, "🔎 검증 미완료");
  res = run([ins("기아"), ins("현대제철")], [ref("기아"), ref(null, null, { legible: false })]);
  assert.strictEqual(res.verdict, "🚨 이상 발견 / 일부 검증 미완료");
});

test("취소 지시 제외, 해제 지시 처리", () => {
  const res = run(
    [ins("기아"), ins("기아", null, { action: "취소" }), ins("현대제철", null, { action: "해제" })],
    [ref("현대제철")]
  );
  // 취소는 제외하지만 '기아' 지정 지시 자체는 남는다(같은 이름의 취소 처리는 AI 추출 단계 몫)
  assert.strictEqual(res.cancelled.length, 1);
  assert.strictEqual(byName(res, "현대제철").status, S.CHECK);
});

test("캡처 문제 보고 시 전체 일치 선언 금지", () => {
  const res = run([ins("기아")], [ref("기아")], { capture_issues: ["목록 하단이 잘려 있음"] });
  assert.strictEqual(res.verdict, "🔎 검증 미완료");
});

test("집계 합계 = 대조표 행 수", () => {
  const res = run([ins("기아"), ins("A"), ins("B", null, { legible: false })], [ref("기아"), ref("C")]);
  const c = res.counts;
  assert.strictEqual(c.match + c.missing + c.extra + c.check + c.unread, res.rows.length);
});
