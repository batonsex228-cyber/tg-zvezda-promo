"""FAQ 150 acceptance: curated variants, typos, context and no accidental actions.

All FAQ content, including prices and the event programme, is demonstration-only.
"""
from dataclasses import replace
import json
import re

import pytest
from app import assistant, service
from app.config import ROOT

@pytest.fixture
def faq_setup(ready, monkeypatch):
    cfg=replace(ready,showcase_mode=True)
    monkeypatch.setattr(assistant,'settings',cfg)
    monkeypatch.setattr(service,'settings',cfg)
    assistant.knowledge.cache_clear()
    service.ensure_showcase_schedule()
    return cfg

def test_exactly_150_unique_faq_and_provenance(faq_setup):
    kb=json.loads((ROOT/'data'/'showcase_knowledge.json').read_text(encoding='utf-8'))
    entries=kb['entries']
    assert len(entries)==150
    assert len({x['id'] for x in entries})==150
    assert sum(len(x['aliases']) for x in entries)>=900
    for item in entries:
        assert set(('id','entity','intent','question','answer','aliases','source_type')).issubset(item)
        assert isinstance(item['answer'],str) and (len(item['answer'])>40 or item['answer'].startswith('dynamic:'))
        assert len(item['aliases'])>=3
        assert item['question'] in item['aliases']
        assert item['source_type'] in ('demo','verified_public','dynamic')

def test_all_150_questions_choose_their_topic(faq_setup):
    wrong=[]
    for item in assistant.knowledge():
        got=assistant._resolve(item['question'],{})
        if not got or got['id']!=item['id']:
            wrong.append((item['id'],got and got['id']))
    assert not wrong,wrong

def test_all_900_plus_curated_paraphrases_route_to_right_answer(faq_setup):
    wrong=[]; count=0
    for item in assistant.knowledge():
        for alias in item['aliases']:
            count+=1
            got=assistant._resolve(alias,{})
            if not got or got['id']!=item['id']:
                wrong.append((item['id'],alias,got and got['id']))
    assert count>=900
    assert not wrong,wrong[:30]

@pytest.mark.parametrize('question,needle',[
    ('Добрый вечер дайте адресс','Кукунина'),
    ('а гдэ вы вообще','Кукунина'),
    ('скока стоит билярд на час','900 ₽'),
    ('Скок за мафку','600 ₽'),
    ('как забукать бильярд','Бильярд'),
    ('чо по еде?','меню'),
    ('вифи работает?','Wi'),
    ('уайфай есть','Wi'),
    ('караоки есть?','караоке'),
    ('покир новичкам норм?','нович'),
    ('в субботу до скока','17:00'),
    ('хочу посмотреть мафию, не играть','зрител'),
    ('очень хочу попеть но не умею','не обязательно'),
    ('можно футбол глянуть','спортив'),
    ('пиво на кранах есть','ассортимент'),
    ('Как оплачивать, наличкой или картой','карты'),
    ('забукать столик на субботу','администратор'),
    ('Как снять бронь','Мои заявки'),
    ('у вас сколько микрофонов','караоке'),
    ('песня отсутствует в каталоге, что делать','песн'),
])
def test_natural_language_typos_and_slang(faq_setup,question,needle):
    answer=assistant.answer(question)
    assert answer and needle.lower() in answer.lower(),(question,answer)

def test_no_show_hypothetical_and_cancel_are_distinct(faq_setup):
    hypothetical=assistant.answer('Что будет, если я не приду по брони?')
    assert hypothetical and 'штраф' in hypothetical.lower(),hypothetical
    direct=assistant.answer('Я не приду на игру, хочу отменить')
    assert direct and 'отмен' in direct.lower(),direct

def test_sensitive_negation_and_unrelated_topic_do_not_lead_to_false_booking(faq_setup):
    assert 'не буду' in assistant.answer('Не хочу записываться на мафию')
    assert 'не меняю' in assistant.answer('Не хочу отменять заявку')
    assert assistant.answer('Какой породы у вас кот?') is None
    irrelev=assistant.answer('Сколько стоит ремонт моего трактора?')
    assert irrelev is None or 'Уточните' in irrelev

def test_context_price_followup_changes_topic_and_is_private(faq_setup):
    assert 'мафия' in assistant.answer('Расскажи про мафию',100).lower()
    assert '600 ₽' in assistant.answer('А скока?',100)
    assert '900 ₽' in assistant.answer('Сколько стоит бильярд?',100)
    assert '900 ₽' in assistant.answer('А цена?',100)
    assert 'Уточните' in assistant.answer('А почём это?',101)

def test_in_production_demo_prices_are_hidden(ready,monkeypatch):
    cfg=replace(ready,showcase_mode=False)
    monkeypatch.setattr(assistant,'settings',cfg)
    assert 'у администратора' in assistant.answer('Сколько стоит покер?')
