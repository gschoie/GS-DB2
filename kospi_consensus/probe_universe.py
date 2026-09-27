"""임시 프로브: 네이버 개편 후 KOSPI200 구성·코스닥 시총 소스 탐색 (러너 전용)."""
import re, requests, json
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
MH = {"User-Agent": UA, "Referer": "https://m.stock.naver.com/"}
def show(u, h=None, redir=True, n=500, method="get", data=None):
    try:
        r = requests.request(method, u, headers=h or {"User-Agent": UA}, timeout=15,
                             allow_redirects=redir, data=data)
        print(f"\n### {u}\n  -> {r.status_code} final={r.url} loc={r.headers.get('location')} len={len(r.content)}")
        print("  ", r.text[:n].replace("\n", " "))
        return r
    except Exception as e:
        print(f"\n### {u}\n  !! {e}")
show("https://finance.naver.com/sise/entryJongmok.naver?type=KPI200&page=1", redir=False)
r = show("https://finance.naver.com/sise/entryJongmok.naver?type=KPI200&page=1")
show("https://finance.naver.com/sise/entryJongmok.naver?type=KPI200&page=1", h={"User-Agent": UA, "Referer": "https://finance.naver.com/sise/"}, redir=False)
show("https://finance.naver.com/sise/sise_market_sum.naver?sosok=1&page=1", redir=False)
for u in [
    "https://m.stock.naver.com/api/index/KPI200/enrollStocks?page=1&pageSize=5",
    "https://m.stock.naver.com/api/index/KPI200/stocks?page=1&pageSize=5",
    "https://m.stock.naver.com/api/index/KPI200/integration",
    "https://m.stock.naver.com/api/index/KPI200/basic",
    "https://m.stock.naver.com/api/stocks/marketValue/KOSDAQ?page=1&pageSize=5",
    "https://m.stock.naver.com/api/stocks/marketValue/KOSPI?page=1&pageSize=5",
    "https://m.stock.naver.com/front-api/marketIndex/kospi200/stocks?page=1&pageSize=5",
    "https://stock.naver.com/api/domestic/index/KPI200/enrollStocks?page=1&pageSize=5",
]:
    show(u, h=MH, n=700)
# 새 SPA 페이지에서 API 경로 힌트 수집
for u in ["https://stock.naver.com/domestic/index/KPI200/total", "https://m.stock.naver.com/domestic/index/KPI200/total"]:
    r = show(u, n=200)
    if r is not None:
        apis = sorted(set(re.findall(r'["\'](/?(?:front-)?api/[^"\'\s]{3,120})', r.text)))
        print("  api hints:", apis[:60])
        js = sorted(set(re.findall(r'src="([^"]+\.js)"', r.text)))[:15]
        print("  js:", js)
        for j in js:
            ju = j if j.startswith("http") else requests.compat.urljoin(r.url, j)
            try:
                t = requests.get(ju, headers={"User-Agent": UA}, timeout=15).text
            except Exception:
                continue
            hits = sorted(set(re.findall(r'["`\'](/?(?:front-)?api/[^"`\'\s]{3,120})', t)))
            hits = [h for h in hits if re.search(r"(?i)enroll|index|marketValue|stocks|rank", h)]
            if hits:
                print("  ", ju, hits[:40])
# KRX 지수 구성종목
show("http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd", method="post",
     h={"User-Agent": UA, "Referer": "http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201010106"},
     data={"bld": "dbms/MDC/STAT/standard/MDCSTAT00601", "indIdx": "1", "indIdx2": "028", "trdDd": "20260925"}, n=400)
