/*
 * 매매제한 컴플라이언스 대조 엔진 (순수 로직, 브라우저·Node 공용)
 *
 * AI는 자료 A(지시)·자료 B(파워베이스 캡처)에서 종목을 "읽기"만 하고,
 * 대조·상태 판정·집계는 전부 이 파일의 규칙으로 결정한다.
 * → 같은 입력이면 항상 같은 결과, 숫자 검산이 구조적으로 맞는다.
 *
 * 입력 형식 (extract 결과):
 * {
 *   check_date: "2026.10.31" | null,
 *   instructions: [{ name, code, action: "지정"|"해제"|"변경"|"취소", period, legible, source, note }],
 *   reflected:    [{ name, code, status: "적용"|"해제"|"불명", period, registered_at, legible, source, file_index, note }],
 *   capture_issues: ["..."]
 * }
 */
(function (root) {
  "use strict";

  const S = {
    MATCH: "✅ 일치",
    MISSING: "❌ 누락",
    EXTRA: "⚠️ 초과",
    CHECK: "❓ 확인필요",
    UNREAD: "🔎 판독불가",
  };
  // 이상 종목 우선 정렬 순서
  const ORDER = [S.MISSING, S.EXTRA, S.CHECK, S.UNREAD, S.MATCH];

  /** 종목코드: 문자열 유지(앞자리 0 보존). 공백 제거, 'A005930' 형태의 A 접두만 떼어 낸다. */
  function normCode(code) {
    if (code === null || code === undefined) return null;
    let c = String(code).normalize("NFKC").replace(/\s+/g, "").toUpperCase();
    if (!c || c === "-") return null;
    if (/^A\d{6}$/.test(c)) c = c.slice(1);
    return c;
  }

  /** 종목명: 공백·전각 차이만 무시. 우선주 '우', '우B' 등은 그대로 남아 다른 종목으로 구분된다. */
  function normName(name) {
    if (name === null || name === undefined) return null;
    const n = String(name).normalize("NFKC").replace(/\s+/g, "").toUpperCase();
    return n || null;
  }

  /** 기간 비교용: 숫자만 남긴다 (2026.10.31~2026.11.01 == 2026-10-31 ~ 2026-11-01). */
  function normPeriod(p) {
    if (!p) return null;
    const d = String(p).replace(/[^0-9]/g, "");
    return d || null;
  }

  function keyOf(item) {
    const c = normCode(item.code);
    if (c) return "C:" + c;
    const n = normName(item.name);
    return n ? "N:" + n : null;
  }

  function label(item) {
    const n = item && item.name ? item.name : "판독불가";
    const c = item && normCode(item.code) ? normCode(item.code) : "-";
    return `${n} / ${c}`;
  }

  /** 자료 A 정리: 취소 지시 제외, 중복 병합 */
  function prepareInstructions(list) {
    const out = [];
    const cancelled = [];
    const byKey = new Map();
    for (const raw of list || []) {
      const it = Object.assign({}, raw);
      if (it.action === "취소") {
        cancelled.push(it);
        continue;
      }
      const k = it.legible === false ? null : keyOf(it);
      if (k && byKey.has(k)) {
        const prev = byKey.get(k);
        prev._dupCount = (prev._dupCount || 1) + 1;
        if (!prev.code && it.code) prev.code = it.code;
        continue;
      }
      if (k) byKey.set(k, it);
      out.push(it);
    }
    return { items: out, cancelled };
  }

  /**
   * 자료 B 정리: 같은 캡처 안에서 두 번 나온 종목은 '중복 등록 의심',
   * 서로 다른 캡처에 걸쳐 나온 종목은 캡처 겹침으로 보고 하나로 합친다.
   */
  function prepareReflected(list) {
    const out = [];
    const byKey = new Map();
    for (const raw of list || []) {
      const it = Object.assign({}, raw);
      const k = it.legible === false ? null : keyOf(it);
      if (!k) {
        out.push(it);
        continue;
      }
      if (byKey.has(k)) {
        const prev = byKey.get(k);
        const sameFile =
          prev.file_index !== undefined && prev.file_index !== null && prev.file_index === it.file_index;
        if (sameFile) prev._dupInSameCapture = (prev._dupInSameCapture || 1) + 1;
        else prev._overlap = true;
        if (!prev.code && it.code) prev.code = it.code;
        // 한 행이라도 '적용'이면 적용 증거로 본다
        if (it.status === "적용") prev.status = "적용";
        continue;
      }
      byKey.set(k, it);
      out.push(it);
    }
    return out;
  }

  function judgeMatched(a, b, notes) {
    if (b.legible === false) return S.UNREAD;
    if (b._dupInSameCapture) {
      notes.push(`반영 화면에 동일 종목 ${b._dupInSameCapture}회 중복 등록`);
      return S.CHECK;
    }
    if (a.action === "해제") {
      if (b.status === "해제") return S.MATCH;
      if (b.status === "적용") {
        notes.push("해제 지시인데 반영 화면상 제한 유지");
        return S.CHECK;
      }
      notes.push("해제 여부 확인 불가");
      return S.CHECK;
    }
    // 지정 / 변경
    if (b.status === "해제") {
      notes.push("반영 화면상 해제 상태");
      return S.CHECK;
    }
    if (b.status !== "적용") {
      notes.push("화면상 매매제한 적용 증거 없음");
      return S.CHECK;
    }
    const pa = normPeriod(a.period);
    const pb = normPeriod(b.period);
    if (pa && pb && pa !== pb) {
      notes.push(`적용기간 상이 (지시: ${a.period} / 반영: ${b.period})`);
      return S.CHECK;
    }
    return S.MATCH;
  }

  /**
   * 대조 실행
   * @returns {{rows, counts, verdict, issues, cancelled, warnings, checkDate}}
   */
  function compare(extract, opts) {
    opts = opts || {};
    const { items: A, cancelled } = prepareInstructions(extract.instructions);
    const B = prepareReflected(extract.reflected);
    const used = new Set();
    const rows = [];
    const aHasUnread = A.some((x) => x.legible === false);

    const findB = (pred) => {
      for (let i = 0; i < B.length; i++) {
        if (used.has(i) || B[i].legible === false) continue;
        if (pred(B[i])) return i;
      }
      return -1;
    };

    for (const a of A) {
      const notes = [];
      if (a._dupCount) notes.push(`지시 자료에 ${a._dupCount}회 중복 기재`);
      if (a.action === "변경") notes.push("변경 지시");
      if (a.action === "해제") notes.push("해제 지시");

      if (a.legible === false) {
        rows.push(row(a, null, "판독불가", "-", S.UNREAD, notes.concat(a.note ? [a.note] : [])));
        continue;
      }
      const ac = normCode(a.code);
      const an = normName(a.name);

      // 1) 코드 일치 최우선
      let bi = ac ? findB((b) => normCode(b.code) === ac) : -1;
      if (bi >= 0) {
        used.add(bi);
        const b = B[bi];
        const bn = normName(b.name);
        if (an && bn && an !== bn) {
          notes.push(`코드 일치, 종목명 상이 (지시: ${a.name} / 반영: ${b.name})`);
          rows.push(row(a, b, "O", "O", S.CHECK, notes));
        } else {
          const st = judgeMatched(a, b, notes);
          rows.push(row(a, b, "O", st === S.UNREAD ? "판독불가" : "O", st, notes));
        }
        continue;
      }

      // 2) 종목명 일치
      bi = an ? findB((b) => normName(b.name) === an) : -1;
      if (bi >= 0) {
        used.add(bi);
        const b = B[bi];
        const bc = normCode(b.code);
        if (ac && bc && ac !== bc) {
          // 이름이 같아도 코드가 다르면 절대 동일 종목으로 자동 처리하지 않음
          notes.push(`종목명 동일, 코드 상이 (지시: ${ac} / 반영: ${bc})`);
          rows.push(row(a, b, "O", "O", S.CHECK, notes, `${ac} / ${bc}`));
          continue;
        }
        // 지시 메시지는 보통 종목명만 오므로(!ac && bc) 종목명 정확 일치면 별도 비고 없이 일치 처리
        if (ac && !bc) notes.push("반영 화면에 코드 미표시 — 종목명 정확히 일치");
        const st = judgeMatched(a, b, notes);
        rows.push(row(a, b, "O", st === S.UNREAD ? "판독불가" : "O", st, notes));
        continue;
      }

      // 3) 반영 결과에 없음
      if (a.action === "해제") {
        notes.push("반영 목록에 없음 (해제 반영으로 간주)");
        rows.push(row(a, null, "O", "X", S.MATCH, notes));
      } else {
        rows.push(row(a, null, "O", "X", S.MISSING, notes));
      }
    }

    // 4) 지시에 없는 반영 종목
    B.forEach((b, i) => {
      if (used.has(i)) return;
      const notes = [];
      if (b.legible === false) {
        notes.push(b.note || b.source || "판독불가 행");
        rows.push(row(null, b, "-", "판독불가", S.UNREAD, notes));
        return;
      }
      if (b._dupInSameCapture) notes.push(`반영 화면에 동일 종목 ${b._dupInSameCapture}회 중복 등록`);
      if (aHasUnread) notes.push("지시 자료에 판독불가 항목 있음 — 해당 종목일 가능성 확인");
      if (b.status === "적용") {
        rows.push(row(null, b, "X", "O", S.EXTRA, notes));
      } else {
        notes.unshift(b.status === "해제" ? "지시 없음, 화면상 해제 표시" : "지시 없음, 제한 적용 여부 불명");
        rows.push(row(null, b, "X", b.status === "해제" ? "해제" : "?", S.CHECK, notes));
      }
    });

    // 등록시각 참고 표시 (판정에는 영향 없음)
    for (const r of rows) {
      if (r._b && r._b.registered_at) r.registered_at = r._b.registered_at;
      if (r._b && r._b._overlap) r.notes.push("여러 캡처에 걸쳐 표시(겹침, 1건 처리)");
    }

    rows.sort((x, y) => ORDER.indexOf(x.status) - ORDER.indexOf(y.status));
    rows.forEach((r, i) => (r.no = i + 1));

    const counts = {
      instructed: A.length,
      total: rows.length,
      match: 0,
      missing: 0,
      extra: 0,
      check: 0,
      unread: 0,
    };
    for (const r of rows) {
      if (r.status === S.MATCH) counts.match++;
      else if (r.status === S.MISSING) counts.missing++;
      else if (r.status === S.EXTRA) counts.extra++;
      else if (r.status === S.CHECK) counts.check++;
      else if (r.status === S.UNREAD) counts.unread++;
    }
    // 숫자 검산
    const sum = counts.match + counts.missing + counts.extra + counts.check + counts.unread;
    if (sum !== counts.total) throw new Error(`집계 불일치: ${sum} != ${counts.total}`);

    const warnings = [];
    for (const w of extract.capture_issues || []) warnings.push(w);
    if (opts.noA) warnings.push("자료 A(매매제한 지시)가 첨부되지 않음");
    if (opts.noB) warnings.push("자료 B(파워베이스 반영 화면)가 첨부되지 않음");
    if (A.length === 0 && !opts.noA) warnings.push("자료 A에서 지시 종목을 찾지 못함");

    const anomalies = counts.missing + counts.extra + counts.check;
    const incomplete = counts.unread > 0 || warnings.length > 0;
    let verdict;
    if (anomalies && incomplete) verdict = "🚨 이상 발견 / 일부 검증 미완료";
    else if (anomalies) verdict = "🚨 이상 발견";
    else if (incomplete) verdict = "🔎 검증 미완료";
    else verdict = "✅ 전체 일치";

    const issues = rows.filter((r) => r.status !== S.MATCH);

    return {
      checkDate: opts.checkDate || extract.check_date || null,
      rows: rows.map(stripPrivate),
      counts,
      verdict,
      issues: issues.map(stripPrivate),
      cancelled,
      warnings,
    };
  }

  function row(a, b, inA, inB, status, notes, codeOverride) {
    const src = a || b;
    let code = codeOverride || normCode(a && a.code) || normCode(b && b.code) || "-";
    let name = (a && a.name) || (b && b.name) || "판독불가";
    if (status === S.UNREAD && !(src && src.name)) name = "판독불가";
    return {
      no: 0,
      name,
      code,
      inA,
      inB,
      status,
      notes: notes.filter(Boolean),
      registered_at: null,
      sourceA: a ? a.source || null : null,
      sourceB: b ? b.source || null : null,
      _b: b,
    };
  }

  function stripPrivate(r) {
    const o = Object.assign({}, r);
    delete o._b;
    return o;
  }

  function issueLine(r) {
    const tag = r.status.split(" ")[0];
    const who = `[${r.name} / ${r.code}]`;
    if (r.status === S.MISSING) return `- ${tag} ${who}: 지시 O, 반영 X`;
    if (r.status === S.EXTRA) return `- ${tag} ${who}: 지시 X, 반영 O${r.notes.length ? " (" + r.notes.join("; ") + ")" : ""}`;
    if (r.status === S.UNREAD) {
      const where = [r.sourceA, r.sourceB].filter(Boolean).join(", ");
      return `- ${tag} [${r.name}${where ? " · " + where : ""}]: 판독불가, 재확인 필요`;
    }
    return `- ${tag} ${who}: ${r.notes.join("; ") || "불일치"}`;
  }

  function closingSentence(res) {
    const c = res.counts;
    const parts = [];
    const names = (st) => res.rows.filter((r) => r.status === st).map((r) => r.name);
    if (c.missing) parts.push(`누락 종목(${names(S.MISSING).join(", ")})은 파워베이스 매매제한 등록 필요`);
    if (c.extra) parts.push(`초과 종목(${names(S.EXTRA).join(", ")})은 지시 여부 확인 후 해제 검토`);
    if (c.check) parts.push(`확인필요 종목(${names(S.CHECK).join(", ")})은 코드·상태·기간 재확인`);
    if (c.unread) parts.push(`판독불가 ${c.unread}건은 선명한 캡처로 재검증 필요`);
    if (res.warnings.length) parts.push(`자료 확인사항: ${res.warnings.join("; ")}`);
    if (!parts.length) return "추가 조치 필요 없음.";
    return parts.join(". ") + ".";
  }

  /** 메신저에 그대로 붙여넣을 수 있는 텍스트 보고서 */
  function renderText(res) {
    const c = res.counts;
    const L = [];
    L.push("[아침 컴플라이언스 매매제한 점검]");
    L.push("");
    L.push(`- 점검일: ${res.checkDate || "미상"}`);
    L.push(`- 검증 결과: ${res.verdict}`);
    L.push(`- 지시 종목: ${c.instructed}건`);
    L.push(`- 일치: ${c.match}건`);
    L.push(`- 누락: ${c.missing}건`);
    L.push(`- 초과: ${c.extra}건`);
    L.push(`- 확인필요: ${c.check}건`);
    L.push(`- 판독불가: ${c.unread}건`);
    L.push("");
    if (res.issues.length) {
      L.push("🚨 확인이 필요한 종목");
      L.push("");
      for (const r of res.issues) L.push(issueLine(r));
    } else if (!res.warnings.length) {
      L.push("✅ 전체 일치 — 이상 없음");
    }
    if (res.warnings.length) {
      L.push("");
      L.push("🔎 자료 확인사항");
      for (const w of res.warnings) L.push(`- ${w}`);
    }
    L.push("");
    L.push("| No | 종목명 | 종목코드 | 지시(A) | 반영(B) | 상태 | 비고 |");
    L.push("|---|---|---|---|---|---|---|");
    for (const r of res.rows) {
      const note = r.notes.join("; ").replace(/\|/g, "/") || "";
      L.push(`| ${r.no} | ${r.name} | ${r.code} | ${r.inA} | ${r.inB} | ${r.status} | ${note} |`);
    }
    if (res.cancelled.length) {
      L.push("");
      L.push(`※ 취소·정정으로 제외한 지시: ${res.cancelled.map(label).join(", ")}`);
    }
    L.push("");
    L.push("검증 집계");
    L.push("");
    L.push(`- 총 지시: ${c.instructed}건`);
    L.push(`- 전체 비교 대상(중복 제거): ${c.total}건`);
    L.push(`- 일치: ${c.match}건`);
    L.push(`- 누락: ${c.missing}건`);
    L.push(`- 초과: ${c.extra}건`);
    L.push(`- 확인필요: ${c.check}건`);
    L.push(`- 판독불가: ${c.unread}건`);
    L.push("");
    L.push(closingSentence(res));
    L.push("");
    L.push("※ 캡처 기준 대조 결과임 (파워베이스 실시스템 조회 아님).");
    return L.join("\n");
  }

  const api = { STATUS: S, normCode, normName, normPeriod, compare, renderText, closingSentence };
  root.ComplianceMatcher = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
