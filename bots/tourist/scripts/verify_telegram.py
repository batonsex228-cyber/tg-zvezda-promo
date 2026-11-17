"""Explicit ONLINE connectivity test for a freshly created BotFather bot.

Only harmless Bot API GET calls are made: getMe and getWebhookInfo.
Never print the token, raw request URL, or the contents of API exceptions.
"""
import argparse
import re

import httpx
from app.config import settings
from app.telegram_transport import method_url, relay_headers


class TelegramCheckError(RuntimeError):
    pass


def check_bot(token, transport=None):
    """Return safe metadata or raise a user-readable, redacted error."""
    if not re.fullmatch(r'\d{5,}:[A-Za-z0-9_-]{20,}', token):
        raise TelegramCheckError('BOT_TOKEN не заполнен или имеет неверный формат.')
    try:
        with httpx.Client(transport=transport, timeout=10.0, follow_redirects=False) as client:
            def call(method):
                response = client.get(method_url(token, method), headers=relay_headers())
                response.raise_for_status()
                payload = response.json()
                if payload.get('ok') is not True or not isinstance(payload.get('result'),dict):
                    raise TelegramCheckError(f'Telegram не подтвердил {method}. Проверьте токен.')
                return payload['result']
            me=call('getMe')
            webhook=call('getWebhookInfo')
    except httpx.TimeoutException as exc:
        raise TelegramCheckError('Таймаут Telegram API. Проверьте интернет/VPN и повторите.') from exc
    except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
        raise TelegramCheckError('Нет доступа к Telegram Bot API или токен недействителен. Проверьте сеть и токен.') from exc
    if not isinstance(me.get('id'),int) or not me.get('is_bot') or not isinstance(me.get('username'),str):
        raise TelegramCheckError('Telegram вернул некорректные сведения о боте.')
    return {'id':me['id'],'username':me['username'],
            'webhook_active':bool(webhook.get('url')),
            'pending_updates':int(webhook.get('pending_update_count') or 0)}


def main():
    parser=argparse.ArgumentParser(description='Онлайн-проверка Telegram BotFather токена')
    parser.parse_args()
    try:
        result=check_bot(settings.bot_token)
    except TelegramCheckError as exc:
        print('[ERROR]',exc)
        return 1
    print(f"[OK] Telegram подтверждает бота @{result['username']} (ID {result['id']}).")
    if result['webhook_active']:
        print('[ERROR] У бота настроен webhook, а проект использует long polling. '
              'Отключите прежний webhook перед запуском, чтобы не потерять рабочие подключения.')
        return 1
    print(f"[OK] Webhook не настроен. Необработанных обновлений: {result['pending_updates']}.")
    print('[OK] Проверка не отправляла сообщения и не меняла настройки бота.')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
