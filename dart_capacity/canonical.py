"""정규화 행의 부문·품목 이름을 회사 안에서 통일하고, 같은 (줄, 기간) 행을 합친다.

모델이 보고서마다 '엔 진 기 계'/'엔진기계', '선 박'/'선박 (HD현대중공업㈜)' 처럼 조금씩 다르게 적어
대시보드에서 같은 줄이 수십 개로 쪼개졌다(10/20 실측). 규칙:
  1. 비교 키 = 공백 제거 + 가운뎃점 통일 + 꼬리 '등' 제거. 괄호 안 회사명은 따로 떼어 둔다.
  2. 최신 보고서의 이름이 그 줄의 표시 이름. 이전 보고서의 행은 같은 부문 안에서
     품목 키가 같거나 한쪽이 다른 쪽을 포함하거나 유사도 0.8 이상이면 그 줄로 흡수.
     괄호 회사명이 둘 다 있고 서로 다르면 다른 줄(HD현대중공업㈜ vs HD현대엔진(유)).
  3. 같은 (회사, 줄, 기간) 행은 하나로 — 값은 필드마다 '값이 있는 가장 최신 보고서' 것.
     능력(천GT)과 실적(백만원)이 다른 표에서 와도 한 줄에 모인다(단위는 각각 보존).
"""
from __future__ import annotations

import difflib
import re

_SIM = 0.8


def _norm(s: str) -> str:
    """비교 키: 공백 제거, 나열 구분자(쉼표·슬래시·가운뎃점)는 전부 쉼표로, 꼬리 '등' 제거."""
    s = (s or "").strip()
    s = re.sub(r"[ㆍ・·/,]", ",", s)
    s = re.sub(r"\s+", "", s)
    s = re.sub(r",?등$", "", s)
    return s.strip(" ,")


_CO_TOKEN = re.compile(r"[가-힣A-Za-z0-9]+(?:㈜|\(주\)|\(유\))")


def _same_company(a: str, b: str) -> bool:
    """회사 키 비교: 같거나 포함 관계거나, ㈜ 로 끝나는 회사 토큰을 하나라도 공유하면 같은 회사
    ('한화세미텍㈜(구.한화정밀기계㈜)및해외생산법인' ↔ '한화정밀기계㈜및해외생산법인')."""
    if a == b or a in b or b in a:
        return True
    return bool(set(_CO_TOKEN.findall(a)) & set(_CO_TOKEN.findall(b)))


_CO_RE = re.compile(r"㈜|\(주\)|법인|Ltd|Inc|Pte|\(유\)|종속회사|부문")


def _split_company(product: str) -> tuple[str, str]:
    """product 를 (품목 키, 회사 키) 로. 회사명은 괄호 안('선박 (HD현대중공업㈜ 外)')일 수도, 밖('한화시스템㈜ (전술통신장비 등)',
    '한화에어로스페이스㈜ - 자주포 …', '한화정밀기계㈜ 및 해외생산법인 / 칩마운터 …')일 수도 있어 ㈜·법인 같은 표지로 가른다.
    괄호가 중첩돼도('HD현대엔진(유)') 첫 여는 괄호 ~ 마지막 닫는 괄호를 한 덩어리로 본다."""
    p = (product or "").strip()
    # 마지막 괄호 묶음을 균형 맞춰 찾는다: '선박엔진 (HD현대엔진(유))' → '(HD현대엔진(유))',
    # '한화세미텍㈜(구.한화정밀기계㈜) 및 해외생산법인 (칩마운터, 공작기계 등)' → '(칩마운터, 공작기계 등)'.
    # 괄호 안팎에 모두 회사 표지가 있으면('한화비전㈜(舊. 한화테크윈㈜) …') 그 괄호는 사명 변경 주석 — 떼고 다시 본다.
    while True:
        j = max(p.rfind(")"), p.rfind("）"))
        i, depth = -1, 0
        for pos in range(j, -1, -1) if j >= 0 else []:
            if p[pos] in ")）":
                depth += 1
            elif p[pos] in "(（":
                depth -= 1
                if depth == 0:
                    i = pos
                    break
        if i < 0 or j <= i:
            break
        outside, inside = (p[:i] + p[j + 1:]).strip(), p[i + 1:j].strip()
        if _CO_RE.search(inside) and not _CO_RE.search(outside):
            return _norm(outside), _norm(inside)
        if _CO_RE.search(outside) and not _CO_RE.search(inside):
            return _norm(inside), _norm(outside)
        if _CO_RE.search(inside) and _CO_RE.search(outside):
            p = outside
            continue
        return _norm(outside), _norm(inside)
    m = re.match(r"^(.+?)\s*[-:/]\s+(.+)$", p)          # '한화에어로스페이스㈜: 자주포 …', '회사 / 품목', '회사 - 품목'
    if m and _CO_RE.search(m.group(1)) and not _CO_RE.search(m.group(2)):
        return _norm(m.group(2)), _norm(m.group(1))
    return _norm(p), ""


def display(s: str) -> str:
    """표시 이름: '엔 진 기 계'·'합    계'처럼 글자를 띄어 쓴 낱말만 붙인다(모든 토큰이 2자 이하일 때).
    '엔진류, 기계설비 등' 같은 설명은 그대로 둔다."""
    s = re.sub(r"\s+", " ", (s or "").strip())
    toks = s.split(" ")
    if len(toks) > 1 and len("".join(toks)) <= 4 and all(len(t) <= 2 and re.fullmatch(r"[가-힣]+", t) for t in toks):
        return "".join(toks)                           # 낱말 하나를 띄어 쓴 경우만('상선 조립 및 건조 등' 은 그대로)
    return s


def line_key(row: dict) -> tuple[str, str, str]:
    core, comp = _split_company(row.get("product", ""))
    return (_norm(row.get("segment", "")), core, comp)


def _same_line(a: tuple, b: tuple) -> bool:
    seg_a, prod_a, comp_a = a
    seg_b, prod_b, comp_b = b
    if seg_a != seg_b and not (seg_a and seg_b and (seg_a in seg_b or seg_b in seg_a)):
        return False
    if comp_a and comp_b and not _same_company(comp_a, comp_b):
        return False
    if prod_a == prod_b:
        return True
    if prod_a and prod_b and (prod_a in prod_b or prod_b in prod_a):
        return True
    return bool(prod_a and prod_b) and difflib.SequenceMatcher(None, prod_a, prod_b).ratio() >= _SIM


def canonicalize(rows: list[dict]) -> list[dict]:
    """회사별 줄 이름 통일 + 같은 (줄, 기간) 병합. 입력은 바꾸지 않는다."""
    by_company: dict[str, list[dict]] = {}
    for r in rows:
        by_company.setdefault(r.get("stock_code", ""), []).append(r)
    out: list[dict] = []
    for code, crows in by_company.items():
        crows = sorted(crows, key=lambda r: r.get("source_rcept_no", ""), reverse=True)   # 최신 보고서 먼저
        canon: list[tuple[tuple, dict]] = []                                            # (key, 표시 이름)
        merged: dict[tuple, dict] = {}
        for r in crows:
            k = line_key(r)
            hit = next((c for c in canon if _same_line(c[0], k)), None)
            if hit is None:
                hit = (k, {"segment": display(r.get("segment", "")), "product": display(r.get("product", ""))})
                canon.append(hit)
            name = hit[1]
            mk = (code, hit[0], r.get("period", ""))
            cur = merged.get(mk)
            if cur is None:
                merged[mk] = {**r, "segment": name["segment"], "product": name["product"],
                              "sources": [r.get("source_rcept_no", "")]}
                continue
            # 최신 보고서가 먼저 왔으므로, 비어 있는 칸만 옛 보고서 값으로 채운다
            for f, u in (("capacity", "capacity_unit"), ("production", "production_unit"), ("utilization_pct", None)):
                if cur.get(f) is None and r.get(f) is not None:
                    cur[f] = r[f]
                    if u:
                        cur[u] = r.get(u) or cur.get(u, "")
            if not cur.get("note") and r.get("note"):
                cur["note"] = r["note"]                # 비고는 최신 보고서 것만(이어 붙이면 같은 말이 세 번 반복된다)
            if r.get("source_rcept_no") not in cur["sources"]:
                cur["sources"].append(r.get("source_rcept_no", ""))
        for row in merged.values():
            if row.get("capacity_unit") and row.get("production_unit") and row["capacity_unit"] == row["production_unit"]:
                row["unit"] = row["capacity_unit"]
            out.append(row)
    out.sort(key=lambda r: (r.get("sector", ""), r.get("company", ""), r.get("segment", ""), r.get("product", ""), r.get("period", "")))
    return out
