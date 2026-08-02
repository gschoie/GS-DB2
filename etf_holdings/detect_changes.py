# -*- coding: utf-8 -*-
"""전일 대비 구성종목 변화 감지 엔진.

핵심 아이디어: 비중(%)은 주가로 매일 저절로 흔들리므로 그대로 쓰면 노이즈.
그래서 '주가 효과'와 'CU 자금유출입 효과'를 제거하고 **운용사가 실제로 사고판 것**만 남긴다.

계약수(shares)는 주가와 무관 → 실매매의 깨끗한 신호.
  · CU 자금유출입: 설정/환매로 전 종목 계약수가 같은 배수 f로 스케일 → f로 정규화해 제거.
  · active_ratio = (오늘계약수/전일계약수) / f   (>1 실제 매수, <1 실제 매도)
액티브 비중변화(%p): 전일 계약수를 오늘 단가로 평가한 '무매매 가정 비중'(w_passive)과
  실제 오늘 비중(w_now)의 차 = w_now - w_passive. 주가·자금흐름이 상쇄된 순수 리밸런싱.

트리거(합의):
  · 신규 Top10 진입 / Top10 이탈: 항상
  · 대형 리밸런싱: |액티브 비중변화| ≥ 1.0%p  (5.0%p 이상은 헤드라인 강조)
  · 포지션 대폭 조정: |액티브 계약수변화| ≥ 30%  (작은 종목이 배증/반토막 잡기)

결과: changes.json (리포트/텔레그램이 읽음)
"""
from __future__ import annotations
import os, sys, json, glob, statistics
from datetime import datetime, timedelta, timezone

try:  # Windows 콘솔(cp949)에서 이모지/em-dash 출력 대비
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR = os.path.join(HERE, "snapshots")
KST = timezone(timedelta(hours=9))

# ── 임계값 ──
WEIGHT_PP_MIN = 1.0      # 액티브 비중변화 감지 하한(%p)
WEIGHT_PP_BIG = 5.0      # 헤드라인 강조(%p)
SHARE_PCT_MIN = 30.0     # 액티브 계약수변화 감지 하한(%)


def _snap_dates():
    files = sorted(glob.glob(os.path.join(SNAP_DIR, "*.json")))
    return [(os.path.splitext(os.path.basename(f))[0], f) for f in files]


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _by_key(holdings):
    return {h["key"]: h for h in holdings if h.get("key")}


def diff_etf(prev, now):
    """한 ETF의 전일→오늘 변화. prev/now = etf record(dict)."""
    ph, nh = _by_key(prev["holdings"]), _by_key(now["holdings"])
    pk, nk = set(ph), set(nh)
    common = [k for k in nk & pk if ph[k]["shares"] > 0 and nh[k]["shares"] > 0]

    # CU 자금유출입 배수 f (공통 종목 계약수비의 중앙값)
    ratios = [nh[k]["shares"] / ph[k]["shares"] for k in common]
    f = statistics.median(ratios) if ratios else 1.0
    if f <= 0:
        f = 1.0

    # 액티브 비중변화용 무매매 가정 비중(공통 종목, 비중 존재시)
    has_w = any(nh[k]["weight"] > 0 for k in common)
    w_common = sum(nh[k]["weight"] for k in common)
    denom = sum((nh[k]["weight"] / (nh[k]["shares"] / ph[k]["shares"]))
                for k in common if nh[k]["weight"] > 0)

    moves = []
    for k in common:
        qratio = nh[k]["shares"] / ph[k]["shares"]
        active_ratio = qratio / f
        active_share_pct = (active_ratio - 1) * 100
        w_now = nh[k]["weight"]
        w_pp = None
        if has_w and w_now > 0 and denom > 0:
            w_passive = w_common * (w_now / qratio) / denom
            w_pp = w_now - w_passive
        big = (w_pp is not None and abs(w_pp) >= WEIGHT_PP_MIN)
        resize = abs(active_share_pct) >= SHARE_PCT_MIN
        if big or resize:
            moves.append({
                "key": k, "name": nh[k]["name"], "code": nh[k]["code"],
                "shares_now": nh[k]["shares"], "shares_prev": ph[k]["shares"],
                "active_share_pct": round(active_share_pct, 1),
                "active_weight_pp": None if w_pp is None else round(w_pp, 2),
                "weight_now": round(w_now, 2), "weight_prev": round(ph[k]["weight"], 2),
                "headline": bool(w_pp is not None and abs(w_pp) >= WEIGHT_PP_BIG),
            })
    moves.sort(key=lambda m: abs(m["active_weight_pp"] or 0) + abs(m["active_share_pct"]) / 100,
               reverse=True)

    new = [{"key": k, "name": nh[k]["name"], "code": nh[k]["code"],
            "weight": round(nh[k]["weight"], 2), "shares": nh[k]["shares"]}
           for k in nk - pk]
    gone = [{"key": k, "name": ph[k]["name"], "code": ph[k]["code"],
             "weight_prev": round(ph[k]["weight"], 2), "shares_prev": ph[k]["shares"]}
            for k in pk - nk]
    new.sort(key=lambda x: x["weight"], reverse=True)
    gone.sort(key=lambda x: x["weight_prev"], reverse=True)
    return {"flow_factor": round(f, 4), "new": new, "gone": gone, "moves": moves,
            "has_weight": has_w}


def compare(prev, now, prev_date, now_date, generated=""):
    """두 스냅샷(dict)을 비교해 changes payload를 만든다. 리포트의 과거일 재계산에도 사용."""
    etfs_out = []
    n_new = n_gone = n_moves = 0
    for code, now_rec in now["etfs"].items():
        prev_rec = prev["etfs"].get(code)
        if not prev_rec:
            continue
        d = diff_etf(prev_rec, now_rec)
        if not (d["new"] or d["gone"] or d["moves"]):
            continue
        n_new += len(d["new"]); n_gone += len(d["gone"]); n_moves += len(d["moves"])
        etfs_out.append({
            "code": code, "label": now_rec.get("label", now_rec.get("name", "")),
            "group": now_rec.get("group", ""), **d,
        })

    # 변화 큰 ETF 먼저
    etfs_out.sort(key=lambda e: (len(e["new"]) + len(e["gone"])) * 10
                  + sum(1 for m in e["moves"] if m["headline"]) * 5 + len(e["moves"]),
                  reverse=True)
    today_base = now.get("base_date", "")
    prev_base = prev.get("base_date", "")
    return {
        "date": now_date, "prev_date": prev_date, "generated_at": generated,
        "base_date": today_base, "prev_base_date": prev_base,
        "same_base": bool(today_base and today_base == prev_base),
        "first_run": False, "etfs": etfs_out,
        "thresholds": {"weight_pp_min": WEIGHT_PP_MIN, "weight_pp_big": WEIGHT_PP_BIG,
                       "share_pct_min": SHARE_PCT_MIN},
        "summary": {"etfs_changed": len(etfs_out), "new_total": n_new,
                    "gone_total": n_gone, "moves_total": n_moves,
                    "universe": len(now["etfs"])},
    }


def detect():
    dates = _snap_dates()
    generated = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    if not dates:
        raise SystemExit("스냅샷이 없습니다. 먼저 fetch_holdings.py 실행")
    today_date, today_path = dates[-1]
    today = _load(today_path)

    if len(dates) < 2:
        payload = {"date": today_date, "prev_date": None, "generated_at": generated,
                   "base_date": today.get("base_date", ""), "first_run": True, "etfs": [],
                   "summary": {"etfs_changed": 0, "new_total": 0, "gone_total": 0,
                               "moves_total": 0, "universe": len(today["etfs"])}}
        _save(payload)
        print(f"첫 스냅샷({today_date}) — 비교 대상 없음. 내일부터 변화 감지.")
        return payload

    prev_date, prev_path = dates[-2]
    prev = _load(prev_path)
    payload = compare(prev, today, prev_date, today_date, generated)
    etfs_out = payload["etfs"]
    n_new, n_gone = payload["summary"]["new_total"], payload["summary"]["gone_total"]
    n_moves = payload["summary"]["moves_total"]
    _save(payload)
    print(f"변화 감지: {today_date} vs {prev_date} · 변화ETF {len(etfs_out)}개 "
          f"(신규 {n_new}·이탈 {n_gone}·실매매 {n_moves}) → changes.json")
    return payload


def _save(payload):
    with open(os.path.join(HERE, "changes.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    detect()
