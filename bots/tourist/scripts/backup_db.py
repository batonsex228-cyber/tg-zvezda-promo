"""WAL-safe backup of an EXISTING SQLite database; never creates a new DB."""
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from app.config import ROOT
from app.database import database_path


def create_backup(destination_dir=None, *, prefix="tourist_backup_"):
    source = database_path()
    if not source.is_file():
        raise FileNotFoundError('База ещё не создана. Сначала запустите приложение.')
    destination = Path(destination_dir) if destination_dir is not None else ROOT / 'backups'
    destination.mkdir(parents=True, exist_ok=True)
    if prefix not in ('tourist_backup_', 'tourist_auto_'):
        raise ValueError('Unsupported backup prefix')
    name = prefix + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f') + '.sqlite3'
    backup = destination / name
    partial = destination / (name + '.partial')
    try:
        with sqlite3.connect(f'file:{source.as_posix()}?mode=ro', uri=True) as src, sqlite3.connect(partial) as out:
            src.backup(out)
        with sqlite3.connect(partial) as probe:
            if probe.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Не пройдена проверка целостности резервной копии.')
        partial.replace(backup)  # Publish only a validated, complete SQLite file.
        return backup
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


if __name__=='__main__':
    print('Резервная копия:', create_backup())
