"""v0.14: safe booking retries, privacy and explicit owner-managed delivery recovery."""
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
import pytest
from app import api, database, notifications, service


def _outbox_rows():
    with database.session() as c:
        return [dict(r) for r in c.execute('SELECT * FROM notification_outbox ORDER BY id')]


def _counts():
    with database.session() as c:
        return (c.execute('SELECT COUNT(*) FROM audit').fetchone()[0],
                c.execute('SELECT COUNT(*) FROM notification_outbox').fetchone()[0])


@pytest.mark.parametrize('approve_before', [False, True])
def test_event_cancel_retry_is_exactly_one_request(ready, next_thursday, approve_before):
    e = service.create_event(42, 'mafia', 'Игра с отменой', next_thursday, 10, 'classic')
    rid = service.join_event(100, e['id'])
    if approve_before:
        service.decide(42, 'event', rid, True)
    service.request_cancel(100, 'event', rid)
    original = _counts()
    assert service.request_cancel(100, 'event', rid) is True
    assert _counts() == original  # no duplicate alert to the staff and no audit spam
    assert service.request_status(100, 'event', rid) == 'cancel_requested'
    assert service.decide(42, 'event', rid, False)['status'] == ('confirmed' if approve_before else 'pending')


def test_billiard_cancel_retry_keeps_one_reserved_slot(ready):
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(timespec='seconds')
    rid = service.billiard_book(100, future, 2, 2)
    service.request_cancel(100, 'billiard', rid)
    original = _counts()
    assert service.request_cancel(100, 'billiard', rid)
    assert _counts() == original
    with pytest.raises(service.BusinessError, match='занят'):
        service.billiard_book(101, future, 1, 1)


def test_user_cannot_cancel_another_users_request(ready, next_thursday):
    event = service.create_event(42, 'mafia', 'Закрытая отмена', next_thursday, 10, 'classic')
    rid = service.join_event(100, event['id'])
    with pytest.raises(service.BusinessError):
        service.request_cancel(101, 'event', rid)
    assert service.request_status(100, 'event', rid) == 'pending'


def test_cannot_repeat_cancel_after_decision(ready, next_thursday):
    event = service.create_event(42, 'mafia', 'После отмены', next_thursday, 10, 'classic')
    rid = service.join_event(100, event['id'])
    service.request_cancel(100, 'event', rid)
    assert service.decide(42, 'event', rid, True)['status'] == 'cancelled'
    with pytest.raises(service.BusinessError, match='нельзя'):
        service.request_cancel(100, 'event', rid)


def test_public_schedule_does_not_expose_creator_telegram_id(ready, next_thursday):
    service.create_event(42, 'mafia', 'Открытая игра', next_thursday, 10, 'classic')
    safe = {'id', 'kind', 'title', 'format', 'starts_at', 'capacity', 'min_players',
            'stack', 'blinds', 'status', 'occupied', 'confirmed'}
    with TestClient(api.app) as c:
        events = c.get('/api/schedule').json()
        assert len(events) == 1
        assert set(events[0]) == safe
        assert 'created_by' not in c.get('/api/schedule').text
        assert events[0]['title'] == 'Открытая игра'


def test_cancel_retries_work_through_api(ready, next_thursday):
    event = service.create_event(42, 'mafia', 'Проверка сети', next_thursday, 10, 'classic')
    rid = service.join_event(100, event['id'])
    with TestClient(api.app) as c:
        first = c.post(f'/api/event/{rid}/cancel', headers={'X-Demo-User-ID': '100'})
        second = c.post(f'/api/event/{rid}/cancel', headers={'X-Demo-User-ID': '100'})
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json() == {'status': 'cancel_requested'}


def _failed(recipient, error, *, purpose='system', key=None, state='failed'):
    with database.session(write=True) as c:
        service.enqueue(c, recipient, 'Системное уведомление', purpose=purpose)
        mid = c.execute('SELECT MAX(id) FROM notification_outbox').fetchone()[0]
        c.execute('UPDATE notification_outbox SET state=?,last_error=?,bot_key=? WHERE id=?',
                  (state, error, key or service.bot_key(), mid))
        return mid


def test_owner_can_requeue_only_transient_system_failures(ready):
    failed = _failed(100, 'HTTP 503')
    timed = _failed(101, 'ReadTimeout')
    blocked = _failed(102, 'HTTP 403')
    reminder = _failed(100, 'HTTP 503', purpose='reminder')
    sent = _failed(101, 'ReadTimeout', state='sent')
    other_bot = _failed(102, 'HTTP 500', key='DIFFERENT_BOT')
    with TestClient(api.app) as c:
        result = c.post('/api/admin/notifications/retry', headers={'X-Demo-User-ID': '42'})
        assert result.status_code == 200 and result.json()['requeued'] == 2
    with database.session() as db:
        state = {r['id']: dict(r) for r in db.execute('SELECT * FROM notification_outbox')}
    assert state[failed]['state'] == state[timed]['state'] == 'pending'
    assert state[failed]['attempts'] == 0 and state[failed]['last_error'] is None
    for mid in (blocked, reminder, sent, other_bot):
        assert state[mid]['state'] in ('failed', 'sent')
    assert notifications.retry_transient_failures()['requeued'] == 0


def test_notification_retry_requires_owner_even_for_senior(ready):
    service.set_role(42, 101, 'senior')
    with TestClient(api.app) as c:
        for user in (100, 101, 102):
            assert c.post('/api/admin/notifications/retry', headers={'X-Demo-User-ID': str(user)}).status_code == 403
        assert c.post('/api/admin/notifications/retry', headers={'X-Demo-User-ID': '42'}).status_code == 200


def test_notification_retry_limit_and_protected_data(ready):
    for uid in range(30):
        _failed(100, 'HTTP 502')
    result = notifications.retry_transient_failures(limit=100)
    assert result == {'requeued': 20, 'limit': 20}
    # Retrying is not sending: the worker still delivers separately.
    rows = _outbox_rows()
    assert sum(x['state'] == 'pending' for x in rows) == 20
    assert sum(x['state'] == 'failed' for x in rows) == 10


def test_notification_retry_does_not_queue_unknown_error(ready):
    bad = _failed(100, 'HTTP 400')
    unknown = _failed(101, 'UntrustedCustomError')
    assert notifications.retry_transient_failures()['requeued'] == 0
    assert all(r['state']=='failed' for r in _outbox_rows() if r['id'] in (bad, unknown))


def test_stage14_miniapp_has_confirmed_owner_retry_and_no_secrets():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    html=(root/'web/index.html').read_text(encoding='utf-8')
    js=(root/'web/app.js').read_text(encoding='utf-8')
    assert 'id="operations-box"' in html
    assert 'data-retry-notifications="1"' in html
    assert "window.confirm('Повторить отправку" in js
    assert "'/api/admin/notifications/retry'" in js
