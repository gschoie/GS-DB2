"""텔레그램 본문에 TP가 없는 기업분석 보고서의 적정주가를 PDF 원문에서 보강한다.

DAOL 보고서 표지의 '현재/직전/변동' 박스(예: `적정주가 980,000 1,100,000 하향`)를
1순위로 읽는다. 텔레그램 글이 "선호주로 상향"처럼 TP 숫자 없이 나가는 보고서가
대상이며, PDF 텍스트는 톤 대시보드와 같은 캐시(daol_pdf_text_cache.json)를 공유해
같은 PDF를 두 번 받지 않는다.

2025년~4Q25 시절 PDF 상당수는 텍스트가 이미지로 박혀 있어(추출 불가) 표지 1페이지를
OCR한다. OCR은 tesseract(-kor)+pypdfium2+pytesseract가 있을 때만 동작하고, 없으면
해당 건은 건너뛴다(CI 우분투 러너에서 설치해 실행).

주의: 전체 재분류(rebuild_parsed_data)나 재수집이 보고서 행을 다시 만들면 보강값이
지워지므로, 수집이 도는 워크플로마다 이 스크립트를 뒤에 한 번씩 돌려 다시 채운다.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from io import BytesIO

from pathlib import Path

from db import connect, initialize

# 톤 트래커가 daol-research-tone 리포로 독립하면서, 여기서 쓰던 PDF 캐시 경로와
# UA를 직접 정의한다(과거엔 build_daol_tone_dashboard에서 임포트).
PDF_CACHE = Path(__file__).resolve().parent / 'data' / 'daol_pdf_text_cache.json'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36'}

# 표지 박스: `적정주가 980,000 1,100,000 하향` / 신규 커버리지는 직전값이 없을 수 있다.
COVER_RE = re.compile(
    r"(?:적정주가|목표주가)\s*([0-9][0-9,]{2,})\s*원?\s+(?:([0-9][0-9,]{2,})|[-–—])?\s*원?\s*(상향|하향|유지|신규)"
)
# 폴백: 본문 첫 `적정주가 61,000원` 식 표기 (변동 방향 없음)
FALLBACK_RE = re.compile(r"(?:적정주가|목표주가)\s*(?:\(원\))?\s*[:：]?\s*([0-9][0-9,]{2,})\s*원?")
# 이런 오류는 일시적이라 다음 실행에서 다시 시도한다.
RETRYABLE_ERRORS = ("Timeout", "Connect", "MaxRetry", "ConnectionError", "HTTPError")


def _num(raw: str | None) -> int | None:
    if not raw or not raw[0].isdigit():
        return None
    value = int(raw.replace(",", ""))
    return value if value >= 1_000 else None


def extract_tp(text: str) -> dict | None:
    cover = COVER_RE.search(text)
    if cover:
        target = _num(cover.group(1))
        previous = _num(cover.group(2))
        # OCR 오독 방어: 직전값이 있는데 현재값과 5배 이상 차이나면 버린다.
        if target and (not previous or 0.2 <= target / previous <= 5):
            return {
                "target_price": target,
                "previous_target_price": previous,
                "target_change": "신규/미확인" if cover.group(3) == "신규" else cover.group(3),
                "confident": True,
            }
    fallback = FALLBACK_RE.search(text)
    if fallback and _num(fallback.group(1)):
        return {
            "target_price": _num(fallback.group(1)),
            "previous_target_price": None,
            "target_change": "신규/미확인",
            "confident": False,
        }
    return None


_OCR_READY: bool | None = None


def _ocr_ready() -> bool:
    global _OCR_READY
    if _OCR_READY is None:
        try:
            import pypdfium2  # noqa: F401
            import pytesseract
            pytesseract.get_tesseract_version()
            _OCR_READY = "kor" in pytesseract.get_languages()
        except Exception:
            _OCR_READY = False
    return _OCR_READY


def _ocr_first_page(content: bytes) -> str:
    """이미지형 PDF 표지(1페이지)를 300dpi로 렌더링해 OCR한다."""
    try:
        import pypdfium2 as pdfium
        import pytesseract
        page = pdfium.PdfDocument(content)[0]
        image = page.render(scale=300 / 72).to_pil()
        return pytesseract.image_to_string(image, lang="kor+eng")
    except Exception:
        return ""


def report_pdf_text(source_url: str, cache: dict) -> dict:
    """톤 대시보드 캐시와 호환되는 형태로 PDF 텍스트를 얻는다. OCR 결과는 status='ocr'."""
    entry = cache.get(source_url)
    if entry:
        if entry["status"] in ("pdf", "ocr"):
            return entry
        error = entry.get("error", "")
        retry_network = any(word in error for word in RETRYABLE_ERRORS)
        retry_with_ocr = "empty or scanned" in error and _ocr_ready()
        if not (retry_network or retry_with_ocr):
            return entry
    import requests
    from pypdf import PdfReader
    result = {"status": "failed", "final_url": source_url, "text": "", "error": ""}
    try:
        r = requests.get(source_url, headers=UA, timeout=(6, 25), allow_redirects=True)
        r.raise_for_status()
        if len(r.content) > 25_000_000:
            raise ValueError("PDF exceeds 25MB")
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(r.content)).pages)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(text) >= 300:
            result = {"status": "pdf", "final_url": r.url, "text": text, "error": ""}
        else:
            ocr_text = _ocr_first_page(r.content).strip()
            if len(ocr_text) >= 50:
                result = {"status": "ocr", "final_url": r.url, "text": ocr_text, "error": ""}
            else:
                result["error"] = "ValueError: PDF text is empty or scanned"
    except Exception as e:  # noqa: BLE001 — 개별 PDF 실패가 전체를 막지 않게
        result["error"] = f"{type(e).__name__}: {e}"[:240]
    cache[source_url] = result
    return result


def enrich(since: str = "2025-01-01", limit: int = 150, budget_seconds: int = 600) -> None:
    initialize()
    cache = json.loads(PDF_CACHE.read_text(encoding="utf-8")) if PDF_CACHE.exists() else {}
    started = time.monotonic()
    filled = attempted = 0
    print(f"OCR 사용 가능: {_ocr_ready()}")
    with connect() as conn:
        rows = conn.execute(
            """SELECT r.id, r.original_url, r.confidence FROM reports r
               JOIN telegram_messages m ON m.id=r.message_id
               WHERE r.report_type='기업분석' AND r.target_price IS NULL
                 AND r.original_url IS NOT NULL AND m.posted_at>=?
               ORDER BY m.posted_at DESC LIMIT ?""",
            (since, limit),
        ).fetchall()
        for row in rows:
            if time.monotonic() - started > budget_seconds:
                print(f"시간 한도 {budget_seconds}초 도달 — 남은 건 다음 실행에서 이어감")
                break
            attempted += 1
            pdf = report_pdf_text(row["original_url"], cache)
            if pdf["status"] not in ("pdf", "ocr"):
                continue
            found = extract_tp(pdf["text"])
            if not found:
                continue
            confidence = min(0.95, row["confidence"] + 0.2) if found["confident"] else row["confidence"]
            conn.execute(
                """UPDATE reports SET target_price=?, previous_target_price=?, target_change=?,
                   confidence=?, needs_review=? WHERE id=?""",
                (found["target_price"], found["previous_target_price"], found["target_change"],
                 confidence, int(confidence < 0.8), row["id"]),
            )
            filled += 1
        conn.commit()
    PDF_CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"PDF TP 보강 완료: 시도 {attempted}건 중 {filled}건 채움 (대상 {len(rows)}건)")


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("--since", default="2025-01-01", help="이 날짜(posted_at) 이후 보고서만")
    cli.add_argument("--limit", type=int, default=150, help="한 번에 처리할 최대 건수")
    cli.add_argument("--budget-seconds", type=int, default=600, help="PDF 다운로드·OCR 시간 한도")
    args = cli.parse_args()
    enrich(args.since, args.limit, args.budget_seconds)
