"""Administrative bootstrap and demo examples: python -m app.cli seed-demo."""
import argparse
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from app.config import settings
from app.database import initialize_storage, database_path
from app import service


def refuse_unbound_cli_on_existing_bot():
    """No token must NOT make a bot-bound client DB writable from maintenance CLI.

    The normal demo without token remains possible on a fresh unbound SQLite.
    A read-only probe runs before initialize_storage can migrate anything.
    """
    if settings.bot_token or not database_path().is_file():
        return
    import sqlite3
    with sqlite3.connect(f'file:{database_path().as_posix()}?mode=ro', uri=True) as c:
        exists = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bot_identity'").fetchone()
        if exists and c.execute('SELECT 1 FROM bot_identity WHERE id=1').fetchone():
            raise RuntimeError('Для служебной команды с базой Telegram-бота необходимо указать BOT_TOKEN. '
                               'Если это новый клиент, используйте отдельный DATABASE_PATH.')


def main():
    p=argparse.ArgumentParser(description='Турист · утилиты разработчика')
    sub=p.add_subparsers(dest='cmd',required=True)
    sub.add_parser('sync-now',help='Принудительно выгрузить все данные в Google Sheets')
    seed=sub.add_parser('seed-demo',help='Создать 3 демонстрационных события (не для реального клуба)')
    create=sub.add_parser('create-event',help='Создать настоящее событие')
    create.add_argument('--kind',choices=['mafia','poker'],required=True)
    create.add_argument('--title',required=True)
    create.add_argument('--start',required=True,help='2026-11-12T19:00 (местное время клуба)')
    create.add_argument('--format',default='')
    create.add_argument('--capacity',type=int,default=10)
    create.add_argument('--min-players',type=int,default=1)
    create.add_argument('--stack',default='')
    create.add_argument('--blinds',default='')
    args=p.parse_args(); refuse_unbound_cli_on_existing_bot(); initialize_storage()
    if args.cmd=='sync-now':
        from app.sheets import sync_once
        print(sync_once(force=True)); return
    if not settings.owner_telegram_id:
        p.error('Укажите OWNER_TELEGRAM_ID в .env')
    service.ensure_user(settings.owner_telegram_id,'Владелец')
    if args.cmd=='create-event':
        x=service.create_event(settings.owner_telegram_id,args.kind,args.title,args.start,args.capacity,args.format,args.min_players,args.stack,args.blinds)
        print('Событие создано:',x['id']); return
    zone=ZoneInfo(settings.club_timezone)
    today=datetime.now(zone).replace(hour=19,minute=0,second=0,microsecond=0)
    def next_day(w):
        delta=(w-today.weekday())%7
        if delta==0: delta=7
        return (today+timedelta(days=delta)).isoformat()
    demo=[('mafia','Классическая мафия',next_day(3),10,'classic',1,'',''),
          ('mafia','Городская мафия',next_day(6),15,'city',10,'',''),
          ('poker','Спортивный покер',next_day(5),10,'',1,'10 000','100/200')]
    for kind,title,start,cap,fmt,minimum,stack,blinds in demo:
        e=service.create_event(settings.owner_telegram_id,kind,title,start,cap,fmt,minimum,stack,blinds)
        print('Добавлено:',e['id'],title)
    print('События добавлены в расписание.')

if __name__=='__main__':main()
