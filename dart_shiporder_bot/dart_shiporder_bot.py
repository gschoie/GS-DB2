"""DART 조선 수주공시 → 캡처(형광펜) + 텔레그램 카드.

DART 단일판매·공급계약체결 공시 URL(또는 rcpNo)을 받아서:
  1) 공시 본문 표를 캡처하고 핵심 항목에 형광펜을 칠한다
     (체결계약명 · 계약금액[억원 이상] · 계약 종료일 · 환율)
  2) 선종/척수/납기/신조선가를 계산해 텔레그램 채널에 카드로 보낸다

신조선가 = 계약금액 ÷ 척수 ÷ 환율 (백만달러, 소수1자리)
납기      = 계약기간 종료일의 연·월  (예: 2029-05-15 → 2029년 5월 납기)

필수 환경변수: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
입력:          --url <DART URL 또는 rcpNo>  (또는 env DART_URL)
"""

from __future__ import annotations

import argparse
import html as htmllib
import json
import mimetypes
import os
import re
import sys
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "captures"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
MAIN_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcp}"
VIEWER_URL = ("https://dart.fss.or.kr/report/viewer.do?rcpNo={rcp}&dcmNo={dcm}"
              "&eleId=0&offset=0&length=0&dtd=HTML")
CHANNEL = "https://t.me/HI_GS"
SIGNATURE = "🎴 조선/기계/방산 | 최광식 | DAOL투자증권\n📈 텔레그램 공개 채널 " + CHANNEL
# 계약금액이 이 값(억원) 이상일 때만 형광펜 (기본 1억 = 사실상 항상)
HIGHLIGHT_MIN_EOK = int(os.getenv("DART_HIGHLIGHT_MIN_EOK", "1"))


# ────────────────────────── DART 수집·파싱 ──────────────────────────
def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://dart.fss.or.kr/"})
    raw = urllib.request.urlopen(request, timeout=30).read()
    for enc in ("euc-kr", "cp949", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp949", errors="replace")


def rcp_no(value: str) -> str:
    match = re.search(r"rcpNo=(\d+)", value) or re.fullmatch(r"\s*(\d{10,})\s*", value)
    if not match:
        raise SystemExit(f"rcpNo를 찾지 못했습니다: {value!r}")
    return match.group(1)


def clean(doc: str) -> str:
    return htmllib.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", doc))).strip()


def eok_prefix(amount_str: str) -> str:
    """계약금액 원문 문자열에서 '억원 단위까지'에 해당하는 앞부분만 반환.
    예: '115,823,400,000'(=1,158억) → '115,8'  (형광펜을 억 자리까지만 칠하기 위함)."""
    digits = amount_str.replace(",", "")
    keep = len(digits) - 8  # 1억=10^8 이상 자릿수 개수
    if keep <= 0:
        return amount_str  # 1억 미만이면 전체
    count, out = 0, []
    for ch in amount_str:
        out.append(ch)
        if ch.isdigit():
            count += 1
            if count == keep:
                break
    return "".join(out)


def parse_disclosure(rcp: str) -> dict:
    main = fetch(MAIN_URL.format(rcp=rcp))
    candidates = [n for n in dict.fromkeys(re.findall(r"'(\d{6,10})'", main)) if n != rcp]
    doc = ""
    dcm = ""
    for candidate in candidates:
        page = fetch(VIEWER_URL.format(rcp=rcp, dcm=candidate))
        if "계약금액" in page:
            doc, dcm = page, candidate
            break
    if not doc:
        raise SystemExit("공시 본문(계약금액)을 찾지 못했습니다. 수주(단일판매·공급계약) 공시가 맞는지 확인하세요.")
    text = clean(doc)

    def grab(pattern, group=1, cast=str):
        m = re.search(pattern, text)
        return cast(m.group(group)) if m else None

    company = grab(r"([가-힣A-Za-z0-9]+)\s*/\s*단일판매")
    contract_name = grab(r"체결계약명\s*(.+?)\s*2\.\s*계약내역")  # 예: "선박용 엔진"
    sales_ratio = grab(r"매출액대비\s*\(%\)\s*([\d.]+)")  # 최근매출액 대비 %
    amount = grab(r"계약금액\s*\(원\)\s*([\d,]+)", cast=lambda s: int(s.replace(",", "")))
    # 환율 표기는 공시마다 다르다: "매매기준환율(@1,531.8/$)" / "USD 1 = 1,526.60원" 등
    fx_str = None
    for _p in (r"USD\s*1\s*=\s*([\d,.]+)\s*원",
               r"1\s*USD\s*=?\s*([\d,.]+)\s*원",
               r"매매기준환율\s*\(?@?\s*([\d,.]+)\s*/\s*\$",
               r"환율[^0-9]{0,25}?([\d,]{2,}\.\d+)\s*원",
               r"환율[^0-9]{0,25}?@?\s*([\d,.]+)\s*/\s*\$"):
        _m = re.search(_p, text)
        if _m:
            fx_str = _m.group(1)
            break
    fx = float(fx_str.replace(",", "")) if fx_str else None
    end = re.search(r"종료일\s*(\d{4})-(\d{2})-(\d{2})", text)
    # 선종/척수: 체결계약명(예 'VLAC 3척'·'LNG운반선 2척')의 'N척'을 우선 파싱한다.
    # '선'으로 끝나지 않는 영문 약어 선종(VLAC·VLCC·VLGC 등)도 잡도록 '척' 기준으로 인식.
    ship = (re.search(r"([A-Za-z가-힣0-9/·\-]+)\s*(\d+)\s*척", contract_name or "")
            or re.search(r"([A-Za-z가-힣0-9/·\-]+)\s*(\d+)\s*척", text))
    counterparty = grab(r"계약상대\s*(.+?)\s*회사와의")
    end_str = grab(r"종료일\s*(\d{4}-\d{2}-\d{2})")
    amount_str = grab(r"계약금액\s*\(원\)\s*([\d,]+)")
    amount_eok = eok_prefix(amount_str) if amount_str else None  # 억 자리까지만 형광펜
    region = grab(r"공급지역\s*(.+?)\s*5\s*\.\s*계약기간")  # 예: '아시아 지역'
    region = region.strip() if region else None

    # 조선 수주(○○선 N척)면 신조선가 카드, 아니면(엔진·기자재 등) 일반 수주 카드
    is_ship = ship is not None
    required = {"회사명": company, "계약금액": amount, "종료일": end}
    if is_ship:
        required.update({"환율": fx, "선종/척수": ship})
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise SystemExit(f"공시에서 다음 항목을 찾지 못했습니다: {', '.join(missing)}")

    ship_type, ships = (ship.group(1), int(ship.group(2))) if is_ship else (None, None)
    # 형광펜(부분 하이라이트) 대상: 계약금액은 '억 자리까지'(amount_eok)만,
    # 환율·종료일·체결계약명·판매공급지역, 조선이면 선종/척수까지. (계약상대는 셀 단위로 별도 처리)
    hl = [amount_eok, end_str, contract_name, fx_str]
    if region and region not in ("-", ""):
        hl.append(region)
    if is_ship:
        hl += [f"{ship_type} {ships}척", ship_type]
    return {
        "rcp": rcp, "dcm": dcm,
        "company": company, "is_ship": is_ship,
        "ship_type": ship_type, "ships": ships,
        "contract_name": (contract_name or "").strip(), "sales_ratio": sales_ratio,
        "amount": amount, "fx": fx,
        "end_year": end.group(1), "end_month": int(end.group(2)),
        "counterparty": (counterparty or "").strip(" -"),
        # 형광펜용 원문 문자열
        "hl": [s for s in hl if s],
        "amount_str": amount_str,
        "amount_eok": amount_eok,
        "region": region,
        "viewer": VIEWER_URL.format(rcp=rcp, dcm=dcm),
        "main": MAIN_URL.format(rcp=rcp),
    }


def build_message(d: dict, comment: str = "", html: bool = False) -> str:
    # html=True: 봇 caption(parse_mode=HTML)용 — 동적 텍스트 이스케이프 + <b> 굵게.
    # html=False: 채널에 직접 붙여넣기용 평문 — 태그 없이 그대로 보이게.
    esc = htmllib.escape if html else (lambda s: s)
    bold = (lambda s: f"<b>{s}</b>") if html else (lambda s: s)
    delivery = f"{d['end_year']}년 {d['end_month']}월 납기"
    if d["is_ship"]:
        price = d["amount"] / d["ships"] / d["fx"] / 1_000_000  # 척당, 백만달러
        title = f"「{esc(d['company'])}, {esc(d['ship_type'])} {d['ships']}척 수주」"
        second = f"💲 {delivery}, 신조선가 {price:.1f}백만달러"
    else:
        # 엔진·기자재 등 척수 없는 수주 → 계약금액(억원) + 납기 카드
        eok = d["amount"] / 100_000_000
        name = esc(d["contract_name"]) if d["contract_name"] else "수주"
        title = f"「{esc(d['company'])}, {name} {eok:,.0f}억원 수주」"
        ratio = f" (최근 매출액 대비 {d['sales_ratio']}%)" if d.get("sales_ratio") else ""
        second = f"💲 {delivery}{ratio}"
    lines = [
        bold(title),
        second,
        f"☞ {esc(d['main'])}",
        "",
        SIGNATURE,
    ]
    comment = (comment or "").strip()
    if comment:
        comment = comment if comment.startswith("❗") else f"❗ {comment}"
        lines += ["", esc(comment)]
    return "\n".join(lines)


# ────────────────────────── 캡처(형광펜) ──────────────────────────
# 텍스트 노드에서 '대상 문자열만' 골라 <span>으로 감싸 부분 하이라이트한다.
# (셀 전체가 아니라 '115,8'·'1,504.20' 같은 값만 칠하려는 것)
HIGHLIGHT_JS = """
(targets) => {
  const STYLE = 'background-color:#fff35a;font-weight:700;';
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
  const nodes = [];
  while (walker.nextNode()) {
    const n = walker.currentNode;
    if (n.nodeValue && n.nodeValue.trim()) nodes.push(n);
  }
  for (const node of nodes) {
    const text = node.nodeValue;
    for (const t of targets) {
      if (!t) continue;
      const idx = text.indexOf(t);
      if (idx < 0) continue;
      const span = document.createElement('span');
      span.setAttribute('style', STYLE);
      span.textContent = text.slice(idx, idx + t.length);
      const frag = document.createDocumentFragment();
      const before = text.slice(0, idx), after = text.slice(idx + t.length);
      if (before) frag.appendChild(document.createTextNode(before));
      frag.appendChild(span);
      if (after) frag.appendChild(document.createTextNode(after));
      node.parentNode.replaceChild(frag, node);
      break;  // 이 노드는 처리 완료
    }
  }
}
"""

# 계약상대 값 셀을 통째로 칠한다 — 이름이 있으면 이름, 없으면 '-'라도 칠하기 위함.
COUNTERPARTY_JS = """
() => {
  const norm = s => (s || '').replace(/\\s+/g, '');
  const cells = [...document.querySelectorAll('td,th')];
  const label = cells.find(c => {
    const t = norm(c.textContent);
    return t.includes('계약상대') && !t.includes('회사와의') && t.length <= 10;
  });
  if (!label) return false;
  const row = label.closest('tr');
  if (!row) return false;
  const kids = [...row.children];
  const i = kids.indexOf(label);
  let painted = false;
  for (let j = i + 1; j < kids.length; j++) {
    const el = kids[j];
    el.setAttribute('style', (el.getAttribute('style') || '') + ';background-color:#fff35a;font-weight:700;');
    painted = true;
  }
  return painted;
}
"""

# 공시 표를 흰 여백 div로 감싸 캡처 시 약간의 여백이 생기게 한다.
WRAP_JS = """
() => {
  const table = [...document.querySelectorAll('table')].find(t => (t.textContent || '').includes('계약금액'));
  if (!table) return false;
  const wrap = document.createElement('div');
  wrap.id = '__cap_wrap';
  wrap.style.cssText = 'display:inline-block;padding:14px;background:#ffffff';
  table.parentNode.insertBefore(wrap, table);
  wrap.appendChild(table);
  return true;
}
"""


def capture(d: dict) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"dart_{d['rcp']}.png"
    targets = list(d["hl"])
    if d["amount"] < HIGHLIGHT_MIN_EOK * 100_000_000 and d["amount_eok"] in targets:
        targets.remove(d["amount_eok"])  # 억원 미만이면 계약금액 형광펜 제외
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_context(
            user_agent=UA, viewport={"width": 900, "height": 1400},
            extra_http_headers={"Referer": d["main"]},
        ).new_page()
        page.goto(d["viewer"], wait_until="networkidle", timeout=60_000)
        page.evaluate(HIGHLIGHT_JS, targets)
        page.evaluate(COUNTERPARTY_JS)  # 계약상대 값 셀 형광펜(있으면 이름, 없으면 '-')
        target = ("#__cap_wrap" if page.evaluate(WRAP_JS)
                  else "table")  # 여백 래퍼가 붙으면 그걸, 아니면 표를
        table = page.locator(target).filter(has_text="계약금액").first if target == "table" else page.locator(target)
        try:
            table.screenshot(path=str(path))  # 표 + 약간의 흰 여백만 캡처
        except Exception:
            page.screenshot(path=str(path), full_page=True)
        browser.close()
    return path


# ────────────────────────── 텔레그램 전송 ──────────────────────────
def _multipart(fields: dict, file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    body = bytearray()
    for name, value in fields.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
    filename = file_path.name
    ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
             f"filename=\"{filename}\"\r\nContent-Type: {ctype}\r\n\r\n").encode()
    body += file_path.read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def send_photo(image: Path, caption: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    body, content_type = _multipart(
        {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}, "photo", image)
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        data=body, headers={"Content-Type": content_type},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise SystemExit(f"텔레그램 전송 실패: {result}")


def run(url_or_rcp: str, comment: str = "", dry: bool = False) -> None:
    d = parse_disclosure(rcp_no(url_or_rcp))
    message = build_message(d, comment, html=True)  # 봇 caption(HTML)으로 전송
    print(message, flush=True)
    image = capture(d)
    print(f"캡처: {image}", flush=True)
    if dry:
        print("[dry-run] 텔레그램 전송 생략")
        return
    send_photo(image, message)
    print("텔레그램 전송 완료 → 공개채널 https://t.me/HI_GS", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="DART 조선 수주공시 → 공개채널(t.me/HI_GS)에 사진+캡션 카드로 바로 전송")
    parser.add_argument("--url", default=os.getenv("DART_URL", ""), help="DART 공시 URL 또는 rcpNo")
    parser.add_argument("--comment", default=os.getenv("DART_COMMENT", ""), help="카드 하단에 붙일 내 코멘트")
    parser.add_argument("--dry-run", action="store_true",
                        help="(테스트) 전송 없이 메시지·캡처만 만들어 확인")
    args = parser.parse_args()
    if not args.url:
        sys.exit("DART URL(--url 또는 env DART_URL)이 필요합니다.")
    run(args.url, args.comment, args.dry_run)
