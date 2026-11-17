"""Offline preflight: never prints the Telegram token or Google key.

Use after SETUP_WINDOWS.bat:
    python -m scripts.doctor --live
    python -m scripts.doctor --demo

No requests are sent to Telegram, Google, or Cloudflare.
"""
import argparse
import importlib.util
import json
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import ROOT, settings
from app.database import token_fingerprint


def diagnose(mode='live', root=ROOT, cfg=None, require_packages=True):
    cfg = cfg or settings
    issues = []
    def add(severity, message):
        issues.append({'level':severity,'message':message})

    if not ((3, 11) <= sys.version_info[:2] <= (3, 13)):
        add('ERROR', 'Для Windows выберите Python 3.11–3.13, рекомендуем 3.12.')
    else:
        add('OK', f'Python {sys.version_info.major}.{sys.version_info.minor}')
    if require_packages:
        packages=['fastapi','uvicorn','dotenv','httpx','pydantic','tzdata','cryptography']
        if mode == 'live':
            packages.append('aiogram')
        if cfg.google_sheet_id or cfg.google_credentials_file:
            packages.extend(('gspread','google.auth'))
        for name in packages:
            try: present = importlib.util.find_spec(name) is not None
            except (ImportError, ModuleNotFoundError, ValueError): present = False
            add('OK' if present else 'ERROR', f'Зависимость {name}: '+('найдена' if present else 'отсутствует; запустите SETUP_WINDOWS.bat'))
    if not (root / 'web' / 'index.html').is_file() or not (root / 'web' / 'app.js').is_file():
        add('ERROR','Не найдены файлы Mini App: распакуйте полный ZIP в одну папку.')
    else: add('OK', 'Статические файлы Mini App найдены')

    if mode == 'live':
        if cfg.demo_mode:
            add('ERROR', 'DEMO_MODE=true недопустим для настоящего бота или публичного Mini App.')
        if not re.fullmatch(r'\d{5,}:[A-Za-z0-9_-]{20,}', cfg.bot_token):
            add('ERROR', 'BOT_TOKEN отсутствует или не похож на токен BotFather (значение скрыто).')
        else:
            add('OK','Формат BOT_TOKEN похож на BotFather (проверка Telegram API ещё не выполнена).')
        if cfg.owner_telegram_id == 0:
            add('WARN', 'OWNER_TELEGRAM_ID=0: можно запустить /id, затем записать ID владельца в .env и перезапустить. Админка пока без владельца.')
        elif not (0 < cfg.owner_telegram_id < 10**16):
            add('ERROR', 'OWNER_TELEGRAM_ID должен быть положительным числовым Telegram ID.')
        else: add('OK', 'ID владельца указан (не проверен через Telegram)')
        if not cfg.webapp_url:
            add('WARN', 'WEBAPP_URL пустой: текстовый бот работает, но Mini App в Telegram недоступен. Для временного URL используйте START_TUNNEL_WINDOWS.bat.')
        else:
            parsed = urlsplit(cfg.webapp_url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                add('ERROR', 'WEBAPP_URL должен быть действительным HTTPS-адресом без логина и пароля.')
            else: add('OK','HTTPS URL заполнен (сеть ещё не проверялась).')
    else:
        if cfg.bot_token:
            add('WARN', 'Демо-режим не использует BOT_TOKEN; для локального демо токен игнорируется.')
        add('OK','Локальное демо работает без Telegram-токена и без публичного HTTPS.')
    if not (0 <= cfg.reminder_hours_before <= 168):
        add('ERROR','REMINDER_HOURS_BEFORE: 0 (выкл.) либо 1–168 часов.')
    elif cfg.reminder_hours_before:
        add('WARN', f'Автоматические напоминания включены за {cfg.reminder_hours_before} ч. Проверьте согласие клиента и время.')
    else:
        add('OK','Напоминания отключены до согласования с клиентом.')
    if not 0 <= cfg.backup_interval_hours <= 24*30:
        add('ERROR', 'BACKUP_INTERVAL_HOURS: 0 (выкл.) либо 1–720 часов.')
    elif cfg.backup_interval_hours == 0:
        add('WARN', 'Автоматические копии отключены: включите их до передачи клиенту.')
    else:
        add('OK', f'Автоматическая резервная копия: каждые {cfg.backup_interval_hours} ч.')
    if not 1 <= cfg.backup_keep_days <= 3650:
        add('ERROR', 'BACKUP_KEEP_DAYS: от 1 до 3650 дней.')
    else:
        add('OK', f'Срок хранения автоматических копий: {cfg.backup_keep_days} дней.')
    try:
        ZoneInfo(cfg.club_timezone)
        add('OK','Часовой пояс клуба доступен')
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        add('ERROR','CLUB_TIMEZONE неизвестен; используйте Europe/Moscow для Новомосковска.')
    try:
        path=Path(cfg.database_path)
        if not path.is_absolute(): path=root/path
        if path.exists():
            with sqlite3.connect(f'file:{path.as_posix()}?mode=ro',uri=True) as c:
                integrity=c.execute('PRAGMA quick_check').fetchone()[0]
                existing_tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                identity=(c.execute('SELECT token_fingerprint FROM bot_identity WHERE id=1').fetchone()
                          if 'bot_identity' in existing_tables else None)
            if integrity!='ok':add('ERROR','SQLite повреждена: восстановите резервную копию.')
            else:add('OK','Существующая SQLite читается; quick_check=ok')
            if mode=='live' and cfg.bot_token and identity and identity[0]!=token_fingerprint(cfg.bot_token):
                add('ERROR','База привязана к другому боту. Измените DATABASE_PATH на новый файл; старые данные сохраните.')
        elif not path.parent.exists():
            add('WARN','Папка данных ещё не создана: создастся при первом запуске.')
        else:
            add('OK','Новая SQLite будет создана при первом запуске.')
    except (OSError,sqlite3.DatabaseError) as exc:
        add('ERROR','Не удалось открыть SQLite: '+type(exc).__name__)
    if cfg.google_sheet_id and not cfg.google_credentials_file or cfg.google_credentials_file and not cfg.google_sheet_id:
        add('WARN','Google Sheets настроены частично: укажите оба поля или оставьте оба пустыми.')
    credential_path=Path(cfg.google_credentials_file) if cfg.google_credentials_file else None
    if credential_path and not credential_path.is_absolute(): credential_path=root/credential_path
    if credential_path and not credential_path.exists():
        add('WARN','Файл ключа Google не найден; синхронизация работать не будет.')
    return issues


def main(argv=None):
    parser=argparse.ArgumentParser(description='Турист: безопасная проверка перед запуском')
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--live',action='store_true')
    group.add_argument('--demo',action='store_true')
    parser.add_argument('--json',action='store_true')
    args=parser.parse_args(argv)
    issues=diagnose('demo' if args.demo else 'live')
    if args.json:
        print(json.dumps(issues,ensure_ascii=False,indent=2))
    else:
        print('ТУРИСТ | Проверка готовности к запуску (токены скрыты)')
        for item in issues:print(f"[{item['level']}] {item['message']}")
        print('Результат: '+('ОШИБКИ — исправьте их до запуска' if any(i['level']=='ERROR' for i in issues) else 'критических ошибок не обнаружено'))
    return 1 if any(x['level']=='ERROR' for x in issues) else 0


if __name__=='__main__':
    raise SystemExit(main())
