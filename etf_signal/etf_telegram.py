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
DASH_URL = "https://gschoie.github.io/GS-DB2/etf_signal_report.html"
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

WD_KO = "월화수목금토일"


def _week_range(today=None):
    """일요일에 도는 주간 정리가 다루는 구간 = 직전 월~금. (월, 금) date 쌍."""
    today = today or datetime.date.today()
    # 일요일(weekday 6) 기준 6일 전이 월요일. 다른 요일에 수동 실행해도 '가장 최근 월~금'.
    monday = today - datetime.timedelta(days=(today.weekday() + 1) % 7 + 6)
    if today.weekday() != 6:
        monday = today - datetime.timedelta(days=today.weekday() + 7)
    return monday, monday + datetime.timedelta(days=4)


def load_week(start, end):
    """history/<거래일>.json 을 월~금 구간만큼 읽는다. 휴장일 파일은 없으므로 건너뛴다."""
    days = []
    d = start
    while d <= end:
        path = os.path.join(HERE, "history", f"{d.isoformat()}.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                days.append((d, json.load(f)))
        d += datetime.timedelta(days=1)
    return days


def _tally(days, flag):
    """주중에 그 신호가 뜬 종목을 모은다. {code: {name, group, 요일들, 마지막 신호}}"""
    picked = {}
    for day, payload in days:
        for s in payload.get("signals") or []:
            if not s.get(flag) or not _keep(s):
                continue
            row = picked.setdefault(s["code"], {"name": s["name"], "group": s["group"],
                                                "days": [], "last": s})
            row["days"].append(WD_KO[day.weekday()])
            row["last"] = s
    return picked


def _week_returns(days):
    """주 첫 거래일 종가 → 마지막 거래일 종가 등락률. {code: (name, pct)}"""
    if len(days) < 2:
        return {}
    first = {s["code"]: s for s in (days[0][1].get("signals") or [])}
    last = {s["code"]: s for s in (days[-1][1].get("signals") or [])}
    out = {}
    for code, s in last.items():
        base = first.get(code, {}).get("close")
        if base:
            out[code] = (s["name"], (s["close"] - base) / base * 100)
    return out


def weekly_message(today=None):
    """일요일 발송용 '월~금 누적' 정리. 한 주 동안 뜬 신호를 종목별로 묶어 보여준다.

    매일 발송은 '그날 뜬 신호'만 보여주므로 주 중에 흘려보낸 것을 놓치기 쉽다.
    주말에 한 번 몰아 보면 '이번 주에 어떤 종목이 몇 번 신호를 냈나'가 남는다.
    """
    start, end = _week_range(today)
    days = load_week(start, end)
    if not days:
        return None

    span = f"{start:%m/%d}~{end:%m/%d}"
    lines = [f"<b>📡 ETF/섹터 신호 · 월~금 누적</b> · {span} ({len(days)}거래일)", ""]

    buys, sells, adxs = _tally(days, "alert"), _tally(days, "alert_sell"), _tally(days, "alert_adx")
    rets = _week_returns(days)

    def block(title, picked, icon):
        if not picked:
            return []
        rows = sorted(picked.values(), key=lambda r: (-len(r["days"]), r["name"]))[:8]
        out = [f"{title} <b>{len(picked)}</b>개", ""]
        for r in rows:
            code = next(c for c, v in picked.items() if v is r)
            pct = rets.get(code, (None, None))[1]
            move = f" · 주간 {pct:+.1f}%" if pct is not None else ""
            out += [f"{icon} <b>{esc(r['name'])}</b> · {esc(r['group'])}",
                    f"   {esc('·'.join(r['days']))}요일 {len(r['days'])}회{move}", ""]
        if len(picked) > len(rows):
            out += [f"   … 외 {len(picked) - len(rows)}개", ""]
        return out

    body = (block("★ 매수 신호", buys, "🟢")
            + block("▼ 매도 경고", sells, "🔴")
            + block("⚡ 추세 강도", adxs, "⚡"))
    if not body:
        lines += ["이번 주 새 신호 없음 ✅", ""]
    else:
        lines += body

    if rets:
        ranked = sorted(rets.values(), key=lambda x: -x[1])
        top = " · ".join(f"{esc(n)} {p:+.1f}%" for n, p in ranked[:3])
        bottom = " · ".join(f"{esc(n)} {p:+.1f}%" for n, p in ranked[-3:][::-1])
        lines += [f"📈 주간 상승 {top}", f"📉 주간 하락 {bottom}", ""]

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
    ap.add_argument("--weekly", action="store_true",
                    help="월~금 누적 정리 발송(일요일). signals.json 대신 history를 읽는다")
    args = ap.parse_args()
    _load_env()

    if args.weekly:
        msg = weekly_message()
        if msg is None:
            print("주간 history 없음 → 발송 생략")
            _write_status(True, "weekly_no_history")
            return
        if args.dry_run:
            print("─── 미리보기 (HTML 태그 포함) ───\n")
            print(msg)
            return
        res = send(msg)
        ok = bool(res.get("ok"))
        _write_status(ok, "weekly_sent" if ok else "send_failed", res)
        print("텔레그램 전송 완료" if ok else f"⚠️ 텔레그램 전송 실패: {res}")
        return

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
