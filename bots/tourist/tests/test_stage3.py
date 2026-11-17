"""Stage 3 regression tests for real booking rules, controlled reminders and Mini App dashboard."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api, config, database, notifications, service
from scripts.doctor import diagnose
from scripts.local_smoke import main as smoke


def _reminders():
    with database.session() as c:
        return [dict(r) for r in c.execute("SELECT * FROM notification_outbox WHERE purpose='reminder' ORDER BY id")]


def _enable_reminders(monkeypatch, original, hours=1):
    replacement = replace(original, reminder_hours_before=hours)
    monkeypatch.setattr(service, 'settings', replacement)
    monkeypatch.setattr(notifications, 'settings', replacement)
    return replacement


def test_refuse_pending_cancellation_restores_pending(ready,next_thursday):
    event = service.create_event(42, 'mafia', 'Мафия без подтверждения', next_thursday, 10, 'classic')
    request = service.join_event(100, event['id'])
    service.request_cancel(100,'event',request)
    assert service.decide(42,'event',request,False)['status']=='pending'
    assert service.my_requests(100)['events'][0]['status']=='pending'
    assert service.list_pending(42)['events'][0]['id']==request
    assert service.list_events()[0]['occupied']==1


def test_refuse_pending_billiard_cancel_restores_pending(ready):
    when = (datetime.now(timezone.utc)+timedelta(days=3)).replace(minute=0,second=0,microsecond=0)
    request=service.billiard_book(100,when.isoformat(),1,2)
    service.request_cancel(100,'billiard',request)
    assert service.decide(42,'billiard',request,False)['status']=='pending'


def test_reminder_created_only_on_approval_and_not_due_yet(ready,next_thursday,monkeypatch):
    _enable_reminders(monkeypatch,ready)
    event = service.create_event(42,'mafia','Тестовое напоминание',next_thursday,10,'classic')
    request=service.join_event(100,event['id'])
    assert _reminders()==[]
    service.decide(42,'event',request,True)
    rows=_reminders()
    assert len(rows)==1 and rows[0]['entity_id']==request and rows[0]['entity_type']=='event'
    expected=datetime.fromisoformat(event['starts_at'])-timedelta(hours=1)
    assert datetime.fromisoformat(rows[0]['next_attempt_at'])==expected
    assert rows[0]['telegram_id']==100
    assert notifications.reminder_still_valid(rows[0])
    assert all(x['purpose']!='reminder' for x in notifications.due_messages())


def test_reminder_disabled_by_default(ready,next_thursday):
    event = service.create_event(42,'mafia','Без напоминания',next_thursday,10,'classic')
    rid=service.join_event(100,event['id'])
    service.decide(42,'event',rid,True)
    assert _reminders()==[]


def test_reminder_deleted_on_cancel_and_rebuilt_if_cancel_refused(ready,next_thursday,monkeypatch):
    _enable_reminders(monkeypatch,ready)
    event=service.create_event(42,'mafia','Мафия в четверг',next_thursday,10,'classic')
    rid=service.join_event(100,event['id']);service.decide(42,'event',rid,True)
    assert len(_reminders())==1
    service.request_cancel(100,'event',rid)
    assert _reminders()==[]
    assert service.decide(42,'event',rid,False)['status']=='confirmed'
    assert len(_reminders())==1
    service.request_cancel(100,'event',rid)
    service.decide(42,'event',rid,True)
    assert _reminders()==[]


def test_reminder_rescheduled_after_event_edit(ready,next_thursday,monkeypatch):
    _enable_reminders(monkeypatch,ready)
    e=service.create_event(42,'mafia','Старая игра',next_thursday,10,'classic')
    rid=service.join_event(100,e['id']);service.decide(42,'event',rid,True)
    start=(datetime.fromisoformat(next_thursday)+timedelta(hours=2)).isoformat()
    service.edit_event(42,e['id'],'mafia','Новая игра',start,10,'classic')
    items=_reminders()
    assert len(items)==1
    assert 'Новая игра' in items[0]['message']
    assert datetime.fromisoformat(items[0]['next_attempt_at'])==datetime.fromisoformat(e['starts_at'])+timedelta(hours=1)
    service.edit_event(42,e['id'],'mafia','Новая игра',start,10,'classic',status='cancelled')
    assert _reminders()==[]


def test_stale_reminder_suppressed_even_if_row_was_not_deleted(ready,next_thursday,monkeypatch):
    _enable_reminders(monkeypatch,ready)
    e=service.create_event(42,'mafia','Мафия',next_thursday,10,'classic')
    rid=service.join_event(100,e['id']);service.decide(42,'event',rid,True)
    row=_reminders()[0]
    assert notifications.reminder_still_valid(row)
    with database.session(write=True) as c:
        c.execute("UPDATE applications SET status='cancelled' WHERE id=?",(rid,))
    assert not notifications.reminder_still_valid(row)
    notifications.discard_stale_reminder(row)
    assert _reminders()==[]


def test_billiard_reminder_confirmation_and_rejection(ready,monkeypatch):
    _enable_reminders(monkeypatch,ready)
    d=(datetime.now(timezone.utc)+timedelta(days=3)).replace(hour=17,minute=0,second=0,microsecond=0)
    rid=service.billiard_book(100,d.isoformat(),2,3)
    service.decide(42,'billiard',rid,True)
    assert _reminders()[0]['entity_type']=='billiard'
    service.request_cancel(100,'billiard',rid)
    service.decide(42,'billiard',rid,True)
    assert not _reminders()


def test_dashboard_has_counts_and_requires_admin(ready,next_thursday):
    e=service.create_event(42,'mafia','Будущая мафия',next_thursday,10,'classic')
    a=service.join_event(100,e['id'])
    service.decide(42,'event',a,True)
    service.join_event(101,e['id'])
    numbers=service.admin_dashboard(42)
    assert numbers['upcoming_events']==1
    assert numbers['confirmed_events']==1
    assert numbers['event_requests']==1
    assert numbers['pending_total']==1
    with pytest.raises(service.BusinessError):service.admin_dashboard(100)
    with TestClient(api.app) as client:
        assert client.get('/api/admin/dashboard',headers={'X-Demo-User-ID':'100'}).status_code==403
        r=client.get('/api/admin/dashboard',headers={'X-Demo-User-ID':'42'})
        assert r.status_code==200 and r.json()['confirmed_events']==1
        assert 'admin-metrics' in client.get('/').text
        assert 'loadDashboard' in client.get('/assets/app.js').text


def test_schema_migration_is_idempotent(ready):
    database.init_db();database.init_db()
    with database.session() as c:
        for table, columns in {
            'applications':('cancel_origin',),'billiard_bookings':('cancel_origin',),
            'notification_outbox':('purpose','entity_type','entity_id')}.items():
            actual={r['name'] for r in c.execute(f'PRAGMA table_info({table})')}
            assert set(columns).issubset(actual)
    assert service.get_user(100)['nickname']=='Ник100'


def test_doctor_can_check_demo_without_live_secrets(fresh):
    info=diagnose('demo',Path(__file__).resolve().parents[1],fresh,require_packages=False)
    assert not [x for x in info if x['level']=='ERROR']
    live=diagnose('live',Path(__file__).resolve().parents[1],fresh,require_packages=False)
    assert any(x['level']=='ERROR' and 'BOT_TOKEN' in x['message'] for x in live)
    assert all('123456' not in x['message'] for x in live)


def test_isolated_server_smoke_does_not_touch_main_database(fresh):
    path=Path(fresh.database_path)
    original=path.stat().st_size
    smoke()
    assert path.exists() and path.stat().st_size>=original
