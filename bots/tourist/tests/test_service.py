from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import pytest
from app import service


def test_unique_nickname_casefold(fresh):
    service.set_profile(100,'Иван Иванов','+79991112233','Турист')
    with pytest.raises(service.BusinessError,match='занят'):
        service.set_profile(101,'Петр Петров','+79991112244','турист')


def test_profile_needed_for_join(fresh,next_thursday):
    ev=service.create_event(42,'mafia','Мафия тест',next_thursday,10,'classic')
    with pytest.raises(service.BusinessError,match='профиль'):
        service.join_event(100,ev['id'])


def test_mafia_classic_thursday_required(ready,next_sunday):
    with pytest.raises(service.BusinessError,match='четверг'):
        service.create_event(42,'mafia','Неверная дата',next_sunday,10,'classic')


def test_mafia_city_limits(ready,next_sunday):
    with pytest.raises(service.BusinessError,match='от 10 до 15'):
        service.create_event(42,'mafia','Городская',next_sunday,16,'city',10)
    ev=service.create_event(42,'mafia','Городская',next_sunday,15,'city',10)
    assert ev['min_players']==10


def test_poker_stack_blinds_and_capacity(ready,next_thursday):
    with pytest.raises(service.BusinessError,match='Покер'):
        service.create_event(42,'poker','Турнир',next_thursday,11,stack='10000',blinds='100/200')
    p=service.create_event(42,'poker','Турнир',next_thursday,10,stack='10000',blinds='100/200')
    assert p['capacity']==10


def test_join_reserves_and_duplicate_denied(ready,next_thursday):
    ev=service.create_event(42,'mafia','Мафия тест',next_thursday,10,'classic')
    rid=service.join_event(100,ev['id'])
    with pytest.raises(service.BusinessError,match='уже'):
        service.join_event(100,ev['id'])
    assert service.list_events()[0]['occupied']==1
    assert service.my_requests(100)['events'][0]['id']==rid


def test_admin_approval_and_cancel_request(ready,next_thursday):
    e=service.create_event(42,'mafia','Мафия тест',next_thursday,10,'classic')
    r=service.join_event(100,e['id'])
    with pytest.raises(service.BusinessError,match='прав'):
        service.decide(101,'event',r,True)
    assert service.decide(42,'event',r,True)['status']=='confirmed'
    service.request_cancel(100,'event',r)
    assert service.list_events()[0]['occupied']==1
    assert service.decide(42,'event',r,True)['status']=='cancelled'
    assert service.list_events()[0]['occupied']==0


def test_cancel_denial_restores_confirmed(ready,next_thursday):
    e=service.create_event(42,'mafia','Мафия тест',next_thursday,10,'classic')
    rid=service.join_event(100,e['id'])
    service.decide(42,'event',rid,True)
    service.request_cancel(100,'event',rid)
    assert service.decide(42,'event',rid,False)['status']=='confirmed'


def test_nickname_snapshot(ready,next_thursday):
    e=service.create_event(42,'mafia','Мафия тест',next_thursday,10,'classic')
    r=service.join_event(100,e['id'])
    service.decide(42,'event',r,True)
    service.set_profile(100,'Гость 100','+79990000100','Новый ник')
    assert service.event_members(e['id'])==[{'nickname_snapshot':'Ник100'}]


def test_billiard_overlap(ready):
    now=(datetime.now(ZoneInfo('Europe/Moscow'))+timedelta(days=2)).replace(minute=0,second=0,microsecond=0)
    r=service.billiard_book(100,now.isoformat(),2,2)
    with pytest.raises(service.BusinessError,match='занят'):
        service.billiard_book(101,(now+timedelta(hours=1)).isoformat(),1,3)
    service.decide(42,'billiard',r,False)
    assert service.billiard_book(101,(now+timedelta(hours=1)).isoformat(),1,3)>r


def test_billiard_max_7_days_and_hours(ready):
    now=datetime.now(ZoneInfo('Europe/Moscow'))+timedelta(days=8)
    with pytest.raises(service.BusinessError,match='7 дней'):
        service.billiard_book(100,now.isoformat(),1,2)
    with pytest.raises(service.BusinessError,match='от 1 до 4'):
        service.billiard_book(100,(datetime.now(ZoneInfo('Europe/Moscow'))+timedelta(days=2)).isoformat(),5,2)


def test_role_rules(fresh):
    with pytest.raises(service.BusinessError):service.set_role(100,101,'admin')
    service.set_role(42,100,'senior')
    with pytest.raises(service.BusinessError):service.set_role(100,101,'senior')
    service.set_role(100,101,'admin')
    assert service.get_user(101)['role']=='admin'
    with pytest.raises(service.BusinessError):service.set_role(100,42,'guest')


def test_owner_transfer_revokes_old_owner(fresh,monkeypatch):
    from dataclasses import replace
    from app import service as s
    assert s.get_user(42)['role']=='owner'
    monkeypatch.setattr(s,'settings',replace(fresh,owner_telegram_id=101))
    with pytest.raises(s.BusinessError,match='прав'):
        s.check_role(42)
    s.ensure_user(101,'Клиент')
    assert s.get_user(42)['role']=='guest'
    assert s.get_user(101)['role']=='owner'


def test_atomic_last_slot_under_concurrent_requests(ready,next_thursday):
    from concurrent.futures import ThreadPoolExecutor
    from app import service as s
    e=s.create_event(42,'mafia','Мафия конкурентный тест',next_thursday,10,'classic')
    for i in range(200,209):
        s.ensure_user(i,'Игрок')
        s.set_profile(i,f'Игрок {i}','+79990000'+str(i),'Ник'+str(i))
        s.join_event(i,e['id'])
    results=[]
    def attempt(i):
        try:return ('ok',s.join_event(i,e['id']))
        except s.BusinessError as ex:return ('err',ex.status)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(attempt,[100,101]))
    assert sorted(x[0] for x in results)==['err','ok']
    assert s.list_events()[0]['occupied']==10


def test_billiard_cancel_pending_does_not_free_until_approved(ready):
    from app import service as s
    now=(datetime.now(ZoneInfo('Europe/Moscow'))+timedelta(days=1)).replace(minute=0,second=0,microsecond=0)
    r=s.billiard_book(100,now.isoformat(),2,2)
    s.request_cancel(100,'billiard',r)
    with pytest.raises(s.BusinessError,match='занят'):
        s.billiard_book(101,now.isoformat(),1,1)
    s.decide(42,'billiard',r,True)
    assert s.billiard_book(101,now.isoformat(),1,1)>r
