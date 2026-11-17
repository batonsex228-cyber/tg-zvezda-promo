"""150 independent research utterances + context/safety checks, no network calls."""
import json
import sys
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))

from app.semantic_knowledge import SemanticKnowledge
from app.conversation import classify_social_only
from app.booking import is_booking_request

ROOT=Path(__file__).resolve().parent.parent
sem=SemanticKnowledge(now=date(2026,11,17))
rows=[json.loads(line) for line in (ROOT/'tests/semantic_150_messages.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
assert len(rows)==150
cards=sem.cards
assert len(cards)==50

for row in rows:
    text=row['user_text']; expected=row['topic_id']; analysis=sem.analyze(text)
    subjects=[p.topic_id for p in analysis.topics]
    social=classify_social_only(text)
    if expected=='social':
        assert social in {'thanks','farewell','acknowledgement'},(row['id'],text,social)
    elif expected=='context_followup':
        assert analysis.clarification or subjects,(row['id'],text)
    elif expected=='multi_intent':
        assert len(subjects)>=2,(row['id'],subjects)
    else:
        assert expected in subjects,(row['id'],text,expected,subjects)
    formatted=sem.formulate(analysis)
    if row['expected_behavior'] in {'live_check','personal_to_human','clarify_or_handoff','needs_confirmation'}:
        # Never claim live availability, a personalized medical approval, or special discount.
        if formatted:
            body=formatted[0].lower()
            assert not any(x in body for x in ['места есть, бронируем','обязательно дадут скидку', 'аллергия не помеха']), row['id']
    if row['expected_behavior'] in {'start_form','form_consent','form_control'}:
        assert formatted is None, (row['id'], formatted)

# Context must be based on a previous supported topic, not a guessed referent.
assert 'shift_3' in [x.topic_id for x in sem.analyze('а там сколько стоит?',{'topic':'semantic:shift_3'}).topics]
assert 'gazebo_booking' in [x.topic_id for x in sem.analyze('а на субботу свободно?',{'topic':'semantic:gazebo_price'}).topics]
assert 'weekend' in [x.topic_id for x in sem.analyze('а на 3 дня можно?',{'topic':'semantic:weekend'}).topics]
assert 'payment_refund' in [x.topic_id for x in sem.analyze('а если нет, можно частями?',{'topic':'semantic:payment_refund'}).topics]
assert 'shift_1' in [x.topic_id for x in sem.analyze('а первая тогда сколько?',{'topic':'semantic:shift_3'}).topics]
assert sem.analyze('А на эту дату свободно?').clarification

# Test multi-topic output, differentiation and negation.
for q,want in [
    ('Скок стоит третья смена и когда выезд?',{'shift_3','arrival'}),
    ('А телефон забирают и как часто кормят?',{'phone_policy','food_freq'}),
    ('Хотим на вторую, но ещё какие документы и есть ли места?',{'shift_2','arrival_docs','free_places'}),
    ('Что дешевле: 1 смена или 4?',{'shift_1','shift_4'}),
]:
    got={x.topic_id for x in sem.analyze(q).topics}
    assert want <= got,(q,got,want)
assert not is_booking_request('Мне НЕ нужна аренда беседки, хочу узнать смены')
assert sem.analyze('Мне НЕ нужна аренда беседки, хочу узнать смены').topics[0].topic_id=='shifts_all'
assert sem.analyze('Мой ребёнок где живет в лагере?').topics[0].topic_id=='contact_child'
assert sem.analyze('На сайте цитрусы нельзя, в старой памятке апельсины можно').topics[0].topic_id=='allowed_food'
assert sem.analyze('Что если у ребенка диабет, подойдёт ли меню?').topics[0].topic_id=='food_allergy'
assert sem.analyze('Спасибо, сколько стоит первая смена?').topics[0].topic_id=='shift_1'
assert classify_social_only('Спасибо, а какие справки нужны?') is None
assert classify_social_only('спасибкиии, оч помогли!!')=='thanks'

# Empty or vague requests should not fabricate an answer.
for q in ['а что насчет этого?', 'ну и как?', 'помогите пожалуйста']:
    decision=sem.analyze(q)
    assert not decision.topics or not sem.formulate(decision),q
# Expired prices are not returned as current verified prices without refresh.
stale=SemanticKnowledge(now=date(2027,1,3))
f=stale.formulate(stale.analyze('сколько стоит путёвка летом 2027'))
assert f and '40 000' not in f[0]
print('SEMANTIC KNOWLEDGE REGRESSION: PASS - 150/150 research utterances + safety/context assertions')
