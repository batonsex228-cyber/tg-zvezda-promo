"""Live startup gates: never expose a wrong local service through the Mini App tunnel.

These checks happen BEFORE uvicorn initializes/migrates the production SQLite DB.
They do not modify Telegram webhook settings or send any messages.
"""
import asyncio
import errno
import socket


class StartupError(RuntimeError):
    """Startup failure with a human-readable message and no credentials."""


def assert_port_free(host: str = '127.0.0.1', port: int = 8000) -> None:
    """Refuse if any process already occupies the local API port.

    This is a best-effort preflight, not a cross-process lock; uvicorn still owns
    the actual bind and reports any race at startup.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError as exc:
            if exc.errno in (errno.EADDRINUSE, errno.EACCES, 10048, 10013):
                raise StartupError(
                    f'Порт {port} уже занят или недоступен. Закройте другую копию «Турист» '
                    'или программу на этом порту; не открывайте HTTPS-туннель к чужому серверу.'
                ) from None
            raise StartupError('Не удалось проверить локальный порт сервера.') from None


async def check_live_telegram(bot_token: str, *, checker=None) -> dict:
    """Validate actual bot identity and reject existing webhook before touching DB.

    Offline demo skips this step. The checker is injectable for hermetic tests.
    """
    if not bot_token:
        return {}
    if checker is None:
        from scripts.verify_telegram import check_bot, TelegramCheckError
        checker = check_bot
    else:
        from scripts.verify_telegram import TelegramCheckError
    try:
        metadata = await asyncio.to_thread(checker, bot_token)
    except TelegramCheckError as exc:
        raise StartupError(f'Проверка Telegram не прошла: {exc}') from None
    if metadata.get('webhook_active'):
        raise StartupError('У бота активен webhook. Long polling не запустится. '
                           'Отключите прежний webhook вручную после проверки старого проекта.')
    return metadata
