# ⏳ 매매제한 컴플 체크 (24H)

GEMS(Gemini Gem)로 하던 아침 매매제한 대조 검증을 브라우저 프로그램으로 옮긴 것.
매매제한 지시(자료 A)와 파워베이스 반영 캡처(자료 B)를 올리면 누락·초과·코드 불일치를 대조한다.

## 쓰는 법

1. `compliance/index.html`을 브라우저(Chrome·Edge)로 연다. 파일 더블클릭으로도 되고 서버는 필요 없다.
   (`compliance` 폴더째로 받아야 한다. `matcher.js`와 `vendor/`가 같이 있어야 함)
2. AI를 고르고(기본 **Gemini**, 또는 Claude) API 키를 넣는다. "이 브라우저에 저장"을 체크하면 다음부터 안 넣어도 된다.
   - 모델 기본값: Gemini `gemini-pro-latest`(Google 최신 안정판 별칭), Claude `claude-opus-5-5`.
   - **모델 목록 불러오기**를 누르면 그 키로 쓸 수 있는 모델이 모델 칸 목록에 뜬다. 더 싸고 빠른 걸 원하면 `gemini-flash-latest`.
3. 자료를 넣는다.
   - **자료 A**: 김민경/대체 담당자 메시지 캡처. 텍스트는 아래 입력칸에 그대로 붙여넣어도 된다.
   - **자료 B**: RA 당번 파워베이스 매매제한 등록 화면 캡처. 여러 장 가능.
   - **A+B 혼합**: 엑셀 정리 시트처럼 지시 문구와 캡처가 한 장에 같이 있는 경우.
   - 영역을 클릭해 선택한 뒤 `Ctrl+V` 하면 클립보드 캡처가 바로 붙는다. 드래그앤드롭도 된다.
4. **대조 검증 실행** → 결과 화면, **결과 텍스트 복사**로 메신저에 붙여넣기.

## 구조: AI는 읽기만, 판정은 규칙으로

| 단계 | 담당 | 파일 |
| --- | --- | --- |
| 이미지·PDF·텍스트에서 종목 판독 | Gemini API 또는 Claude API (같은 JSON 스키마로 구조화 출력) | `index.html` |
| 대조·상태 판정·집계·보고서 | 고정 규칙 (같은 입력이면 항상 같은 결과) | `matcher.js` |

GEMS처럼 AI에게 대조와 집계까지 맡기면 건수가 틀리거나 판독 못 한 종목을 "일치"로 넘길 수 있다.
그래서 AI는 화면에 보이는 종목만 JSON으로 뽑고, 판정은 코드가 한다. 집계 합계는 대조표 행 수와 맞지 않으면 에러로 멈춘다.
AI 판독이 틀렸으면 결과 하단 "AI 판독 결과 보기"에서 JSON을 고친 뒤 **재대조**하면 된다(API 재호출 없음).

### 판정 규칙 (지침 반영)

- 종목코드는 문자열 그대로 둔다(앞자리 0 보존). `A005930`의 `A` 접두만 뗀다.
- 코드가 양쪽에 있으면 코드 일치를 최우선으로 본다. 코드가 같은데 종목명이 다르면 ❓.
- 종목명이 같아도 코드가 다르면 ❓로 두고 두 코드를 함께 적는다.
- 한쪽에만 코드가 있으면 종목명 정확 일치로 본다. 우선주(…우)·ETF·ETN은 이름이 달라서 자동으로 다른 종목이 된다.
- 반영 행에 매매제한 적용 증거가 없거나(상태 불명) 해제 표시면 ❓. 적용기간이 서로 다르면 ❓.
- 같은 캡처 안에 같은 종목이 두 번 있으면 중복 등록 의심 ❓. 다른 캡처끼리 겹친 건 1건으로 합친다.
- 해제 지시 종목이 반영 목록에 없으면 해제 반영으로 본다(✅, 비고 표시).
- 판독불가가 있거나, AI가 캡처 잘림 같은 문제를 보고하면 "전체 일치"를 선언하지 않는다(🔎 검증 미완료).
- 등록일시가 보이면 비고에 참고로 표시한다(판정에는 안 씀).

## 비용·보안

- Gemini는 REST `generateContent`에 `responseJsonSchema`로 스키마를 강제한다. 모델이 스키마 일부를 거부하면(400) 스키마를 프롬프트에 넣고 JSON 모드로 자동 재시도한다.
- Claude는 Opus 5.5가 기본이고 Sonnet 5.5(더 저렴)로 바꿀 수 있다. 서버측 refusal fallback(`fallbacks: "default"`)이 켜져 있어서, 안전 분류기가 드물게 거절하면 서버가 권장 모델로 자동 재시도한다.
- 처음 며칠은 같은 캡처를 Gemini·Claude 둘 다로 돌려 판독 결과가 같은지 확인하는 걸 권장한다.
- API 키와 첨부 자료는 브라우저에서 선택한 AI 회사(Google/Anthropic) API로만 바로 간다. 이 저장소나 다른 서버로 가지 않는다. 키는 AI별로 따로 저장된다.
- 저장소가 공개라서 API 키는 절대 커밋하지 않는다.

## 개발

```bash
node --test compliance/matcher.test.js
```

`vendor/anthropic-sdk-1.3.0.js`는 Anthropic 공식 JS SDK(`@anthropic-ai/sdk@1.3.0`, MIT)를 esbuild로 묶은 것이다.
CDN이 막힌 사내망이나 `file://`에서 열 때도 동작하게 하려고 넣었다. 다시 만들 때:

```bash
npm i @anthropic-ai/sdk@1.3.0 esbuild
echo 'import Anthropic from "@anthropic-ai/sdk"; window.Anthropic = Anthropic;' > entry.js
npx esbuild entry.js --bundle --minify --format=iife --platform=browser --target=es2020 --legal-comments=eof --outfile=compliance/vendor/anthropic-sdk-1.3.0.js
```
