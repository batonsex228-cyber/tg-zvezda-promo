"""Club business rules used by both Telegram bot and Web API."""
import json
import hashlib
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from app.config import settings
from app.database import session, utcnow, log, mark_dirty

ACTIVE = ('pending', 'confirmed', 'cancel_requested')
STATUS_RU = {'pending':'ожидает подтверждения','confirmed':'подтверждена','rejected':'отклонена',
             'cancel_requested':'ожидает отмены','cancelled':'отменена'}

class BusinessError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status
        super().__init__(message)


def plain(row):
    return dict(row) if row is not None else None


def when(value: str, future=True) -> str:
    try:
        d = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if d.tzinfo is None:
            d = d.replace(tzinfo=ZoneInfo(settings.club_timezone))
        d = d.astimezone(timezone.utc)
    except (ValueError, TypeError, KeyError) as e:
        raise BusinessError('Неверная дата или время') from e
    if future and d <= datetime.now(timezone.utc):
        raise BusinessError('Выберите будущее время')
    return d.isoformat(timespec='seconds')


def ensure_user(tgid: int, first_name=''):
    """Create/refresh a Telegram user without generating unnecessary Sheets syncs.

    Any new user or actual change to first_name/owner role MUST increment the
    Google mirror revision. This also matters if a new user joins *during* the
    first snapshot export. Merely fetching /api/me must not increment it.
    """
    now = utcnow()
    first_name = first_name[:100] if isinstance(first_name, str) else ''
    expected_owner = bool(settings.owner_telegram_id and tgid == settings.owner_telegram_id)
    with session(write=True) as c:
        changed = False
        # Enforce a single owner even after updating OWNER_TELEGRAM_ID.
        demoted = c.execute("UPDATE users SET role='guest', updated_at=? "
                            "WHERE role='owner' AND telegram_id!=?",
                            (now, settings.owner_telegram_id))
        changed = demoted.rowcount > 0
        old = c.execute('SELECT * FROM users WHERE telegram_id=?', (tgid,)).fetchone()
        if old is None:
            c.execute('INSERT INTO users(telegram_id,first_name,role,created_at,updated_at) '
                      'VALUES (?,?,?,?,?)',
                      (tgid, first_name, 'owner' if expected_owner else 'guest', now, now))
            changed = True
        else:
            changes = {}
            if expected_owner and old['role'] != 'owner':
                changes['role'] = 'owner'
            if first_name and old['first_name'] != first_name:
                changes['first_name'] = first_name
            if changes:
                columns = ', '.join(f'{field}=?' for field in changes)
                c.execute(f'UPDATE users SET {columns},updated_at=? WHERE telegram_id=?',
                          (*changes.values(), now, tgid))
                changed = True
        # Always advance revision, even before the first Sheets export. If a
        # user arrives during an export, the next export must include them.
        if changed:
            mark_dirty(c)
        return plain(c.execute('SELECT * FROM users WHERE telegram_id=?', (tgid,)).fetchone())


def get_user(tgid):
    with session() as c:
        return plain(c.execute('SELECT * FROM users WHERE telegram_id=?', (tgid,)).fetchone())


def profile_ready(user):
    return bool(user and user['full_name'] and user['phone'] and user['nickname'])


def set_profile(tgid, full_name, phone, nickname):
    full_name = full_name.strip()
    phone = re.sub(r'[\s()\-]', '', phone.strip())
    nickname = nickname.strip()
    if not (2 <= len(full_name) <= 100):
        raise BusinessError('Имя: от 2 до 100 символов')
    if not re.fullmatch(r'\+?\d{10,15}', phone):
        raise BusinessError('Укажите телефон в формате +79991234567')
    if not re.fullmatch(r'[\w\- ]{2,24}', nickname, flags=re.UNICODE):
        raise BusinessError('Ник: 2–24 символа, буквы, цифры, пробел или дефис')
    nick_key = nickname.casefold()
    with session(write=True) as c:
        try:
            c.execute('UPDATE users SET full_name=?,phone=?,nickname=?,nickname_key=?,updated_at=? WHERE telegram_id=?',
                      (full_name, phone, nickname, nick_key, utcnow(), tgid))
        except sqlite3.IntegrityError as e:
            raise BusinessError('Этот игровой ник уже занят', 409) from e
        u = c.execute('SELECT * FROM users WHERE telegram_id=?', (tgid,)).fetchone()
        if u is None:
            raise BusinessError('Пользователь не найден', 404)
        log(c,tgid,'profile.updated','user',tgid)
    return plain(u)


def list_events():
    with session() as c:
        rows=c.execute("""SELECT e.id,e.kind,e.title,e.format,e.starts_at,e.capacity,e.min_players,e.stack,e.blinds,e.status, (SELECT COUNT(*) FROM applications a WHERE a.event_id=e.id AND a.status IN ('pending','confirmed','cancel_requested')) AS occupied,
        (SELECT COUNT(*) FROM applications a WHERE a.event_id=e.id AND a.status='confirmed') AS confirmed
        FROM events e WHERE e.starts_at>=? AND e.status!='cancelled' AND (e.is_demo=0 OR ?=1)
        ORDER BY e.starts_at ASC""", (utcnow(), 1 if settings.showcase_mode else 0)).fetchall()
        return [plain(x) for x in rows]


def validate_event(kind, title, start, capacity, format='', min_players=1, stack='', blinds=''):
    if kind not in ('mafia', 'poker'):
        raise BusinessError('Неизвестный тип события')
    title = title.strip()
    if not (3 <= len(title) <= 120):
        raise BusinessError('Укажите название события')
    if type(capacity) is not int or type(min_players) is not int or not 1 <= capacity <= 100 or not 1 <= min_players <= capacity:
        raise BusinessError('Некорректный лимит игроков')
    start_utc = when(start)
    if kind == 'mafia':
        if format not in ('classic', 'city'):
            raise BusinessError('Для мафии выберите classic или city')
        day = datetime.fromisoformat(start_utc).astimezone(ZoneInfo(settings.club_timezone)).weekday()
        if format == 'classic' and (day != 3 or capacity > 10):
            raise BusinessError('Классическая мафия: четверг, не более 10 игроков')
        if format == 'city' and (day != 6 or not 10 <= min_players <= capacity <= 15):
            raise BusinessError('Городская мафия: воскресенье, от 10 до 15 игроков')
    if kind == 'poker' and (capacity > 10 or not stack.strip() or not blinds.strip()):
        raise BusinessError('Покер: не более 10 игроков; укажите стек и блайнды')
    return title, start_utc


def bot_key():
    # Prevent a new client's bot from sending messages queued for a previous token.
    return hashlib.sha256(settings.bot_token.encode('utf-8')).hexdigest()[:24] if settings.bot_token else 'no-bot'


def retry_fingerprint(data) -> str:
    """Canonical payload digest; stores no credentials and scopes retries to one payload."""
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def prior_request(c, tgid, operation, key, fingerprint):
    """Check a client-supplied retry key *inside* the booking write transaction.

    A key can be used only with its original payload and user. Old keys expire
    after 48 hours to avoid unbounded database growth.
    """
    if key is None:
        return None
    if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}', key):
        raise BusinessError('Неверный ключ повторного запроса')
    cutoff=(datetime.now(timezone.utc)-timedelta(hours=48)).isoformat(timespec='seconds')
    c.execute('DELETE FROM idempotency_keys WHERE created_at<?', (cutoff,))
    row=c.execute('SELECT fingerprint,result_id FROM idempotency_keys WHERE telegram_id=? AND operation=? AND request_key=?',
                  (tgid,operation,key)).fetchone()
    if not row:
        return None
    if row['fingerprint'] != fingerprint:
        raise BusinessError('Повторный запрос изменён. Повторите действие заново.', 409)
    return row['result_id']


def remember_request(c, tgid, operation, key, fingerprint, result_id):
    if key is not None:
        c.execute('INSERT INTO idempotency_keys (telegram_id,operation,request_key,fingerprint,result_id,created_at) VALUES (?,?,?,?,?,?)',
                  (tgid,operation,key,fingerprint,result_id,utcnow()))


def enqueue(c, recipient, message, *, send_at=None, purpose='system', entity_type=None, entity_id=None):
    now = utcnow()
    c.execute("""INSERT INTO notification_outbox
             (bot_key,telegram_id,message,state,next_attempt_at,created_at,purpose,entity_type,entity_id)
             VALUES (?,?,?,'pending',?,?,?,?,?)""",
              (bot_key(), recipient, message[:4000], send_at or now, now, purpose, entity_type, entity_id))


def cancel_reminder(c, category, request_id):
    """Do not send stale, unsent reminders for changed or cancelled reservations."""
    c.execute("""DELETE FROM notification_outbox
           WHERE purpose='reminder' AND entity_type=? AND entity_id=? AND state='pending'""",
              (category, request_id))


def schedule_reminder(c, category, request_id, recipient, starts_at, label):
    cancel_reminder(c, category, request_id)
    lead = settings.reminder_hours_before
    if not (1 <= lead <= 168):
        return
    start = datetime.fromisoformat(starts_at)
    send_at = start - timedelta(hours=lead)
    if send_at <= datetime.now(timezone.utc) or start <= datetime.now(timezone.utc):
        return  # Don't send an immediate surprise reminder for a last-minute booking.
    local = start.astimezone(ZoneInfo(settings.club_timezone)).strftime('%d.%m.%Y в %H:%M')
    enqueue(c, recipient, f'Турист: напоминаем, что {label} состоится {local}. Ждём Вас!',
            send_at=send_at.isoformat(timespec='seconds'), purpose='reminder',
            entity_type=category, entity_id=request_id)



def enqueue_admins(c, message):
    admins = c.execute("SELECT telegram_id,role FROM users WHERE role IN ('owner','senior','admin')").fetchall()
    for admin in admins:
        if admin['role'] != 'owner' or admin['telegram_id'] == settings.owner_telegram_id:
            enqueue(c, admin['telegram_id'], message)


def create_event(actor, kind, title, start, capacity, format='', min_players=1, stack='', blinds=''):
    check_role(actor, ('owner','senior'))
    title, start = validate_event(kind, title, start, capacity, format, min_players, stack, blinds)
    with session(write=True) as c:
        cur=c.execute('INSERT INTO events(kind,title,format,starts_at,capacity,min_players,stack,blinds,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                      (kind,title,format,start,capacity,min_players,stack,blinds,actor,utcnow()))
        eid=cur.lastrowid
        log(c,actor,'event.created','event',eid)
        return plain(c.execute('SELECT * FROM events WHERE id=?',(eid,)).fetchone())


def admin_events(actor, limit=100):
    check_role(actor)
    with session() as c:
        return [dict(r) for r in c.execute("""SELECT e.*,
            (SELECT COUNT(*) FROM applications a WHERE a.event_id=e.id AND a.status IN ('pending','confirmed','cancel_requested')) AS occupied,
            (SELECT COUNT(*) FROM applications a WHERE a.event_id=e.id AND a.status='confirmed') AS confirmed
            FROM events e ORDER BY e.starts_at DESC LIMIT ?""", (max(1, min(limit, 200)),))]


def edit_event(actor, event_id, kind, title, start, capacity, format='', min_players=1, stack='', blinds='', status='open'):
    check_role(actor, ('owner', 'senior'))
    if status not in ('open', 'closed', 'cancelled'):
        raise BusinessError('Недопустимый статус события')
    # Validate before transaction; the transaction re-checks current state / occupancy.
    title, start = validate_event(kind, title, start, capacity, format, min_players, stack, blinds)
    with session(write=True) as c:
        existing = c.execute('SELECT * FROM events WHERE id=?', (event_id,)).fetchone()
        if not existing:
            raise BusinessError('Мероприятие не найдено', 404)
        if existing['status'] == 'cancelled':
            raise BusinessError('Отменённое мероприятие нельзя возобновлять или редактировать', 409)
        occupied = c.execute("SELECT COUNT(*) FROM applications WHERE event_id=? AND status IN ('pending','confirmed','cancel_requested')", (event_id,)).fetchone()[0]
        if occupied and kind != existing['kind'] and status != 'cancelled':
            raise BusinessError('Нельзя менять вид игры, когда есть заявки', 409)
        if capacity < occupied and status != 'cancelled':
            raise BusinessError(f'Нельзя установить лимит меньше текущих {occupied} занятых мест', 409)
        if status == 'cancelled':
            active_rows = list(c.execute("SELECT id,telegram_id FROM applications WHERE event_id=? AND status IN ('pending','confirmed','cancel_requested')", (event_id,)))
            recipients = [r['telegram_id'] for r in active_rows]
            for r in active_rows:
                cancel_reminder(c, 'event', r['id'])
            c.execute("UPDATE applications SET status='cancelled',updated_at=? WHERE event_id=? AND status IN ('pending','confirmed','cancel_requested')", (utcnow(),event_id))
            for user_id in recipients:
                enqueue(c, user_id, f'Турист: мероприятие «{existing["title"]}» отменено. Ваша заявка отменена.')
        else:
            recipients = [r['telegram_id'] for r in c.execute("SELECT telegram_id FROM applications WHERE event_id=? AND status IN ('pending','confirmed','cancel_requested')", (event_id,))]
            if (start != existing['starts_at'] or title != existing['title']):
                for user_id in recipients:
                    enqueue(c, user_id, f'Турист: информация о мероприятии «{title}» изменилась. Проверьте дату и время в приложении.')
                for row in c.execute("SELECT id,telegram_id FROM applications WHERE event_id=? AND status='confirmed'", (event_id,)).fetchall():
                    schedule_reminder(c, 'event', row['id'], row['telegram_id'], start, f'игра «{title}»')
        c.execute("""UPDATE events SET kind=?,title=?,starts_at=?,capacity=?,format=?,min_players=?,stack=?,blinds=?,status=? WHERE id=?""",
                  (kind,title,start,capacity,format,min_players,stack,blinds,status,event_id))
        log(c,actor,'event.updated','event',event_id,json.dumps({'status':status,'capacity':capacity},ensure_ascii=False))
        return dict(c.execute('SELECT * FROM events WHERE id=?', (event_id,)).fetchone())


def search_users(actor, q='', limit=40):
    check_role(actor)
    q = q.strip()[:80]
    with session() as c:
        if not q:
            rows = c.execute('SELECT telegram_id,first_name,full_name,phone,nickname,role,created_at FROM users ORDER BY updated_at DESC LIMIT ?', (limit,))
        else:
            pattern = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            rows = c.execute("""SELECT telegram_id,first_name,full_name,phone,nickname,role,created_at FROM users
                WHERE CAST(telegram_id AS TEXT) LIKE ? ESCAPE '\\' OR full_name LIKE ? ESCAPE '\\'
                  OR nickname LIKE ? ESCAPE '\\' OR phone LIKE ? ESCAPE '\\'
                ORDER BY updated_at DESC LIMIT ?""",(pattern,pattern,pattern,pattern,limit))
        return [dict(r) for r in rows]


def audit_feed(actor, limit=60):
    check_role(actor, ('owner','senior'))
    with session() as c:
        return [dict(r) for r in c.execute('SELECT * FROM audit ORDER BY id DESC LIMIT ?', (max(1,min(100,limit)),))]


def billiard_busy(date):
    try:
        day = datetime.strptime(date, '%Y-%m-%d').replace(tzinfo=ZoneInfo(settings.club_timezone))
    except (TypeError,ValueError):
        raise BusinessError('Неверная дата, ожидается ГГГГ-ММ-ДД')
    start = day.astimezone(timezone.utc)
    end = (day + timedelta(days=1)).astimezone(timezone.utc)
    if day.date() < datetime.now(ZoneInfo(settings.club_timezone)).date() or day.date() > (datetime.now(ZoneInfo(settings.club_timezone))+timedelta(days=7)).date():
        raise BusinessError('Выберите дату в пределах ближайших 7 дней', 409)
    with session() as c:
        rows = c.execute("""SELECT starts_at, ends_at FROM billiard_bookings
           WHERE status IN ('pending','confirmed','cancel_requested') AND starts_at < ? AND ends_at > ?
           ORDER BY starts_at""", (end.isoformat(timespec='seconds'),start.isoformat(timespec='seconds'))).fetchall()
    return [dict(r) for r in rows]


def event_members(event_id):
    with session() as c:
        return [dict(r) for r in c.execute("SELECT nickname_snapshot FROM applications WHERE event_id=? AND status='confirmed' ORDER BY created_at,id",(event_id,))]


def join_event(tgid,event_id,request_key=None):
    with session(write=True) as c:
        fingerprint=retry_fingerprint({'event_id':event_id})
        prior=prior_request(c,tgid,'event.join',request_key,fingerprint)
        if prior is not None:
            return prior
        u=c.execute('SELECT * FROM users WHERE telegram_id=?',(tgid,)).fetchone()
        if not profile_ready(u):
            raise BusinessError('Сначала заполните профиль', 409)
        e=c.execute('SELECT * FROM events WHERE id=?',(event_id,)).fetchone()
        if not e or e['status']!='open' or e['starts_at']<=utcnow():
            raise BusinessError('Запись закрыта',409)
        prev=c.execute('SELECT * FROM applications WHERE event_id=? AND telegram_id=?',(event_id,tgid)).fetchone()
        if prev and prev['status'] in ACTIVE:
            raise BusinessError('Вы уже записались на это событие',409)
        occupied=c.execute("SELECT COUNT(*) FROM applications WHERE event_id=? AND status IN ('pending','confirmed','cancel_requested')", (event_id,)).fetchone()[0]
        if occupied>=e['capacity']:
            raise BusinessError('Свободных мест пока нет',409)
        now=utcnow()
        if prev:
            c.execute('UPDATE applications SET nickname_snapshot=?,status=?,created_at=?,updated_at=? WHERE id=?',
                      (u['nickname'],'pending',now,now,prev['id']))
            rid=prev['id']
        else:
            rid=c.execute('INSERT INTO applications(event_id,telegram_id,nickname_snapshot,status,created_at,updated_at) VALUES (?,?,?,"pending",?,?)',
                          (event_id,tgid,u['nickname'],now,now)).lastrowid
        log(c,tgid,'application.requested','application',rid)
        remember_request(c,tgid,'event.join',request_key,fingerprint,rid)
        enqueue_admins(c, f'Турист: новая заявка на игру №{rid}. Откройте /admin')
        return rid


def request_cancel(tgid,category,request_id):
    table = 'applications' if category=='event' else 'billiard_bookings' if category=='billiard' else None
    if table is None:
        raise BusinessError('Неизвестный тип заявки')
    with session(write=True) as c:
        a=c.execute(f'SELECT * FROM {table} WHERE id=? AND telegram_id=?',(request_id,tgid)).fetchone()
        if not a:
            raise BusinessError('Заявка не найдена',404)
        # A retry after a lost HTTP response is not a second cancellation.
        # Keep the original decision state, audit log and notification intact.
        if a['status'] == 'cancel_requested':
            return True
        if a['status'] not in ('pending','confirmed'):
            raise BusinessError('Эту заявку нельзя отменить',409)
        c.execute(f'UPDATE {table} SET status="cancel_requested",cancel_origin=?,updated_at=? WHERE id=?', (a['status'],utcnow(),request_id))
        cancel_reminder(c, category, request_id)
        log(c,tgid,'cancel.requested',category,request_id)
        enqueue_admins(c, f'Турист: запрос отмены {category} №{request_id}. Откройте /admin')
        return True


def billiard_book(tgid,start,hours,guest_count,request_key=None):
    if type(hours) is not int or not 1<=hours<=4:
        raise BusinessError('Бронирование: от 1 до 4 часов')
    if type(guest_count) is not int or not 1<=guest_count<=30:
        raise BusinessError('Некорректное число гостей')
    d=datetime.fromisoformat(when(start))
    if d>datetime.now(timezone.utc)+timedelta(days=7):
        raise BusinessError('Бильярд можно забронировать максимум за 7 дней',409)
    end=(d+timedelta(hours=hours)).isoformat(timespec='seconds')
    with session(write=True) as c:
        fingerprint=retry_fingerprint({'starts_at':d.isoformat(timespec='seconds'),'hours':hours,'guest_count':guest_count})
        prior=prior_request(c,tgid,'billiard.book',request_key,fingerprint)
        if prior is not None:
            return prior
        u=c.execute('SELECT * FROM users WHERE telegram_id=?',(tgid,)).fetchone()
        if not profile_ready(u):
            raise BusinessError('Сначала заполните профиль',409)
        conflicts=c.execute("""SELECT COUNT(*) FROM billiard_bookings WHERE status IN ('pending','confirmed','cancel_requested')
          AND starts_at < ? AND ends_at > ?""",(end,d.isoformat(timespec='seconds'))).fetchone()[0]
        if conflicts:
            raise BusinessError('Стол уже занят или ожидает подтверждения в это время',409)
        now=utcnow()
        bid=c.execute('INSERT INTO billiard_bookings(telegram_id,starts_at,ends_at,guest_count,status,created_at,updated_at) VALUES (?,?,?,? ,"pending",?,?)',
                    (tgid,d.isoformat(timespec='seconds'),end,guest_count,now,now)).lastrowid
        log(c,tgid,'billiard.requested','billiard',bid)
        remember_request(c,tgid,'billiard.book',request_key,fingerprint,bid)
        enqueue_admins(c, f'Турист: новая заявка на бильярд №{bid}. Откройте /admin')
        return bid


def request_status(tgid, category, request_id):
    """Return actual persisted state, including results of idempotent retries.

    The old API replied 'pending' even if an admin confirmed the reservation
    before a network retry completed.
    """
    table = {'event':'applications','billiard':'billiard_bookings'}.get(category)
    if table is None:
        raise BusinessError('Неизвестный тип заявки')
    with session() as c:
        row = c.execute(f'SELECT status FROM {table} WHERE id=? AND telegram_id=?',
                        (request_id, tgid)).fetchone()
        if row is None:
            raise BusinessError('Заявка не найдена', 404)
        return row['status']


def my_requests(tgid):
    with session() as c:
        ev=[dict(r) for r in c.execute('''SELECT a.id,a.event_id,a.status,a.nickname_snapshot,e.title,e.kind,e.starts_at
            FROM applications a JOIN events e ON e.id=a.event_id WHERE a.telegram_id=? ORDER BY a.created_at DESC''',(tgid,))]
        bil=[dict(r) for r in c.execute('''SELECT id,status,starts_at,ends_at,guest_count FROM billiard_bookings
            WHERE telegram_id=? ORDER BY created_at DESC''',(tgid,))]
        return {'events':ev,'billiard':bil}


def check_role(tgid,allowed=('admin','senior','owner')):
    u=get_user(tgid)
    if not u or u['role'] not in allowed or (u['role']=='owner' and tgid!=settings.owner_telegram_id):
        raise BusinessError('Недостаточно прав',403)
    return u


def admin_ids():
    with session() as c:
        rows=c.execute("SELECT telegram_id,role FROM users WHERE role IN ('owner','senior','admin')").fetchall()
        return [r['telegram_id'] for r in rows if r['role']!='owner' or r['telegram_id']==settings.owner_telegram_id]


def list_pending(actor):
    check_role(actor)
    with session() as c:
        ev=[dict(x) for x in c.execute('''SELECT a.*,e.title,u.full_name,u.phone
            FROM applications a JOIN events e ON e.id=a.event_id JOIN users u ON u.telegram_id=a.telegram_id
            WHERE a.status IN ('pending','cancel_requested') ORDER BY a.created_at DESC''')]
        bil=[dict(x) for x in c.execute('''SELECT b.*,u.full_name,u.nickname,u.phone FROM billiard_bookings b
            JOIN users u ON b.telegram_id=u.telegram_id WHERE b.status IN ('pending','cancel_requested') ORDER BY b.created_at DESC''')]
        return {'events':ev,'billiard':bil}


def decide(actor,category,request_id,approve):
    check_role(actor)
    table = 'applications' if category=='event' else 'billiard_bookings' if category=='billiard' else None
    if table is None:
        raise BusinessError('Неизвестный тип заявки')
    with session(write=True) as c:
        r=c.execute(f'SELECT * FROM {table} WHERE id=?',(request_id,)).fetchone()
        if not r or r['status'] not in ('pending','cancel_requested'):
            raise BusinessError('Заявка уже обработана',409)
        if r['status']=='pending':
            if approve:
                if category == 'event':
                    event = c.execute('SELECT starts_at,status FROM events WHERE id=?', (r['event_id'],)).fetchone()
                    if not event or event['status']=='cancelled' or event['starts_at']<=utcnow():
                        raise BusinessError('Нельзя подтвердить заявку на прошедшее или отменённое мероприятие',409)
                elif r['starts_at']<=utcnow():
                    raise BusinessError('Нельзя подтвердить бронь на прошедшее время',409)
            status='confirmed' if approve else 'rejected'
        else:
            # Rejection must restore the actual pre-cancellation status, including
            # pending applications that were never approved by an administrator.
            status='cancelled' if approve else (r['cancel_origin'] or 'confirmed')
        # Pending application consumed a reserved slot; approving cannot overbook.
        c.execute(f'UPDATE {table} SET status=?,cancel_origin=NULL,updated_at=? WHERE id=?',(status,utcnow(),request_id))
        if status == 'confirmed':
            if category == 'event':
                e = c.execute('SELECT title,starts_at FROM events WHERE id=?', (r['event_id'],)).fetchone()
                if e:
                    schedule_reminder(c, 'event', request_id, r['telegram_id'], e['starts_at'], f'игра «{e["title"]}»')
            else:
                schedule_reminder(c, 'billiard', request_id, r['telegram_id'], r['starts_at'], 'бронь бильярда')
        else:
            cancel_reminder(c, category, request_id)
        log(c,actor,'request.decided',category,request_id,json.dumps({'result':status},ensure_ascii=False))
        enqueue(c, r['telegram_id'], f'Турист: статус заявки №{request_id} — {STATUS_RU[status]}.')
        return {'telegram_id':r['telegram_id'],'status':status,'id':request_id,'category':category}


def set_role(actor,target,new_role):
    check_role(actor,('owner','senior'))
    if new_role not in ('guest','admin','senior'):
        raise BusinessError('Недопустимая роль')
    with session(write=True) as c:
        acting=c.execute('SELECT role FROM users WHERE telegram_id=?',(actor,)).fetchone()['role']
        current=c.execute('SELECT role FROM users WHERE telegram_id=?',(target,)).fetchone()
        if not current:
            raise BusinessError('Гость сначала должен запустить бота',404)
        if current['role']=='owner' or (acting!='owner' and (current['role']=='senior' or new_role=='senior')):
            raise BusinessError('Эту роль может изменять только владелец',403)
        c.execute('UPDATE users SET role=?,updated_at=? WHERE telegram_id=?',(new_role,utcnow(),target))
        log(c,actor,'role.changed','user',target,json.dumps({'role':new_role}))
    return {'telegram_id':target,'role':new_role}


def admin_dashboard(actor):
    """Consistent cross-channel metrics for the Mini App administrator overview."""
    check_role(actor)
    now = utcnow()
    with session() as c:
        counts = {
            'guests': c.execute("SELECT COUNT(*) FROM users WHERE role='guest'").fetchone()[0],
            'upcoming_events': c.execute("SELECT COUNT(*) FROM events WHERE starts_at>=? AND status!='cancelled'", (now,)).fetchone()[0],
            'open_events': c.execute("SELECT COUNT(*) FROM events WHERE starts_at>=? AND status='open'", (now,)).fetchone()[0],
            'event_requests': c.execute("SELECT COUNT(*) FROM applications WHERE status IN ('pending','cancel_requested')").fetchone()[0],
            'billiard_requests': c.execute("SELECT COUNT(*) FROM billiard_bookings WHERE status IN ('pending','cancel_requested')").fetchone()[0],
            'confirmed_events': c.execute("SELECT COUNT(*) FROM applications WHERE status='confirmed'").fetchone()[0],
            'confirmed_billiard': c.execute("SELECT COUNT(*) FROM billiard_bookings WHERE status='confirmed' AND starts_at>=?", (now,)).fetchone()[0],
        }
        counts['pending_total'] = counts['event_requests'] + counts['billiard_requests']
        return counts


# -------- Showcase data, never presented as real client events --------
def ensure_showcase_schedule():
    """Make three illustrative upcoming events in a fresh showcase database.

    Safe on repeated starts: write transaction and no duplicates. Real club events
    take precedence; once a real event exists, stop generating example entries.
    """
    if not settings.showcase_mode:
        return 0
    zone = ZoneInfo(settings.club_timezone)
    now = datetime.now(zone)
    def next_weekday(weekday, hour):
        delta = (weekday - now.weekday()) % 7
        target = (now + timedelta(days=delta)).replace(hour=hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=7)
        return target.astimezone(timezone.utc).isoformat(timespec='seconds')
    items = [
        ('mafia', 'Мафия · Классический вечер', 'classic', next_weekday(3,19), 10, 1, '', ''),
        ('poker', 'Спортивный покер · Турнир', '', next_weekday(5,18), 10, 1, '10 000', '100/200'),
        ('mafia', 'Городская мафия · Большая игра', 'city', next_weekday(6,18), 15, 10, '', ''),
    ]
    created = 0
    with session(write=True) as c:
        # Safely rename only internally marked fixture events created by older versions.
        # Keep IDs, registrations, statuses and audit records intact for existing users.
        old_titles = {
            'ДЕМО · Мафия · Классический вечер': 'Мафия · Классический вечер',
            'ДЕМО · Спортивный покер · Турнир': 'Спортивный покер · Турнир',
            'ДЕМО · Городская мафия · Большая игра': 'Городская мафия · Большая игра',
        }
        renamed = 0
        for old_title, new_title in old_titles.items():
            updated = c.execute('UPDATE events SET title=? WHERE is_demo=1 AND title=?',
                                (new_title, old_title)).rowcount
            renamed += updated
        if renamed:
            mark_dirty(c)
        # Never mix fictional fixtures into a client's real calendar.
        if c.execute('SELECT 1 FROM events WHERE is_demo=0 LIMIT 1').fetchone():
            return 0
        for kind, title, fmt, start, cap, minimum, stack, blinds in items:
            old = c.execute("SELECT 1 FROM events WHERE is_demo=1 AND kind=? AND starts_at=? AND status!='cancelled'", (kind,start)).fetchone()
            if old:
                continue
            c.execute("""INSERT INTO events(kind,title,format,starts_at,capacity,min_players,stack,blinds,status,created_by,created_at,is_demo)
                         VALUES (?,?,?,?,?,?,?,?,'open',NULL,?,1)""",
                      (kind,title,fmt,start,cap,minimum,stack,blinds,utcnow()))
            created += 1
        if created:
            mark_dirty(c)
    return created


# -------- Guest ↔ administrator conversations --------
def create_support_ticket(tgid: int, question: str, request_key: str | None = None) -> int:
    text = question.strip()
    if not 5 <= len(text) <= 1500:
        raise BusinessError('Напишите вопрос длиной от 5 до 1500 символов')
    fingerprint = retry_fingerprint({'text':text})
    with session(write=True) as c:
        old = prior_request(c,tgid,'support.create',request_key,fingerprint)
        if old is not None:
            return old
        if not c.execute('SELECT 1 FROM users WHERE telegram_id=?', (tgid,)).fetchone():
            raise BusinessError('Откройте /start перед обращением к администратору')
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec='seconds')
        count = c.execute('SELECT COUNT(*) FROM support_tickets WHERE telegram_id=? AND created_at>=?', (tgid,cutoff)).fetchone()[0]
        if count >= 5:
            raise BusinessError('Слишком много новых обращений. Попробуйте позднее.', 429)
        now = utcnow()
        tid = c.execute("INSERT INTO support_tickets (telegram_id,status,created_at,updated_at) VALUES (?,'open',?,?)", (tgid,now,now)).lastrowid
        c.execute("INSERT INTO support_messages(ticket_id,sender_id,sender_role,body,created_at) VALUES (?,?,'guest',?,?)", (tid,tgid,text,now))
        # Never include guest telephone or other private profile fields in alerts.
        enqueue_admins(c, f'💬 Новое обращение №{tid} от пользователя {tgid}\n{text[:900]}\nОтветьте командой /reply {tid} текст ответа или откройте админ-панель.')
        log(c,tgid,'support.opened','support',tid)
        remember_request(c,tgid,'support.create',request_key,fingerprint,tid)
        return tid


def list_support_tickets(actor, limit=50):
    check_role(actor)
    with session() as c:
        return [dict(r) for r in c.execute("""SELECT t.id,t.telegram_id,t.status,t.created_at,t.updated_at,
            (SELECT body FROM support_messages WHERE ticket_id=t.id ORDER BY id ASC LIMIT 1) AS question,
            (SELECT body FROM support_messages WHERE ticket_id=t.id ORDER BY id DESC LIMIT 1) AS last_message
            FROM support_tickets t ORDER BY CASE WHEN t.status='open' THEN 0 ELSE 1 END, t.updated_at DESC LIMIT ?""", (min(100,max(1,limit)),))]


def my_support_tickets(tgid, limit=25):
    with session() as c:
        return [dict(r) for r in c.execute("""SELECT t.id,t.status,t.created_at,t.updated_at,
            (SELECT body FROM support_messages WHERE ticket_id=t.id ORDER BY id ASC LIMIT 1) AS question,
            (SELECT body FROM support_messages WHERE ticket_id=t.id AND sender_role='staff' ORDER BY id DESC LIMIT 1) AS answer
            FROM support_tickets t WHERE t.telegram_id=? ORDER BY t.updated_at DESC LIMIT ?""", (tgid,limit))]


def answer_support_ticket(actor, ticket_id, answer):
    check_role(actor)
    text = answer.strip()
    if not 2 <= len(text) <= 2000:
        raise BusinessError('Ответ должен содержать от 2 до 2000 символов')
    with session(write=True) as c:
        t = c.execute('SELECT * FROM support_tickets WHERE id=?', (ticket_id,)).fetchone()
        if not t:
            raise BusinessError('Обращение не найдено',404)
        if t['status']=='closed':
            raise BusinessError('Обращение закрыто',409)
        now=utcnow()
        c.execute("INSERT INTO support_messages(ticket_id,sender_id,sender_role,body,created_at) VALUES (?,?,'staff',?,?)", (ticket_id,actor,text,now))
        c.execute("UPDATE support_tickets SET status='answered',updated_at=? WHERE id=?",(now,ticket_id))
        enqueue(c,t['telegram_id'],f'💬 Ответ администратора на обращение №{ticket_id}:\n{text}')
        log(c,actor,'support.answered','support',ticket_id)
        return {'id':ticket_id,'status':'answered','telegram_id':t['telegram_id']}
