# -*- coding: utf-8 -*-
"""시장관심.내러티브를 텔레그램으로 발송.

latest.json(trend_daily.py 산출)을 읽어 테마 요약 메시지를 만든다.
전송 결과는 telegram_status.json 에 남긴다(시크릿 누락 등 실패 원인을 1회 실행으로 특정).
--dry-run 으로 미리보기. 필수 환경변수: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.

메시지가 4096자를 넘으면 테마 경계에서 나눠 여러 통으로 보낸다.
"""
import argparse
import datetime
import html
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 콘솔에서 이모지 출력 보호

HERE = Path(__file__).resolve().parent
LATEST = HERE.parent / "telegram_research_dashboard" / "static" / "market_trend" / "latest.json"
DASH_URL = "https://gs-research-desk.pages.dev/market_trend_report.html"
SIGNATURE = "🎴 GS Research Desk · 시장관심.내러티브"
STATUS_PATH = HERE / "telegram_status.json"
WD = "월화수목금토일"
CHUNK_LIMIT = 3800  # 텔레그램 하드 리밋 4096 − 조각 접미사 여유


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=False)


def build_message(payload: dict) -> str | None:
    date = datetime.date.fromisoformat(payload["date"])
    head = f"🧠 <b>시장관심.내러티브</b> · {date.month}/{date.day}({WD[date.weekday()]})"

    lines = [head]
    if payload.get("one_liner"):
        lines += ["", f"<i>{esc(payload['one_liner'])}</i>"]

    themes = payload.get("themes") or []
    for i, theme in enumerate(themes, start=1):
        strength = max(0, min(int(theme.get("strength") or 0), 5))
        badge = "🆕" if theme.get("status") == "new" else "〰️"
        lines += ["", f"{i}. <b>{esc(theme.get('name', '(이름 없음)'))}</b> {badge} {'●' * strength}{'○' * (5 - strength)}"]
        if theme.get("narrative"):
            lines.append(esc(theme["narrative"]))
        if theme.get("keywords"):
            lines.append("· " + " · ".join(esc(k) for k in theme["keywords"][:6]))

    if not themes:
        # --no-llm 산출일 때는 급증 키워드 상위로 대신한다 — 아무것도 안 오는 것보다 낫다.
        spikes = (payload.get("signals") or {}).get("spikes") or []
        if not spikes:
            return None
        lines += ["", "<b>급증 키워드</b> (테마 합성 없음)"]
        for row in spikes[:10]:
            burst = f" · {row['burst']:.1f}×" if row.get("burst") is not None else ""
            flag = " 🆕" if row.get("new") else ""
            lines.append(f"· {esc(row['term'])} {row['count']}건{burst}{flag}")

    stats = payload.get("stats") or {}
    lines += ["", f"<i>채널 {stats.get('channels', '?')}개 · 글 {stats.get('messages', '?')}건 분석</i>",
              f'상세 › <a href="{DASH_URL}">대시보드</a>', SIGNATURE]
    return "\n".join(lines)


def split_chunks(text: str, limit: int = CHUNK_LIMIT) -> list[str]:
    """긴 메시지를 빈 줄(테마 경계) 우선으로 나눈다."""
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > limit and current:
            chunks.append(current)
            current = block
        else:
            current = candidate
    if current:
        chunks.append(current)
    return [f"{chunk}\n({i + 1}/{len(chunks)})" if len(chunks) > 1 else chunk
            for i, chunk in enumerate(chunks)]


def send(text: str) -> dict:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return {"ok": False, "description": "TELEGRAM_BOT_TOKEN/CHAT_ID 미설정"}
    data = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                       "disable_web_page_preview": True}).encode("utf-8")
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                 data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "description": f"HTTP {e.code}", "error_code": e.code}
    except Exception as e:
        return {"ok": False, "description": f"{type(e).__name__}: {e}"}


def _write_status(ok: bool, note: str, res=None) -> None:
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    status = {
        "when_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
        "ok": ok, "note": note, "chat_id_tail": chat[-4:] if chat else "",
        "token_set": bool(os.environ.get("TELEGRAM_BOT_TOKEN")), "response": res,
    }
    STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print("상태 기록:", json.dumps(status, ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not LATEST.exists():
        print(f"latest.json 없음({LATEST}) → 발송 생략")
        _write_status(True, "no_latest")
        return
    payload = json.loads(LATEST.read_text(encoding="utf-8"))

    # 어제 산출물을 오늘 다시 쏘지 않는다 — 창 날짜가 오늘(KST)일 때만 발송.
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d")
    if payload.get("date") != today:
        print(f"산출 날짜 {payload.get('date')} ≠ 오늘 {today} → 발송 생략")
        _write_status(True, "stale_payload")
        return

    msg = build_message(payload)
    if msg is None:
        print("보낼 내용 없음(테마·신호 모두 비어 있음) → 발송 생략")
        _write_status(True, "empty_payload")
        return
    if args.dry_run:
        print("─── 미리보기 ───\n" + msg)
        return

    results = [send(chunk) for chunk in split_chunks(msg)]
    ok = all(bool(r.get("ok")) for r in results)
    _write_status(ok, "sent" if ok else "send_failed",
                  results if len(results) > 1 else results[0])
    print("텔레그램 전송 완료" if ok else f"⚠️ 전송 실패: {results}")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
