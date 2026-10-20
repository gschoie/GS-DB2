"""원문 zip 에서 '생산능력 / 생산실적 / 가동률' 섹션의 표만 잘라낸다.

  python extract.py                     # data/raw/doc/*.zip 전부(이미 추출된 rcept_no 는 건너뜀)
  python extract.py --codes 329180      # 일부 회사만
  python extract.py --force --preview   # 다시 추출 + 표 미리보기 출력

산출물(보고서당):
  data/extracted/<종목코드>_<rcept_no>.html  — 표를 원본 마크업 그대로 + 바로 앞 제목·단위 문구
  data/extracted/<종목코드>_<rcept_no>.json  — 같은 내용의 기계용(표마다 heading·unit·rows·html)

표 선정 규칙: 표 본문 또는 **표 바로 앞 블록(이전 표 이후의 제목·문단·단위 문구)** 에
키워드가 있으면 뽑는다. 'Ⅱ. 사업의 내용' 밖(재무제표 주석 등)의 우연한 일치는 섹션 제목을
같이 적어 두고 정규화 단계에서 판단한다 — 여기서는 버리지 않는다.
"""
from __future__ import annotations

import argparse
import hashlib
import html as htmllib
import json
import re
import sys
import zipfile
from pathlib import Path

import warnings

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
sys.stdout.reconfigure(line_buffering=True)

from common import DART_VIEWER, EXTRACTED, load_index

DOC_DIR = Path(__file__).resolve().parent / "data" / "raw" / "doc"
KEYWORDS = ("생산능력", "생산실적", "가동률", "가동율")
_KW_RE = re.compile("|".join(KEYWORDS))
_UNIT_RE = re.compile(r"단\s*위")
HEADING_MAX = 60          # 이보다 긴 문단은 제목이 아니라 본문(각주 문장)으로 본다
CONTEXT_MAX = 12          # 표 앞에서 거슬러 올라가 담아 두는 블록 수 상한(문맥 보존용)
NEAR = 4                  # 키워드 판정에 쓰는 '바로 앞' 블록 수 — 멀리 있는 각주 문장에 끌려가지 않게
# 셀 하나가 통째로 지표 이름인 경우만 표 본문 적중으로 친다 — '생산능력 향상'(투자 기대효과) 같은
# 서술형 셀은 제외. 머리글 행(첫 행·th)은 포함 일치로 본다.
_CELL_RE = re.compile(r"^(생산능력|생산실적|가동률|가동율)\s*(\([^)]*\)\s*)*(\(%\))?\s*(\(.*\))?$")
_TINY_CELLS = 2           # 이 수 이하의 셀만 가진 표는 '단위 표'나 '각주 표'로 본다


def _decode(raw: bytes) -> str:
    head = raw[:200].decode("ascii", errors="ignore")
    m = re.search(r'encoding="([^"]+)"', head)
    for enc in ([m.group(1)] if m else []) + ["utf-8", "cp949", "euc-kr"]:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _text(el: Tag) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def _lines(el: Tag) -> list[str]:
    """요소 안의 줄(태그 경계)을 따로 — DART 는 제목 여러 줄을 한 요소에 담기도 한다
    ('(2) 산출의 근거 … 라. 생산실적 및 가동률 (1) 생산실적' 이 한 P 로 온 두산밥캣 실측)."""
    raw = el.get_text("\n", strip=True)
    return [re.sub(r"\s+", " ", ln).strip() for ln in raw.split("\n") if ln.strip()]


_BLOCK_TAGS = ("p", "title", "tu", "te", "span", "div", "h1", "h2", "h3", "h4")
_TEXT_PARENTS = ("p", "title", "tu", "te")


def _is_heading(txt: str) -> bool:
    """짧고 서술형이 아닌 문장만 제목으로 — '…입니다.' '…합니다.' '※ …' 는 각주 문장."""
    if not txt or len(txt) > HEADING_MAX:
        return False
    if txt.startswith(("※", "주)", "주1", "(주")):
        return False
    if re.search(r"(다|음|함|임)\s*\.?$", txt):
        return False
    return True


_SUB_RE = re.compile(r"(?=\(\d+\)\s*)|(?=\b\d+\)\s*)|(?=[가-힣]\.\s)|(?=[①-⑳])")


def _heading_tail(txt: str) -> str:
    """'다. 주요 원재료 및 생산능력 (1) 주요 원재료 등의 현황' → '(1) 주요 원재료 등의 현황'.
    상위 항목 이름에 든 키워드로 하위 표가 끌려오지 않게 마지막 소항목만 본다."""
    parts = [p.strip() for p in _SUB_RE.split(txt) if p and p.strip()]
    return parts[-1] if parts else txt


def _is_note_table(rows: list[list[str]], ttext: str) -> bool:
    """산출기준·산출방법 같은 짧은 2열 목록 표(숫자 표가 아님)."""
    if not rows or len(rows) > 8 or len(ttext) > 400:
        return False
    if any(len(r) > 2 for r in rows):
        return False
    digits = sum(ch.isdigit() for ch in ttext)
    return digits < len(ttext) * 0.1 and any(r[0].startswith(("ㆍ", "·", "-", "※")) or (len(r) > 1 and r[1].startswith(":")) for r in rows)


def _level(txt: str) -> int:
    """제목 위계: 1 '가.' · 2 '(1)' · 3 '1)'/'가)'/'①'/'[라벨]' · 0 번호 없음."""
    if re.match(r"^[가-힣]\.\s", txt):
        return 1
    if re.match(r"^\(\d+\)", txt):
        return 2
    if re.match(r"^(\d+\)|[가-힣]\)|[①-⑳]|\[)", txt):
        return 3
    return 0


def _nearest_heading_kw(near: list[str]) -> list[str]:
    """가장 가까운 제목 한 줄로 판정한다 — 상위 항목('다. 주요 원재료 및 생산능력')의 키워드가
    하위 표(원재료 현황)로 흘러들지 않게. 가까운 줄이 하위 라벨('가) 국내', '[회사명]')이면 한 줄 더 올라간다."""
    for h in reversed(near):
        kws = sorted(set(_KW_RE.findall(_heading_tail(h))))
        if kws:
            return kws
        if _level(h) >= 3:
            continue
        return []
    return []


def _cell_hit(rows: list[list[str]]) -> list[str]:
    """지표 이름 셀(또는 머리글 포함)에서 적중한 키워드."""
    hits = set()
    for i, row in enumerate(rows):
        for cell in row:
            c = cell.strip()
            if i == 0:
                hits.update(_KW_RE.findall(c))
            elif _CELL_RE.match(c):
                hits.update(_KW_RE.findall(c))
    return sorted(hits)


def _rows(table: Tag) -> list[list[str]]:
    rows = []
    for tr in table.find_all("tr"):
        cells = [_text(td) for td in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(cells)
    return rows


def extract_tables(doc: str) -> tuple[list[dict], list[dict]]:
    """(채택 표, 탈락 후보). 문서를 **한 번만** 앞으로 훑으며 '이전 표 이후의 제목·문단 줄'을
    버퍼에 모아 두었다가 표를 만나면 그 버퍼가 문맥이 된다 — 표마다 뒤로 되짚는 방식은
    큰 보고서(표 수백 개)에서 문서당 40초가 걸렸다(10/19 실측).
    탈락 후보는 느슨한 일치(아무 셀·아무 문맥)만 된 것 — 검토용."""
    soup = BeautifulSoup(doc, "lxml")
    found: list[dict] = []
    rejected: list[dict] = []
    ctx: list[str] = []          # 이전 (일반) 표 이후의 문맥 줄
    titles: list[str] = []       # 최근 TITLE 3개 (섹션 경로)
    pending_unit = ""            # 바로 앞 '단위 표'의 문구
    since_found = 1              # 마지막 채택 표 이후 지나간 일반 표 수 — 0일 때만 각주·산출기준 표를 붙인다
    for el in soup.find_all(True):
        name = el.name
        if name == "table":
            if el.find_parent("table") is not None:
                continue                              # 중첩 표는 바깥 표에 포함
            rows = _rows(el)
            ttext = _text(el)
            ncells = sum(len(r) for r in rows)
            # (단위 : 백만원) 만 든 한두 칸짜리 표 → 다음 표의 단위 (문맥에도 남긴다)
            if ncells <= _TINY_CELLS and _UNIT_RE.search(ttext):
                pending_unit = ttext
                ctx.append(ttext)
                continue
            # '※ …'·'주1) …' 한 칸짜리 각주 표 → **바로 앞** 채택 표의 각주 (다른 표를 지나왔으면 무관한 각주)
            if ncells <= _TINY_CELLS and (ttext.startswith("※") or re.match(r"주\s*\d*\)", ttext)):
                if found and since_found == 0 and ttext not in found[-1]["footnotes"]:
                    found[-1]["footnotes"].append(ttext)
                ctx.append(ttext)
                continue
            if ncells <= _TINY_CELLS:
                if ttext:
                    ctx.append(ttext)
                continue
            # 'ㆍ선 박 | : 도크의 최대 건조가능 용량 기준' 꼴의 산출기준 표(짧은 2열 목록) → 바로 앞 채택 표의 각주
            if _is_note_table(rows, ttext):
                if found and since_found == 0:
                    found[-1]["footnotes"].append(" / ".join(" ".join(r) for r in rows))
                continue
            context = ctx[-CONTEXT_MAX * 3:]
            headings = [t for t in context if _is_heading(t) and not _UNIT_RE.search(t)]
            near = [t for t in context[-NEAR:] if _is_heading(t) and not _UNIT_RE.search(t)]
            kw_table = _cell_hit(rows)
            kw_ctx = _nearest_heading_kw(near)
            unit_texts = [t for t in context if _UNIT_RE.search(t)]
            unit = unit_texts[-1] if unit_texts else pending_unit
            pending_unit = ""
            record = {
                "section": list(titles[-3:]),
                "headings": headings,
                "context": context,
                "unit": unit,
                "keywords": sorted(set(kw_table) | set(kw_ctx)),
                "keyword_in": "table" if kw_table else ("heading" if kw_ctx else ""),
                "rows": rows,
                "html": str(el),
                "footnotes": [],
                "digest": hashlib.md5(ttext.encode("utf-8")).hexdigest()[:12],
            }
            ctx = []                                  # 일반 표를 지났으니 문맥은 여기서 끊긴다
            if kw_table or kw_ctx:
                found.append(record)
                since_found = 0
                continue
            since_found += 1
            loose = sorted(set(_KW_RE.findall(ttext)) | {k for t in context for k in _KW_RE.findall(t)})
            if loose:
                rejected.append({**record, "keywords": loose, "html": "", "rows": rows[:3],
                                 "why": "셀 전체가 지표명이 아니거나 멀리 있는 문장에만 키워드"})
            continue
        if name not in _BLOCK_TAGS:
            continue
        if el.find_parent("table") is not None:
            continue
        if name in ("span", "div") and any(el.find_parent(t) is not None for t in _TEXT_PARENTS):
            continue                                  # 부모 문단이 이미 담는 텍스트
        if name == "div" and el.find(["p", "div", "table", "title"]) is not None:
            continue                                  # 블록을 품은 컨테이너 — 자식이 각자 줄을 낸다(중복 방지)
        if name in ("p", "div") and el.find_parent(["p", "div", "tu", "te"]) is not None and name == "p":
            pass
        lines = _lines(el)
        if not lines:
            continue
        if name == "title":
            titles.append(" ".join(lines))
        ctx.extend(lines)
        if len(ctx) > CONTEXT_MAX * 6:
            ctx = ctx[-CONTEXT_MAX * 3:]
    return found, rejected


def extract_zip(zip_path: Path) -> tuple[list[dict], list[dict]]:
    tables: list[dict] = []
    rejected: list[dict] = []
    seen: set[str] = set()
    with zipfile.ZipFile(zip_path) as zf:
        names = sorted(n for n in zf.namelist() if n.lower().endswith((".xml", ".html", ".htm")))
        # 본문(<rcept_no>.xml)을 먼저, 첨부는 뒤에
        names.sort(key=lambda n: (0 if re.fullmatch(r"\d+\.xml", Path(n).name) else 1, n))
        for name in names:
            doc = _decode(zf.read(name))
            got, rej = extract_tables(doc)
            for t in got:
                if t["digest"] in seen:
                    continue
                seen.add(t["digest"])
                t["file"] = Path(name).name
                tables.append(t)
            for t in rej:
                t["file"] = Path(name).name
                rejected.append(t)
    return tables, rejected


def _esc(s: str) -> str:
    return htmllib.escape(s, quote=False)


def render_html(meta: dict, tables: list[dict]) -> str:
    head = (f"<h1>{_esc(meta.get('company',''))} ({meta.get('stock_code','')}) · {_esc(meta.get('report_nm',''))}</h1>"
            f"<p>접수번호 <a href=\"{DART_VIEWER.format(rcept_no=meta['rcept_no'])}\" target=\"_blank\">{meta['rcept_no']}</a>"
            f" · 접수일 {meta.get('rcept_dt','')} · 표 {len(tables)}개</p>")
    parts = []
    for i, t in enumerate(tables, 1):
        parts.append(
            f"<section data-table=\"{i}\" data-keywords=\"{_esc(','.join(t['keywords']))}\" data-file=\"{_esc(t['file'])}\">"
            f"<h2>표 {i} <small>[{_esc(' › '.join(t['section']))}]</small></h2>"
            f"<div class=\"ctx\">{'<br>'.join(_esc(h) for h in t['headings'])}"
            f"{('<br><b>단위:</b> ' + _esc(t['unit'])) if t['unit'] else ''}</div>"
            f"{t['html']}"
            f"{''.join('<p class=fn>' + _esc(f) + '</p>' for f in t.get('footnotes', []))}</section>")
    css = ("body{font-family:system-ui,sans-serif;margin:24px;max-width:1100px}h2{margin:32px 0 4px;font-size:16px}"
           "h2 small{color:#666;font-weight:normal}.ctx{color:#444;font-size:13px;margin:4px 0 8px;white-space:pre-wrap}"
           "table{border-collapse:collapse;font-size:12px}td,th{border:1px solid #999;padding:3px 6px;vertical-align:top}"
           ".fn{color:#555;font-size:12px;margin:4px 0}")
    return f"<!doctype html><meta charset=\"utf-8\"><title>{_esc(meta.get('company',''))} {meta['rcept_no']}</title><style>{css}</style>{head}{''.join(parts)}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", default="")
    ap.add_argument("--force", action="store_true", help="이미 추출된 보고서도 다시")
    ap.add_argument("--preview", action="store_true", help="표 미리보기를 stdout 에 출력")
    args = ap.parse_args()

    index = load_index()
    want = {c.strip() for c in args.codes.split(",") if c.strip()}
    EXTRACTED.mkdir(parents=True, exist_ok=True)
    done = skipped = 0
    for rcept_no, meta in sorted(index.items(), key=lambda kv: (kv[1].get("stock_code", ""), kv[1].get("rcept_dt", ""))):
        if want and meta.get("stock_code") not in want:
            continue
        zip_path = DOC_DIR / f"{rcept_no}.zip"
        if not zip_path.exists():
            continue
        stem = f"{meta['stock_code']}_{rcept_no}"
        out_json = EXTRACTED / f"{stem}.json"
        if out_json.exists() and not args.force:
            skipped += 1
            continue
        tables, rejected = extract_zip(zip_path)
        meta_out = {k: meta.get(k, "") for k in ("company", "sector", "stock_code", "corp_code", "rcept_no", "rcept_dt",
                                                  "report_nm", "report_type", "period", "period_label", "corrected")}
        meta_out["rcept_no"] = rcept_no
        meta_out["dart_url"] = DART_VIEWER.format(rcept_no=rcept_no)
        (EXTRACTED / f"{stem}.html").write_text(render_html(meta_out, tables), encoding="utf-8")
        out_json.write_text(json.dumps({"meta": meta_out, "tables": tables, "rejected": rejected}, ensure_ascii=False, indent=1), encoding="utf-8")
        index[rcept_no]["extracted"] = len(tables)
        done += 1
        print(f"{meta.get('company','?')} {meta.get('report_nm','')} {rcept_no}: 표 {len(tables)}개 (탈락 후보 {len(rejected)})")
        if args.preview:
            for i, t in enumerate(tables, 1):
                print(f"  ── 표 {i} [{' › '.join(t['section'][-2:])}] kw={','.join(t['keywords'])}({t['keyword_in']}) unit='{t['unit']}'")
                for h in t["headings"][-3:]:
                    print(f"     ▸ {h[:HEADING_MAX]}")
                for f in t["footnotes"]:
                    print(f"     ※ {f[:100]}")
                for row in t["rows"][:8]:
                    print("     | " + " | ".join(c[:18] for c in row))
                if len(t["rows"]) > 8:
                    print(f"     | … ({len(t['rows'])}행)")
    from common import save_index
    save_index(index)
    print(f"\n추출 {done}건, 건너뜀 {skipped}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
