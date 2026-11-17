"""Recover a verified SQLite backup to a NEW database file, without touching live data.

This command never replaces DATABASE_PATH, never modifies the original backup,
and never changes .env. After restoration an operator must explicitly point
DATABASE_PATH to the verified recovered copy and restart with the old bot stopped.
"""
import argparse
import os
import shutil
import sqlite3
from pathlib import Path

from app.config import settings
from app.database import database_path, token_fingerprint
from scripts.restore_check import verify_backup


class RecoveryError(ValueError):
    pass


def check_identity(backup: Path, token: str):
    # Call only after basic backup verification, without changing any DB.
    with sqlite3.connect(f'file:{backup.as_posix()}?mode=ro', uri=True) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'bot_identity' not in tables:
            return 'legacy-unbound'
        row = db.execute('SELECT token_fingerprint FROM bot_identity WHERE id=1').fetchone()
        if row is None:
            return 'legacy-unbound'
        if not token:
            raise RecoveryError('Эта копия привязана к боту. Сначала настройте BOT_TOKEN локально в .env.')
        if token_fingerprint(token) != row[0]:
            raise RecoveryError('Копия принадлежит другому Telegram-боту. Нужен отдельный токен/проект.')
        return 'matched'


def restore_to_new_database(source, destination, *, bot_token=None):
    source = Path(source).expanduser().resolve()
    destination = Path(destination).expanduser().absolute()
    live = database_path()
    if destination.suffix.lower() != '.sqlite3':
        raise RecoveryError('Новый файл должен заканчиваться на .sqlite3')
    if not source.is_file():
        raise FileNotFoundError('Исходная резервная копия не найдена')
    if source == live or destination.resolve() == live:
        raise RecoveryError('Нельзя заменять или копировать поверх рабочей базы')
    if source == destination.resolve() or destination.exists() or destination.is_symlink():
        raise FileExistsError('Новый файл уже существует или совпадает с копией')
    if not destination.parent.is_dir():
        raise FileNotFoundError('Папка назначения не существует. Создайте её заранее.')
    verify_backup(source)
    identity = check_identity(source, settings.bot_token if bot_token is None else bot_token)

    # Exclusive creation guarantees no accidental overwrite even under a race.
    # The new file is not a live DATABASE_PATH; nobody should connect before
    # this command returns. Failed writes are removed; source stays untouched.
    created = False
    try:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(fd, 'wb') as out, source.open('rb') as inp:
            shutil.copyfileobj(inp, out, length=1024*1024)
            out.flush()
            os.fsync(out.fileno())
        counts = verify_backup(destination)
        if identity != 'legacy-unbound':
            check_identity(destination, settings.bot_token if bot_token is None else bot_token)
        return {'file': str(destination), 'identity': identity, 'counts': counts}
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description='ТУРИСТ: восстановление в НОВУЮ SQLite без перезаписи рабочей')
    parser.add_argument('source', help='Путь к проверенному .sqlite3 бэкапу')
    parser.add_argument('destination', help='Путь к новому ещё НЕ существующему .sqlite3')
    args = parser.parse_args(argv)
    try:
        result = restore_to_new_database(args.source, args.destination)
    except (OSError, sqlite3.DatabaseError, RecoveryError, RuntimeError) as exc:
        print(f'ОШИБКА ВОССТАНОВЛЕНИЯ: {exc}')
        return 1
    print('Копия восстановлена в ОТДЕЛЬНЫЙ файл. Рабочая база и .env НЕ изменялись.')
    print('Проверены SQLite integrity_check, связи и таблицы.')
    print('Расположение:', result['file'])
    print('Далее остановите бота, сохраните старую базу, измените DATABASE_PATH в .env и запустите диагностику.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
