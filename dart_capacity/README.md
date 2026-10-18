# dart_capacity — 생산능력·생산실적·가동률 (OpenDART)

국내 상장사 정기보고서(사업·반기·분기)의 「생산능력 / 생산실적 / 가동률」 표를 모아
회사·섹터별 시계열로 보여주는 모듈.

```
config/companies.yaml   대상 회사(종목코드·섹터)
fetch.py      OpenDART corpCode → list.json → document.xml (원문 zip 캐시 data/raw/, 리포 미포함)
extract.py    원문에서 키워드 섹션의 표만 잘라내기 → data/extracted/<코드>_<rcept_no>.html|.json
normalize.py  Claude API 로 공통 스키마 JSON → data/normalized/, 모호한 건 data/review.csv
dashboard/    정적 HTML (회사·섹터 필터, 시계열, 가동률 비교)
```

- 환경변수: `DART_API_KEY`(OpenDART 인증키, 무료 발급), `ANTHROPIC_API_KEY`(정규화).
- 워크플로 `dart-capacity.yml`: 3·5·8·11월 20일 07:00 KST + 수동(종목·단계 선택).
  원문 zip 은 `actions/cache` 로만 보관한다.
- 단위는 바꾸지 않는다(척·CGT·톤·대·억원 그대로). 금액 기준인지 수량 기준인지는 note 에.

로컬 실행: `DART_API_KEY=… python fetch.py --codes 329180 && python extract.py --preview`
(개발 컨테이너는 OpenDART 가 차단돼 러너에서만 실행 가능.)
