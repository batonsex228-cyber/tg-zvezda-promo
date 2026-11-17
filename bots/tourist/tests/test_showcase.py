"""v0.15 showcase regression: fake calendar, guest→staff relay, safety and UX."""
from dataclasses import replace
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from app import api, service, database, config, assistant
from tests.test_stage7 import simulated_bot


def test_demo_schedule_is_opt_in_idempotent_and_clearly_marked(fresh, monkeypatch):
    cfg=replace(fresh,showcase_mode=True)
    for module in (database,service,api,config):
        monkeypatch.setattr(module,'settings',cfg)
    assert service.ensure_showcase_schedule()==3
    assert service.ensure_showcase_schedule()==0
    events=service.list_events()
    assert len(events)==3
    assert all(not x['title'].startswith('ДЕМО · ') for x in events)
    assert all(datetime.fromisoformat(x['starts_at'])>datetime.now(timezone.utc) for x in events)
    assert any(x['kind']=='poker' for x in events)
    assert any(x['kind']=='mafia' for x in events)
    cfg2=replace(cfg,showcase_mode=False)
    monkeypatch.setattr(service,'settings',cfg2)
    assert service.list_events()==[]


def test_demo_never_auto_inserts_alongside_real_club_event(ready,next_thursday,monkeypatch):
    from app import config
    ev=service.create_event(42,'mafia','Настоящая игра',next_thursday,10,'classic')
    cfg=replace(ready,showcase_mode=True)
    monkeypatch.setattr(service,'settings',cfg)
    assert service.ensure_showcase_schedule()==0
    assert [x['id'] for x in service.list_events()]==[ev['id']]


def test_support_ticket_notify_and_staff_answer(ready):
    ticket=service.create_support_ticket(100,'Можно ли прийти с друзьями?')
    assert ticket>0
    rows=service.list_support_tickets(42)
    assert rows[0]['id']==ticket and 'друзьями' in rows[0]['question']
    with pytest.raises(service.BusinessError):service.list_support_tickets(100)
    from app.database import session
    with session() as c:
        note=c.execute("SELECT message FROM notification_outbox WHERE telegram_id=42 ORDER BY id DESC LIMIT 1").fetchone()
        assert f'№{ticket}' in note[0]
    result=service.answer_support_ticket(42,ticket,'Да, с друзьями можно!')
    assert result['status']=='answered'
    own=service.my_support_tickets(100)
    assert own[0]['answer']=='Да, с друзьями можно!'
    with session() as c:
        notify=c.execute("SELECT message FROM notification_outbox WHERE telegram_id=100 ORDER BY id DESC LIMIT 1").fetchone()
        assert 'Да, с друзьями можно!' in notify[0]
    with pytest.raises(service.BusinessError):service.answer_support_ticket(101,ticket,'Нельзя')


def test_ticket_rate_limit_and_validation(ready):
    for text in ['', 'x', 'a'*1501]:
        with pytest.raises(service.BusinessError): service.create_support_ticket(100,text)
    for i in range(5):service.create_support_ticket(100,f'Вопрос про клуб номер {i}')
    with pytest.raises(service.BusinessError) as exc:service.create_support_ticket(100,'Шестой вопрос')
    assert exc.value.status==429
    assert len(service.my_support_tickets(100))==5


def test_support_api_authorized_guest_and_admin(ready):
    with TestClient(api.app) as c:
        guest={'X-Demo-User-ID':'100'};owner={'X-Demo-User-ID':'42'}
        response=c.post('/api/support/tickets',headers=guest,json={'text':'Хочу задать вопрос администратору'})
        assert response.status_code==200
        ticket=response.json()['id']
        assert c.get('/api/support/mine',headers=guest).json()[0]['status']=='open'
        assert c.get('/api/admin/support',headers=guest).status_code==403
        assert c.post(f'/api/admin/support/{ticket}/reply',headers=guest,json={'text':'Привет'}).status_code==403
        assert c.get('/api/admin/support',headers=owner).json()[0]['id']==ticket
        assert c.post(f'/api/admin/support/{ticket}/reply',headers=owner,json={'text':'Добрый день, помогу!'}).status_code==200
        assert c.get('/api/support/mine',headers=guest).json()[0]['answer']=='Добрый день, помогу!'
        assert c.get('/api/admin/support').status_code==403


def test_natural_language_answers_live_data_and_fallback(ready,next_thursday):
    assert 'Профиль' in assistant.answer('А как мне сделать игровой ник?') or 'профиль' in assistant.answer('А как мне сделать игровой ник?')
    assert 'Бильярд' in assistant.answer('Можно ли забронировать бильярд?')
    service.create_event(42,'mafia','Вечер с друзьями',next_thursday,10,'classic')
    a=assistant.answer('А когда у вас будет мафия?')
    assert 'Вечер с друзьями' in a
    assert 'из них нет' not in a
    assert assistant.answer('Какая порода у вашего кота?') is None
    assert 'у администратора' in assistant.answer('Сколько стоит билет на покер?')


def test_ui_includes_support_and_showcase_badge():
    from app.config import ROOT
    h=(ROOT/'web/index.html').read_text()
    js=(ROOT/'web/app.js').read_text()
    css=(ROOT/'web/showcase.css').read_text()
    assert 'screen-support' in h and 'admin-support' in h
    assert 'showcase-banner' not in h
    assert '/api/support/tickets' in js and '/api/admin/support/' in js
    assert 'game-art' in css and '.hero-orbit' in css
    assert 'Вызвать <em>администратора' in h

@pytest.mark.asyncio
async def test_ai_opt_in_disabled_by_default(fresh,monkeypatch):
    from app import ai_helper
    monkeypatch.setattr(ai_helper,'settings',replace(fresh,ai_mode='off',ollama_model='qwen3.5:4b'))
    assert await ai_helper.maybe_answer('Расскажи про настольные игры') is None


@pytest.mark.asyncio
async def test_ai_loopback_only_and_bounded_output(fresh,monkeypatch):
    from app import ai_helper
    from types import SimpleNamespace
    monkeypatch.setattr(ai_helper,'settings',replace(fresh,ai_mode='ollama',ollama_model='test',ollama_url='http://remote.example:11434'))
    assert await ai_helper.maybe_answer('Помоги составить план') is None
    monkeypatch.setattr(ai_helper,'settings',replace(fresh,ai_mode='ollama',ollama_model='test',ollama_url='http://127.0.0.1:11434'))
    captured=[]
    class Client:
        def __init__(self,timeout): self.timeout=timeout
        async def __aenter__(self):return self
        async def __aexit__(self,*_):pass
        async def post(self,url,json):
            captured.append((url,json))
            return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'message':{'content':'Вот короткий полезный ответ.'}})
    monkeypatch.setattr(ai_helper.httpx,'AsyncClient',Client)
    ans=await ai_helper.maybe_answer('Как организовать вечер настольных игр?')
    assert ans=='Вот короткий полезный ответ.'
    assert captured[0][0]=='http://127.0.0.1:11434/api/chat'
    assert captured[0][1]['model']=='test'


def test_bot_support_callback_fsm_and_staff_reply(ready,simulated_bot,monkeypatch):
    import asyncio
    from tests.test_stage7 import _FakeMessage,_FakeCallback,_FakeState
    bot,_=simulated_bot
    monkeypatch.setattr(bot,'settings',ready)
    state=_FakeState()
    asyncio.run(bot.callback(_FakeCallback(100,'support'),state))
    assert state.value==bot.SupportQuestion.text
    msg=_FakeMessage(100,'Добрый день, можно прийти с друзьями?')
    asyncio.run(bot.support_question(msg,state))
    assert state.value is None
    assert service.my_support_tickets(100)[0]['status']=='open'
    admin_state=_FakeState()
    asyncio.run(bot.callback(_FakeCallback(42,'support_reply:1'),admin_state))
    assert admin_state.value==bot.SupportReply.text
    answer=_FakeMessage(42,'Конечно, приходите!')
    asyncio.run(bot.support_reply_text(answer,admin_state))
    assert service.my_support_tickets(100)[0]['status']=='answered'
    assert any('Ответ сохранён' in text for text,_ in answer.sent)


def test_bot_free_text_faq_and_unknown_forward(ready,simulated_bot,monkeypatch):
    import asyncio
    from tests.test_stage7 import _FakeMessage
    bot,_=simulated_bot
    monkeypatch.setattr(bot,'settings',ready)
    hi=_FakeMessage(100,'Расскажите про бильярд')
    asyncio.run(bot.free_text(hi))
    assert any('бильярд' in text.lower() for text,_ in hi.sent)
    assert service.my_support_tickets(100)==[]
    question=_FakeMessage(100,'Какой дизайн потолка вы планируете?')
    asyncio.run(bot.free_text(question))
    assert any('передал Ваш вопрос' in text for text,_ in question.sent)
    assert len(service.my_support_tickets(100))==1


def test_support_retry_key_never_duplicates_staff_notification(ready):
    from app.database import session
    k='ticket_2026_0001'
    first=service.create_support_ticket(100,'Можно в субботу прийти?',k)
    second=service.create_support_ticket(100,'Можно в субботу прийти?',k)
    assert first==second
    with session() as c:
        assert c.execute('SELECT COUNT(*) FROM support_tickets WHERE telegram_id=100').fetchone()[0]==1
        assert c.execute('SELECT COUNT(*) FROM notification_outbox WHERE telegram_id=42').fetchone()[0]==1
    with pytest.raises(service.BusinessError) as ex:
        service.create_support_ticket(100,'Другой вопрос по тому же ключу',k)
    assert ex.value.status==409
