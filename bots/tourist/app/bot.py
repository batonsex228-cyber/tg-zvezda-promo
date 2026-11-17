"""Telegram commands, inline menu and admin moderation."""
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from aiogram import Bot, Dispatcher, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command, CommandStart
from aiogram.types import (Message, CallbackQuery, BotCommand, InlineKeyboardButton,
                           InlineKeyboardMarkup, WebAppInfo, MenuButtonWebApp, MenuButtonCommands,
                           KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove)
from app.config import settings
from app.database import initialize_storage
from app import service, sheets, assistant, ai_helper

router=Router()

class SupportQuestion(StatesGroup):
    text=State()


class SupportReply(StatesGroup):
    text=State()


class Registration(StatesGroup):
    name=State()
    phone=State()
    nick=State()

def local_date(value):
    return datetime.fromisoformat(value).astimezone(ZoneInfo(settings.club_timezone)).strftime('%d.%m.%Y %H:%M')


def menu():
    rows=[]
    if settings.webapp_url.startswith('https://'):
        rows.append([InlineKeyboardButton(text='📱 Открыть Mini App',web_app=WebAppInfo(url=settings.webapp_url))])
    rows.append([InlineKeyboardButton(text='🗓 Расписание', callback_data='schedule'),
                 InlineKeyboardButton(text='👤 Мои заявки', callback_data='mine')])
    rows.append([InlineKeyboardButton(text='💬 Вызвать администратора',callback_data='support')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def event_buttons(e):
    full=e['occupied']>=e['capacity'] or e['status']!='open'
    button=InlineKeyboardButton(text='Мест пока нет' if full else '📝 Записаться',callback_data='full' if full else f"join:{e['id']}")
    return InlineKeyboardMarkup(inline_keyboard=[
        [button],
        [InlineKeyboardButton(text='Назад к расписанию',callback_data='schedule')]])


async def show_schedule(message:Message):
    if message.chat.type!='private': return
    events=service.list_events()
    if not events:
        await message.answer('Ближайших событий пока нет. Расписание скоро появится.',reply_markup=menu()); return
    await message.answer('🗓 Ближайшие события клуба:')
    for e in events[:12]:
        desc=(f"{e['title']}\n{local_date(e['starts_at'])}\n"
              f"Мест: {e['capacity']-e['occupied']} из {e['capacity']}")
        if e['kind']=='poker':
            desc+=f"\nСтек: {e['stack']} · Блайнды: {e['blinds']}"
        await message.answer(desc,reply_markup=event_buttons(e))


async def show_mine(message:Message):
    if message.chat.type!='private': return
    u=service.ensure_user(message.chat.id)
    if not service.profile_ready(u):
        await message.answer('Для записи нужен профиль: имя, телефон и игровой ник. Нажмите /register или откройте Mini App.',reply_markup=menu()); return
    items=service.my_requests(message.chat.id)
    lines=[f"👤 {u['nickname']} · Мои заявки"]
    for x in items['events'][:10]: lines.append(f"🎲 {x['title']}: {service.STATUS_RU[x['status']]} (№{x['id']})")
    for x in items['billiard'][:10]: lines.append(f"🎱 Бильярд {local_date(x['starts_at'])}: {service.STATUS_RU[x['status']]} (№{x['id']})")
    if len(lines)==1: lines.append('Пока заявок нет.')
    await message.answer('\n'.join(lines),reply_markup=menu())
    for cat,xs in (('event',items['events']),('billiard',items['billiard'])):
        for x in xs[:10]:
            if x['status'] in ('pending','confirmed'):
                kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f'Запросить отмену №{x["id"]}',callback_data=f'cancel:{cat}:{x["id"]}')]])
                await message.answer(f'Заявка №{x["id"]}',reply_markup=kb)


@router.message(CommandStart())
async def start(m:Message,state:FSMContext):
    if m.chat.type!='private': return
    await state.clear()
    service.ensure_user(m.from_user.id,m.from_user.first_name)
    await m.answer('Добро пожаловать в караоке-кафе-бар «Турист»!\nКараоке, мафия, спортивный покер и бильярд. Подскажу адрес, график, цены и запись — спрашивайте своими словами.',reply_markup=menu())


@router.message(Command('help'))
async def help_cmd(m:Message):
    await m.answer('Команды: /start — меню, /schedule — расписание, /my — заявки, /register — профиль, /ask — вызвать администратора, /id — мой ID. Для сотрудников: /admin, /tickets и /reply.')


@router.message(Command('app'))
async def open_app(m: Message):
    if m.chat.type != 'private':
        return
    if not settings.webapp_url.startswith('https://'):
        await m.answer('Приложение сейчас недоступно. Попробуйте чуть позже или напишите администратору.')
        return
    await m.answer('Откройте приложение клуба по кнопке ниже:', reply_markup=menu())


@router.message(Command('id'))
async def own_id(m:Message):
    if m.chat.type=='private':
        await m.answer(f'Ваш Telegram ID: {m.from_user.id}')


@router.message(Command('register'))
async def register(m:Message,state:FSMContext):
    if m.chat.type!='private': return
    service.ensure_user(m.from_user.id,m.from_user.first_name)
    await state.clear()
    await state.set_state(Registration.name)
    await m.answer('Регистрация в клубе «Турист».\nВведите Ваше имя. Для выхода — /cancel.')


@router.message(Command('cancel'))
async def cancel_registration(m:Message,state:FSMContext):
    await state.clear()
    await m.answer('Действие прервано.',reply_markup=ReplyKeyboardRemove())
    await m.answer('Главное меню:',reply_markup=menu())


@router.message(Registration.name)
async def register_name(m:Message,state:FSMContext):
    name=(m.text or '').strip()
    if not 2<=len(name)<=100:
        await m.answer('Имя должно содержать от 2 до 100 символов. Попробуйте ещё раз.');return
    await state.update_data(full_name=name)
    await state.set_state(Registration.phone)
    kb=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='📱 Поделиться своим номером',request_contact=True)]],resize_keyboard=True,one_time_keyboard=True)
    await m.answer('Теперь отправьте номер телефона (или поделитесь контактом):',reply_markup=kb)


@router.message(Registration.phone)
async def register_phone(m:Message,state:FSMContext):
    if m.contact:
        if m.contact.user_id!=m.from_user.id:
            await m.answer('Можно отправить только собственный контакт.');return
        phone=m.contact.phone_number
    else:
        phone=(m.text or '').strip()
    import re
    normalized=re.sub(r'[\s()\-]','',phone)
    if not re.fullmatch(r'\+?\d{10,15}',normalized):
        await m.answer('Номер должен содержать 10–15 цифр. Например, +79991234567.');return
    await state.update_data(phone=normalized)
    await state.set_state(Registration.nick)
    await m.answer('Придумайте уникальный игровой ник (от 2 до 24 символов):',reply_markup=ReplyKeyboardRemove())


@router.message(Registration.nick)
async def register_nick(m:Message,state:FSMContext):
    nick=(m.text or '').strip()
    data=await state.get_data()
    try:
        service.set_profile(m.from_user.id,data['full_name'],data['phone'],nick)
    except service.BusinessError as exc:
        await m.answer(exc.message+'\nПопробуйте другой игровой ник:');return
    await state.clear()
    await m.answer('✅ Профиль готов! Теперь можно записываться на игры.',reply_markup=menu())


@router.message(Command('schedule'))
async def schedule_cmd(m:Message):
    await show_schedule(m)


@router.message(Command('my'))
async def my_cmd(m:Message):
    await show_mine(m)


async def show_admin(m:Message):
    if m.chat.type!='private': return
    service.ensure_user(m.chat.id)
    try: items=service.list_pending(m.chat.id)
    except service.BusinessError:
        await m.answer('Этот раздел доступен только сотрудникам клуба.'); return
    both=[('event',x) for x in items['events']]+[('billiard',x) for x in items['billiard']]
    if not both: await m.answer('Заявок на рассмотрении нет.'); return
    for cat,x in both[:15]:
        name=x.get('title','Бильярд')
        kb=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='✅ Одобрить',callback_data=f'decide:{cat}:{x["id"]}:1'),
             InlineKeyboardButton(text='❌ Отклонить',callback_data=f'decide:{cat}:{x["id"]}:0')]])
        await m.answer(f"{name} · №{x['id']} · {x['status']}\n{ x.get('full_name','') } · {x.get('phone','')}",reply_markup=kb)


@router.message(Command('admin'))
async def admin_cmd(m:Message):
    await show_admin(m)


@router.message(Command('ask'))
async def ask_admin(m:Message,state:FSMContext):
    if m.chat.type!='private': return
    service.ensure_user(m.from_user.id,m.from_user.first_name)
    await state.set_state(SupportQuestion.text)
    await m.answer('💬 Напишите свой вопрос одним сообщением. Я передам его администратору клуба. Для отмены — /cancel.')


@router.message(SupportQuestion.text)
async def support_question(m:Message,state:FSMContext):
    if m.chat.type!='private': return
    try:
        ticket=service.create_support_ticket(m.from_user.id,m.text or '',f'tg_{m.from_user.id}_{m.message_id}' if getattr(m,'message_id',None) else None)
    except service.BusinessError as exc:
        await m.answer(exc.message+' Попробуйте снова или нажмите /cancel.');return
    await state.clear()
    await m.answer(f'✅ Обращение №{ticket} передано администратору. Ответ придёт прямо в этот чат.',reply_markup=menu())


@router.message(Command('tickets'))
async def tickets_cmd(m:Message):
    if m.chat.type!='private': return
    try:
        tickets=service.list_support_tickets(m.from_user.id)
    except service.BusinessError:
        await m.answer('Обращения доступны только сотрудникам клуба.');return
    if not tickets:
        await m.answer('Новых обращений нет.');return
    for t in tickets[:15]:
        kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f'💬 Ответить №{t["id"]}',callback_data=f'support_reply:{t["id"]}')]])
        await m.answer(f'Обращение №{t["id"]} · {t["status"]}\n{t["question"][:900]}',reply_markup=kb)


@router.message(Command('reply'))
async def reply_cmd(m:Message,state:FSMContext):
    if m.chat.type!='private': return
    try:
        service.check_role(m.from_user.id)
    except service.BusinessError:
        await m.answer('Ответы доступны только администраторам.');return
    import re
    match=re.match(r'^/reply(?:@\w+)?\s+(\d+)(?:\s+([\s\S]+))?$',m.text or '')
    if not match:
        await m.answer('Формат: /reply НОМЕР ответ, например /reply 12 Добрый день!');return
    tid=int(match.group(1));body=match.group(2)
    if not body:
        await state.set_state(SupportReply.text)
        await state.update_data(ticket_id=tid)
        await m.answer(f'Введите ответ на обращение №{tid}. Отмена: /cancel.');return
    try: service.answer_support_ticket(m.from_user.id,tid,body)
    except service.BusinessError as exc: await m.answer(exc.message);return
    await m.answer(f'✅ Ответ по обращению №{tid} сохранён и поставлен в очередь отправки гостю.')


@router.message(SupportReply.text)
async def support_reply_text(m:Message,state:FSMContext):
    tid=(await state.get_data()).get('ticket_id')
    try: service.answer_support_ticket(m.from_user.id,tid,m.text or '')
    except service.BusinessError as exc: await m.answer(exc.message);return
    await state.clear()
    await m.answer('✅ Ответ сохранён и будет доставлен гостю.')


@router.callback_query()
async def callback(q:CallbackQuery, state:FSMContext=None):
    if not q.message or not q.from_user:return
    if q.message.chat.type!='private':
        await q.answer('Доступно только в личном чате');return
    uid=q.from_user.id
    try:
        if q.data=='full':
            await q.answer('Все места зарезервированы',show_alert=True)
        elif q.data=='schedule':
            await q.answer(); await show_schedule(q.message)
        elif q.data=='mine':
            await q.answer(); await show_mine(q.message)
        elif q.data=='admin':
            await q.answer(); await show_admin(q.message)
        elif q.data=='support':
            await q.answer()
            if state:
                service.ensure_user(uid,getattr(q.from_user,'first_name',''))
                await state.set_state(SupportQuestion.text)
                await q.message.answer('💬 Напишите вопрос следующим сообщением. Я передам его администратору. Отмена: /cancel.')
            else:
                await q.message.answer('💬 Чтобы вызвать администратора, нажмите /ask и напишите свой вопрос. Ответ придёт сюда.')
        elif q.data and q.data.startswith('support_reply:'):
            service.check_role(uid)
            ticket_id=int(q.data.split(':',1)[1])
            await q.answer()
            if state:
                await state.set_state(SupportReply.text)
                await state.update_data(ticket_id=ticket_id)
                await q.message.answer(f'Напишите ответ на обращение №{ticket_id} следующим сообщением. Отмена: /cancel.')
            else:
                await q.message.answer(f'Ответьте на обращение №{ticket_id} командой /reply {ticket_id} Ваш ответ')
        elif q.data and q.data.startswith('join:'):
            rid=service.join_event(uid,int(q.data.split(':')[1]))
            await q.answer(f'Заявка №{rid} отправлена администратору',show_alert=True)
        elif q.data and q.data.startswith('cancel:'):
            _,category,req_id=q.data.split(':')
            service.request_cancel(uid,category,int(req_id))
            await q.answer('Запрос отмены передан администратору',show_alert=True)
            await q.message.edit_reply_markup(reply_markup=None)
        elif q.data and q.data.startswith('decide:'):
            _,category,req_id,yes=q.data.split(':')
            result=service.decide(uid,category,int(req_id),yes=='1')
            await q.answer(f"Заявка: {service.STATUS_RU[result['status']]}",show_alert=True)
            await q.message.edit_reply_markup(reply_markup=None)
        else: await q.answer('Неизвестная команда')
    except (ValueError,service.BusinessError) as exc:
        await q.answer(str(exc),show_alert=True)


@router.message()
async def free_text(m:Message):
    if m.chat.type!='private':return
    if not m.text: return
    service.ensure_user(m.from_user.id,m.from_user.first_name)
    response=assistant.answer(m.text,user_id=m.from_user.id)
    if response:
        await m.answer(response,reply_markup=menu());return
    ai_reply=await ai_helper.maybe_answer(m.text)
    if ai_reply:
        await m.answer(ai_reply,reply_markup=menu());return
    # Do not hallucinate answers to arbitrary questions: escalate transparently.
    try:
        tid=service.create_support_ticket(m.from_user.id,m.text,f'tg_{m.from_user.id}_{m.message_id}' if getattr(m,'message_id',None) else None)
    except service.BusinessError as exc:
        await m.answer('Не нашёл точный ответ. '+exc.message+' Используйте /ask.',reply_markup=menu());return
    await m.answer(f'Хочу ответить точно, поэтому передал Ваш вопрос администратору (№{tid}). Он ответит сюда. 💬',reply_markup=menu())


async def polling():
    if not settings.bot_token:
        print('[bot] BOT_TOKEN не задан: Telegram polling выключен.',flush=True)
        return
    initialize_storage()
    from app.telegram_transport import build_aiogram_session
    bot=Bot(settings.bot_token, session=build_aiogram_session())
    dp=Dispatcher()
    dp.include_router(router)
    try:
        await bot.set_my_commands([BotCommand(command='start',description='Главное меню'),
                                  BotCommand(command='schedule',description='Расписание'),
                                  BotCommand(command='my',description='Мои заявки'),
                                  BotCommand(command='app',description='Открыть Mini App'),
                                  BotCommand(command='register',description='Регистрация'),
                                  BotCommand(command='id',description='Мой Telegram ID'),
                                  BotCommand(command='ask',description='Вызвать администратора'),
                                  BotCommand(command='tickets',description='Обращения для сотрудников'),
                                  BotCommand(command='reply',description='Ответить на обращение'),
                                  BotCommand(command='admin',description='Заявки для сотрудников'),
                                  BotCommand(command='cancel',description='Прервать ввод')])
        if settings.webapp_url.startswith('https://'):
            await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text='Турист',web_app=WebAppInfo(url=settings.webapp_url)))
        else:
            # A previous temporary tunnel URL must not remain attached to bot menu.
            await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        await dp.start_polling(bot,handle_signals=False)
    finally:
        await bot.session.close()
