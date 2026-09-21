"""선물 수급: KIS / KRX(https·정확한 referer) / 네이버 선물 SPA 를 한 번에(일회용)."""
import os, json, re, requests

print("=" * 72); print("[A] 한투(KIS) — 이미 키가 붙어 있는 경로")
key, sec = os.environ.get("KIS_APP_KEY"), os.environ.get("KIS_APP_SECRET")
if not key:
    print("  키 미설정")
else:
    B = "https://openapi.koreainvestment.com:9443"
    tok = requests.post(f"{B}/oauth2/tokenP", timeout=20, json={
        "grant_type": "client_credentials", "appkey": key, "appsecret": sec}).json()["access_token"]
    def call(path, tr, params):
        h = {"authorization": f"Bearer {tok}", "appkey": key, "appsecret": sec,
             "tr_id": tr, "custtype": "P"}
        try:
            r = requests.get(B + path, headers=h, params=params, timeout=20)
            j = r.json()
            out = j.get("output") or j.get("output1") or j.get("output2")
            head = json.dumps(out[0] if isinstance(out, list) and out else out,
                              ensure_ascii=False)[:230] if out else ""
            print(f"  {r.status_code} rt={j.get('rt_cd')} {tr:<14} {str(j.get('msg1'))[:34]:<34} {head}")
        except Exception as e:
            print(f"  ERR {tr} {type(e).__name__}: {e}")
    # 선물옵션 시세/투자자 후보
    call("/uapi/domestic-futureoption/v1/quotations/inquire-price", "FHMIF10000000",
         {"FID_COND_MRKT_DIV_CODE": "F", "FID_INPUT_ISCD": "101W12"})
    call("/uapi/domestic-stock/v1/quotations/inquire-investor", "FHPTJ04400000",
         {"FID_COND_MRKT_DIV_CODE": "F", "FID_INPUT_ISCD": "101W12"})
    # 업종/지수 투자자별 (지수 = K200)
    call("/uapi/domestic-stock/v1/quotations/inquire-investor", "FHPTJ04040000",
         {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": "0001"})
    call("/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice", "FHKUP03500100",
         {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": "2001",
          "FID_INPUT_DATE_1": "20260901", "FID_INPUT_DATE_2": "20260921", "FID_PERIOD_DIV_CODE": "D"})

print("\n" + "=" * 72); print("[B] KRX — https + 메뉴 referer 정확히")
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
                  "Accept": "application/json, text/javascript, */*; q=0.01",
                  "X-Requested-With": "XMLHttpRequest"})
MENU = "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201030104"
try:
    r0 = S.get(MENU, timeout=25)
    print("  메뉴 열기:", r0.status_code, "쿠키:", list(S.cookies.keys()))
except Exception as e:
    print("  메뉴 열기 실패:", e)
for name, bld, extra in [
    ("파생 투자자별 12901", "dbms/MDC/STAT/standard/MDCSTAT12901",
     {"inqTpCd": "1", "trdVolVal": "1", "askBid": "3", "prodId": "KRDRVFUK2I",
      "strtDd": "20260915", "endDd": "20260921", "share": "1", "money": "1"}),
    ("현물 투자자별 02203", "dbms/MDC/STAT/standard/MDCSTAT02203",
     {"inqTpCd": "1", "trdVolVal": "2", "askBid": "3", "mktId": "STK",
      "strtDd": "20260918", "endDd": "20260921", "share": "1", "money": "1"}),
]:
    try:
        r = S.post("https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
                   headers={"Referer": MENU}, data={"bld": bld, **extra}, timeout=25)
        print(f"  {r.status_code} {name}: {r.text[:240]}")
    except Exception as e:
        print(f"  ERR {name}: {type(e).__name__}: {e}")

print("\n" + "=" * 72); print("[C] 네이버 선물 SPA 실제 경로")
UA = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile Safari/604.1",
      "Referer": "https://m.stock.naver.com/"}
try:
    r = requests.get("https://m.stock.naver.com/front-api/domestic/futures/current", headers=UA, timeout=15)
    print("  futures/current:", r.status_code, r.text[:200])
except Exception as e:
    print("  ERR", e)
for pg in ("https://m.stock.naver.com/domestic/futures/101W12/total",
           "https://m.stock.naver.com/domestic/futures"):
    try:
        r = requests.get(pg, headers=UA, timeout=20)
        m = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
        print(f"\n  {r.status_code} {pg} → {r.url[:64]}")
        if m:
            qs = json.loads(m.group(1))["props"]["pageProps"].get("dehydratedState", {}).get("queries", [])
            for q in qs:
                print("     KEY:", json.dumps(q.get("queryKey"), ensure_ascii=False)[:120])
    except Exception as e:
        print("  ERR", pg, type(e).__name__)
