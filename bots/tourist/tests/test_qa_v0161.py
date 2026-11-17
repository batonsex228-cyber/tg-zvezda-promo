"""Regression cases found in the second review of v0.16.

The fictional commercial information is intentionally marked as demo.
"""
from dataclasses import replace
import json
from hashlib import sha256
from app import assistant, service
from app.config import ROOT


def test_colloquial_guest_questions(ready, monkeypatch):
    cfg=replace(ready,showcase_mode=True)
    monkeypatch.setattr(assistant,'settings',cfg)
    monkeypatch.setattr(service,'settings',cfg)
    pairs=[
        ('как к вам добраться?', 'yandex.ru/maps'),
        ('скиньте меню', 'В меню'),
        ('в субботу открыто?', '02:00'),
        ('по какому телефону звонить?', 'Вызвать администратора'),
        ('я хочу отменить заявку', 'Запросить отмену'),
        ('я не хочу отменять заявку', 'не меняю'),
        ('не хочу играть в мафию, а бильярд у вас есть?', 'бильярд'),
        ('адрес и режим работы', 'Кукунина'),
        ('можно забронировать столик на четверых?', 'обычного столика'),
        ('какие у вас акции?', 'скидка 10%'),
        ('можно с детьми?', 'детьми'),
        ('как сделать бронь?', 'Афишу'),
        ('что значит мафия?', 'командная игра'),
        ('есть что-нибудь вкусное поесть?', 'бургеры'),
    ]
    for question, phrase in pairs:
        reply=assistant.answer(question)
        assert reply is not None and phrase.lower() in reply.lower(), (question,reply)
    compound=assistant.answer('адрес и режим работы')
    assert 'Кукунина' in compound and '17:00' in compound


def test_logo_unaltered_and_ui_hydration_guard():
    logo=ROOT/'web/tourist_logo_original.png'
    assert sha256(logo.read_bytes()).hexdigest()=='dc07705cf3f9dd5f94de9b1479f875136addab4fe2d3dcbb847cdb8fa07f9930'
    src=(ROOT/'web/app.js').read_text()
    assert 'editAtRequest===state.profileEditSerial' in src
    assert "$('#profile-form').addEventListener('input'" in src
    html=(ROOT/'web/index.html').read_text()
    assert 'ОБРАЩЕНИЯ' in html and 'СПРАВОЧНАЯ БАРА' not in html


def test_old_corpus_still_has_provenance(ready,monkeypatch):
    cfg=replace(ready,showcase_mode=True)
    monkeypatch.setattr(assistant,'settings',cfg)
    monkeypatch.setattr(service,'settings',cfg)
    corpus=json.loads((ROOT/'data/dialogue_qa_84.json').read_text())
    assert all(assistant.answer(q) for q in corpus['questions'])
    entries=assistant.knowledge()
    assert all(x['source_type'] in ('demo','verified_public','dynamic') for x in entries)
