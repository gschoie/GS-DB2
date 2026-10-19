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


def _context(table: Tag) -> list[str]:
    """이전 표 이후 ~ 이 표 사이의 제목·문단 텍스트(문서 순서)."""
    out: list[str] = []
    seen = 0
    for el in table.find_all_previous(True):
        if el.name == "table":
            # 단위·각주만 든 한두 칸짜리 표는 경계가 아니라 문맥이다 — 지나서 계속 올라간다
            if sum(len(r) for r in _rows(el)) <= _TINY_CELLS:
                txt = _text(el)
                if txt:
                    out.append(txt)
                continue
            break
        if el.name not in ("p", "title", "tu", "te", "span", "div", "h1", "h2", "h3", "h4"):
            continue
        if el.find_parent("table") is not None:
            continue
        if any(el.find_parent(t) is not None for t in ("p", "title", "tu", "te")) and el.name in ("span", "div"):
            continue                                  # 부모 문단이 이미 담는 텍스트
        txt = _text(el)
        if not txt:
            continue
        out.append(txt)
        seen += 1
        if seen >= CONTEXT_MAX:
            break
    out.reverse()
    return out


def _section_titles(table: Tag) -> list[str]:
    titles = []
    for el in table.find_all_previous("title"):
        if el.find_parent("table") is not None:
            continue
        titles.append(_text(el))
        if len(titles) >= 3:
            break
    titles.reverse()
    return titles


def _is_heading(txt: str) -> bool:
    """짧고 서술형이 아닌 문장만 제목으로 — '…입니다.' '…합니다.' '※ …' 는 각주 문장."""
    if not txt or len(txt) > HEADING_MAX:
        return False
    if txt.startswith(("※", "주)", "주1", "(주")):
        return False
    if re.search(r"(다|음|함|임)\s*\.?$", txt):
        return False
    return True


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
    """(채택 표, 탈락 후보). 탈락 후보는 느슨한 일치(아무 셀·아무 문맥)만 된 것 — 검토용."""
    soup = BeautifulSoup(doc, "lxml")
    found: list[dict] = []
    rejected: list[dict] = []
    pending_unit = ""        # 바로 앞 '단위 표'의 문구
    for table in soup.find_all("table"):
        if table.find_parent("table") is not None:
            continue                                  # 중첩 표는 바깥 표에 포함
        rows = _rows(table)
        ttext = _text(table)
        ncells = sum(len(r) for r in rows)
        # (단위 : 백만원) 만 든 한두 칸짜리 표 → 다음 표의 단위
        if ncells <= _TINY_CELLS and _UNIT_RE.search(ttext):
            pending_unit = ttext
            continue
        # '※ …' 한 칸짜리 각주 표 → 직전 채택 표의 각주
        if ncells <= _TINY_CELLS and found and (ttext.startswith("※") or ttext.startswith("주")):
            found[-1]["footnotes"].append(ttext)
            continue
        ctx = _context(table)
        headings = [t for t in ctx if _is_heading(t) and not _UNIT_RE.search(t)]
        near = [t for t in ctx[-NEAR:] if _is_heading(t) and not _UNIT_RE.search(t)]
        kw_table = _cell_hit(rows)
        kw_ctx = sorted({k for t in near for k in _KW_RE.findall(t)})
        unit_texts = [t for t in ctx if _UNIT_RE.search(t)]
        unit = unit_texts[-1] if unit_texts else pending_unit
        pending_unit = ""
        record = {
            "section": _section_titles(table),
            "headings": headings,
            "context": ctx,
            "unit": unit,
            "keywords": sorted(set(kw_table) | set(kw_ctx)),
            "keyword_in": "table" if kw_table else ("heading" if kw_ctx else ""),
            "rows": rows,
            "html": str(table),
            "footnotes": [],
            "digest": hashlib.md5(ttext.encode("utf-8")).hexdigest()[:12],
        }
        if kw_table or kw_ctx:
            found.append(record)
            continue
        loose = sorted(set(_KW_RE.findall(ttext)) | {k for t in ctx for k in _KW_RE.findall(t)})
        if loose:
            rejected.append({**record, "keywords": loose, "html": "", "rows": rows[:3],
                             "why": "셀 전체가 지표명이 아니거나 멀리 있는 문장에만 키워드"})
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
