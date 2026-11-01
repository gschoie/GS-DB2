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
    s = rec.get('title_sector') or ''
    if not s:
        return kind or '기타'
    # '[2027년 산업전망]' 같은 시리즈 머리는 섹터가 아니다
    if re.search(r'전망|Flash|Preview|Review|Comment|Daily|Weekly|Monthly|산업분석|기업분석|\d{4}', s, re.I):
        return kind or '기타'
    return s


# ── PDF 표지에서 적정주가·투자의견 ─────────────────────────────────────────
_TP_PAT = re.compile(
    r'(?:목표주가|적정주가|Target\s*Price|TP)\s*[:：]?\s*(?:\(?(상향|하향|유지|신규)\)?\s*)?'
    r'([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,7})\s*원?'
    r'(?:\s*\(?\s*(상향|하향|유지|신규)\s*\)?)?', re.I)
_PRIOR_PAT = re.compile(r'(?:기존|이전|직전|종전)\s*(?:목표주가|적정주가|TP)?\s*[:：]?\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,7})\s*원?'
                        r'|([0-9]{1,3}(?:,[0-9]{3})+)\s*원?\s*(?:→|->|에서)\s*([0-9]{1,3}(?:,[0-9]{3})+)\s*원?')
_OP_PAT = re.compile(r'(?:투자의견|Rating)\s*[:：]?\s*(Buy|Hold|Sell|Neutral|Overweight|Underweight|매수|중립|매도|N/?R)'
                     r'(?:\s*\(?\s*(상향|하향|유지|신규)\s*\)?)?', re.I)


def _num(s):
    try:
        return int(str(s).replace(',', ''))
    except (TypeError, ValueError):
        return None


def extract_cover(text, max_chars=6000):
    """PDF 첫 페이지 텍스트에서 투자의견·적정주가·직전가·방향. 못 찾으면 None 값."""
    head = (text or '')[:max_chars]
    out = {'opinion': '', 'opinion_change': '', 'tp': None, 'tp_prior': None, 'tp_change': ''}
    om = _OP_PAT.search(head)
    if om:
        out['opinion'] = norm_opinion(om.group(1))
        out['opinion_change'] = om.group(2) or ''
    tm = _TP_PAT.search(head)
    if tm:
        val = _num(tm.group(2))
        if val and 100 <= val <= 50_000_000:
            out['tp'] = val
            out['tp_change'] = tm.group(1) or tm.group(3) or ''
    pm = _PRIOR_PAT.search(head)
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
    if out['tp'] and out['tp_prior']:
        if out['tp_prior'] == out['tp']:
            out['tp_change'] = out['tp_change'] or '유지'
        elif not out['tp_change']:
            out['tp_change'] = '상향' if out['tp'] > out['tp_prior'] else '하향'
    return out
