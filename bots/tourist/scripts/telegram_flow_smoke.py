"""Offline live-auth protocol rehearsal: REAL FastAPI, SQLite and Telegram HMAC.

Run: python -m scripts.telegram_flow_smoke
Does not contact Telegram, Google or Cloudflare; uses synthetic signed initData.
Does not read .env token or write to the configured production database.
"""
import hashlib
import hmac
import json
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from app import api, config, database, notifications, service, sheets

SYNTHETIC_TOKEN = '123456789:Tourist_Offline_Synthetic_Token_Only_Do_Not_Use'


def sign_init_data(token: str, user_id: int, name='Тестовый игрок', *, age=0) -> str:
    """Emulate the signature produced by Telegram (test-only; no real credentials)."""
    fields = {
        'auth_date': str(int(time.time()) - age),
        'user': json.dumps({'id': user_id, 'first_name': name}, ensure_ascii=False, separators=(',', ':')),
    }
    canonical = '\n'.join(f'{key}={value}' for key, value in sorted(fields.items()))
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    fields['hash'] = hmac.new(secret, canonical.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def run(*, database_file: Path, token: str = SYNTHETIC_TOKEN, verbose: bool = False) -> dict:
    """Perform a full owner+guest API flow with signed, expiring credentials."""
    cfg = replace(config.settings, database_path=str(database_file), bot_token=token,
                  demo_mode=False, owner_telegram_id=710001,
                  google_sheet_id='', google_credentials_file='', reminder_hours_before=0)
    for module in (config, database, service, api, notifications, sheets):
        module.settings = cfg
    database.initialize_storage()
    # Client without context manager intentionally avoids background Telegram workers.
    client = TestClient(api.app)
    owner = {'X-Telegram-Init-Data': sign_init_data(token, 710001, 'Владелец')}
    guest = {'X-Telegram-Init-Data': sign_init_data(token, 710002, 'Гость')}
    stranger = {'X-Telegram-Init-Data': sign_init_data(token, 710003, 'Гость 2')}
    assert client.get('/api/me', headers=owner).status_code == 200
    assert client.get('/api/me', headers=guest).status_code == 200
    assert client.get('/api/me', headers=stranger).status_code == 200
    assert client.get('/api/admin/dashboard', headers=guest).status_code == 403
    # User IDs from untrusted test headers cannot override signed Telegram identity.
    spoofed = {**guest, 'X-Demo-User-ID': '710001'}
    assert client.get('/api/admin/dashboard', headers=spoofed).status_code == 403
    assert client.get('/api/me', headers={'X-Telegram-Init-Data': 'spoofed'}).status_code == 401
    old = {'X-Telegram-Init-Data': sign_init_data(token, 710002, age=86401)}
    assert client.get('/api/me', headers=old).status_code == 401

    profile = {'full_name':'Тестовый гость', 'phone':'+79998887766', 'nickname':'Пилот-Тест'}
    assert client.put('/api/profile', headers=guest, json=profile).status_code == 200
    assert client.put('/api/profile', headers=stranger, json={**profile, 'nickname':'Второй'}).status_code == 200
    starts_at = (datetime.now(timezone.utc) + timedelta(days=3)).replace(microsecond=0).isoformat()
    create = client.post('/api/admin/events',headers=owner,json={
        'kind':'poker','title':'Интеграционный турнир','starts_at':starts_at,'capacity':1,
        'min_players':1,'format':'','stack':'10000','blinds':'100/200'})
    assert create.status_code == 200, create.text
    event_id = create.json()['id']
    key = {'X-Idempotency-Key':'same_request_integration_0001'}
    first = client.post(f'/api/events/{event_id}/join',headers={**guest, **key})
    duplicate = client.post(f'/api/events/{event_id}/join',headers={**guest, **key})
    assert first.status_code == 200 and duplicate.json() == first.json()
    rid = first.json()['id']
    denied = client.post(f'/api/events/{event_id}/join',headers=stranger)
    assert denied.status_code == 409, denied.text
    pending = client.get('/api/admin/pending',headers=owner).json()
    assert len(pending['events']) == 1 and pending['events'][0]['id'] == rid
    approved = client.post('/api/admin/decide', headers=owner,
                           json={'category':'event','request_id':rid,'approve':True})
    assert approved.status_code == 200 and approved.json()['status'] == 'confirmed'
    assert client.get('/api/me',headers=guest).json()['requests']['events'][0]['status'] == 'confirmed'
    assert client.post(f'/api/events/{event_id}/join',headers={**guest,**key}).json()['status']=='confirmed'
    assert client.post(f'/api/event/{rid}/cancel',headers=guest).status_code==200
    denied_cancel = client.post('/api/admin/decide',headers=owner,
                                json={'category':'event','request_id':rid,'approve':False})
    assert denied_cancel.json()['status']=='confirmed'
    assert client.post(f'/api/event/{rid}/cancel',headers=guest).status_code==200
    confirmed_cancel=client.post('/api/admin/decide',headers=owner,
                                 json={'category':'event','request_id':rid,'approve':True})
    assert confirmed_cancel.json()['status']=='cancelled'

    billiard_time=(datetime.now(timezone.utc)+timedelta(days=2)).replace(microsecond=0).isoformat()
    booking={'starts_at':billiard_time, 'hours':2, 'guest_count':2}
    b=client.post('/api/billiard',headers={**guest,'X-Idempotency-Key':'booking_integration_0001'},json=booking)
    assert b.status_code==200, b.text
    b2=client.post('/api/billiard',headers=stranger,json=booking)
    assert b2.status_code==409, b2.text
    result=client.post('/api/admin/decide',headers=owner,
                       json={'category':'billiard','request_id':b.json()['id'],'approve':True})
    assert result.json()['status']=='confirmed'
    with database.session() as c:
        outbox=c.execute('SELECT COUNT(*) FROM notification_outbox WHERE bot_key=?', (service.bot_key(),)).fetchone()[0]
        audit=c.execute('SELECT COUNT(*) FROM audit').fetchone()[0]
        guests=c.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    assert outbox >= 4 and audit >= 7 and guests == 3
    summary={'test':'offline signed Telegram integration','users':guests,'event_id':event_id,
             'event_final':'cancelled','billiard_final':'confirmed','queued_notifications':outbox,
             'audit_rows':audit,'verified_auth':True,'real_telegram_contacted':False}
    if verbose:
        print(json.dumps(summary,ensure_ascii=False,indent=2))
    return summary


def main():
    with tempfile.TemporaryDirectory(prefix='tourist_signed_smoke_') as tmp:
        run(database_file=Path(tmp)/'signed_flow.sqlite3',verbose=True)
    print('PASS: signed Mini App -> API -> SQLite -> moderation -> notification outbox')

if __name__ == '__main__':
    main()
