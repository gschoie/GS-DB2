# -*- coding: utf-8 -*-
"""changes.json의 구성 변화를 텔레그램으로 발송 (기존 봇과 동일: sendMessage/HTML).
변화가 없으면 발송하지 않음(스팸 방지). --dry-run 미리보기. --force 는 변화 없어도 확인 메시지.
전송 결과는 telegram_status.json 에 기록. 필수 환경변수: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
import os, sys, json, html, argparse, datetime, urllib.request, urllib.error

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
DASH_URL = "https://gs-research-desk.pages.dev/etf_holdings_report.html"
SIGNATURE = "🎴 GS Research Desk · 액티브 ETF 트래커"
STATUS_PATH = os.path.join(HERE, "telegram_status.json")
MAX_ETFS = 12          # 메시지에 상세 표기할 최대 ETF 수(나머지는 '외 N개')


def _load_env():
    p = os.path.join(HERE, ".env")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def esc(s):
    return html.escape(str(s))


def etf_block(e):
    lines = [f"🟢 <b>{esc(e['label'])}</b> · {esc(e['group'])}"]
    if e["new"]:
        lines.append("   ⊕ 진입: " + ", ".join(esc(n["name"]) for n in e["new"]))
    if e["gone"]:
        lines.append("   ⊖ 이탈: " + ", ".join(esc(g["name"]) for g in e["gone"]))
    for m in e["moves"][:4]:
        up = m["active_share_pct"] >= 0
        arrow = "▲" if up else "▽"
        sign = "+" if up else "−"
        wp = m["active_weight_pp"]
        wtxt = "" if wp is None else f" · 비중 {'+' if wp >= 0 else '−'}{abs(wp):.1f}%p"
        star = " ★" if m["headline"] else ""
        lines.append(f"   {arrow} {esc(m['name'])} 계약수 {sign}{abs(m['active_share_pct']):.0f}%{wtxt}{star}")
    if len(e["moves"]) > 4:
        lines.append(f"   … 실매매 외 {len(e['moves'])-4}건")
    return "\n".join(lines)


def build_message(ch):
    if ch.get("first_run") or not ch["etfs"]:
        return None
    etfs = ch["etfs"]
    s = ch["summary"]
    base = ch.get("base_date") or "—"
    head = [f"<b>🧩 액티브 ETF 구성 변화</b> · 구성 기준일 {esc(base)} (KRX 장마감)", "",
            f"변화 ETF <b>{s['etfs_changed']}</b>개 · 진입 {s['new_total']}·이탈 {s['gone_total']}·실매매 {s['moves_total']}", ""]
    blocks = [etf_block(e) for e in etfs[:MAX_ETFS]]
    if len(etfs) > MAX_ETFS:
        blocks.append(f"… 외 {len(etfs)-MAX_ETFS}개 ETF 변화")
    tail = ["", f'전체 상세 › <a href="{DASH_URL}">대시보드</a>', SIGNATURE]
    return "\n".join(head + ["\n".join(blocks)] + tail)


def heartbeat_message(ch):
    base = ch.get("base_date") or "—"
    prevbase = ch.get("prev_base_date") or "—"
    return "\n".join([
        f"<b>🧩 액티브 ETF 구성 변화</b> · 구성 기준일 {esc(base)}", "",
        f"오늘({esc(prevbase)} → {esc(base)}) 유의미한 구성 변화 없음 ✅ (수동 갱신 확인)", "",
        f'전체 › <a href="{DASH_URL}">대시보드</a>', SIGNATURE])


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
    with open(STATUS_PATH, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    print("상태 기록:", json.dumps(status, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="발송 없이 메시지만 출력")
    ap.add_argument("--force", action="store_true", help="변화 없어도 확인 메시지 발송")
    args = ap.parse_args()
    _load_env()
    with open(os.path.join(HERE, "changes.json"), encoding="utf-8") as f:
        ch = json.load(f)
    msg = build_message(ch)
    forced = False
    if msg is None:
        if args.force:
            msg, forced = heartbeat_message(ch), True
        else:
            print("변화 없음 → 발송 생략")
            _write_status(True, "no_change_skip")
            return
    if args.dry_run:
        print("─── 미리보기 (HTML 태그 포함) ───\n")
        print(msg)
        return
    res = send(msg)
    ok = bool(res.get("ok"))
    note = ("forced_heartbeat" if forced else "change_sent") if ok else "send_failed"
    _write_status(ok, note, res)
    print("텔레그램 전송 완료" if ok else f"⚠️ 텔레그램 전송 실패: {res}")


if __name__ == "__main__":
    main()
