"""OpenDART 수집 — corpCode → list.json → document.xml(원문 zip 캐시).

  python fetch.py                       # config 전체, 최근 3년 정기보고서
  python fetch.py --codes 329180,012450 # 일부 회사만
  python fetch.py --limit 3             # config 앞에서 3개만
  python fetch.py --years 3 --refresh-corp

환경변수 DART_API_KEY 필수. 호출 간격 0.4초, 네트워크/5xx 는 3회 재시도.
원문 zip 은 data/raw/doc/<rcept_no>.zip 에 캐시 — 있으면 다시 받지 않는다.
찾은 보고서 목록은 data/reports.json 에 누적(extract·대시보드가 공유).
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import sys
import time
import zipfile
import xml.etree.ElementTree as ET

import requests

from common import RAW, load_companies, load_index, parse_report_name, save_index

API = "https://opendart.fss.or.kr/api"
CORP_ZIP = RAW / "corpCode.zip"
LIST_DIR = RAW / "list"
DOC_DIR = RAW / "doc"
PAUSE = 0.4
RETRIES = 3

sys.stdout.reconfigure(line_buffering=True)   # 러너 로그에 진행 상황이 바로 보이게
_session = requests.Session()
_session.headers["User-Agent"] = "gs-research-desk dart_capacity/1.0"


def api_key() -> str:
    key = os.environ.get("DART_API_KEY", "").strip()
    if not key:
        sys.exit("DART_API_KEY 환경변수가 없습니다 (OpenDART 인증키).")
    return key


def _get(url: str, params: dict) -> requests.Response:
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            resp = _session.get(url, params=params, timeout=(15, 120))   # (연결, 읽기) 초
            if resp.status_code >= 500:
                raise requests.HTTPError(f"HTTP {resp.status_code}")
            time.sleep(PAUSE)
            return resp
        except (requests.RequestException, requests.HTTPError) as exc:
            last = exc
            wait = 2 ** attempt
            print(f"  ! {exc} — {wait}s 후 재시도({attempt}/{RETRIES})")
            time.sleep(wait)
    raise RuntimeError(f"요청 실패: {url} ({last})")


def _check_json(payload: dict, what: str) -> dict:
    status = payload.get("status", "")
    if status not in ("000", "013"):          # 013 = 조회 결과 없음(정상)
        raise RuntimeError(f"{what}: OpenDART 오류 {status} {payload.get('message')}")
    return payload


# ───────────────────── corpCode ─────────────────────
def corp_table(key: str, refresh: bool = False) -> list[dict]:
    """[{corp_code, corp_name, stock_code}] — 상장사(stock_code 있음)만 돌려준다."""
    if refresh or not CORP_ZIP.exists():
        CORP_ZIP.parent.mkdir(parents=True, exist_ok=True)
        resp = _get(f"{API}/corpCode.xml", {"crtfc_key": key})
        if not zipfile.is_zipfile(io.BytesIO(resp.content)):
            raise RuntimeError(f"corpCode.xml 응답이 zip 이 아닙니다: {resp.text[:200]}")
        CORP_ZIP.write_bytes(resp.content)
        print(f"corpCode.zip 저장 ({len(resp.content)//1024} KB)")
    with zipfile.ZipFile(CORP_ZIP) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".xml"))
        root = ET.fromstring(zf.read(name))
    rows = []
    for item in root.iter("list"):
        stock = (item.findtext("stock_code") or "").strip()
        if not stock:
            continue
        rows.append({
            "corp_code": (item.findtext("corp_code") or "").strip(),
            "corp_name": (item.findtext("corp_name") or "").strip(),
            "stock_code": stock,
        })
    return rows


def resolve(companies: list[dict], table: list[dict]) -> list[dict]:
    by_code = {r["stock_code"]: r for r in table}
    by_name = {r["corp_name"].replace(" ", ""): r for r in table}
    out = []
    for c in companies:
        hit = by_code.get(c["stock_code"]) if c["stock_code"] else None
        if not hit:
            for nm in [c["name"], *c["aliases"]]:
                hit = by_name.get(nm.replace(" ", ""))
                if hit:
                    break
        if not hit:
            print(f"  ✗ {c['name']}: corpCode 에서 찾지 못함 (stock_code={c['stock_code'] or '-'}) — 건너뜀")
            continue
        if c["stock_code"] and c["stock_code"] != hit["stock_code"]:
            print(f"  ! {c['name']}: 종목코드 불일치 config={c['stock_code']} dart={hit['stock_code']}")
        if not c["stock_code"]:
            print(f"  · {c['name']}: 종목코드 {hit['stock_code']} (DART 명 '{hit['corp_name']}') — companies.yaml 에 적어 두세요")
        out.append({**c, "stock_code": hit["stock_code"], "corp_code": hit["corp_code"], "dart_name": hit["corp_name"]})
    return out


# ───────────────────── list.json ─────────────────────
def periodic_reports(key: str, corp_code: str, years: int) -> list[dict]:
    today = dt.date.today()
    bgn = today.replace(year=today.year - years)
    rows: list[dict] = []
    page = 1
    while True:
        resp = _get(f"{API}/list.json", {
            "crtfc_key": key, "corp_code": corp_code,
            "bgn_de": bgn.strftime("%Y%m%d"), "end_de": today.strftime("%Y%m%d"),
            "pblntf_ty": "A",                     # 정기공시
            "page_no": page, "page_count": 100,
        })
        payload = _check_json(resp.json(), "list.json")
        rows.extend(payload.get("list") or [])
        if page >= int(payload.get("total_page") or 1):
            break
        page += 1
    out = []
    for r in rows:
        meta = parse_report_name(r.get("report_nm", ""))
        if not meta["report_type"]:
            continue                               # 사업/반기/분기보고서가 아닌 정기공시(예: 등록법인결산)는 제외
        out.append({**meta, "rcept_no": r["rcept_no"], "report_nm": r["report_nm"], "rcept_dt": r["rcept_dt"]})
    LIST_DIR.mkdir(parents=True, exist_ok=True)
    (LIST_DIR / f"{corp_code}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


# ───────────────────── document.xml ─────────────────────
def download_document(key: str, rcept_no: str) -> tuple[bool, str]:
    """원문 zip 캐시. (새로 받았나, 메시지)"""
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    target = DOC_DIR / f"{rcept_no}.zip"
    if target.exists() and target.stat().st_size > 0:
        return False, "캐시"
    resp = _get(f"{API}/document.xml", {"crtfc_key": key, "rcept_no": rcept_no})
    if not zipfile.is_zipfile(io.BytesIO(resp.content)):
        # 오류는 200 으로 XML 본문에 status/message 로 온다
        try:
            root = ET.fromstring(resp.content)
            msg = f"{root.findtext('status')} {root.findtext('message')}"
        except ET.ParseError:
            msg = resp.text[:120]
        return False, f"zip 아님: {msg}"
    target.write_bytes(resp.content)
    return True, f"{len(resp.content)//1024} KB"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", default="", help="종목코드 콤마 목록(없으면 config 전체)")
    ap.add_argument("--limit", type=int, default=0, help="config 앞에서 n개만")
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--refresh-corp", action="store_true")
    ap.add_argument("--list-only", action="store_true", help="원문은 받지 않고 목록만")
    args = ap.parse_args()

    key = api_key()
    companies = load_companies()
    if args.codes:
        want = {c.strip() for c in args.codes.split(",") if c.strip()}
        companies = [c for c in companies if c["stock_code"] in want]
    if args.limit:
        companies = companies[: args.limit]

    print(f"corpCode 로드…")
    table = corp_table(key, refresh=args.refresh_corp)
    print(f"  상장사 {len(table)}개")
    companies = resolve(companies, table)
    index = load_index()
    new_docs = 0
    for c in companies:
        reports = periodic_reports(key, c["corp_code"], args.years)
        print(f"\n[{c['sector']}] {c['name']}({c['stock_code']}) 정기보고서 {len(reports)}건 (최근 {args.years}년)")
        for r in sorted(reports, key=lambda x: x["rcept_dt"]):
            entry = {**r, "company": c["name"], "sector": c["sector"], "stock_code": c["stock_code"], "corp_code": c["corp_code"]}
            index.setdefault(r["rcept_no"], {}).update(entry)
            if args.list_only:
                print(f"  {r['rcept_dt']} {r['report_nm']:<28} {r['rcept_no']}")
                continue
            t0 = time.monotonic()
            fresh, msg = download_document(key, r["rcept_no"])
            index[r["rcept_no"]]["raw"] = bool(fresh or msg == "캐시")
            new_docs += int(fresh)
            print(f"  {r['rcept_dt']} {r['report_nm']:<28} {r['rcept_no']}  {msg} ({time.monotonic() - t0:.1f}s)")
    save_index(index)
    print(f"\n보고서 인덱스 {len(index)}건 저장, 원문 신규 {new_docs}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
