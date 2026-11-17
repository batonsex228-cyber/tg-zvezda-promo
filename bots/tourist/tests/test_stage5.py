"""v0.5.0 regression suite: retry safety, public config and online preflight."""
from app.version import VERSION
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient
from app import api, database, service, notifications, config
from scripts.verify_telegram import check_bot, TelegramCheckError

TOKEN = '123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_01234'


def _poker_at(hours=36):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(timespec='seconds')


def test_same_event_key_is_atomic_and_no_duplicate_admin_notification(ready):
    ev=service.create_event(42,'poker','Стол на вечер',_poker_at(),2,stack='10 000',blinds='100/200')
    with ThreadPoolExecutor(max_workers=6) as pool:
        ids=list(pool.map(lambda _:service.join_event(100,ev['id'],'test_key_2026_11_05'),range(6)))
    assert len(set(ids))==1
    with database.session() as c:
        assert c.execute('SELECT COUNT(*) FROM applications').fetchone()[0]==1
        assert c.execute("SELECT COUNT(*) FROM audit WHERE action='application.requested'").fetchone()[0]==1
        assert c.execute("SELECT COUNT(*) FROM notification_outbox WHERE message LIKE '%новая заявка%'").fetchone()[0]==1
        assert c.execute("SELECT COUNT(*) FROM idempotency_keys WHERE operation='event.join'").fetchone()[0]==1


def test_key_bound_to_user_and_payload_not_another_event(ready):
    a=service.create_event(42,'poker','Первая игра',_poker_at(),10,stack='1 000',blinds='10/20')
    b=service.create_event(42,'poker','Вторая игра',_poker_at(60),10,stack='1 000',blinds='10/20')
    key='test_replay_key_A'
    id_a=service.join_event(100,a['id'],key)
    assert service.join_event(100,a['id'],key)==id_a
    with pytest.raises(service.BusinessError,match='изменён'):
        service.join_event(100,b['id'],key)
    assert service.join_event(101,b['id'],key) != id_a
    assert len(service.my_requests(100)['events'])==1


def test_key_retry_not_wiped_after_admin_confirms(ready):
    ev=service.create_event(42,'poker','Группа',_poker_at(),10,stack='5000',blinds='50/100')
    key='retry_key_aabbccdd'
    rid=service.join_event(100,ev['id'],key)
    service.decide(42,'event',rid,True)
    assert service.join_event(100,ev['id'],key)==rid
    assert service.my_requests(100)['events'][0]['status']=='confirmed'


def test_billiard_key_retries_and_detects_changed_request(ready):
    start=_poker_at()
    key='billiard_key_123456'
    one=service.billiard_book(100,start,2,2,key)
    assert service.billiard_book(100,start,2,2,key)==one
    with pytest.raises(service.BusinessError,match='изменён'):
        service.billiard_book(100,start,2,4,key)
    with pytest.raises(service.BusinessError,match='занят'):
        service.billiard_book(100,start,2,2,'other_key_2222222')
    with database.session() as c:
        assert c.execute('SELECT COUNT(*) FROM billiard_bookings').fetchone()[0]==1


def test_idempotency_rejects_bad_keys(ready):
    ev=service.create_event(42,'poker','Проверка ключа',_poker_at(),10,stack='5000',blinds='50/100')
    for key in ['short','spaces 12345','a'*101,'ключ_123456']:
        with pytest.raises(service.BusinessError,match='ключ'):
            service.join_event(100,ev['id'],key)


def test_database_v04_to_v05_migrates_idempotency_without_losing_guests(ready):
    # Simulate a previous-version database without the new table.
    with database.session(write=True) as c:
        c.execute('DROP TABLE idempotency_keys')
    database.init_db()
    with database.session() as c:
        assert c.execute("SELECT COUNT(*) FROM users").fetchone()[0]==4
        assert c.execute("SELECT name FROM sqlite_master WHERE name='idempotency_keys'").fetchone()
    ev=service.create_event(42,'poker','Обновлённая база',_poker_at(),10,stack='1000',blinds='10/20')
    assert service.join_event(100,ev['id'],'migration_key_123')>0


def test_api_retry_headers_in_live_preview(ready):
    ev=service.create_event(42,'poker','API повтор',_poker_at(),10,stack='1000',blinds='10/20')
    with TestClient(api.app) as client:
        conf=client.get('/api/config').json()
        assert conf['club_timezone']=='Europe/Moscow'
        assert 'bot_token' not in conf and 'owner_telegram_id' not in conf
        headers={'X-Demo-User-ID':'100','X-Idempotency-Key':'header_retry_123456'}
        r1=client.post(f'/api/events/{ev["id"]}/join',headers=headers)
        r2=client.post(f'/api/events/{ev["id"]}/join',headers=headers)
        assert r1.status_code==200 and r2.json()['id']==r1.json()['id']
        wrong={'X-Demo-User-ID':'100','X-Idempotency-Key':'short'}
        assert client.post(f'/api/events/{ev["id"]}/join',headers=wrong).status_code==400
        assert client.get('/health').json()['version']==VERSION
        assert client.get('/assets/app.js').status_code==200
        assert client.get('/assets/styles.css').status_code==200


def test_online_verify_get_me_and_webhook_without_mutations():
    calls=[]
    def handle(req):
        calls.append((req.method,req.url.path))
        if req.url.path.endswith('/getMe'):
            return httpx.Response(200,json={'ok':True,'result':{'id':567890,'is_bot':True,'username':'test_tourist_bot'}})
        return httpx.Response(200,json={'ok':True,'result':{'url':'','pending_update_count':0}})
    result=check_bot(TOKEN,transport=httpx.MockTransport(handle))
    assert result=={'id':567890,'username':'test_tourist_bot','webhook_active':False,'pending_updates':0}
    assert [x[0] for x in calls]==['GET','GET']
    assert all(x[1].endswith(('/getMe','/getWebhookInfo')) for x in calls)


def test_online_verify_detects_existing_webhook():
    def handle(req):
        if req.url.path.endswith('/getMe'):
            return httpx.Response(200,json={'ok':True,'result':{'id':3,'is_bot':True,'username':'mybot'}})
        return httpx.Response(200,json={'ok':True,'result':{'url':'https://previous.site/secret'}})
    assert check_bot(TOKEN,transport=httpx.MockTransport(handle))['webhook_active'] is True


def test_online_verify_errors_never_include_secret():
    assert TOKEN not in str(TelegramCheckError('Неверный токен'))
    with pytest.raises(TelegramCheckError) as ex:
        check_bot(TOKEN,transport=httpx.MockTransport(lambda _:httpx.Response(401)))
    assert TOKEN not in str(ex.value)
    with pytest.raises(TelegramCheckError):check_bot('bad_token')


def test_notification_rate_limit_respects_telegram_retry_after(fresh):
    with database.session(write=True) as c:
        service.enqueue(c,100,'Проверка ограничений Telegram')
    item=notifications.claim_due_messages()[0]
    before=datetime.now(timezone.utc)
    async def send():
        def handle(req):
            return httpx.Response(429,json={'ok':False,'parameters':{'retry_after':240}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            await notifications.send_once(client,item)
    asyncio.run(send())
    with database.session() as c:
        row=c.execute('SELECT next_attempt_at,state,attempts,last_error FROM notification_outbox WHERE id=?',(item['id'],)).fetchone()
    assert row['state']=='pending' and row['attempts']==1
    assert datetime.fromisoformat(row['next_attempt_at'])-before >= timedelta(seconds=239)
    assert row['last_error']=='HTTP 429'


def test_main_module_importable_without_aiogram():
    # The local Mini App demo remains runnable when Telegram is not being used.
    import app.main
    assert callable(app.main.main)
