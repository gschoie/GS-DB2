"""보수적인 규칙 기반 1차 파서. 원문은 항상 DB에 별도로 보존한다."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

# 파싱 규칙을 바꿀 때마다 +1 한다. CI가 이 값을 DB의 PRAGMA user_version과 비교해
# 파서가 바뀐 첫 수집 런에서만 전체 재분류를 자동으로 돌린다(rebuild_parsed_data.py --if-parser-changed).
PARSER_VERSION = 7

# 뉴스 공유 글의 기사 제목은 「제목」 꼴로 감싸 두는 게 채널 관례다. ❗️ 줄은
# AI가 뽑은 핵심 문구지 제목이 아니므로 제목 후보에서 뺀다.
CORNER_TITLE_RE = re.compile(r"「([^」\n]{4,180})」")


# 텔레그램에서 URL 뒤에 공백 없이 붙인 한글 코멘트까지 링크로 먹지 않는다.
URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#@!$&'*+,;=%-]+")
PRICE_RE = re.compile(r"(?:목표주가|적정주가|TP)\s*[:：]?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(만)?\s*원?", re.I)
PREVIOUS_PRICE_RE = re.compile(r"(?:기존|종전)\s*(?:목표주가|적정주가|TP)?\s*[:：]?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(만)?\s*원?", re.I)
OPINION_RE = re.compile(r"(?:투자의견|의견)\s*[:：]?\s*([A-Za-z가-힣 ]{2,16})", re.I)
REPORT_WORDS = ("목표주가", "투자의견", "리포트", "보고서", "기업분석", "산업분석")
REPORT_MARKERS = ("컴플라이언스 승인을 득한 보고서", "컴플 보고서")
DAILY_NEWS_RE = re.compile(r"\d{1,2}/\d{1,2}\([^)]*\)\s*데일리뉴스")
WEEKLY_RE = re.compile(r"주시\s*뉴스")
INDUSTRIES = ("조선", "방산", "기계", "해양", "LNG", "가스선", "컨테이너", "탱커")
KNOWN_COMPANIES = (
    "HD한국조선해양", "HD현대중공업", "HD현대미포", "HD현대", "한화오션",
    "한화에어로스페이스", "한화시스템", "현대로템", "한국항공우주",
    "LIG넥스원", "LIG D&A", "풍산", "HJ중공업", "K조선", "HD현대마린엔진", "현대마린엔진",
    "HD건설기계", "삼성중공업", "두산에너빌리티", "제이오션중공업", "대한항공",
    "두산밥캣", "HD현대건설기계", "HD현대인프라코어",
    "한국카본", "STX엔진", "한화엔진", "HD현대마린솔루션", "SNT다이내믹스",
    "대한조선", "엠앤씨솔루션", "삼양컴텍", "쎄트렉아이", "동성화인텍",
    "현대힘스", "케이프", "성광벤드", "태광", "화인베스틸", "한라IMS",
    "오리엔탈정공", "하이록코리아", "대동", "웨이브일렉트로닉스", "에스엔시스",
    "세진중공업", "HD현대일렉트릭", "SK오션플랜트", "한화필리조선",
)

# 드롭다운·기업명 라벨·Most Mentioned에 노출할 '실제 상장사' 화이트리스트.
# 여기 없는 태그(티커번호·기사문구 등 파서 폴백 노이즈)는 화면에서 '기업 미확인'으로 처리한다.
# 커버리지가 늘면 이 목록에 한 줄씩 추가하면 된다("+알파").
APPROVED_COMPANIES = [
    # 커버리지 코어
    "HD한국조선해양", "HD현대중공업", "HD현대마린엔진", "HD현대마린솔루션",
    "삼성중공업", "한화오션", "한화엔진", "대한조선", "한국카본",
    "한화에어로스페이스", "한화시스템", "한국항공우주", "LIG D&A", "현대로템",
    "두산밥캣", "HD건설기계", "HD현대건설기계",
    # 알파 (상장 피어)
    "LIG넥스원", "풍산", "대한항공", "두산에너빌리티", "HD현대미포",
    "HD현대인프라코어", "STX엔진", "SNT다이내믹스", "HJ중공업", "HD현대",
    "엠앤씨솔루션", "삼양컴텍", "쎄트렉아이", "동성화인텍", "현대힘스",
    "케이프", "성광벤드", "태광", "화인베스틸", "한라IMS", "오리엔탈정공",
    "하이록코리아", "대동", "웨이브일렉트로닉스", "에스엔시스",
    "세진중공업", "HD현대일렉트릭", "SK오션플랜트",
    # 비상장 자회사지만 별도 태그로 노출한다 (미국 필라델피아 조선소, 한화시스템 산하)
    "한화필리조선",
]
COMPANY_ALIASES = {
    "LIG디펜스앤에어로스페이스": "LIG D&A",
    "LIG디앤에이": "LIG D&A",
    "KAI": "한국항공우주",
    "KF-21": "한국항공우주",
    "KF21": "한국항공우주",
    "보라매": "한국항공우주",
    "삼성重": "삼성중공업",
    "고스트로보틱스": "LIG D&A",  # LIG D&A 자회사 (사족보행 로봇 비전 60)
    # 개명 전 구사명 → 현재 상장사명. 과거 보고서(하이·한투 시절) 아카이브를
    # 현재 기업 필터로 묶기 위한 매핑이다.
    "현대미포": "HD현대미포",          # 현대미포조선 포함
    "현대중공업": "HD현대중공업",
    "한국조선해양": "HD한국조선해양",
    "대우조선해양": "한화오션",
    "현대일렉트릭": "HD현대일렉트릭",
    "두산인프라코어": "HD현대인프라코어",
    "현대건설기계": "HD현대건설기계",
    "두산엔진": "한화엔진",
    "HSD엔진": "한화엔진",
    "한진중공업": "HJ중공업",
    "삼강엠앤티": "SK오션플랜트",
    "두산중공업": "두산에너빌리티",
    "엠엔씨솔루션": "엠앤씨솔루션",    # 오탈자 표기 통일
    "필리조선": "한화필리조선",        # "필리조선소" 표기 포함
    "필리 조선소": "한화필리조선",
    "Philly Shipyard": "한화필리조선",
}
# 비상장 자회사 → 상장 모회사. 자회사가 태깅되면 모회사도 함께 행에 남긴다.
SUBSIDIARY_PARENTS = {"한화필리조선": "한화시스템"}
# 외신·영문 기사용: 무기체계 코드로 한국 상장사를 역추적한다.
# K2·K9처럼 짧은 코드는 앞뒤가 영숫자가 아닐 때만 매칭해 오탐(K21, AK9, K239 등)을 막되,
# K9MH·K2PL 같은 변형 접미사(대문자 1~3자 + 숫자)는 같은 체계로 인정한다.
WEAPON_SYSTEM_ALIASES = {
    # 항공기 (KAI)
    r"KF-?21[A-Z]{0,2}": "한국항공우주",
    r"FA-?50[A-Z]{0,2}": "한국항공우주",
    r"T-?50[A-Z]{0,2}": "한국항공우주",
    r"수리온|Surion": "한국항공우주",
    # 지상 화력 (한화에어로스페이스: K9 자주포 / 현대로템: K2 전차)
    r"K9(?:[A-Z]{1,3}\d?)?": "한화에어로스페이스",
    r"K2(?:[A-Z]{1,3}\d?)?": "현대로템",
    r"흑표": "현대로템",
    # 다연장 로켓 천무 (K239·Chunmoo·Homar) 및 MLRS
    r"K239": "한화에어로스페이스",
    r"Chunmoo|천무|Homar": "한화에어로스페이스",
    r"MLRS": "한화에어로스페이스",
    r"MRLS": "한화에어로스페이스",
    r"Redback|레드백": "한화에어로스페이스",
    # 방공 천궁 / M-SAM
    r"M-?SAM": "LIG D&A",
    r"천궁|Cheongung": "LIG D&A",
}
# 외신에 나오는 영문 사명 → 한국 상장사.
ENGLISH_COMPANY_ALIASES = {
    "hanwha aerospace": "한화에어로스페이스",
    "hanwha systems": "한화시스템",
    "hanwha ocean": "한화오션",
    "daewoo shipbuilding": "한화오션",
    "dsme": "한화오션",
    "korea aerospace industries": "한국항공우주",
    "hyundai rotem": "현대로템",
    "lig nex1": "LIG넥스원",
    "ghost robotics": "LIG D&A",
    "samsung heavy": "삼성중공업",
    "hyundai heavy": "HD현대중공업",
    "poongsan": "풍산",
    "korea shipbuilding": "HD한국조선해양",
}
CHANNEL_SIGNATURE_RE = re.compile(
    r"(?:조선\s*/\s*기계\s*/\s*방산.*최광식|최광식.*(?:DAOL|다올).*투자증권)", re.I
)
PUBLISHER_RE = re.compile(r"(?:출처|Source)\s*[:：]\s*\[?([^\]\n]+)", re.I)
PUBLISHER_DOMAINS = {
    "yna.co.kr": "연합뉴스", "yonhapnewstv.co.kr": "연합뉴스TV", "news1.kr": "뉴스1",
    "newsis.com": "뉴시스", "theguru.co.kr": "더구루",
    "hankyung.com": "한국경제", "mk.co.kr": "매일경제", "sedaily.com": "서울경제",
    "edaily.co.kr": "이데일리", "mt.co.kr": "머니투데이", "fnnews.com": "파이낸셜뉴스",
    "chosun.com": "조선일보", "biz.chosun.com": "조선비즈", "joongang.co.kr": "중앙일보",
    "donga.com": "동아일보", "hani.co.kr": "한겨레", "khan.co.kr": "경향신문",
    "hankookilbo.com": "한국일보", "seoul.co.kr": "서울신문", "kmib.co.kr": "국민일보",
    "munhwa.com": "문화일보", "segye.com": "세계일보", "kukinews.com": "쿠키뉴스",
    "asiae.co.kr": "아시아경제", "heraldcorp.com": "헤럴드경제", "ajunews.com": "아주경제",
    "etnews.com": "전자신문", "dt.co.kr": "디지털타임스", "zdnet.co.kr": "ZDNet Korea",
    "inews24.com": "아이뉴스24", "businesspost.co.kr": "비즈니스포스트", "thebell.co.kr": "더벨",
    "biz.heraldcorp.com": "헤럴드경제", "wowtv.co.kr": "한국경제TV", "newspim.com": "뉴스핌",
    "moneys.co.kr": "머니S", "dailian.co.kr": "데일리안", "pinpointnews.co.kr": "핀포인트뉴스",
    "g-enews.com": "글로벌이코노믹", "ekn.kr": "에너지경제", "e2news.com": "이투뉴스",
    "sisajournal.com": "시사저널", "ceoscoredaily.com": "CEO스코어데일리",
    "econovill.com": "이코노믹리뷰", "econonews.co.kr": "이코노뉴스",
    "eurasiantimes.com": "EurAsian Times", "reuters.com": "Reuters",
    "tradewinds.com": "TradeWinds", "tradewindsnews.com": "TradeWinds",
    "upstreamonline.com": "Upstream", "defensenews.com": "Defense News",
    "janes.com": "Janes", "navalnews.com": "Naval News", "bloomberg.com": "Bloomberg",
}


def is_channel_signature(value: str | None) -> bool:
    return bool(value and CHANNEL_SIGNATURE_RE.search(value))


HANGUL_RE = re.compile(r"[가-힣]")
# 줄 앞의 이모지·기호 장식(✈️ 🚀 > 등). 단어문자·한글·대괄호류가 나오면 멈춘다.
LEADING_DECOR_RE = re.compile(r"^[^\w가-힣\[「]*")


def bilingual_headline_pair(text: str) -> tuple[str, str] | None:
    """외신 공유의 '영어 원제 + 한국어 번역' 헤드라인 쌍을 찾는다.

    형식: 같은 이모지 프리픽스를 단 연속 두 줄(첫 줄 영어, 둘째 줄 한국어 번역).
    이때 제목은 한국어 번역, '내 코멘트'는 영어 원제가 된다.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2 or URL_RE.search(lines[0]) or URL_RE.search(lines[1]):
        return None
    prefix_first = LEADING_DECOR_RE.match(lines[0]).group(0).strip()
    prefix_second = LEADING_DECOR_RE.match(lines[1]).group(0).strip()
    english = LEADING_DECOR_RE.sub("", lines[0]).strip()
    korean = LEADING_DECOR_RE.sub("", lines[1]).strip()
    if not english or not korean or not prefix_first or prefix_first != prefix_second:
        return None
    if HANGUL_RE.search(english) or not HANGUL_RE.search(korean):
        return None
    return english, korean


def unwrap_google_redirect(url: str) -> str:
    """구글 앱 공유가 링크를 google.com/search?q=<원래URL>(또는 /url?q=)로 감싼 것을 벗긴다.

    감싼 채 두면 보강이 구글 페이지를 열어 제목이 'Google Search'가 되고,
    구글로 감싸진 t.me 셀프링크는 is_article_url 필터도 통과해버린다.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    if (host == "google.com" or host.endswith(".google.com")) and parsed.path in ("/search", "/url"):
        inner = parse_qs(parsed.query).get("q", [""])[0]
        if inner.startswith(("http://", "https://")):
            return inner
    return url


def is_article_url(url: str) -> bool:
    """뉴스 행이 되면 안 되는 부속 링크를 거른다.

    - t.me/telegram.me: 메시지 서명의 채널 셀프링크. 행으로 만들면 같은 뉴스가 중복되고,
      제목 보강이 t.me 페이지 제목(=채널명 'DAOL 조선/기계/방산 | 최광식')을 물어온다.
    - finance.naver.com/item/…: 실적속보 포워딩에 딸려오는 Npay 증권 종목 링크.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold().removeprefix("www.").removeprefix("m.")
    if host in ("t.me", "telegram.me"):
        return False
    if host == "finance.naver.com" and parsed.path.startswith("/item/"):
        return False
    return True


def extract_publisher(text: str, url: str | None = None) -> str | None:
    match = PUBLISHER_RE.search(text)
    if match:
        return match.group(1).strip(" *`[]")[:80]
    if not url:
        return None
    host = (urlparse(url).hostname or "").casefold().removeprefix("www.").removeprefix("m.")
    for domain, publisher in PUBLISHER_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return publisher
    return host or None


def _first_line(text: str) -> str:
    for line in text.splitlines():
        clean = line.strip(" -•>\t")
        if clean and not clean.startswith("http") and not is_channel_signature(clean):
            return clean[:180]
    return "제목 미확인"


def _price(match: re.Match[str] | None) -> int | None:
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    if match.group(2):  # "적정주가 104만원", "TP 3.5만원" 같은 만원 단위 표기
        value *= 10_000
    # 커버리지 상장사 TP가 1,000원 밑일 수 없다 — 단위가 깨진 오파싱은 버린다.
    return int(value) if value >= 1_000 else None


def _dedupe_companies(found: list[str]) -> list[str]:
    # 긴 정식 명칭을 우선해 HD현대와 HD현대중공업의 중복을 피한다.
    ordered = sorted(dict.fromkeys(found), key=len, reverse=True)
    selected: list[str] = []
    for name in ordered:
        if not any(name in longer for longer in selected):
            selected.append(name)
    return selected


def _with_parents(names: list[str]) -> list[str]:
    for name in list(names):
        parent = SUBSIDIARY_PARENTS.get(name)
        if parent and parent not in names:
            names.append(parent)
    return names


def identify_companies(text: str) -> list[str]:
    """한국 정식사명·별칭으로 먼저 식별하고, 실패하면 외신 무기체계/영문 사명으로 역추적한다.

    대괄호·해시태그 같은 노이즈 폴백은 쓰지 않으므로 제목뿐 아니라 본문에 적용해도 안전하다.
    """
    lowered = text.casefold()
    found = [name for name in KNOWN_COMPANIES if name.casefold() in lowered]
    found.extend(company for alias, company in COMPANY_ALIASES.items() if alias.casefold() in lowered)
    if found:
        return _with_parents(_dedupe_companies(found))
    # 외신 폴백: 한국 사명이 안 잡힐 때만 무기체계/영문 사명으로 분류한다.
    foreign = [company for phrase, company in ENGLISH_COMPANY_ALIASES.items() if phrase in lowered]
    for pattern, company in WEAPON_SYSTEM_ALIASES.items():
        if re.search(rf"(?<![A-Za-z0-9])(?:{pattern})(?![A-Za-z0-9])", text, re.I):
            foreign.append(company)
    return _with_parents(_dedupe_companies(foreign))


def extract_companies(text: str) -> list[str]:
    identified = identify_companies(text)
    if identified:
        return identified
    patterns = (
        r"\[([가-힣A-Za-z0-9&. ]{2,30})\]",
        r"(?:기업|종목)\s*[:：]\s*([가-힣A-Za-z0-9&. ]{2,30})",
        r"#([가-힣A-Za-z][가-힣A-Za-z0-9&.]*)",
    )
    for pattern in patterns:
        matches = [value.strip() for value in re.findall(pattern, text)]
        matches = [value for value in matches
                   if not any(skip in value for skip in (
                       "투자증권", "데일리뉴스", "다올 시황", "선박기계", "위클리", "주시뉴스", "주시 뉴스"
                   ))
                   and value not in INDUSTRIES and value not in ("조선업", "방위산업")]
        if matches:
            return list(dict.fromkeys(matches))
    return []


def _company(text: str) -> str | None:
    companies = extract_companies(text)
    return ", ".join(companies) if companies else None


# 묶음 보고서(산업 + 기업 리뷰 N개)의 기업 섹션 헤더: `▶️ 한화엔진 「부제」`
SECTION_HEADER_RE = re.compile(r"^\s*[▶►]️?\s*(.+?)\s*$", re.M)
SECTION_COMPANY_RE = re.compile(r"^([가-힣A-Za-z0-9&. ]{2,30}?)\s*(「[^」]+」)")


def canonical_company(name: str) -> str | None:
    name = name.strip()
    if name in KNOWN_COMPANIES:
        return name
    return COMPANY_ALIASES.get(name)


def _infer_change(target: int | None, previous: int | None,
                  source: str, matches: list[re.Match[str]]) -> str:
    if target and previous:
        return "상향" if target > previous else "하향" if target < previous else "유지"
    if not target:
        return "미확인"
    # `TP: 91,000원으로 19% 하향`, `TP: 144,000원 견지`처럼 TP 줄의 서술어로 방향을 읽는다.
    line_end = source.find("\n", matches[-1].end())
    tp_line = source[matches[-1].start():line_end if line_end != -1 else len(source)]
    if "상향" in tp_line:
        return "상향"
    if "하향" in tp_line:
        return "하향"
    if any(word in tp_line for word in ("견지", "유지", "동결")):
        return "유지"
    return "신규/미확인"


def split_company_sections(text: str) -> list[dict]:
    """`▶️ 기업명 「부제」` 헤더 기준으로 묶음 보고서를 기업별 섹션으로 나눈다.

    PDF를 열지 않아도 텔레그램 본문만으로 기업분석 분리가 가능하도록
    섹션 안의 TP·방향·투자의견까지 같이 읽는다. 섹션이 2개 이상일 때만
    묶음으로 본다(1개면 사실상 단일 기업 보고서라 분리 이득이 없다).
    """
    headers = list(SECTION_HEADER_RE.finditer(text))
    sections = []
    for index, header in enumerate(headers):
        title_match = SECTION_COMPANY_RE.match(header.group(1))
        company = canonical_company(title_match.group(1)) if title_match else None
        if not company:
            continue
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        body = text[header.start():end]
        footer = re.search(r"^-{5,}", body, re.M)
        if footer:
            body = body[:footer.start()]
        target_matches = list(PRICE_RE.finditer(body))
        target = _price(target_matches[-1]) if target_matches else None
        previous = _price(PREVIOUS_PRICE_RE.search(body))
        opinion = OPINION_RE.search(body)
        sections.append({
            "company": company,
            "title": f"{company} {title_match.group(2)}",
            "opinion": opinion.group(1).strip() if opinion else None,
            "target_price": target, "previous_target_price": previous,
            "target_change": _infer_change(target, previous, body, target_matches),
        })
    return sections if len(sections) >= 2 else []


def classify(text: str) -> str:
    if any(marker in text for marker in REPORT_MARKERS):
        return "report"
    if DAILY_NEWS_RE.search(text):
        return "news"
    score = sum(word.lower() in text.lower() for word in REPORT_WORDS)
    if score >= 2 or PRICE_RE.search(text):
        return "report"
    if URL_RE.search(text):
        return "news"
    return "unclassified"


def parse_report(text: str) -> dict:
    sections = split_company_sections(text)
    target_matches = list(PRICE_RE.finditer(text))
    # "기존 목표주가 → 목표주가" 형식에서는 마지막 값을 현재 TP로 본다.
    target = _price(target_matches[-1]) if target_matches else None
    previous = _price(PREVIOUS_PRICE_RE.search(text))
    change = _infer_change(target, previous, text, target_matches)
    opinion = OPINION_RE.search(text)
    urls = URL_RE.findall(text)
    companies = extract_companies(text)
    company = ", ".join(companies) if companies else None
    confidence = min(0.95, 0.45 + (0.2 if company else 0) + (0.2 if target else 0))
    lowered = text.casefold()
    if "한국투자증권" in text:
        firm = "한국투자증권"
    elif "하이투자증권" in text or "hi투자증권" in lowered:
        firm = "하이투자증권"
    elif any(word in lowered for word in ("다올투자증권", "daol투자증권", "ktb투자증권")):
        firm = "다올투자증권"
    else:
        firm = None
    analyst = "최광식" if "최광식" in text else None
    if WEEKLY_RE.search(text):
        report_type = "위클리"
        sections = []
        if "한국투자증권" in text or "kiss" in lowered:
            weekly_folder = "한투시절"
        elif "하이투자증권" in text or "hi투자증권" in lowered:
            weekly_folder = "하이투자증권시절"
        else:
            weekly_folder = "다올선박"
    else:
        weekly_folder = None
        title_companies = identify_companies(_first_line(text))
        if sections:
            # 기업 섹션이 여럿이면 산업 엄브렐러로 두고, 기업별 행은 섹션이 맡는다.
            report_type = "산업분석"
        elif len(title_companies) == 1:
            # 제목(해시태그)에 기업이 하나면 본문에 피어가 언급돼도 기업분석이다.
            report_type = "기업분석"
        else:
            report_type = "산업분석" if (len(companies) > 1 or not company and any(word in text for word in ("조선", "방산", "기계"))) else "기업분석"
    if sections:
        # 엄브렐러 행에 서로 다른 기업의 TP가 섞여 남지 않게 비운다. TP는 섹션 행이 가진다.
        target = previous = None
        change = "미확인"
        confidence = 0.9
    return {
        "title": _first_line(text), "company_name": company,
        "companies": companies, "sections": sections,
        "securities_firm": firm, "analyst": analyst, "report_type": report_type,
        "weekly_folder": weekly_folder,
        "opinion": opinion.group(1).strip() if opinion else None,
        "target_price": target, "previous_target_price": previous,
        "target_change": change, "original_url": urls[0] if urls else None,
        "confidence": confidence, "needs_review": int(confidence < 0.8),
    }


def parse_news(text: str) -> dict:
    urls = [url for url in map(unwrap_google_redirect, URL_RE.findall(text)) if is_article_url(url)]
    article_url = urls[0] if urls else None
    pair = bilingual_headline_pair(text)
    headline = pair[1] if pair else _first_line(text)
    corner = CORNER_TITLE_RE.search(headline or "")
    if corner:
        headline = corner.group(1).strip()
    companies = extract_companies(text)
    company = ", ".join(companies) if companies else None
    event_map = {
        "실적": ("실적", "영업이익", "매출"), "수주": ("수주", "계약"),
        "투자": ("투자", "증설"), "정책": ("정책", "정부", "규제"),
        "인수합병": ("인수", "합병", "M&A"), "자금조달": ("유상증자", "회사채", "자금조달"),
    }
    event_type = next((kind for kind, words in event_map.items() if any(w in text for w in words)), "기타")
    confidence = 0.75 if company and urls else 0.55
    return {
        "title": headline, "company_name": company, "companies": companies,
        "publisher": extract_publisher(text, article_url),
        "article_url": article_url, "event_type": event_type,
        "summary": headline, "confidence": confidence,
        "needs_review": int(confidence < 0.8),
    }


def parse_news_items(text: str) -> list[dict]:
    """데일리뉴스 묶음에서 제목/URL 쌍을 분리한다. 단독 기사도 한 항목으로 반환한다."""
    lines = [line.strip(" \t•>") for line in text.splitlines()]
    items = []
    pair = bilingual_headline_pair(text)
    current_industry = None
    for index, line in enumerate(lines):
        if line in INDUSTRIES:
            current_industry = line
            continue
        urls = list(dict.fromkeys(
            url for url in map(unwrap_google_redirect, URL_RE.findall(line)) if is_article_url(url)
        ))
        if not urls:
            continue
        title = None
        candidates = []
        for previous in range(index - 1, max(-1, index - 10), -1):
            candidate = lines[previous]
            if (candidate and not URL_RE.search(candidate) and candidate not in INDUSTRIES
                    and not DAILY_NEWS_RE.search(candidate) and "다올투자증권" not in candidate
                    and not is_channel_signature(candidate)
                    and not candidate.startswith(("출처:", "출처 ", "* 위 내용", "위 내용은", "❗", "URL:", "URL "))):
                candidates.append(candidate)
        corner = next((match.group(1).strip() for candidate in candidates
                       if (match := CORNER_TITLE_RE.search(candidate))), None)
        if corner is None:
            # 「제목」이 URL보다 멀리(글 맨 위) 있는 단건 공유 글: 메시지 전체에서 첫 「…」를 쓴다.
            message_corner = CORNER_TITLE_RE.search(text)
            corner = message_corner.group(1).strip() if message_corner else None
        bracketed = next((candidate for candidate in candidates
                          if candidate.startswith("[") and candidate.endswith("]")
                          and candidate not in ("[TradeWinds]", "[Upstream]")), None)
        title = corner or bracketed or (candidates[0] if candidates else None)
        if title is None:
            for following in range(index + 1, min(len(lines), index + 4)):
                candidate = lines[following]
                if candidate and not URL_RE.search(candidate):
                    title = candidate
                    break
        if pair:
            # 외신 공유(영어 원제 + 한국어 번역 쌍): 제목은 한국어 번역이 맡는다.
            title = pair[1]
        title = title or "기사 제목 미확인"
        for url in urls:
            parsed = parse_news(f"{title}\n{url}")
            parsed["industry"] = current_industry
            parsed["publisher"] = extract_publisher(text, url)
            companies = extract_companies("\n".join(pair) if pair else title)
            parsed["companies"] = companies
            parsed["company_name"] = ", ".join(companies) if companies else None
            items.append(parsed)
    if not items:
        parsed = parse_news(text)
        parsed["industry"] = next((name for name in INDUSTRIES if name in text), None)
        items.append(parsed)
    # 단건 공유 글은 제목(「…」)에 기업명이 없는 경우가 많다 — 본문 전체에서 다시 찾는다.
    # (묶음 데일리뉴스는 항목 간 오염을 막기 위해 제목 범위 추출을 유지)
    if len(items) == 1 and not items[0]["companies"]:
        companies = extract_companies(text)
        if companies:
            items[0]["companies"] = companies
            items[0]["company_name"] = ", ".join(companies)
    # 같은 URL이 본문에 반복된 경우 한 번만 저장한다.
    unique = []
    seen = set()
    for item in items:
        key = item["article_url"] or item["title"]
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique
