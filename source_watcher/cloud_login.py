"""GitHub Actions 안에서 텔레그램 계정 로그인을 끝내는 스크립트. PC가 필요 없다.

텔레그램 로그인은 '전화번호 → 앱으로 온 인증코드 입력' 두 단계라 한 번에 끝나지 않는다.
그래서 워크플로를 두 번 나눠 돌린다.

    request : 인증코드를 내 텔레그램 앱으로 보낸다. 이때 만든 임시 세션과
              phone_code_hash를 파일로 남긴다(코드 확인 때 같은 세션이어야 한다).
    confirm : 앱으로 온 코드(TELEGRAM_LOGIN_CODE 시크릿)로 로그인을 마치고
              완성된 세션 문자열을 파일로 남긴다.

이 스크립트는 평문 파일만 다룬다. 암호화(SESSION_PASSPHRASE)와 커밋은 워크플로
(telegram-login.yml)가 한다 — 러너는 실행이 끝나면 통째로 사라지므로 평문이 남지 않는다.

주의: 앱으로 온 인증코드를 텔레그램 대화창에 그대로 적어 보내면 텔레그램이 그 코드를
즉시 무효화한다. 코드는 GitHub 시크릿에만 넣을 것.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def need(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"시크릿 {name}이(가) 비어 있습니다 — 저장소 Settings → Secrets에 등록하세요.", file=sys.stderr)
        raise SystemExit(2)
    return value


async def request(out_path: Path) -> None:
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    client = TelegramClient(StringSession(), int(need("TELEGRAM_API_ID")), need("TELEGRAM_API_HASH"))
    await client.connect()
    try:
        sent = await client.send_code_request(need("TELEGRAM_PHONE"))
        out_path.write_text(
            json.dumps({"session": StringSession.save(client.session), "phone_code_hash": sent.phone_code_hash}),
            encoding="utf-8",
        )
    finally:
        await client.disconnect()
    print("인증코드를 보냈습니다. 텔레그램 앱에 도착한 숫자를 TELEGRAM_LOGIN_CODE 시크릿에 넣고")
    print("이 워크플로를 step=confirm 으로 다시 실행하세요. 코드는 몇 분이면 만료됩니다.")


async def confirm(pending_path: Path, out_path: Path) -> None:
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError
    from telethon.sessions import StringSession

    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    client = TelegramClient(
        StringSession(pending["session"]), int(need("TELEGRAM_API_ID")), need("TELEGRAM_API_HASH")
    )
    await client.connect()
    try:
        try:
            await client.sign_in(
                phone=need("TELEGRAM_PHONE"),
                code=need("TELEGRAM_LOGIN_CODE"),
                phone_code_hash=pending["phone_code_hash"],
            )
        except SessionPasswordNeededError:
            # 계정에 2단계 인증(클라우드 비밀번호)이 걸려 있는 경우
            password = os.environ.get("TELEGRAM_2FA_PASSWORD", "").strip()
            if not password:
                print("이 계정은 2단계 인증이 걸려 있습니다 — TELEGRAM_2FA_PASSWORD 시크릿을 "
                      "등록하고 confirm을 다시 실행하세요.", file=sys.stderr)
                raise SystemExit(2)
            await client.sign_in(password=password)

        me = await client.get_me()
        channels = 0
        async for dialog in client.iter_dialogs():
            if getattr(dialog.entity, "broadcast", False):
                channels += 1
        out_path.write_text(StringSession.save(client.session), encoding="utf-8")
        # 세션 문자열은 로그에 절대 찍지 않는다 — 공개 저장소의 Actions 로그는 누구나 본다.
        print(f"로그인 완료: @{me.username or '(아이디 없음)'} · 구독 채널 {channels}개가 감시 대상이 됩니다.")
    finally:
        await client.disconnect()


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description="Actions 러너 안에서 텔레그램 계정 로그인")
    cli.add_argument("step", choices=["request", "confirm"])
    cli.add_argument("--pending", type=Path, default=Path("login_pending.json"),
                     help="request가 남기고 confirm이 읽는 임시 세션 파일(평문)")
    cli.add_argument("--out", type=Path, default=Path("session_string.txt"),
                     help="confirm이 남기는 완성 세션 문자열 파일(평문)")
    args = cli.parse_args(argv)

    try:
        import telethon  # noqa: F401
    except ImportError:
        print("telethon이 필요합니다: pip install telethon", file=sys.stderr)
        return 2

    if args.step == "request":
        asyncio.run(request(args.pending))
    else:
        if not args.pending.exists():
            print("임시 세션 파일이 없습니다 — 먼저 step=request 를 실행하세요.", file=sys.stderr)
            return 2
        asyncio.run(confirm(args.pending, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
