"""Offline relay checks - no Telegram token or external network required."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
import os
import tempfile
import sys

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings, _telegram_api_base_url, load_settings
from app.db import Database
from app.telegram_adapter import TelegramAdapter, TelegramAPIError

WORKER = 'https://telegram-api-proxy.aleksejnazarov93583.workers.dev'
FAKE_TOKEN = '100000:dummy_local_testing_token'


def settings_for(folder: Path, base: str, key=None) -> Settings:
    return Settings(
        site_url='https://zvezdaglazov.ru/', kb_file=folder/'kb.json',
        db_file=folder/'db.sqlite3', crawl_max_pages=40,
        openai_api_key=None, openai_model='test', faq_min_score=.72,
        retrieval_min_score=.48, camp_name='test', debug=False,
        show_source_links=False, telegram_bot_token=FAKE_TOKEN,
        telegram_api_base_url=base, telegram_relay_key=key,
    )


async def check_http(base_url: str, secret=None):
    requests = []

    def mock_worker(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if secret is not None and request.headers.get('X-Relay-Key') != secret:
            return httpx.Response(401, text='Unauthorized')
        method = request.url.path.rsplit('/', 1)[-1]
        if method == 'getMe':
            return httpx.Response(200, json={'ok':True,'result':{'id':17,'username':'mock_bot'}})
        if method == 'getUpdates':
            return httpx.Response(200, json={'ok':True,'result':[]})
        if method == 'sendMessage':
            return httpx.Response(200, json={'ok':True,'result':{'message_id':104}})
        if method == 'setMessageReaction':
            return httpx.Response(200, json={'ok':True,'result':True})
        return httpx.Response(200, json={'ok':True,'result':True})

    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)
        settings=settings_for(path,base_url,secret)
        bot=TelegramAdapter(settings,None,Database(settings.db_file),None)
        await bot.client.aclose()
        bot.client=httpx.AsyncClient(transport=httpx.MockTransport(mock_worker),timeout=40)
        try:
            assert (await bot.validate())['username']=='mock_bot'
            assert await bot.api('getUpdates',offset=10,timeout=25) == []
            assert (await bot.api('sendMessage',chat_id=123,text='Привет'))['message_id']==104
            assert await bot.react_heart(123,55)
            assert all(r.method=='POST' for r in requests)
            for r in requests:
                assert str(r.url).startswith(base_url + '/bot' + FAKE_TOKEN + '/')
                assert r.headers.get('X-Relay-Key')==(secret or None)
            assert b'"timeout":25' in requests[1].content
            assert requests[3].url.path.endswith('/setMessageReaction')
        finally:
            await bot.close()


def test_env_validation():
    assert _telegram_api_base_url(WORKER+'/') == WORKER
    assert _telegram_api_base_url('') == 'https://api.telegram.org'
    for invalid in [
        'http://api.telegram.org',
        'https://evil.invalid/bot',
        'https://evil.invalid/bot123:abc/getMe',
        'https://user:password@evil.invalid',
        'https://evil.invalid/?token=123',
        'https://evil.invalid/#fragment',
        'file:///etc/passwd',
        'https://',
    ]:
        try:
            _telegram_api_base_url(invalid)
        except RuntimeError:
            pass
        else:
            raise AssertionError('Unsafe URL was accepted: ' + invalid)


def test_load_from_env():
    """Production .env is not read or written; fake environment gets validated."""
    # load_settings loads a project .env if present, then accepts environment overrides
    with tempfile.TemporaryDirectory() as tmp:
        required = {
            'TELEGRAM_BOT_TOKEN': FAKE_TOKEN,
            'TELEGRAM_API_BASE_URL': WORKER,
            'TELEGRAM_RELAY_KEY': 'local-test-secret',
            'KB_FILE': str(Path(tmp)/'kb.json'),
            'DB_FILE': str(Path(tmp)/'db.sqlite3'),
        }
        before={key:os.environ.get(key) for key in required}
        try:
            os.environ.update(required)
            s=load_settings()
            assert s.telegram_api_base_url==WORKER
            assert s.telegram_relay_key=='local-test-secret'
        finally:
            for key,val in before.items():
                if val is None:
                    os.environ.pop(key,None)
                else:
                    os.environ[key]=val


async def check_auth_errors():
    with tempfile.TemporaryDirectory() as tmp:
        settings=settings_for(Path(tmp),WORKER)
        bot=TelegramAdapter(settings,None,Database(settings.db_file),None)
        await bot.client.aclose()
        bot.client=httpx.AsyncClient(transport=httpx.MockTransport(
            lambda req: httpx.Response(403,text='Forbidden, no key')
        ))
        try:
            try: await bot.api('getMe')
            except TelegramAPIError as exc:
                assert exc.code == 403
                assert 'TELEGRAM_RELAY_KEY' in str(exc)
                assert FAKE_TOKEN not in str(exc)
            else:
                raise AssertionError('403 was not recognized')
        finally:
            await bot.close()

        bot=TelegramAdapter(settings,None,Database(settings.db_file),None)
        await bot.client.aclose()
        # URL leaks must not get into an exception from httpx.ConnectError.
        def network_fail(req):
            raise httpx.ConnectError(f'Connection failed at {req.url}',request=req)
        bot.client=httpx.AsyncClient(transport=httpx.MockTransport(network_fail))
        try:
            try: await bot.api('getMe')
            except TelegramAPIError as exc:
                assert 'ConnectError' in str(exc)
                assert FAKE_TOKEN not in str(exc)
            else: raise AssertionError('Network failure not detected')
        finally:
            await bot.close()


async def run():
    test_env_validation()
    test_load_from_env()
    await check_http('https://api.telegram.org')
    await check_http(WORKER)
    await check_http(WORKER,'local-test-secret')
    await check_auth_errors()
    print('TELEGRAM CLOUDFLARE RELAY TEST: PASS (direct, relay, header, auth, safety)')


if __name__=='__main__':
    asyncio.run(run())
