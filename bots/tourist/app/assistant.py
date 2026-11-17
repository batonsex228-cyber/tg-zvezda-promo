"""Tourist Dialogue v0.16: source-labelled FAQ, local conversation context and live events.

No cloud model is required. Unknown topics return None for staff escalation.
This module never creates bookings, changes roles or handles payments.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from functools import lru_cache
import json
from pathlib import Path
import re

from app import service
from app.config import ROOT, settings
from app.database import session

CONTEXT_TTL_MINUTES = 25
STOP = {'а','и','или','но','в','во','на','у','вы','вас','нам','мне','мой','моя','можно','ли','что','как','где','какой','какая','какие','пожалуйста','подскажите','подскажи','скажите','скажешь','хотел','бы','могу','есть','это','этот','из','да','тут','там','ну','же','я','мы','вы','к','по','с','со','для','не','то','еще','ещё','вообще','здравствуйте','добрый','день','вечер','утро','привет','расскажите','расскажи','плиз','спасибо','своими','словами'}
ALIASES = {'забронить':'забронировать','броньку':'бронь','записатся':'записаться', 'кудавас':'адрес','вайфай':'wifi','вай фай':'wifi','докскольки':'до скольки'}
ENTITY_STEMS = {
    'mafia':('мафи', 'мафиозн'),
    'poker':('покер','блайнд','стеки','стек','реба'),
    'billiard':('бильяр','кия','кии','кием','кий','шар','пул'),
    'karaoke':('караок','песн','петь','спеть','попеть','треки','микрофон'),
}
INTENT_STEMS = {
    'address':('адрес','находит','локац','геолокац','геоточк','где вы','где бар','куда к вам','где турист'),
    'route':('добрат','доехат','доехать','проехат','проехать','маршрут','дойти','остановк'),
    'map':('карт','навигат','геоточк','геолокац'),
    'hours':('час работ','работает','работаете','открыв','закрыв','до скольк','до котор','режим','график'),
    'price':('цен','стоим','стоит','почем','почём','прайс','сколько за','скольк за','оплат','рубл','билет'),
    'availability':('свобод','занят','остал','налич','есть мест','места есть'),
    'schedule':('расписан','афиш','ближайш','когда','во скольк','какого числа','по дням','по выходным'),
    'booking':('запис','заброни','брон','резерв','попасть на игру','хочу на игру','хочу играть'),
    'cancel':('отмен','передум','не приду','не смогу','отказ'),
    'reschedule':('перенес','перенест','перенести','передвин','поменят время','другую дату'),
    'duration':('длится','длительн','скольк по времен','сколько часов','на сколько часов','сколько идет','сколько идёт'),
    'beginner':('нович','первый раз','не уме','не играл','без опыт','научит'),
    'rules':('правил','регламент','как играть','как устроен'),
    'support':('администрат','оператор','менеджер','сотрудник','сотруднику','поговорить с человеком','позови сотрудника'),
    'players':('скольк человек','скольк игроков','нас трое','нас двое','вдвоём','вдвоем'),
    'profile':('регистрац','профил','ник','номер телефон'),
    'myrequests':('мои заявк','мою брон','я записан','статус моей','где моя заявк'),
    'about':('что такое','расскаж','что у вас','какие развлеч'),
}
INTRO = re.compile(r'^\s*(привет|приветик|здра[вc]ствуйте|добрый (день|вечер|утро)|здравствуй|салют|хай)[ !,.]*',re.I)
THANKS = re.compile(r'^(спасибо( вам)?|благодарю|спс|отлично спасибо|все понятно|всё понятно)[ !,.]*$',re.I)
ENTITY_MATCH_RE = {key:tuple(x for x in stems) for key,stems in ENTITY_STEMS.items()}


# Carefully curated spoken-language spellings, abbreviations and common typos.
# Corrections are token-boundary based; we never rewrite negations ("не", "нет")
# or arbitrary words, which could change the visitor's intention.
SPOKEN_WORDS = {
    'адресс':'адрес', 'адрс':'адрес', 'адерс':'адрес',
    'билярд':'бильярд', 'бильард':'бильярд', 'бильярт':'бильярд',
    'билльярд':'бильярд', 'бильирд':'бильярд', 'бильярдик':'бильярд',
    'мафка':'мафия','мафку':'мафию','мафке':'мафии','мафиа':'мафия','мафиюха':'мафия',
    'покир':'покер','покр':'покер','покерок':'покер',
    'кароке':'караоке','караоки':'караоке','караоеке':'караоке',
    'скока':'сколько','скок':'сколько','сколька':'сколько',
    'вифи':'wifi','уайфай':'wifi','вайфай':'wifi',
    'позырить':'посмотреть','наличкой':'наличными','карточкой':'картой',
    'почом':'почем','почемка':'почем',
    'седня':'сегодня','сёдня':'сегодня','севодня':'сегодня',
    'завтро':'завтра','завтря':'завтра',
    'админ':'администратор','админа':'администратора','админчик':'администратор',
    'забронить':'забронировать','забукать':'забронировать',
    'записатся':'записаться','запесаца':'записаться',
    'режым':'режим','работаите':'работаете',
    'восколько':'во сколько','докскольки':'до скольки',
    'гдэ':'где','подьехать':'подъехать','следущая':'следующая','следущий':'следующий',
    'коктели':'коктейли','дэсерт':'десерт','кандей':'кондей',
    'спс':'спасибо', 'пж':'пожалуйста', 'плиз':'пожалуйста',
    'тг':'телеграм','телега':'телеграм',
}

def normalize(s: str) -> str:
    s = str(s).lower().replace('ё','е')
    # Normalize punctuation before replacing multiword variants such as вай-фай.
    s = re.sub(r'[^0-9a-zа-я]+',' ',s)
    s = re.sub(r'\s+',' ',s).strip()
    s = re.sub(r'\bвай\s+фай\b','wifi',s)
    s = re.sub(r'\bwi\s*fi\b','wifi',s)
    tokens = [SPOKEN_WORDS.get(token, token) for token in s.split()]
    s = ' '.join(tokens)
    for a,b in ALIASES.items():
        if ' ' in a:
            s=re.sub(r'(?<![a-zа-я])'+re.escape(a)+r'(?![a-zа-я])',b,s)
    return re.sub(r'\s+',' ',s).strip()


def words(s: str) -> set[str]:
    return {w for w in normalize(s).split() if w not in STOP and len(w)>2}


def stem_match(haystack: str, needle: str) -> bool:
    return bool(re.search(r'(?<![а-яa-z])'+re.escape(needle)+r'[а-яa-z]*',haystack)) if len(needle)>=4 and ' ' not in needle else needle in haystack


def has(s: str, *stems: str) -> bool:
    return any(stem_match(s,x) for x in stems)


@lru_cache(maxsize=1)
def knowledge() -> tuple[dict,...]:
    data=json.loads((ROOT/'data'/'showcase_knowledge.json').read_text(encoding='utf-8'))
    return tuple(data['entries'])


def get_context(user_id: int|None) -> dict:
    if not user_id: return {}
    try:
        with session() as c:
            row=c.execute('SELECT last_entity,last_intent,last_topic,expires_at FROM dialogue_context WHERE telegram_id=?',(user_id,)).fetchone()
            if row and datetime.fromisoformat(row['expires_at'])>datetime.now(timezone.utc):
                return dict(row)
    except Exception:  # preserve Telegram replies if storage is undergoing upgrade
        return {}
    return {}


def save_context(user_id: int|None, entity: str, intent: str, topic: str) -> None:
    if not user_id: return
    now=datetime.now(timezone.utc)
    try:
        with session(write=True) as c:
            c.execute('''INSERT INTO dialogue_context(telegram_id,last_entity,last_intent,last_topic,updated_at,expires_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET
                last_entity=excluded.last_entity,last_intent=excluded.last_intent,
                last_topic=excluded.last_topic,updated_at=excluded.updated_at,expires_at=excluded.expires_at''',
                (user_id,entity,intent,topic,now.isoformat(),(now+timedelta(minutes=CONTEXT_TTL_MINUTES)).isoformat()))
    except Exception:
        pass  # never block the guest on transient SQLite availability


def _contains_entity(text: str) -> str|None:
    for entity,stems in ENTITY_MATCH_RE.items():
        if has(text,*stems): return entity
    return None


def _detect_intent(s: str) -> str|None:
    hits=[]
    for intent,stems in INTENT_STEMS.items():
        if has(s,*stems): hits.append(intent)
    if not hits: return None
    # Overrides: a mixed statement usually asks about a change, not availability.
    for priority in ('cancel','reschedule','myrequests','address','route','map','hours','support','duration','beginner','rules','price','availability','schedule','booking','players','profile','about'):
        if priority in hits:return priority
    return hits[0]


def _score(query: str, item: dict, entity: str|None, intent: str|None, context:dict) -> float:
    aliases=item['aliases']
    qtokens=words(query)
    normalized=normalize(query)
    best=0.0
    for alias in aliases:
        a=normalize(alias)
        atokens=words(alias)
        if a==normalized: return 50.0
        if len(a)>=10 and (a in normalized or (len(normalized)>=10 and normalized in a)):
            best=max(best,9.0)
        if atokens and qtokens:
            overlap=0.0
            used=set()
            for w in qtokens:
                for aw in atokens-used:
                    if w==aw or (min(len(w),len(aw))>=5 and (w.startswith(aw[:5]) or aw.startswith(w[:5]))):
                        overlap+=1; used.add(aw);break
            denom=max(1,(len(qtokens)+len(atokens))/2)
            ratio=overlap/denom
            if overlap>=2 or (len(qtokens)==1 and overlap==1 and len(atokens)<=2):
                best=max(best,5.5*ratio+0.45*SequenceMatcher(None,normalized,a).ratio())
    # A known topic and a specific question intent provide stronger evidence than
    # lexical overlap alone. A generic 'сколько стоит?' without a subject does not.
    if entity and intent and item['entity']==entity and item['intent']==intent:
        best=max(best,2.4)
    if intent=='profile' and item['id']=='profile':
        best=max(best,2.4)
    if intent=='support' and item['id']=='support':
        best=max(best,2.4)
    if intent=='address' and item['id']=='location':
        best=max(best,3.0)
    if best<0.65:return -100
    if entity:
        best += 3.7 if item['entity']==entity else (-4.5 if item['entity']!='bar' else -0.9)
    if intent:
        best += 3.2 if item['intent']==intent else -1.8
    # If a brief continuation has no explicit entity, restore the preceding topic.
    if not entity and context.get('last_entity') and item['entity']==context['last_entity']:
        best+=2.0
    return best


def _events(kind: str|None, availability=False) -> str:
    events=service.list_events()
    if kind in ('poker','mafia'):
        events=[e for e in events if e['kind']==kind]
    if not events:
        return 'Пока ближайших встреч в опубликованной афише нет. Загляните в Mini App позже или уточните у администратора.'
    label='Свободные места на ближайших встречах:' if availability else 'Ближайшие встречи:'
    out=[label]
    try:
        from zoneinfo import ZoneInfo
        zone=ZoneInfo(settings.club_timezone)
    except Exception:
        zone=timezone.utc
    for ev in events[:4]:
        local=datetime.fromisoformat(ev['starts_at']).astimezone(zone)
        free=max(0,ev['capacity']-ev['occupied'])
        out.append(f'• {ev["title"]}: {local:%d.%m} в {local:%H:%M}, свободно {free} из {ev["capacity"]} мест')
    out.append('Записаться можно в «Афише» Mini App; окончательное подтверждение — от администратора.')
    return '\n'.join(out)


def _resolve(query: str, context: dict) -> dict|None:
    s=normalize(query)
    entity=_contains_entity(s)
    intent=_detect_intent(s)
    # Intent-only followup uses the last unambiguous entity.
    if entity is None and context.get('last_entity') and (intent in ('price','schedule','availability','duration','beginner','rules','booking','players','about')):
        entity=context['last_entity']
    candidates=[]
    for item in knowledge():
        if item['source_type']=='demo' and not settings.showcase_mode:
            continue
        score=_score(s,item,entity,intent,context)
        if score>=2.8:
            candidates.append((score,item))
    if not candidates:return None
    candidates.sort(key=lambda pair:pair[0],reverse=True)
    score,item=candidates[0]
    # Do not guess solely because some words are vaguely similar.
    if score<4.3:return None
    if len(candidates)>1 and score-candidates[1][0]<0.35 and score<9.0:
        return None
    return item


def _reply_for(item:dict, user_id:int|None) -> str:
    ans=item['answer']
    if ans.startswith('dynamic:'):
        key=ans.split(':',1)[1]
        return _events(key,availability=item['intent']=='availability')
    if item['source_type']=='demo' and not settings.showcase_mode:
        return 'Уточните актуальные условия у администратора клуба.'
    return ans


def answer(text:str, user_id:int|None=None) -> str|None:
    """Answer only on sufficiently recognized domains; None means staff escalation.

    user_id enables an optional *private* 25-minute SQLite topic pointer, no chat logs.
    """
    text=(text or '').strip()
    if not text:
        return 'Напишите вопрос: адрес, график, игры, цены или бронь — отвечу по делу.'
    if len(text)>1500:return 'Вопрос получился длинным. Напишите, пожалуйста, до 1500 символов.'
    if THANKS.fullmatch(text):return 'Пожалуйста! Если захотите уточнить что-то ещё — пишите 🙂'
    rest=INTRO.sub('',text).strip(' !,.')
    if not rest:
        return 'Добрый вечер! 👋 Я помогу с адресом, расписанием, ценами, караоке и бронью в «Туристе». Спрашивайте как удобно, обычными словами.'
    text=rest
    norm=normalize(text)
    context=get_context(user_id)
    # Very short conversational follow-ups can omit both subject and the
    # price word: after a topic, «а скока?» is a price question.
    # Without context we ask for clarification below instead of guessing.
    if context.get('last_entity') and norm in ('а сколько','сколько','ну сколько','а почем','а почем это','а по цене'):
        subject={'mafia':'мафия','poker':'покер','billiard':'бильярд','karaoke':'караоке'}.get(context['last_entity'])
        if subject:
            text=f'Сколько стоит {subject}?'
            norm=normalize(text)
    if norm in ('а почем это','а сколько','сколько','а почем это будет','сколько это будет стоить','а сколько это стоит','а по цене','сколько стоит','а завтра тоже можно','а завтра можно','а на завтра можно') and not context.get('last_entity'):
        return 'Уточните, пожалуйста, что Вас интересует: мафия, покер, бильярд или посещение бара?'
    if not settings.showcase_mode and _detect_intent(normalize(text))=='price':
        return 'Стоимость участия уточняется у администратора клуба. Напишите, какая игра Вас интересует, — подскажем условия.'
    # Hypothetical no-show questions must get the policy, not a generic
    # cancellation instruction. A direct "я не приду" still offers cancellation.
    if (has(norm,'что будет','что если','штраф','неявк') and
        has(norm,'не приду','не явл','неявк','брон','игр')):
        hypothetic = _resolve(text, context)
        if hypothetic and hypothetic['id']=='no_show':
            if user_id: save_context(user_id,hypothetic['entity'],hypothetic['intent'],hypothetic['id'])
            return _reply_for(hypothetic,user_id)
    # A negative preference followed by a separate positive question is not a cancel request.
    # e.g. «Не хочу играть в мафию, а бильярд у вас есть?».
    if has(norm,'не хочу','не буду') and (',' in text or ' а ' in f' {norm} '):
        fragments=re.split(r',\s*|\s+а\s+',text,maxsplit=1,flags=re.I)
        if len(fragments)==2 and _contains_entity(normalize(fragments[1])):
            positive=_resolve(fragments[1],{})
            if positive:
                if user_id:save_context(user_id,positive['entity'],positive['intent'],positive['id'])
                return _reply_for(positive,user_id)
    # A user can explicitly say not to cancel; no cancellation should be implied.
    if has(norm,'не хочу отмен','не надо отмен','не отменя'):
        return 'Хорошо, заявку не меняю. Её текущий статус можно проверить в «Моих заявках».'
    if has(norm,'отмен','передум','не приду') and has(norm,'заявк','брон','игр','мафи','покер','бильяр','мест'):
        return 'Для отмены откройте «Мои заявки» и нажмите «Запросить отмену». Администратор рассмотрит запрос, а статус обновится.'
    # A negated booking statement is NOT permission to register the user.
    if has(norm,'не хочу','не надо','не буду') and has(norm,'запис','брон','играт','пойт'):
        return 'Понял, записывать Вас не буду. Если заявка уже была оформлена, откройте «Мои заявки» и запросите отмену.'
    # A cancellation request takes precedence over generic suggestions to join an event.
    if has(norm,'отмен','отказ','передум') and has(norm,'мафи','покер','брон','запис','бильяр'):
        return 'Чтобы отменить оформленную заявку, откройте «Мои заявки» и нажмите «Запросить отмену». Администратор проверит её, а статус обновится.'
    # If the person asks an unscoped price question involving unrelated objects, do not
    # fabricate a price by fuzzy-matching the words «сколько стоит» to a random ticket.
    if _detect_intent(norm)=='price' and _contains_entity(norm) is None and not context.get('last_entity'):
        known=('вход','бар','кафе','билет','игр','стол','меню','напит','кофе','песн','депозит','участ','чай','лимонад','пиво','фри')
        if not any(stem in norm for stem in known) and len(words(norm))>=2:
            return 'Уточните, пожалуйста, что интересует по цене: игра, бильярд, столик или меню?'
    # Separately answer meaningful compound questions; never combine duplicate booking actions.
    parts=re.split(r'\s+и\s+|[,;]\s*а\s+',text,maxsplit=1,flags=re.I)
    if len(parts)==2 and len(parts[0].strip())>=3 and len(parts[1].strip())>=3:
        first=_resolve(parts[0],context)
        second=_resolve(parts[1], {**context,'last_entity':first['entity']} if first else context)
        if first and second and first['id']!=second['id']:
            if user_id: save_context(user_id,second['entity'],second['intent'],second['id'])
            return _reply_for(first,user_id)+'\n\n'+_reply_for(second,user_id)
    # A definite address query must beat broad topic matches ("где вы вообще находитесь").
    item=_resolve(text,context)
    if not item and norm in ('а почем это будет','а завтра тоже можно','а завтра можно','а по цене'):
        return 'Подскажите, пожалуйста, речь об игре, бильярде или о посещении бара? Тогда отвечу точнее.'
    if item and settings.showcase_mode and item['id']=='billiard_price':
        hours_match=re.search(r'(?<![а-я])(\d+|один|два|две|три|четыре)\s*(?:час|ч\b)',norm)
        if hours_match:
            h={'один':1,'два':2,'две':2,'три':3,'четыре':4}.get(hours_match.group(1))
            if h is None:h=int(hours_match.group(1))
            if 1<=h<=4:
                if user_id:save_context(user_id,'billiard','price','billiard_price')
                return f'Бильярд: {h} ч × 900 ₽ = {h*900:,} ₽ за стол. Выберите время в Mini App, чтобы отправить заявку на бронь.'.replace(',', ' ')

    if item:
        if user_id: save_context(user_id,item['entity'],item['intent'],item['id'])
        return _reply_for(item,user_id)
    # Explicitly unrecognized; caller may add an operator ticket.
    return None
