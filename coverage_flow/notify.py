# -*- coding: utf-8 -*-
"""data/latest.json → 텔레그램 한 통(평문). 수주공시 봇과 같은 봇·채널로 보낸다.

시크릿: 봇 토큰은 COVFLOW_TELEGRAM_BOT_TOKEN → TELEGRAM_BOT_TOKEN(수주공시 봇) 순.
채널은 COVFLOW_TELEGRAM_CHAT_ID → TELEGRAM_CHAT_ID_PRIVATE(수주공시 봇의 비공개 미리보기 방) 순 —
**공개채널(TELEGRAM_CHAT_ID)로는 절대 폴백하지 않는다**(10/17 사용자 요청: 공개채널 제외).
둘 다 없으면 발송을 건너뛰고 status 에 사유만 남긴다. 전송 결과는 telegram_status.json 에.
"""
from __future__ import annotations
import os, re, sys, json, html, urllib.request, urllib.error
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


def _extra_chats():
    """추가 발송 방(10/20 사용자 요청: 바담 방 + DAOL 조선 방). `COVFLOW_TELEGRAM_CHAT_ID_EXTRA` 에
    쉼표·공백으로 여러 개(숫자 ID 또는 공개채널 @handle). 기본 방과 같은 ID 는 뺀다 — 두 번 안 간다.
    같은 봇 토큰으로 보내므로 봇이 그 방에 들어가(채널이면 관리자) 있어야 한다."""
    _, primary = _creds()
    out = []
    for c in re.split(r"[,\s]+", os.environ.get("COVFLOW_TELEGRAM_CHAT_ID_EXTRA", "")):
        if c and c != primary and c not in out:
            out.append(c)
    return out


SHARE_URL = "https://gs-research-desk.github.io/coverage_flow_report.html"   # 공유용 주소(50번) — 추가 방 본문 끝에만


def targets():
    """발송 방 목록 — 기본 방이 먼저(이 결과가 종료코드·status 를 정한다), 추가 방은 뒤에."""
    _, primary = _creds()
    return [primary] + _extra_chats()


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
    est_times = sorted({r["flow"]["today_src"].split(" ", 1)[1] for r in rows
                        if str(r.get("flow", {}).get("today_src", "")).startswith("estimate ")})
    today_lbl = (f" · 오늘 잠정(가집계 {'·'.join(est_times)}) 포함" if est_times else (" · 오늘 잠정 포함" if prov else ""))
    L = [f"[GS🎴 조선·방산·건기] 수급 브리핑 {head_dt}", ""]
    L.append(f"외국인·기관 순매수 · {len(rows)}종목 · 5일 합산 억원{today_lbl}")
    buy, sell = metrics.rank_flow(rows)
    L.append("📈 사는 쪽 · 시총 대비 5일")
    for r in buy or []:
        f = r["flow"]
        bits = [f"{r['name']} {f['fi5_mcap_pct']:+.1f}%", f"외인 {_sign_won(f['frgn5'])}", f"기관 {_sign_won(f['inst5'])}"]
        bits += metrics.streak_text(f)
        L.append("· " + " · ".join(bits))
    if not buy:
        L.append("· 시총 대비 순매수 종목 없음")
    L.append("📉 파는 쪽 · 시총 대비 5일")
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
    L.append("⚙️ 기계적 수급 (ETF/패시브)")
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
    L.append("🌡️ RSI 1년 극단" + (" (잠정)" if prov else ""))
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


SECTION_HEADS = ("📈 사는 쪽", "📉 파는 쪽", "⚙️ 기계적 수급", "🌡️ RSI 1년 극단")   # HTML 모드에서 볼드로 찍는 섹션 제목


def compose_html(d):
    """compose() 의 평문을 HTML 모드용으로 — 머리글(첫 줄)과 SECTION_HEADS 로 시작하는 섹션 제목을
    <b>…</b>(사용자 요청 10/19). 본문은 전부 escape 하므로 종목명의 '&'(LIG D&A)도 안전하다."""
    lines = compose(d).split("\n")
    out = []
    for i, x in enumerate(lines):
        e = html.escape(x)
        out.append(f"<b>{e}</b>" if (i == 0 or x.startswith(SECTION_HEADS)) else e)
    return "\n".join(out)


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


CAPTION_MAX = 1024   # 텔레그램 캡션 한도(일반 봇)


def send_photos(paths, caption="", parse_mode=None, chat=None):
    """캡쳐 PNG 들을 앨범(sendMediaGroup) 한 묶음으로. 캡션은 첫 장에만 — 앨범에서는 사진 **밑에**
    붙어 보인다(10/19 사용자 요청: 본문을 이미지 밑에). 한 장이면 sendPhoto. 캡션 한도는 호출부가 지킨다.
    chat 을 주면 그 방으로(추가 방), 없으면 기본 방."""
    tok, primary = _creds()
    chat = chat or primary
    if not tok or not chat:
        return {"ok": False, "description": "텔레그램 토큰/채팅ID 미설정"}
    paths = [p for p in paths if os.path.exists(p)]
    if not paths:
        return {"ok": False, "description": "캡쳐 파일 없음"}
    pm = {"parse_mode": parse_mode} if parse_mode else {}
    if len(paths) == 1:
        body, ctype = _multipart({"chat_id": chat, "caption": caption[:CAPTION_MAX], **pm}, {"photo": paths[0]})
        url = f"https://api.telegram.org/bot{tok}/sendPhoto"
    else:
        media = [{"type": "photo", "media": f"attach://p{i}", **({"caption": caption[:CAPTION_MAX], **pm} if i == 0 else {})}
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


def send(text, parse_mode=None, chat=None):
    tok, primary = _creds()
    chat = chat or primary
    if not tok or not chat:
        return {"ok": False, "description": "텔레그램 토큰/채팅ID 미설정 (COVFLOW_TELEGRAM_CHAT_ID 또는 TELEGRAM_CHAT_ID_PRIVATE 필요 — 공개채널로는 보내지 않음)"}
    body = {"chat_id": chat, "text": text, "disable_web_page_preview": True}
    if parse_mode:
        body["parse_mode"] = parse_mode
    data = json.dumps(body).encode("utf-8")
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
    import glob as _g
    if "--photos" in args:
        photos = sorted(_g.glob(args[args.index("--photos") + 1]))
    with open(LATEST, encoding="utf-8") as f:
        d = json.load(f)
    text = compose(d)
    print(text)
    if dry:
        return 0
    # 수집 오류가 하나라도 있으면 보내지 않는다(10/19 사용자 규칙). 빠진 종목이 섞인 표·캡쳐가
    # 채널에 남는 것보다 한 번 거르는 게 낫다 — 페이지는 오류 목록과 함께 갱신돼 있으니 거기서 본다.
    errs = d.get("errors") or []
    if errs:
        msg = f"수집 오류 {len(errs)}건 — 텔레그램 발송 생략"
        print(msg)
        for e in errs:
            print("  " + e)
        tok, chat = _creds()
        with open(STATUS, "w", encoding="utf-8") as f:
            json.dump({"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "ok": False, "skipped": True,
                       "description": msg, "token_set": bool(tok), "chat_set": bool(chat),
                       "slot": d.get("slot"), "photo_ok": None}, f, ensure_ascii=False, indent=1)
        return 0
    html_text = compose_html(d)
    photos = [p for p in photos if os.path.exists(p)]
    # 방마다 같은 묶음(앨범+캡션)을 보낸다 — 기본 방(바담)이 먼저, 추가 방(DAOL 조선 등)은 뒤에.
    # 추가 방 실패는 기본 방 결과(종료코드)를 바꾸지 않는다 — 늦은 크론이 재시도하면 바담 방에 두 통 간다.
    # 두 방 모두 같은 2장(① 등락률 / ①-2 투자자별) + 같은 본문(10/20 저녁 사용자 확정 "원래 그 글도
    # 넣어, 2개 방에 다"). 추가 방(DAOL 조선)만 본문 맨 밑에 공유 링크 한 줄 — 바담 방은 링크 없음(10/17 규칙).
    outs = []
    for i, chat in enumerate(targets()):
        if i:
            res, pres = _deliver(chat, d, text + "\n\n" + SHARE_URL, html_text + "\n\n" + SHARE_URL, photos)
        else:
            res, pres = _deliver(chat, d, text, html_text, photos)
        outs.append((chat, res, pres))
        tag = "기본 방" if i == 0 else f"추가 방 {chat}"
        if pres is not None:
            print(f"[{tag}] 사진 {len(photos)}장:", "성공" if pres.get("ok") else f"실패 — {pres.get('description')}")
        print(f"[{tag}] 전송:", "성공" if res.get("ok") else f"실패 — {res.get('description')}")
    _, res, pres = outs[0]
    tok, chat = _creds()
    with open(STATUS, "w", encoding="utf-8") as f:
        json.dump({"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "ok": bool(res.get("ok")),
                   "description": res.get("description", ""), "token_set": bool(tok), "chat_set": bool(chat),
                   "slot": d.get("slot"), "photo_ok": (None if pres is None else bool(pres.get("ok"))),
                   "extra": [{"chat": c, "ok": bool(r.get("ok")), "description": r.get("description", ""),
                              "photo_ok": (None if p is None else bool(p.get("ok")))} for c, r, p in outs[1:]]},
                  f, ensure_ascii=False, indent=1)
    return 0 if res.get("ok") else 1


def visible_len(html_text):
    """텔레그램 캡션 한도(1,024자)는 **파싱 뒤 보이는 글자** 기준 — <b> 태그·&amp; 같은 이스케이프는 안 센다.
    태그 길이까지 세면 본문+링크가 1,046자로 한도를 넘는 것처럼 보여 본문이 사진 밑에서 떨어진다(10/20 실측)."""
    return len(html.unescape(re.sub(r"<[^>]+>", "", html_text)))


def _deliver(chat, d, text, html_text, photos):
    """한 방에 본문+캡쳐를 보낸다. 반환 (본문/캡션 결과, 사진 결과 또는 None).
    캡쳐가 있고 본문이 캡션 한도 안이면 앨범 캡션(사진 밑) 한 덩어리 → HTML 거부 시 평문 캡션 →
    그래도 실패면 옛 방식(본문 따로 + 사진 짧은 캡션)."""
    pres = None
    res = {"ok": False, "description": "미발송"}
    if photos and visible_len(html_text) <= CAPTION_MAX:
        res = send_photos(photos, html_text, parse_mode="HTML", chat=chat)
        if not res.get("ok") and "parse" in str(res.get("description", "")).lower():
            res = send_photos(photos, text, chat=chat)
        pres = res
        if not res.get("ok"):
            print(f"캡션 앨범 실패 — {res.get('description')} → 본문 따로 발송")
    if pres is None or not pres.get("ok"):
        res = send(html_text, parse_mode="HTML", chat=chat)
        if not res.get("ok") and "parse" in str(res.get("description", "")).lower():
            res = send(text, chat=chat)                      # HTML 파싱 거부 시 평문 폴백(머리글만 볼드가 빠진다)
        # 본문이 너무 길어 캡션에 못 담은 경우에만 사진을 짧은 캡션으로 뒤따라 보낸다.
        if res.get("ok") and photos and pres is None:
            pres = send_photos(photos, f"커버리지 수급 화면 · {d.get('asof', '')}", chat=chat)
    return res, pres


if __name__ == "__main__":
    sys.exit(main())
