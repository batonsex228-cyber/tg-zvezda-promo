import asyncio, json, tempfile, re, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from unittest.mock import AsyncMock
from app.config import Settings
from app.db import Database
from app.knowledge import KnowledgeBase
from app.responder import StrictResponder
from app.core import SupportCore
from app.operator import OperatorBridge
from app.shift_booking import ShiftEngine
from app.telegram_adapter import TelegramAdapter
from app.telegram_keyboards import shift_consent_keyboard, shift_review_keyboard, manager_shift_keyboard

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))

async def run():
 with tempfile.TemporaryDirectory() as tmp:
  settings=Settings(site_url='https://zvezdaglazov.ru/',kb_file=Path(tmp)/'kb.json',db_file=Path(tmp)/'db.sqlite',crawl_max_pages=40,openai_api_key=None,openai_model='gpt-5.6',faq_min_score=.72,retrieval_min_score=.48,camp_name='ДЗЛ Звездочка',debug=True,show_source_links=True,telegram_bot_token='123:test',telegram_manager_user_id=99,shift_bookings_enabled=True,shift_privacy_policy_url='https://zvezdaglazov.ru/pages/parents.html',shift_active_numbers=(1,2,3,4))
  db=Database(settings.db_file)
  kb=KnowledgeBase(settings.kb_file,ROOT/'data/seed_faq.json',db,fallback_kb_file=ROOT/'data/knowledge_base.json')
  core=SupportCore(StrictResponder(settings,kb))
  op=OperatorBridge(settings,db)
  shifts=ShiftEngine(settings,db,backend=None)
  tg=TelegramAdapter(settings,core,db,op,knowledge_base=kb,shifts=shifts)
  sent=[]; answers=[]
  async def fake_api(method, **kw):
   if method=='sendMessage': sent.append(kw); return {'message_id': len(sent)}
   if method=='answerCallbackQuery': answers.append(kw); return True
   return {}
  tg.api=fake_api
  op.set_telegram_sender(tg.send_plain_from_operator)
  op.set_telegram_manager_sender(tg.send_to_manager)
  op.set_telegram_marker(tg.mark_support_conversation)
  def msg(text,user=10):
   return {'message':{'from':{'id':user,'first_name':'Иван' if user==10 else 'Миша'},'chat':{'id':user,'type':'private'},'text':text}}
  async def command(text,user=10): await tg._dispatch_telegram(msg(text,user))
  async def press(action,cmd,manager=False):
   peer=99 if manager else 10
   if action=='shift_parent':
    key=shift_consent_keyboard() if cmd.startswith('consent') else shift_review_keyboard()
   elif action=='shift_manager':
    with db._conn() as conn: app=conn.execute('SELECT application_id FROM shift_applications ORDER BY rowid DESC').fetchone()[0]
    key=manager_shift_keyboard(app)
   m=tg._telegram_keyboard(key,peer)
   for row in m['inline_keyboard']:
    for b in row:
     payload=tg._lookup_callback(peer,b['callback_data'])
     if payload.get('action')==action and payload.get('cmd')==cmd:
      return await tg._dispatch_telegram({'callback_query':{'id':'CALLBACK'+cmd,'from':{'id':peer},'message':{'chat':{'type':'private','id':peer}},'data':b['callback_data']}})
   raise AssertionError(cmd)
  await command('/start'); assert any('помощ' in m['text'].lower() for m in sent)
  print('start',len(sent));sent.clear()
  await command('Хочу оформить заявку на 3 смену')
  print('shift intro',sent[-1]['text'][:100]);assert shifts.has_active(10)
  await press('shift_parent','consent_yes'); assert shifts._session(10)['step']=='child_name'
  await command('Назаров Василий Николаевич'); assert shifts._session(10)['step']=='child_birth_date'
  await command('15.06.2014'); assert shifts._session(10)['step']=='phone'
  await command('+79001234567'); assert shifts._session(10)['step']=='parent_name'
  await command('Назаров Алексей Сергеевич'); assert shifts._session(10)['step']=='review'
  await press('shift_parent','submit'); assert not shifts.has_active(10)
  with db._conn() as conn: app=conn.execute('SELECT * FROM shift_applications').fetchone()
  assert app and app['phone']=='+79001234567'
  assert any(m['chat_id']==99 and app['application_id'] in m['text'] for m in sent)
  assert any(m['chat_id']==10 and app['application_id'] not in m['text'] and 'успешно' in m['text'] for m in sent)
  print('shift submit: PASS')
  await press('shift_manager','approve',manager=True)
  with db._conn() as conn: app=conn.execute('SELECT status FROM shift_applications').fetchone()
  assert app['status']=='confirmed'
  assert any('подтвердил' in m['text'] for m in sent if m['chat_id']==10)
  await command('🍲 Питание'); print('food answer',sent[-1]['text'][:80]); assert any('питан' in m['text'].lower() for m in sent[-3:])
  await command('#stats',user=99); assert 'статистик' in sent[-1]['text'].lower()
  await command('В каком конкретно ящике на складе лежат мои потерянные фиолетовые очки?')
  with db._conn() as conn:
   ticket = conn.execute("SELECT id FROM tickets WHERE platform='telegram' AND status='open' ORDER BY id DESC LIMIT 1").fetchone()
  assert ticket, 'Manager escalation should create a Telegram support ticket'
  await command(f'#{ticket["id"]} Мы проверим находку и свяжемся с Вами.', user=99)
  assert any(m['chat_id']==10 and 'Ответ специалиста' in m['text'] for m in sent)
  with db._conn() as conn:
   closed=conn.execute('SELECT status FROM tickets WHERE id=?', (ticket['id'],)).fetchone()
  assert closed['status']=='answered'
  db.set_subscription(user_id=10,peer_id=10,enabled=True)
  await command('#рассылка',user=99)
  await command('Тестовое объявление о начале смены.',user=99)
  with db._conn() as conn:
   campaign=conn.execute('SELECT id FROM newsletter_campaigns ORDER BY id DESC LIMIT 1').fetchone()
  assert campaign
  from app.telegram_keyboards import newsletter_preview_keyboard
  markup=tg._telegram_keyboard(newsletter_preview_keyboard(campaign['id']),99)
  cb=markup['inline_keyboard'][0][0]['callback_data']
  await tg._dispatch_telegram({'callback_query':{'id':'NEWS', 'from':{'id':99},
    'message':{'chat':{'type':'private','id':99}},'data':cb}})
  assert any(m['chat_id']==10 and 'Тестовое объявление' in m['text'] for m in sent)
  await tg.close()
  print('FULL PORT FLOW PASS',len(sent),'messages')

asyncio.run(run())
