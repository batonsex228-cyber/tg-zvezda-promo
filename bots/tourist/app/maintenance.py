"""Daily verified SQLite backups with conservative retention.

Manual backups are NEVER deleted. Automatic retention starts only after a verified
new backup. Always preserve at least one most-recent automatic backup.
This service is for the single-process local deployment (one Uvicorn worker).
"""
import asyncio
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from app.config import ROOT, settings
from app.database import database_path
from scripts.backup_db import create_backup
from scripts.restore_check import verify_backup

_lock = threading.Lock()
_last_error = None


def backup_folder():
    return ROOT / 'backups'


def automatic_files():
    folder = backup_folder()
    return sorted((p for p in folder.glob('tourist_auto_*.sqlite3') if p.is_file()),
                  key=lambda p: (p.stat().st_mtime, p.name)) if folder.is_dir() else []


def backup_status(now=None):
    """Read-only, non-secret metadata for the authenticated administrator UI."""
    now = time.time() if now is None else now
    files = automatic_files()
    latest = files[-1] if files else None
    age = max(0, (now-latest.stat().st_mtime)/3600) if latest else None
    interval = settings.backup_interval_hours
    return {
        'enabled': interval > 0,
        'active': interval > 0 and bool(settings.bot_token) and not settings.demo_mode,
        'interval_hours': interval,
        'keep_days': settings.backup_keep_days,
        'copies': len(files),
        'last_created_at': datetime.fromtimestamp(latest.stat().st_mtime,timezone.utc).isoformat(timespec='seconds') if latest else None,
        'age_hours': round(age, 1) if age is not None else None,
        'overdue': interval > 0 and (age is None or age > interval + 1),
        'last_error': _last_error,
    }


def backup_if_due(now=None):
    global _last_error
    now = time.time() if now is None else now
    if not (0 <= settings.backup_interval_hours <= 24*30 and 1 <= settings.backup_keep_days <= 3650):
        raise ValueError('Некорректная настройка автоматического резервного копирования')
    if settings.backup_interval_hours == 0 or settings.demo_mode or not settings.bot_token:
        return 'disabled'
    if not database_path().is_file():
        return 'no-database'
    # Do not let overlapping calls in this process launch multiple backups.
    if not _lock.acquire(blocking=False):
        return 'already-running'
    try:
        recent = automatic_files()
        if recent and now-recent[-1].stat().st_mtime < settings.backup_interval_hours*3600:
            try:
                verify_backup(recent[-1])
                return 'up-to-date'
            except Exception:
                # A recently corrupted backup must not block a replacement.
                pass
        # Export via SQLite Online Backup API, then verify before publishing.
        result = create_backup(destination_dir=backup_folder(), prefix='tourist_auto_')
        verify_backup(result)
        # Retention applies ONLY to automatic files, and ONLY AFTER success.
        cutoff = now - settings.backup_keep_days*86400
        for old in automatic_files()[:-1]:
            if old.stat().st_mtime < cutoff:
                old.unlink(missing_ok=True)
        _last_error = None
        return 'created'
    except Exception as exc:
        _last_error = type(exc).__name__  # no credentials / internal paths in UI
        raise
    finally:
        _lock.release()


async def background_backups():
    # Keep expensive disk I/O out of app startup / tests and out of the event loop.
    await asyncio.sleep(30)
    while True:
        try:
            await asyncio.to_thread(backup_if_due)
        except Exception as exc:
            print(f'[backup] Backup failed ({type(exc).__name__}). Manual check required.', flush=True)
        await asyncio.sleep(3600)
