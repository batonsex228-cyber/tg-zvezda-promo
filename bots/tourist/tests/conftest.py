from dataclasses import replace
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import pytest
from app import config, database, service, api

@pytest.fixture
def fresh(tmp_path,monkeypatch):
    settings=replace(config.settings,database_path=str(tmp_path/'test.sqlite3'),owner_telegram_id=42,
                     bot_token='',demo_mode=True,google_sheet_id='',google_credentials_file='')
    for mod in (config,database,service,api):
        monkeypatch.setattr(mod,'settings',settings)
    database.init_db()
    service.ensure_user(42,'Owner')
    for i in (100,101,102):service.ensure_user(i,f'Guest{i}')
    return settings

@pytest.fixture
def ready(fresh):
    for i in (100,101,102):
        service.set_profile(i,'Гость '+str(i),'+79990000'+str(i).zfill(3),'Ник'+str(i))
    return fresh

@pytest.fixture
def next_thursday():
    n=datetime.now(ZoneInfo('Europe/Moscow'))+timedelta(days=1)
    while n.weekday()!=3:n+=timedelta(days=1)
    return n.replace(hour=19,minute=0,second=0,microsecond=0).isoformat()

@pytest.fixture
def next_sunday():
    n=datetime.now(ZoneInfo('Europe/Moscow'))+timedelta(days=1)
    while n.weekday()!=6:n+=timedelta(days=1)
    return n.replace(hour=18,minute=0,second=0,microsecond=0).isoformat()
