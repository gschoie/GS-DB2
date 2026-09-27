"""임시 프로브: 새 universe.py를 러너에서 실제 실행해 KOSPI200·코스닥50 수 확인."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import universe
k = universe.crawl_kospi200(); print("KOSPI200", len(k), list(k.items())[:3], list(k.items())[-3:])
q = universe.crawl_kosdaq50(); print("KOSDAQ50", len(q), list(q.items())[:3])
universe.CACHE = "/tmp/uni.json"
u = universe.load_or_crawl(refresh=True)
from collections import Counter
print("total", len(u), Counter(g for v in u.values() for g in v["groups"]))
