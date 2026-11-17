"""A destructive-free restoration rehearsal using a temporary directory.

Creates a fresh SQLite snapshot of the active DB, restores it to another NEW
file, and validates table counts; only temp files are removed afterward.
"""
import argparse
import tempfile
from pathlib import Path

from app.database import database_path
from scripts.backup_db import create_backup
from scripts.restore_check import verify_backup
from scripts.recover_to_new_db import restore_to_new_database


def run_drill():
    if not database_path().is_file():
        raise FileNotFoundError('Для тестового восстановления нужна существующая рабочая база.')
    with tempfile.TemporaryDirectory(prefix='tourist_recovery_drill_') as temp:
        folder = Path(temp)
        original_snapshot = create_backup(folder / 'backups')
        counts_before = verify_backup(original_snapshot)
        result = restore_to_new_database(original_snapshot, folder / 'recovered.sqlite3')
        if result['counts'] != counts_before:
            raise RuntimeError('Количество записей после восстановления отличается от оригинальной копии.')
        return {'result': 'ok', 'tables_checked': len(counts_before), 'counts_match': True}


def main(argv=None):
    argparse.ArgumentParser(description='ТУРИСТ: тест восстановления без изменения базы').parse_args(argv)
    try:
        result = run_drill()
        print(f"RECOVERY DRILL OK: {result['tables_checked']} таблиц, записи совпадают. Живая база не изменена.")
        return 0
    except Exception as exc:
        print(f'RECOVERY DRILL FAILED: {type(exc).__name__}: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
