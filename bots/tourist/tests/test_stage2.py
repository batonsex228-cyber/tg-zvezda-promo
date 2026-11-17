"""Stage 2: event editing, staff management, public availability and notification reliability."""
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest
from fastapi.testclient import TestClient
from app import service, notifications, database, api
from app.api import app


def test_edit_limits_and_closure(ready,next_thursday):
    e=service.create_event(42,'mafia','Мафия четверга',next_thursday,10,'classic')
    service.join_event(100,e['id'])
    with pytest.raises(service.BusinessError,match='лимит'):
        service.edit_event(42,e['id'],'mafia','Мафия четверга',next_thursday,0,'classic')
    # protect a valid schema with fewer places than existing applications
    for i in range(200,203):
        service.ensure_user(i)
        service.set_profile(i,f'Игрок {i}','+79991111'+str(i).zfill(3),'Тест'+str(i))
        service.join_event(i,e['id'])
    with pytest.raises(service.BusinessError,match='занятых'):
        service.edit_event(42,e['id'],'mafia','Мафия четверга',next_thursday,3,'classic')
    new=service.edit_event(42,e['id'],'mafia','Новая мафия',next_thursday,9,'classic',status='closed')
    assert new['status']=='closed'
    assert service.list_events()[0]['status']=='closed'
    with pytest.raises(service.BusinessError,match='закрыта'):
        service.join_event(101,e['id'])
    service.edit_event(42,e['id'],'mafia','Новая мафия',next_thursday,9,'classic',status='open')
    assert service.join_event(101,e['id'])


def test_cancel_event_cancels_all_and_notifies(ready,next_thursday):
    e=service.create_event(42,'mafia','Завтра игра',next_thursday,10,'classic')
    a=service.join_event(100,e['id'])
    b=service.join_event(101,e['id'])
    service.decide(42,'event',a,True)
    cancelled=service.edit_event(42,e['id'],'mafia','Завтра игра',next_thursday,10,'classic',status='cancelled')
    assert cancelled['status']=='cancelled'
    assert service.list_events()==[]
    assert service.my_requests(100)['events'][0]['status']=='cancelled'
    assert service.my_requests(101)['events'][0]['status']=='cancelled'
    with database.session() as c:
        messages=[(row['telegram_id'],row['message']) for row in c.execute('SELECT telegram_id,message FROM notification_outbox')]
    assert any(uid==100 and 'отменено' in msg for uid,msg in messages)
    assert any(uid==101 and 'отменено' in msg for uid,msg in messages)
    with pytest.raises(service.BusinessError,match='Отменённое'):
        service.edit_event(42,e['id'],'mafia','Завтра игра',next_thursday,10,'classic',status='open')
    with pytest.raises(service.BusinessError,match='закрыта'):
        service.join_event(102,e['id'])


def test_reject_edit_change_game_and_admin_permissions(ready,next_thursday):
    e=service.create_event(42,'mafia','Мафия четверга',next_thursday,10,'classic')
    service.join_event(100,e['id'])
    with pytest.raises(service.BusinessError,match='вид игры'):
        service.edit_event(42,e['id'],'poker','Покер четверга',next_thursday,10,stack='10000',blinds='100/200')
    service.set_role(42,101,'admin')
    with pytest.raises(service.BusinessError,match='прав'):
        service.edit_event(101,e['id'],'mafia','Мафия четверга',next_thursday,10,'classic')
    with pytest.raises(service.BusinessError,match='прав'):
        service.audit_feed(101)


def test_user_search_with_escaped_wildcards(ready):
    service.set_profile(100,'Александр 100%','+79991112233','100_')
    assert [x['telegram_id'] for x in service.search_users(42,'%')]==[100]
    assert [x['telegram_id'] for x in service.search_users(42,'_')]==[100]
    assert not service.search_users(42,'NONEXISTENT')
    assert any(x['telegram_id']==100 for x in service.search_users(42,'Александр'))
    with pytest.raises(service.BusinessError,match='прав'):
        service.search_users(100)


def test_billiard_public_busy(ready):
    d=(datetime.now(ZoneInfo('Europe/Moscow'))+timedelta(days=2)).replace(hour=19,minute=0,second=0,microsecond=0)
    bid=service.billiard_book(100,d.isoformat(),2,3)
    assert len(service.billiard_busy(d.strftime('%Y-%m-%d')))==1
    service.decide(42,'billiard',bid,False)
    assert service.billiard_busy(d.strftime('%Y-%m-%d'))==[]
    with pytest.raises(service.BusinessError,match='Неверная дата'):
        service.billiard_busy('../../secret')
    with TestClient(app) as client:
        r=client.get('/api/billiard/busy',params={'date':d.strftime('%Y-%m-%d')})
        assert r.status_code==200
        assert 'telegram_id' not in r.text


def test_outbox_retries_and_token_rotation(fresh,monkeypatch):
    service.set_profile(100,'Пётр','+79991112233','Petr')
    next_at=database.utcnow()
    with database.session(write=True) as c:
        service.enqueue(c,100,'Test notification')
    items=notifications.due_messages()
    assert len(items)==1 and items[0]['telegram_id']==100
    notifications.record_outcome(items[0]['id'],False,error='timeout')
    assert notifications.due_messages()==[] # delayed next attempt
    assert notifications.pending_status()['pending']==1
    notifications.record_outcome(items[0]['id'],True)
    assert notifications.pending_status()['sent']==1
    new_settings=replace(fresh,bot_token='12345:NEW_TOKEN')
    monkeypatch.setattr(service,'settings',new_settings)
    assert notifications.pending_status()['sent']==0
    assert notifications.due_messages()==[]


def test_stage2_api_role_permissions_and_edits(ready,next_thursday):
    with TestClient(app) as client:
        owner={'X-Demo-User-ID':'42'}
        guest={'X-Demo-User-ID':'100'}
        r=client.post('/api/admin/events',headers=owner,json={'kind':'mafia','title':'Четверг в клубе','starts_at':next_thursday,'capacity':10,'format':'classic'})
        assert r.status_code==200,r.text
        event_id=r.json()['id']
        assert client.get('/api/admin/events',headers=guest).status_code==403
        assert client.get('/api/admin/users',headers=guest).status_code==403
        assert client.get('/api/admin/audit',headers=guest).status_code==403
        assert client.get('/api/admin/notifications',headers=owner).status_code==200
        response=client.put(f'/api/admin/events/{event_id}',headers=owner,json={'kind':'mafia','title':'Четверг обновлён','starts_at':next_thursday,'capacity':10,'format':'classic','status':'closed'})
        assert response.status_code==200,response.text
        assert response.json()['status']=='closed'
        assert client.get('/api/admin/events',headers=owner).json()[0]['title']=='Четверг обновлён'
        assert client.get('/api/admin/users',headers=owner,params={'q':'Ник100'}).json()[0]['telegram_id']==100
        assert client.get('/api/admin/audit',headers=owner).status_code==200
        assert client.get('/').status_code==200
        assert 'Mini App' in client.get('/').text or 'ТУРИСТ' in client.get('/').text
        assert 'loadAdminEvents' in client.get('/assets/app.js').text


def test_billiard_racing_reservation(ready):
    d=(datetime.now(ZoneInfo('Europe/Moscow'))+timedelta(days=2)).replace(hour=19,minute=0,second=0,microsecond=0)
    def attempt(uid):
        try: return 'ok',service.billiard_book(uid,d.isoformat(),2,2)
        except service.BusinessError as exc:return 'err',exc.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        res=list(pool.map(attempt,[100,101]))
    assert sorted(x[0] for x in res)==['err','ok']
    assert len(service.billiard_busy(d.strftime('%Y-%m-%d')))==1


def test_preserves_existing_database_on_schema_upgrade(fresh):
    service.set_profile(100,'Антон','+79991112233','СтарыйГость')
    database.init_db()
    database.init_db()
    assert service.get_user(100)['nickname']=='СтарыйГость'


def test_upgrade_creates_missing_notification_table_without_losing_users(ready):
    # Models a v0.1.1 database: users and games exist, outbox table does not.
    with database.session(write=True) as c:
        c.execute('DROP TABLE notification_outbox')
    assert service.get_user(100)['nickname']=='Ник100'
    database.init_db()
    assert notifications.pending_status()=={'pending':0,'sent':0,'failed':0}
    assert service.get_user(100)['nickname']=='Ник100'


def test_api_authorization_with_realistic_signed_initdata(fresh,monkeypatch):
    # This is a locally signed synthetic Telegram payload; no external API calls.
    from tests.test_auth import make_init, TOKEN
    from app import config
    signed=replace(fresh,bot_token=TOKEN,demo_mode=False)
    monkeypatch.setattr(api,'settings',signed)
    monkeypatch.setattr(service,'settings',signed)
    with TestClient(app) as client:
        assert client.get('/api/me').status_code==401
        h={'X-Telegram-Init-Data':make_init(user_id=100)}
        me=client.get('/api/me',headers=h)
        assert me.status_code==200,me.text
        assert me.json()['user']['telegram_id']==100
        assert client.get('/api/me',headers={'X-Telegram-Init-Data':'bad=bad'}).status_code==401
        assert client.get('/api/admin/users',headers=h).status_code==403


def test_notifications_http_success_and_permanent_error(fresh,monkeypatch):
    import asyncio
    import httpx
    with database.session(write=True) as c:
        service.enqueue(c,100,'Сообщение для гостя')
        service.enqueue(c,101,'Сообщение для другого гостя')
    items=notifications.due_messages()
    assert len(items)==2

    def handler(request):
        data=request.content.decode('utf-8')
        if '100' in data:
            return httpx.Response(200,json={'ok':True,'result':{'message_id':2}})
        return httpx.Response(403,json={'ok':False,'description':'Forbidden: bot was blocked'})

    async def send():
        transport=httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            for item in items:
                await notifications.send_once(client,item)
    asyncio.run(send())
    assert notifications.pending_status()=={'pending':0,'sent':1,'failed':1}
