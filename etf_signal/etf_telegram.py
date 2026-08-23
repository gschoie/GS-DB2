# -*- coding: utf-8 -*-
"""signals.json의 '오늘 알림'(매수 골든크로스 · 매도 데드크로스 · ADX 추세 강도)만
텔레그램으로 발송 (기존 봇과 동일: sendMessage/HTML).
알림이 없으면 발송하지 않음(스팸 방지). --dry-run 으로 메시지만 미리보기.
--force 는 신호가 없어도 '오늘 새 신호 없음' 확인 메시지를 보냄(수동 🔄 갱신 확인용).
전송 결과(성공/에러 원문)는 telegram_status.json 에 남긴다(원인 진단용).
필수 환경변수: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
import os, json, html, argparse, datetime, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
DASH_URL = "https://gschoie.github.io/GS-output-dashboard/etf_signal_report.html"
SIGNATURE = "🎴 GS Research Desk · ETF/섹터 신호"
STATUS_PATH = os.path.join(HERE, "telegram_status.json")

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

def reasons_sell(s):
    r = []
    if s.get("ev_trend_dead"): r.append("＋DI가 −DI 하향이탈·추세꺾임")
    if s.get("stoch_overbought"): r.append("Stochastic 과열 이탈·데드크로스")
    elif s.get("ev_stoch_dead"): r.append("Stochastic 데드크로스")
    if s.get("dist"): r.append("외인·기관 동반 순매도")
    return " · ".join(r) or "신호 발생"

def reasons_adx(s):
    """추세 강도 사유. 20 = 확인, 25 = 강력."""
    up = s.get("adx_up")
    dirn = "상승추세" if up else "하락추세"
    r = []
    if s.get("adx_stage") == 2: r.append(f"ADX 25 상향돌파 · {dirn} 강화(강력)")
    elif s.get("adx_stage") == 1: r.append(f"ADX 20 상향돌파 · {dirn} 확립(확인)")
    if up and s.get("flow") == "쌍끌이": r.append("외인·기관 동반 순매수")
    if not up and s.get("dist"): r.append("외인·기관 동반 순매도")
    return " · ".join(r) or "신호 발생"

FLOW_LABEL = {"쌍끌이": "외인·기관 쌍끌이", "개인몰림": "개인몰림 주의",
              "중립": "수급 중립", "수급없음": "수급 –"}

def _block(rows, icon, why):
    """icon은 고정 문자열 또는 종목별로 아이콘을 정하는 함수."""
    lines = []
    for s in rows:
        flow = FLOW_LABEL.get(s["flow"], s["flow"])
        mark = icon(s) if callable(icon) else icon
        lines += [
            f"{mark} <b>{esc(s['name'])}</b> · {esc(s['group'])}",
            f"   {esc(why(s))}",
            f"   ADX {s['adx']} · %K {s['k']}/{s['d']} · {esc(flow)}",
            *( [f"   [{s['grade']}] {esc(' · '.join(s['conviction_why']))}"]
               if s.get("conviction_why") else [] ),
            "",
        ]
    return lines

def _adx_icon(s):
    """강력(25↑)은 ⚡, 확인(20↑)은 방향 화살표."""
    if s.get("adx_stage") == 2:
        return "⚡"
    return "🔺" if s.get("adx_up") else "🔻"

MIN_GRADE = ("A", "B")   # 텔레그램은 B 이상만 — 대시보드에는 C까지 전부 표시된다


def _keep(s):
    """알림 피로를 줄이려고 등급이 낮은 신호는 발송하지 않는다.
    등급이 없는 구버전 payload는 그대로 통과시킨다."""
    return s.get("grade", "A") in MIN_GRADE


def build_message(payload):
    sig = payload["signals"]
    buys = [s for s in sig if s["alert"] and _keep(s)]
    sells = [s for s in sig if s.get("alert_sell") and _keep(s)]
    # 추세 강도는 강력(25↑) 먼저, 그다음 확인(20↑)
    adxs = sorted([s for s in sig if s.get("alert_adx") and _keep(s)],
                  key=lambda s: -(s.get("adx_stage") or 0))
    if not buys and not sells and not adxs:
        return None
    asof = sig[0]["asof"]
    lines = [f"<b>📡 ETF/섹터 신호</b> · {esc(asof)} (전일 확정)", ""]
    if buys:
        lines += [f"★ 매수 신호(골든크로스) <b>{len(buys)}</b>개", ""]
        lines += _block(buys, "🟢", reasons)
    if sells:
        lines += [f"▼ 매도 경고(데드크로스) <b>{len(sells)}</b>개", ""]
        lines += _block(sells, "🔴", reasons_sell)
    if adxs:
        n2 = sum(1 for s in adxs if s.get("adx_stage") == 2)
        head = f"⚡ 추세 강도 <b>{len(adxs)}</b>개"
        if n2:
            head += f" (강력 {n2})"
        lines += [head, ""]
        lines += _block(adxs, _adx_icon, reasons_adx)
    lines += [f'전체 신호판 › <a href="{DASH_URL}">대시보드</a>', SIGNATURE]
    return "\n".join(lines)

def heartbeat_message(payload):
    asof = payload["signals"][0]["asof"] if payload.get("signals") else "-"
    return "\n".join([
        f"<b>📡 ETF/섹터 신호</b> · {esc(asof)} (전일 확정)", "",
        "오늘 새 신호 없음 ✅ (수동 갱신 확인)", "",
        f'전체 신호판 › <a href="{DASH_URL}">대시보드</a>', SIGNATURE])

def send(text):
    """전송 후 결과 dict 반환. 예외 없이 {ok, description, error_code} 형태."""
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
    tail = chat[-4:] if chat else ""
    status = {
        "when_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
        "ok": ok, "note": note,
        "chat_id_tail": tail,
        "token_set": bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
        "response": res,
    }
    with open(STATUS_PATH, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    print("상태 기록:", json.dumps(status, ensure_ascii=False))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="발송 없이 메시지만 출력")
    ap.add_argument("--force", action="store_true", help="신호 없어도 확인 메시지 발송(수동 갱신)")
    args = ap.parse_args()
    _load_env()
    with open(os.path.join(HERE, "signals.json"), encoding="utf-8") as f:
        payload = json.load(f)
    msg = build_message(payload)
    forced = False
    if msg is None:
        if args.force:
            msg, forced = heartbeat_message(payload), True
        else:
            print("오늘 알림 없음 → 발송 생략")
            _write_status(True, "no_alert_skip")
            return
    if args.dry_run:
        print("─── 미리보기 (HTML 태그 포함) ───\n")
        print(msg)
        return
    res = send(msg)
    ok = bool(res.get("ok"))
    note = ("forced_heartbeat" if forced else "alert_sent") if ok else "send_failed"
    _write_status(ok, note, res)
    if ok:
        print("텔레그램 전송 완료")
    else:
        print(f"⚠️ 텔레그램 전송 실패: {res}")  # 워크플로는 계속 진행(리포트 배포 보장)

if __name__ == "__main__":
    main()
