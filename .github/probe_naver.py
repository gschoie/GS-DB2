"""새 수집 경로를 러너에서 실제로 돌려본다(일회용 검증)."""
import sys, json, datetime as dt
sys.path.insert(0, "market_flow")
import scrape

biz = dt.datetime.now(scrape.KST).strftime("%Y%m%d")
print("bizdate =", biz)
print("\n[1] kospi_basic"); print("   ", scrape.kospi_basic())
print("\n[2] snapshot_provisional"); print("   ", scrape.snapshot_provisional(biz))
print("\n[3] daily_confirmed (30영업일 백필)")
c = scrape.daily_confirmed(biz)
print(f"    {len(c)}일 수신")
for d in sorted(c)[-6:]:
    print("   ", d, json.dumps(c[d], ensure_ascii=False))
print("\n[4] curve_from_slots — 슬롯 2개로 모양 확인")
day = {"slots": {"1300": {"time": "13:00", "individual": -100, "foreign": 50,
                          "institution": 50, "arb": 10, "nonarb": 20, "program": 30},
                 "1000": {"time": "10:00", "individual": -60, "foreign": 30,
                          "institution": 30, "arb": 5, "nonarb": 10, "program": 15}}}
print("    investor:", scrape.curve_from_slots(day, "investor"))
print("    program :", scrape.curve_from_slots(day, "program"))
print("\n[5] futures_daily — 실패해야 정상(섹션 비표시)")
try:
    scrape.futures_daily(biz); print("    ⚠️ 예외가 안 났다")
except Exception as e:
    print("    OK:", e)
