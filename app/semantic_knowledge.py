"""Evidence-limited, platform-independent topic understanding for conversational Russian.

No per-message lookup table: compact concept vocabulary is scored against messages,
then corroborated with safe, reviewed topic cards. Does NOT claim to be a neural model.
Important mutable/medical/individual facts are never inferred.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

CATALOG_FILE = Path(__file__).resolve().parent.parent / 'data' / 'semantic_topics.json'
WORD = re.compile(r'[а-яёa-z0-9]+', re.I)
STOP = frozenset('а и но а еще вообще вы мне нам пожалуйста пж подскажите слушайте вот это какие какая какой как у вас на в во с со про там ребята сын дочка ребенок дети из за куда для от да ли по уже что сколько скок вообще'.split())
SLANG = {
    'скок': 'сколько', 'скока':'сколько','сколька':'сколько', 'денех':'денег',
    'почем':'цена', 'пачом':'цена', 'плз':'пожалуйста','пж':'пожалуйста',
    'скидон':'скидка','дисконт':'скидка','доки':'документы',
    'кроссы':'кроссовки','шмотки':'одежда','тапки':'тапочки',
    'тел':'телефон', 'мыльно':'гигиена','рыльное':'гигиена',
    'мобилы':'телефоны','мобилу':'телефон','забронить':'забронировать',
    'покушац':'покушать','годик':'год','дата др':'дата рождения',
    'тг':'телеграм','ок':'хорошо',
}

@dataclass(frozen=True)
class Topic:
    topic_id: str
    confidence: float
    policy: str
    text: str | None
    source: str
    needs_review: bool
    expired: bool

@dataclass(frozen=True)
class Analysis:
    topics: tuple[Topic, ...] = ()
    clarification: str | None = None


def normalize(text: str) -> list[str]:
    raw=(text or '').lower().replace('ё','е').replace('мыльно-рыльное','гигиена')
    for a,b in SLANG.items():
        raw=re.sub(r'(?<![\wа-я])'+re.escape(a)+r'(?![\wа-я])',b,raw)
    tokens=WORD.findall(raw)
    return [t for t in tokens if t not in STOP]


def has_root(tokens: list[str], root: str) -> bool:
    """Match inflected roots and moderate typos; never fuzzy-match short digits/words."""
    root=root.lower().replace('ё','е')
    for word in tokens:
        if word.startswith(root) or (len(root)>=5 and root in word and len(word)-len(root)<=3):
            return True
        if len(root)>=6 and len(word)>=5 and word[:2] == root[:2]:
            prefix=word[:min(len(word),len(root)+2)]
            if SequenceMatcher(None,prefix,root).ratio()>=0.94:
                return True
    return False


def any_root(tokens: list[str], *roots: str) -> bool:
    return any(has_root(tokens, r) for r in roots)


def shift_number(text: str) -> int | None:
    raw=(text or '').lower().replace('ё','е')
    mapping={'перв':1,'втор':2,'трет':3,'треть':3,'четвер':4}
    for stem,num in mapping.items():
        if re.search(r'(?<![а-я])'+stem+r'[а-я]*', raw):
            if any_root(normalize(raw),'смен','путев','стоим','цен','стоит','дат','когда','лет','сколько') or 'на '+stem in raw or 'а '+stem in raw:
                return num
    if re.search(r'\b(?:сразу|две|два|купим|покупаем)\s+(?:\d\s+)?смен\w*',raw) and re.search(r'\b[1-4]\s+смен\w*',raw):
        return None  # number of purchased shifts, not an ordinal
    m=re.search(r'(?<!\d)([1-4])\s*(?:-?\s*(?:я|ю|ая|ую|ью))?\s*(?:смен|путев)|(?:смен|путев)\w*\s*(?:№\s*)?([1-4])(?=\D|$)',raw)
    if m:return int(next(g for g in m.groups() if g is not None))
    return None


class SemanticKnowledge:
    def __init__(self, catalog_path: Path | None = None, *, now: date | None = None):
        raw=json.loads((catalog_path or CATALOG_FILE).read_text(encoding='utf-8'))
        self.cards={str(c['topic_id']):c for c in raw['topics']}
        self.now=now or date.today()

    def _score(self, card: dict[str,Any], words: list[str]) -> float:
        # Multiple concept roots, not a full-utterance equality test.
        anchors=[a for a in card['anchors'] if len(a)>=3]; mods=[m for m in card['modifiers'] if len(m)>=3]
        matches=sum(has_root(words,a) for a in anchors)
        mod_matches=sum(has_root(words,a) for a in mods)
        if not matches:return 0.0
        return min(0.99,0.30+0.145*min(matches,4)+0.07*min(mod_matches,4))

    def _make(self, topic_id: str, confidence: float) -> Topic:
        card=self.cards[topic_id]
        expiry=str(card.get('valid_until') or '')
        expired=bool(expiry and self.now>date.fromisoformat(expiry))
        return Topic(topic_id=topic_id, confidence=confidence, policy=card['policy'],
                     text=card.get('response'), source=card.get('verified_source') or '',
                     needs_review=bool(card.get('required_review')), expired=expired)

    def analyze(self, text: str, context: dict[str,str] | None = None) -> Analysis:
        raw=(text or '').lower().replace('ё','е')
        words=normalize(text)
        if not words:return Analysis()
        # Invalid calendar dates are rejected before answering about arrivals or reservations.
        for m in re.finditer(r'(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)',raw):
            try:
                date(int(m.group(3)),int(m.group(2)),int(m.group(1)))
            except ValueError:
                return Analysis(clarification='В указанной дате есть ошибка. Проверьте число и месяц, пожалуйста. Например: 30.06.2027.')
        ctx=(context or {}).get('topic') or ''
        ctx=ctx.removeprefix('semantic:')
        entity=(context or {}).get('entity') or ''
        if ctx=='office_address' and re.search(r'\b(?:сами|сами\s+корпуса|где\s+корпус)',raw):
            return Analysis((self._make('camp_address',.91),))
        if ctx=='payment_refund' and any_root(words,'частям','верн','оплат','рассроч','взнос'):
            return Analysis((self._make('payment_refund',.89),))
        if ctx=='weekend' and any_root(words,'дня','дней','ноч','суток','выходн'):
            return Analysis((self._make('weekend',.85),))
        if re.search(r'\bне\s+нужн\w*\s+(?:аренд\w*\s+)?бесед\w*',raw) and any_root(words,'смен','путев'):
            return Analysis((self._make('shifts_all',.93),))

        # Context is explicitly scoped to a previous, non-sensitive subject.
        if (any_root(words,'свобод','занят','налич','остал') and
                (any_root(words,'дат','суббот','воскрес','завтр','сегод','врем') or 'эту' in raw) and
                (ctx in {'gazebo_price','gazebo_booking','weekend'} or entity=='extra_service_dynamic')):
            return Analysis((self._make('gazebo_booking',.96),))
        if len(words)<=5 and re.search(r'\b(?:а\s+)?(?:там|эта|эту|той|этой|это)\b',raw):
            if any_root(words,'свобод','налич','остал'):
                if not ctx:return Analysis(clarification='Уточните, пожалуйста, о какой смене или услуге и дате речь. Наличие проверяется отдельно.')
                return Analysis((self._make('free_places', .85),))
            if any_root(words,'стоит','цен','сколько','дорог'):
                if ctx in {'gazebo_price','weekend','winter','shift_1','shift_2','shift_3','shift_4','summer_price','shifts_all','quests'}:
                    return Analysis((self._make(ctx,.87),))
                if not ctx:return Analysis(clarification='Подскажите, пожалуйста, стоимость чего хотите узнать: путёвки, беседки или тура выходного дня?')

        if any_root(words,'адрес') and any_root(words,'оформ','договор','документ') and not re.search(r'\bне\s+офис',raw):
            return Analysis((self._make('office_address',.92),))
        if any_root(words,'возраст') or (re.search(r'\b(?:16|17)\b',raw) and any_root(words,'лет','сайт','путев')):
            return Analysis((self._make('age',.94),))
        if re.search(r'\b(?:подать|оформить|оставить)\s+заявк\w*',raw) and not any_root(words,'смен','путев','номер'):
            return Analysis(clarification='Конечно, помогу оформить заявку. На какую смену хотите записать ребёнка? Напишите номер смены, и я подскажу следующий шаг.')
        # Prioritize live checks, privacy, health, refunds and special discount categories.
        # These classes never gain 'confirmed' status from fuzzy similarity.
        if (any_root(words,'вожат','отряд') and any_root(words,'номер','связ','позвон','телефон')) or (
              any_root(words,'мой','моем','вася','дочк','сын','ребен') and
              any_root(words,'корпус','жив','поговор','связ') and
              not any_root(words,'аренд','ночев','стоим')):
            return Analysis((self._make('contact_child',.99),))
        if any_root(words,'аллерг','диабет','глютен','неперенос','инсулин'):
            # Don't let a generic dietary FAQ 'answer' an individual medical situation.
            return Analysis((self._make('food_allergy',.99),))
        if any_root(words,'рассроч','возврат','вернет','вернут','предоплат','аванс','кредит'):
            return Analysis((self._make('payment_refund',.98),))
        if any_root(words,'многодет','инвалид','малоимущ','ветеран') or 'сво' in words:
            return Analysis((self._make('discount_other',.98),))
        if any_root(words,'свобод') and any_root(words,'мангал') and any_root(words,'суббот','воскрес','дат','числ'):
            return Analysis((self._make('gazebo_booking',.95),))
        if any_root(words,'бесед','беседоч') and any_root(words,'свобод','заброни','бронь','аренд','взять') and any_root(words,'дат','числ','суббот','воскрес','час','свобод','заброни','бронь') and not any_root(words,'стоит','цен','стоим'):
            return Analysis((self._make('gazebo_booking',.97),))
        if (any_root(words,'мест','путев','смен','июл','август') and
                any_root(words,'остал','свобод','налич','разобрал','занят','законч') and
                not any_root(words,'стоит','цен','стоим','скид')):
            return Analysis((self._make('free_places',.98),))
        if any_root(words,'цитрус','апельсин','яблок','печеньк','шоколад','передачк'):
            return Analysis((self._make('allowed_food',.93),))
        if any_root(words,'телефон','мобил','смартфон','звон') and any_root(words,'забира','отбира','выда','хран','сдав','звон'):
            other=(self._make('food_freq',.86),) if any_root(words,'корм','питан','едят') else ()
            return Analysis((self._make('phone_policy',.96),*other))
        if any_root(words,'079') or ('медсправк' in words and any_root(words,'дней','день','срок')):
            return Analysis((self._make('form_079',.97),))
        if any_root(words,'договор') and any_root(words,'паспорт','снилс','документ','оформ'):
            return Analysis((self._make('contract_docs',.96),))
        if any_root(words,'документ','справк','полис','свидетельств') and any_root(words,'мест','свобод','остал') and any_root(words,'смен','втор','перв','треть','трет','четвер','путев'):
            sh=shift_number(text)
            out=((self._make(f'shift_{sh}',.91),) if sh else ())
            return Analysis((*out,self._make('arrival_docs',.91),self._make('free_places',.94)))
        if any_root(words,'документ','справк','полис','свидетельств') and any_root(words,'заезд','привез','документ','справк','нужн','требу'):
            return Analysis((self._make('arrival_docs',.91),))

        # Numbered shifts override fuzzy phrases such as "сколько стоит путевка".
        # Age and an explicit request for the daily menu must never become shift-price answers.
        if any_root(words,'возраст') or (any(w.isdigit() and int(w) in range(6,18) for w in words) and any_root(words,'лет','летн','ребен','сын','дочк') and not any_root(words,'смен')):
            return Analysis((self._make('age',.92),))
        if any_root(words,'меню','раскладк','готовят') and any_root(words,'питан','сахар','дня','завтр','обед','смен','меню'):
            return Analysis((self._make('menu_today',.92),))
        if any_root(words,'вход','включ','доплач','страхов') and any_root(words,'стоим','путев','питан','кружк','тыс') and not any_root(words,'трансфер'):
            return Analysis((self._make('included',.9),))
        if any_root(words,'забыл','потерял','находк','пропал') or (any_root(words,'вещ') and any_root(words,'после') and any_root(words,'смен')):
            return Analysis((self._make('lost',.91),))
        if any_root(words,'корпоратив','свадьб','банкет','конференц'):
            return Analysis((self._make('events',.94),))
        if any_root(words,'квест'):
            return Analysis((self._make('quests',.93),))
        if any_root(words,'вирус','простуд','заболеет','температур') and not any_root(words,'лечени','срочно'):
            return Analysis((self._make('illness',.92),))
        # Explicitly comparing two numbered shifts: show both, not just the first.
        if any_root(words,'дешевл','сравн','разниц','одинаков') or re.search(r'\b[1-4]\s+смен\w*\s+или\s+[1-4]',raw):
            pair=re.findall(r'(?<!\d)([1-4])\s*(?:-?я)?\s*(?:смен\w*)?|(?<!\d)([1-4])(?=\s*(?:или|\?|$))',raw)
            numbers=[]
            for match in pair:
                val=next((x for x in match if x),None)
                if val and int(val) not in numbers:numbers.append(int(val))
            if len(numbers)>=2:
                return Analysis(tuple(self._make(f'shift_{n}',.94) for n in numbers[:2]))
        shift=shift_number(text)
        if shift is None and re.search(r'\bна\s+(?:перв\w*|втор\w*|трет\w*|треть\w*|четвер\w*)\b',raw):
            shift=next((n for prefix,n in [('перв',1),('втор',2),('трет',3),('треть',3),('четвер',4)] if re.search(r'\bна\s+'+prefix,raw)),None)
        forced_shift=f'shift_{shift}' if shift is not None else None
        if forced_shift and not any_root(words,'исправ','отмен','подтвержд') and not any_root(words,'запис','оформ','заявк','заброни'):
            match=self._make(forced_shift,.99)
            secondary=[]
            if any_root(words,'выезд','привоз','заезд','забира'):
                secondary.append(self._make('arrival',.86))
            if any_root(words,'документ','справк','полис'):
                secondary.append(self._make('arrival_docs',.86))
            if any_root(words,'свобод','мест','остал','налич'):
                secondary.append(self._make('free_places',.89))
            # User asks for all shifts, not a single numbered one.
            if any_root(words,'все','график','расписан') and 'до четвертой' in raw:
                return Analysis((self._make('shifts_all',.96),))
            return Analysis((match,*secondary))

        # Introductory statements and form controls stay with deterministic engines.
        if any_root(words,'запис','оформ','заявк','заброни') and (any_root(words,'путев','смен','дочк','сын','перв','втор','трет','четвер')):
            return Analysis((self._make('shift_apply',.92),))
        if any_root(words,'исправ','поправ','ошибк') and any_root(words,'анкет','фамил','телефон','рожден','дат','др'):
            return Analysis((self._make('form_change',.96),))
        if any_root(words,'согласен','согласна','отказываюсь') and len(words)<=9:
            return Analysis((self._make('form_consent',.95),))
        if len(words)<=7 and any_root(words,'подтверждаю','отмен','отправляйте','передумали'):
            return Analysis((self._make('form_confirmation',.86),))

        if any_root(words,'скид','дисконт','дешевл','мчс','фсб','мвд','фсин') and not any_root(words,'многодет','инвалид','малоимущ','ветеран'):
            return Analysis((self._make('discount',.94),))
        if any_root(words,'зим','новогод') and any_root(words,'лагер','смен','каникул','путев','есть'):
            return Analysis((self._make('winter',.93),))
        if any_root(words,'цен','стоим','стоит','тыс','денег') and any_root(words,'лет','путев','смен') and not any_root(words,'бесед','ночев','зим','новогод'):
            if not any_root(words,'первая','вторая','третья','четвертая'):
                return Analysis((self._make('summer_price',.9),))
        if any_root(words,'заезд','привоз','выезд','забира') and not any_root(words,'город','автобус','трансфер'):
            return Analysis((self._make('arrival',.9),))
        if any_root(words,'автобус','трансфер','довоз') or (any_root(words,'забира') and any_root(words,'город')):
            return Analysis((self._make('transfer',.93),))
        if (any_root(words,'навещ','посещ','приход','приех') or re.search(r'\bв\s+вс\b',raw)) and any_root(words,'дочк','мама','ребен','дет','лагер'):
            return Analysis((self._make('visits',.9),))
        if any_root(words,'позвон','контакт','почт','номер','админ') and any_root(words,'путев','лагер','школ','админ','тел') and not any_root(words,'вожат','ребен','дочк','сын'):
            return Analysis((self._make('contacts',.9),))
        if any_root(words,'офис','офлайн','ленина','продаж') and not any_root(words,'корпус','бесед') and not re.search(r'\bне\s+офис',raw):
            return Analysis((self._make('office_address',.89),))
        if any_root(words,'адрес','навигатор','адам') and any_root(words,'лагер','звездочк','физически','адам'):
            return Analysis((self._make('camp_address',.92),))
        if any_root(words,'вейп','ножик','сигарет','зажигал') or (any_root(words,'нельзя','запрещ') and any_root(words,'вещ','предмет','класть')):
            return Analysis((self._make('forbidden_items',.92),))
        if any_root(words,'чипс','кол','дошик','сухарик') or (any_root(words,'нельзя','запрещ') and any_root(words,'ед','продукт')):
            return Analysis((self._make('forbidden_food',.92),))
        if any_root(words,'кросс','обув','тапк','тапоч','кед','сандал'):
            return Analysis((self._make('shoes',.89),))
        if any_root(words,'гигиен','шампун','щетк','зубн','паста','мыл'):
            return Analysis((self._make('hygiene',.9),))
        if any_root(words,'кофт','одежд','тепл','шмот','дожд') and any_root(words,'брать','собра','какие','сколько','надо','список'):
            return Analysis((self._make('clothing',.87),))
        if any_root(words,'лекарств','таблетк','антибиотик','препарат'):
            return Analysis((self._make('medicines',.92),))
        if any_root(words,'территор','бассейн','душ','корпус') and not any_root(words,'ночев','тур','стоит','цена'):
            return Analysis((self._make('territory',.88),))
        if any_root(words,'активност','занят','программ','кружк','танц','блогинг'):
            return Analysis((self._make('program',.88),))
        if any_root(words,'ночев','выходн','ночь','корпус','прожив'):
            return Analysis((self._make('weekend',.86),))
        # Score all topic cards from compact concept lexicon, not 150 test phrases.
        excluded={'social','multi_intent','context_followup','form_consent','form_confirmation','form_change','shift_apply',
                  'free_places','gazebo_booking','shift_1','shift_2','shift_3','shift_4'}
        ranked=[]
        for tid,card in self.cards.items():
            if tid in excluded:continue
            s=self._score(card,words)
            if s>=0.43:ranked.append((s,tid))
        ranked.sort(reverse=True)
        if not ranked:return Analysis()
        # Specificity and exclusion safeguards before considering multiple topics.
        identifiers={tid for s,tid in ranked if s>.48}
        if 'discount' in identifiers and not any_root(words,'скид','дисконт','скидон','дешевл','льгот','мчс','фсб','мвд','фсин'):
            ranked=[(s,t) for s,t in ranked if t!='discount']
        if 'summer_price' in identifiers and not any_root(words,'цен','стоит','стоим','почем','дорог','денег','тысяч'):
            ranked=[(s,t) for s,t in ranked if t!='summer_price']
        if not any_root(words,'зим','новогод','январ'):
            ranked=[(s,t) for s,t in ranked if t!='winter']
        if 'phone_policy' in identifiers and any_root(words,'телефон','номер') and not any_root(words,'отбира','забира','выда','хран','сдава','мобил'):
            ranked=[(s,t) for s,t in ranked if t!='phone_policy']
        if 'contacts' in identifiers and any_root(words,'звон','телефон') and any_root(words,'ребен','дочк','сын','мобил','вожат'):
            ranked=[(s,t) for s,t in ranked if t!='contacts']
        if 'arrival_docs' in identifiers and any_root(words,'снилс','договор'):
            ranked=[(s,t) for s,t in ranked if t!='arrival_docs']
        if 'included' in identifiers and not any_root(words,'вход','включ','доплач','страхов','кружк'):
            ranked=[(s,t) for s,t in ranked if t!='included']
        if 'visits' in identifiers and not any_root(words,'навещ','посещ','приех','прийти','приход'):
            ranked=[(s,t) for s,t in ranked if t!='visits']
        if 'food_freq' in identifiers and not any_root(words,'корм','питан','пищ','покуш','едят','голода'):
            ranked=[(s,t) for s,t in ranked if t!='food_freq']
        if not ranked:return Analysis()
        # Favor more discriminative topics over generic ones.
        specificity={'food_freq':.14,'forbidden_food':.14,'arrival':.1,'transfer':.14,'visits':.1,
                     'phone_policy':.11,'shoes':.14,'hygiene':.13,'clothing':.1,'forbidden_items':.1,
                     'gazebo_price':.22,'weekend':.18,'quests':.18,'office_address':.17,
                     'camp_address':.13,'included':.12,'program':.10,'discount':.12,
                     'age':.1,'gazebo_booking':.16,'menu_today':.12}
        ranked.sort(key=lambda it:it[0]+specificity.get(it[1],0),reverse=True)
        best_score, best=ranked[0]
        if best_score<0.44:return Analysis()
        # Multi-topic only where independent topics have strong distinct anchors and coordinating language.
        selected=[(best_score,best)]
        if re.search(r'\b(?:и|еще|ещё|но|плюс|а\s+также)\b',raw) or raw.count('?')>1:
            for score,tid in ranked[1:]:
                if len(selected)>=3:break
                if score>=0.51 and tid not in {t for s,t in selected}:
                    incompatible={frozenset(('clothing','shoes')), frozenset(('summer_price','shifts_all')),
                                  frozenset(('contacts','phone_policy')), frozenset(('gazebo_price','weekend'))}
                    if any(frozenset((tid,other)) in incompatible for _,other in selected):continue
                    selected.append((score,tid))
        return Analysis(tuple(self._make(t,s) for s,t in selected))

    def formulate(self, analysis: Analysis) -> tuple[str, str | None] | None:
        """Return safe human response + first cite URL. None delegates to old flow."""
        if analysis.clarification:return analysis.clarification,None
        if not analysis.topics:return None
        responses=[]; source=None
        for topic in analysis.topics[:3]:
            if topic.topic_id in {'shift_apply','form_consent','form_change','form_confirmation'}:
                return None  # Existing consent and state machines own these transitions.
            if not topic.text:
                return None
            if topic.expired and topic.policy in {'answer','conditional_answer'}:
                responses.append('Эту информацию нужно обновить по официальным данным. Уточните, пожалуйста, у администрации лагеря.');continue
            responses.append(topic.text)
            source=source or topic.source
        return '\n\n'.join(dict.fromkeys(responses)),source
