# -*- coding: utf-8 -*-
"""매크로 데스크 텔레그램 발송 — 오늘 숫자 + 앞으로 1주 발표 + 지금 구간 + 한 줄.

왜 이렇게 생겼나
  · **숫자는 "직전 미국 장 종가"다.** 발송 시각 21:00 KST는 미 장 시작(서머타임
    22:30) 전이라 그날 미국 움직임은 아직 없다. 헤더에 그대로 적는다 — 34번 교훈
    (모르는 걸 다른 값으로 바꿔 읽으면 조용히 반대로 동작한다)의 같은 부류다.
  · **평일(월~금)만 보낸다.** 토·일 21:00의 숫자는 금요일 종가 그대로라 같은
    메시지가 두 번 더 간다. 월 21:00 = 금 종가, 화 = 월 종가 … 로 월~금이 미국
    5개 세션을 정확히 한 번씩 덮는다.
  · **'지금 구간'은 guide.yml 의 quote_reads 밴드**로 뽑는다(규칙·결정적).
    그 아래 '한 줄'만 Gemini 가 그 밴드들을 종합한다 — 밴드가 근거고 한 줄은 요약이다.
    **Gemini 가 실패하면 한 줄만 빠지고 나머지는 그대로 간다**(쿼터 사고 교훈).
  · 값을 못 구한 항목은 **줄에서 아예 빠진다** — '–' 원칙과 같은 줄기로, 지어내지 않는다.
  · 본문은 **평문**이다. HTML parse_mode 는 400 → 평문 재시도 분기를 달아야 하는데,
    여기 본문엔 서식이 필요한 데가 없고 텔레그램은 맨 URL 을 알아서 링크로 만든다.

시크릿 (없으면 발송만 조용히 생략 — 수집·빌드는 영향 없음)
  MACRO_TELEGRAM_BOT_TOKEN / _CHAT_ID  → 없으면 CONGPT_TELEGRAM_*  (매크로_공부 방)
  MACRO_GEMINI_API_KEY → CONSTRUCTION_GEMINI_API_KEY → GEMINI_API_KEY
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import yaml

import calendar_rules as cr
import releases as rl

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE.parent / "telegram_research_dashboard" / "static" / "macro_desk"
KST = dt.timezone(dt.timedelta(hours=9))
WD = "월화수목금토일"
PAGE = "https://gschoie.github.io/GS-DB2/macro_desk_report.html"

# 한 줄 생성용 모델. 문장 하나짜리 일이라 가장 싼 별칭을 먼저 쓴다(쿼터 보호).
GEMINI_MODELS = ["gemini-flash-lite-latest", "gemini-flash-latest"]

ONE_LINER_RULES = """당신은 매크로 데스크의 편집자입니다. 아래 '지금 구간' 판정만 근거로
**한 문장(최대 두 문장)**의 종합을 씁니다.

규칙
1. 구간 판정에 없는 사실·전망·목표가·투자 권유를 보태지 마세요.
2. 숫자를 다시 나열하지 마세요 — 바로 위에 이미 있습니다.
3. 신호가 서로 엇갈리면 그 점을 집어 말하세요(예: 금리는 높은데 변동성은 평온하다).
4. 존댓말, 전체 80자 안팎. 머리말·따옴표·목록 없이 문장만 출력하세요."""


def now_kst() -> dt.datetime:
    return dt.datetime.now(KST)


def latest_payload() -> dict:
    files = sorted(DATA_DIR.glob("*.json")) if DATA_DIR.exists() else []
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else {}


def load_yaml(name: str) -> dict:
    return yaml.safe_load((HERE / name).read_text(encoding="utf-8")) or {}


# ── 숫자 표기 ──────────────────────────────────────────────────────────────
def fmt_value(v, unit: str) -> str:
    if v is None:
        return "–"
    if unit == "pp":
        # 스프레드는 두 금리의 **차이**다. '0.44%' 로 적으면 수익률처럼 읽히므로
        # 부호까지 붙여 %p 로 적는다(금리 %p · 나머지 % 규칙의 연장).
        return f"{v:+,.2f}%p"
    if unit == "pct":
        return f"{v:,.2f}%"
    if unit == "krw":
        return f"{v:,.1f}원"
    if unit == "usd":
        return f"${v:,.2f}"
    return f"{v:,.2f}"


def fmt_change(ch: dict, unit: str) -> str:
    """금리는 %p(절대차), 나머지는 %(비율) — 섞으면 '10년물이 6% 올랐다'로 읽힌다."""
    if not ch:
        return ""
    if unit == "pct":
        return f'{ch["diff"]:+.2f}%p'
    return f'{ch["pct"]:+.2f}%'


def quote_of(data: dict, qid: str) -> dict:
    """yahoo 쪽과 FRED 쪽 어디에 있든 찾아준다."""
    return (data.get("quotes", {}).get(qid)
            or data.get("fred", {}).get(qid) or {})


# ── 1. 오늘 숫자 ───────────────────────────────────────────────────────────
def quote_blocks(cfg: dict, data: dict, per_line: int = 2) -> str:
    """그룹별로 '이름 값 (1D)' 를 줄당 몇 개씩 묶는다.

    FRED 키가 있으면 야후 us2y 는 **뺀다** — 그건 2년물이 없어 5년물로 대신한
    칸이고, 같은 메시지에 진짜 2년물(dgs2)과 나란히 서면 숫자 둘이 어긋나 보인다.
    화면은 각주로 설명하지만 텔레그램엔 각주를 달 데가 없다.
    """
    groups = list(cfg.get("quotes", []))
    if data.get("has_fred") and quote_of(data, "dgs2"):
        groups = [{**g, "items": [i for i in g["items"] if i["id"] != "us2y"]}
                  for g in groups]
    if data.get("has_fred"):
        groups.append({"group": "금리 파생(FRED)", "items": cfg.get("fred", [])})

    out = []
    for grp in groups:
        cells = []
        for it in grp["items"]:
            q = quote_of(data, it["id"])
            if not q.get("last"):
                continue                       # 못 받은 칸은 지어내지 않고 빠진다
            ch = fmt_change(q.get("1D"), it["unit"])
            cells.append(f'{it["name"]} {fmt_value(q["last"], it["unit"])}'
                         + (f" ({ch})" if ch else ""))
        if not cells:
            continue
        lines = [" · ".join(cells[i:i + per_line])
                 for i in range(0, len(cells), per_line)]
        out.append(f'〈{grp["group"]}〉\n' + "\n".join(lines))
    return "\n\n".join(out)


# ── 2. 앞으로 1주 ──────────────────────────────────────────────────────────
def upcoming_block(cfg: dict, today: dt.date, data: dict, days: int = 7) -> str:
    """컨센·직전치가 있는 건만 두 줄로 펼치고, 나머지는 한 줄에 몰아 적는다."""
    rel = data.get("releases") or {}
    cons = rl.load_consensus()
    end = today + dt.timedelta(days=days)
    nxt = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    ev = cr.month_events(cfg.get("calendar", []), today.year, today.month) \
        + cr.month_events(cfg.get("calendar", []), *nxt)
    ev = [e for e in ev if today <= e["date"] <= end]
    if not ev:
        return "🗓 앞으로 1주 — 예정된 발표가 없습니다."

    big, small = [], []
    for e in ev:
        d = e["date"]
        when = f'{d.month}/{d.day}({WD[d.weekday()]})' + ("~" if e.get("estimated") else "")
        c = (cons.get(e["id"]) or {}).get("text")
        r = rel.get(e["id"]) or {}
        if c or r.get("text"):
            head = f'{when} {e["name"]}' + ("" if e.get("estimated") else " ★확정일")
            det = []
            if c:
                det.append(f"    컨센 {c}")
            if r.get("text"):
                det.append(f'    직전({r.get("period", "")}) {r["text"]}')
            big.append(head + "\n" + "\n".join(det))
        else:
            small.append(f'{when} {e["name"]}')

    out = ["🗓 앞으로 1주"] + big
    if small:
        out.append(" · ".join(small))
    out.append("( ~ 는 규칙으로 뽑은 추정일 )")
    return "\n".join(out)


# ── 3. 지금 구간 (규칙) ────────────────────────────────────────────────────
def pick_band(value: float, bands: list[dict]) -> dict | None:
    """**위에서부터 처음 맞는 밴드 하나.** ge=이상, lt=미만, 조건 없으면 폴백.

    순서가 곧 규칙이다 — 좁은 조건이 위에 있어야 한다. 값이 None 이면 아무것도
    고르지 않는다(모르는 것을 '아니다'로 읽지 않는다 — 30번 교훈).
    """
    if value is None:
        return None
    for b in bands or []:
        if "ge" in b and value < b["ge"]:
            continue
        if "lt" in b and value >= b["lt"]:
            continue
        return b
    return None


def band_block(guide: dict, data: dict) -> tuple[str, list[str]]:
    """('🧭 지금 구간' 본문, 한 줄 생성에 넘길 판정 목록)"""
    lines, facts = [], []
    for qid, spec in (guide.get("quote_reads") or {}).items():
        q = quote_of(data, qid)
        b = pick_band(q.get("last"), spec.get("bands"))
        if not b:
            continue
        val = fmt_value(q["last"], spec.get("unit", "idx"))
        # say 가 '5% 이상 — 뜻' 꼴이라 여기서 또 대시를 쓰면 한 줄에 대시가 두 번 나온다.
        lines.append(f'· {spec["name"]} {val} → {b["say"]}')
        facts.append(f'{spec["name"]} {val} → {b["say"]}')
    if not lines:
        return "", []
    return "🧭 지금 구간\n" + "\n".join(lines), facts


# ── 4. 한 줄 (Gemini — 실패하면 그냥 빠진다) ───────────────────────────────
def one_liner(facts: list[str]) -> str:
    key = (os.environ.get("MACRO_GEMINI_API_KEY")
           or os.environ.get("CONSTRUCTION_GEMINI_API_KEY")
           or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key or not facts:
        if not key:
            print("[한 줄] Gemini 키 없음 — 한 줄 생략(구간 판정은 그대로 갑니다)")
        return ""
    try:
        from google import genai
        from google.genai import types as gt
    except Exception as e:                      # 패키지 없으면 한 줄만 포기
        print(f"[한 줄] google-genai 없음 — 생략 ({e})", file=sys.stderr)
        return ""

    client = genai.Client(api_key=key)
    cfgen = gt.GenerateContentConfig(system_instruction=ONE_LINER_RULES,
                                     temperature=0.4, max_output_tokens=300)
    body = "[지금 구간 판정]\n" + "\n".join(facts)
    for model in GEMINI_MODELS:
        for attempt in range(2):
            try:
                r = client.models.generate_content(model=model, contents=body,
                                                   config=cfgen)
                txt = (r.text or "").strip().strip('"').strip()
                if txt:
                    print(f"[한 줄] {model}: {txt}")
                    return txt.replace("\n", " ")
            except Exception as e:
                print(f"[한 줄] {model} 시도 {attempt + 1} 실패: {e}", file=sys.stderr)
            time.sleep(20)
    print("[한 줄] 전 모델 실패 — 한 줄 없이 보냅니다", file=sys.stderr)
    return ""


# ── 조립 ───────────────────────────────────────────────────────────────────
def build_message(cfg: dict, guide: dict, data: dict, now: dt.datetime) -> str:
    today = now.date()
    head = (f"📊 GS의 매크로 데스크 · {today.month}/{today.day}({WD[today.weekday()]}) "
            f'{now.strftime("%H:%M")}\n'
            "숫자는 직전 미국 장 종가 기준입니다 (한국 저녁엔 미 장이 아직 안 열렸습니다)")
    if data.get("date") and data["date"] != today.isoformat():
        head += f'\n⚠ 최신 수집은 {data["date"]} 입니다 (오늘 수집 전)'

    bands, facts = band_block(guide, data)
    parts = [head, quote_blocks(cfg, data), upcoming_block(cfg, today, data)]
    if bands:
        parts.append(bands)
        line = one_liner(facts)
        if line:
            parts.append(f"💬 한 줄\n{line}")
    parts.append(f"🔗 {PAGE}")
    return "\n\n".join(p for p in parts if p)


def send(text: str) -> None:
    import requests
    token = (os.environ.get("MACRO_TELEGRAM_BOT_TOKEN")
             or os.environ.get("CONGPT_TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (os.environ.get("MACRO_TELEGRAM_CHAT_ID")
            or os.environ.get("CONGPT_TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat:
        print("[텔레그램] 시크릿 미설정 — 발송 생략")
        return
    for attempt in range(3):
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text,
                                "disable_web_page_preview": True}, timeout=30)
        if r.ok:
            print("[텔레그램] 1개 메시지 전송 완료")
            return
        print(f"[텔레그램] 실패 {r.status_code} {r.text[:200]}", file=sys.stderr)
        time.sleep(5)
    raise RuntimeError("텔레그램 전송 실패")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="발송 없이 본문만 출력")
    ap.add_argument("--force", action="store_true", help="주말에도 보낸다")
    a = ap.parse_args()

    now = now_kst()
    if now.weekday() >= 5 and not a.force:
        # 토·일 숫자는 금요일 종가 그대로다 — 같은 메시지를 두 번 더 보내지 않는다.
        print(f"[스킵] {WD[now.weekday()]}요일 — 주말은 숫자가 금요일 종가 그대로입니다")
        return 0

    data = latest_payload()
    if not data:
        print("[스킵] 수집 데이터가 없습니다 — collect.py 를 먼저 실행하세요")
        return 0

    text = build_message(load_yaml("config.yml"), load_yaml("guide.yml"), data, now)
    if a.dry_run:
        print(text)
        return 0
    send(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
