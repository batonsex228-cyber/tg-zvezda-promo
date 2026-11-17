"""v0.8 regressions: Sheets mirrors newly created Telegram users and real HMAC integration."""
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from app import config, database, service, sheets


def revision():
    return sheets.status()['revision']


def test_new_user_marks_google_mirror_dirty_after_first_export(fresh):
    with database.session(write=True) as c:
        c.execute('UPDATE sync_jobs SET synced_once=1,synced_revision=revision WHERE id=1')
    before=revision()
    service.ensure_user(200001,'Новый игрок')
    assert revision()==before+1
    assert service.get_user(200001)['first_name']=='Новый игрок'


def test_refresh_same_profile_does_not_force_endless_sheets_exports(fresh):
    before=revision()
    for _ in range(10): service.ensure_user(100,'Guest100')
    assert revision()==before
    u=service.get_user(100)
    service.ensure_user(100,'Другой ник Telegram')
    assert revision()==before+1
    assert service.get_user(100)['first_name']=='Другой ник Telegram'
    assert service.get_user(100)['updated_at']>=u['updated_at']
    for _ in range(10):service.ensure_user(100,'Другой ник Telegram')
    assert revision()==before+1


def test_owner_reassignment_triggers_google_export_once(fresh,monkeypatch):
    config2=replace(fresh,owner_telegram_id=100)
    monkeypatch.setattr(service,'settings',config2)
    before=revision()
    assert service.ensure_user(100)['role']=='owner'
    assert service.get_user(42)['role']=='guest'
    assert revision()==before+1  # both changes in one atomic transaction
    service.ensure_user(100)
    assert revision()==before+1


def test_first_sheets_export_cannot_lose_guest_created_during_export(fresh,monkeypatch):
    import sys
    enabled=replace(fresh,google_sheet_id='SYNTHETIC',google_credentials_file='fake.json')
    monkeypatch.setattr(sheets,'settings',enabled)
    tabs={}
    created={'yes':False}
    class Tab:
        def __init__(self,name):self.name=name
        def clear(self):pass
        def update(self,range_name,values,value_input_option):
            tabs[self.name]=values
            if not created['yes'] and self.name=='Гости':
                created['yes']=True
                service.ensure_user(800001,'Новый во время выгрузки')
    class FakeGspread:
        class WorksheetNotFound(Exception):pass
        @staticmethod
        def service_account(filename):
            return SimpleNamespace(open_by_key=lambda _:SimpleNamespace(
                worksheet=lambda tab: Tab(tab)))
    monkeypatch.setitem(sys.modules,'gspread',FakeGspread)
    assert sheets.sync_once()=='synced'
    r=sheets.status()
    assert r['revision']>r['synced_revision']  # Race was noticed, not silently skipped.
    assert sheets.sync_once()=='synced'
    assert any('800001' in str(row) for row in tabs['Гости'])
    assert sheets.status()['revision']==sheets.status()['synced_revision']


def test_real_hmac_integration_script_isolated_from_telegram_and_google():
    root=Path(__file__).resolve().parents[1]
    process=subprocess.run([sys.executable,'-m','scripts.telegram_flow_smoke'],cwd=root,
                           text=True,capture_output=True,timeout=35)
    assert process.returncode==0, process.stdout+'\n'+process.stderr
    assert 'real_telegram_contacted": false' in process.stdout
    assert 'PASS: signed Mini App' in process.stdout


def test_no_real_credentials_or_data_in_new_integrations():
    root=Path(__file__).resolve().parents[1]
    for name in ('scripts/telegram_flow_smoke.py','scripts/telegram_mode_browser_smoke.py'):
        text=(root/name).read_text(encoding='utf-8')
        assert 'os.getenv("BOT_TOKEN")' not in text
        assert "os.getenv('BOT_TOKEN')" not in text
        assert 'TemporaryDirectory' in text
