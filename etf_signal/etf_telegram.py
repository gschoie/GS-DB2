# -*- coding: utf-8 -*-
"""signals.json의 '오늘 알림'만 텔레그램으로 발송 (기존 봇과 동일: sendMessage/HTML).
알림이 없으면 발송하지 않음(스팸 방지). --dry-run 으로 메시지만 미리보기.
필수 환경변수: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
import os, json, html, argparse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DASH_URL = "https://gschoie.github.io/GS-output-dashboard/etf_signal_report.html"
SIGNATURE = "🎴 GS Research Desk · ETF/섹터 신호"

def _load_env():
    p = os.path.join(HERE, ".env")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

def esc(s): return html.escape(str(s))

def reasons(s):
    r = []
    if s["ev_trend"]: r.append("＋DI가 −DI 상향돌파·추세전환")
    if s["stoch_oversold"]: r.append("Stochastic 과매도 반등·골든크로스")
    elif s["ev_stoch"]: r.append("Stochastic 골든크로스")
    if s["flow"] == "쌍끌이": r.append("외인·기관 동반 순매수")
    return " · ".join(r) or "신호 발생"

def build_message(payload):
    alerts = [s for s in payload["signals"] if s["alert"]]
    if not alerts:
        return None
    asof = payload["signals"][0]["asof"]
    lines = [f"<b>📡 ETF/섹터 신호</b> · {esc(asof)} (전일 확정)", "",
             f"★ 오늘 새 신호 <b>{len(alerts)}</b>개", ""]
    for s in alerts:
        flow = {"쌍끌이": "외인·기관 쌍끌이", "개인몰림": "개인몰림 주의",
                "중립": "수급 중립", "수급없음": "수급 –"}.get(s["flow"], s["flow"])
        lines += [
            f"🟢 <b>{esc(s['name'])}</b> · {esc(s['group'])}",
            f"   {esc(reasons(s))}",
            f"   ADX {s['adx']} · %K {s['k']}/{s['d']} · {esc(flow)}",
            "",
        ]
    lines += [f'전체 신호판 › <a href="{DASH_URL}">대시보드</a>', SIGNATURE]
    return "\n".join(lines)

def send(text):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    data = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                       "disable_web_page_preview": True}).encode("utf-8")
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                 data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.loads(r.read().decode("utf-8"))
    if not res.get("ok"):
        raise SystemExit(f"텔레그램 전송 실패: {res}")
    print("텔레그램 전송 완료")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="발송 없이 메시지만 출력")
    args = ap.parse_args()
    _load_env()
    with open(os.path.join(HERE, "signals.json"), encoding="utf-8") as f:
        payload = json.load(f)
    msg = build_message(payload)
    if msg is None:
        print("오늘 알림 없음 → 발송 생략")
        return
    if args.dry_run:
        print("─── 미리보기 (HTML 태그 포함) ───\n")
        print(msg)
        return
    send(msg)

if __name__ == "__main__":
    main()
