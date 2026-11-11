# weekly_highlights — 이번주 튀는 차트

주보 5종(📈 피어그룹 주가변동표 · ⚔️ 주가 INDEX 비교 · 💰 수급 그림 · 📊 컨센서스 · 📐 ER)에서
**이번 주 의미 있는 변화가 있는 차트만** 규칙으로 골라 보여준다. 사이드바 📰 주보 › ✨ 이번주.튀는차트.

- `catalog.py` — 차트 목록. 종목 정의는 ecos-fx-rates 생성기 모듈(`ECOS_DIR`)과 coverage_flow 에서 빌려 쓴다.
- `rules.py` — 판정 규칙(순수 함수). 임계값은 `TH` 한 곳. 모르는 값은 침묵(없음으로 안 바꾼다).
- `build.py` — 야후 시세 수집 + 로컬/ecos 데이터 → `static/weekly_highlights/<기준일>.json` · `latest.json` · `index.json`.
- `../telegram_research_dashboard/static/weekly_highlights_report.html` — JSON 을 읽어 그리는 페이지(그림은 직접 SVG).
- 워크플로 `weekly-highlights.yml` — 토요일 새벽(미국장 마감 뒤). 정시는 Claude 예약, 크론은 안전망.

```bash
# 컨테이너(야후 불가)에서 모양 확인 — 컨센·ER·수급은 실제 파일, 시세만 가짜
ECOS_DIR=/path/to/ecos-fx-rates python build.py --demo --out /tmp/wh
python -m unittest tests.test_rules
```
