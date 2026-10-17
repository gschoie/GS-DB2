# -*- coding: utf-8 -*-
"""data/latest.json → 텔레그램 한 통(평문). 수주공시 봇과 같은 봇·채널로 보낸다.

시크릿: COVFLOW_TELEGRAM_BOT_TOKEN/CHAT_ID 우선 → 없으면 TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID
(dart_shiporder_bot 이 쓰는 공개채널 봇). 전송 결과는 telegram_status.json 에 남긴다.
"""
from __future__ import annotations
import os, sys, json, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import metrics  # noqa: E402

KST = timezone(timedelta(hours=9))
LATEST = os.path.join(HERE, "data", "latest.json")
STATUS = os.path.join(HERE, "telegram_status.json")
PAGE = "https://gschoie.github.io/GS-DB2/coverage_flow_report.html"
WD = "월화수목금토일"


def _creds():
    tok = os.environ.get("COVFLOW_TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("COVFLOW_TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID", "")
    return tok, chat


def _sign_won(v):
    return metrics.signed(v, 0)


def compose(d):
    """다올 수급 브리핑 형식을 따른 평문. 비어 있는 꼭지는 한 줄 안내로 대신한다."""
    rows = d.get("rows", [])
    try:
        t = datetime.strptime(d["asof"], "%Y-%m-%d %H:%M")
        head_dt = f"{t.month}/{t.day}({WD[t.weekday()]}) {t:%H:%M}"
    except Exception:
        head_dt = d.get("asof", "")
    prov = any(r.get("flow", {}).get("has_today") for r in rows)
    L = [f"[GS 조선·방산·건기] 수급 브리핑 {head_dt}", ""]
    L.append(f"외국인·기관 순매수 · {len(rows)}종목 · 5일 합산 억원{' · 오늘 잠정 포함' if prov else ''}")
    buy, sell = metrics.rank_flow(rows)
    L.append("사는 쪽 · 시총 대비 5일")
    for r in buy or []:
        f = r["flow"]
        bits = [f"{r['name']} {f['fi5_mcap_pct']:+.1f}%", f"외인 {_sign_won(f['frgn5'])}", f"기관 {_sign_won(f['inst5'])}"]
        bits += metrics.streak_text(f)
        L.append("· " + " · ".join(bits))
    if not buy:
        L.append("· 시총 대비 순매수 종목 없음")
    L.append("파는 쪽 · 시총 대비 5일")
    for r in sell or []:
        f = r["flow"]
        bits = [f"{r['name']} {f['fi5_mcap_pct']:+.1f}%", f"외인 {_sign_won(f['frgn5'])}", f"기관 {_sign_won(f['inst5'])}"]
        bits += metrics.streak_text(f)
        L.append("· " + " · ".join(bits))
    if not sell:
        L.append("· 시총 대비 순매도 종목 없음")
    tm = metrics.today_movers(rows)
    if tm:
        L.append("오늘(잠정): " + " · ".join(f"{n} {who} {_sign_won(v)}" for n, who, v in tm))

    # 기계적 수급
    L.append("")
    L.append("기계적 수급 (ETF/패시브)")
    pas = [r for r in rows if r.get("passive") and r["passive"].get("adv_pct") is not None and abs(r["passive"]["adv_pct"]) >= 1]
    pas.sort(key=lambda r: abs(r["passive"]["adv_pct"]), reverse=True)
    for r in pas[:5]:
        p = r["passive"]
        L.append(f"· {r['name']} {metrics.passive_label(p['adv_pct'])} · ADV {p['adv_pct']:+.1f}%")
    if not pas:
        if any(e.get("delta_shares") is not None for e in d.get("etfs", [])):
            L.append("· 섹터 ETF 설정·환매 미미(ADV 1% 미만)")
        else:
            L.append("· 첫 수집 — 설정·환매 비교는 다음 거래일부터")
    act = d.get("active", [])
    if act:
        L.append(f"액티브 ETF ({d.get('active_date', '')})")
        for h in act[:5]:
            pct = f" {h['pct']:+.0f}%" if h.get("pct") is not None else ""
            L.append(f"· {h['etf']} → {h['stock']} {h['kind']}{pct}")

    # 기술 지표
    L.append("")
    L.append("RSI 1년 극단" + (" (잠정)" if prov else ""))
    ex = [r for r in rows if r.get("tech", {}).get("extreme")]
    ex.sort(key=lambda r: r["tech"].get("rsi_pctl") or 50)
    lo = [r for r in ex if (r["tech"].get("rsi_pctl") or 50) <= 50]
    hi = [r for r in ex if (r["tech"].get("rsi_pctl") or 50) > 50][::-1]
    for r in lo + hi:
        t = r["tech"]
        L.append(f"· {r['name']} RSI {t['rsi']:.0f} · {t['extreme']}")
    if not ex:
        band = [r for r in rows if r.get("tech", {}).get("rsi") is not None
                and (r["tech"]["rsi"] <= metrics.RSI_LO or r["tech"]["rsi"] >= metrics.RSI_HI)]
        if band:
            for r in band:
                L.append(f"· {r['name']} RSI {r['tech']['rsi']:.0f} ({'과매도' if r['tech']['rsi'] <= 30 else '과매수'} 구간)")
        else:
            L.append("· 1년 극단권 종목 없음")

    L.append("")
    L.append("기계적 수급은 섹터 ETF 7개 Top10 비중 기준 하한값 · 규칙 기반 상태값이며 검증 전입니다.")
    L.append(PAGE)
    return "\n".join(L)


def send(text):
    tok, chat = _creds()
    if not tok or not chat:
        return {"ok": False, "description": "텔레그램 토큰/채팅ID 미설정"}
    data = json.dumps({"chat_id": chat, "text": text, "disable_web_page_preview": True}).encode("utf-8")
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "description": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "description": f"{type(e).__name__}: {e}"}


def main(argv=None):
    dry = "--dry" in (argv or sys.argv[1:])
    with open(LATEST, encoding="utf-8") as f:
        d = json.load(f)
    text = compose(d)
    print(text)
    if dry:
        return 0
    res = send(text)
    tok, chat = _creds()
    with open(STATUS, "w", encoding="utf-8") as f:
        json.dump({"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "ok": bool(res.get("ok")),
                   "description": res.get("description", ""), "token_set": bool(tok), "chat_set": bool(chat),
                   "slot": d.get("slot")}, f, ensure_ascii=False, indent=1)
    print("전송:", "성공" if res.get("ok") else f"실패 — {res.get('description')}")
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
