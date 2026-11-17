"""v0.9 Operational Safety: backups, read-only staff status, expiry guard."""
import os
import sqlite3
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import api, config, database, maintenance, service
from scripts.backup_db import create_backup
from scripts.doctor import diagnose
from scripts.restore_check import verify_backup


def live_copy(monkeypatch, ready):
    live = replace(ready, bot_token='123456:XXXXXXXXXXXXXXXXXXXXXXXXXXXXX', demo_mode=False)
    monkeypatch.setattr(maintenance, 'settings', live)
    return live


def test_automatic_backup_is_valid_and_only_once_per_interval(ready, tmp_path, monkeypatch):
    live_copy(monkeypatch, ready)
    monkeypatch.setattr(maintenance, 'ROOT', tmp_path)
    assert maintenance.backup_if_due() == 'created'
    copies = maintenance.automatic_files()
    assert len(copies) == 1
    assert verify_backup(copies[0])['users'] >= 4
    assert not list((tmp_path/'backups').glob('*.partial'))
    with database.session(write=True) as c:
        c.execute("UPDATE users SET first_name='Изменено' WHERE telegram_id=100")
    # No spurious new file until interval expires.
    assert maintenance.backup_if_due() == 'up-to-date'
    assert len(maintenance.automatic_files()) == 1
    with sqlite3.connect(copies[0]) as snapshot:
        assert snapshot.execute('SELECT first_name FROM users WHERE telegram_id=100').fetchone()[0] != 'Изменено'
    # Expire the old verified copy and check the new version contains the update.
    old = time.time() - 25*3600
    os.utime(copies[0], (old, old))
    assert maintenance.backup_if_due() == 'created'
    assert len(maintenance.automatic_files()) == 2
    with sqlite3.connect(maintenance.automatic_files()[-1]) as snapshot:
        assert snapshot.execute('SELECT first_name FROM users WHERE telegram_id=100').fetchone()[0] == 'Изменено'


def test_retention_only_deletes_old_automated_not_manual_backup(ready, monkeypatch, tmp_path):
    live_copy(monkeypatch, ready)
    monkeypatch.setattr(maintenance, 'ROOT', tmp_path)
    manual = create_backup(tmp_path/'backups')
    auto_old = create_backup(tmp_path/'backups', prefix='tourist_auto_')
    old = time.time() - 20*86400
    for path in (manual, auto_old):
        os.utime(path, (old, old))
    assert maintenance.backup_if_due() == 'created'
    assert manual.exists() and verify_backup(manual)['users'] >= 4
    assert not auto_old.exists()
    assert len(maintenance.automatic_files()) == 1
    assert not (tmp_path/'backups'/'.env').exists()


def test_failed_backup_does_not_delete_good_copy_or_manual(ready, monkeypatch, tmp_path):
    live_copy(monkeypatch, ready)
    monkeypatch.setattr(maintenance, 'ROOT', tmp_path)
    auto_old = create_backup(tmp_path/'backups', prefix='tourist_auto_')
    manual = create_backup(tmp_path/'backups')
    old = time.time() - 20*86400
    os.utime(auto_old, (old, old))
    def broken(*args, **kwargs):
        raise OSError('never show internal path in UI')
    monkeypatch.setattr(maintenance, 'create_backup', broken)
    with pytest.raises(OSError):
        maintenance.backup_if_due()
    assert auto_old.exists() and manual.exists()
    assert maintenance.backup_status()['last_error']=='OSError'
    assert 'internal' not in str(maintenance.backup_status())


def test_recent_corrupt_copy_replaced_not_counted_healthy(ready, monkeypatch, tmp_path):
    live_copy(monkeypatch, ready)
    monkeypatch.setattr(maintenance, 'ROOT', tmp_path)
    directory = tmp_path/'backups'
    directory.mkdir()
    damaged = directory/'tourist_auto_20200101_000000_000000.sqlite3'
    damaged.write_bytes(b'not a sqlite database')
    assert maintenance.backup_if_due() == 'created'
    assert verify_backup(maintenance.automatic_files()[-1])['users'] >= 4


def test_demo_backup_is_automatic_disabled_even_if_setting_positive(ready,monkeypatch,tmp_path):
    monkeypatch.setattr(maintenance, 'ROOT', tmp_path)
    monkeypatch.setattr(maintenance, 'settings', ready)
    assert maintenance.backup_if_due() == 'disabled'
    assert not (tmp_path/'backups').exists()
    assert maintenance.backup_status()['active'] is False
    assert maintenance.backup_status()['enabled'] is True


def test_disabled_backup_and_no_db_do_not_touch_disk(monkeypatch,tmp_path,ready):
    s=replace(ready, bot_token='12345:XXXXXXXXXXXXXXXXXXXX', demo_mode=False,
              database_path=str(tmp_path/'not-here.sqlite3'))
    monkeypatch.setattr(database,'settings',s)
    monkeypatch.setattr(maintenance,'settings',s)
    monkeypatch.setattr(maintenance,'ROOT',tmp_path)
    assert maintenance.backup_if_due()=='no-database'
    assert not (tmp_path/'not-here.sqlite3').exists()
    monkeypatch.setattr(maintenance,'settings',replace(s,backup_interval_hours=0))
    assert maintenance.backup_if_due()=='disabled'


def test_backup_api_is_private_and_contains_no_paths_or_tokens(ready, monkeypatch, tmp_path):
    live_copy(monkeypatch, ready)
    monkeypatch.setattr(maintenance,'ROOT',tmp_path)
    with TestClient(api.app) as client:
        assert client.get('/api/admin/backups',headers={'X-Demo-User-ID':'100'}).status_code==403
        good=client.get('/api/admin/backups',headers={'X-Demo-User-ID':'42'})
        assert good.status_code==200
        payload=good.json()
        assert payload['copies']==0
        assert 'bot_token' not in good.text
        assert 'database_path' not in good.text
        assert '/mnt/' not in good.text
        assert '\\' not in good.text
        html=client.get('/').text
        assert 'backup-info' in html
        js=client.get('/assets/app.js').text
        assert 'loadBackupStatus' in js


def test_live_api_hides_admin_backup_without_valid_signature(ready,monkeypatch):
    s=replace(ready,bot_token='123456:XXXXXXXXXXXXXXXXXXXXXXXXXXXX',demo_mode=False)
    monkeypatch.setattr(api,'settings',s)
    with TestClient(api.app) as client:
        assert client.get('/api/admin/backups').status_code==401
        assert client.get('/api/admin/backups',headers={'X-Demo-User-ID':'42'}).status_code==401


def test_pending_expired_event_must_not_be_confirmed(ready, next_thursday):
    event=service.create_event(42,'mafia','Прошедшая мафия',next_thursday,10,'classic')
    rid=service.join_event(100,event['id'])
    with database.session(write=True) as c:
        c.execute('UPDATE events SET starts_at=? WHERE id=?',
                  ((datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(timespec='seconds'),event['id']))
    with pytest.raises(service.BusinessError,match='прошедшее'):
        service.decide(42,'event',rid,True)
    assert service.request_status(100,'event',rid)=='pending'
    assert service.decide(42,'event',rid,False)['status']=='rejected'


def test_pending_expired_billiards_must_not_be_confirmed(ready):
    start=(datetime.now(timezone.utc)+timedelta(hours=4)).isoformat(timespec='seconds')
    rid=service.billiard_book(100,start,1,2)
    with database.session(write=True) as c:
        past=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(timespec='seconds')
        c.execute('UPDATE billiard_bookings SET starts_at=? WHERE id=?',(past,rid))
    with pytest.raises(service.BusinessError,match='прошедшее'):
        service.decide(42,'billiard',rid,True)
    assert service.request_status(100,'billiard',rid)=='pending'
    assert service.decide(42,'billiard',rid,False)['status']=='rejected'


def test_doctor_warns_invalid_backup_config(ready):
    bad=replace(ready,backup_interval_hours=-1,backup_keep_days=0)
    checks=diagnose('demo',cfg=bad,require_packages=False)
    assert sum(x['level']=='ERROR' for x in checks)>=2


def test_legacy_restore_check_discovers_only_auto_backup(ready,tmp_path,monkeypatch):
    from scripts import restore_check
    monkeypatch.setattr(restore_check,'ROOT',tmp_path)
    auto=create_backup(tmp_path/'backups',prefix='tourist_auto_')
    monkeypatch.setattr('sys.argv',['restore_check'])
    restore_check.main()
    assert auto.exists()

def test_manual_backup_atomic_publish_failure_keeps_no_partial(ready,tmp_path,monkeypatch):
    from scripts import backup_db
    original_connect=backup_db.sqlite3.connect
    def fail_destination(*args,**kwargs):
        if str(args[0]).endswith('.partial'):
            raise OSError('disk full')
        return original_connect(*args,**kwargs)
    monkeypatch.setattr(backup_db.sqlite3,'connect',fail_destination)
    with pytest.raises(OSError):
        backup_db.create_backup(tmp_path/'backup')
    assert not list((tmp_path/'backup').glob('*.partial'))
    assert not list((tmp_path/'backup').glob('*.sqlite3'))


def test_release_identity_matches_api_and_tunnel(ready):
    from app.version import VERSION
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    assert VERSION==root.joinpath('VERSION.txt').read_text().strip()
    with TestClient(api.app) as client:
        assert client.get('/health').json()['version']==VERSION
    from scripts.run_tunnel import wait_for_our_api
    assert wait_for_our_api.__defaults__[0] is None  # tunnel uses same VERSION
