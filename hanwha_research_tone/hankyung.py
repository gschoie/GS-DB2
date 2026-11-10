"""한경컨센서스(consensus.hankyung.com)에서 한화투자증권 리포트 PDF 를 받아 본문을 보강한다.

한화 홈페이지의 첨부 PDF 는 로그인 전용이지만 한경컨센서스는 같은 PDF 를 로그인 없이 준다
(2026-11-01 러너 실측: `analysis/list?search_text=한화투자증권&sdate=&edate=&pagenum=80` 이
증권사 필터로 동작, 행마다 `analysis/downpdf?report_idx=` 링크. 열: 작성일·분류·제목·작성자·제공출처·첨부).

  python hankyung.py --backfill            # 2025-01-01 부터 월 단위로 목록 전부
  python hankyung.py --days 14             # 증분(최근 2주)
  python hankyung.py --pdf-budget 900      # PDF 다운로드·텍스트 추출 예산(초)

산출: data/hankyung_index.json(report_idx → 행), 게시판 레코드에 `hk`(매칭된 idx·pdf_url) 와
`pdf_tp`(PDF 표지 정규식), data/pdf_text/YYYY-MM.json(seq → 텍스트, 월별 샤드 — 매일 다시 쓰는
한 덩어리 파일보다 git 차분이 작다). PDF 자체는 저장하지 않는다.
"""
import argparse, io, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect as C
import parse as P

BASE = 'https://consensus.hankyung.com'
BROKER = '한화투자증권'
INDEX = C.DATA / 'hankyung_index.json'
PDF_DIR = C.DATA / 'pdf_text'
STATUS = C.DATA / 'hankyung_status.json'
PDF_MAX_CHARS = int(os.getenv('HANWHA_PDF_MAX_CHARS', '12000'))
PDF_PAGES = 4   # 표지·요약·투자포인트는 앞 몇 쪽에 다 있다


def list_url(sdate, edate, page, pagenum=80):
    from urllib.parse import quote
    return (f'{BASE}/analysis/list?sdate={sdate}&edate={edate}&search_value=&search_text={quote(BROKER)}'
            f'&order_type=&pagenum={pagenum}&now_page={page}')


_ROW = re.compile(r'<tr[^>]*>(.*?)</tr>', re.S)
_TD = re.compile(r'<td[^>]*>(.*?)</td>', re.S)


def _text(html):
    return P.clean(__import__('html').unescape(re.sub(r'<[^>]+>', ' ', html)))


def parse_list(html):
    """목록 HTML → 행 목록. 제목 칸은 같은 제목이 3번 반복돼 첫 앵커 텍스트만 쓴다."""
    out = []
    for row in _ROW.findall(html):
        tds = _TD.findall(row)
        if len(tds) < 6:
            continue
        d = _text(tds[0])
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', d):
            continue
        m = re.search(r'report_idx=(\d+)', row)
        if not m:
            continue
        a = re.search(r'<a[^>]*>(.*?)</a>', tds[2], re.S)
        title = _text(a.group(1)) if a else _text(tds[2])
        if not title:
            title = _text(tds[2])
        cm = re.match(r'(.+?)\((\d{6}|[0-9A-Z]{6})\)\s*(.*)', title)
        out.append({'idx': m.group(1), 'date': d, 'kind': _text(tds[1]), 'title': title,
                    'company': P.clean(cm.group(1)) if cm else '', 'code': cm.group(2) if cm else '',
                    'subject': P.clean(cm.group(3)) if cm else title,
                    'analyst': _text(tds[3]), 'broker': _text(tds[4]),
                    'pdf_url': f'{BASE}/analysis/downpdf?report_idx={m.group(1)}'})
    return out


def month_windows(since, until):
    cur = date.fromisoformat(since)
    while cur <= until:
        nxt = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
        yield cur.isoformat(), min(nxt - timedelta(days=1), until).isoformat()
        cur = nxt


def crawl(s, sdate, edate, index):
    new = 0
    for page in range(1, 20):
        rows = []
        for attempt in range(3):
            try:
                r = s.get(list_url(sdate, edate, page), timeout=40)
                if r.status_code == 200:
                    rows = parse_list(r.text)
                break
            except Exception as exc:
                print(f'::warning::한경 목록 {sdate}~{edate} p{page} 실패: {str(exc)[:100]}')
                time.sleep(2 + attempt * 2)
        rows = [x for x in rows if x['broker'] == BROKER]
        for x in rows:
            if x['idx'] not in index:
                index[x['idx']] = x; new += 1
        if len(rows) < 80:
            break
        time.sleep(0.5)
    return new


# ── 게시판 글 ↔ 한경 행 매칭 ───────────────────────────────────────────────
def _toks(s):
    return {w for w in re.split(r'[^0-9A-Za-z가-힣]+', (s or '').lower()) if len(w) >= 2}


def match_score(rec, row):
    """같은 날짜(±1일) + 같은 담당자면 후보. 종목코드 일치 > 제목 토큰 겹침 순으로 점수."""
    try:
        dd = abs((date.fromisoformat(rec['date']) - date.fromisoformat(row['date'])).days)
    except ValueError:
        return 0
    if dd > 1:
        return 0
    an_ok = bool(row['analyst']) and (row['analyst'].split(',')[0].strip() in (rec.get('analyst') or ''))
    score = 0
    if rec.get('code') and rec['code'] == row['code']:
        score += 60
    bt, ht = _toks(rec.get('subject') or rec.get('title')), _toks(row['subject'])
    if bt and ht:
        inter = len(bt & ht)
        cover = inter / max(len(bt), len(ht))
        # 한경 제목이 시리즈 이름뿐일 때('FI Weekly' vs 게시판 '[FI Weekly] FOMC 프리뷰…')는 포함 관계로도 본다
        contain = inter / min(len(bt), len(ht)) if min(len(bt), len(ht)) >= 2 else 0
        score += int(50 * max(cover, 0.8 * contain))
    if an_ok:
        score += 20
    if dd == 0:
        score += 10
    return score


def match_all(reports, index):
    by_date = {}
    for row in index.values():
        by_date.setdefault(row['date'], []).append(row)
    used, n = set(), 0
    recs = sorted((r for r in reports.values() if C.wanted(r, '2025-01-01')), key=lambda r: (r['date'], r['id']), reverse=True)
    for rec in recs:
        if rec.get('hk') and rec['hk'].get('idx') in index:
            used.add(rec['hk']['idx']); continue
        d = date.fromisoformat(rec['date'])
        cands = [x for k in (d - timedelta(days=1), d, d + timedelta(days=1)) for x in by_date.get(k.isoformat(), [])
                 if x['idx'] not in used]
        best = max(cands, key=lambda x: match_score(rec, x), default=None)
        if best and match_score(rec, best) >= 60:
            rec['hk'] = {'idx': best['idx'], 'pdf_url': best['pdf_url'], 'title': best['title'], 'score': match_score(rec, best)}
            used.add(best['idx']); n += 1
    return n


# ── PDF 텍스트 ──────────────────────────────────────────────────────────────
def shard_path(month):
    return PDF_DIR / f'{month}.json'


def load_shards():
    out = {}
    if PDF_DIR.exists():
        for p in sorted(PDF_DIR.glob('*.json')):
            out[p.stem] = json.loads(p.read_text(encoding='utf-8'))
    return out


def extract_pdf_text(data):
    from pypdf import PdfReader
    rd = PdfReader(io.BytesIO(data))
    parts = []
    for pg in rd.pages[:PDF_PAGES]:
        try:
            parts.append(pg.extract_text() or '')
        except Exception:
            parts.append('')
    text = '\n'.join(P.clean(x) for x in '\n'.join(parts).split('\n') if P.clean(x))
    return text[:PDF_MAX_CHARS], len(rd.pages)


def fetch_pdf(s, rec):
    r = s.get(rec['hk']['pdf_url'], timeout=90, headers={'Referer': BASE + '/analysis/list'})
    if r.status_code != 200 or r.content[:4] != b'%PDF':
        raise RuntimeError(f'PDF 아님 ({r.status_code}, {r.headers.get("content-type")})')
    text, pages = extract_pdf_text(r.content)
    return {'text': text, 'pages': pages, 'ok': len(re.findall(r'[가-힣]', text)) >= 80}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', default=os.getenv('HANWHA_SINCE', '2025-01-01'))
    ap.add_argument('--backfill', action='store_true')
    ap.add_argument('--days', type=int, default=14)
    ap.add_argument('--pdf-budget', type=int, default=int(os.getenv('HANWHA_PDF_BUDGET', '900')))
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--no-pdf', action='store_true')
    a = ap.parse_args()
    started = time.monotonic()
    s = C.session()
    index = C.load(INDEX, {})
    today = datetime.now(C.KST).date()
    backfill = a.backfill or not index
    new = 0
    if backfill:
        for sd, ed in month_windows(a.since, today):
            new += crawl(s, sd, ed, index)
    else:
        new += crawl(s, (today - timedelta(days=a.days)).isoformat(), today.isoformat(), index)
    C.save(INDEX, index)
    print(f'한경 목록: 누적 {len(index)}건, 신규 {new}건')

    reports = C.load(C.REPORTS, {})
    matched = match_all(reports, index)
    total_matched = sum(1 for r in reports.values() if r.get('hk'))
    print(f'매칭: 신규 {matched}건, 누적 {total_matched}건 / 대상 {sum(1 for r in reports.values() if C.wanted(r, a.since))}건')

    fetched = failed = 0
    shards = load_shards()
    have = {seq for sh in shards.values() for seq in sh}
    left = 0
    if not a.no_pdf:
        todo = sorted((r for r in reports.values() if r.get('hk') and r['id'] not in have and C.wanted(r, a.since)),
                      key=lambda r: (r['date'], r['id']), reverse=True)
        print(f'PDF 미수집 {len(todo)}건 — 예산 {a.pdf_budget}초')
        pending = list(todo)
        touched = set()
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            while pending and time.monotonic() - started < a.pdf_budget:
                batch, pending = pending[:a.workers * 2], pending[a.workers * 2:]
                futs = {ex.submit(fetch_pdf, s, r): r for r in batch}
                for f in as_completed(futs):
                    r = futs[f]
                    try:
                        d = f.result()
                        month = r['date'][:7]
                        shards.setdefault(month, {})[r['id']] = {'text': d['text'], 'pages': d['pages'], 'ok': d['ok'], 'idx': r['hk']['idx']}
                        touched.add(month)
                        if d['ok']:
                            r['pdf_tp'] = P.extract_cover(d['text'])
                            if not r.get('opinion') and r['pdf_tp'].get('opinion'):
                                r['opinion'] = r['pdf_tp']['opinion']
                        fetched += 1
                    except Exception as exc:
                        failed += 1
                        r.setdefault('hk', {})['error'] = str(exc)[:100]
                time.sleep(0.3)
        left = len(pending)
        PDF_DIR.mkdir(parents=True, exist_ok=True)
        for month in touched:
            shard_path(month).write_text(json.dumps(shards[month], ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    C.save(C.REPORTS, reports)
    status = {'ran_at': datetime.now(timezone.utc).isoformat(), 'index': len(index), 'index_new': new, 'matched': total_matched,
              'pdf_fetched': fetched, 'pdf_failed': failed, 'pdf_left': left, 'pdf_total': len(have) + fetched}
    C.save(STATUS, status)
    print(json.dumps(status, ensure_ascii=False))


def pdf_text_for(seq, month, shards=None):
    """seq 의 PDF 텍스트(없거나 이미지 PDF 면 '')."""
    sh = (shards or load_shards()).get(month, {})
    ent = sh.get(seq)
    return ent['text'] if ent and ent.get('ok') else ''


if __name__ == '__main__':
    main()
