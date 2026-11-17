"""Telegram Bot API transport for Tourist: direct or trusted HTTPS relay.

One origin for aiogram polling, preflight identity, notification outbox,
and Windows testing. Never log a BotFather token or relay secret.
"""
from urllib.parse import urlsplit
from app.config import settings

def api_origin(base_url=None):
    base = (settings.telegram_api_base_url if base_url is None else base_url).strip().rstrip('/')
    parsed = urlsplit(base)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment):
        raise ValueError('Telegram API: требуется доверенный HTTPS-домен без пути или параметров')
    return base

def method_url(token, method, base_url=None):
    return f'{api_origin(base_url)}/bot{token}/{method}'

def relay_headers(key=None):
    value = settings.telegram_relay_key if key is None else key
    return {'X-Relay-Key': value} if value else {}

def build_aiogram_session():
    # Importing aiogram lazily keeps offline configuration tests lightweight.
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.client.telegram import TelegramAPIServer

    class SessionWithRelayHeader(AiohttpSession):
        def __init__(self, relay_key, **kwargs):
            super().__init__(**kwargs)
            self.relay_key = relay_key

        async def create_session(self):
            client = await super().create_session()
            if self.relay_key:
                # aiohttp.ClientSession.headers is public and mutable.
                client.headers['X-Relay-Key'] = self.relay_key
            return client

    return SessionWithRelayHeader(
        relay_key=settings.telegram_relay_key,
        api=TelegramAPIServer.from_base(api_origin()),
    )
