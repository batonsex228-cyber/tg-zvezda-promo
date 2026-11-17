"""Isolated server smoke test. Creates a temporary database, never touches real users."""
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import api, config, database, notifications, service, sheets


def main():
    with tempfile.TemporaryDirectory(prefix='tourist-smoke-') as folder:
        demo=replace(config.settings, bot_token='', owner_telegram_id=900001, demo_mode=True,
                     google_sheet_id='', google_credentials_file='',
                     database_path=str(Path(folder)/'smoke.sqlite3'),reminder_hours_before=0)
        with patch.object(api,'settings',demo),patch.object(database,'settings',demo), \
             patch.object(service,'settings',demo),patch.object(sheets,'settings',demo), \
             patch.object(notifications,'settings',demo):
            with TestClient(api.app) as client:
                for path in ('/', '/health', '/assets/app.js', '/assets/styles.css', '/api/schedule', '/api/me'):
                    response=client.get(path)
                    if response.status_code!=200:
                        raise RuntimeError(f'{path}: HTTP {response.status_code}: {response.text[:200]}')
                # Explicitly deny nonlocal demo access even when X-Demo-User-ID is supplied.
                response=client.get('/api/me',headers={'Host':'public.example','X-Demo-User-ID':'900001'})
                if response.status_code!=401:
                    raise RuntimeError('Неожиданный удалённый демо-доступ')
                print('SMOKE OK: FastAPI, Mini App HTML/JS/CSS, SQLite, расписание, профиль, защита демо.')

if __name__=='__main__':main()
