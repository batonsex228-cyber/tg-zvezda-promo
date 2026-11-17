"""Environment-based configuration. Secrets are never bundled."""
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')

@dataclass(frozen=True)
class Settings:
    bot_token: str = os.getenv('BOT_TOKEN', '').strip()
    telegram_api_base_url: str = os.getenv('TELEGRAM_API_BASE_URL', 'https://api.telegram.org').strip().rstrip('/')
    telegram_relay_key: str = os.getenv('TELEGRAM_RELAY_KEY', '').strip()
    webapp_url: str = os.getenv('WEBAPP_URL', '').rstrip('/')
    database_path: str = os.getenv('DATABASE_PATH', str(ROOT / 'data' / 'tourist.sqlite3'))
    owner_telegram_id: int = int(os.getenv('OWNER_TELEGRAM_ID', '0'))
    club_timezone: str = os.getenv('CLUB_TIMEZONE', 'Europe/Moscow')
    demo_mode: bool = os.getenv('DEMO_MODE', 'false').lower() == 'true'
    showcase_mode: bool = os.getenv('SHOWCASE_MODE', 'false').lower() == 'true'
    ai_mode: str = os.getenv('AI_MODE','off').lower()
    ollama_model: str = os.getenv('OLLAMA_MODEL','').strip()
    ollama_url: str = os.getenv('OLLAMA_URL','http://127.0.0.1:11434').strip()
    google_sheet_id: str = os.getenv('GOOGLE_SHEET_ID', '').strip()
    google_credentials_file: str = os.getenv('GOOGLE_CREDENTIALS_FILE', '').strip()
    sync_interval_seconds: int = int(os.getenv('SYNC_INTERVAL_SECONDS', '45'))
    reminder_hours_before: int = int(os.getenv('REMINDER_HOURS_BEFORE', '0'))
    backup_interval_hours: int = int(os.getenv('BACKUP_INTERVAL_HOURS', '24'))
    backup_keep_days: int = int(os.getenv('BACKUP_KEEP_DAYS', '14'))

settings = Settings()
