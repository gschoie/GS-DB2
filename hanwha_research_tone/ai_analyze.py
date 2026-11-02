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
import hankyung as H

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
MODELS = [m for m in os.getenv('HANWHA_GEMINI_MODELS', 'gemini-flash-lite-latest,gemini-flash-latest,gemini-3.5-flash-lite,gemini-3.5-flash,gemini-2.5-flash').split(',') if m]
# 11/2 실측: gemini-2.5-flash-lite 는 404('no longer available to new users') — 404 모델은 그 run 에서 제외한다


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
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=150) as resp:
                payload = json.loads(resp.read().decode())
            return json.loads(payload['candidates'][0]['content']['parts'][0]['text'])
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', errors='ignore')
            if exc.code == 429:
                raise QuotaExhausted(f'{model}: {detail[:300]}') from exc
            if exc.code in (500, 502, 503, 504) and attempt == 0:
                time.sleep(15); continue        # 일시 과부하 — 한 번은 같은 모델로 다시
            raise RuntimeError(f'{model} HTTP {exc.code}: {detail[:300]}') from exc
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            # 읽기 타임아웃(11/1 실측: PDF 입력이 길어진 뒤 연속 발생) — 한 번 더 시도하고 그래도 안 되면 다음 건으로
            if attempt == 0:
                time.sleep(10); continue
            raise RuntimeError(f'{model} network: {exc}') from exc
    raise RuntimeError('unreachable')


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


def build_input(rec, body, pdf_text=''):
    """입력 우선순위: 한경 PDF 원문(앞 몇 쪽) > 게시판 본문 > 요약만. 반환 (텍스트, src)."""
    parts = [f"[발간일] {rec['date']}  [애널리스트] {rec.get('analyst')}  [구분] {rec.get('kind')} / {rec.get('sector')}",
             f"[제목] {rec['title']}", f"[요약] {rec.get('summary') or ''}"]
    if pdf_text and len(pdf_text) > 200:
        parts.append(f"[PDF 원문 발췌]\n{pdf_text[:14000]}")
        if body and len(body) > 80:
            parts.append(f"[게시판 본문]\n{body[:4000]}")
        return '\n\n'.join(parts), 'pdf'
    if body and len(body) > 80:
        parts.append(f"[본문]\n{body[:14000]}")
        return '\n\n'.join(parts), 'body'
    parts.append('[본문] (게시판 본문 없음 — 제목·요약만으로 판단하고, 없는 숫자는 null/없음으로)')
    return '\n\n'.join(parts), 'summary'


def pending_reports(reports, bodies, cache, since, shards=None):
    """미분석(최신순) + 업그레이드 후보(요약·본문으로 분석했는데 이제 PDF 가 있는 것, 최신순) 순.
    업그레이드는 미분석이 다 끝난 뒤에만 차례가 온다 — 무료 쿼터는 새 글에 먼저."""
    shards = shards if shards is not None else H.load_shards()
    fresh, upgrade = [], []
    for r in reports.values():
        if not C.wanted(r, since) or r.get('routine'):
            continue
        if r['id'] not in bodies:
            continue   # 상세를 아직 못 받았으면 다음 run 에(로그인 전용 글은 본문이 '' 로 저장돼 요약으로 분석)
        ent = cache.get(r['id'])
        if not ent or ent.get('v') != SCHEMA_VERSION:
            fresh.append(r)
        elif ent.get('src') != 'pdf' and H.pdf_text_for(r['id'], r['date'][:7], shards):
            upgrade.append(r)
    key = lambda r: (r['date'], r['id'])
    return sorted(fresh, key=key, reverse=True) + sorted(upgrade, key=key, reverse=True)


def run(max_reports, budget, since):
    reports, bodies, cache = C.load(C.REPORTS, {}), C.load(C.BODIES, {}), C.load(AI_CACHE, {})
    shards = H.load_shards()
    pend = pending_reports(reports, bodies, cache, since, shards)
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
            text, src = build_input(r, bodies.get(r['id'], ''), H.pdf_text_for(r['id'], r['date'][:7], shards))
            for _ in range(len(MODELS)):
                try:
                    raw = gemini(text, MODELS[mi])
                    cache[r['id']] = {'v': SCHEMA_VERSION, 'analyzed_at': datetime.now(timezone.utc).isoformat(),
                                      'model': MODELS[mi], 'src': src, 'result': normalize(raw)}
                    done += 1
                    break
                except QuotaExhausted as exc:
                    status['last_error'] = str(exc)[:300]
                    mi = (mi + 1) % len(MODELS)
                    print(f'::warning::429 — 모델 교대 → {MODELS[mi]}')
                    time.sleep(3)
                except Exception as exc:
                    status['last_error'] = str(exc)[:300]
                    if 'HTTP 404' in str(exc) and len(MODELS) > 1:
                        # 폐기된 모델 — 오류로 세지 않고 목록에서 빼고 같은 건을 다음 모델로 다시
                        print(f'::warning::모델 폐기(404) → {MODELS[mi]} 제외')
                        MODELS.pop(mi); mi %= len(MODELS)
                        continue
                    errors += 1
                    print(f"::warning::{r['id']} 분석 실패: {str(exc)[:200]}")
                    break
            else:
                print('::warning::모든 모델이 429 — 이번 run 중단'); break
            if errors >= 25:          # 연속이 아니라 누적 — 일시 장애 10건에 run 이 통째로 끝나지 않게
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
        pend = pending_reports(reports, bodies, cache, a.since)
        print(json.dumps({'cached': len(cache), 'pending': len(pend),
                          'fresh': sum(1 for r in pend if (cache.get(r['id']) or {}).get('v') != SCHEMA_VERSION)}))
        return
    run(a.max, a.budget, a.since)


if __name__ == '__main__':
    main()
