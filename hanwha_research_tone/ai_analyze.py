"""리포트 1건 → Gemini 구조화 분석(톤·TP 변경사유·실적추정·투자포인트). 다올 리서치톤의
ai_report_analyzer 와 같은 스키마 — 두 보드를 나란히 읽을 수 있게 필드를 맞췄다.

입력은 게시판 제목 + 목록 요약 + 상세 본문(bodies.json). 결과는 data/ai_analysis.json 에 seq 기준
캐시되어 증분 실행된다. 키는 HANWHA_GEMINI_API_KEY → GEMINI_API_KEY 순(무료 티어, 429 는 모델 교대).

  python ai_analyze.py --max 60
  python ai_analyze.py --dry-run
"""
import argparse, json, os, re, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect as C

DATA = C.DATA
AI_CACHE = DATA / 'ai_analysis.json'
AI_STATUS = DATA / 'ai_run_status.json'
GEMINI_URL = 'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
SCHEMA_VERSION = 2   # 2: 본문 정리(푸터 JS 제거) 뒤 재분석

TP_REASONS = ['실적추정', '멀티플', '방법론', '시점롤포워드', '기타']
TONE_LABELS = ['강한 확신', '긍정', '중립·건조', '신중', '부정적']
DIRECTIONS = ['상향', '하향', '유지', '신규', '없음']

SYSTEM_PROMPT = '''당신은 한국 셀사이드(한화투자증권) 리서치 보고서의 톤을 분석하는 전문가다.
보고서 텍스트(게시판 제목 + 요약 + 본문 발췌)를 읽고 JSON만 출력한다. 본문은 첨부 PDF가 아니라
게시판에 실린 요약 본문이므로, 본문에 없는 숫자는 지어내지 말고 null/없음으로 둔다.

규칙:
- conviction: 애널리스트 확신도 1~5 정수. 5=강한 확신(단정적 전망·공격적 매수 논거), 4=긍정,
  3=중립·건조(사실 나열 위주), 2=신중(헤징 표현 다수), 1=방어적·부정적. 문구를 근거로 판단한다.
- tone_label: [강한 확신, 긍정, 중립·건조, 신중, 부정적] 중 하나.
- strong_phrases / hedge_phrases / negative_phrases: 본문에서 "원문 그대로" 인용(각 80자 이내, 최대 3개).
  강한 문구=단정·확신 표현, 헤징 문구=유보·조건부 표현("~할 가능성", "지켜볼 필요"), 부정 문구=리스크·우려.
  해당 없으면 빈 배열.
- tp: 목표주가. direction은 [상향, 하향, 유지, 신규, 없음] 중 하나(언급 없으면 "없음").
  value/prior는 원 단위 숫자(없으면 null). reasons는 변경 배경을 [실적추정, 멀티플, 방법론, 시점롤포워드, 기타]
  중 해당하는 것 전부. prior(직전 목표주가)는 본문에 금액이 "명시"된 경우만 채운다 — '10% 하향'처럼
  비율만 있으면 prior는 null(비율로 역산하지 말 것). evidence에 근거 문장을 원문 인용(160자 이내).
- earnings: 실적(영업이익/EPS) 추정치 방향 [상향, 하향, 유지, 신규, 없음] + 근거 인용(160자 이내).
- opinion: 명시된 투자의견. 기업자료는 [Buy, Hold, Sell], 산업자료는 [Overweight, Neutral, Underweight].
  제목의 '[코드/Buy]' 표기도 명시로 본다. 명시 없으면 "없음". 주간·시황 자료는 톤으로 추측하지 말고 "없음".
- report_scope: 특정 기업 분석이면 "기업", 산업/전략/시황/경제면 "산업".
- company/code: 대상 기업명과 6자리 종목코드(산업자료면 빈 문자열).
- investment_points: 핵심 투자포인트 최대 4개. label은 12자 이내의 재사용 가능한 키워드
  (예: "북미 오프라인 확장", "HBM 증설", "환손실"), summary는 80자 이내 요지.
- one_line: 이 보고서의 톤을 한 문장으로(60자 이내).
- estimates: 애널리스트 본인의 실적 추정치(컨센서스 아님). quarter_label은 이 보고서가 다루는 당분기를
  '3Q26' 형식으로. quarter_op/year_op는 그 분기/당해 연도 영업이익 추정(억원), quarter_eps/year_eps는
  EPS(원). 본문에 없으면 null. 산업자료는 전부 null.
모든 텍스트는 한국어.'''


def _g(t, **kw):
    return {'type': t, **kw}


SCHEMA = _g('OBJECT', properties={
    'report_scope': _g('STRING', enum=['기업', '산업']),
    'company': _g('STRING'), 'code': _g('STRING'), 'opinion': _g('STRING'),
    'tp': _g('OBJECT', properties={
        'direction': _g('STRING', enum=DIRECTIONS), 'value': _g('NUMBER', nullable=True),
        'prior': _g('NUMBER', nullable=True), 'reasons': _g('ARRAY', items=_g('STRING', enum=TP_REASONS)),
        'evidence': _g('STRING')}, required=['direction', 'reasons', 'evidence']),
    'earnings': _g('OBJECT', properties={'direction': _g('STRING', enum=DIRECTIONS), 'evidence': _g('STRING')},
                   required=['direction', 'evidence']),
    'conviction': _g('INTEGER'), 'tone_label': _g('STRING', enum=TONE_LABELS),
    'strong_phrases': _g('ARRAY', items=_g('STRING')), 'hedge_phrases': _g('ARRAY', items=_g('STRING')),
    'negative_phrases': _g('ARRAY', items=_g('STRING')),
    'investment_points': _g('ARRAY', items=_g('OBJECT', properties={'label': _g('STRING'), 'summary': _g('STRING')},
                                             required=['label', 'summary'])),
    'one_line': _g('STRING'),
    'estimates': _g('OBJECT', properties={
        'quarter_label': _g('STRING'), 'quarter_op': _g('NUMBER', nullable=True), 'quarter_eps': _g('NUMBER', nullable=True),
        'year_op': _g('NUMBER', nullable=True), 'year_eps': _g('NUMBER', nullable=True)},
        required=['quarter_label', 'quarter_op', 'quarter_eps', 'year_op', 'year_eps']),
}, required=['report_scope', 'company', 'code', 'opinion', 'tp', 'earnings', 'conviction', 'tone_label',
             'strong_phrases', 'hedge_phrases', 'negative_phrases', 'investment_points', 'one_line', 'estimates'])

# 무료 티어 한도 버킷이 모델마다 따로다 — 429 면 기다리지 말고 다음 모델로(CLAUDE.md 49번 교훈).
MODELS = [m for m in os.getenv('HANWHA_GEMINI_MODELS', 'gemini-flash-lite-latest,gemini-flash-latest,gemini-2.5-flash-lite,gemini-2.5-flash').split(',') if m]


class QuotaExhausted(RuntimeError):
    pass


def api_key():
    return (os.getenv('HANWHA_GEMINI_API_KEY') or os.getenv('GEMINI_API_KEY') or '').strip()


def gemini(user_text, model):
    body = {'systemInstruction': {'parts': [{'text': SYSTEM_PROMPT}]},
            'contents': [{'role': 'user', 'parts': [{'text': user_text}]}],
            'generationConfig': {'responseMimeType': 'application/json', 'responseSchema': SCHEMA, 'temperature': 0.1}}
    req = urllib.request.Request(GEMINI_URL.format(model=model) + f'?key={api_key()}',
                                 data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.loads(resp.read().decode())
        return json.loads(payload['candidates'][0]['content']['parts'][0]['text'])
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='ignore')
        if exc.code == 429:
            raise QuotaExhausted(f'{model}: {detail[:300]}') from exc
        raise RuntimeError(f'{model} HTTP {exc.code}: {detail[:300]}') from exc


def _num(x):
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def normalize(raw):
    tp = raw.get('tp') or {}
    conv = raw.get('conviction')
    conv = min(5, max(1, int(conv))) if isinstance(conv, (int, float)) else 3
    ph = lambda k: [str(x)[:120] for x in (raw.get(k) or []) if str(x).strip()][:3]
    est = raw.get('estimates') or {}
    return {
        'report_scope': raw.get('report_scope') if raw.get('report_scope') in ('기업', '산업') else '산업',
        'company': str(raw.get('company') or '').strip()[:40],
        'code': raw.get('code') if re.fullmatch(r'[0-9]{6}', str(raw.get('code') or '')) else '',
        'opinion': str(raw.get('opinion') or '없음').strip()[:20],
        'tp': {'direction': tp.get('direction') if tp.get('direction') in DIRECTIONS else '없음',
               'value': _num(tp.get('value')), 'prior': _num(tp.get('prior')),
               'reasons': [x for x in (tp.get('reasons') or []) if x in TP_REASONS],
               'evidence': str(tp.get('evidence') or '')[:240]},
        'earnings': {'direction': (raw.get('earnings') or {}).get('direction') if (raw.get('earnings') or {}).get('direction') in DIRECTIONS else '없음',
                     'evidence': str((raw.get('earnings') or {}).get('evidence') or '')[:240]},
        'conviction': conv,
        'tone_label': raw.get('tone_label') if raw.get('tone_label') in TONE_LABELS else '중립·건조',
        'strong_phrases': ph('strong_phrases'), 'hedge_phrases': ph('hedge_phrases'), 'negative_phrases': ph('negative_phrases'),
        'investment_points': [{'label': str(p.get('label') or '')[:20], 'summary': str(p.get('summary') or '')[:100]}
                              for p in (raw.get('investment_points') or []) if str(p.get('label') or '').strip()][:4],
        'one_line': str(raw.get('one_line') or '')[:100],
        'estimates': {'quarter_label': str(est.get('quarter_label') or '')[:8], 'quarter_op': _num(est.get('quarter_op')),
                      'quarter_eps': _num(est.get('quarter_eps')), 'year_op': _num(est.get('year_op')), 'year_eps': _num(est.get('year_eps'))},
    }


def build_input(rec, body):
    parts = [f"[발간일] {rec['date']}  [애널리스트] {rec.get('analyst')}  [구분] {rec.get('kind')} / {rec.get('sector')}",
             f"[제목] {rec['title']}", f"[요약] {rec.get('summary') or ''}"]
    if body and len(body) > 80:
        parts.append(f"[본문]\n{body[:14000]}")
    else:
        parts.append('[본문] (게시판 본문 없음 — 제목·요약만으로 판단하고, 없는 숫자는 null/없음으로)')
    return '\n\n'.join(parts)


def pending_reports(reports, bodies, cache, since):
    out = []
    for r in reports.values():
        if not C.wanted(r, since) or r.get('routine'):
            continue
        ent = cache.get(r['id'])
        if ent and ent.get('v') == SCHEMA_VERSION:
            continue
        if r['id'] not in bodies:
            continue   # 상세를 아직 못 받았으면 다음 run 에(로그인 전용 글은 본문이 '' 로 저장돼 요약으로 분석)
        out.append(r)
    return sorted(out, key=lambda r: (r['date'], r['id']), reverse=True)


def run(max_reports, budget, since):
    reports, bodies, cache = C.load(C.REPORTS, {}), C.load(C.BODIES, {}), C.load(AI_CACHE, {})
    pend = pending_reports(reports, bodies, cache, since)
    status = {'ran_at': datetime.now(timezone.utc).isoformat(), 'pending_before': len(pend), 'analyzed': 0, 'errors': 0, 'last_error': ''}
    if not api_key():
        status['last_error'] = 'GEMINI_API_KEY 없음 — AI 분석 건너뜀'
        C.save(AI_STATUS, status); print(json.dumps(status, ensure_ascii=False)); return
    started, mi, done, errors = time.monotonic(), 0, 0, 0
    delay = float(os.getenv('AI_CALL_DELAY', '4.5'))
    try:
        for r in pend[:max_reports]:
            if time.monotonic() - started > budget:
                break
            text = build_input(r, bodies.get(r['id'], ''))
            for _ in range(len(MODELS)):
                try:
                    raw = gemini(text, MODELS[mi])
                    cache[r['id']] = {'v': SCHEMA_VERSION, 'analyzed_at': datetime.now(timezone.utc).isoformat(),
                                      'model': MODELS[mi], 'result': normalize(raw)}
                    done += 1
                    break
                except QuotaExhausted as exc:
                    status['last_error'] = str(exc)[:300]
                    mi = (mi + 1) % len(MODELS)
                    print(f'::warning::429 — 모델 교대 → {MODELS[mi]}')
                    time.sleep(3)
                except Exception as exc:
                    errors += 1; status['last_error'] = str(exc)[:300]
                    print(f"::warning::{r['id']} 분석 실패: {str(exc)[:200]}")
                    if '404' in str(exc):
                        mi = (mi + 1) % len(MODELS)
                    break
            else:
                print('::warning::모든 모델이 429 — 이번 run 중단'); break
            if errors >= 10:
                break
            time.sleep(delay)
    finally:
        if done:
            C.save(AI_CACHE, cache)
        status.update(analyzed=done, errors=errors, cached_total=len(cache), pending_left=len(pend) - done, model=MODELS[mi])
        C.save(AI_STATUS, status)
    print(json.dumps(status, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max', type=int, default=int(os.getenv('AI_MAX_REPORTS', '80')))
    ap.add_argument('--budget', type=int, default=int(os.getenv('AI_BUDGET_SECONDS', '1500')))
    ap.add_argument('--since', default=os.getenv('HANWHA_SINCE', '2025-01-01'))
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    if a.dry_run:
        reports, bodies, cache = C.load(C.REPORTS, {}), C.load(C.BODIES, {}), C.load(AI_CACHE, {})
        print(json.dumps({'cached': len(cache), 'pending': len(pending_reports(reports, bodies, cache, a.since))}))
        return
    run(a.max, a.budget, a.since)


if __name__ == '__main__':
    main()
