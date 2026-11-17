"""New natural language scenarios: QA corpus, role boundaries, context, original brand.

These local tests do not simulate a real Telegram BotFather token or customer VPS.
"""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import json

import httpx
import pytest
from app import assistant, api, service
from app.config import ROOT


@pytest.fixture
def showcase(ready, monkeypatch):
    config=replace(ready,showcase_mode=True)
    monkeypatch.setattr(assistant,'settings',config)
    monkeypatch.setattr(service,'settings',config)
    monkeypatch.setattr(api,'settings',config)
    service.ensure_showcase_schedule()
    assistant.knowledge.cache_clear()
    return config


def test_brand_png_is_identical_to_original_uploaded_image():
    path=ROOT/'web'/'tourist_logo_original.png'
    assert sha256(path.read_bytes()).hexdigest()=='dc07705cf3f9dd5f94de9b1479f875136addab4fe2d3dcbb847cdb8fa07f9930'
    html=(ROOT/'web/index.html').read_text()
    assert html.count('tourist_logo_original.png')>=2
    assert 'ТУРИСТ' in html


def test_knowledge_file_has_100_topics_and_explicit_provenance():
    entries=assistant.knowledge()
    assert len(entries)>=100
    assert sum(len(x['aliases']) for x in entries)>=500
    assert len({x['id'] for x in entries})==len(entries)
    assert all(x['source_type'] in ('demo','verified_public','dynamic') for x in entries)
    assert 'Кукунина' in next(x['answer'] for x in entries if x['id']=='location')


def test_84_conversational_questions_do_not_fall_through(showcase):
    corpus=json.loads((ROOT/'data'/'dialogue_qa_84.json').read_text())['questions']
    assert len(corpus)==84
    for question in corpus:
        result=assistant.answer(question)
        assert result and result.strip(),question
        assert 'Токен' not in result


def test_semantics_source_facts_and_live_schedule(showcase):
    qs=[('Добрый вечер, подскажите свой адрес','Кукунина'),
        ('Хочу попробовать сыграть в мафию','Афиша'),
        ('Когда следующая мафия?','Ближайшие встречи'),
        ('Сколько стоит час бильярда?','900 ₽'),
        ('Есть у вас караоке?','караоке'),
        ('Можно прийти просто пообщаться?','без участия'),
        ('Как отменить запись?','отмен'),
        ('Скиньте геолокацию','yandex.ru'),
        ('Как написать сотруднику?','администратора')]
    for question,needle in qs:
        result=assistant.answer(question)
        assert result is not None and needle.lower() in result.lower(),(question,result)


def test_persistent_context_and_switches(showcase):
    uid=100
    assert 'мафия' in assistant.answer('Что у вас с мафией?',uid).lower()
    assert 'Ближайшие встречи' in assistant.answer('А ближайшая когда?',uid)
    assert '600 ₽' in assistant.answer('А стоимость?',uid)
    assert '900 ₽' in assistant.answer('Сколько стоит бильярд?',uid)
    assert '2 700 ₽' in assistant.answer('А на три часа сколько?',uid)
    assert 'Кукунина' in assistant.answer('А где вы находитесь?',uid)
    assert 'парковк' in assistant.answer('А парковка рядом?',uid).lower()


def test_dont_fabricate_and_clarify_without_context(showcase):
    assert assistant.answer('Как зовут вашего кота?') is None
    assert 'Уточните' in assistant.answer('А почём это будет?')
    assert 'Уточните' in assistant.answer('А завтра тоже можно?')
    assert 'не подтвержд' in assistant.answer('Вы дог френдли?').lower() or 'заранее' in assistant.answer('Вы дог френдли?')


def test_non_showcase_hides_demo_pricing(ready, monkeypatch):
    monkeypatch.setattr(assistant,'settings',ready)
    assert 'у администратора' in assistant.answer('Сколько стоит билет на покер?')


@pytest.mark.asyncio
async def test_webapp_assistant_same_engine_and_private_context(showcase):
    transport=httpx.ASGITransport(app=api.app)
    async with httpx.AsyncClient(transport=transport,base_url='http://testserver') as client:
        headers={'X-Demo-User-ID':'100'}
        one=await client.post('/api/assistant/reply',headers=headers,json={'text':'Какой у вас адрес?'})
        assert one.status_code==200 and one.json()['matched']
        assert 'Кукунина' in one.json()['answer']
        other=await client.post('/api/assistant/reply',headers=headers,json={'text':'Как зовут кота?'})
        assert other.status_code==200 and not other.json()['matched']
        assert 'администратору' in other.json()['answer']
        empty=await client.post('/api/assistant/reply',headers=headers,json={'text':''})
        assert empty.status_code==422


def test_negation_and_cancel_dont_become_positive_bookings(showcase):
    negative=assistant.answer('Я НЕ хочу записываться на покер')
    assert negative is not None and 'не буду' in negative
    cancel=assistant.answer('Хочу отменить мафию')
    assert cancel is not None and 'отмен' in cancel.lower() and 'Мои заявки' in cancel


def test_irrelevant_product_pricing_is_not_a_club_ticket(showcase):
    reply=assistant.answer('Сколько стоит привезти холодильник?')
    assert reply is None or ('Уточните' in reply and '600 ₽' not in reply)


def test_compound_location_and_hours_are_both_answered(showcase):
    result=assistant.answer('Какой у вас адрес и до скольких вы открыты?')
    assert result is not None and 'Кукунина' in result and '17:00' in result


def test_context_is_isolated_by_telegram_id(showcase):
    assert '600 ₽' in assistant.answer('Сколько стоит мафия?',100)
    service.ensure_user(101,'Другой гость')
    separate=assistant.answer('А почём это будет?',101)
    assert '600 ₽' not in separate and 'Уточните' in separate


def test_84_intent_routes_match_expected_topics(showcase):
    data=json.loads((ROOT/'data'/'dialogue_qa_84.json').read_text())
    wrong=[]
    for question,want in zip(data['questions'],data['expected_ids']):
        if want=='clarification':continue
        cleaned=assistant.INTRO.sub('',question).strip(' !,.')
        got=assistant._resolve(cleaned,{})
        if not got or got['id']!=want:
            wrong.append((question,want,got and got['id']))
    assert not wrong,wrong
