"""v0.10 disaster recovery, owner diagnostics, privacy and regression tests."""
import sqlite3
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import api, database, operations, service
from scripts.backup_db import create_backup
from scripts.restore_check import verify_backup
from scripts.recover_to_new_db import RecoveryError, restore_to_new_database
from scripts.recovery_drill import run_drill


def test_new_file_recovery_preserves_originals(ready, tmp_path):
    source = create_backup(tmp_path / 'backups')
    old_db = Path(ready.database_path)
    source_bytes = source.read_bytes()
    before = verify_backup(source)
    result = restore_to_new_database(source, tmp_path / 'recovered.sqlite3')
    assert result['counts'] == before and result['identity'] == 'legacy-unbound'
    assert verify_backup(result['file']) == before
    assert source.read_bytes() == source_bytes
    assert old_db.is_file() and old_db != Path(result['file'])
    with sqlite3.connect(result['file']) as conn:
        conn.execute("UPDATE users SET first_name='После восстановления' WHERE telegram_id=100")
        conn.commit()
    with database.session() as conn:
        assert conn.execute('SELECT first_name FROM users WHERE telegram_id=100').fetchone()[0] != 'После восстановления'


def test_recovery_rejects_existing_destination_and_live_database(ready, tmp_path):
    source = create_backup(tmp_path/'backups')
    live_bytes = Path(ready.database_path).read_bytes()
    with pytest.raises(RecoveryError, match='рабочей базы'):
        restore_to_new_database(source, ready.database_path)
    assert Path(ready.database_path).read_bytes() == live_bytes
    other = tmp_path/'existing.sqlite3'
    other.write_bytes(b'keep me')
    with pytest.raises(FileExistsError):
        restore_to_new_database(source, other)
    assert other.read_bytes() == b'keep me'
    with pytest.raises((FileExistsError, RecoveryError)):
        restore_to_new_database(source, source)


def test_recovery_rejects_corrupt_and_missing_backup_without_creating_output(ready,tmp_path):
    bad = tmp_path/'corrupt.sqlite3'
    bad.write_bytes(b'NOT A DATABASE')
    out = tmp_path/'new.sqlite3'
    with pytest.raises(sqlite3.DatabaseError):
        restore_to_new_database(bad, out)
    assert not out.exists()
    with pytest.raises(FileNotFoundError):
        restore_to_new_database(tmp_path/'not_here.sqlite3',out)
    assert not out.exists()


def test_recovery_rejects_wrong_bot_and_accepts_matching_bot(ready, tmp_path):
    from app.database import token_fingerprint
    token_a = '123456:ONE_TEST_TOKEN_ABC'
    token_b = '123456:TWO_TEST_TOKEN_DEF'
    with database.session(write=True) as c:
        c.execute('INSERT INTO bot_identity(id,token_fingerprint,created_at) VALUES(1,?,?)',
                  (token_fingerprint(token_a),database.utcnow()))
    source = create_backup(tmp_path/'backups')
    dest = tmp_path/'new.sqlite3'
    with pytest.raises(RecoveryError,match='другому'):
        restore_to_new_database(source,dest,bot_token=token_b)
    assert not dest.exists()
    with pytest.raises(RecoveryError,match='BOT_TOKEN'):
        restore_to_new_database(source,dest,bot_token='')
    result=restore_to_new_database(source,dest,bot_token=token_a)
    assert result['identity']=='matched'


def test_recovery_copy_error_cleans_partial_and_preserves_source(ready, tmp_path, monkeypatch):
    from scripts import recover_to_new_db
    source = create_backup(tmp_path/'backups')
    old = source.read_bytes()
    out = tmp_path/'unfinished.sqlite3'
    def fail_copy(inp, dest, length=None):
        dest.write(b'broken')
        raise OSError('injected disk full')
    monkeypatch.setattr(recover_to_new_db.shutil,'copyfileobj',fail_copy)
    with pytest.raises(OSError):
        restore_to_new_database(source,out)
    assert not out.exists() and source.read_bytes()==old


def test_recovery_drill_succeeds_without_changing_current_database(ready):
    before = Path(ready.database_path).stat().st_size
    result = run_drill()
    assert result['result'] == 'ok' and result['counts_match']
    assert Path(ready.database_path).stat().st_size == before


def test_operations_owner_only_and_avoids_paths_secrets(ready,monkeypatch,tmp_path):
    from app import maintenance
    monkeypatch.setattr(maintenance,'ROOT',tmp_path)
    with TestClient(api.app) as client:
        assert client.get('/api/admin/operations').status_code==403
        assert client.get('/api/admin/operations',headers={'X-Demo-User-ID':'100'}).status_code==403
        owner = client.get('/api/admin/operations',headers={'X-Demo-User-ID':'42'})
        assert owner.status_code == 200
        j = owner.json()
        assert j['database']['quick_check_ok'] is True
        assert j['database']['users'] >= 4
        assert j['notifications']['pending'] >= 0
        assert 'bot_token' not in owner.text and 'database_path' not in owner.text
        assert 'telegram_id' not in owner.text and '/tmp/' not in owner.text
        assert 'password' not in owner.text and 'phone' not in owner.text
        assert 'credentials' not in owner.text
        assert 'operations-box' in client.get('/').text
        assert 'loadOperationsStatus' in client.get('/assets/app.js').text


def test_operations_live_requires_telegram_signature(ready, monkeypatch):
    live=replace(ready,bot_token='123456:XYZTESTTOKEN999999999999',demo_mode=False)
    monkeypatch.setattr(api,'settings',live)
    with TestClient(api.app) as client:
        assert client.get('/api/admin/operations').status_code==401
        assert client.get('/api/admin/operations',headers={'X-Demo-User-ID':'42'}).status_code==401


def test_ops_warns_about_disk_space_for_owner(ready,monkeypatch):
    monkeypatch.setattr(operations.shutil,'disk_usage',lambda _: SimpleNamespace(free=100 * 1024 * 1024))
    info=operations.snapshot()
    assert info['disk']['low_space'] and info['disk']['free_mb']==100
    assert info['google']['configured'] is False


def test_restore_refuses_invalid_file_extension(ready,tmp_path):
    src=create_backup(tmp_path/'backups')
    out=tmp_path/'notdb.env'
    with pytest.raises(RecoveryError,match='sqlite3'):
        restore_to_new_database(src,out)
    assert not out.exists()


def test_operations_owner_flag_removed_when_owner_unset(ready,monkeypatch):
    monkeypatch.setattr(api,'settings',replace(ready,owner_telegram_id=0))
    with TestClient(api.app) as client:
        assert client.get('/api/admin/operations',headers={'X-Demo-User-ID':'42'}).status_code==403
