"""소스 종류별 수집 어댑터.

모든 어댑터는 `Item` 리스트를 돌려준다. 어댑터는 '새 글인지'를 판단하지 않는다.
중복 판정·발송 여부는 watch_sources.py가 상태 파일(state/seen.json)로 결정한다.

지원 종류
- telegram : 공개 채널 웹 미리보기(t.me/s/<채널>) 파싱. 로그인·봇 초대 불필요.
- rss      : RSS 2.0 / Atom. 네이버 블로그(rss.blog.naver.com/<id>.xml) 포함.
- web      : CSS 선택자로 목록 페이지를 긁는 범용 어댑터(beautifulsoup4 필요).
"""

from __future__ import annotations

import asyncio
import html
import os
import re
import time
import urllib.error
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

USER_AGENT = "Mozilla/5.0 (compatible; GS-SourceWatcher/1.0)"


@dataclass
class Item:
    """수집된 글 한 건.

    uid는 소스 안에서 글을 유일하게 식별하는 키다. 상태 파일에 이 값이 쌓이므로
    같은 글이 매번 다른 uid로 나오면 중복 발송된다(예: 시간이 섞인 URL 금지).

    origin은 한 소스가 여러 채널을 훑을 때(telegram_account) 글이 나온 채널 이름이다.
    알림에 소스 이름 대신 이것을 찍어야 어느 방에서 온 말인지 알 수 있다.
    """

    uid: str
    title: str
    url: str
    body: str
    published_at: datetime | None = None
    origin: str | None = None

    def text_for_match(self) -> str:
        return f"{self.title}\n{self.body}"


def fetch(url: str, *, timeout: int = 30, retries: int = 4) -> str:
    """일시적 DNS/네트워크 오류에 죽지 않도록 재시도하며 본문을 받아온다.

    public_importer.fetch_page와 같은 정책(4회·점증 대기). Actions 러너에서
    간헐적으로 나는 'Name or service not known'을 흡수하기 위한 것이다.
    """
    request = Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, OSError) as exc:
            last_error = exc
            print(f"  ⚠ 요청 실패({attempt + 1}/{retries}) {url}: {exc} — 재시도", flush=True)
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
    raise last_error  # type: ignore[misc]


# ── 공통 유틸 ──────────────────────────────────────────────────────────────

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t ]+")


def strip_html(value: str) -> str:
    """HTML 조각을 읽을 수 있는 평문으로. <br>/</p>는 줄바꿈으로 살린다."""
    value = re.sub(r"(?i)<\s*br\s*/?>", "\n", value)
    value = re.sub(r"(?i)</\s*(p|div|li|tr|h[1-6])\s*>", "\n", value)
    value = TAG_RE.sub("", value)
    value = html.unescape(value).replace("\xa0", " ")
    value = WS_RE.sub(" ", value)
    return "\n".join(line.strip() for line in value.splitlines() if line.strip())


def to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def first_line(value: str, limit: int = 80) -> str:
    """본문만 있고 제목이 없는 소스(텔레그램)의 제목을 첫 줄에서 만든다."""
    for line in value.splitlines():
        line = line.strip()
        if line:
            return line[:limit] + ("…" if len(line) > limit else "")
    return "(제목 없음)"


# ── telegram ──────────────────────────────────────────────────────────────
#
# 파싱 규칙은 telegram_research_dashboard/public_importer.py와 동일하다.
# 그쪽은 SQLite 적재가 목적이라 db/telegram_importer에 묶여 있어서, 발송 전용인
# 여기서는 의존성 없이 쓰도록 최소한만 가져왔다. t.me HTML이 바뀌면 양쪽 모두 손봐야 한다.

POST_RE = re.compile(r'data-post="([^"/]+)/([0-9]+)"')
DATETIME_RE = re.compile(r'<time[^>]+datetime="([^"]+)"')
BLOCK_RE = re.compile(
    r'(<div class="tgme_widget_message_wrap[^>]*>.*?)'
    r'(?=<div class="tgme_widget_message_wrap|<div class="tgme_widget_message_centered|\Z)',
    re.S,
)


class _MessageTextParser(HTMLParser):
    """본문 div만 캡처한다. 답글 인용(js-message_reply_text)은 본문이 아니라 제외."""

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.capture = False
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        classes = values.get("class", "").split()
        if (
            tag == "div"
            and "tgme_widget_message_text" in classes
            and "js-message_reply_text" not in classes
        ):
            self.capture = True
            self.depth = 1
            return
        if self.capture:
            if tag == "div":
                self.depth += 1
            if tag == "br":
                self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.capture and tag == "div":
            self.depth -= 1
            if self.depth == 0:
                self.capture = False

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)

    def text(self) -> str:
        value = html.unescape("".join(self.parts)).replace("\xa0", " ")
        return "\n".join(line.strip() for line in value.splitlines() if line.strip())


def normalize_channel(value: str) -> str:
    """@채널 / https://t.me/채널 / t.me/s/채널 → 채널"""
    value = value.strip().rstrip("/")
    if value.startswith("@"):
        return value[1:]
    if "t.me/" in value:
        return urlparse(value if "//" in value else f"https://{value}").path.strip("/").removeprefix("s/")
    return value


def parse_telegram_page(source_html: str, channel: str) -> list[Item]:
    items: list[Item] = []
    for block in BLOCK_RE.findall(source_html):
        post = POST_RE.search(block)
        stamp = DATETIME_RE.search(block)
        if not post or not stamp:
            continue
        parser = _MessageTextParser()
        parser.feed(block)
        text = parser.text()
        if not text:
            continue
        message_id = int(post.group(2))
        items.append(
            Item(
                uid=f"{channel}:{message_id}",
                title=first_line(text),
                url=f"https://t.me/{channel}/{message_id}",
                body=text,
                published_at=to_utc(datetime.fromisoformat(stamp.group(1).replace("Z", "+00:00"))),
            )
        )
    return items


def collect_telegram(source: dict) -> list[Item]:
    channel = normalize_channel(str(source.get("channel") or source.get("url") or ""))
    if not channel:
        raise ValueError("telegram 소스에는 channel(또는 url)이 필요합니다")
    # 채널 아이디는 원래 영문·숫자·밑줄이다. 한글이 들어왔다는 것은 sources.yml의
    # 예시를 안 바꿨거나 채널 '이름'을 넣었다는 뜻이라, 붙여 보기 전에 바로 알려준다.
    if not re.fullmatch(r"[A-Za-z0-9_]+", channel):
        raise ValueError(
            f"채널 주소가 아닙니다: {channel!r} — @아이디 또는 t.me/아이디 형식이어야 합니다"
        )
    return parse_telegram_page(fetch(f"https://t.me/s/{channel}"), channel)


# ── rss ───────────────────────────────────────────────────────────────────

def _tag(element: ET.Element) -> str:
    """네임스페이스를 떼어낸 태그명. Atom은 항상 네임스페이스가 붙는다."""
    return element.tag.rsplit("}", 1)[-1].lower()


def _child_text(entry: ET.Element, *names: str) -> str:
    for child in entry:
        if _tag(child) in names:
            return (child.text or "").strip()
    return ""


def _entry_link(entry: ET.Element) -> str:
    # RSS는 <link>텍스트</link>, Atom은 <link href="…" rel="alternate"/>
    fallback = ""
    for child in entry:
        if _tag(child) != "link":
            continue
        if child.text and child.text.strip():
            return child.text.strip()
        href = child.attrib.get("href", "").strip()
        if href and child.attrib.get("rel", "alternate") == "alternate":
            return href
        fallback = fallback or href
    return fallback


def _entry_date(entry: ET.Element) -> datetime | None:
    raw = _child_text(entry, "pubdate", "published", "updated", "date")
    if not raw:
        return None
    try:  # RFC822 (네이버 블로그 RSS 포함)
        return to_utc(parsedate_to_datetime(raw))
    except (TypeError, ValueError, IndexError):
        pass
    try:  # ISO8601 (Atom)
        return to_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError:
        return None


def parse_feed(xml_text: str) -> list[Item]:
    root = ET.fromstring(xml_text.strip())
    entries = [node for node in root.iter() if _tag(node) in {"item", "entry"}]
    items: list[Item] = []
    for entry in entries:
        link = _entry_link(entry)
        title = strip_html(_child_text(entry, "title")) or "(제목 없음)"
        body = strip_html(_child_text(entry, "description", "summary", "content", "encoded"))
        guid = _child_text(entry, "guid", "id") or link or title
        items.append(
            Item(uid=guid, title=title, url=link, body=body, published_at=_entry_date(entry))
        )
    return items


def collect_rss(source: dict) -> list[Item]:
    url = source.get("url")
    if not url:
        raise ValueError("rss 소스에는 url이 필요합니다")
    return parse_feed(fetch(url))


# ── web ───────────────────────────────────────────────────────────────────

def collect_web(source: dict) -> list[Item]:
    """목록 페이지를 CSS 선택자로 긁는다. RSS도 텔레그램도 없는 소스용 최후 수단.

    필요한 키: url, item_selector. 선택: title_selector, link_selector, body_selector.
    사이트 개편에 그대로 깨지므로, 가능하면 rss/telegram을 먼저 찾을 것.
    """
    try:
        from bs4 import BeautifulSoup  # 이 어댑터를 쓸 때만 필요
    except ImportError as exc:  # pragma: no cover - 환경 의존
        raise RuntimeError("web 어댑터에는 beautifulsoup4가 필요합니다: pip install beautifulsoup4") from exc

    url = source["url"]
    selector = source.get("item_selector")
    if not selector:
        raise ValueError("web 소스에는 item_selector가 필요합니다")

    soup = BeautifulSoup(fetch(url), "html.parser")
    items: list[Item] = []
    for node in soup.select(selector):
        def pick(key: str):
            sub = source.get(key)
            return node.select_one(sub) if sub else None

        title_node = pick("title_selector") or node
        link_node = pick("link_selector") or (node if node.name == "a" else node.find("a"))
        body_node = pick("body_selector")

        href = (link_node.get("href") if link_node else None) or ""
        link = urljoin(url, href) if href else url
        title = strip_html(title_node.decode_contents()) if title_node else ""
        body = strip_html(body_node.decode_contents()) if body_node else ""
        if not title and not body:
            continue
        items.append(Item(uid=link or title, title=title or first_line(body), url=link, body=body))
    return items


# ── telegram_account ──────────────────────────────────────────────────────
#
# 채널을 하나씩 지정하지 않고 '내가 들어가 있는 모든 채널'을 훑는다. 공개 미리보기
# (t.me/s)로는 불가능한 일이다 — 비공개·초대링크 채널은 로그인 없이 보이지 않고,
# 공개 채널이라도 주소를 알아야 읽을 수 있기 때문이다. 대신 내 계정 세션이 필요하다.
#
# 호출량을 줄이는 것이 이 어댑터의 핵심이다. 대화 목록은 한 번에 100개씩 받아오면서
# 각 방의 최신 글 시각을 같이 주므로, 그 시각이 조회 창(lookback)보다 오래된 방은
# 히스토리를 아예 요청하지 않는다. 채널 300개를 구독해도 실제 요청은 대화 목록
# 3~4번 + 새 글이 있는 방 몇 개뿐이다.

DEFAULT_SESSION_PATH = "data/telegram_user"


def _account_session():
    """세션 문자열(CI·서버용)이 있으면 그것을, 없으면 세션 파일 경로를 쓴다."""
    raw = os.environ.get("TELEGRAM_SESSION_STRING", "").strip()
    if raw:
        from telethon.sessions import StringSession

        return StringSession(raw)
    return os.environ.get("TELEGRAM_SESSION_PATH", DEFAULT_SESSION_PATH)


def _chat_names(entity) -> set[str]:
    names = set()
    for value in (getattr(entity, "username", None), getattr(entity, "title", None)):
        if value:
            names.add(str(value).casefold())
    return names


def _message_url(entity, message_id: int) -> str:
    username = getattr(entity, "username", None)
    if username:
        return f"https://t.me/{username}/{message_id}"
    # 비공개 채널은 내부 주소만 있다. 텔레그램 앱에서는 열리지만 브라우저에서는 열리지 않는다.
    internal = str(getattr(entity, "id", "")).lstrip("-").removeprefix("100")
    return f"https://t.me/c/{internal}/{message_id}" if internal else ""


async def _scan_account(source: dict, since: datetime) -> list[Item]:
    from telethon import TelegramClient

    api_id = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    if not api_id or not api_hash:
        raise RuntimeError(
            "telegram_account 어댑터에는 TELEGRAM_API_ID/TELEGRAM_API_HASH가 필요합니다 "
            "(my.telegram.org에서 발급)"
        )

    include = {str(name).lstrip("@").casefold() for name in (source.get("include_chats") or [])}
    exclude = {str(name).lstrip("@").casefold() for name in (source.get("exclude_chats") or [])}
    include_groups = bool(source.get("include_groups"))
    per_chat_limit = int(source.get("per_chat_limit") or 30)
    max_chats = int(source.get("max_chats") or 500)

    client = TelegramClient(_account_session(), int(api_id), api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            # 여기서 대화형 로그인을 시작하면 자동 실행이 입력을 기다리며 멈춰 선다.
            raise RuntimeError(
                "텔레그램 계정 세션이 없습니다 — 먼저 `python login_account.py`로 한 번 로그인하세요"
            )

        items: list[Item] = []
        scanned = 0
        async for dialog in client.iter_dialogs(limit=max_chats):
            entity = dialog.entity
            broadcast = bool(getattr(entity, "broadcast", False))
            megagroup = bool(getattr(entity, "megagroup", False))
            if not broadcast and not (include_groups and megagroup):
                continue  # 1:1 대화와 일반 그룹은 리서치 소스가 아니다

            names = _chat_names(entity)
            if include and not (names & include):
                continue
            if names & exclude:
                continue
            # 최신 글이 조회 창보다 오래된 방은 히스토리를 요청하지 않는다(호출량 절약).
            if dialog.date and to_utc(dialog.date) < since:
                continue

            scanned += 1
            title = getattr(entity, "title", None) or getattr(entity, "username", "") or "이름 없는 채널"
            async for message in client.iter_messages(entity, limit=per_chat_limit):
                posted = to_utc(message.date)
                if posted and posted < since:
                    break  # 최신순이라 창을 벗어나면 그 방은 끝
                text = (message.message or "").strip()
                if not text:
                    continue
                items.append(
                    Item(
                        uid=f"{getattr(entity, 'id', '?')}:{message.id}",
                        title=first_line(text),
                        url=_message_url(entity, message.id),
                        body=text,
                        published_at=posted,
                        origin=str(title),
                    )
                )
        print(f"  · 새 글이 있는 방 {scanned}개 확인", flush=True)
        return items
    finally:
        await client.disconnect()


def collect_telegram_account(source: dict) -> list[Item]:
    """내 계정이 들어가 있는 모든 채널에서 조회 창 안의 글을 모은다.

    채널 목록을 관리할 필요가 없는 대신 계정 세션이 필요하다. 세션 파일은 계정 그 자체나
    다름없으므로 저장소에 올리지 않는다(.gitignore). 자세한 준비 절차는 README를 볼 것.
    """
    try:
        import telethon  # noqa: F401
    except ImportError as exc:  # pragma: no cover - 환경 의존
        raise RuntimeError(
            "telegram_account 어댑터에는 telethon이 필요합니다: pip install telethon"
        ) from exc

    hours = int(source.get("lookback_hours") or 0) or 24
    # 워크플로가 늦게 돌거나 한 번 걸러도 글을 놓치지 않게 조회 창을 조금 넉넉히 잡는다.
    since = datetime.now(timezone.utc) - timedelta(hours=hours + 1)
    return asyncio.run(_scan_account(source, since))


COLLECTORS = {
    "telegram": collect_telegram,
    "telegram_account": collect_telegram_account,
    "rss": collect_rss,
    "web": collect_web,
}


def collect(source: dict) -> list[Item]:
    kind = str(source.get("type", "")).lower()
    if kind not in COLLECTORS:
        raise ValueError(f"알 수 없는 소스 종류: {source.get('type')!r} (가능: {', '.join(COLLECTORS)})")
    return COLLECTORS[kind](source)
