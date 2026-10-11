# 매크로 데스크 (macro_desk)

금리·채권·환율·원자재 숫자와 월·분기 지표 발표 일정을 한 장에 모으고, **숫자 옆에
"얼마면 무슨 뜻인가"를 같이 둔다.** 매크로를 처음 보는 사람이 혼자 읽을 수 있게 하는 게 목적.

매일 **저녁 9시(KST)** 갱신 → 대시보드 `📈 투자 > 📊 매크로.데스크`.

## 화면 구성

| 섹션 | 내용 |
|---|---|
| 📈 지금 숫자 | 미국 금리 4종·달러/환율 4종·원자재와 VIX. 1D/1W/1M/3M/12M 변화 |
| 🗓 발표 일정 | 이번 달 + 다음 달 달력. 🇺🇸/🇰🇷 구분, 칸에 커서를 올리면 발표 시각 |
| 🧭 지표 해석 | 지표별 밴드("근원 CPI 3.5% 이상이면 …") + 시장 반응 + 한국 함의 + 원문 링크 |
| 📚 기초 | 금리·채권가격, 장단기 역전, 실질금리, '예상 대비', 미국→한국 전달 경로 |

표기 규칙: **금리는 %p(절대차), 나머지는 %(비율)** 로 변화를 적는다 — 둘을 섞으면
"10년물이 6% 올랐다"처럼 읽는 사람이 오해한다.

## 데이터

**키 없이 도는 것** — yfinance
`^IRX ^FVX ^TNX ^TYX` / `DX-Y.NYB KRW=X JPY=X EURUSD=X` / `CL=F GC=F HG=F ^VIX`

**`FRED_API_KEY` 를 넣으면 추가되는 것** (무료 키, https://fredaccount.stlouisfed.org/apikeys)
`DGS2`(진짜 2년물) · `T10Y2Y`(10년−2년 스프레드) · `T10YIE`(기대인플레) ·
`DFII10`(실질금리) · `SOFR`

> ⚠️ 키가 없으면 "미국 2년물" 칸은 **실제로 5년물(^FVX)** 이다 — yfinance에 2년물
> 티커가 없다. 화면 ⓘ에 그렇게 적어두었고, 키를 넣으면 진짜 2년물로 바뀐다.

## 발표 일정 — 규칙과 확정일을 나눈 이유

`calendar_rules.py` 가 `config.yml` 의 규칙을 날짜로 바꾼다.

- `nth_weekday: [1, fri]` 첫째 금요일 (고용보고서) · `[-1, fri]` 마지막 금요일 (PCE)
- `nth_bizday: 1` 첫 영업일 (ISM 제조업) — **공휴일은 모르고 주말만 제외**한다
- `day: 1` / `around: 12` 매월 n일 (수출입 / CPI)
- `fixed: true` **규칙이 없는 것** — FOMC·금통위

규칙으로 뽑은 날짜는 화면에 **`~`** 를 붙여 추정일임을 표시한다. `fixed` 인 항목은
`fixed_dates.json` 에 있을 때만 달력에 나오고, 없으면 "일정 미확인"으로 남는다 —
**기관 공표일을 추측해서 달력에 박으면 틀린 날짜가 사실처럼 보이기 때문이다.**

```json
// fixed_dates.json
{"dates": {"fomc": ["2026-10-28", "2026-12-09"], "bok": ["2026-10-15"]}}
```

`tests/test_calendar.py` 14개가 날짜 산수를 검산한다. 월말이 주말일 때 다음 달로
넘어가 그 달 달력에서 사라지던 버그를 이 테스트가 잡았다(2026-02-28 토요일).

## 해석 가이드는 코드가 아니라 `guide.yml`

숫자는 매일 바뀌어도 해석 틀은 잘 안 바뀐다. 그래서 수집과 분리했다 — 문구를 고칠
일이 생기면 `guide.yml` 만 고치면 화면이 따라 바뀐다.

유튜브는 **영상 ID 대신 검색 링크**를 건다. 특정 영상을 박으면 몇 달 뒤 내려가 죽은
링크가 되지만 검색은 남는다. 기관 링크(BLS·BEA·연준·통계청·한은)만 직접 건다.

## 실행

```bash
pip install -r requirements.txt
python collect.py              # 수집 → static/macro_desk/<날짜>.json (120일 보관)
python collect.py --dry-run    # 저장 없이 출력만
python build_report.py         # → static/macro_desk_report.html
python -m unittest discover -s tests -p "test_*.py"
```

## 배포

`macro-desk.yml` — 저녁 9시 크론(안전망) + `workflow_dispatch`. 정시성은 GAS 시계
(`gas/dispatch_proxy.gs` SCHEDULE `macro` 21:00 daily)가 담당하고, 크론에는 guard 잡
(이벤트 무관·자기 제외·600분 창, CLAUDE.md 24번 방식)을 걸어 중복 실행을 막는다.

커밋 → `deploy-pages.yml` 의 workflow_run("매크로 데스크")이 받아 Pages로 올린다.
화면 `🔄 지표 갱신` 버튼은 GAS `macro` 라우트로 workflow_dispatch.

## 아직 안 한 것

- **텔레그램** — 사용자 확인 후 붙인다("오늘 숫자 + 내일 발표 예정 + 한 줄 해석" 안)
- **FOMC·금통위 확정일 수집** — 연준·한은 공식 페이지에서 받아 `fixed_dates.json` 갱신
- 한국 국고채 금리(ECOS 키 필요), 신용스프레드, 중국 지표
