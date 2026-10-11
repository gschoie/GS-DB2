# 매크로 데스크 (macro_desk)

금리·채권·환율·원자재 숫자와 월·분기 지표 발표 일정을 한 장에 모으고, **숫자 옆에
"얼마면 무슨 뜻인가"를 같이 둔다.** 매크로를 처음 보는 사람이 혼자 읽을 수 있게 하는 게 목적.

매일 **저녁 9시(KST)** 갱신 → 대시보드 `📈 투자 > 📊 매크로.데스크`.

## 화면 구성

| 섹션 | 내용 |
|---|---|
| 📈 지금 숫자 | 미국 금리 4종·달러/환율 4종·원자재와 VIX. 1D/1W/1M/3M/12M 변화 |
| 🗓 발표 일정 | **다가오는 발표(3주) 표** — 직전 발표값·컨센서스·최근 3회 추이 + 이번 달·다음 달 달력 |
| 🧭 지표 해석 | 지표별 밴드("근원 CPI 3.5% 이상이면 …") + 시장 반응 + 한국 함의 + 원문 링크 |
| 📚 기초 | 금리·채권가격, 장단기 역전, 실질금리, '예상 대비', 미국→한국 전달 경로 |

표기 규칙: **금리는 %p(절대차), 나머지는 %(비율)** 로 변화를 적는다 — 둘을 섞으면
"10년물이 6% 올랐다"처럼 읽는 사람이 오해한다.

## 데이터

**키 없이 도는 것** — yfinance
`^IRX ^FVX ^TNX ^TYX` / `DX-Y.NYB KRW=X JPY=X EURUSD=X` / `CL=F GC=F HG=F ^VIX`

**발표 지표의 직전치 — BLS 공개 API v1, 키 불필요** (`releases.py`)
CPI(`CUSR0000SA0` + 코어 `CUSR0000SA0L1E`) · PPI(`WPSFD4`) ·
고용보고서(취업자 `CES0000000001` + 실업률 `LNS14000000`).
v1 한도가 **IP당 25회/일 · 요청당 50계열** 이라 계열마다 부르면 한도에 걸린다 →
**전 지표를 한 번의 호출로** 받는다.

**`FRED_API_KEY` 를 넣으면 추가되는 것** (무료 키, https://fredaccount.stlouisfed.org/apikeys)
- 시세판: `DGS2`(진짜 2년물) · `T10Y2Y`(10년−2년 스프레드) · `T10YIE`(기대인플레) ·
  `DFII10`(실질금리) · `SOFR`
- 달력 직전치: 소매판매 `RSAFS` · PCE `PCEPI`/`PCEPILFE` · GDP `A191RL1Q225SBEA` ·
  정책금리 `DFEDTARU` · 한국 CPI·실업률·GDP

> ⚠️ 키가 없으면 "미국 2년물" 칸은 **실제로 5년물(^FVX)** 이다 — yfinance에 2년물
> 티커가 없다. 표 밑에 각주로 적어두었고, 키를 넣으면 진짜 2년물로 바뀐다.

### 러너에서 뭐가 막히고 뭐가 되나 (실측 2026-10-11)

| 소스 | 러너 | 메모 |
|---|---|---|
| `api.bls.gov/publicAPI/v1` | **됨 (키 불필요)** | 물가·고용·임금. 25회/일·50계열 |
| `api.stlouisfed.org` (FRED **API**) | **됨** | 가짜 키로 부르면 "키 형식 오류" 400 — **키만 넣으면 쓸 수 있다** |
| `fred.stlouisfed.org` (그래프·CSV) | **막힘** | 0.05초 만에 `HTTP/2 INTERNAL_ERROR`. '키 없이 CSV' 우회 불가 |
| `api.census.gov` (소매판매) | 키 필요 | `Missing Key` |
| `apps.bea.gov` (GDP·PCE 원본) | 타임아웃 | |
| ISM | 경로 없음 | 2022년 재배포 중단 — 유료 외 방법 없음 |

> **FRED 를 뭉떵그려 "안 된다"고 적으면 안 된다** — 막힌 건 그래프·CSV 호스트
> (`fred.stlouisfed.org`)뿐이고 키 경로(`api.stlouisfed.org`)는 열려 있다.

> 파이썬 `urlopen(timeout=)` 은 위 차단을 **타임아웃으로 못 잡는다**(소켓 1회 작업
> 기준이라 응답이 느리게 흘러오면 안 걸린다) — 1차 프로브가 15분을 매달렸다.
> 도달성은 `curl --max-time` 으로 끊어서 보는 게 빠르다.

**컨센서스는 무료 API 가 없다** (Investing·TradingEconomics 유료/차단) →
`consensus.json` 에 적힌 것만 화면에 나온다. 비어 있으면 '–'. 세션에
"매크로 컨센 갱신" 을 시키면 웹서치로 이 파일을 채운다.

소스가 또 막히면 `tests/probe_release_sources.py` 를 러너에서 돌려 생존 확인.

## 발표 일정 — 규칙과 확정일을 나눈 이유

`calendar_rules.py` 가 `config.yml` 의 규칙을 날짜로 바꾼다.

- `nth_weekday: [1, fri]` 첫째 금요일 (고용보고서) · `[-1, fri]` 마지막 금요일 (PCE)
- `nth_bizday: 1` 첫 영업일 (ISM 제조업) — **공휴일은 모르고 주말만 제외**한다
- `day: 1` / `around: 12` 매월 n일 (수출입 / CPI)
- `fixed: true` **규칙이 없는 것** — FOMC·금통위

규칙으로 뽑은 날짜는 화면에 **`~`** 를 붙여 추정일임을 표시한다.

**확정일을 알면 규칙보다 확정일이 먼저다** — 규칙은 근사라 며칠씩 어긋난다
(2026년 9월 CPI: 규칙 `around 12` → 10/12, BLS 일정표의 실제 발표일 → **10/14**).
`fixed_dates.json` 에 날짜가 있으면 그 날짜를 쓰고 `~` 를 떼고, 없는 달은 규칙으로
돌아간다. `fixed: true` 인 항목(FOMC·금통위)은 날짜를 모르면 **아예 안 보여준다** —
기관 공표일을 추측해서 달력에 박으면 틀린 날짜가 사실처럼 보이기 때문이다.

```json
// fixed_dates.json — dates 는 확정일, tentative 는 출처 한 곳뿐이라 ~ 가 붙는다
{"dates":     {"fomc": ["2026-10-28"], "us_cpi": ["2026-10-14"]},
 "tentative": {"bok":  ["2026-10-22"]}}
```

`tests/test_calendar.py` 19개가 날짜 산수를 검산한다. 월말이 주말일 때 다음 달로
넘어가 그 달 달력에서 사라지던 버그를 이 테스트가 잡았다(2026-02-28 토요일).
`tests/test_releases.py` 는 직전치 변환(전월비·전년동월비·증감·분기 라벨)을 검산한다 —
**변화율을 못 구할 때 지수 원값을 대신 찍어 '코어 337.8' 이 되던 버그**를 여기서 잡았다.

## 툴팁에만 정보를 두지 않는다

처음 판은 달력 칩에 지표 이름만 찍고 설명을 `title` 툴팁에 뒀다. `cursor:help` 때문에
**커서만 물음표로 바뀌고 화면에는 숫자가 하나도 없었다** — 툴팁은 모바일에서 아예
안 뜬다. 지금은 칩이 두 줄(이름 + 컨센/직전치)이고, 누르면 그 지표의 해석 카드로
내려간다. 시세표의 ⓘ 주의문도 각주로 표 밑에 쓴다.

국기 이모지(🇺🇸·🇰🇷)도 **윈도우에서 안 그려져 `us`·`KR` 글자로 떨어진다** →
처음부터 글자 배지(`<i class="cc">US</i>`)를 쓴다.

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
python tests/test_calendar.py   # 발표일 계산
python tests/test_releases.py   # 직전치 변환
```

`tests/probe_release_sources.py` 는 **러너 전용** 탐색 스크립트다(컨테이너에서는
전부 egress 차단). 소스가 죽었는지 확인할 때 일회성 워크플로로 돌린다.

## 배포

`macro-desk.yml` — 저녁 9시 크론(안전망) + `workflow_dispatch`. 정시성은 GAS 시계
(`gas/dispatch_proxy.gs` SCHEDULE `macro` 21:00 daily)가 담당하고, 크론에는 guard 잡
(이벤트 무관·자기 제외·600분 창, CLAUDE.md 24번 방식)을 걸어 중복 실행을 막는다.

커밋 → `deploy-pages.yml` 의 workflow_run("매크로 데스크")이 받아 Pages로 올린다.
화면 `🔄 지표 갱신` 버튼은 GAS `macro` 라우트로 workflow_dispatch.

## 아직 안 한 것

- **텔레그램** — 사용자 확인 후 붙인다("오늘 숫자 + 내일 발표 예정 + 한 줄 해석" 안)
- **확정 발표일 자동 수집** — 지금은 손으로 적는다. BLS(`bls.gov/schedule`)·연준·한은
  일정 페이지를 긁어 `fixed_dates.json` 을 갱신하면 손이 빠진다(러너 도달성 미확인)
- **금통위 확정일** — 현재 `tentative`(출처 한 곳). 한은 공식 일정으로 확인 필요
- **컨센서스 채우기** — 수동/세션 웹서치. 자동화하려면 유료 소스가 필요하다
- 한국 국고채 금리(ECOS 키 필요), 신용스프레드, 중국 지표
