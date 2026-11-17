"""v0.12 optional offsite encrypted snapshots: all tests are offline (no AWS)."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import hashlib

import pytest
from fastapi.testclient import TestClient

from app import api, operations, maintenance
from scripts.offsite_backup import (
    OffsiteConfig, OffsiteError, read_passphrase, run_once, state_path,
    state_snapshot, save_state,
)
from scripts.encrypted_backup import import_encrypted, MAGIC

PASSWORD = 'A-strong-phrase-for-private-tables-2026!'


class FakeS3:
    def __init__(self, fail=False, tamper=False, corrupt_download=False):
        self.fail, self.tamper = fail, tamper
        self.corrupt_download = corrupt_download
        self.uploads = []
        self.objects = {}

    def upload_file(self, filename, bucket, key, ExtraArgs):
        if self.fail:
            raise ConnectionError('private credentials must never be logged')
        data = Path(filename).read_bytes()
        self.uploads.append((bucket, key, ExtraArgs))
        self.objects[key] = (data, ExtraArgs)

    def head_object(self, Bucket, Key):
        data, opts = self.objects[Key]
        return {'ContentLength': len(data) + (1 if self.tamper else 0),
                'Metadata': opts['Metadata']}

    def download_file(self, bucket, key, destination):
        data = self.objects[key][0]
        if self.corrupt_download:
            corrupted = bytearray(data)
            corrupted[-8] ^= 1
            data = bytes(corrupted)
        Path(destination).write_bytes(data)


def cfg(tmp_path):
    password_file = tmp_path / 'secret.txt'
    password_file.write_text(PASSWORD)
    return OffsiteConfig(bucket='private-tourist-backups', prefix='club-1/',
                         passphrase_file=str(password_file), interval_hours=24)


def test_config_validates_and_rejects_http_urls(tmp_path):
    x = cfg(tmp_path)
    assert x.validate() == x
    assert replace(x, endpoint_url='https://s3.example.org').validate()
    for url in ('http://s3.example.org', 'https://user:pass@s3.example.org',
                'https://s3.example.org/path', 'https://s3.example.org:9000',
                'https://[not-valid'):
        with pytest.raises(OffsiteError):
            replace(x, endpoint_url=url).validate()


@pytest.mark.parametrize('update', [
    {'bucket':''}, {'bucket':'!bad'}, {'prefix':'../unsafe'},
    {'prefix':'/absolute'}, {'prefix':'bad\\key'}, {'interval_hours':0},
    {'interval_hours':721}, {'passphrase_file':''},
])
def test_config_fail_closed_on_bad_inputs(tmp_path, update):
    with pytest.raises(OffsiteError):
        replace(cfg(tmp_path), **update).validate()


def test_secret_does_not_allow_symlink_or_short_password(tmp_path):
    original = tmp_path / 'secret.txt'; original.write_text('short')
    with pytest.raises(OffsiteError): read_passphrase(str(original))
    original.write_text(PASSWORD+'\n')
    assert read_passphrase(str(original)) == PASSWORD
    link = tmp_path / 'link.txt'; link.symlink_to(original)
    with pytest.raises(OffsiteError): read_passphrase(str(link))


def test_secret_read_refuses_multiline(tmp_path):
    file=tmp_path/'secret.txt';file.write_text(PASSWORD+'\nextra')
    with pytest.raises(OffsiteError): read_passphrase(str(file))


def test_offsite_upload_is_only_encrypted_data(ready,tmp_path):
    s3 = FakeS3()
    folder = tmp_path / 'backups'
    out = run_once(cfg(tmp_path), s3=s3, folder=folder)
    assert out == 'uploaded-and-download-verified'
    assert len(s3.uploads) == 1
    bucket,key,opts=s3.uploads[0]
    assert bucket == 'private-tourist-backups'
    assert key.startswith('club-1/') and key.endswith('.tbackup')
    assert opts['ServerSideEncryption'] == 'AES256'
    ciphertext = s3.objects[key][0]
    assert ciphertext.startswith(MAGIC)
    assert b'Guest100' not in ciphertext and not ciphertext.startswith(b'SQLite format 3')
    assert opts['Metadata']['tourist-sha256']==hashlib.sha256(ciphertext).hexdigest()
    assert state_snapshot(folder)['present']
    assert sorted(p.name for p in folder.iterdir()) == ['.offsite_last_success.json']
    # Real restore with the *same* password exercises authenticated AES-GCM data.
    archive = tmp_path/'download.tbackup'; archive.write_bytes(ciphertext)
    restored = tmp_path/'download.sqlite3'
    assert import_encrypted(archive,restored,passphrase=PASSWORD)['counts']['users'] >= 4


def test_does_not_duplicate_until_interval_elapses(ready,tmp_path):
    s3=FakeS3();folder=tmp_path/'offsite';t=datetime.now(timezone.utc)
    x=cfg(tmp_path)
    assert run_once(x,s3=s3,folder=folder,now=t)=='uploaded-and-download-verified'
    assert run_once(x,s3=s3,folder=folder,now=t+timedelta(minutes=1))=='up-to-date'
    assert len(s3.uploads)==1
    assert run_once(x,s3=s3,folder=folder,now=t+timedelta(hours=25))=='uploaded-and-download-verified'
    assert len(s3.uploads)==2


def test_upload_failure_never_marks_success_and_cleans_files(ready,tmp_path):
    folder=tmp_path/'offsite';folder.mkdir()
    with pytest.raises(ConnectionError):
        run_once(cfg(tmp_path),s3=FakeS3(fail=True),folder=folder)
    assert not state_path(folder).exists()
    assert list(folder.iterdir()) == []


def test_bad_remote_head_does_not_publish_success(ready,tmp_path):
    folder=tmp_path/'offsite';folder.mkdir()
    with pytest.raises(OffsiteError, match='Проверка'):
        run_once(cfg(tmp_path),s3=FakeS3(tamper=True),folder=folder)
    assert not state_path(folder).exists()
    assert not list(folder.iterdir())


def test_failed_upload_does_not_erase_previous_success(ready,tmp_path):
    folder=tmp_path/'offsite';folder.mkdir()
    previous='2026-11-01T00:00:00+00:00'
    save_state(folder,previous,'safe/key',777,'a'*64)
    with pytest.raises(ConnectionError):
        run_once(cfg(tmp_path),s3=FakeS3(fail=True),folder=folder,force=True)
    assert json.loads(state_path(folder).read_text())['uploaded_at']==previous


def test_broken_or_missing_status_is_redacted(tmp_path):
    folder=tmp_path/'offsite';folder.mkdir()
    assert state_snapshot(folder)=={'last_verified_upload_at':None,'age_hours':None,'present':False}
    state_path(folder).write_text('not json')
    assert not state_snapshot(folder)['present']
    save_state(folder,datetime.now(timezone.utc).isoformat(),'private/object',123,'a'*64)
    status=state_snapshot(folder)
    assert 'object_key' not in status and status['present'] is True


def test_owner_operations_show_only_summary(ready,tmp_path,monkeypatch):
    folder=tmp_path/'backup';folder.mkdir()
    monkeypatch.setattr(maintenance,'backup_folder',lambda:folder)
    save_state(folder,datetime.now(timezone.utc).isoformat(),
               'sensitive/client-name/key',1024,'a'*64)
    with TestClient(api.app) as client:
        r=client.get('/api/admin/operations', headers={'X-Demo-User-ID':'42'})
        assert r.status_code==200
        assert r.json()['offsite']['present'] is True
        assert 'sensitive' not in r.text
        denied=client.get('/api/admin/operations',headers={'X-Demo-User-ID':'100'})
        assert denied.status_code==403


def test_offsite_backup_is_not_automatically_enabled_by_dual_deploy():
    root = Path(__file__).resolve().parents[3]
    base = (root/'compose.yaml').read_text(encoding='utf-8')
    assert 'offsite:' not in base
    assert 'offsite_passphrase' not in base
    assert '8000:8000' not in base
    assert 'tourist_backups:/app/backups' in base
    assert '.env' in (root/'.gitignore').read_text(encoding='utf-8')
    assert 'secrets/' in (root/'.dockerignore').read_text(encoding='utf-8')


def test_remote_body_tampering_is_detected_after_head_passes(ready,tmp_path):
    folder=tmp_path/'offsite';folder.mkdir()
    with pytest.raises(OffsiteError,match='Контрольная сумма'):
        run_once(cfg(tmp_path),s3=FakeS3(corrupt_download=True),folder=folder)
    assert not state_path(folder).exists()
    assert not list(folder.iterdir())
