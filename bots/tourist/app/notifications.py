"""Transactional Telegram notification outbox: retry delivery separately from bookings.

At-least-once delivery: a crash after Telegram accepts a message but before we mark
it sent can produce a duplicate. Never rely on Telegram delivery for booking integrity.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
from app.config import settings
from app.telegram_transport import method_url, relay_headers
from app.database import session, utcnow
from app.service import bot_key


def pending_status():
    with session() as c:
        row = c.execute("""SELECT
            SUM(CASE WHEN state='pending' THEN 1 ELSE 0 END) AS pending,
            SUM(CASE WHEN state='sent' THEN 1 ELSE 0 END) AS sent,
            SUM(CASE WHEN state='failed' THEN 1 ELSE 0 END) AS failed
            FROM notification_outbox WHERE bot_key=?""", (bot_key(),)).fetchone()
        return {'pending': row['pending'] or 0, 'sent': row['sent'] or 0, 'failed': row['failed'] or 0}


def due_messages(limit=10):
    with session() as c:
        return [dict(r) for r in c.execute("""SELECT * FROM notification_outbox
           WHERE bot_key=? AND state='pending' AND next_attempt_at<=?
           ORDER BY id LIMIT ?""", (bot_key(), utcnow(), limit))]


def claim_due_messages(limit=10, lease_seconds=45):
    """Atomic temporary claim: a second worker won't send the same batch concurrently.

    If a worker crashes, its uncommitted delivery gets retried after the lease.
    Telegram delivery remains at-least-once, not mathematically exactly-once.
    """
    with session(write=True) as c:
        now = utcnow()
        rows = [dict(r) for r in c.execute("""SELECT * FROM notification_outbox
            WHERE bot_key=? AND state='pending' AND next_attempt_at<=?
            ORDER BY id LIMIT ?""", (bot_key(), now, max(1,min(int(limit),50))))]
        if rows:
            lease_until = (datetime.now(timezone.utc)+timedelta(seconds=lease_seconds)).isoformat(timespec='seconds')
            c.executemany("UPDATE notification_outbox SET next_attempt_at=? WHERE id=? AND state='pending'",
                          [(lease_until,r['id']) for r in rows])
        return rows


def record_outcome(message_id, success, permanent=False, error='', retry_after=None):
    with session(write=True) as c:
        row = c.execute("SELECT attempts,state FROM notification_outbox WHERE id=?", (message_id,)).fetchone()
        if not row or row['state'] != 'pending':
            return
        attempts = row['attempts'] + 1
        if success:
            c.execute("""UPDATE notification_outbox SET state='sent',attempts=?,sent_at=?,last_error=NULL WHERE id=?""",
                      (attempts, utcnow(), message_id))
        elif permanent or attempts >= 12:
            c.execute("""UPDATE notification_outbox SET state='failed',attempts=?,last_error=? WHERE id=?""",
                      (attempts, error[:350], message_id))
        else:
            wait = min(3600, 2 ** min(attempts, 11) * 5)
            if retry_after is not None:
                # Telegram flood-control uses a retry_after hint in seconds.
                try:
                    wait=max(wait,min(3600,max(1,int(retry_after))))
                except (ValueError,TypeError):
                    pass
            next_at = (datetime.now(timezone.utc) + timedelta(seconds=wait)).isoformat(timespec='seconds')
            c.execute("""UPDATE notification_outbox SET attempts=?,last_error=?,next_attempt_at=? WHERE id=?""",
                      (attempts, error[:350], next_at, message_id))


def reminder_still_valid(item: dict) -> bool:
    if item.get('purpose') != 'reminder':
        return True
    now = utcnow()
    with session() as c:
        if item['entity_type'] == 'event':
            r = c.execute("""SELECT a.status,e.starts_at,e.status AS event_status FROM applications a
                 JOIN events e ON e.id=a.event_id WHERE a.id=?""", (item['entity_id'],)).fetchone()
            return bool(r and r['status']=='confirmed' and r['event_status']!='cancelled' and r['starts_at']>now)
        if item['entity_type'] == 'billiard':
            r = c.execute('SELECT status,starts_at FROM billiard_bookings WHERE id=?', (item['entity_id'],)).fetchone()
            return bool(r and r['status']=='confirmed' and r['starts_at']>now)
    return False


def discard_stale_reminder(item: dict):
    with session(write=True) as c:
        c.execute("DELETE FROM notification_outbox WHERE id=? AND state='pending' AND purpose='reminder'", (item['id'],))


async def send_once(client: httpx.AsyncClient, item: dict):
    if not reminder_still_valid(item):
        discard_stale_reminder(item)
        return
    try:
        url = method_url(settings.bot_token, 'sendMessage')
        response = await client.post(url, json={'chat_id': item['telegram_id'], 'text': item['message']}, headers=relay_headers())
        response.raise_for_status()
        data = response.json()
        if data.get('ok') is not True:
            raise RuntimeError('Telegram API не подтвердил отправку')
        record_outcome(item['id'], True)
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        # Invalid / missing users, banned bot, and bad request cannot be retried.
        retry_after=None
        if code==429:
            try:
                retry_after=exc.response.json().get('parameters',{}).get('retry_after')
            except (ValueError,AttributeError,TypeError):
                pass
        record_outcome(item['id'], False, permanent=code in (400,401,403,404), error=f'HTTP {code}',retry_after=retry_after)
    except (httpx.RequestError, ValueError, RuntimeError) as exc:
        record_outcome(item['id'], False, error=type(exc).__name__)


def retry_transient_failures(limit=20):
    """Owner-triggered replay of undelivered *system* messages only.

    Never replay completed messages, stale reminders, or permanent 4xx failures.
    Telegram offers at-least-once delivery: the operator must acknowledge that
    a previously accepted message could exceptionally be delivered twice.
    """
    limit = max(1, min(int(limit), 20))
    transient = {'ConnectError', 'ConnectTimeout', 'ReadTimeout', 'WriteTimeout',
                 'PoolTimeout', 'ReadError', 'WriteError', 'RemoteProtocolError',
                 'RuntimeError', 'HTTP 408', 'HTTP 425', 'HTTP 429',
                 'HTTP 500', 'HTTP 502', 'HTTP 503', 'HTTP 504'}
    with session(write=True) as c:
        rows = c.execute("""SELECT id,last_error FROM notification_outbox
            WHERE bot_key=? AND state='failed' AND purpose='system'
            ORDER BY id LIMIT 500""", (bot_key(),)).fetchall()
        selected = [r['id'] for r in rows if r['last_error'] in transient][:limit]
        if selected:
            c.executemany("""UPDATE notification_outbox
                SET state='pending',attempts=0,last_error=NULL,next_attempt_at=?
                WHERE id=? AND bot_key=? AND state='failed' AND purpose='system'""",
                [(utcnow(), mid, bot_key()) for mid in selected])
    return {'requeued': len(selected), 'limit': limit}


async def background_notifications():
    async with httpx.AsyncClient(timeout=8) as client:
        while True:
            if settings.bot_token:
                try:
                    for item in claim_due_messages():
                        await send_once(client, item)
                except Exception as exc:
                    print(f'[notify] Сбой обработки очереди: {type(exc).__name__}', flush=True)
            await asyncio.sleep(3)
