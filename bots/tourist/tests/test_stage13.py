"""v0.13 real-deployment preflight: never write a different client's database.

Google tests are isolated; they never contact Google or use real credentials.
"""
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import cli, config, database, service
from scripts import check_google_online as google

TOKEN_ONE = '123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz11'
TOKEN_TWO = '123457:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz22'


def _bind_db(ready, monkeypatch):
    s = replace(ready, bot_token=TOKEN_ONE, demo_mode=False)
    monkeypatch.setattr(database, 'settings', s)
    database.bind_bot_identity()
    return s


def test_cli_fails_before_any_unsafe_command_when_identity_mismatch(ready, monkeypatch):
    _bind_db(ready, monkeypatch)
    other = replace(ready, bot_token=TOKEN_TWO, demo_mode=False)
    monkeypatch.setattr(database, 'settings', other)
    monkeypatch.setattr(cli, 'settings', other)
    # An older DB requiring migrations proves no schema changes happen first.
    with database.session(write=True) as c:
        c.execute('DROP TABLE idempotency_keys')
    monkeypatch.setattr(sys, 'argv', ['tourist-cli', 'seed-demo'])
    with pytest.raises(RuntimeError, match='до миграции'):
        cli.main()
    with database.session() as c:
        assert c.execute("SELECT 1 FROM sqlite_master WHERE name='idempotency_keys'").fetchone() is None
        assert c.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 0
        assert c.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 4


@pytest.mark.parametrize('command', ['sync-now', 'seed-demo'])
def test_cli_rejects_other_bot_in_separate_real_process(ready, monkeypatch, command):
    _bind_db(ready, monkeypatch)
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, BOT_TOKEN=TOKEN_TWO, OWNER_TELEGRAM_ID='42', DEMO_MODE='false',
               DATABASE_PATH=str(database.database_path()), GOOGLE_SHEET_ID='',
               GOOGLE_CREDENTIALS_FILE='')
    process = subprocess.run([sys.executable, '-m', 'app.cli', command], cwd=root,
                             env=env, text=True, capture_output=True, timeout=12)
    assert process.returncode != 0
    assert TOKEN_ONE not in (process.stdout + process.stderr)
    assert TOKEN_TWO not in (process.stdout + process.stderr)
    with database.session() as c:
        assert c.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 0


def _json(tmp_path, **changes):
    data = {'type': 'service_account', 'client_email': 'robot@example.invalid',
            'private_key': 'FAKE-NOT-REAL-KEY', 'token_uri': 'https://oauth2.googleapis.com/token'}
    data.update(changes)
    file = tmp_path / 'secret.json'
    file.write_text(json.dumps(data), encoding='utf-8')
    return file


def _cfg():
    return replace(config.settings, google_sheet_id='not-a-real-sheet-id',
                   google_credentials_file='not-a-real-file')


def test_google_unconfigured_is_safe_and_does_not_use_network(tmp_path):
    def fail(**kwargs):
        raise AssertionError('Should not contact Google')
    report = google.check_google_online(config=replace(_cfg(),google_sheet_id=''),
                                        path=tmp_path / 'no-file', client_factory=fail)
    assert report['status'] == 'not_configured'
    assert report['write_permission_verified'] is False


def test_google_metadata_only_never_reads_rows_or_writes(tmp_path):
    key = _json(tmp_path)
    interactions = []
    class Spreadsheet:
        def worksheets(self):
            interactions.append('worksheets')
            return [SimpleNamespace(title='Private spreadsheet tab')]
        def __getattr__(self, name):
            raise AssertionError('Forbidden spreadsheet operation: ' + name)
    def account(*, filename):
        assert filename == str(key)
        return SimpleNamespace(open_by_key=lambda sheet_id: Spreadsheet())
    report = google.check_google_online(config=_cfg(),path=key,client_factory=account)
    assert report == {'configured': True, 'credentials_valid': True,
                      'spreadsheet_readable': True, 'write_permission_verified': False,
                      'status': 'read_only_ok'}
    assert interactions == ['worksheets']
    assert 'secret' not in json.dumps(report)


@pytest.mark.parametrize('corruption', [
    '{wrong json', '{}', '{"type":"authorized_user"}',
    '{"type":"service_account","client_email":"robot@example.invalid"}',
])
def test_google_invalid_key_fails_closed_without_network(tmp_path, corruption):
    secret = tmp_path / 'broken.json'; secret.write_text(corruption)
    def fail(**kwargs):
        raise AssertionError('Should not contact Google')
    report=google.check_google_online(config=_cfg(),path=secret,client_factory=fail)
    assert report['status']=='credentials_invalid'
    assert report['spreadsheet_readable'] is False


def test_google_rejects_untrusted_oauth_token_endpoint(tmp_path):
    secret=_json(tmp_path, token_uri='http://evil.example/token')
    def no_network(**kwargs):
        raise AssertionError('Must not request credentials from arbitrary endpoint')
    result=google.check_google_online(config=_cfg(),path=secret,client_factory=no_network)
    assert result['status']=='credentials_invalid'


def test_google_unconfigured_cli_is_not_reported_as_pass(monkeypatch,capsys):
    monkeypatch.setattr(google,'check_google_online',lambda: {'status':'not_configured'})
    assert google.main(['--json'])==2
    assert 'not_configured' in capsys.readouterr().out


def test_google_symlink_key_rejected(tmp_path):
    secret=_json(tmp_path)
    link=tmp_path/'link.json';link.symlink_to(secret)
    report=google.check_google_online(config=_cfg(),path=link,
                                      client_factory=lambda **kw:None)
    assert report['status']=='credentials_invalid'


def test_google_connection_errors_hide_secrets_and_fail_not_success(tmp_path):
    secret=_json(tmp_path)
    def broken(**kwargs):
        raise ConnectionError('private api key: PASSWORD_AND_SHEET_ID_MUST_STAY_HIDDEN')
    report=google.check_google_online(config=_cfg(),path=secret,client_factory=broken)
    assert report['status']=='connection_failed'
    assert 'PASSWORD' not in str(report) and 'SHEET_ID' not in str(report)
    assert not report['spreadsheet_readable']


def test_docs_and_windows_helpers_exist():
    root=Path(__file__).resolve().parents[1]
    assert (root/'CHECK_GOOGLE_ONLINE_WINDOWS.bat').exists()
    assert (root/'UAT_CHECKLIST_RU.md').exists()
    assert 'initialize_storage()' in (root/'app/cli.py').read_text()


def test_frontend_assets_use_release_version_cache_busting():
    root=Path(__file__).resolve().parents[1]
    from app.version import VERSION
    html=(root/'web/index.html').read_text()
    assert f'/assets/app.js?v={VERSION}' in html
    assert f'/assets/styles.css?v={VERSION}' in html


def test_live_google_check_does_not_require_real_credentials_in_release():
    root=Path(__file__).resolve().parents[1]
    # The distributed package contains code and instructions, never client JSON.
    assert not list(root.glob('*.json'))
    assert not list(root.rglob('google-credentials.json'))
    assert not (root/'.env').exists()


def test_cli_with_missing_token_cannot_edit_bound_client_database(ready, monkeypatch):
    _bind_db(ready,monkeypatch)
    root=Path(__file__).resolve().parents[1]
    env=dict(os.environ, BOT_TOKEN='', DEMO_MODE='true', OWNER_TELEGRAM_ID='42',
             DATABASE_PATH=str(database.database_path()), GOOGLE_SHEET_ID='', GOOGLE_CREDENTIALS_FILE='')
    r=subprocess.run([sys.executable,'-m','app.cli','seed-demo'],cwd=root,
                     env=env,text=True,capture_output=True,timeout=12)
    assert r.returncode!=0
    assert 'BOT_TOKEN' in r.stderr or 'BOT_TOKEN' in r.stdout
    with database.session() as c:
        assert c.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 0


def test_cli_with_missing_token_allows_fresh_unbound_demo(ready,monkeypatch,tmp_path):
    new_db=tmp_path/'fresh_unbound.sqlite3'
    root=Path(__file__).resolve().parents[1]
    env=dict(os.environ,BOT_TOKEN='',DEMO_MODE='true',OWNER_TELEGRAM_ID='42',
             DATABASE_PATH=str(new_db),GOOGLE_SHEET_ID='',GOOGLE_CREDENTIALS_FILE='')
    r=subprocess.run([sys.executable,'-m','app.cli','seed-demo'],cwd=root,
                     env=env,text=True,capture_output=True,timeout=12)
    assert r.returncode==0, r.stderr
    with sqlite3.connect(new_db) as c:
        assert c.execute('SELECT COUNT(*) FROM events').fetchone()[0]==3
