"""Check the 20 conversation research cases without contacting Telegram or Google."""
from datetime import date
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from app.semantic_knowledge import SemanticKnowledge
from app.conversation import classify_social_only
from app.intake import is_urgent_safety
from app.booking import is_booking_request

s=SemanticKnowledge(now=date(2026,11,17))
dialogues=json.loads((Path(__file__).resolve().parent.parent/'tests/context_20_dialogues.json').read_text())['dialogues']
assert len(dialogues)==20
observed={}
for d in dialogues:
    ctx={}; last=None
    for turn in d['turns']:
        if turn['role']!='родитель':continue
        msg=turn['text']; a=s.analyze(msg,ctx)
        last=(msg,[t.topic_id for t in a.topics],a.clarification,classify_social_only(msg))
        if a.topics:ctx={'topic':'semantic:'+a.topics[0].topic_id}
    observed[d['id']]=last

checks={
'D01':lambda x: 'shift_1' in x[1],
'D02':lambda x: 'gazebo_booking' in x[1],
'D03':lambda x: x[3]=='thanks',
'D04':lambda x: 'shoes' in x[1] and x[3] is None,
'D05':lambda x: 'form_confirmation' in x[1],
'D06':lambda x: 'form_consent' in x[1],
'D07':lambda x: {'shift_4','free_places'} <= set(x[1]),
'D08':lambda x: {'phone_policy','food_freq'} <= set(x[1]),
'D09':lambda x: 'payment_refund' in x[1],
'D10':lambda x: 'contact_child' in x[1],
'D11':lambda x: 'camp_address' in x[1],
'D12':lambda x: 'medicines' in x[1],
'D13':lambda x: is_urgent_safety(x[0]),
'D14':lambda x: 'shift_2' in x[1],
'D15':lambda x: bool(x[2] and 'ошибка' in x[2]),
'D16':lambda x: 'shifts_all' in x[1] and not is_booking_request(x[0]),
'D17':lambda x: {'shift_1','shift_4'} <= set(x[1]),
'D18':lambda x: 'weekend' in x[1] and '1 450 ₽ с человека' in (s.formulate(s.analyze(x[0],{'topic':'semantic:weekend'})) or ('',))[0],
'D19':lambda x: 'age' in x[1],
'D20':lambda x: 'allowed_food' in x[1],
}
for id_,check in checks.items():
    assert check(observed[id_]),(id_,observed[id_])
print('CONTEXT DIALOGUE REGRESSION: PASS - 20/20')
