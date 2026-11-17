"""v0.7: real-launch gates, webhook conflicts, tunnel health and safety.

Network calls use hermetic fakes. No real BotFather token is ever used here.
"""
from app.version import VERSION
import asyncio
import io
import json
import socket
from dataclasses import replace
from unittest.mock import patch

import httpx
import pytest
from app import main, config
from app.runtime import assert_port_free, check_live_telegram, StartupError
from scripts import run_tunnel
from scripts.verify_telegram import TelegramCheckError, check_bot

TOKEN = '123456789:This_is_a_Synthetic_Only_Test_Bot_Token_99999'


def test_free_port_probe_succeeds():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    assert_port_free(port=port)


def test_used_port_is_refused_and_message_contains_no_secrets():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        s.listen(1)
        with pytest.raises(StartupError, match='уже занят') as caught:
            assert_port_free(port=s.getsockname()[1])
    assert TOKEN not in str(caught.value)


def test_check_bot_before_live_start_success():
    def fake(token):
        assert token == TOKEN
        return {'username':'tourist_test_bot','id':123456789,'webhook_active':False}
    assert asyncio.run(check_live_telegram(TOKEN, checker=fake))['username']=='tourist_test_bot'


def test_live_preflight_refuses_webhook():
    def fake(_token):return {'id':123,'username':'fake','webhook_active':True}
    with pytest.raises(StartupError,match='webhook'):
        asyncio.run(check_live_telegram(TOKEN, checker=fake))


def test_live_preflight_redacts_failed_check():
    def fake(_token):raise TelegramCheckError('Токен не подтверждён')
    with pytest.raises(StartupError,match='Токен не подтверждён') as error:
        asyncio.run(check_live_telegram(TOKEN, checker=fake))
    assert TOKEN not in str(error.value)


def test_no_telegram_call_when_token_blank():
    def fail(_):raise AssertionError('no Telegram call expected')
    assert asyncio.run(check_live_telegram('',checker=fail))=={}


def test_main_rejects_demo_with_token_before_db_creation(monkeypatch, tmp_path):
    s=replace(config.settings,bot_token=TOKEN,demo_mode=True,database_path=str(tmp_path/'untouched.sqlite3'))
    monkeypatch.setattr(main,'settings',s)
    with pytest.raises(StartupError,match='DEMO_MODE'):
        asyncio.run(main.main())
    assert not (tmp_path/'untouched.sqlite3').exists()


def test_main_refuses_bad_telegram_before_db_creation(monkeypatch,tmp_path):
    s=replace(config.settings,bot_token=TOKEN,demo_mode=False,database_path=str(tmp_path/'untouched.sqlite3'))
    monkeypatch.setattr(main,'settings',s)
    monkeypatch.setattr(main,'assert_port_free',lambda:None)
    async def reject(_):raise StartupError('Нет связи с Telegram')
    monkeypatch.setattr(main,'check_live_telegram',reject)
    with pytest.raises(StartupError,match='Telegram'):
        asyncio.run(main.main())
    assert not (tmp_path/'untouched.sqlite3').exists()


def test_tunnel_health_waits_for_correct_version(monkeypatch):
    seen={'n':0}
    class FakeResponse:
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def read(self,*args):return b''
    def fake_urlopen(url,timeout=0):
        seen['n']+=1
        assert url=='http://127.0.0.1:8000/health'
        if seen['n']==1:raise ConnectionRefusedError('not yet')
        class Response(io.BytesIO):
            def __enter__(self):return self
            def __exit__(self,*args):pass
        return Response(json.dumps({'ok':True,'version':VERSION}).encode())
    monkeypatch.setattr('urllib.request.urlopen',fake_urlopen)
    monkeypatch.setattr(run_tunnel.time,'sleep',lambda _:None)
    class Alive:
        def poll(self):return None
    run_tunnel.wait_for_our_api(Alive(),seconds=4)
    assert seen['n']==2


def test_tunnel_refuses_wrong_server_identity(monkeypatch):
    class Response(io.BytesIO):
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr('urllib.request.urlopen',lambda *a,**kw: Response(b'{"ok":true,"version":"old-project"}'))
    class Alive:
        def poll(self):return None
    with pytest.raises(StartupError,match='другой сервер'):
        run_tunnel.wait_for_our_api(Alive(),seconds=2)


def test_tunnel_refuses_dead_server_early():
    class Dead:
        def poll(self):return 1
    with pytest.raises(StartupError,match='завершился'):
        run_tunnel.wait_for_our_api(Dead(),seconds=1)


def test_tunnel_resets_temp_menu_without_leaking_token(monkeypatch,capsys):
    seen=[]
    class FakeResponse:
        def raise_for_status(self):pass
        def json(self):return {'ok':True,'result':True}
    class FakeClient:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,json,headers=None):
            seen.append((url,json,headers));return FakeResponse()
    monkeypatch.setattr(httpx,'Client',FakeClient)
    assert run_tunnel.reset_temporary_menu(TOKEN)
    assert seen==[(f'https://api.telegram.org/bot{TOKEN}/setChatMenuButton',{'menu_button':{'type':'commands'}}, {})]
    assert TOKEN not in capsys.readouterr().out


def test_protocol_refuses_webhook_with_mock_bot_api():
    seen=[]
    def handler(request):
        seen.append(request.url.path.split('/')[-1])
        if request.url.path.endswith('getMe'):
            data={'ok':True,'result':{'id':123456789,'is_bot':True,'username':'tourist_test_bot'}}
        else:
            data={'ok':True,'result':{'url':'https://old.example/webhook','pending_update_count':12}}
        return httpx.Response(200,json=data)
    result=check_bot(TOKEN, transport=httpx.MockTransport(handler))
    assert seen==['getMe','getWebhookInfo']
    assert result['webhook_active'] is True
    assert result['pending_updates']==12


def test_protocol_valid_bot_with_no_webhook():
    def handler(request):
        payload=({'id':123456789,'is_bot':True,'username':'tourist_test_bot'}
                 if request.url.path.endswith('/getMe') else {'url':'','pending_update_count':0})
        return httpx.Response(200,json={'ok':True,'result':payload})
    result=check_bot(TOKEN,transport=httpx.MockTransport(handler))
    assert result['webhook_active'] is False


def test_no_public_file_or_secret_in_health(ready):
    from fastapi.testclient import TestClient
    from app.api import app
    with TestClient(app) as client:
        h=client.get('/health').json()
        assert h['version']==VERSION
        assert 'bot_token' not in h and 'database_path' not in h
        assert client.get('/assets/.env').status_code==404
        assert client.get('/assets/../.env').status_code==404

@pytest.fixture
def simulated_bot(monkeypatch):
    """Exercise our real async handler bodies without network or aiogram installation.

    This is a behavioral smoke, NOT a replacement for Telegram/aiogram testing.
    """
    import sys
    import types
    import importlib

    class Router:
        def message(self,*args,**kwargs):return lambda f:f
        def callback_query(self,*args,**kwargs):return lambda f:f
    class Dispatcher:
        def include_router(self,router):self.router=router
        async def start_polling(self,bot,**kwargs):bot.polling_started=True
    class Filter:
        def __init__(self,*args,**kwargs):pass
    class State:
        def __init__(self):pass
    class StatesGroup:pass
    class DTO:
        def __init__(self,**kwargs):self.__dict__.update(kwargs)
    class InlineKeyboardMarkup(DTO):pass
    class FakeBot:
        last=None
        def __init__(self,token,session=None):
            self.token=token; self.commands=[]; self.menu_button=None
            self.polling_started=False; self.session=types.SimpleNamespace(close=self.close)
            FakeBot.last=self
        async def close(self):pass
        async def set_my_commands(self,commands):self.commands=commands
        async def set_chat_menu_button(self,menu_button):self.menu_button=menu_button
    modules={}
    for name in ('aiogram','aiogram.fsm','aiogram.fsm.context', 'aiogram.fsm.state',
                 'aiogram.filters','aiogram.types'):
        modules[name]=types.ModuleType(name)
        modules[name].__path__=[]
    mods=modules
    mods['aiogram'].Router=Router
    mods['aiogram'].Dispatcher=Dispatcher
    mods['aiogram'].Bot=FakeBot
    mods['aiogram'].F=object()
    mods['aiogram.fsm.context'].FSMContext=object
    mods['aiogram.fsm.state'].State=State
    mods['aiogram.fsm.state'].StatesGroup=StatesGroup
    mods['aiogram.filters'].Command=Filter
    mods['aiogram.filters'].CommandStart=Filter
    for typename in ('Message','CallbackQuery','BotCommand','InlineKeyboardButton',
                     'InlineKeyboardMarkup','WebAppInfo','MenuButtonWebApp','MenuButtonCommands','KeyboardButton',
                     'ReplyKeyboardMarkup','ReplyKeyboardRemove'):
        setattr(mods['aiogram.types'],typename, type(typename,(DTO,),{}))
    for name,module in modules.items():monkeypatch.setitem(sys.modules,name,module)
    from app import telegram_transport
    monkeypatch.setattr(telegram_transport, 'build_aiogram_session', lambda: None)
    original=sys.modules.pop('app.bot',None)
    bot=importlib.import_module('app.bot')
    yield bot,FakeBot
    sys.modules.pop('app.bot',None)
    if original is not None:sys.modules['app.bot']=original


class _FakeState:
    def __init__(self):self.value=None;self.data={}
    async def clear(self):self.value=None;self.data={}
    async def set_state(self,state):self.value=state
    async def update_data(self,**values):self.data.update(values)
    async def get_data(self):return self.data.copy()


class _FakeMessage:
    def __init__(self, uid, text='', contact=None):
        from types import SimpleNamespace
        self.from_user=SimpleNamespace(id=uid,first_name='Тест')
        self.chat=SimpleNamespace(id=uid,type='private')
        self.text=text
        self.contact=contact
        self.sent=[]
        self.edited=False
    async def answer(self, text, reply_markup=None):
        self.sent.append((text,reply_markup))
    async def edit_reply_markup(self,reply_markup=None):
        self.edited=True


class _FakeCallback:
    def __init__(self,uid,data):
        from types import SimpleNamespace
        self.from_user=SimpleNamespace(id=uid)
        self.message=_FakeMessage(uid)
        self.data=data
        self.answers=[]
    async def answer(self,text=None,show_alert=False):self.answers.append(text)


def test_offline_bot_registration_app_and_inline_workflow(ready,next_thursday,simulated_bot,monkeypatch):
    from app import service
    bot,_=simulated_bot
    monkeypatch.setattr(bot,'settings',ready)
    state=_FakeState()
    msg=_FakeMessage(100)
    asyncio.run(bot.start(msg,state))
    assert any('Добро пожаловать' in text for text,_ in msg.sent)
    asyncio.run(bot.register(msg,state))
    assert state.value==bot.Registration.name
    msg.text='Гость клуба'
    asyncio.run(bot.register_name(msg,state))
    assert state.value==bot.Registration.phone
    msg.text='+79998887766'
    asyncio.run(bot.register_phone(msg,state))
    assert state.value==bot.Registration.nick
    msg.text='Капитан'
    asyncio.run(bot.register_nick(msg,state))
    assert service.get_user(100)['nickname']=='Капитан'
    event=service.create_event(42,'mafia','Тестовое событие',next_thursday,10,'classic')
    join=_FakeCallback(100,f'join:{event["id"]}')
    asyncio.run(bot.callback(join))
    assert 'Заявка №' in join.answers[0]
    req=service.my_requests(100)['events'][0]
    approve=_FakeCallback(42,f'decide:event:{req["id"]}:1')
    asyncio.run(bot.callback(approve))
    assert service.my_requests(100)['events'][0]['status']=='confirmed'
    assert approve.message.edited
    cancellation=_FakeCallback(100,f'cancel:event:{req["id"]}')
    asyncio.run(bot.callback(cancellation))
    assert service.my_requests(100)['events'][0]['status']=='cancel_requested'
    # URL was not yet configured; /app must describe tunnel setup clearly.
    asyncio.run(bot.open_app(msg))
    assert any('Приложение сейчас недоступно' in text for text,_ in msg.sent)


def test_offline_bot_sets_menu_commands_or_web_app(ready,simulated_bot,monkeypatch):
    bot,FakeBot=simulated_bot
    offline=replace(ready,bot_token=TOKEN,demo_mode=False,webapp_url='')
    monkeypatch.setattr(bot,'settings',offline)
    asyncio.run(bot.polling())
    assert FakeBot.last.polling_started
    assert type(FakeBot.last.menu_button).__name__=='MenuButtonCommands'
    assert any(c.command=='app' for c in FakeBot.last.commands)
    https=replace(offline,webapp_url='https://club-tunnel.trycloudflare.com')
    monkeypatch.setattr(bot,'settings',https)
    asyncio.run(bot.polling())
    assert type(FakeBot.last.menu_button).__name__=='MenuButtonWebApp'
    assert FakeBot.last.menu_button.web_app.url==https.webapp_url


def test_tunnel_reader_queue_is_bounded_and_process_stops_after_failure(monkeypatch):
    """A broken cloudflared must not leak child processes in the background."""
    from scripts import run_tunnel
    class FakeProcess:
        def __init__(self):
            self.stdout = io.StringIO('cloudflared exited without a URL\n')
            self.terminated = False
        def poll(self):return None if not self.terminated else 1
        def terminate(self):self.terminated = True
        def wait(self, timeout):return 1
        def kill(self):self.terminated = True
    fake = FakeProcess()
    monkeypatch.setattr(run_tunnel.subprocess,'Popen',lambda *a,**kw: fake)
    class BrokenQueue:
        def __init__(self,maxsize=0):
            assert maxsize == 100
        def get(self,timeout=None):raise RuntimeError('Fake reader failure')
        def put_nowait(self,line):pass
    monkeypatch.setattr(run_tunnel.queue,'Queue',BrokenQueue)
    with pytest.raises(RuntimeError, match='Fake reader'):
        run_tunnel.start_tunnel('fake-cloudflared',seconds=2)
    assert fake.terminated
