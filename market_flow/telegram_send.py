# -*- coding: utf-8 -*-
"""오늘의 최신 수급 스냅샷을 텔레그램(gs_macro_get)으로 발송.

data/run_meta.json 의 ran=false(휴장 등)면 발송하지 않는다.
전송 결과는 telegram_status.json 에 남긴다. --dry-run 으로 미리보기.
필수 환경변수: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
import os, sys, json, argparse, datetime, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 콘솔에서 이모지 출력 보호

HERE = Path(__file__).resolve().parent
DASH_URL = "https://gschoie.github.io/GS-output-dashboard/market_flow_report.html"
SIGNATURE = "🎴 GS Research Desk · 시장 수급"
STATUS_PATH = HERE / "telegram_status.json"
SLOT_LABEL = {"1000": "10:00", "1300": "13:00",
              "1540": "15:40 · 마감 잠정", "1640": "16:40 · 확정"}
SLOT_ORDER = ["1000", "1300", "1540", "1640"]
WD = "월화수목금토일"


def _load_env():
    p = HERE / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def fmt(v):
    if v is None:
        return "–"
    return ("+" if v > 0 else "-" if v < 0 else "") + f"{abs(v):,}"


def build_message():
    hist = json.loads((HERE / "data" / "history.json").read_text(encoding="utf-8"))
    today_key = sorted(hist["days"])[-1]
    day = hist["days"][today_key]
    slots = day.get("slots", {})
    keys = [k for k in SLOT_ORDER if k in slots]
    if not keys:
        return None
    cur_key = keys[-1]
    s = slots[cur_key]
    prev = slots[keys[-2]] if len(keys) >= 2 else None
    d = datetime.date.fromisoformat(today_key)
    chg = s.get("chg_pct", 0)
    arrow = "🔺" if chg > 0 else "🔻" if chg < 0 else "▪️"

    def line(label, key):
        base = f"{label} <b>{fmt(s[key])}억</b>"
        if prev and s.get(key) is not None and prev.get(key) is not None:
            base += f" ({fmt(s[key] - prev[key])})"
        return base

    lines = [f"💹 <b>시장 수급</b> · {d.month}/{d.day}({WD[d.weekday()]}) {SLOT_LABEL[cur_key]}",
             f"KOSPI <b>{s.get('kospi', '–'):,}</b> {arrow}{abs(chg)}%", ""]
    lines += [line("개인", "individual"), line("외국인", "foreign"), line("기관", "institution"), ""]
    lines.append(f"프로그램 <b>{fmt(s['program'])}억</b> = "
                 f"차익 {fmt(s['arb'])} · 비차익 {fmt(s['nonarb'])}")
    if prev:
        lines.append(f"<i>( ) 안은 {SLOT_LABEL[keys[-2]].split(' ')[0]} 대비 증감</i>")
    lines += ["", f'상세 차트 › <a href="{DASH_URL}">대시보드</a>', SIGNATURE]
    return "\n".join(lines)


def send(text):
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


def _write_status(ok, note, res=None):
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    status = {
        "when_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
        "ok": ok, "note": note, "chat_id_tail": chat[-4:] if chat else "",
        "token_set": bool(os.environ.get("TELEGRAM_BOT_TOKEN")), "response": res,
    }
    STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print("상태 기록:", json.dumps(status, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    _load_env()
    meta_path = HERE / "data" / "run_meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if not meta.get("ran"):
            print(f"수집 생략됨(note={meta.get('note')}) → 발송 안 함")
            _write_status(True, f"skip_{meta.get('note', 'no_run')}")
            return
    msg = build_message()
    if msg is None:
        print("오늘 스냅샷 없음 → 발송 생략")
        _write_status(True, "no_snapshot")
        return
    if args.dry_run:
        print("─── 미리보기 ───\n" + msg)
        return
    res = send(msg)
    ok = bool(res.get("ok"))
    _write_status(ok, "sent" if ok else "send_failed", res)
    print("텔레그램 전송 완료" if ok else f"⚠️ 전송 실패: {res}")


if __name__ == "__main__":
    main()
