"""v0.4 integration hardening: signed auth, migration, ownership, concurrency, delivery leases."""
from app.version import VERSION
import hashlib
import hmac
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from app import api, config, database, notifications, service, sheets
from app.security import verify_init_data, AuthError
from scripts.doctor import diagnose

BOT_TOKEN = '987654321:VALID_TEST_TOKEN_ONLY_NO_REAL_TELEGRAM'
OTHER_TOKEN = '987654321:OTHER_TEST_TOKEN_ONLY_NO_REAL_TELEGRAM'


def sign_user(token=BOT_TOKEN, uid=100, age=0, user="__default__"):
    details={'id':uid,'first_name':'Тестовый гость'} if user == '__default__' else user
    fields={'auth_date':str(int(time.time())-age),
            'user':json.dumps(details, ensure_ascii=False, separators=(',',':'))}
    text='\n'.join(f'{k}={v}' for k,v in sorted(fields.items()))
    key=hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    fields['hash']=hmac.new(key, text.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_identity_binding_blocks_token_rotation_without_destroying_data(ready,monkeypatch):
    s1=replace(ready, bot_token=BOT_TOKEN, demo_mode=False)
    monkeypatch.setattr(database, 'settings', s1)
    database.bind_bot_identity()
    assert service.get_user(100)['nickname']=='Ник100'
    with database.session() as c:
        fingerprint=c.execute('SELECT token_fingerprint FROM bot_identity WHERE id=1').fetchone()[0]
    assert fingerprint==database.token_fingerprint(BOT_TOKEN)
    assert BOT_TOKEN not in fingerprint
    database.bind_bot_identity()  # idempotent
    s2=replace(s1,bot_token=OTHER_TOKEN)
    monkeypatch.setattr(database,'settings',s2)
    with pytest.raises(RuntimeError,match='другому Telegram-боту'):
        database.bind_bot_identity()
    assert service.get_user(100)['nickname']=='Ник100'
    info=diagnose('live',Path(__file__).resolve().parents[1],s2,require_packages=False)
    assert any(x['level']=='ERROR' and 'другому боту' in x['message'] for x in info)
    assert all(BOT_TOKEN not in x['message'] and OTHER_TOKEN not in x['message'] for x in info)


def test_new_client_database_with_new_token_does_not_contain_staff(ready,monkeypatch,tmp_path):
    first=replace(ready,bot_token=BOT_TOKEN)
    monkeypatch.setattr(database,'settings',first)
    database.bind_bot_identity()
    service.set_role(42,100,'admin')
    second=replace(first,bot_token=OTHER_TOKEN,database_path=str(tmp_path/'client.sqlite3'))
    monkeypatch.setattr(database,'settings',second)
    monkeypatch.setattr(service,'settings',second)
    database.init_db()
    database.bind_bot_identity()
    assert service.get_user(100) is None
    assert service.ensure_user(100)['role']=='guest'


def test_forged_initdata_rejected_even_with_demo_header(ready,next_thursday,monkeypatch):
    live=replace(ready,bot_token=BOT_TOKEN,demo_mode=False)
    for mod in (config,database,service,api,notifications,sheets):
        monkeypatch.setattr(mod,'settings',live)
    with TestClient(api.app) as client:
        assert client.get('/health').json()['version']==VERSION
        assert client.get('/api/me',headers={'X-Demo-User-ID':'42'}).status_code==401
        assert client.get('/api/admin/users',headers={'X-Telegram-Init-Data':sign_user(uid=100)}).status_code==403
        assert client.get('/api/me',headers={'X-Telegram-Init-Data':sign_user(token=OTHER_TOKEN)}).status_code==401
        assert client.get('/api/me',headers={'X-Telegram-Init-Data':sign_user(age=100000)}).status_code==401
        valid={'X-Telegram-Init-Data':sign_user(uid=100)}
        assert client.get('/api/me',headers=valid).status_code==200
        assert client.get('/api/me',headers={'X-Telegram-Init-Data':sign_user(uid=42)}).json()['user']['role']=='owner'
        ev=service.create_event(42,'mafia','Подписанный тест',next_thursday,10,'classic')
        rid=client.post(f'/api/events/{ev["id"]}/join',headers=valid).json()['id']
        assert client.get('/api/admin/pending',headers={'X-Telegram-Init-Data':sign_user(uid=100)}).status_code==403
        admin={'X-Telegram-Init-Data':sign_user(uid=42)}
        assert client.post('/api/admin/decide',headers=admin,json={'category':'event','request_id':rid,'approve':True}).status_code==200
        assert client.get('/api/me',headers=valid).json()['requests']['events'][0]['status']=='confirmed'
        assert client.post(f'/api/event/{rid}/cancel',headers=valid).status_code==200
        assert client.post('/api/admin/decide',headers=admin,json={'category':'event','request_id':rid,'approve':True}).json()['status']=='cancelled'
        assert client.get('/api/me',headers=valid).json()['requests']['events'][0]['status']=='cancelled'


@pytest.mark.parametrize('user',[[],None,True,1,{'id':True}, {'id':0}, {'id':-1}, {'id':'invalid'}])
def test_malformed_signed_telegram_payloads_return_auth_error(user):
    with pytest.raises(AuthError):
        verify_init_data(sign_user(user=user),BOT_TOKEN)


def test_phone_and_personal_details_not_exposed_by_public_apis(ready,next_thursday):
    e=service.create_event(42,'mafia','Мафия',next_thursday,10,'classic')
    a=service.join_event(100,e['id']);service.decide(42,'event',a,True)
    with TestClient(api.app) as client:
        public=client.get('/api/schedule').text+client.get(f'/api/events/{e["id"]}/confirmed').text
        assert 'phone' not in public and '+7999' not in public and 'full_name' not in public
        private=client.get('/api/admin/pending',headers={'X-Demo-User-ID':'100'})
        assert private.status_code==403


def test_two_guests_cannot_book_last_event_place(ready):
    d=(datetime.now(timezone.utc)+timedelta(days=2)).replace(hour=17,minute=0,second=0,microsecond=0)
    event=service.create_event(42,'poker','Тест последнего места',d.isoformat(),1,stack='10000',blinds='100/200')
    def submit(uid):
        try:
            return ('ok',service.join_event(uid,event['id']))
        except service.BusinessError as exc:
            return ('error',exc.status)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(submit,[100,101]))
    assert sorted(x[0] for x in results)==['error','ok']
    assert [x['occupied'] for x in service.list_events()]==[1]


def test_notification_claim_lease_prevents_parallel_senders(fresh):
    with database.session(write=True) as c:
        service.enqueue(c,100,'Проверка очереди')
    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed=list(pool.map(lambda _:notifications.claim_due_messages(),[1,2]))
    assert sorted(len(x) for x in claimed)==[0,1]
    assert notifications.due_messages()==[]
    row=(claimed[0] or claimed[1])[0]
    notifications.record_outcome(row['id'],True)
    assert notifications.pending_status()['sent']==1


def test_crashed_notification_worker_retries_after_lease(fresh):
    with database.session(write=True) as c:
        service.enqueue(c,100,'Напоминание')
    item=notifications.claim_due_messages()[0]
    assert not notifications.claim_due_messages()
    with database.session(write=True) as c:
        c.execute('UPDATE notification_outbox SET next_attempt_at=? WHERE id=?',
                  ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(timespec='seconds'),item['id']))
    assert notifications.claim_due_messages()[0]['id']==item['id']


def test_event_and_billiard_cancelled_at_same_time_do_not_affect_each_other(ready,next_thursday):
    e=service.create_event(42,'mafia','Тест обеих очередей',next_thursday,10,'classic')
    r=service.join_event(100,e['id'])
    btime=(datetime.now(timezone.utc)+timedelta(days=1)).replace(hour=18,minute=0,second=0,microsecond=0)
    b=service.billiard_book(100,btime.isoformat(),1,2)
    service.request_cancel(100,'event',r)
    service.decide(42,'event',r,True)
    assert service.my_requests(100)['events'][0]['status']=='cancelled'
    assert service.my_requests(100)['billiard'][0]['status']=='pending'
    service.decide(42,'billiard',b,True)
    assert service.my_requests(100)['billiard'][0]['status']=='confirmed'


def test_deleting_events_by_query_string_is_not_possible(fresh):
    with TestClient(api.app) as client:
        assert client.get('/api/billiard/busy?date=2026-05-05%27%3BDROP%20TABLE%20users%3B--').status_code==400
        assert service.get_user(42) is not None


def test_manual_backup_while_wal_is_active(ready,tmp_path):
    from sqlite3 import connect
    src=Path(ready.database_path)
    dst=tmp_path/'copy.sqlite3'
    with connect(src) as source,connect(dst) as target:
        source.backup(target)
    with connect(dst) as c:
        assert c.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        assert c.execute('SELECT COUNT(*) FROM users').fetchone()[0]==4

@pytest.mark.parametrize('status,expected',[(200,'sent'),(503,'pending'),(403,'failed')])
def test_notification_delivery_mocked_telegram_responses(fresh,status,expected):
    import asyncio
    import httpx
    with database.session(write=True) as c:
        service.enqueue(c,100,'Проверка ответа Telegram')
    row=notifications.claim_due_messages()[0]
    async def simulate():
        def responder(request):
            assert request.url.path.endswith('/sendMessage')
            data=json.loads(request.content)
            assert data['chat_id']==100 and 'Telegram' in data['text']
            return httpx.Response(status, json={'ok':status==200})
        async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as client:
            await notifications.send_once(client,row)
    asyncio.run(simulate())
    with database.session() as c:
        result=c.execute('SELECT state,attempts FROM notification_outbox WHERE id=?',(row['id'],)).fetchone()
    assert result['state']==expected and result['attempts']==1


def test_google_sheets_fake_sync_is_revision_safe(ready,monkeypatch):
    import sys
    from types import SimpleNamespace
    original=sheets.settings
    enabled=replace(ready,google_sheet_id='FAKE_SHEET_ID',google_credentials_file='fake-credentials.json')
    monkeypatch.setattr(sheets,'settings',enabled)
    updates={}
    class FakeTab:
        def __init__(self,name):self.name=name
        def clear(self):updates.setdefault(self.name,[]).append('clear')
        def update(self,range_name,values,value_input_option):
            assert range_name=='A1' and value_input_option=='RAW'
            updates.setdefault(self.name,[]).append(values)
    class FakeBook:
        def worksheet(self,name):
            if name not in updates:
                raise FakeGspread.WorksheetNotFound()
            return FakeTab(name)
        def add_worksheet(self,title,rows,cols):return FakeTab(title)
    class FakeGspread:
        class WorksheetNotFound(Exception):pass
        @staticmethod
        def service_account(filename):
            assert filename==str((sheets.ROOT/'fake-credentials.json').resolve())
            return SimpleNamespace(open_by_key=lambda key:FakeBook())
    monkeypatch.setitem(sys.modules,'gspread',FakeGspread)
    assert sheets.sync_once()=='synced'
    assert sorted(updates)==['Бильярд','Гости','Заявки','История','События']
    assert any('Ник100' in str(x) for x in updates['Гости'])
    assert sheets.sync_once()=='up-to-date'
    service.set_profile(100,'Новое Имя','+79990000100','Ник100')
    assert sheets.sync_once()=='synced'
    assert sheets.status()['revision']==sheets.status()['synced_revision']


def test_google_sync_failure_records_error_and_can_retry(fresh,monkeypatch):
    import sys
    from types import SimpleNamespace
    enabled=replace(fresh,google_sheet_id='TEST',google_credentials_file='fake.json')
    monkeypatch.setattr(sheets,'settings',enabled)
    class Broken:
        @staticmethod
        def service_account(filename):
            raise ConnectionError('Тестовый отказ Google')
    monkeypatch.setitem(sys.modules,'gspread',Broken)
    with pytest.raises(ConnectionError):sheets.sync_once(force=True)
    assert sheets.status()['last_error'] == 'ConnectionError'
    assert sheets.status()['synced_once']==0 and sheets.status()['last_error']


def test_doctor_does_not_print_secret_strings(ready):
    private=replace(ready,bot_token=BOT_TOKEN)
    issues=diagnose('live',Path(__file__).resolve().parents[1],private,require_packages=False)
    rendered=json.dumps(issues,ensure_ascii=False)
    assert BOT_TOKEN not in rendered and 'VALID_TEST_TOKEN' not in rendered


def test_existing_schema_migrates_with_new_identity_table(ready):
    database.init_db()
    with database.session() as c:
        tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert 'bot_identity' in tables
    assert service.get_user(42)['role']=='owner'


def test_empty_google_sheet_receives_headers_on_first_sync(fresh,monkeypatch):
    import sys
    from types import SimpleNamespace
    enabled=replace(fresh,google_sheet_id='TEST',google_credentials_file='fake.json')
    monkeypatch.setattr(sheets,'settings',enabled)
    rows=[]
    class Tab:
        def clear(self):pass
        def update(self,range_name,values,value_input_option):rows.append(values)
    class Gspread:
        class WorksheetNotFound(Exception):pass
        @staticmethod
        def service_account(filename):
            return SimpleNamespace(open_by_key=lambda _:SimpleNamespace(worksheet=lambda name:Tab()))
    monkeypatch.setitem(sys.modules,'gspread',Gspread)
    assert sheets.status()['revision']>=1  # Initial guests now count as changes.
    assert sheets.sync_once()=='synced'
    assert len(rows)==5
    assert sheets.status()['synced_once']==1


def test_simultaneous_schema_initialization_does_not_break(fresh):
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(lambda _:database.init_db(),(1,2)))
    assert outcomes==[None,None]
    assert service.get_user(42)['telegram_id']==42
