# 소스 감시 봇

블로그·텔레그램 채널에 새 글이 올라오면 텔레그램으로 밀어준다.
**소스를 늘릴 때 건드리는 파일은 `sources.yml` 하나뿐이다.** 파이썬 코드는 손대지 않는다.

## 소스 추가하는 법

`sources.yml`의 `sources:` 아래에 항목을 추가하고 커밋하면 끝이다.

```yaml
  - key: some_blog          # 상태 파일 식별자 — 한 번 정하면 바꾸지 말 것
    name: 보여줄 이름         # 텔레그램 메시지 머리에 찍힌다
    type: rss               # telegram | rss | web
    url: https://example.com/rss
    tags: [블로그]
```

넣기 전에 잡히는지 먼저 확인하는 것을 권한다.

```bash
python watch_sources.py --check --only some_blog
```

### 어떤 `type`을 쓰나

| 종류 | 쓸 때 | 필요한 키 |
|---|---|---|
| `telegram` | 공개 텔레그램 채널 (로그인·봇 초대 불필요) | `channel` (`@아이디` 또는 `https://t.me/아이디`) |
| `rss` | RSS/Atom이 있는 블로그·언론사. 네이버 블로그는 `https://rss.blog.naver.com/<블로그ID>.xml` | `url` |
| `web` | RSS도 텔레그램도 없을 때의 최후 수단. 사이트 개편에 그대로 깨진다 | `url`, `item_selector` |

## 조선 코멘트 감시 (`ship_all`) — 구독한 모든 채널에서 회사 이름 잡아내기

내 텔레그램 계정이 **가입해 있는 모든 채널**(비공개·초대링크 포함)을 훑어,
현대중공업·삼성중공업·한화오션 등 조선 관련 낱말이 든 글의 **걸린 문장만**
**@gs_sb_bot**으로 보낸다. 채널 목록을 관리할 필요가 없다 — 새 채널에 들어가면
다음 실행부터 자동으로 감시 대상이 된다. 낱말 목록은 `sources.yml`의
`x_ship_keywords`에서 고친다.

**리소스 걱정은 하지 않아도 된다.** 대화 목록 조회가 100개 단위 요청 몇 번이고,
새 글이 없는 방은 아예 히스토리를 요청하지 않는다. 채널 수백 개를 구독해도
실행당 몇십 초 수준이며, 이 저장소는 public이라 Actions 사용료도 없다.

### 준비 — PC 없이 GitHub 웹에서 전부 한다

봇 토큰으로는 '내가 구독한 채널'을 읽을 수 없어서(봇은 초대된 방만 본다)
**내 계정 세션**이 한 번의 로그인으로 필요하다. 로그인도 Actions 안에서 한다.

**1. 시크릿 등록** — 저장소 → Settings → Secrets and variables → Actions:

| 시크릿 이름 | 값 |
|---|---|
| `SHIP_TELEGRAM_BOT_TOKEN` | @BotFather가 준 **@gs_sb_bot**의 토큰 (`123456:AAE...`) |
| `SHIP_TELEGRAM_CHAT_ID` | 알림 받을 방의 chat_id (아래 '알아내는 법' 참고) |
| `TELEGRAM_API_ID` | my.telegram.org → API development tools의 api_id |
| `TELEGRAM_API_HASH` | 같은 곳의 api_hash |
| `TELEGRAM_PHONE` | 계정 전화번호, `+8210...` 국제 형식 |
| `SESSION_PASSPHRASE` | 아무 길고 무작위한 문자열 — 세션 암호화 열쇠. 한 번 정하면 유지 |

chat_id 알아내는 법: @gs_sb_bot에게 텔레그램에서 아무 말이나 보낸 뒤
`https://api.telegram.org/bot<토큰>/getUpdates`를 브라우저로 열면
`"chat":{"id":숫자}`가 보인다. 부호까지 그대로 넣는다.

**2. 로그인 (Actions → `텔레그램 계정 로그인` 워크플로, 두 번 실행)**

1. `Run workflow` → step: **request** — 인증코드가 내 텔레그램 앱으로 온다.
2. 앱에 온 숫자를 시크릿 **`TELEGRAM_LOGIN_CODE`** 로 등록한다.
   (⚠ 코드를 텔레그램 대화창에 적어 보내면 텔레그램이 즉시 무효화한다.
   코드는 몇 분이면 만료되니 바로 이어서 할 것. 2단계 인증 계정이면
   `TELEGRAM_2FA_PASSWORD` 시크릿도 등록.)
3. `Run workflow` → step: **confirm** — 로그인이 끝나고, 세션이
   `SESSION_PASSPHRASE`로 암호화되어 `state/session.enc`로 커밋된다.
   로그에 "로그인 완료 · 구독 채널 n개"가 찍히면 성공. `TELEGRAM_LOGIN_CODE`는
   지워도 된다.

이후 소스 감시 봇이 매 실행마다 그 암호문을 풀어 쓴다. 재로그인은 필요 없다.
세션 평문은 러너 안에서만 존재하고 로그에 찍히지 않으며, 저장소에는 암호문만
남는다(passphrase는 시크릿에만 있다). 세션을 폐기하려면 텔레그램 앱 →
설정 → 기기에서 해당 세션을 끊고 `state/session.enc`를 지우면 된다.

**3. 점검** — Actions → `소스 감시 봇` → Run workflow → mode: `test`,
only: `ship_all`. 최신 매칭 글 1건이 @gs_sb_bot으로 시험 발송된다.

로그인 전에도 다른 소스는 그대로 돈다 — `ship_all`만 수집 실패로 남을 뿐이다.

### 중복·소음을 막는 장치

- **내용 중복 제거(`dedupe_scope`)** — 채널들이 같은 리포트 요약을 퍼나르면 본문
  지문(min-hash)으로 알아채 **한 번만** 보낸다. 머리말 한 줄이 붙어 있어도 잡는다.
  `channels:`로 펼친 소스끼리는 자동으로 묶인다.
- **걸린 문장만 발송(`push: hit`)** — 긴 데일리 전문 대신 회사 이름이 걸린 줄만
  발췌해 오고, 알림 머리에 어느 회사(🚨) · 어느 채널(📡)인지 찍는다. 전문은 원문
  링크로 본다.
- **별칭 낱말 묶음(`match_any`)** — `한화오션: [한화오션, 대우조선해양, "042660"]`처럼
  회사 이름 아래 별칭·종목코드를 묶는다. 정규식이 아니라 글자 그대로 찾는다.

### 한 채널에서 원하는 자료만 받기

증권사 채널은 데일리·종목리포트·공지를 한 채널에 섞어 뿌리는 경우가 많다.
`match`(통과시킬 정규식)와 `exclude`(버릴 정규식)로 거른다. 제목과 본문 모두에 걸린다.

```yaml
    match: "개장전|꼭 알아야"
    exclude: "휴장|공지"
```

## 지금 등록된 소스

| key | 이름 | 종류 | 주소 |
|---|---|---|---|
| `ship_all` | 조선 코멘트 | telegram_account | 구독한 전 채널 → @gs_sb_bot (로그인 필요, 위 절 참고) |
| `mer` | 메르 | rss | `https://rss.blog.naver.com/ranto28.xml` |
| `hanwha_5things` | 한화 임혜윤 · 개장전 5가지 | telegram | `https://t.me/lim_econ` |

`hanwha_5things`에는 `match: "개장전|꼭 알아야|5가지"`가 걸려 있다. 채널이 데일리 말고
다른 자료도 올리기 때문이다. 채널 글을 전부 받고 싶으면 `match` 줄을 지우면 된다.

## 실행

```bash
pip install -r requirements.txt

python watch_sources.py                 # 수집 → 새 글 발송 → 상태 저장
python watch_sources.py --check         # 연결 점검만 (발송·저장 없음)
python watch_sources.py --dry-run       # 무엇이 나갈지 출력만
python watch_sources.py --only mer      # 특정 소스만
python watch_sources.py --seed          # 현재 글을 전부 '읽음' 처리 (발송 없음)
python watch_sources.py --test          # 발송 경로 점검 — 최신 글 1건 시험 발송
python watch_sources.py --max 1         # 소스당 발송 상한 임시 변경
```

`--test`는 토큰·chat_id·렌더링이 실제로 동작하는지 확인하는 용도다. 새 글이 올라올
때까지 기다리지 않고 각 소스의 최신 글 1건을 그대로 보낸다. **상태 파일을 건드리지
않으므로** 시험 발송한 글이 진짜 새 글로 다시 올 일은 없고, 정상 발송도 그대로 이어진다.

발송에는 환경변수 두 개가 필요하다. `--check` / `--dry-run` / `--seed` 는 필요 없다.

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

## 자동 실행

`.github/workflows/source-watcher.yml`이 KST 06~22시에 30분 간격으로 돌린다.
`Actions → 소스 감시 봇 → Run workflow`로 수동 실행할 수 있고, 이때 `mode`를
`check` / `dry-run` / `seed`로 골라 시험해 볼 수 있다.

## 봇 설정 — 값을 넣는 자리

발송 봇은 **@gs_macro_bot**을 쓴다. 토큰과 채팅방 ID는 코드에 넣지 않고
저장소 시크릿으로 넣는다. 넣는 자리는 딱 한 곳이다.

> GitHub 저장소 → **Settings** → **Secrets and variables** → **Actions**
> → **New repository secret**

여기에 두 개를 등록한다.

| 시크릿 이름 | 값 |
|---|---|
| `WATCH_TELEGRAM_BOT_TOKEN` | @BotFather가 준 `123456:AAE...` 형태의 토큰 |
| `WATCH_TELEGRAM_CHAT_ID` | 글을 받을 채팅방 ID (개인이면 숫자, 채널이면 `@채널아이디`) |

이 이름은 `.github/workflows/source-watcher.yml`의 `소스 감시 실행` 단계에서 읽는다.
이름을 바꾸고 싶으면 그 파일의 `env:` 블록만 고치면 된다.

```yaml
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.WATCH_TELEGRAM_BOT_TOKEN || secrets.KDEF_TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.WATCH_TELEGRAM_CHAT_ID || secrets.KDEF_TELEGRAM_CHAT_ID }}
```

`WATCH_*`를 등록하지 않으면 방산 브리핑이 쓰는 `KDEF_TELEGRAM_*`으로 자동 폴백한다.
방산 브리핑과 같은 방에서 받을 거라면 아무것도 등록하지 않아도 된다.

### `WATCH_TELEGRAM_CHAT_ID` 알아내는 법

1. 텔레그램에서 **@gs_macro_bot**과 대화를 시작해 아무 말이나 보낸다.
   (채널로 받을 거라면 봇을 그 채널의 관리자로 추가한다.)
2. 브라우저에서 아래를 연다. `<토큰>` 자리에 봇 토큰을 넣는다.

   ```
   https://api.telegram.org/bot<토큰>/getUpdates
   ```

3. 결과 JSON의 `"chat":{"id":123456789 ...}` 에 있는 숫자가 chat_id다.
   그룹·채널이면 `-100`으로 시작하는 음수가 나오는데, **부호까지 그대로** 넣는다.

### 내 PC에서 시험 발송

```bash
export TELEGRAM_BOT_TOKEN='123456:AAE...'
export TELEGRAM_CHAT_ID='123456789'
python watch_sources.py --only mer --max 1
```

토큰을 셸 히스토리에 남기고 싶지 않으면 `.env`에 적어두고 `set -a; . ./.env; set +a`로
불러온다. `.env`는 저장소에 올리지 말 것.

## 중복 발송을 막는 장치

같은 글이 두 번 오지 않게 하는 것이 이 봇의 핵심이다. 네 겹으로 막는다.

1. **상태 파일** `state/seen.json` — 이미 보낸 글의 uid를 소스별로 최대 300개 기억한다.
   러너는 매번 새 컨테이너라, 워크플로가 이 파일을 저장소에 **커밋**해야 다음 실행이 안다.
2. **첫 실행 시딩** — 새 소스는 첫 실행에서 아무것도 보내지 않고 현재 글을 전부 읽음
   처리한다. 그러지 않으면 피드에 있는 수십 건이 한꺼번에 쏟아진다. 다음 글부터 온다.
3. **`lookback_hours`** (기본 48) — 그보다 오래된 글은 미발송분이어도 보내지 않는다.
   피드가 통째로 갱신되거나 과거 글이 수정돼 다시 뜰 때의 역류를 막는다.
4. **`max_per_run`** (기본 5) — 한 번에 보낼 상한. 상한에 걸려 못 보낸 글도 읽음
   처리하므로, 밀린 글이 다음 실행에 다시 밀려오지 않는다.

`key`를 바꾸면 상태가 끊겨 그 소스가 '첫 실행'으로 되돌아간다. 이름만 바꾸고 싶으면
`key`는 두고 `name`만 고칠 것.

## 발송 형태

- `push: full` — 본문을 통째로. 텔레그램 소스의 기본값(그 자체가 완성된 글이라).
- `push: excerpt` — 제목 + 발췌 + 원문 링크. RSS/web의 기본값.
  발췌 길이는 `excerpt_chars`(기본 600).

4096자 제한에 걸리면 문단 경계에서 나눠 여러 통으로 보낸다.

증권사 리서치 원문 전문을 공개된 곳에 재배포하는 것은 저작권 문제가 될 수 있다.
이 봇이 개인 텔레그램으로만 보내고 대시보드에 공개 아카이브를 만들지 않는 이유다.

## 테스트

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

네트워크를 타지 않는다. 실제 `sources.yml`이 파싱되는지도 함께 검사하므로,
레지스트리를 잘못 고치면 워크플로가 발송 전에 멈춘다.

## 파일

| 파일 | 하는 일 |
|---|---|
| `sources.yml` | 소스 레지스트리 — **평소 손대는 유일한 파일** |
| `watch_sources.py` | 선별·중복판정·상태관리·발송 오케스트레이션 |
| `adapters.py` | 종류별 수집기(telegram/telegram_account/rss/web). 새 종류는 여기에 붙인다 |
| `notify.py` | 텔레그램 발송(분할·재시도) |
| `cloud_login.py` | Actions 안에서 계정 로그인 — `텔레그램 계정 로그인` 워크플로가 부른다 |
| `login_account.py` | PC에서 로그인하고 싶을 때의 대안 (`--string`으로 세션 문자열 출력) |
| `state/seen.json` | 이미 보낸 글 기록 — 손으로 고치지 말 것 |
| `state/session.enc` | 암호화된 계정 세션 — 로그인 워크플로가 만들고 감시 봇이 푼다 |
