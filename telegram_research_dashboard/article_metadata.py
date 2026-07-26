"""링크만 있는 뉴스에서 안전하게 기사 제목과 기업명을 보강한다."""

from __future__ import annotations

import html
import ipaddress
import re
import socket
from base64 import b64decode
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from parser import extract_companies, PUBLISHER_DOMAINS


TITLE_PLACEHOLDERS = {"기사 제목 미확인", "제목 미확인"}
MAX_HTML_BYTES = 1_500_000
# 단축링크 서비스가 (주로 CI IP 차단·rate-limit 시) 리다이렉트 대신 자기 랜딩 페이지를
# 200으로 돌려주면 그 제목("URL Shortener … | TinyURL")이 기사 제목으로 저장돼버린다.
# 최종 URL이 단축 도메인에 머물러 있거나 제목이 랜딩/봇차단 문구면 수집 실패로 취급한다.
SHORTENER_HOSTS = {"tinyurl.com", "buly.kr", "bit.ly", "bitly.ws", "han.gl", "url.kr", "me2.do"}
JUNK_TITLE_RE = re.compile(
    r"url shortener|tinyurl|bitly|branded short links|just a moment|attention required"
    r"|access denied|captcha|robot check|verify you are",
    re.I,
)
# TinyURL은 봇으로 판단한 요청을 301 대신 preview 페이지(200)로 보낸다. 목적지는
# "Redirecting to <URL>" 텍스트 또는 externalPageData의 original(base64·URL인코딩) 필드에 있다.
SHORTENER_REDIRECT_RE = re.compile(r"Redirecting to (https?://[^\s\"'<>]+)", re.I)
SHORTENER_ORIGINAL_RE = re.compile(r"original(?:\\u0022|[\"']):(?:\\u0022|[\"'])([A-Za-z0-9+/=]{8,})")


def _shortener_destination(source: str) -> str | None:
    """단축링크 랜딩/프리뷰 페이지에서 목적지 URL을 찾는다."""
    match = SHORTENER_REDIRECT_RE.search(source)
    if match:
        return html.unescape(match.group(1))
    match = SHORTENER_ORIGINAL_RE.search(source)
    if match:
        try:
            return unquote(b64decode(match.group(1)).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
    return None
META_TITLE_RE = re.compile(
    r"<meta\b[^>]*(?:property|name)=[\"'](?:og:title|twitter:title)[\"'][^>]*content=[\"']([^\"']+)",
    re.I,
)
META_TITLE_RE_REVERSED = re.compile(
    r"<meta\b[^>]*content=[\"']([^\"']+)[\"'][^>]*(?:property|name)=[\"'](?:og:title|twitter:title)[\"']",
    re.I,
)
HTML_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.I | re.S)
BODY_RE = re.compile(r"<body\b[^>]*>(.*?)</body>", re.I | re.S)
SCRIPT_STYLE_RE = re.compile(r"<(?:script|style|noscript)\b[^>]*>.*?</(?:script|style|noscript)>", re.I | re.S)


class ArticleMetadataParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta, self.in_title, self.title_parts = {}, False, []

    def handle_starttag(self, tag, attrs):
        values = {key.casefold(): value for key, value in attrs if value is not None}
        if tag.casefold() == "meta":
            key = (values.get("property") or values.get("name") or "").casefold()
            if key and values.get("content"):
                self.meta[key] = values["content"]
        elif tag.casefold() == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag.casefold() == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("지원하지 않는 기사 URL")
    host = parsed.hostname.casefold()
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("로컬 주소는 열지 않음")
    for info in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80)):
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise ValueError("공개 인터넷 주소가 아님")


class SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urljoin(req.full_url, newurl)
        _validate_public_url(target)
        return super().redirect_request(req, fp, code, msg, headers, target)


def _clean_title(value: str) -> str | None:
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value).strip(" \t\r\n-|·")
    return value[:240] if len(value) >= 4 else None


def fetch_article_metadata(url: str, timeout: int = 10, _shortener_hop: bool = False) -> dict | None:
    """원문 HTML에서 제목과 기업 판별용 본문 텍스트를 반환한다."""
    try:
        _validate_public_url(url)
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; GSResearchDashboard/1.0)",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
            },
        )
        with build_opener(SafeRedirectHandler()).open(request, timeout=timeout) as response:
            content_type = response.headers.get_content_type()
            final_url = response.geturl()
            if content_type not in {"text/html", "application/xhtml+xml"}:
                return None
            raw = response.read(MAX_HTML_BYTES + 1)
            if len(raw) > MAX_HTML_BYTES:
                raw = raw[:MAX_HTML_BYTES]
            charset = response.headers.get_content_charset() or "utf-8"
            source = raw.decode(charset, errors="replace")
        parser = ArticleMetadataParser()
        parser.feed(source)
        raw_title = parser.meta.get("og:title") or parser.meta.get("twitter:title") or "".join(parser.title_parts)
        title = _clean_title(raw_title)
        final_host = (urlparse(final_url).hostname or "").casefold().removeprefix("www.")
        if final_host in SHORTENER_HOSTS or (title and JUNK_TITLE_RE.search(title)):
            destination = _shortener_destination(source)
            if destination and not _shortener_hop:
                return fetch_article_metadata(destination, timeout, _shortener_hop=True)
            return None
        description = _clean_title(parser.meta.get("og:description", "")) or ""
        body_match = BODY_RE.search(source)
        body = body_match.group(1) if body_match else source
        body = SCRIPT_STYLE_RE.sub(" ", body)
        body = html.unescape(re.sub(r"<[^>]+>", " ", body))
        body = re.sub(r"\s+", " ", body)[:50_000]
        return {"title": title, "description": description, "text": body,
                "final_url": final_url, "site_name": parser.meta.get("og:site_name")}
    except Exception:
        # 원문 하나가 이상 응답(BadStatusLine·IncompleteRead 등 HTTPException 계열 포함)을
        # 보내도 수집 파이프라인 전체가 죽으면 안 된다. 실패는 None으로 보고 넘어간다.
        return None


def fetch_article_title(url: str, timeout: int = 10) -> str | None:
    metadata = fetch_article_metadata(url, timeout)
    return metadata["title"] if metadata else None


# og:site_name이 매체명이 아니라 포털/집계 이름이면 버린다.
GENERIC_SITE_NAMES = {"네이버", "네이버 뉴스", "naver", "daum", "다음", "다음뉴스", "google"}


def publisher_from(meta: dict | None, original_url: str | None) -> str | None:
    """단축·집계 링크를 따라간 최종 URL에서 실제 언론사명을 뽑는다."""
    if not meta:
        return None
    final = meta.get("final_url") or original_url or ""
    host = (urlparse(final).hostname or "").casefold().removeprefix("www.").removeprefix("m.")
    for domain, name in PUBLISHER_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return name
    site = (meta.get("site_name") or "").strip()
    if site and 2 <= len(site) <= 30 and site.casefold() not in GENERIC_SITE_NAMES:
        return site
    return host or None


def enrich_news_item(item: dict, metadata_fetcher=fetch_article_metadata) -> dict:
    """링크 뉴스의 원문 제목과 본문을 기준으로 제목·기업을 보강한다."""
    if not item.get("article_url"):
        return item
    needs_fetch = item.get("title") in TITLE_PLACEHOLDERS or not item.get("company_name")
    # 단축 URL·차단된 사이트처럼 원문을 열지 못하더라도 현재 저장된 제목의
    # 약칭(KAI, 삼성重 등)은 먼저 표준 기업명으로 정규화한다.
    existing_companies = ([] if item.get("title") in TITLE_PLACEHOLDERS
                          else extract_companies(item.get("title", "")))
    if existing_companies:
        item["companies"] = existing_companies
        item["company_name"] = ", ".join(existing_companies)
        item["confidence"] = 0.85
        item["needs_review"] = 0
    if not needs_fetch:
        return item
    fetched = metadata_fetcher(item["article_url"])
    if isinstance(fetched, str):
        fetched = {"title": fetched, "text": fetched}
    title = fetched.get("title") if fetched else None
    if not title:
        return item
    companies = extract_companies(title)
    if not companies:
        companies = extract_companies(fetched.get("description", ""))
    if not companies:
        companies = extract_companies(fetched.get("text", ""))
    item["title"] = title
    item["summary"] = title
    item["companies"] = companies
    item["company_name"] = ", ".join(companies) if companies else None
    item["confidence"] = 0.85 if companies else 0.65
    item["needs_review"] = int(not companies)
    return item
