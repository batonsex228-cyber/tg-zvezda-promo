"""Hermetic tests: Cloudflare relay for polling, startup checks and notifications."""
from types import SimpleNamespace
import asyncio
import httpx
import pytest
from app import telegram_transport as transport
from scripts import verify_telegram

WORKER = 'https://example-proxy.workers.dev'
TOKEN = '123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456'

def test_relay_url_is_strict_https_root_only(monkeypatch):
    monkeypatch.setattr(transport,'settings',SimpleNamespace(telegram_api_base_url=WORKER,telegram_relay_key='secret'))
    assert transport.method_url(TOKEN,'getMe') == WORKER+'/bot'+TOKEN+'/getMe'
    assert transport.relay_headers() == {'X-Relay-Key':'secret'}
    for url in ('http://bad.example','https://bad.example/path','https://user:pw@bad.example','https://bad.example?x=1'):
        with pytest.raises(ValueError):
            transport.api_origin(url)

def test_live_identity_check_follows_worker_url_and_header(monkeypatch):
    monkeypatch.setattr(transport,'settings',SimpleNamespace(telegram_api_base_url=WORKER,telegram_relay_key='secret'))
    seen=[]
    def handler(request):
        seen.append((str(request.url),request.headers.get('X-Relay-Key')))
        if request.url.path.endswith('/getMe'):
            return httpx.Response(200,json={'ok':True,'result':{'id':123456,'is_bot':True,'username':'touristdemo'}})
        return httpx.Response(200,json={'ok':True,'result':{'url':'','pending_update_count':0}})
    result=verify_telegram.check_bot(TOKEN,transport=httpx.MockTransport(handler))
    assert result['username']=='touristdemo'
    assert all(url.startswith(WORKER+'/bot'+TOKEN+'/') and key=='secret' for url,key in seen)
    assert len(seen)==2

def test_aiogram_session_custom_base_and_relay_header(monkeypatch):
    pytest.importorskip('aiogram')
    monkeypatch.setattr(transport,'settings',SimpleNamespace(telegram_api_base_url=WORKER,telegram_relay_key='secret'))
    async def check():
        session=transport.build_aiogram_session()
        try:
            assert session.api.api_url(TOKEN,'getUpdates') == WORKER+'/bot'+TOKEN+'/getUpdates'
            assert session.api.file_url(TOKEN,'hello.dat') == WORKER+'/file/bot'+TOKEN+'/hello.dat'
            client=await session.create_session()
            assert client.headers.get('X-Relay-Key')=='secret'
        finally:
            await session.close()
    asyncio.run(check())
