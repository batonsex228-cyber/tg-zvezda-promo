"""Optional Google Sheets mirror; database remains the source of truth.

Uses a revision cursor so retries do not lose updates. The Google spreadsheet must be
shared with the service account's email. Calls run in a worker thread.
"""
import asyncio
from pathlib import Path
from app.config import settings, ROOT
from app.database import session, utcnow

TABS = {
  'Гости': ('SELECT telegram_id,full_name,phone,nickname,role,created_at FROM users ORDER BY created_at',
           ['Telegram ID','Имя','Телефон','Игровой ник','Роль','Создан']),
  'События': ('SELECT id,kind,title,format,starts_at,capacity,min_players,stack,blinds,status FROM events ORDER BY starts_at',
             ['ID','Направление','Название','Формат','Начало UTC','Лимит','Минимум','Стек','Блайнды','Статус']),
  'Заявки': ('SELECT id,event_id,telegram_id,nickname_snapshot,status,created_at,updated_at FROM applications ORDER BY id',
             ['ID','Событие ID','Telegram ID','Ник на момент игры','Статус','Создана','Обновлена']),
  'Бильярд': ('SELECT id,telegram_id,starts_at,ends_at,guest_count,status,created_at FROM billiard_bookings ORDER BY id',
             ['ID','Telegram ID','Начало UTC','Конец UTC','Гостей','Статус','Создана']),
  'История': ('SELECT id,actor_id,action,entity_type,entity_id,details,created_at FROM audit ORDER BY id',
             ['ID','Автор','Действие','Тип','Объект ID','Детали','Время UTC']),
}


def enabled():
    return bool(settings.google_sheet_id and settings.google_credentials_file)


def credentials_path():
    if not settings.google_credentials_file:
        return None
    path=Path(settings.google_credentials_file).expanduser()
    return (path if path.is_absolute() else ROOT/path).resolve()


def sync_once(force=False):
    if not enabled():
        return 'not-configured'
    with session() as c:
        job=c.execute('SELECT revision,synced_revision,synced_once,last_error FROM sync_jobs WHERE id=1').fetchone()
        if not force and job['synced_once'] and not job['last_error'] and job['revision']==job['synced_revision']:
            return 'up-to-date'
        revision=job['revision']
        snapshots={name:[headers]+[[ '' if v is None else str(v) for v in row ] for row in c.execute(sql).fetchall()]
                   for name,(sql,headers) in TABS.items()}
    try:
        import gspread
        gc=gspread.service_account(filename=str(credentials_path()))
        book=gc.open_by_key(settings.google_sheet_id)
        for tab,values in snapshots.items():
            try:
                ws=book.worksheet(tab)
            except gspread.WorksheetNotFound:
                ws=book.add_worksheet(title=tab,rows=max(100,len(values)+20),cols=max(12,len(values[0])+2))
            ws.clear()
            ws.update(range_name='A1',values=values,value_input_option='RAW')
    except Exception as e:
        with session(write=True) as c:
            c.execute('UPDATE sync_jobs SET last_error=?,updated_at=? WHERE id=1',(type(e).__name__,utcnow()))
        raise
    with session(write=True) as c:
        c.execute('UPDATE sync_jobs SET synced_revision=?,synced_once=1,last_error=NULL,updated_at=? WHERE id=1', (revision,utcnow()))
    return 'synced'


async def background_sync():
    while True:
        if enabled():
            try:
                await asyncio.to_thread(sync_once)
            except Exception as exc:
                print(f'[sheets] Ошибка синхронизации ({type(exc).__name__}); повторим позже.', flush=True)
        await asyncio.sleep(max(15,settings.sync_interval_seconds))


def status():
    with session() as c:
        r=dict(c.execute('SELECT * FROM sync_jobs WHERE id=1').fetchone())
    return {'configured':enabled(), **r}
