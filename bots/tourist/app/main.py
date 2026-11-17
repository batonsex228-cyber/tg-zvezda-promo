"""Run Telegram and Mini App API in one process: python -m app.main.

Fail closed before SQLite migration: prevent exposing the wrong app on port 8000,
validate the real BotFather identity, and refuse a conflicting webhook.
"""
import asyncio
import uvicorn
from app.config import settings
from app.api import app
from app.runtime import assert_port_free, check_live_telegram, StartupError


async def main(*, host="127.0.0.1", port=8000):
    if settings.demo_mode and settings.bot_token:
        raise StartupError('DEMO_MODE=true нельзя использовать с токеном живого Telegram-бота.')
    if host == "127.0.0.1" and port == 8000:
        assert_port_free()
    else:
        assert_port_free(host=host, port=port)
    if settings.bot_token:
        meta = await check_live_telegram(settings.bot_token)
        print(f"[Telegram] Проверен бот @{meta['username']} (ID {meta['id']}); webhook не настроен.", flush=True)
    # Fail before concurrent API/bot startup if this DB belongs to another token.
    from app.database import assert_existing_bot_identity
    assert_existing_bot_identity()
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port,
                                           log_level='info', access_log=False))
    server_task = asyncio.create_task(server.serve())
    if not settings.bot_token:
        await server_task
        return
    from app.bot import polling  # Import aiogram only when Telegram is enabled.
    bot_task = asyncio.create_task(polling())
    try:
        done, _ = await asyncio.wait((server_task, bot_task), return_when=asyncio.FIRST_COMPLETED)
        if bot_task in done:
            server.should_exit = True
            await server_task
            bot_task.result()  # Show actual bot startup failure.
        else:
            bot_task.cancel()
            await asyncio.gather(bot_task, return_exceptions=True)
            server_task.result()
            if not server.started:
                raise StartupError('FastAPI не открыл порт 8000. Проверьте занятость порта и права Windows.')
    finally:
        if not bot_task.done():
            bot_task.cancel()
            await asyncio.gather(bot_task, return_exceptions=True)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (StartupError, RuntimeError) as exc:
        print(f'[START ERROR] {exc}', flush=True)
        raise SystemExit(1) from None
