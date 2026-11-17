from fastapi.testclient import TestClient
from app.api import app
from app import service


def test_public_schedule_and_protected_profile(fresh):
    with TestClient(app) as client:
        assert client.get('/health').json()['ok']
        assert client.get('/api/schedule').status_code==200
        assert client.get('/api/me',headers={'Host':'public.example'}).status_code==401
        mine=client.get('/api/me')
        assert mine.status_code==200
        assert not mine.json()['profile_ready']
        updated=client.put('/api/profile',json={'full_name':'Тестовый Гость','phone':'+79992223344','nickname':'Игрок-1'})
        assert updated.status_code==200
        assert client.get('/api/me').json()['profile_ready']


def test_admin_access_blocked(fresh):
    with TestClient(app) as c:
        assert c.get('/api/admin/pending').status_code==403
        assert c.post('/api/admin/roles',json={'telegram_id':100,'role':'admin'}).status_code==403


def test_admin_can_create_event(ready,next_thursday):
    with TestClient(app) as c:
        headers={'X-Demo-User-ID':'42'}
        r=c.post('/api/admin/events',headers=headers,json={'kind':'mafia','title':'Тестовая мафия','starts_at':next_thursday,'capacity':10,'format':'classic'})
        assert r.status_code==200, r.text
        id=r.json()['id']
        a=c.post(f'/api/events/{id}/join',headers={'X-Demo-User-ID':'100'})
        assert a.status_code==200,a.text
        p=c.get('/api/admin/pending',headers=headers).json()
        assert len(p['events'])==1
        d=c.post('/api/admin/decide',headers=headers,json={'category':'event','request_id':a.json()['id'],'approve':True})
        assert d.status_code==200
        assert c.get(f'/api/events/{id}/confirmed').json()==[{'nickname_snapshot':'Ник100'}]
