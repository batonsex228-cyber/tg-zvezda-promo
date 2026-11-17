# ДЗЛ «Звёздочка»: GitHub -> GHCR -> Docker на сервере

**Релиз:** Telegram v1.0.4 (Semantic KB), Docker/GHCR пакет 1.0.4-docker1. VK-проект не заменяется.

Этот документ описывает ПУБЛИКАЦИЮ через GitHub Container Registry (`ghcr.io`), а не Docker Hub. Образ собирается автоматически через GitHub Actions после push в `main` и успешных тестов.

## 0. Что уже подготовлено в ZIP

- `Dockerfile`: Linux Python 3.12, установка зависимостей, запуск `python -m app.main`, процесс без root.
- `.dockerignore`: не отправлять в сборку секреты и рабочую базу.
- `compose.yaml`: серверный запуск из готового GHCR-образа; `restart: unless-stopped`; постоянный volume для SQLite и знаний.
- `.github/workflows/publish-ghcr.yml`: 8 проверок (6 групп Telegram-тестов, Google Apps Script и Docker release check), затем сборка и публикация образа `linux/amd64` и `linux/arm64`.
- `.env.example`: пример настроек; **не является секретным**; реальные значения заполняются только на сервере в `.env`.
- `scripts/docker_release_check.py`: офлайн-проверка состава релиза.

Важное ограничение: без Docker Engine нельзя окончательно подтвердить реальный `docker build` и подключение к Telegram. Зелёная GitHub Actions и серверный тест обязательны до того, как считать развёртывание рабочим.

## 1. Создайте НОВЫЙ репозиторий GitHub

Не заливайте эту сборку поверх существующего VK-репозитория `zvezdochka-bot-prod`.

1. В GitHub нажмите **New repository**.
2. Название: `zvezdochka-telegram-bot`.
3. Для самой простой передачи другу можно выбрать **Public**, но код будет общедоступен. Все секреты должны быть только в `.env` сервера. Если выбираете **Private**, для доступа к коду и образу потребуется выдать права отдельно.
4. Поставьте **Add a README file**, создайте репозиторий.
5. Откройте **Code -> Codespaces -> Create codespace on main**.

## 2. Загрузите подготовленный ZIP в Codespaces

Перетащите `ZVEZDOCHKA_TELEGRAM_DOCKER_GITHUB_v1_0_4_READY.zip` в корень проекта слева в VS Code. Откройте терминал Codespaces и выполните:

```bash
pwd
ls *.zip
unzip -o ZVEZDOCHKA_TELEGRAM_DOCKER_GITHUB_v1_0_4_READY.zip -d .
rm ZVEZDOCHKA_TELEGRAM_DOCKER_GITHUB_v1_0_4_READY.zip
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
git commit -m "Telegram v1.0.4 Docker GHCR release"
git push origin main
```

Проверьте, что в списке коммита нет `.env`, `runtime`, `.venv`, `.tools`, персональных данных и файлов с токенами. Если они случайно оказались в индексе, отмените `git add` и удалите их из набора для коммита **до push**.

## 5. Дождитесь GitHub Actions

1. Откройте вкладку **Actions** нового репозитория.
2. Workflow: **Telegram bot - tests and GHCR Docker image**.
3. Посмотрите последний запуск. Он должен стать **зелёным**.
4. При успехе появится образ:

```text
ghcr.io/<ВАШ_GITHUB_LOGIN>/zvezdochka-telegram-bot:latest
```

Также будут теги `:v1.0.4` и `:sha-<FULL_COMMIT_SHA>`. Точный адрес зависит от созданного Вами репозитория; реальную ссылку можно посмотреть в Packages.

Если workflow не стартовал, проверьте, разрешены ли Actions для репозитория. Если нет прав на публикацию, проверьте в Settings -> Actions -> General права `GITHUB_TOKEN`/разрешения workflow и настройки пакета; workflow явно запрашивает `packages: write`.

## 6. Откройте доступ к Docker-образу

Зайдите в GitHub -> Ваш профиль -> **Packages** -> `zvezdochka-telegram-bot` -> **Package settings**. Укажите видимость **Public**, если хотите, чтобы друг мог скачивать образ без GitHub-токена. Новый GHCR-пакет может быть приватным, даже если репозиторий публичный. Для приватного пакета потребуются соответствующие права и авторизация Docker на сервере.

ДРУГУ передаёте ссылку на репозиторий:

```text
https://github.com/<ВАШ_GITHUB_LOGIN>/zvezdochka-telegram-bot
```

и адрес готового Docker-образа:

```text
ghcr.io/<ВАШ_GITHUB_LOGIN>/zvezdochka-telegram-bot:latest
```

Ни одна из этих ссылок ещё не существует, пока Вы не создадите репозиторий и не опубликуете образ.

## 7. Инструкция другу (Linux VPS с Docker Compose v2)

Перед переносом **остановите Telegram-бота на Windows** (закройте BAT/`Ctrl+C`), иначе оба экземпляра одного токена начнут конфликтовать из-за `getUpdates`.

На сервере:

```bash
git clone https://github.com/<ВАШ_GITHUB_LOGIN>/zvezdochka-telegram-bot.git
cd zvezdochka-telegram-bot
cp .env.example .env
nano .env
```

В `.env` заполните минимум:

```dotenv
TELEGRAM_BOT_TOKEN=ВАШ_ТОКЕН_ОТ_BOTFATHER
BOT_IMAGE=ghcr.io/<ВАШ_GITHUB_LOGIN>/zvezdochka-telegram-bot:latest
TELEGRAM_MANAGER_USER_ID=0
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
