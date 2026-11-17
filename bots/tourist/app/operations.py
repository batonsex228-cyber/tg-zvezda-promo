"""Read-only owner diagnostics. Never return secret tokens, IDs, file paths or PII."""
import shutil
from pathlib import Path

from app.config import settings
from app.database import database_path, session
from app import maintenance, notifications, sheets
from scripts.offsite_backup import state_snapshot


def snapshot():
    db = database_path()
    if not db.exists():
        return {'database': {'present': False}, 'disk': {'free_mb': None, 'low_space': None},
                'backup': maintenance.backup_status(), 'google': {'configured': sheets.enabled()},
                'notifications': {'pending': 0, 'failed': 0}, 'telegram': {'configured': bool(settings.bot_token)},
                'offsite': state_snapshot(maintenance.backup_folder())}
    disk = shutil.disk_usage(db.parent)
    # Disk stats and row counts only. Never expose records, secret paths or filenames.
    with session() as c:
        quick = c.execute('PRAGMA quick_check').fetchone()[0]
        sync = dict(c.execute('SELECT revision,synced_revision,synced_once,last_error FROM sync_jobs WHERE id=1').fetchone())
        users = c.execute('SELECT count(*) FROM users').fetchone()[0]
    note = notifications.pending_status()
    return {
        'database': {'present': True, 'quick_check_ok': quick == 'ok', 'users': users,
                     'size_mb': round(db.stat().st_size / (1024*1024), 1)},
        'disk': {'free_mb': round(disk.free / (1024*1024)), 'low_space': disk.free < 200*1024*1024},
        'backup': maintenance.backup_status(),
        'google': {'configured': sheets.enabled(), 'synced_once': bool(sync['synced_once']),
                   'behind': sync['revision'] > sync['synced_revision'], 'has_error': bool(sync['last_error'])},
        'notifications': {'pending': note['pending'], 'failed': note['failed']},
        'telegram': {'configured': bool(settings.bot_token), 'miniapp_https_configured': settings.webapp_url.startswith('https://')},
        'offsite': state_snapshot(maintenance.backup_folder()),
    }
