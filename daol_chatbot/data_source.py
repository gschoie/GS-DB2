"""DAOL-RESEARCH-TONE GitHub Pages JSON 로더.

모든 데이터는 https://gschoie.github.io/DAOL-RESEARCH-TONE/ 에서 CORS 개방으로
서빙된다(핸드오프 문서 2장). 로컬 캐시(TTL)로 재요청을 줄이고, 네트워크 실패 시
만료된 캐시라도 폴백으로 사용한다.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

BASE_URL = os.getenv("DAOL_TONE_BASE_URL", "https://gschoie.github.io/DAOL-RESEARCH-TONE/")
CACHE_DIR = Path(os.getenv("DAOL_CHATBOT_CACHE_DIR", Path(__file__).resolve().parent / "data" / "cache"))
DEFAULT_TTL_SECONDS = int(os.getenv("DAOL_CHATBOT_CACHE_TTL", "600"))


def _cache_path(name: str) -> Path:
    return CACHE_DIR / name


def fetch_json(name: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> dict | list:
    """Pages의 JSON 파일 하나를 읽는다. 캐시가 신선하면 캐시를, 아니면 원격을 사용한다."""
    path = _cache_path(name)
    if path.is_file() and (time.time() - path.stat().st_mtime) < ttl_seconds:
        return json.loads(path.read_text(encoding="utf-8"))

    url = BASE_URL.rstrip("/") + "/" + name
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding="utf-8")
        return data
    except Exception:
        # 네트워크 실패: 만료된 캐시라도 있으면 사용
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        raise


def load_tone_v2() -> dict:
    """메인 데이터 (~1.5MB): companies/sectors/events/steady/street."""
    return fetch_json("daol_tone_v2.json")


def load_summary() -> dict:
    """경량 요약: 최신 리포트 20건 + 이벤트 20건 + 카운트."""
    return fetch_json("tone_summary.json")


def load_ked_street() -> dict | list:
    """전시장 타사 리포트 120일치 — 다올 미커버 종목 질의용."""
    return fetch_json("ked_street.json")
