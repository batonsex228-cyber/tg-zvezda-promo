# ДЗЛ «Звёздочка» - Telegram Support Bot v1.0.4

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
python scripts/docker_release_check.py
```

### Docker на сервере

1. Дождитесь зелёной GitHub Actions сборки образа `ghcr.io/<OWNER>/zvezdochka-telegram-bot:latest`.
2. На сервере скопируйте `.env.example` в `.env`, настройте `TELEGRAM_BOT_TOKEN` и `BOT_IMAGE` (и `TELEGRAM_MANAGER_USER_ID`, если нужны менеджер и заявки).
3. Выполните `docker compose pull && docker compose up -d`.
4. Проверьте `docker compose logs --tail=100 -f`.

**Токены, `.env`, SQLite и `runtime/` не включаются в Git/Docker-образ.** Данные хранятся в постоянном Docker volume.

Не запускайте одновременно Windows- и Docker-копию бота с одним токеном: Telegram long polling допускает одного потребителя обновлений. Для бронирований с общей Google-таблицей требуются отдельные настройки (см. README_RU.md).
