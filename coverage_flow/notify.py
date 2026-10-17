# -*- coding: utf-8 -*-
"""data/latest.json → 텔레그램 한 통(평문). 수주공시 봇과 같은 봇·채널로 보낸다.

시크릿: 봇 토큰은 COVFLOW_TELEGRAM_BOT_TOKEN → TELEGRAM_BOT_TOKEN(수주공시 봇) 순.
채널은 COVFLOW_TELEGRAM_CHAT_ID → TELEGRAM_CHAT_ID_PRIVATE(수주공시 봇의 비공개 미리보기 방) 순 —
**공개채널(TELEGRAM_CHAT_ID)로는 절대 폴백하지 않는다**(10/17 사용자 요청: 공개채널 제외).
둘 다 없으면 발송을 건너뛰고 status 에 사유만 남긴다. 전송 결과는 telegram_status.json 에.
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
    chat = os.environ.get("COVFLOW_TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID_PRIVATE", "")
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
    # 주의: pctl 0.0 은 '최저' 이지 '없음' 이 아니다 — `or 50` 으로 쓰면 1년 최저가 중간으로 간다
    ex.sort(key=lambda r: metrics.pctl_or(r["tech"].get("rsi_pctl"), 50))
    lo = [r for r in ex if metrics.pctl_or(r["tech"].get("rsi_pctl"), 50) <= 50]
    hi = [r for r in ex if metrics.pctl_or(r["tech"].get("rsi_pctl"), 50) > 50][::-1]
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
    # 대시보드 주소는 적지 않는다(반비공개 주소) — 화면은 캡쳐 사진으로 따로 보낸다(send_photo).
    return "\n".join(L)


def _multipart(fields, files):
    """fields: {name: str}, files: {field_name: path} → (body, content-type)"""
    import uuid
    boundary = "----covflow" + uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8"))
    for field, path in files.items():
        with open(path, "rb") as f:
            data = f.read()
        parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; "
                      f"filename=\"{os.path.basename(path)}\"\r\nContent-Type: image/png\r\n\r\n").encode("utf-8") + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def send_photos(paths, caption=""):
    """캡쳐 PNG 들을 앨범(sendMediaGroup) 한 묶음으로. 캡션은 첫 장에만(1024자 한도).
    한 장이면 sendPhoto. 본문은 send() 로 따로 보낸다."""
    tok, chat = _creds()
    if not tok or not chat:
        return {"ok": False, "description": "텔레그램 토큰/채팅ID 미설정"}
    paths = [p for p in paths if os.path.exists(p)]
    if not paths:
        return {"ok": False, "description": "캡쳐 파일 없음"}
    if len(paths) == 1:
        body, ctype = _multipart({"chat_id": chat, "caption": caption[:1000]}, {"photo": paths[0]})
        url = f"https://api.telegram.org/bot{tok}/sendPhoto"
    else:
        media = [{"type": "photo", "media": f"attach://p{i}", **({"caption": caption[:1000]} if i == 0 else {})}
                 for i in range(len(paths))]
        body, ctype = _multipart({"chat_id": chat, "media": json.dumps(media, ensure_ascii=False)},
                                 {f"p{i}": p for i, p in enumerate(paths)})
        url = f"https://api.telegram.org/bot{tok}/sendMediaGroup"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "description": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "description": f"{type(e).__name__}: {e}"}


def send(text):
    tok, chat = _creds()
    if not tok or not chat:
        return {"ok": False, "description": "텔레그램 토큰/채팅ID 미설정 (COVFLOW_TELEGRAM_CHAT_ID 또는 TELEGRAM_CHAT_ID_PRIVATE 필요 — 공개채널로는 보내지 않음)"}
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
    args = list(argv if argv is not None else sys.argv[1:])
    dry = "--dry" in args
    photos = []
    if "--photos" in args:
        import glob as _g
        photos = sorted(_g.glob(args[args.index("--photos") + 1]))
    with open(LATEST, encoding="utf-8") as f:
        d = json.load(f)
    text = compose(d)
    print(text)
    if dry:
        return 0
    res = send(text)
    # 사진은 본문 뒤에 — 본문이 실패하면 사진도 안 보낸다(반쪽 메시지 방지). 사진 실패는 경고만.
    pres = None
    if res.get("ok") and photos:
        pres = send_photos(photos, f"커버리지 수급 화면 · {d.get('asof', '')}")
        print(f"사진 {len(photos)}장:", "성공" if pres.get("ok") else f"실패 — {pres.get('description')}")
    tok, chat = _creds()
    with open(STATUS, "w", encoding="utf-8") as f:
        json.dump({"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "ok": bool(res.get("ok")),
                   "description": res.get("description", ""), "token_set": bool(tok), "chat_set": bool(chat),
                   "slot": d.get("slot"), "photo_ok": (None if pres is None else bool(pres.get("ok")))},
                  f, ensure_ascii=False, indent=1)
    print("전송:", "성공" if res.get("ok") else f"실패 — {res.get('description')}")
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
