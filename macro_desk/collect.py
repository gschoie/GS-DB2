# -*- coding: utf-8 -*-
"""매크로 시세 수집 → static/macro_desk/<날짜>.json

설계 원칙
  · **키 없이도 돌아간다** — yfinance 만으로 금리·환율·원자재가 채워진다.
    FRED_API_KEY 를 넣으면 진짜 2년물·장단기 스프레드·기대인플레·실질금리가 더해진다.
  · 발표 지표의 **직전치**도 같이 받는다(releases.py — FRED 공개 CSV, 키 불필요).
    달력에 이름만 있으면 쓸모가 없어서다.
  · 한 종목이 실패해도 나머지는 저장한다(그 줄만 빈칸).
  · 네트워크 라이브러리는 **지연 import** — 렌더만 할 때는 설치 없이 돌게 한다
    (construction_briefing 과 같은 이유).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path

import yaml

import releases as rl

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE.parent / "telegram_research_dashboard" / "static" / "macro_desk"
KST = dt.timezone(dt.timedelta(hours=9))
KEEP_DAYS = 120

# 변화율을 재는 구간(거래일 기준 근사). 1M=21, 3M=63, 12M=252
SPANS = [("1D", 1), ("1W", 5), ("1M", 21), ("3M", 63), ("12M", 252)]


def now_kst() -> dt.datetime:
    return dt.datetime.now(KST)


def load_config() -> dict:
    return yaml.safe_load((HERE / "config.yml").read_text(encoding="utf-8"))


def _changes(closes: list[float]) -> dict:
    """마지막 값 대비 각 구간 변화. 금리는 %p, 나머지는 %로 보여줄 것이라
    여기서는 **절대차와 비율 둘 다** 담아 두고 화면이 골라 쓴다."""
    if not closes:
        return {}
    last = closes[-1]
    out = {"last": round(last, 4)}
    for label, back in SPANS:
        if len(closes) > back:
            prev = closes[-1 - back]
            if prev:
                out[label] = {"diff": round(last - prev, 4),
                              "pct": round((last - prev) / abs(prev) * 100, 2)}
    return out


def fetch_yahoo(items: list[dict]) -> dict:
    """yfinance 일별 종가 → {id: {last, 1D, 1W, …}}"""
    import yfinance as yf          # 지연 import

    out = {}
    for it in items:
        try:
            hist = yf.Ticker(it["ticker"]).history(period="400d", interval="1d")
            closes = [float(v) for v in hist["Close"].dropna().tolist()]
            if not closes:
                raise ValueError("빈 응답")
            out[it["id"]] = _changes(closes)
            print(f"  OK {it['name']:<16} {closes[-1]:>12,.2f}")
        except Exception as e:
            print(f"  ERR {it['name']:<16} {str(e)[:60]}")
    return out


def fetch_fred(items: list[dict], key: str) -> dict:
    """FRED 시계열. 키가 없으면 호출부가 아예 부르지 않는다."""
    import requests                # 지연 import

    out = {}
    start = (now_kst().date() - dt.timedelta(days=500)).isoformat()
    for it in items:
        try:
            r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                             timeout=20, params={
                                 "series_id": it["series"], "api_key": key,
                                 "file_type": "json", "observation_start": start})
            r.raise_for_status()
            vals = [float(o["value"]) for o in r.json().get("observations", [])
                    if o.get("value") not in (".", "", None)]
            if not vals:
                raise ValueError("빈 응답")
            out[it["id"]] = _changes(vals)
            print(f"  OK {it['name']:<22} {vals[-1]:>8.2f}")
        except Exception as e:
            print(f"  ERR {it['name']:<22} {str(e)[:60]}")
    return out


def collect(cfg: dict) -> dict:
    print("야후 파이낸스")
    quotes = {}
    for grp in cfg.get("quotes", []):
        quotes.update(fetch_yahoo(grp["items"]))

    fred_key = os.environ.get("FRED_API_KEY", "").strip()

    print("발표 지표 직전치(BLS 공개 API — 키 불필요" +
          (", FRED 계열 포함)" if fred_key else "; FRED 계열은 키가 없어 생략)"))
    releases = rl.fetch(cfg.get("calendar", []), fred_key)

    fred = {}
    if fred_key and cfg.get("fred"):
        print("FRED")
        fred = fetch_fred(cfg["fred"], fred_key)
    else:
        print("FRED_API_KEY 없음 — 스프레드·기대인플레·실질금리 생략")

    return {
        "date": now_kst().strftime("%Y-%m-%d"),
        "generated_at": now_kst().strftime("%Y-%m-%d %H:%M"),
        "quotes": quotes,
        "fred": fred,
        "has_fred": bool(fred),
        "releases": releases,
    }


def save(payload: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{payload['date']}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    cutoff = (now_kst().date() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    for old in sorted(OUT_DIR.glob("*.json")):
        if old.stem < cutoff:
            old.unlink()
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="저장하지 않고 출력만")
    args = ap.parse_args()

    payload = collect(load_config())
    got = len(payload["quotes"]) + len(payload["fred"]) + len(payload["releases"])
    if not got:
        raise SystemExit("수집된 값이 하나도 없다 — 저장하지 않는다")
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=1)[:2000])
        return
    print(f"\n{got}개 수집 → {save(payload)}")


if __name__ == "__main__":
    main()
