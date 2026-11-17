## 0.18.0 — Gold Lounge Visual Polish (2026-11-17)
- Плавные локальные анимации и единые системные шрифты без CDN.
- Улучшена навигация на телефонах, reduced-motion и доступность поп-апов (focus trap / Escape / возврат фокуса).
- Дни и время бронирования имеют доступные выбранные состояния; исправлена версия BAT.
- Сохранены оригинальный логотип и вся логика Telegram + Mini App.

## 0.17.0 Gold Lounge

- Premium interactive Mini App with original logo and isolated visual assets.
- Real responsive navigation, event imagery, billiard booking controls and status graphics.
- 10 additional regression tests and real-image Chromium visual QA.

## v0.14.0 — Retry and Privacy Hardening
- Idempotent cancellation retries for already cancel_requested event/billiard requests.
- Public schedule no longer returns the creator's Telegram ID.
- Owner-only manual retry of transient failed system notifications (max 20, never already sent/permanent/reminder).
- Mini App explicit confirmation and new owner recovery browser smoke test.
- 225 automated tests including new coverage for privacy, permissions and duplicate cancellation.

## 0.13.0
- Служебные команды CLI защищены от подключения к БД другого бота ещё до миграции, в том числе при пустом токене на уже привязанной базе.
- Read-only Google Sheets connectivity check и Windows-скрипт.
- Чек-лист UAT, инструкции Google и перехода.

# ТУРИСТ v0.12.0 — Offsite backup readiness

- Необязательный `compose.offsite.yaml` для отдельного контейнера с доступом к SQLite только на чтение.
- Локальный WAL-safe SQLite snapshot → AES-256-GCM `.tbackup` → S3 upload с SSE-S3 → HEAD сверка → обратное скачивание → SHA-256 сверка.
- При сбоях прежняя успешная отметка остаётся; временные файлы удаляются.
- Owner-only Mini App диагностика последней подтверждённой внешней копии, без раскрытия object key.
- `offsite.env.example`, secret-file, правила выдачи минимальных прав и регламент восстановления.
- Прежний бот и Windows-скрипты не требуют S3.

---

# Турист v0.11.0 — Production groundwork + encrypted recovery

- Separate Linux Docker Compose/Caddy TLS deployment with private unexposed app port, named persistent volumes, non-root app, read-only container root, startup preflight and readiness probe.
- Existing Windows and tunnel startup default behavior remains unchanged.
- Streaming AES-256-GCM portable backup export/import (Scrypt passphrase, authenticated metadata, exclusive file creation, no overwrite of live DB, validate SQLite and bot identity).
- Docker and Windows operator instructions. Automatic offsite upload is **not** implemented.
- Regression tests expanded from 144 to 175 (subject to final release audit).

# Турист v0.10.0 — Recovery & Operations

- Restore a verified SQLite backup only to a non-existing destination, using exclusive creation and pre/post validation; never replace `DATABASE_PATH` or mutate `.env`.
- Check existing bot fingerprint before restore; reject a foreign bot backup. Clean up incomplete copies on I/O errors.
- Add disposable recovery drill: fresh online backup → independent recovery → table counts comparison → cleanup.
- Add owner-only diagnostics endpoint and Mini App overview panel. No secret/path/PII exposure.
- Redact raw Google Sheets exception text from state and logs.
- Add Windows entry points `RECOVERY_DRILL_WINDOWS.bat`, `RESTORE_TO_NEW_DB_WINDOWS.bat`.
- Regression suite: 144 checks; Chrome/Chromium smoke scripts updated to verify the new owner panel.

# Турист v0.9.0 — Operational Safety

- Автоматические проверяемые SQLite-бэкапы по расписанию, без удаления ручных копий.
- Атомарная публикация backup.sqlite3 через промежуточный .partial и проверку целостности.
- Контроль резервных копий в админке Mini App, защищённый API только для сотрудников.
- Запрет подтверждения заявок на прошлое/отменённое событие и прошедшую бронь.
- Дополнительная диагностика BACKUP_INTERVAL_HOURS и BACKUP_KEEP_DAYS.
- Тестирование миграции, обслуживания базы и прав пользователей.

# CHANGELOG

## v0.8.0 — подписанная интеграция и ревизии Google Sheets

- Исправлено отслеживание созданных и обновлённых Telegram-пользователей в Google Sheets.
- Изменения во время первой выгрузки теперь сохраняют следующую ревизию.
- Добавлен настоящий end-to-end прогон FastAPI и SQLite с синтетическим Telegram HMAC без сети.
- Добавлен optional Chromium smoke с гостем и администратором в Telegram WebApp-режиме.
- Добавлены `INTEGRATION_QA_WINDOWS.bat`, 6 регрессионных тестов и расширен `FULL_QA_WINDOWS.bat`.

## v0.7.0 — Telegram first-run readiness

- Live startup now validates the actual BotFather identity and checks for webhook conflicts **before** starting FastAPI or modifying the SQLite schema.
- Refuses to open or expose local port 8000 when another process owns it. Adds `FIRST_RUN_CHECK_WINDOWS.bat` for offline settings, port and Telegram API readiness.
- The temporary HTTPS launcher checks `/health` and the exact running version before displaying the Mini App link. Failed starts terminate child processes.
- Cloudflared output reader has a bounded queue (no indefinite log-memory growth). Temporary menu button is reset when test tunnel is stopped; if offline, rerun `/start` after relaunch.
- `/app` command added; without HTTPS it explains how to enable the Mini App. The default Telegram menu returns to commands when no HTTPS URL is configured.
- New isolated tests for actual command and callback handler logic through mocked aiogram, simulated Telegram Bot API, preflight failures, occupied ports and tunnel lifecycle.
- No live users, Telegram messages, Google accounts or production data were accessed by tests. Real Telegram/aiogram and Windows integration still require user-side testing.

# Changelog — ТУРИСТ

## v0.6.0 — Pre-live QA and handover safety
- Pre-migration, read-only DB/bot-token identity guard; independent SQLite relative to app root.
- Google credentials path resolved from project root consistently.
- Idempotent retry status reflects actual application/booking status.
- WAL-safe backup of existing DB only, restore-check command with integrity and FK checks.
- Safer HTTP security headers; Uvicorn access logs with query strings disabled.
- Extended E2E signed-auth API and Chromium smoke: admin event creation/editing, staff roles and audit.
- Added FULL_QA_WINDOWS.bat and RESTORE_CHECK_WINDOWS.bat.
- 95 automated tests + local API smoke + Chromium checked offline.
- Live Telegram/Google/Windows Tunnel still needs testing with real accounts.

## v0.5.0
- Idempotency keys for game and billiard booking, timezone config, Mini App network errors.
- Telegram getMe/getWebhookInfo preflight, 429 backoff and error handling.
- 85 local tests.

## v0.4.0 and earlier
- Core Telegram bot, Mini App, admin panel, event logic and billiard booking.
- SQLite migrations, role model, signed initData, notification outbox and Google Sheets mirror.
