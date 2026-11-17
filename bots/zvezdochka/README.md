# ДЗЛ «Звёздочка» - Telegram Support Bot v1.0.5

Отдельная версия бота для **Telegram**, перенесённая с исходной VK-логики. Здесь нет необходимости запускать VK-бота или публиковать веб-сервер: используются исходящие Telegram Bot API-запросы (long polling).

## Два способа запуска

- **Windows:** `START_TELEGRAM.bat`. Подробности: [README_RU.md](README_RU.md).
- **Linux / Docker / GitHub Actions / GHCR:** [DEPLOY_DOCKER_RU.md](DEPLOY_DOCKER_RU.md).

### Локальная проверка без Telegram-токена

```bash
python -m pip install -r requirements.txt
python scripts/local_self_test.py
python scripts/telegram_flow_test.py
python scripts/telegram_social_reply_test.py
python scripts/semantic_regression_test.py
python scripts/context_20_test.py
python scripts/telegram_semantic_flow_test.py
python scripts/telegram_cloudflare_proxy_test.py
python scripts/docker_release_check.py
```

### Docker на сервере

1. Дождитесь зелёной GitHub Actions сборки образа `ghcr.io/<OWNER>/zvezdochka-telegram-bot:latest`.
2. На сервере скопируйте `.env.example` в `.env`, настройте `TELEGRAM_BOT_TOKEN` и `BOT_IMAGE` (и `TELEGRAM_MANAGER_USER_ID`, если нужны менеджер и заявки).
3. Выполните `docker compose pull && docker compose up -d`.
4. Проверьте `docker compose logs --tail=100 -f`.

**Токены, `.env`, SQLite и `runtime/` не включаются в Git/Docker-образ.** Данные хранятся в постоянном Docker volume.

Не запускайте одновременно Windows- и Docker-копию бота с одним токеном: Telegram long polling допускает одного потребителя обновлений. Для бронирований с общей Google-таблицей требуются отдельные настройки (см. README_RU.md).


### Cloudflare Worker Telegram API relay

For the Russian Docker host, set `TELEGRAM_API_BASE_URL=https://telegram-api-proxy.aleksejnazarov93583.workers.dev` **in the server `.env`**. This is an HTTPS reverse proxy endpoint, **not** an `HTTP_PROXY` / SOCKS5 address. If the Worker demands `X-Relay-Key`, set `TELEGRAM_RELAY_KEY` to the matching secret on the server, never in GitHub. The adapter sends `getUpdates`, `sendMessage`, `setMessageReaction`, manager callbacks etc. through the relay. For direct access, use `TELEGRAM_API_BASE_URL=https://api.telegram.org`.

Before enabling real child/parent data, have the camp review how the Cloudflare intermediary handles data, access logging and retention. The Worker URL is provided by the operator; its forwarding implementation has **not** been independently verified. Local tests use a mock HTTP transport, not real Telegram credentials.
