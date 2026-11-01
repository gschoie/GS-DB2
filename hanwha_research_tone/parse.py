"""한화투자증권 리서치 게시판 제목·요약·PDF 표지에서 구조 정보를 뽑는 순수 함수들.
네트워크·외부 패키지 없음 — 테스트가 가볍다.

제목 꼴(게시판 실측, 2026-10):
  [화장품] 에이피알[278470/Buy] 4분기부터 다시 서프라이즈 일텐데요…      ← 기업분석
  [인터넷/게임] [2027년 산업전망] 확장에서 결실로                          ← 산업분석
  [미국주식] [Earnings Flash] Amazon,com, Inc.                           ← 해외주식분석
  [경제분석] BOJ, 매파적 동결로 추가 인상 예고                             ← 국내외 경제
  [주간 파생시황] 2026년 10월 26일~29일                                    ← 주식전략
"""
import re

OPINIONS = {'buy': 'Buy', 'hold': 'Hold', 'sell': 'Sell', 'neutral': 'Hold', 'outperform': 'Buy',
            'underperform': 'Sell', 'overweight': 'Overweight', 'underweight': 'Underweight',
            '매수': 'Buy', '중립': 'Hold', '매도': 'Sell', '비중확대': 'Overweight', '비중축소': 'Underweight',
            'n/r': 'N/R', 'nr': 'N/R', 'not rated': 'N/R'}

# 투자전략 게시판(1003)의 구분명 — 톤 보드에서는 '전략·경제'로 묶는다.
STRATEGY_KINDS = {'주식전략', '국내외 경제', '채권전략', '채권분석', '파생상품', '퀀트', '자산배분', '투자전략',
                  '시황', '경제분석', '주간 파생시황', '글로벌 전략', 'ETF', '크레딧'}


def clean(s):
    return re.sub(r'\s+', ' ', s or '').strip()


def norm_opinion(raw):
    k = clean(raw).lower().replace(' ', '')
    for key, val in OPINIONS.items():
        if k == key.replace(' ', ''):
            return val
    return clean(raw)


def parse_title(title):
    """제목 → {sector, company, code, opinion, subject, is_overseas}.
    섹터는 선두 대괄호, 기업은 '이름[코드/의견]' 꼴에서. 못 잡으면 빈 문자열."""
    t = clean(title)
    out = {'sector': '', 'company': '', 'code': '', 'opinion': '', 'subject': t, 'is_overseas': False}
    m = re.match(r'^\[([^\]]{1,30})\]\s*', t)
    rest = t
    if m:
        out['sector'] = clean(m.group(1))
        rest = t[m.end():]
    out['is_overseas'] = bool(re.search(r'미국주식|해외주식|중국주식|일본주식|글로벌주식|해외기업', out['sector']))
    # 기업분석: '에이피알[278470/Buy]' · '삼성전자 [005930/Buy]' · 'LIG넥스원[079550/Buy]'
    cm = re.search(r'([가-힣A-Za-z0-9&.\-·\s]{1,40}?)\s*\[\s*([0-9]{6}|[A-Z]{1,6})\s*/\s*([^\]/]{1,20})\]', rest)
    if cm:
        out['company'] = clean(cm.group(1)).strip('-·')
        out['code'] = cm.group(2)
        out['opinion'] = norm_opinion(cm.group(3))
        out['subject'] = clean(rest[cm.end():].lstrip(' -:–—')) or out['company']
    else:
        # 의견 없이 코드만: '에이피알(278470)'
        pm = re.search(r'([가-힣A-Za-z0-9&.\-·\s]{1,40}?)\s*[\[(]\s*([0-9]{6})\s*[\])]', rest)
        if pm:
            out['company'] = clean(pm.group(1)).strip('-·')
            out['code'] = pm.group(2)
            out['subject'] = clean(rest[pm.end():].lstrip(' -:–—')) or out['company']
        else:
            out['subject'] = clean(rest) or t
    return out


def sector_from_record(rec):
    """게시판 레코드의 보드 섹터: 제목 대괄호 > 구분(산업분석 등). 전략 보드는 '전략·경제'."""
    kind = rec.get('kind') or ''
    if rec.get('board') == '1003' or kind in STRATEGY_KINDS:
        return '전략·경제'
    return canon_sector(rec.get('title_sector')) or kind or '기타'


# ── 본문에서 목표주가·투자의견 ───────────────────────────────────────────
# 숫자 꼴: '180,000원' · '800,000원(-10,000원)' · '30만 원' · '5.1만원' · '1만 2천 원' · '8,300원'
_NUM = r'(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+(?:\.[0-9]+)?\s*만(?:\s*[0-9]+\s*천)?|[0-9]{4,7})\s*원?'
_DIR = r'(상향|하향|유지|신규|인상|인하|상향\s*조정|하향\s*조정)'
_TP_PAT = re.compile(
    r'(?:목표주가|적정주가|목표가|Target\s*Price|TP)\s*(?:는|를|은|을|도|[:：])?\s*(?:\(?' + _DIR + r'\)?\s*[:：]?\s*)?'
    r'(' + _NUM + r')(?:\s*\([^)]{0,20}\))?\s*(?:으로|로|을|를|에서|은|는)?\s*(?:\(?' + _DIR + r'\)?)?', re.I)
_PRIOR_PAT = re.compile(r'(?:기존|이전|직전|종전)\s*(?:목표주가|적정주가|TP)?\s*[:：]?\s*(' + _NUM + r')'
                        r'|(' + _NUM + r')\s*(?:→|->|에서)\s*(' + _NUM + r')')
_OP_PAT = re.compile(r'(?:투자의견|Rating)\s*(?:은|는|을|를|[:：])?\s*(Buy|Hold|Sell|Neutral|Overweight|Underweight|매수|중립|매도|N/?R)'
                     r'(?:\s*(?:을|를|은|는|도)?\s*\(?\s*(상향|하향|유지|신규)\s*\)?)?', re.I)
_DIR_NORM = {'인상': '상향', '인하': '하향'}


def _dir(x):
    x = re.sub(r'\s*조정', '', x or '')
    return _DIR_NORM.get(x, x)


def _num(s):
    """'180,000원'·'30만 원'·'1만 2천 원'·'5.1만원' → 원 단위 정수. 못 읽으면 None."""
    t = str(s or '').replace(',', '').replace('원', '').replace(' ', '')
    m = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)만(?:([0-9]+)천)?', t)
    try:
        if m:
            return int(round(float(m.group(1)) * 10000 + (int(m.group(2)) * 1000 if m.group(2) else 0)))
        return int(t)
    except (TypeError, ValueError):
        return None


def extract_cover(text, max_chars=6000):
    """PDF 첫 페이지 텍스트에서 투자의견·적정주가·직전가·방향. 못 찾으면 None 값."""
    head = (text or '')[:max_chars]
    out = {'opinion': '', 'opinion_change': '', 'tp': None, 'tp_prior': None, 'tp_change': ''}
    om = _OP_PAT.search(head)
    if om:
        out['opinion'] = norm_opinion(om.group(1))
        out['opinion_change'] = _dir(om.group(2) or '')
    tm = _TP_PAT.search(head)
    if tm:
        val = _num(tm.group(2))
        if val and 100 <= val <= 50_000_000:
            out['tp'] = val
            out['tp_change'] = _dir(tm.group(1) or tm.group(3) or '')
    # 직전가는 목표주가 문장 근처에서만 찾는다 — 멀리 있는 BPS·주가 숫자를 직전가로 오인하지 않게
    win = head[max(0, tm.start() - 80): tm.end() + 160] if tm else ''
    pm = _PRIOR_PAT.search(win) if win else None
    if pm:
        if pm.group(1):
            out['tp_prior'] = _num(pm.group(1))
        elif pm.group(2) and pm.group(3):
            # 'A원 → B원' 꼴: 화살표가 있으면 B가 새 값이다(앞의 TP 패턴이 A를 잡았어도 뒤집는다)
            a, b = _num(pm.group(2)), _num(pm.group(3))
            if out['tp'] in (None, a, b):
                out['tp'], out['tp_prior'] = b, a
                if not out['tp_change'] or out['tp_change'] == '유지':
                    out['tp_change'] = ''
    if out['tp'] and out['tp_prior'] and not (0.2 < out['tp_prior'] / out['tp'] < 5):
        out['tp_prior'] = None        # 5배 넘게 차이 나는 '직전가'는 다른 숫자다
    if out['tp'] and out['tp_prior']:
        if out['tp_prior'] == out['tp']:
            out['tp_change'] = out['tp_change'] or '유지'
        elif not out['tp_change']:
            out['tp_change'] = '상향' if out['tp'] > out['tp_prior'] else '하향'
    return out


# ── 상세 본문 정리 ──────────────────────────────────────────────────────────
# researchCont 뒤에 붙는 안내문·면책·푸터 스크립트가 본문에 섞여 들어온다(첫 수집 실측: 본문 2.3KB 뒤에
# 9KB 의 JS). 경계 문구에서 자르고 스크립트 줄을 버린다.
_BODY_STOPS = ['보다 자세한 내용은 로그인', '이 자료는 당사 리서치센터', 'function goLoginContent', 'Acrobat Reader',
               '아크로밧리더', '언제든지 전화주세요', '고객지원센터 080']
_JS_LINE = re.compile(r'^\s*(?:\$\(|//|/\*|\*/|var\s|function\s|if\s*\(|\}|\{|\);|\]\]>|<!\[CDATA|return\b|location\.|window\.|document\.)')


def clean_body(text):
    t = text or ''
    cut = min([i for i in (t.find(p) for p in _BODY_STOPS) if i >= 0] or [len(t)])
    t = t[:cut]
    # '종목명' 표(관련 종목 나열)가 본문 끝에 붙는 경우도 자른다 — 본문 안의 '종목명' 낱말은 줄 단위로만 본다
    lines = []
    for ln in t.split('\n'):
        ln = ln.strip()
        if not ln or _JS_LINE.match(ln):
            continue
        if ln == '종목명':
            break
        lines.append(ln)
    out = '\n'.join(lines).strip()
    return out if len(re.findall(r'[가-힣]', out)) >= 20 else ''


# ── 섹터 표준화 ─────────────────────────────────────────────────────────────
# 제목 대괄호는 담당자가 자유롭게 적어 '철강'·'철강/비철'·'철강/비철금속' 이 섞이고, 'N월의 기분'·'플레이북'
# 같은 시리즈 이름이 섹터 자리에 온다. 시리즈 이름은 None 을 돌려주고(호출 쪽이 담당자의 주 섹터로 대체)
# 변형은 대표 이름으로 접는다.
SECTOR_ALIASES = [
    (r'^(ESG.*|Transition)$', 'ESG'), (r'^(인터넷|SW|인터넷/SW|인터넷/게임|인터넷/SW/게임|플랫폼)$', '인터넷/SW'),
    (r'^(철강|철강/비철|철강/비철금속|비철)$', '철강/비철'), (r'^(건설|건설/부동산|부동산/건설|부동산)$', '건설'),
    (r'^(지주|지주회사)$', '지주'), (r'^(엔터|엔터/레저)$', '엔터'), (r'^(유통|유통/의류)$', '유통'),
    (r'^(의류|섬유/의류|섬유의류)$', '의류'), (r'^(에너지|에너지/화학|화학|정유/화학|정유)$', '에너지/화학'),
    (r'^(2차전지|이차전지|배터리)$', '2차전지'), (r'^(방위산업|방산|우주항공|항공우주)$', '방위산업'),
    (r'^(전력기기|전력기기/풍력|풍력)$', '전력기기'), (r'^(반도체|반도체/SW)$', '반도체'),
    (r'^(은행|은행/증권|증권|보험|금융)$', None),   # 금융은 세부 업종을 그대로 둔다(은행·보험·증권)
    (r'^(자동차|자동차/로봇|타이어)$', '자동차'), (r'^(게임)$', '게임'), (r'^(음식료|음식료/담배)$', '음식료'),
    (r'^(레저|카지노)$', '레저'), (r'^(디지털자산|RWA)$', '디지털자산'), (r'^(기계|건설기계|산업재)$', '기계'),
]
NOT_SECTOR = re.compile(r'기분|플레이북|메가프로젝트|^기업분석$|^산업분석$|전망$|Flash|Preview|Review|Comment|Daily|Weekly|Monthly|'
                        r'^\d|스몰캡|^중국-', re.I)


def canon_sector(raw):
    """대괄호 섹터 → 대표 이름. 시리즈 이름·빈 값이면 None."""
    s = clean(raw)
    if not s or NOT_SECTOR.search(s):
        return None
    for pat, canon in SECTOR_ALIASES:
        if re.match(pat, s, re.I):
            return canon or s
    return s
