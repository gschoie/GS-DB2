"""수집 레코드 + AI 분석 → 톤 보드 데이터(tone_v2.json·tone_summary.json). 순수 파이썬.

  python build_tone.py            # data/ 에 쓰고 대시보드 static/hanwha_tone/ 로 복사
"""
import json, re, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect as C
from ai_analyze import AI_CACHE, SCHEMA_VERSION

OUT_V2 = C.DATA / 'tone_v2.json'
OUT_SUMMARY = C.DATA / 'tone_summary.json'
SITE_DIR = C.ROOT.parent / 'telegram_research_dashboard' / 'static' / 'hanwha_tone'


def fmt_won(v):
    return f'{int(round(v)):,}원' if v else ''


def opinion_class(op):
    o = (op or '').lower()
    if re.search(r'buy|overweight|매수|비중확대|outperform', o):
        return 'up'
    if re.search(r'sell|underweight|매도|비중축소|underperform', o):
        return 'down'
    if re.search(r'hold|neutral|중립|marketperform', o):
        return 'mid'
    return ''


def norm_label(s):
    return re.sub(r'[\s·/,.\-()]+', '', (s or '').lower())


def same_point(a, b):
    x, y = norm_label(a), norm_label(b)
    return bool(x) and (x == y or (len(x) >= 4 and (x in y or y in x)))


def merge_report(r, ai_entry, body, pdf_ok=False):
    ai = (ai_entry or {}).get('result') if (ai_entry or {}).get('v') == SCHEMA_VERSION else None
    company, code, scope = r.get('company') or '', r.get('code') or '', r.get('scope') or '산업'
    if ai and ai['report_scope'] == '기업' and ai['company'] and not code and r['board'] == '1002':
        company, code, scope = ai['company'], ai['code'], '기업'
    opinion = r.get('opinion') or ''
    if not opinion and ai and ai['opinion'] not in ('', '없음') and not r.get('routine'):
        opinion = ai['opinion']
    rec = {'id': r['id'], 'date': r['date'], 'month': r['date'][:7], 'analyst': r.get('analyst') or '미상',
           'sector': r.get('sector') or '기타', 'kind': r.get('kind') or '', 'board': r['board'], 'scope': scope,
           'company': company, 'code': code, 'title': r['title'], 'subject': r.get('subject') or r['title'],
           'summary': (r.get('summary') or '')[:400], 'url': C.view_url(r), 'opinion': opinion,
           'routine': bool(r.get('routine')), 'related': [x[0] for x in (r.get('related') or [])][:12],
           'body_chars': len(body or ''), 'ai': bool(ai), 'ai_src': (ai_entry or {}).get('src', '') if ai else ''}
    # 표지 정규식은 PDF(한경) > 게시판 본문 순 — PDF 표지에 투자의견·목표주가·직전가가 정형으로 찍힌다
    cov = r.get('pdf_tp') if (r.get('pdf_tp') or {}).get('tp') else (r.get('body_tp') or {})
    hk = r.get('hk') or {}
    rec['pdf_url'] = hk.get('pdf_url', '') if hk.get('idx') else ''
    rec['pdf'] = bool(pdf_ok)
    if not rec['opinion'] and (r.get('pdf_tp') or {}).get('opinion'):
        rec['opinion'] = r['pdf_tp']['opinion']
    if ai:
        tp = ai['tp']
        if tp.get('prior') and tp['prior'] % 100:          # 비율 역산 흔적(라운드 숫자가 아님)은 버린다
            tp = {**tp, 'prior': None}
        rec.update({'conviction': ai['conviction'], 'tone_label': ai['tone_label'], 'one_line': ai['one_line'],
                    'strong_phrases': ai['strong_phrases'], 'hedge_phrases': ai['hedge_phrases'],
                    'negative_phrases': ai['negative_phrases'],
                    'points': [p['label'] for p in ai['investment_points']], 'points_detail': ai['investment_points'],
                    'earnings_direction': ai['earnings']['direction'], 'earnings_evidence': ai['earnings']['evidence'],
                    'estimates': ai.get('estimates')})
        # 정규식이 본문에서 잡은 TP(숫자·직전가)가 있으면 그게 더 정확하다 — 방향·사유는 AI 것
        value = cov.get('tp') or tp.get('value')
        prior = cov.get('tp_prior') or tp.get('prior')
        direction = tp['direction'] if tp['direction'] != '없음' else (cov.get('tp_change') or '없음')
        if direction == '없음' and value and prior and value != prior:
            direction = '상향' if value > prior else '하향'
        if direction == '없음' and value:
            direction = ''        # 숫자는 있는데 방향 언급이 없다 — 타임라인의 직전 TP 와 비교해 채운다
        rec['tp_event'] = None if direction in ('없음', '유지') and not value else {
            'direction': direction, 'value': value, 'prior': prior,
            'display': (fmt_won(value) if direction == '유지' or prior == value or not prior
                        else f'{fmt_won(prior)} → {fmt_won(value)}') or direction,
            'reasons': tp['reasons'] or (['기타'] if direction in ('상향', '하향') else []),
            'evidence': tp['evidence']}
    else:
        rec.update({'conviction': None, 'tone_label': '', 'one_line': '', 'strong_phrases': [], 'hedge_phrases': [],
                    'negative_phrases': [], 'points': [], 'points_detail': [], 'earnings_direction': '',
                    'earnings_evidence': '', 'estimates': None})
        value, prior, direction = cov.get('tp'), cov.get('tp_prior'), cov.get('tp_change') or ''
        rec['tp_event'] = {'direction': direction or ('유지' if value and not prior else ''), 'value': value, 'prior': prior,
                           'display': f'{fmt_won(prior)} → {fmt_won(value)}' if prior and prior != value else fmt_won(value),
                           'reasons': [], 'evidence': ''} if value else None
    ev = rec.get('tp_event')
    if ev and ev.get('value') and not ev.get('prior') and ev['direction'] in ('상향', '하향'):
        ev['display'] = f"기존 → {fmt_won(ev['value'])}"
    if scope != '기업' or not company:
        rec['tp_event'] = None      # 산업·전략 자료의 TP 는 어느 종목 것인지 몰라 노이즈
    return rec


def company_key(rec):
    if rec['scope'] != '기업' or not rec['company']:
        return f"IND:{rec['sector']}", f"{rec['sector']} 산업" if rec['sector'] != '전략·경제' else '전략·경제', ''
    return (rec['code'] or f"NM:{norm_label(rec['company'])}"), rec['company'], rec['code']


def fill_tp_priors(timeline):
    """직전 TP 가 본문에 없으면 같은 종목 타임라인의 직전 값으로 채운다.
    본문이 '유지'라 해도 직전 기록과 다르면(그 사이 자료를 못 받았거나 본문에 숫자가 없던 경우) 비교로
    방향을 매기되 inferred 표식을 남긴다 — '유지'로 두면 TP 가 바뀐 사실이 화면에서 사라진다."""
    last, last_date = None, None
    for rec in timeline:                      # 시간순
        tp = rec.get('tp_event')
        if not tp or not tp.get('value'):
            continue
        if tp.get('prior') is None and last and last != tp['value']:
            if tp['direction'] in ('상향', '하향'):
                if (tp['direction'] == '상향') == (tp['value'] > last):
                    tp['prior'] = last; tp['display'] = f'{fmt_won(last)} → {fmt_won(tp["value"])}'
            else:
                tp['direction'] = '상향' if tp['value'] > last else '하향'
                tp['prior'] = last; tp['display'] = f'{fmt_won(last)} → {fmt_won(tp["value"])}'
                tp['reasons'] = tp['reasons'] or ['기타']
                tp['inferred'] = True
                tp['evidence'] = (tp.get('evidence') or '') + f' [직전 기록 {last_date} {fmt_won(last)} 대비 — 본문엔 변경 언급 없음]'
        elif tp['direction'] == '' and last == tp['value']:
            tp['direction'] = '유지'
        elif tp['direction'] == '':
            tp['direction'] = '신규'
        last, last_date = tp['value'], rec['date']


def attach_point_diffs(timeline):
    prev, prev_date = None, None
    for rec in timeline:
        if not rec['ai']:
            rec['points_added'], rec['points_dropped'] = [], []
            continue
        cur = rec['points']
        if prev is None:
            rec['points_added'], rec['points_dropped'] = [], []
        else:
            rec['points_added'] = [p for p in cur if not any(same_point(p, q) for q in prev)]
            rec['points_dropped'] = [q for q in prev if not any(same_point(q, p) for p in cur)]
            rec['points_prev_date'] = prev_date
        prev, prev_date = cur, rec['date']


def timeline_events(key, name, timeline):
    events, steady, prev = [], [], {}
    for rec in timeline:
        base = {'date': rec['date'], 'company_key': key, 'company': name, 'analyst': rec['analyst'],
                'sector': rec['sector'], 'report_id': rec['id'], 'source': rec['url']}
        tp = rec.get('tp_event')
        if tp and tp['direction'] in ('상향', '하향'):
            reasons = '·'.join(tp['reasons'])
            events.append({**base, 'type': f"TP {tp['direction']}",
                           'detail': f"{tp['display']} ← {reasons}" if reasons else tp['display'], 'evidence': tp['evidence']})
        elif tp and tp['direction'] == '유지' and tp.get('value'):
            phrase = (rec['negative_phrases'] or rec['strong_phrases'] or [''])[0]
            steady.append({**base, 'type': 'TP 유지', 'detail': f"{tp['display']} (유지)", 'evidence': tp['evidence'],
                           'phrase': phrase, 'phrase_kind': '부정' if rec['negative_phrases'] else '강한'})
        cur = opinion_class(rec['opinion'])
        if cur and prev.get('op_class') and cur != prev['op_class']:
            events.append({**base, 'type': '의견 변경', 'detail': f"{prev['opinion']} → {rec['opinion']}", 'evidence': ''})
        if rec['ai'] and rec['earnings_direction'] in ('상향', '하향'):
            events.append({**base, 'type': f"실적추정 {rec['earnings_direction']}",
                           'detail': rec['earnings_evidence'][:160], 'evidence': rec['earnings_evidence']})
        if rec['ai'] and prev.get('conviction') is not None and rec['conviction'] is not None:
            delta = rec['conviction'] - prev['conviction']
            if abs(delta) >= 2:
                events.append({**base, 'type': '톤 급변' + ('↑' if delta > 0 else '↓'),
                               'detail': f"확신도 {prev['conviction']} → {rec['conviction']} ({rec['tone_label']})",
                               'evidence': rec['one_line']})
        added, dropped = rec.get('points_added') or [], rec.get('points_dropped') or []
        if added or dropped:
            pl = (rec.get('points_prev_date') or '')[5:].replace('-', '.')
            bits = ([f"신규: {', '.join(added)}"] if added else []) + ([f"{pl + ' 포인트' if pl else '직전'}: {', '.join(dropped)}"] if dropped else [])
            events.append({**base, 'type': '투자포인트 변화', 'detail': ' · '.join(bits), 'evidence': ''})
        if cur:
            prev['opinion'], prev['op_class'] = rec['opinion'], cur
        if rec['conviction'] is not None:
            prev['conviction'] = rec['conviction']
    return events, steady


def build(write_site=True):
    reports, bodies, cache = C.load(C.REPORTS, {}), C.load(C.BODIES, {}), C.load(AI_CACHE, {})
    status = C.load(C.STATUS, {})
    since = status.get('since') or '2025-01-01'
    wanted = [r for r in reports.values() if C.wanted(r, since)]
    # 섹터 미상(시리즈 제목) 글은 그 담당자가 가장 많이 쓴 섹터로 — 담당자별 최빈값
    mode = defaultdict(lambda: defaultdict(int))
    for r in wanted:
        if r['board'] == '1002' and not r.get('sector_guess') and r.get('sector') not in ('기업분석', '산업분석', '기타'):
            mode[r.get('analyst')][r['sector']] += 1
    for r in wanted:
        if r.get('sector_guess') or r.get('sector') in ('기업분석', '산업분석', '기타'):
            if mode.get(r.get('analyst')):
                r['sector'] = max(mode[r['analyst']].items(), key=lambda kv: kv[1])[0]
    import hankyung as H
    shards = H.load_shards()
    pdf_ok_ids = {seq for sh in shards.values() for seq, ent in sh.items() if ent.get('ok')}
    records = [merge_report(r, cache.get(r['id']), bodies.get(r['id']), r['id'] in pdf_ok_ids) for r in wanted]
    by_key = defaultdict(list)
    names = {}
    for rec in records:
        key, name, _ = company_key(rec)
        by_key[key].append(rec); names[key] = name
    companies, events, steady = {}, [], []
    for key, tl in by_key.items():
        tl.sort(key=lambda x: (x['date'], x['id']))
        fill_tp_priors(tl); attach_point_diffs(tl)
        ev, st = timeline_events(key, names[key], tl)
        events += ev; steady += st
        last_tp = next((x['tp_event'] for x in reversed(tl) if x.get('tp_event') and x['tp_event'].get('value')), None)
        last_op = next((x['opinion'] for x in reversed(tl) if opinion_class(x['opinion'])), '')
        companies[key] = {'key': key, 'name': names[key], 'code': tl[-1]['code'], 'sector': tl[-1]['sector'],
                          'analysts': sorted({x['analyst'] for x in tl}), 'report_count': len(tl),
                          'last_date': tl[-1]['date'], 'last_tp': last_tp, 'last_opinion': last_op,
                          'timeline': list(reversed(tl))}
    events.sort(key=lambda e: (e['date'], e['report_id']), reverse=True)
    steady.sort(key=lambda e: (e['date'], e['report_id']), reverse=True)

    # 섹터 × 애널리스트 보드
    sectors = []
    sec_an = defaultdict(lambda: defaultdict(list))
    for rec in records:
        if rec['routine']:
            continue
        sec_an[rec['sector']][rec['analyst']].append(rec)
    for sec, ans in sec_an.items():
        rows = []
        for an, recs in ans.items():
            recs.sort(key=lambda x: (x['date'], x['id']))
            ind = [x for x in recs if x['scope'] != '기업' and opinion_class(x['opinion'])]
            conv = [{'date': x['date'], 'v': x['conviction'], 'company': x['company'] or x['sector']} for x in recs if x['conviction'] is not None][-40:]
            covered = {}
            for x in recs:
                if x['scope'] == '기업' and x['company']:
                    k = company_key(x)[0]
                    covered[k] = {'key': k, 'name': x['company'], 'date': x['date'], 'opinion': x['opinion'],
                                  'tp': (x.get('tp_event') or {}).get('value')}
            rows.append({'analyst': an, 'sector': sec, 'report_count': len(recs), 'last_date': recs[-1]['date'],
                         'last_title': recs[-1]['subject'], 'last_id': recs[-1]['id'],
                         'opinion': ind[-1]['opinion'] if ind else '', 'opinion_date': ind[-1]['date'] if ind else '',
                         'industry_key': f'IND:{sec}', 'conviction_series': conv,
                         'avg_conviction': round(sum(c['v'] for c in conv) / len(conv), 2) if conv else None,
                         'covered': sorted(covered.values(), key=lambda c: c['date'], reverse=True)})
        rows.sort(key=lambda r: r['last_date'], reverse=True)
        sectors.append({'sector': sec, 'analysts': rows, 'report_count': sum(r['report_count'] for r in rows),
                        'last_date': max(r['last_date'] for r in rows)})
    sectors.sort(key=lambda s: s['last_date'], reverse=True)

    ai_n = sum(1 for r in records if r['ai'])
    pdf_n = sum(1 for r in records if r['pdf'])
    v2 = {'pdf_count': pdf_n, 'pdf_matched': sum(1 for r in records if r['pdf_url']),
          'ai_pdf': sum(1 for r in records if r['ai_src'] == 'pdf'), 'hk_status': C.load(C.DATA / 'hankyung_status.json', {}),
'generated_at': datetime.now(timezone.utc).isoformat(), 'source': 'hanwhawm.com research board (1002·1003)',
          'since': since, 'report_count': len(records), 'ai_analyzed': ai_n, 'bodies': len(bodies),
          'collect_status': status, 'ai_status': C.load(C.DATA / 'ai_run_status.json', {}),
          'sectors': sectors, 'companies': companies, 'events': events[:400], 'steady': steady[:200]}
    latest = sorted(records, key=lambda x: (x['date'], x['id']), reverse=True)[:40]
    summary = {'generated_at': v2['generated_at'], 'report_count': len(records), 'ai_analyzed': ai_n,
               'events': events[:30],
               'latest': [{'date': x['date'], 'company': x['company'] or x['sector'], 'company_key': company_key(x)[0],
                           'analyst': x['analyst'], 'sector': x['sector'], 'title': x['title'], 'opinion': x['opinion'],
                           'conviction': x['conviction'], 'tp_dir': (x.get('tp_event') or {}).get('direction', ''),
                           'post_url': x['url']} for x in latest]}
    C.save(OUT_V2, v2); C.save(OUT_SUMMARY, summary)
    if write_site:
        SITE_DIR.mkdir(parents=True, exist_ok=True)
        (SITE_DIR / 'tone_v2.json').write_text(json.dumps(v2, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        (SITE_DIR / 'tone_summary.json').write_text(json.dumps(summary, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({'reports': len(records), 'ai': ai_n, 'companies': len(companies), 'sectors': len(sectors),
                      'events': len(events), 'steady': len(steady)}, ensure_ascii=False))
    return v2


if __name__ == '__main__':
    build()
