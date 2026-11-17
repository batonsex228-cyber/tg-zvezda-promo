"""Verify a backup independently, without touching or overwriting a working DB."""
import argparse
import sqlite3
from pathlib import Path
from app.config import ROOT

REQUIRED_TABLES = {'users','events','applications','billiard_bookings','audit','notification_outbox'}


def verify_backup(path):
    path=Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError('Файл резервной копии не найден')
    with sqlite3.connect(f'file:{path.as_posix()}?mode=ro',uri=True) as c:
        integrity = c.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity != 'ok':
            raise RuntimeError('Повреждена структура SQLite: ' + integrity[:150])
        tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing=REQUIRED_TABLES-tables
        if missing:
            raise RuntimeError('В резервной копии отсутствуют таблицы: '+', '.join(sorted(missing)))
        fk_errors=c.execute('PRAGMA foreign_key_check').fetchall()
        if fk_errors:
            raise RuntimeError('Нарушения связности записей: '+str(len(fk_errors)))
        return {t:c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in sorted(REQUIRED_TABLES)}


def main():
    p=argparse.ArgumentParser(description='ТУРИСТ: безопасная проверка резервной копии')
    p.add_argument('file',nargs='?',help='Путь к .sqlite3 (без аргумента: самая новая копия)')
    args=p.parse_args()
    candidate=Path(args.file) if args.file else None
    if candidate is None:
        options=list((ROOT/'backups').glob('tourist_backup_*.sqlite3')) + list((ROOT/'backups').glob('tourist_auto_*.sqlite3'))
        if not options:
            p.error('Пока нет копий. Запустите BACKUP_WINDOWS.bat после первого запуска.')
        candidate=max(options, key=lambda entry: entry.stat().st_mtime)
    counts=verify_backup(candidate)
    print('BACKUP OK: SQLite integrity_check, foreign_key_check и обязательные таблицы.')
    print('Записей по таблицам:',counts)
    print('Рабочая база не изменялась.')

if __name__=='__main__':main()
