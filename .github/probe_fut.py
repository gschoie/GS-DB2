"""K200 선물 투자자별 수급을 어디서 받을 수 있는지 찾는다(일회용)."""
import json, re, requests

UA = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile Safari/604.1",
      "Referer": "https://m.stock.naver.com/"}

print("=" * 72); print("[1] 네이버 신규 SPA 의 선물 화면 — 쿼리 키/종목코드 캐내기")
for page in ("https://m.stock.naver.com/domestic/futures/KOSPI200",
             "https://m.stock.naver.com/domestic/index/KPI200/total"):
    try:
        r = requests.get(page, headers=UA, timeout=20, allow_redirects=True)
        print(f"\n  {r.status_code} {page}  (최종 {r.url[:70]})")
        m = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
        if m:
            j = json.loads(m.group(1))
            qs = j.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
            for q in qs:
                print("     KEY:", json.dumps(q.get("queryKey"), ensure_ascii=False)[:110])
        # 선물 종목코드 패턴(예: 101W9000, 10600 등)
        codes = sorted(set(re.findall(r'"(1[0-9]{2}[A-Z0-9]{4,6})"', r.text)))[:8]
        print("     선물코드 후보:", codes)
    except Exception as e:
        print(f"  ERR {page} — {type(e).__name__}: {e}")

print("\n" + "=" * 72); print("[2] 네이버 api 선물 경로 후보")
for u in ["https://m.stock.naver.com/api/futures/KOSPI200/basic",
          "https://m.stock.naver.com/api/index/KPI200F/trend",
          "https://m.stock.naver.com/front-api/stock/domestic/integration?code=KPI200F&endType=index",
          "https://m.stock.naver.com/front-api/domestic/futures/list",
          "https://m.stock.naver.com/front-api/stock/domestic/integration?code=KOSPI200F&endType=futures"]:
    try:
        r = requests.get(u, headers=UA, timeout=15)
        print(f"  {r.status_code}  {u.split('naver.com')[1][:62]:<62} {r.text[:110]}")
    except Exception as e:
        print(f"  ERR  {u[-62:]} {type(e).__name__}")

print("\n" + "=" * 72); print("[3] KRX 공식 — 먼저 페이지를 열어 쿠키를 받은 뒤 조회")
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
try:
    S.get("http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd"
          "?menuId=MDC0201020203", timeout=20)
    print("  쿠키:", list(S.cookies.keys()))
except Exception as e:
    print("  세션 준비 실패:", e)
H = {"Referer": "http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd",
     "X-Requested-With": "XMLHttpRequest"}
# MDCSTAT12901 = 파생상품 투자자별 거래실적(일별추이)
for name, bld, extra in [
    ("선물 투자자별 일별추이", "dbms/MDC/STAT/standard/MDCSTAT12901",
     {"inqTpCd": "1", "trdVolVal": "1", "askBid": "3", "prodId": "KRDRVFUK2I",
      "strtDd": "20260901", "endDd": "20260921", "share": "1", "money": "1"}),
    ("현물 투자자별(대조군)", "dbms/MDC/STAT/standard/MDCSTAT02203",
     {"inqTpCd": "1", "trdVolVal": "2", "askBid": "3", "mktId": "STK",
      "strtDd": "20260918", "endDd": "20260921", "share": "1", "money": "1"}),
]:
    try:
        r = S.post("http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
                   headers=H, data={"bld": bld, **extra}, timeout=25)
        print(f"\n  {r.status_code}  {name}\n        {r.text[:300]}")
    except Exception as e:
        print(f"  ERR  {name} — {type(e).__name__}: {e}")
