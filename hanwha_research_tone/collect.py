"""한화투자증권 리서치 게시판 수집기 — 목록(기업/산업 1002 · 투자전략 1003) + 상세 본문.

  python collect.py                      # 증분: 새 글이 안 나올 때까지(겹침 2페이지) 목록을 훑고 상세를 받는다
  python collect.py --since 2025-01-01   # 백필: 그 날짜 이전 글이 나올 때까지 페이지를 넘긴다
  python collect.py --no-detail          # 목록만

실측(2026-11-01, CLAUDE.md 53번):
  · 목록은 GET `list.cmd?depth2_id=1002&mode=depth2&p=N` (10건/페이지, 최신순). 1002 는 19,235건 ·
    1003 은 4,584건. 상세는 `view.cmd?depth3_id=anls1&depth2_id=1002&mode=depth2&seq=66857`.
  · 첨부 PDF 는 로그인 뒤에만 열린다 — 대신 상세 페이지 `div.researchCont` 에 요약 본문(몇 문단)이
    그대로 실려 있어 그걸 분석 입력으로 쓴다. 산업자료는 `spJname`(관련 종목명 목록)도 있다.
  · 페이지 한 장이 ~520KB(메뉴가 대부분)라 백필은 상세 다운로드 예산(초)으로 끊고 다음 run 이 이어 받는다.
  · 개발 컨테이너는 service.hanwhawm.com:9090 접속이 막혀 있다 — 실행은 러너에서만.
"""
import argparse, html as _html, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import parse as P

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
REPORTS = DATA / 'reports.json'      # seq → 레코드(목록 + 상세 파생 필드)
BODIES = DATA / 'bodies.json'        # seq → 상세 본문 텍스트(분석 입력)
STATUS = DATA / 'collect_status.json'
BASE = 'https://service.hanwhawm.com:9090'
BOARDS = {'1002': '기업·산업분석', '1003': '투자전략'}
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36',
      'Accept-Language': 'ko-KR,ko;q=0.9'}
KST = timezone(timedelta(hours=9))

# 해외주식분석(anls19 등)은 한국 애널리스트의 국내 커버리지 톤이 아니라 기본 제외.
SKIP_DEPTH3 = set(filter(None, os.getenv('HANWHA_SKIP_DEPTH3', 'anls19').split(',')))
# 데일리·주간 시황류는 톤 추적 대상이 아니다(목록에는 남기되 AI 분석에서 제외).
ROUTINE_TITLE = re.compile(r'Daily|데일리|Morning|모닝|주간\s*파생시황|FI\s*Weekly|Weekly\s*Note|캘린더|일정|공표\s*중단|커버리지\s*(개시|제외)\s*안내', re.I)


def load(path, default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def save(path, obj):
    DATA.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')


def session():
    import requests
    s = requests.Session()
    s.headers.update(UA)
    return s


_ITEM = re.compile(r'<li>\s*<div class="tit[^"]*">(.*?)</li>', re.S)


def parse_list(html):
    """목록 HTML → 레코드 목록(최신순). bs4 없이 정규식 — 페이지가 커서 파싱이 빠른 쪽을 쓴다."""
    out = []
    for block in _ITEM.findall(html):
        m = re.search(r"view\('(\d+)',\s*'([^']*)',\s*'([^']*)'\)[^>]*>\s*(.*?)\s*</a>", block, re.S)
        if not m:
            continue
        seq, depth3, kind, title = m.group(1), m.group(2), m.group(3), P.clean(_html.unescape(re.sub(r'<[^>]+>', '', m.group(4))))
        summ = re.search(r'<p class="cont_txt">(.*?)</p>', block, re.S)
        info = re.search(r'<p class="info">\s*<span class="gubun">[^<]*</span>\s*(.*?)\s*<span class="date">([^<]*)</span>', block, re.S)
        analyst = P.clean(_html.unescape(re.sub(r'<[^>]+>', '', info.group(1)))) if info else ''
        d = P.clean(info.group(2)) if info else ''
        out.append({'id': seq, 'depth3': depth3, 'kind': kind, 'title': title, 'analyst': analyst,
                    'date': d.replace('.', '-'),
                    'summary': P.clean(_html.unescape(re.sub(r'<[^>]+>', ' ', summ.group(1)))) if summ else ''})
    return out


def view_url(rec):
    return (f"{BASE}/main/research/main/view.cmd?depth3_id={rec['depth3']}&depth2_id={rec['board']}"
            f"&mode=depth2&seq={rec['id']}&p=&depth3_nm={rec['kind']}&templet=default")


def parse_detail(html):
    """상세 HTML → {body, related: [(이름, 코드)]}. 본문은 researchCont 블록의 텍스트."""
    m = re.search(r'<div class="researchCont">(.*?)<!-- 홈페이지 개편', html, re.S) or \
        re.search(r'<div class="researchCont">(.*?)<div class="fileTable">', html, re.S) or \
        re.search(r'<div class="researchCont">(.*?)</div>\s*</div>\s*</div>', html, re.S)
    body = ''
    if m:
        raw = re.sub(r'<script.*?</script>', ' ', m.group(1), flags=re.S | re.I)
        raw = re.sub(r'<br\s*/?>', '\n', raw, flags=re.I)
        raw = re.sub(r'</(p|tr|td|div|li)>', '\n', raw, flags=re.I)
        raw = re.sub(r'<[^>]+>', ' ', raw)
        raw = _html.unescape(raw).replace('\xa0', ' ')
        body = P.clean_body('\n'.join(P.clean(x) for x in raw.split('\n') if P.clean(x)))
    names = re.search(r'var spJname\s*=\s*"([^"]*)"', html)
    codes = re.search(r'var spJcode\s*=\s*"([^"]*)"', html)
    related = []
    if names:
        ns = [x for x in names.group(1).split(',') if x]
        cs = [x for x in codes.group(1).split(',')] if codes else []
        related = [(n, cs[i] if i < len(cs) else '') for i, n in enumerate(ns)]
    return {'body': body, 'related': related}


def enrich(rec):
    """제목·본문에서 파생 필드(섹터·기업·의견·TP)를 채운다. 수집 뒤와 재빌드 때 같은 함수를 쓴다."""
    t = P.parse_title(rec['title'])
    rec['title_sector'] = t['sector']
    rec['company'] = t['company']; rec['code'] = t['code']
    rec['opinion'] = t['opinion']; rec['subject'] = t['subject']
    rec['overseas'] = t['is_overseas']
    rec['sector'] = P.sector_from_record(rec)
    # 대괄호가 시리즈 이름('9월의 기분'·'플레이북')이거나 비어 있으면 섹터 미상 — build 가 담당자의 주 섹터로 채운다
    rec['sector_guess'] = rec['board'] == '1002' and P.canon_sector(rec.get('title_sector')) is None
    rec['routine'] = bool(ROUTINE_TITLE.search(rec['title']))
    rec['scope'] = '기업' if rec['code'] else ('전략' if rec['board'] == '1003' else '산업')
    return rec


def crawl_board(s, board, known, since=None, max_pages=400, overlap=2):
    """목록을 최신순으로 넘기며 새 레코드를 모은다. 증분이면 '전부 아는 페이지'가 overlap 번 연속이면 멈추고,
    백필(since)이면 since 이전 날짜만 있는 페이지가 나오면 멈춘다."""
    new, stale_pages = {}, 0
    for p in range(1, max_pages + 1):
        url = f'{BASE}/main/research/main/list.cmd?depth2_id={board}&mode=depth2&p={p}'
        items = []
        for attempt in range(3):
            try:
                r = s.get(url, timeout=40)
                if r.status_code == 200:
                    items = parse_list(r.text)
                if items:
                    break
            except Exception as exc:
                print(f'::warning::목록 {board} p={p} 실패({attempt + 1}): {str(exc)[:120]}')
            time.sleep(2 + attempt * 2)
        if not items:
            print(f'목록 {board} p={p}: 행 없음 — 중단')
            break
        fresh = 0
        for it in items:
            it['board'] = board
            if it['id'] not in known and it['id'] not in new:
                new[it['id']] = enrich(it); fresh += 1
        oldest = min(x['date'] for x in items)
        if since and oldest < since:
            print(f'목록 {board} p={p}: {oldest} < {since} — 백필 끝')
            break
        if not since:
            stale_pages = stale_pages + 1 if fresh == 0 else 0
            if stale_pages >= overlap:
                break
        if p % 20 == 0:
            print(f'목록 {board} p={p} 누적 신규 {len(new)}건 (가장 오래된 {oldest})')
        time.sleep(0.3)
    return new


def fetch_detail(s, rec):
    r = s.get(view_url(rec), timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f'HTTP {r.status_code}')
    if 'researchDetail' not in r.text and 'researchCont' not in r.text:
        raise RuntimeError('상세 템플릿 아님')
    return parse_detail(r.text)   # 본문이 비어 있어도(로그인 전용 글) 저장해 재요청을 막는다 — 분석은 요약으로


def wanted(rec, since):
    if rec['date'] < since:
        return False
    if rec['depth3'] in SKIP_DEPTH3 or rec.get('overseas'):
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', default=os.getenv('HANWHA_SINCE', '2025-01-01'), help='이 날짜 이후 글만 분석 대상(백필 하한)')
    ap.add_argument('--backfill', action='store_true', help='목록을 since 까지 끝까지 넘긴다(기본은 증분)')
    ap.add_argument('--max-pages', type=int, default=int(os.getenv('HANWHA_MAX_PAGES', '400')))
    ap.add_argument('--no-detail', action='store_true')
    ap.add_argument('--detail-budget', type=int, default=int(os.getenv('HANWHA_DETAIL_BUDGET', '900')), help='상세 다운로드 예산(초)')
    ap.add_argument('--workers', type=int, default=4)
    args = ap.parse_args()

    reports = load(REPORTS, {})
    bodies = load(BODIES, {})
    s = session()
    started = time.monotonic()
    # 목록: 레코드가 하나도 없으면 자동 백필
    backfill = args.backfill or not reports
    total_new = 0
    for board in BOARDS:
        new = crawl_board(s, board, reports, since=args.since if backfill else None, max_pages=args.max_pages)
        reports.update(new); total_new += len(new)
        print(f'{BOARDS[board]}({board}): 신규 {len(new)}건')
    if total_new:
        save(REPORTS, reports)

    # 상세: 분석 대상인데 본문이 없는 글을 최신순으로(예산 안에서)
    fetched = failed = 0
    if not args.no_detail:
        todo = sorted((r for r in reports.values() if wanted(r, args.since) and r['id'] not in bodies),
                      key=lambda r: (r['date'], r['id']), reverse=True)
        print(f'상세 미수집 {len(todo)}건 — 예산 {args.detail_budget}초')
        pending = list(todo)
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            while pending and time.monotonic() - started < args.detail_budget:
                batch, pending = pending[:args.workers * 3], pending[args.workers * 3:]
                futs = {ex.submit(fetch_detail, s, r): r for r in batch}
                for f in as_completed(futs):
                    r = futs[f]
                    try:
                        d = f.result()
                        bodies[r['id']] = d['body'][:20000]
                        if d['related']:
                            r['related'] = d['related'][:30]
                        cov = P.extract_cover(d['body'])
                        r['body_tp'] = cov
                        if not r.get('opinion') and cov['opinion']:
                            r['opinion'] = cov['opinion']
                        fetched += 1
                    except Exception as exc:
                        failed += 1
                        r['detail_error'] = str(exc)[:120]
                if fetched and fetched % 60 == 0:
                    save(BODIES, bodies); save(REPORTS, reports)
                    print(f'상세 {fetched}건 수집(실패 {failed}) … {int(time.monotonic() - started)}초')
        save(BODIES, bodies); save(REPORTS, reports)
        left = len(pending)
    else:
        left = None
    status = {'ran_at': datetime.now(timezone.utc).isoformat(), 'reports': len(reports), 'new': total_new,
              'detail_fetched': fetched, 'detail_failed': failed, 'detail_left': left,
              'bodies': len(bodies), 'since': args.since, 'backfill': backfill}
    save(STATUS, status)
    print(json.dumps(status, ensure_ascii=False))


if __name__ == '__main__':
    main()
