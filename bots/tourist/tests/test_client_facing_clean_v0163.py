"""Guest output and older fixture migration have no internal labels."""
from dataclasses import replace
from pathlib import Path
import json, re
from app import assistant, service, database
from app.config import ROOT

LEAK = re.compile(r"демо|демонстрац|портфолио|тестов(?:ая|ый|ое|ые)|не действующий прайс|пример цены|\bpreview\b", re.I)

def test_all_150_answers_read_naturally(fresh,monkeypatch):
    cfg=replace(fresh,showcase_mode=True)
    monkeypatch.setattr(assistant,'settings',cfg)
    monkeypatch.setattr(service,'settings',cfg)
    assistant.knowledge.cache_clear()
    assert service.ensure_showcase_schedule()==3
    knowledge=assistant.knowledge()
    assert len(knowledge)==150
    for item in knowledge:
        actual=assistant._reply_for(item,None)
        assert actual and not LEAK.search(actual),(item['id'],actual)
    assert not LEAK.search(assistant.answer('А за два часа бильярда сколько?',None) or '')
    assert not LEAK.search(assistant.answer('Когда мафия?',None) or '')

def test_website_has_no_visitor_facing_internal_labels():
    page=(ROOT/'web'/'index.html').read_text(encoding='utf8')
    assert not LEAK.search(page)
    assert 'showcase-banner' not in page
    assert 'tourist_logo_original.png' in page
    script=(ROOT/'web'/'app.js').read_text(encoding='utf8')
    assert "?' · ДЕМО'" not in script
    assert "?'PREVIEW'" not in script
    assert not LEAK.search((ROOT/'FAQ_150_ВОПРОСОВ_И_ОТВЕТОВ.md').read_text(encoding='utf8'))

def test_existing_fixture_titles_updated_without_losing_booking(fresh,monkeypatch):
    cfg=replace(fresh,showcase_mode=True)
    monkeypatch.setattr(service,'settings',cfg)
    assert service.ensure_showcase_schedule()==3
    with database.session(write=True) as c:
        row=c.execute("SELECT id,title FROM events WHERE is_demo=1 LIMIT 1").fetchone()
        event_id=row['id']
        c.execute('UPDATE events SET title=? WHERE id=?', ('ДЕМО · Мафия · Классический вечер',event_id))
        before=c.execute('SELECT COUNT(*) FROM events').fetchone()[0]
    assert service.ensure_showcase_schedule()==0
    with database.session() as c:
        row=c.execute('SELECT title FROM events WHERE id=?',(event_id,)).fetchone()
        assert row['title']=='Мафия · Классический вечер'
        assert c.execute('SELECT COUNT(*) FROM events').fetchone()[0]==before
