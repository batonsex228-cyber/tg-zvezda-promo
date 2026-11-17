"""Production-only process entrypoint for one Docker Compose app replica.

Windows operators should continue using START_WINDOWS.bat / START_TUNNEL_WINDOWS.bat.
This module refuses to bind 0.0.0.0 outside an explicitly selected container.
"""
import asyncio
import os
import re
from urllib.parse import urlsplit
from app.config import settings
from app.main import main
from app.runtime import StartupError


def validate_production(cfg=None, *, domain=None, in_container=None):
    cfg = cfg or settings
    domain = os.getenv('DOMAIN', '') if domain is None else domain
    in_container = os.getenv('TOURIST_CONTAINER') == '1' if in_container is None else in_container
    issues = []
    if not in_container:
        issues.append('Запуск разрешён только внутри настроенного контейнера.')
    if cfg.demo_mode:
        issues.append('DEMO_MODE=true запрещён для публичного сервиса.')
    if not re.fullmatch(r'\d{5,}:[A-Za-z0-9_-]{20,}', cfg.bot_token):
        issues.append('BOT_TOKEN отсутствует или имеет неверный формат.')
    if not (0 < cfg.owner_telegram_id < 10**16):
        issues.append('OWNER_TELEGRAM_ID должен быть указан до публикации.')
    domain = domain.strip().lower().rstrip('.')
    if not (domain and re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', domain)
            and '.' in domain and '..' not in domain):
        issues.append('DOMAIN должен содержать корректное доменное имя.')
    try:
        url = urlsplit(cfg.webapp_url)
        port = url.port
    except ValueError:
        raise StartupError('Проверка production: WEBAPP_URL содержит некорректный адрес.') from None
    if (url.scheme != 'https' or not url.hostname or url.username or url.password or
            url.path not in ('','/') or url.query or url.fragment or port not in (None,443)):
        issues.append('WEBAPP_URL должен быть HTTPS-адресом домена без пути, токенов и query.')
    elif domain and url.hostname.lower().rstrip('.') != domain:
        issues.append('WEBAPP_URL и DOMAIN должны совпадать.')
    if cfg.backup_interval_hours <= 0 or cfg.backup_keep_days < 7:
        issues.append('Перед запуском включите резервные копии (интервал >0, хранение >=7 дней).')
    if bool(cfg.google_sheet_id) != bool(cfg.google_credentials_file):
        issues.append('Google Sheets: настройте оба поля или оставьте оба пустыми.')
    # Do not include values/secrets in error messages.
    if issues:
        raise StartupError('Проверка production: ' + ' '.join(issues))
    return True


if __name__ == '__main__':
    try:
        validate_production()
        asyncio.run(main(host='0.0.0.0', port=8000))
    except (StartupError, RuntimeError) as exc:
        print(f'[PRODUCTION ERROR] {exc}', flush=True)
        raise SystemExit(1) from None
