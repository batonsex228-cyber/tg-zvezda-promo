"""v0.6 regression: launch security, migrations, backups and signed end-to-end API."""
import shutil
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from app import api, config, database, notifications, service, sheets
from scripts.backup_db import create_backup
from scripts.restore_check import verify_backup
from tests.test_stage4 import sign_user, BOT_TOKEN, OTHER_TOKEN


def test_mismatched_token_rejected_before_migration(ready, monkeypatch):
    original=replace(ready,bot_token=BOT_TOKEN,demo_mode=False)
    monkeypatch.setattr(database,'settings',original)
    database.bind_bot_identity()
    with database.session(write=True) as c:
        c.execute('DROP TABLE idempotency_keys') # simulate a pre-v0.5 schema
    changed=replace(original,bot_token=OTHER_TOKEN)
    monkeypatch.setattr(database,'settings',changed)
    with pytest.raises(RuntimeError,match='до миграции'):
        database.initialize_storage()
    with database.session() as c:
        assert c.execute("SELECT name FROM sqlite_master WHERE name='idempotency_keys'").fetchone() is None
        assert c.execute('SELECT token_fingerprint FROM bot_identity').fetchone()[0]==database.token_fingerprint(BOT_TOKEN)
    monkeypatch.setattr(database,'settings',original)
    database.initialize_storage()
    with database.session() as c:
        assert c.execute("SELECT name FROM sqlite_master WHERE name='idempotency_keys'").fetchone()


def test_relative_database_path_anchored_to_project_not_cwd(tmp_path,monkeypatch):
    elsewhere=tmp_path/'elsewhere'; elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(config,'ROOT',tmp_path)
    s=replace(config.settings,database_path='data/relative.sqlite3',bot_token='',demo_mode=True)
    monkeypatch.setattr(database,'settings',s)
    database.init_db()
    assert database.database_path()==(tmp_path/'data'/'relative.sqlite3').resolve()
    assert database.database_path().is_file()
    assert not (elsewhere/'data'/'relative.sqlite3').exists()


def test_backup_roundtrip_preserves_rows_and_no_production_mutation(ready,monkeypatch,tmp_path):
    from scripts import backup_db
    monkeypatch.setattr(backup_db,'ROOT',tmp_path)
    with database.session() as c:
        before=c.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    backup=create_backup()
    result=verify_backup(backup)
    assert result['users']==before and backup.parent==tmp_path/'backups'
    assert backup.stat().st_size>1024
    # Separate copy can be read without writing or modifying the real working DB.
    restored=tmp_path/'restored.sqlite3';shutil.copy2(backup,restored)
    assert verify_backup(restored)['users']==before
    with database.session() as c:
        assert c.execute('SELECT COUNT(*) FROM users').fetchone()[0]==before


def test_backup_requires_existing_database(monkeypatch,tmp_path):
    from scripts import backup_db
    monkeypatch.setattr(backup_db,'ROOT',tmp_path)
    monkeypatch.setattr(database,'settings',replace(config.settings,database_path=str(tmp_path/'never-created.sqlite3')))
    with pytest.raises(FileNotFoundError):create_backup()
    assert not (tmp_path/'never-created.sqlite3').exists()


def test_backup_rejects_missing_tables_and_corruption(tmp_path):
    path=tmp_path/'not-club.sqlite3'
    with sqlite3.connect(path) as c:c.execute('CREATE TABLE something_else(id INTEGER)')
    with pytest.raises(RuntimeError,match='отсутствуют таблицы'):verify_backup(path)
    damaged=tmp_path/'bad.sqlite3';damaged.write_bytes(b'NOT A SQLITE DATABASE')
    with pytest.raises(sqlite3.DatabaseError):verify_backup(damaged)


def test_retry_returns_current_confirmed_or_cancelled_status(ready):
    start=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat(timespec='seconds')
    e=service.create_event(42,'poker','Проверяем актуальный статус',start,3,stack='1000',blinds='10/20')
    with TestClient(api.app) as client:
        hdr={'X-Demo-User-ID':'100','X-Idempotency-Key':'retry_status_12345'}
        created=client.post(f'/api/events/{e["id"]}/join',headers=hdr)
        assert created.json()['status']=='pending'
        service.decide(42,'event',created.json()['id'],True)
        repeated=client.post(f'/api/events/{e["id"]}/join',headers=hdr)
        assert repeated.json()=={'id':created.json()['id'],'status':'confirmed'}
        service.request_cancel(100,'event',created.json()['id'])
        service.decide(42,'event',created.json()['id'],True)
        assert client.post(f'/api/events/{e["id"]}/join',headers=hdr).json()['status']=='cancelled'


def test_billiard_retries_return_real_status(ready):
    d=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat(timespec='seconds')
    with TestClient(api.app) as client:
        h={'X-Demo-User-ID':'100','X-Idempotency-Key':'billiard_status_12345'}
        payload={'starts_at':d,'hours':1,'guest_count':3}
        created=client.post('/api/billiard',headers=h,json=payload)
        assert created.status_code==200 and created.json()['status']=='pending'
        service.decide(42,'billiard',created.json()['id'],True)
        assert client.post('/api/billiard',headers=h,json=payload).json()['status']=='confirmed'


def test_api_enforces_signed_telegram_and_has_security_headers(ready,monkeypatch):
    live=replace(ready,bot_token=BOT_TOKEN,demo_mode=False)
    for mod in (database,service,api,notifications,sheets):monkeypatch.setattr(mod,'settings',live)
    with TestClient(api.app) as client:
        response=client.get('/')
        assert response.status_code==200
        assert "script-src 'self' https://telegram.org" in response.headers['content-security-policy']
        assert 'https://web.telegram.org' in response.headers['content-security-policy']
        assert response.headers['x-content-type-options']=='nosniff'
        assert client.get('/api/me',headers={'X-Demo-User-ID':'42'}).status_code==401
        assert client.get('/api/me',headers={'X-Telegram-Init-Data':sign_user(token=OTHER_TOKEN,uid=42)}).status_code==401
        assert client.get('/api/me',headers={'X-Telegram-Init-Data':sign_user(token=BOT_TOKEN,uid=42)}).json()['user']['role']=='owner'


def test_signed_end_to_end_events_billiard_staff_and_private_data(ready,monkeypatch,next_thursday):
    live=replace(ready,bot_token=BOT_TOKEN,demo_mode=False)
    for mod in (database,service,api,notifications,sheets):monkeypatch.setattr(mod,'settings',live)
    # Disable actual network sending; we exercise the outbox record instead.
    service.ensure_user(42,'Владелец')
    user={'X-Telegram-Init-Data':sign_user(token=BOT_TOKEN,uid=100)}
    owner={'X-Telegram-Init-Data':sign_user(token=BOT_TOKEN,uid=42)}
    with TestClient(api.app) as client:
        assert client.get('/api/admin/pending',headers=user).status_code==403
        created=client.post('/api/admin/events',headers=owner,json={
            'kind':'mafia','title':'Мафия в четверг','starts_at':next_thursday,
            'capacity':10,'format':'classic','min_players':1})
        assert created.status_code==200, created.text
        eid=created.json()['id']
        assert client.get('/api/schedule').json()[0]['id']==eid
        headers={**user,'X-Idempotency-Key':'live_e2e_join_1234'}
        result=client.post(f'/api/events/{eid}/join',headers=headers)
        assert result.status_code==200 and result.json()['status']=='pending'
        rid=result.json()['id']
        assert client.get('/api/admin/pending',headers=owner).json()['events'][0]['id']==rid
        decision=client.post('/api/admin/decide',headers=owner,json={'category':'event','request_id':rid,'approve':True})
        assert decision.status_code==200
        assert client.post(f'/api/events/{eid}/join',headers=headers).json()['status']=='confirmed'
        assert client.get('/api/me',headers=user).json()['requests']['events'][0]['status']=='confirmed'
        assert client.get('/api/events/%d/confirmed'%eid).json()[0]['nickname_snapshot']=='Ник100'
        assert '+7999' not in client.get(f'/api/events/{eid}/confirmed').text
        assert client.post(f'/api/event/{rid}/cancel',headers=user).status_code==200
        assert client.post('/api/admin/decide',headers=owner,json={'category':'event','request_id':rid,'approve':True}).json()['status']=='cancelled'
        assert client.get('/api/me',headers=user).json()['requests']['events'][0]['status']=='cancelled'
    with database.session() as c:
        assert c.execute('SELECT COUNT(*) FROM audit').fetchone()[0]>=5
        assert c.execute('SELECT COUNT(*) FROM notification_outbox').fetchone()[0]>=1


def test_verified_backup_does_not_include_raw_bot_token(ready,monkeypatch,tmp_path):
    from scripts import backup_db
    monkeypatch.setattr(backup_db,'ROOT',tmp_path)
    live=replace(ready,bot_token=BOT_TOKEN,demo_mode=False)
    monkeypatch.setattr(database,'settings',live)
    database.bind_bot_identity()
    path=create_backup()
    assert BOT_TOKEN.encode() not in path.read_bytes()
    assert verify_backup(path)['users']>=1
