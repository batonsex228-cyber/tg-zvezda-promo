# ДЗЛ «Звёздочка»: GitHub -> GHCR -> Docker на сервере

**Релиз:** Telegram v1.0.5 (Semantic KB + Cloudflare Bot API). VK-проект не заменяется.

Этот документ описывает ПУБЛИКАЦИЮ через GitHub Container Registry (`ghcr.io`), а не Docker Hub. Образ собирается автоматически через GitHub Actions после push в `main` и успешных тестов.

## 0. Что уже подготовлено в ZIP

- `Dockerfile`: Linux Python 3.12, установка зависимостей, запуск `python -m app.main`, процесс без root.
- `.dockerignore`: не отправлять в сборку секреты и рабочую базу.
- `compose.yaml`: серверный запуск из готового GHCR-образа; `restart: unless-stopped`; постоянный volume для SQLite и знаний.
- `.github/workflows/publish-ghcr.yml`: 9 проверок (7 групп Telegram-тестов, Google Apps Script и Docker release check), затем сборка и публикация образа `linux/amd64` и `linux/arm64`.
- `.env.example`: пример настроек; **не является секретным**; реальные значения заполняются только на сервере в `.env`.
- `scripts/docker_release_check.py`: офлайн-проверка состава релиза.

Важное ограничение: без Docker Engine нельзя окончательно подтвердить реальный `docker build` и подключение к Telegram. Зелёная GitHub Actions и серверный тест обязательны до того, как считать развёртывание рабочим.

## 1. Используйте существующий Telegram-репозиторий

Рабочий репозиторий: `https://github.com/batonsex228-cyber/tg-zvezda-promo`.

**Не создавайте второй репозиторий и не обновляйте VK-проект `zvezdochka-bot-prod`.**
Откройте Codespaces этого Telegram-репозитория или его локальную копию. Если в репозитории есть свои изменения после v1.0.4, предварительно сохраните их и сверьте с PATCH.

## 2. Загрузите подготовленный ZIP в Codespaces

Рекомендуется PATCH `ZVEZDOCHKA_TELEGRAM_DOCKER_v1_0_5_CLOUDFLARE_PATCH_FROM_v1_0_4.zip` поверх существующей v1.0.4. Перетащите его в корень проекта слева в VS Code. Откройте терминал Codespaces и выполните:

```bash
pwd
ls *.zip
unzip -o ZVEZDOCHKA_TELEGRAM_DOCKER_v1_0_5_CLOUDFLARE_PATCH_FROM_v1_0_4.zip -d .
rm ZVEZDOCHKA_TELEGRAM_DOCKER_v1_0_5_CLOUDFLARE_PATCH_FROM_v1_0_4.zip
ls -la Dockerfile compose.yaml .dockerignore .env.example .github/workflows
```

Если имя загруженного архива другое, сначала подставьте фактическое имя из `ls *.zip`.

## 3. Протестируйте в Codespaces, не запуская Telegram polling

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
node google_apps_script/self_test.js
```

Ни один из этих тестов не требует реального токена бота и не должен запускать второй Telegram polling.

Перед коммитом:

```bash
git status --short
```

**Не должно быть** `.env`, `runtime/`, `.venv/`, токенов или SQLite-файлов. Не копируйте секреты из Windows в Codespaces.

## 4. Отправьте в GitHub

```bash
git add -A
git diff --cached --name-only
git commit -m "Telegram v1.0.5 Cloudflare Bot API relay"
git push origin main
```

Проверьте, что в списке коммита нет `.env`, `runtime`, `.venv`, `.tools`, персональных данных и файлов с токенами. Если они случайно оказались в индексе, отмените `git add` и удалите их из набора для коммита **до push**.

## 5. Дождитесь GitHub Actions

1. Откройте вкладку **Actions** нового репозитория.
2. Workflow: **Telegram bot - tests and GHCR Docker image**.
3. Посмотрите последний запуск. Он должен стать **зелёным**.
4. При успехе появится образ:

```text
ghcr.io/batonsex228-cyber/tg-zvezda-promo:latest
```

Также будут теги `:v1.0.5` и `:sha-<FULL_COMMIT_SHA>`. Точный адрес зависит от созданного Вами репозитория; реальную ссылку можно посмотреть в Packages.

Если workflow не стартовал, проверьте, разрешены ли Actions для репозитория. Если нет прав на публикацию, проверьте в Settings -> Actions -> General права `GITHUB_TOKEN`/разрешения workflow и настройки пакета; workflow явно запрашивает `packages: write`.

## 6. Откройте доступ к Docker-образу

Зайдите в GitHub -> Ваш профиль -> **Packages** -> `tg-zvezda-promo` -> **Package settings**. Укажите видимость **Public**, если хотите, чтобы друг мог скачивать образ без GitHub-токена. Новый GHCR-пакет может быть приватным, даже если репозиторий публичный. Для приватного пакета потребуются соответствующие права и авторизация Docker на сервере.

ДРУГУ передаёте ссылку на репозиторий:

```text
https://github.com/batonsex228-cyber/tg-zvezda-promo
```

и адрес готового Docker-образа:

```text
ghcr.io/batonsex228-cyber/tg-zvezda-promo:latest
```

Ни одна из этих ссылок ещё не существует, пока Вы не создадите репозиторий и не опубликуете образ.

## 7. Инструкция другу (Linux VPS с Docker Compose v2)

Перед переносом **остановите Telegram-бота на Windows** (закройте BAT/`Ctrl+C`), иначе оба экземпляра одного токена начнут конфликтовать из-за `getUpdates`.

На сервере:

```bash
git clone https://github.com/batonsex228-cyber/tg-zvezda-promo.git
cd zvezdochka-telegram-bot
cp .env.example .env
nano .env
```

В `.env` заполните минимум:

```dotenv
TELEGRAM_BOT_TOKEN=ВАШ_ТОКЕН_ОТ_BOTFATHER
BOT_IMAGE=ghcr.io/batonsex228-cyber/tg-zvezda-promo:latest
TELEGRAM_MANAGER_USER_ID=0
TELEGRAM_API_BASE_URL=https://telegram-api-proxy.aleksejnazarov93583.workers.dev
TELEGRAM_RELAY_KEY=
```

Чтобы работали уведомления менеджера и заявки с персональными данными, вместо `0` укажите числовой Telegram ID менеджера. Менеджер сначала должен открыть этого бота и написать `/start`; свой ID он узнает командой `/id`.

Затем:

```bash
docker compose pull
docker compose up -d
docker compose ps
docker compose logs --tail=100 -f
```

Ожидайте строки `Telegram API: OK` и `BOT STARTED`. Реальный тест: напишите `/start` в Telegram, задайте вопрос о скидке, затем «Спасибо», проверьте Reply и реакцию ❤️. Если менеджер настроен, проверьте передачу вопроса специалисту и заявку на смену.

**Порты открывать не нужно**: это Telegram long polling, не webhook. `compose.yaml` не публикует ни одного TCP-порта.

### Обновление позже

После следующего push и зелёной GitHub Actions на сервере:

```bash
docker compose pull
docker compose up -d
docker compose logs --tail=50
```

Данные в Docker volume сохраняются. Не выполняйте `docker compose down -v` и не удаляйте volume, если хотите сохранить заявки/историю.

### Если бот уже работает на другой машине

Один токен Telegram можно использовать только в **одном активном polling-процессе**. Остановите старый экземпляр до старта контейнера. Если был настроен Telegram webhook, этот адаптер при запуске запрашивает `deleteWebhook` для перехода на polling.

### Google Apps Script / бронирование

Стандартный запуск без Google таблицы:

```dotenv
BOOKINGS_ENABLED=false
SHIFT_BOOKINGS_ENABLED=true
SHIFT_EXPORT_PII_TO_GOOGLE=false
```

В этом режиме заявки на смены записываются локально в SQLite и отправляются указанному менеджеру. Для живого календаря бронирований требуется `BOOKING_API_URL`, `BOOKING_API_SECRET`, `BOOKINGS_ENABLED=true` и корректная настройка Google Apps Script. **Не используйте одну и ту же таблицу одновременно для VK и Telegram без разделения идентификаторов платформ.**

### Локальная база Windows

Этот Docker-развёртывание создаёт новую базу в постоянном volume. Если нужно перенести уже накопленные на Windows заявки/настройки, это отдельная миграция с остановкой бота и безопасным копированием `runtime`; не отправляйте файлы с данными родителей в GitHub.

### Безопасность

- `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, `BOOKING_API_SECRET` хранить только в серверном `.env` (или secret manager). Не публиковать в GitHub/ZIP/сообщениях.
- Не пересылать публично полную SQLite-базу; там могут находиться ФИО, даты рождения и телефоны.
- Если бот передаётся третьему лицу, согласуйте с администрацией лагеря доступ к персональным данным, резервное копирование и место хранения.
- Для одного бота запускайте один контейнер/одну реплику, иначе возможна ошибка Telegram `409 Conflict`.

## 8. Диагностика

```bash
docker compose ps
docker compose logs --tail=150
```

- `Telegram bot token` -> проверьте `TELEGRAM_BOT_TOKEN` без кавычек и пробелов.
- `409 Conflict` -> работает второй экземпляр Windows/Docker/другой сервер.
- `manifest unknown` / `denied` -> нет опубликованного образа, неправильный `BOT_IMAGE` либо пакет приватный.
- `permission denied` на SQLite -> проверьте права постоянного volume; контейнер работает от UID 10001.
- Нет заявок менеджеру -> настройте `TELEGRAM_MANAGER_USER_ID`, выполните `/start` с менеджерского аккаунта и перезапустите.


## Обновление v1.0.5: Cloudflare Worker для Telegram API

Рабочий репозиторий: `https://github.com/batonsex228-cyber/tg-zvezda-promo`.
Образ после успешной публикации: `ghcr.io/batonsex228-cyber/tg-zvezda-promo:latest`.

В **серверном** `.env` (не коммитить!) добавьте:

```dotenv
TELEGRAM_API_BASE_URL=https://telegram-api-proxy.aleksejnazarov93583.workers.dev
TELEGRAM_RELAY_KEY=
```

Если Cloudflare Worker защищён секретом `RELAY_KEY`, укажите то же значение в `TELEGRAM_RELAY_KEY` (оно пойдёт заголовком `X-Relay-Key`). Если Worker другой и не поддерживает этот заголовок, оставьте поле пустым. Секрет нельзя вставлять в `.env.example`, код или логи.

1. Загрузите обновлённый код в `main`. Проверьте зелёный GitHub Actions (`Telegram bot - tests and GHCR Docker image`).
2. На сервере Миши: `cd tg-zvezda-promo && git pull --ff-only`.
3. На сервере: `nano .env` и добавьте URL выше. Проверьте `BOT_IMAGE=ghcr.io/batonsex228-cyber/tg-zvezda-promo:latest` и реальный `TELEGRAM_BOT_TOKEN`.
4. Остановите старый экземпляр с этим токеном на Windows или в другом контейнере.
5. Обновите и запустите: `docker compose pull && docker compose up -d`.
6. Проверьте: `docker compose ps && docker compose logs --tail=100 -f`.

Загрузка одного `.env.example` на GitHub **не изменяет серверные переменные**. В логах должен быть `Telegram transport: Cloudflare/HTTPS relay` и затем `Telegram API: OK`. Если видите `401/403`, проверьте настройки Worker и секрет. Если `Non-JSON` / 404, возможно, Worker не пересылает `/bot<TOKEN>/<method>`; если тайм-ауты, проверьте долгие запросы `getUpdates`. Не публикуйте рабочий Telegram-токен в адресной строке браузера.

**Проверка безопасности:** Worker получает токен бота и содержимое запросов, а в сообщениях лагеря могут находиться данные родителей и детей. Прежде чем включать заявки, согласуйте с администрацией применимость 152-ФЗ, трансграничную передачу, логи и политику хранения. Точный Worker код в этом релизе не представлен и потому не проверен.
