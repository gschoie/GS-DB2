#!/usr/bin/env python3
"""유튜브 요리 숏츠 → 레시피 추출 → Notion 저장 봇.

흐름:
  1. 유튜브 링크에서 제목·채널·설명·자막(가능하면)을 수집한다 (yt-dlp,
     실패 시 oEmbed+페이지 메타 폴백 — GitHub 러너에서 yt-dlp가 봇체크에
     막히는 경우가 있어 폴백이 필수다)
  2. Gemini로 요리명/분류/재료/조리방법을 JSON으로 추출한다
  3. Notion 「🍳 레시피」 DB에 페이지로 저장한다 (속성 + 본문 블록)

필수 환경변수: NOTION_TOKEN, GEMINI_API_KEY
선택: RECIPE_DB_ID (기본: 대시보드용 🍳 레시피 DB)
사용: python recipe_bot.py --url "https://youtube.com/shorts/..."
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

import requests

NOTION_DB = os.environ.get("RECIPE_DB_ID", "1a57f2a566ff46a1aec80d6d31407e21")
NOTION_API = "https://api.notion.com/v1"
CATEGORIES = ["한식", "중식", "일식", "양식", "간식/디저트", "기타"]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


# ────────────────────────── 유튜브 수집 ──────────────────────────
def video_id(url: str) -> str:
    m = (re.search(r"(?:shorts/|watch\?v=|youtu\.be/)([\w-]{11})", url)
         or re.fullmatch(r"\s*([\w-]{11})\s*", url))
    if not m:
        raise SystemExit(f"유튜브 링크를 인식하지 못했습니다: {url!r}")
    return m.group(1)


def _captions_text(info: dict) -> str:
    """yt-dlp info에서 한국어(없으면 영어) 자동자막을 내려받아 평문으로 합친다."""
    subs = {**(info.get("automatic_captions") or {}), **(info.get("subtitles") or {})}
    for lang in ("ko", "ko-orig", "en"):
        for fmt in subs.get(lang, []):
            if fmt.get("ext") != "json3":
                continue
            try:
                data = requests.get(fmt["url"], headers={"User-Agent": UA}, timeout=30).json()
                parts = [seg.get("utf8", "") for ev in data.get("events", [])
                         for seg in (ev.get("segs") or [])]
                text = re.sub(r"\s+", " ", "".join(parts)).strip()
                if len(text) > 40:
                    return text[:6000]
            except Exception:
                continue
    return ""


def fetch_video(url: str) -> dict:
    vid = video_id(url)
    canonical = f"https://www.youtube.com/watch?v={vid}"
    meta = {"url": canonical, "title": "", "channel": "", "description": "", "captions": ""}

    # 1차: yt-dlp (제목·설명·자막까지 전부)
    try:
        from yt_dlp import YoutubeDL
        with YoutubeDL({"quiet": True, "skip_download": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(canonical, download=False)
        meta["title"] = info.get("title") or ""
        meta["channel"] = info.get("channel") or info.get("uploader") or ""
        meta["description"] = (info.get("description") or "")[:4000]
        meta["captions"] = _captions_text(info)
        print(f"yt-dlp OK: 제목·설명 {len(meta['description'])}자 · 자막 {len(meta['captions'])}자")
        return meta
    except Exception as exc:
        print(f"yt-dlp 실패({type(exc).__name__}) → oEmbed 폴백")

    # 2차: oEmbed(제목·채널) + 페이지 og:description
    try:
        o = requests.get("https://www.youtube.com/oembed",
                         params={"url": canonical, "format": "json"}, timeout=20).json()
        meta["title"], meta["channel"] = o.get("title", ""), o.get("author_name", "")
    except Exception:
        pass
    try:
        html_text = requests.get(canonical, headers={"User-Agent": UA, "Accept-Language": "ko"},
                                 timeout=30).text
        m = (re.search(r'"shortDescription":"((?:[^"\\]|\\.)*)"', html_text)
             or re.search(r'<meta property="og:description" content="([^"]*)"', html_text))
        if m:
            desc = m.group(1).encode().decode("unicode_escape", errors="ignore")
            meta["description"] = desc[:4000]
    except Exception:
        pass
    if not meta["title"]:
        raise SystemExit("유튜브에서 영상 정보를 가져오지 못했습니다(링크 확인).")
    print(f"폴백 수집: 제목 OK · 설명 {len(meta['description'])}자")
    return meta


# ────────────────────────── Gemini 추출 ──────────────────────────
def extract_recipe(meta: dict) -> dict:
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client()  # GEMINI_API_KEY 사용
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    prompt = f"""다음은 유튜브 요리 영상의 정보다. 레시피를 추출해 JSON으로만 답하라.

제목: {meta['title']}
채널: {meta['channel']}
설명:
{meta['description'] or '(없음)'}

자막(자동 인식이라 오탈자 가능):
{meta['captions'] or '(없음)'}

JSON 스키마:
{{
  "요리명": "간결한 요리 이름 (한국어)",
  "분류": "{'|'.join(CATEGORIES)} 중 하나",
  "재료": ["재료와 분량, 한 줄에 하나", ...],
  "조리방법": ["순서대로 한 단계씩", ...]
}}

규칙: 영상 정보에 근거해서만 작성하고, 재료 분량이 안 나오면 재료명만 적는다.
정보가 부족해 레시피를 알 수 없으면 조리방법에 "영상 정보 부족"이라고 한 줄만 넣는다."""
    config = genai_types.GenerateContentConfig(response_mime_type="application/json")
    response = client.models.generate_content(model=model, contents=prompt, config=config)
    data = json.loads(response.text)
    if data.get("분류") not in CATEGORIES:
        data["분류"] = "기타"
    data.setdefault("요리명", meta["title"][:80] or "이름 미상")
    data["재료"] = [str(x).strip() for x in (data.get("재료") or []) if str(x).strip()]
    data["조리방법"] = [str(x).strip() for x in (data.get("조리방법") or []) if str(x).strip()]
    return data


# ────────────────────────── Notion 저장 ──────────────────────────
def _rt(text: str) -> list:
    return [{"text": {"content": text[:1990]}}] if text else []


def save_to_notion(meta: dict, recipe: dict) -> str:
    token = os.environ["NOTION_TOKEN"]
    headers = {"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28",
               "Content-Type": "application/json"}
    ingredients = "\n".join(recipe["재료"])
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(recipe["조리방법"], 1))
    children = [
        {"object": "block", "type": "heading_2",
         "heading_2": {"rich_text": _rt("🧺 재료")}},
        *[{"object": "block", "type": "bulleted_list_item",
           "bulleted_list_item": {"rich_text": _rt(item)}} for item in recipe["재료"][:60]],
        {"object": "block", "type": "heading_2",
         "heading_2": {"rich_text": _rt("👨‍🍳 조리방법")}},
        *[{"object": "block", "type": "numbered_list_item",
           "numbered_list_item": {"rich_text": _rt(step)}} for step in recipe["조리방법"][:60]],
        {"object": "block", "type": "bookmark", "bookmark": {"url": meta["url"]}},
    ]
    body = {
        "parent": {"database_id": NOTION_DB},
        "properties": {
            "요리명": {"title": _rt(recipe["요리명"])},
            "재료": {"rich_text": _rt(ingredients)},
            "조리방법": {"rich_text": _rt(steps)},
            "유튜브": {"url": meta["url"]},
            "채널": {"rich_text": _rt(meta["channel"])},
            "분류": {"select": {"name": recipe["분류"]}},
        },
        "children": children,
    }
    r = requests.post(f"{NOTION_API}/pages", headers=headers, json=body, timeout=30)
    if r.status_code >= 300:
        raise SystemExit(f"Notion 저장 실패 {r.status_code}: {r.text[:400]}")
    return r.json().get("url", "")


def main() -> None:
    parser = argparse.ArgumentParser(description="유튜브 요리 영상 → Notion 레시피 저장")
    parser.add_argument("--url", default=os.getenv("YT_URL", ""), help="유튜브 숏츠/영상 링크")
    args = parser.parse_args()
    if not args.url.strip():
        sys.exit("유튜브 링크(--url 또는 env YT_URL)가 필요합니다.")
    meta = fetch_video(args.url.strip())
    recipe = extract_recipe(meta)
    print(f"추출: {recipe['요리명']} [{recipe['분류']}] · 재료 {len(recipe['재료'])} · 단계 {len(recipe['조리방법'])}")
    page_url = save_to_notion(meta, recipe)
    print(f"Notion 저장 완료: {page_url}")


if __name__ == "__main__":
    main()
