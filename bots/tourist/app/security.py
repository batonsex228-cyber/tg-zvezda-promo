"""Telegram Mini App HMAC validation. Demo credentials only on loopback."""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

class AuthError(ValueError):
    pass


def verify_init_data(raw: str, token: str, max_age_seconds: int = 86400, now: int | None = None) -> dict:
    if not raw or not token or len(raw) > 16384:
        raise AuthError('Нет данных авторизации Telegram')
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, max_num_fields=40)
    except ValueError as exc:
        raise AuthError('Некорректный формат авторизации') from exc
    data = dict(pairs)
    if len(data) != len(pairs):
        raise AuthError('Повторяющиеся параметры авторизации')
    supplied_hash = data.pop('hash', '')
    if len(supplied_hash) != 64:
        raise AuthError('Нет проверочной подписи')
    try:
        auth_date = int(data['auth_date'])
        user = json.loads(data['user'])
        if not isinstance(user, dict) or isinstance(user.get('id'), bool):
            raise ValueError('Invalid user object')
        user_id = int(user['id'])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise AuthError('Неполные данные Telegram') from exc
    # Telegram's HMAC covers all received parameters except hash; signature, when supplied,
    # is left in the string. See https://core.telegram.org/bots/webapps
    check = '\n'.join(f'{key}={value}' for key, value in sorted(data.items()))
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied_hash, expected):
        raise AuthError('Неверная подпись Telegram')
    current = int(time.time()) if now is None else now
    if auth_date > current + 60 or current - auth_date > max_age_seconds:
        raise AuthError('Сессия Telegram устарела. Откройте приложение заново')
    if not (0 < user_id < 10**16):
        raise AuthError('Некорректный Telegram ID')
    name = user.get('first_name', '')
    return {'id': user_id, 'first_name': name[:100] if isinstance(name, str) else ''}
