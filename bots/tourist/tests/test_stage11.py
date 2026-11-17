"""v0.11.0: production deployment checks, readiness and encrypted portable backups."""
from dataclasses import replace
from pathlib import Path
import os
import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import api, database
from app.production import validate_production
from app.runtime import StartupError
from app.version import VERSION
from scripts.encrypted_backup import (
    MAGIC, EncryptedBackupError, export_encrypted, import_encrypted,
)
from scripts.container_healthcheck import check as healthcheck
from scripts.restore_check import verify_backup

TOKEN = '123456:synthetic_bot_token_for_testing_only_abcdef'
PASSWORD = 'correct-horse-battery-staple-tourist-2026'


def production_config(ready, **kw):
    return replace(ready, bot_token=TOKEN, demo_mode=False, owner_telegram_id=42,
                   webapp_url='https://club.example.org', **kw)


def test_production_validations_accept_configured_container(ready):
    assert validate_production(production_config(ready), domain='club.example.org', in_container=True)


@pytest.mark.parametrize('override', [
    {'bot_token':''}, {'owner_telegram_id':0}, {'demo_mode':True},
    {'webapp_url':'http://club.example.org'},
    {'webapp_url':'https://other.example.org'},
    {'webapp_url':'https://club.example.org/?token=abcd'},
    {'webapp_url':'https://club.example.org:8080'},
    {'backup_interval_hours':0}, {'backup_keep_days':3},
    {'google_sheet_id':'some-id'},
])
def test_production_refuses_unsafe_config(ready, override):
    data = {**production_config(ready).__dict__, **override}
    cfg = type(ready)(**data)
    with pytest.raises(StartupError):
        validate_production(cfg, domain='club.example.org', in_container=True)


def test_production_refuses_public_binding_outside_container(ready):
    with pytest.raises(StartupError, match='контейнера'):
        validate_production(production_config(ready), domain='club.example.org', in_container=False)
    with pytest.raises(StartupError, match='DOMAIN'):
        validate_production(production_config(ready), domain='invalid..domain', in_container=True)


def test_production_does_not_echo_private_token(ready):
    cfg = production_config(ready)
    with pytest.raises(StartupError) as info:
        validate_production(cfg, domain='somewhere.example.org', in_container=True)
    assert cfg.bot_token not in str(info.value)


def test_readiness_reports_version_without_secrets(ready):
    with TestClient(api.app) as client:
        response = client.get('/ready')
        assert response.status_code == 200
        assert response.json() == {'ready':True, 'version': VERSION}
        assert 'sqlite3' not in response.text
        assert 'BOT_TOKEN' not in response.text


def test_readiness_no_database_is_503_no_files_created(ready, tmp_path, monkeypatch):
    missing = tmp_path / 'not_created.sqlite3'
    with TestClient(api.app) as client:
        monkeypatch.setattr(database, 'database_path', lambda: missing)
        response = client.get('/ready')
        assert response.status_code == 503 and response.json() == {'ready': False}
    assert not missing.exists()


def test_portable_encrypted_backup_roundtrip(ready, tmp_path):
    archive=tmp_path/'portable.tbackup'
    before = Path(ready.database_path).stat().st_size
    result=export_encrypted(archive, passphrase=PASSWORD)
    assert result == archive and archive.stat().st_size>100
    assert archive.read_bytes().startswith(MAGIC)
    assert b'Guest100' not in archive.read_bytes()
    restored=tmp_path/'restored.sqlite3'
    metadata=import_encrypted(archive,restored,passphrase=PASSWORD)
    assert metadata['identity']=='legacy-unbound'
    assert metadata['counts']==verify_backup(restored)
    assert Path(ready.database_path).stat().st_size==before


def test_encrypted_wrong_password_leaves_no_plaintext(ready,tmp_path):
    archive=export_encrypted(tmp_path/'portable.tbackup',passphrase=PASSWORD)
    dest=tmp_path/'new.sqlite3'
    with pytest.raises(EncryptedBackupError,match='пароль'):
        import_encrypted(archive,dest,passphrase='an-incorrect-password-2026')
    assert not dest.exists()


def test_tampered_encrypted_backup_is_rejected(ready,tmp_path):
    archive=export_encrypted(tmp_path/'portable.tbackup',passphrase=PASSWORD)
    original=archive.read_bytes()
    corrupted=bytearray(original)
    corrupted[-27]^=0x01
    archive.write_bytes(corrupted)
    dest=tmp_path/'new.sqlite3'
    with pytest.raises(EncryptedBackupError,match='повреждённая'):
        import_encrypted(archive,dest,passphrase=PASSWORD)
    assert not dest.exists()


def test_export_never_overwrites_existing_file_or_partial(ready,tmp_path):
    target=tmp_path/'backup.tbackup'
    target.write_bytes(b'important')
    with pytest.raises(FileExistsError):
        export_encrypted(target,passphrase=PASSWORD)
    assert target.read_bytes()==b'important'
    target.unlink()
    pending=tmp_path/'backup.tbackup.partial'
    pending.write_bytes(b'other-process')
    with pytest.raises(FileExistsError):
        export_encrypted(target,passphrase=PASSWORD)
    assert pending.read_bytes()==b'other-process' and not target.exists()


def test_restore_will_not_overwrite_live_db_or_any_existing(ready,tmp_path):
    archive=export_encrypted(tmp_path/'portable.tbackup',passphrase=PASSWORD)
    original=Path(ready.database_path).read_bytes()
    with pytest.raises(EncryptedBackupError,match='рабочей'):
        import_encrypted(archive,ready.database_path,passphrase=PASSWORD)
    assert Path(ready.database_path).read_bytes()==original
    existing=tmp_path/'already.sqlite3'; existing.write_bytes(b'keep')
    with pytest.raises(FileExistsError):
        import_encrypted(archive,existing,passphrase=PASSWORD)
    assert existing.read_bytes()==b'keep'


def test_encrypted_archive_checks_bot_identity(ready,tmp_path):
    from app.database import token_fingerprint,utcnow
    with database.session(write=True) as db:
        db.execute('INSERT INTO bot_identity(id,token_fingerprint,created_at) VALUES(1,?,?)',
                   (token_fingerprint(TOKEN),utcnow()))
    archive=export_encrypted(tmp_path/'portable.tbackup',passphrase=PASSWORD)
    dest=tmp_path/'new.sqlite3'
    with pytest.raises(ValueError,match='другому'):
        import_encrypted(archive,dest,passphrase=PASSWORD,bot_token=TOKEN+'wrong')
    assert not dest.exists()
    restored=import_encrypted(archive,dest,passphrase=PASSWORD,bot_token=TOKEN)
    assert restored['identity']=='matched'


def test_encrypted_rejects_short_password_and_bad_format(ready,tmp_path):
    with pytest.raises(EncryptedBackupError,match='14'):
        export_encrypted(tmp_path/'secret.tbackup',passphrase='abc')
    assert not list(tmp_path.glob('*.tbackup*'))
    garbage=tmp_path/'garbage.tbackup';garbage.write_bytes(b'abc')
    with pytest.raises(EncryptedBackupError,match='формат'):
        import_encrypted(garbage,tmp_path/'new.sqlite3',passphrase=PASSWORD)


def test_production_files_are_private_by_default(ready):
    project = Path(__file__).resolve().parents[3]
    botroot = Path(__file__).resolve().parents[1]
    compose = (project/'compose.yaml').read_text(encoding='utf-8')
    dockerfile = (botroot/'Dockerfile').read_text(encoding='utf-8')
    ignore = (botroot/'.dockerignore').read_text(encoding='utf-8')
    assert 'python", "-m", "app.production' in dockerfile
    assert 'USER 10001:10001' in dockerfile
    assert 'read_only: true' in compose
    assert 'tourist_runtime:/app/runtime' in compose
    assert 'tourist_backups:/app/backups' in compose
    assert '80:80' in compose and '443:443' in compose
    assert '8000:8000' not in compose
    assert '.env' in ignore and 'credentials*.json' in ignore
    assert (project/'Caddyfile').read_text(encoding='utf-8').count('reverse_proxy tourist:8000') == 1


def test_container_healthcheck_handles_no_server():
    assert healthcheck('http://127.0.0.1:1/ready') is False

@pytest.mark.parametrize('bad_url', [
    'https://[invalid', 'https://club.example.org:notaport',
    'https://user:secret@club.example.org',
])
def test_invalid_production_url_never_crashes_with_traceback(ready, bad_url):
    cfg=replace(production_config(ready),webapp_url=bad_url)
    with pytest.raises(StartupError,match='WEBAPP_URL'):
        validate_production(cfg,domain='club.example.org',in_container=True)


def test_export_disk_write_failure_removes_partial_and_target(ready,tmp_path,monkeypatch):
    from scripts import encrypted_backup as backup
    # Exercise the destination publication phase (not SQLite backup creation).
    monkeypatch.setattr(backup,'_backup_work_dir',lambda:tmp_path)
    def fail_copyfileobj(src, out, length):
        out.write(b'broken-partial-encrypted-file')
        raise OSError('disk full')
    monkeypatch.setattr(backup.shutil,'copyfileobj',fail_copyfileobj)
    dest=tmp_path/'disk-full.tbackup'
    with pytest.raises(OSError,match='disk full'):
        backup.export_encrypted(dest,passphrase=PASSWORD)
    assert not dest.exists() and not (tmp_path/'disk-full.tbackup.partial').exists()
    assert not list(tmp_path.glob('tourist-export-*'))


def test_readiness_not_cacheable(ready):
    with TestClient(api.app) as client:
        result=client.get('/ready')
        assert result.headers['cache-control']=='no-store'


def test_encrypted_export_produces_distinct_ciphertext(ready,tmp_path):
    a=export_encrypted(tmp_path/'a.tbackup',passphrase=PASSWORD)
    b=export_encrypted(tmp_path/'b.tbackup',passphrase=PASSWORD)
    assert a.read_bytes() != b.read_bytes()
    assert a.read_bytes()[:len(MAGIC)]==b.read_bytes()[:len(MAGIC)]==MAGIC


def test_doctor_checks_encryption_dependency(ready):
    from scripts.doctor import diagnose
    results=diagnose('demo',require_packages=True,cfg=ready)
    matches=[item for item in results if 'cryptography' in item['message']]
    assert len(matches)==1 and matches[0]['level']=='OK'
