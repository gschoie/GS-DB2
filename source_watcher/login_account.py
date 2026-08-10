"""텔레그램 계정 세션을 한 번 만든다. `telegram_account` 소스를 쓰기 전 준비 단계다.

봇 토큰으로는 '내가 구독한 채널'을 읽을 수 없다. 봇은 자기가 초대된 방만 보기 때문이다.
그래서 채널을 일일이 지정하지 않고 전부 훑으려면 내 계정으로 한 번 로그인해 두어야 한다.

    pip install telethon
    python login_account.py            # 전화번호 → 인증코드 (2단계 암호가 있으면 그것도)
    python login_account.py --string   # 서버·CI에 넣을 세션 문자열까지 출력

만들어진 세션 파일(data/telegram_user.session)은 계정 그 자체나 다름없다.
저장소에 올리지 말 것 — .gitignore에서 제외한다.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SESSION_PATH = "data/telegram_user"


def load_dotenv() -> None:
    """telegram_research_dashboard와 같은 방식. 이미 있는 환경변수는 덮지 않는다."""
    for path in (BASE_DIR / ".env", BASE_DIR.parent / "telegram_research_dashboard" / ".env"):
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description="텔레그램 계정 세션을 만든다")
    cli.add_argument("--string", action="store_true",
                     help="세션 문자열도 출력(서버·GitHub Actions에 넣을 때)")
    args = cli.parse_args(argv)

    load_dotenv()
    api_id = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    if not api_id or not api_hash:
        print("TELEGRAM_API_ID / TELEGRAM_API_HASH가 필요합니다.", file=sys.stderr)
        print("https://my.telegram.org → API development tools 에서 발급받아 .env에 넣으세요.", file=sys.stderr)
        return 2

    try:
        # telethon.sync 를 거쳐야 await 없이 쓸 수 있다(대화형 로그인에는 이쪽이 편하다).
        from telethon.sessions import StringSession
        from telethon.sync import TelegramClient
    except ImportError:
        print("telethon이 필요합니다: pip install telethon", file=sys.stderr)
        return 2

    session_path = os.environ.get("TELEGRAM_SESSION_PATH", DEFAULT_SESSION_PATH)
    Path(BASE_DIR / session_path).parent.mkdir(parents=True, exist_ok=True)

    with TelegramClient(session_path, int(api_id), api_hash) as client:
        me = client.get_me()
        print(f"로그인 완료: {me.first_name or ''} (@{me.username or '아이디없음'})")
        channels = sum(
            1 for dialog in client.iter_dialogs() if getattr(dialog.entity, "broadcast", False)
        )
        print(f"구독 중인 채널 {channels}개 — 이만큼이 감시 대상이 됩니다.")
        if args.string:
            print("\n세션 문자열(외부에 노출하지 말 것):")
            print(StringSession.save(client.session))

    print(f"\n세션 파일: {BASE_DIR / session_path}.session")
    print("이제 sources.yml의 telegram_account 소스를 enabled: true 로 바꾸고")
    print("  python watch_sources.py --check --only ship_all")
    print("로 무엇이 잡히는지 먼저 확인하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
