# Установка двух Telegram-ботов через один GitHub -> GHCR -> Docker

## Часть A. Обновление имеющегося GitHub (Вы, Codespaces)

Репозиторий: https://github.com/batonsex228-cyber/tg-zvezda-promo
ВАЖНО: при переходе на двухботную структуру недостаточно обычного `unzip -o`:
корневые файлы старой сборки надо безопасно заменить, оставив историю Git.

1. Откройте **тот же Codespace** репозитория и терминал.
2. Убедитесь, что предыдущая версия уже закоммичена:

   ```bash
   cd /workspaces/tg-zvezda-promo
   git status
   git branch --show-current
   ```

   Должно быть `main` и не должно быть незакоммиченных изменений проекта.

3. Скачайте **ZIP `DZL_ZVEZDOCHKA_TOURIST_DOCKER_DUAL_GITHUB.zip`** из этого ответа,
   перетащите в корень Codespaces (в левую панель файлов).
4. Распакуйте его только во временную папку:

   ```bash
   mkdir -p _dual_import
   unzip -q DZL_ZVEZDOCHKA_TOURIST_DOCKER_DUAL_GITHUB.zip -d _dual_import
   ```

5. Установите новый проект поверх старого с резервной веткой и сохранением `.git`:

   ```bash
   python3 _dual_import/scripts/migrate_existing_repo.py _dual_import
   ```

   Скрипт откажется работать, если текущие отслеживаемые файлы изменены, или
   если новая версия может перезаписать неизвестный локальный файл. Он создаст
   отдельную ветку `backup-before-dual-...` и НЕ сделает коммит/пуш сам.

6. Очистите временную папку и запустите проверку:

   ```bash
   rm -rf _dual_import
   python3 -m pip install PyYAML
   python3 scripts/dual_release_check.py
   git status
   ```

7. Прочитайте `git status` и убедитесь, что ни токены, ни `.env`, ни локальные
   базы, ни скачанный архив не готовятся к отправке. Затем:

   ```bash
   git add -A
   git diff --cached --name-only
   git commit -m "Two Telegram demos: Zvezdochka and Tourist with Cloudflare"
   git push origin main
   ```

8. Откройте https://github.com/batonsex228-cyber/tg-zvezda-promo/actions
   и найдите зелёную галочку `Dual Telegram bots - tests and GHCR`.
   **До зелёной галочки нельзя считать Docker-образы готовыми.**

## Часть B. Docker-образы

Workflow публикует два тега в **одном GHCR-пакете**:

```text
ghcr.io/batonsex228-cyber/tg-zvezda-promo:zvezdochka-latest
ghcr.io/batonsex228-cyber/tg-zvezda-promo:tourist-latest
```

Сразу после `push` это только ожидаемые имена; проверьте фактическую публикацию
в GitHub Actions/Packages. Пакет GHCR должен быть публичным либо Миша должен
войти в registry через GitHub PAT с правом `read:packages`.

## Часть C. Запуск у Миши (Ubuntu/Debian, Docker Engine + Compose plugin)

Нужен DNS A/AAAA-запись `TOURIST_DOMAIN` на IP VPS; откройте 80/tcp и 443/tcp
(и опционально 443/udp). Если порты заняты другим reverse proxy, интегрируйте
`tourist:8000` в существующий маршрутизатор вместо второго Caddy.

```bash
git clone https://github.com/batonsex228-cyber/tg-zvezda-promo.git
cd tg-zvezda-promo
cp .env.example .env
chmod 600 .env
nano .env
```

В `.env` установите **два разных токена** и настройки:

```dotenv
ZVEZDOCHKA_IMAGE=ghcr.io/batonsex228-cyber/tg-zvezda-promo:zvezdochka-latest
TOURIST_IMAGE=ghcr.io/batonsex228-cyber/tg-zvezda-promo:tourist-latest
ZVEZDOCHKA_BOT_TOKEN=<первый токен из BotFather>
TOURIST_BOT_TOKEN=<второй токен из BotFather>
ZVEZDOCHKA_MANAGER_ID=0
TOURIST_OWNER_ID=<Ваш числовой Telegram ID>
TOURIST_DOMAIN=<поддомен, например tourist.example.ru>
TELEGRAM_API_BASE_URL=https://telegram-api-proxy.aleksejnazarov93583.workers.dev
TELEGRAM_RELAY_KEY=
```

- `ZVEZDOCHKA_MANAGER_ID` нужен для получения заявок, `0` - ограниченный FAQ-режим.
- `TOURIST_OWNER_ID` обязателен: он защищает админ-панель «Туриста».
- `TOURIST_DOMAIN` обязателен: Mini App требует публичный HTTPS.
- `TELEGRAM_RELAY_KEY` заполняют, только если Worker требует `X-Relay-Key`.
- Секреты держать только в серверном `.env`, не добавлять в репозиторий.
- Прежние Windows-копии обоих ботов с этими токенами надо остановить,
  иначе Telegram long polling будет конфликтовать.

Для диагностики конфигурации не публикуйте вывод `docker compose config`,
потому что он может раскрыть токены и другие секреты.

Далее:

```bash
docker compose pull
docker compose up -d
docker compose ps
docker compose logs --tail=80 zvezdochka tourist caddy
```

Проверка Mini App:

```bash
curl -fsS https://<ваш-домен>/ready
```

Затем в личных чатах с каждым ботом отправьте `/start` и проверьте раздельно:
- Звёздочка: FAQ, новая заявка на смену, уведомление менеджеру.
- Турист: `/id`, `/schedule`, `/app`, вход в Mini App, запись, действия владельца.

Если Cloudflare возвращает HTTP 401/403, проверьте пароль Worker; если 404/502 -
маршрут `/bot<TOKEN>/method` и `getUpdates` в Worker. Наличие `/health` у
Worker подтверждает только доступность его адреса, а не Telegram Bot API.

## Данные и безопасность

У обоих сервисов собственные постоянные тома: `zvezdochka_runtime` и
`tourist_runtime`; отдельный `tourist_backups`. `docker compose down -v`
**нельзя использовать на рабочем сервере**: это удалит локальные базы.
Перенос базы с Windows автоматически не происходит. Для продакшена нужны
бэкапы томов и продуманное восстановление. Через Cloudflare проходит
содержимое Telegram-сообщений (включая персональные данные, если люди их
отправляют): согласуйте это с ответственным за ПДн и исключите запись
чувствительных URL/данных в логи Worker.

## Откат

`git push` меняет исходники, а запущенный Docker обновляется только после
`docker compose pull && docker compose up -d` у Миши.
Старую одиночную версию хранит созданная backup-ветка; для восстановления
применяйте соответствующий прежний Compose и сохранённые базы данных.

### Известные ограничения этой сборки

- Docker Engine здесь не был доступен: реальную сборку и работу двух
  контейнеров в одной сети проверит GitHub Actions и затем сервер Миши.
- Тесты Telegram API не использовали реальных BotFather-токенов.
- Для «Туриста» без DNS, HTTPS и корректного OWNER_ID
  production-режим специально откажется запускаться.
- Cloudflare Worker не является прокси для сайта Mini App.
