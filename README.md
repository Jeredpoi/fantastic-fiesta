# 📥 Telegram Video Downloader Bot

Бот для скачивания видео по ссылке: **YouTube, TikTok, Instagram, VK**.
Написан на [python-telegram-bot](https://python-telegram-bot.org/) v20+ и [yt-dlp](https://github.com/yt-dlp/yt-dlp).

## Возможности

- 🔗 Присылаете ссылку — получаете видео в чат
- 🧵 Очередь на `asyncio.Queue`: параллельные запросы не блокируют бота, число воркеров настраивается
- 🗜 Автосжатие через ffmpeg, если файл больше лимита Telegram (50 МБ)
- 📶 Живой статус с процентами: «В очереди» → «Скачиваю… 42% (12/28 МБ)» → «Сжимаю… 67%» → «Отправляю…» → «Готово»
- 🐘 Файлы до 2 ГБ через локальный [Bot API server](https://github.com/tdlib/telegram-bot-api) (опционально)
- 🎛 Inline-кнопки: меню, справка, личная статистика, отмена задачи в очереди
- 🧹 Автоматическая очистка временных файлов после отправки и при ошибках
- 🗄 Статистика скачиваний в SQLite (кто, что, когда, успех/ошибка)
- 🐢 Rate-limit: не больше N скачиваний в минуту на пользователя
- 🔄 Автообновление yt-dlp: бот сам замечает новую версию на PyPI, ставит её, дожидается конца активных загрузок и перезапускается
- 📝 Ошибки пишутся в `logs/errors.log`
- ⚙️ Вся конфигурация через `.env`
- 🚫 Понятные ответы на невалидные ссылки, приватные и удалённые видео

## Установка

Требования: Python 3.11+, установленный `ffmpeg` (и `ffprobe`) в PATH.

```bash
git clone https://github.com/Jeredpoi/fantastic-fiesta.git
cd fantastic-fiesta

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # и впишите BOT_TOKEN от @BotFather
```

## Запуск

```bash
python -m bot.main
```

## Конфигурация (.env)

| Переменная | По умолчанию | Описание |
|---|---|---|
| `BOT_TOKEN` | — | Токен бота от @BotFather (обязательно) |
| `TEMP_DIR` | `./tmp` | Куда качать временные файлы |
| `DB_PATH` | `./data/stats.db` | Файл SQLite со статистикой |
| `LOG_DIR` | `./logs` | Каталог логов (`errors.log` внутри) |
| `MAX_FILE_SIZE_MB` | `50` | Лимит размера файла; больше — сжимаем (50 МБ у официального API) |
| `RATE_LIMIT_PER_MINUTE` | `3` | Скачиваний в минуту на пользователя |
| `WORKERS` | `2` | Сколько видео скачивается одновременно |
| `MAX_DURATION_SEC` | `3600` | Максимальная длительность видео (0 — без лимита) |
| `BOT_API_URL` | — | Адрес локального Bot API server; пусто = официальный API |
| `SEND_TIMEOUT_SEC` | `300` | Таймаут отправки видео (увеличьте для больших файлов) |
| `UPDATE_CHECK_HOURS` | `24` | Как часто проверять обновления yt-dlp (0 — отключить) |

## Файлы больше 50 МБ (локальный Bot API server)

Официальный Bot API не даёт ботам отправлять файлы больше 50 МБ. Обойти лимит
можно, подняв свой [telegram-bot-api server](https://github.com/tdlib/telegram-bot-api) —
через него боты отправляют до **2 ГБ**.

1. Получите `api_id` и `api_hash` на [my.telegram.org](https://my.telegram.org).
2. Запустите сервер (проще всего в Docker):

   ```bash
   docker run -d --name tg-bot-api -p 8081:8081 \
     -e TELEGRAM_API_ID=<api_id> -e TELEGRAM_API_HASH=<api_hash> \
     -v tg-bot-api-data:/var/lib/telegram-bot-api \
     aiogram/telegram-bot-api:latest
   ```

3. В `.env` укажите:

   ```env
   BOT_API_URL=http://127.0.0.1:8081
   MAX_FILE_SIZE_MB=2000
   SEND_TIMEOUT_SEC=1800
   ```

После этого сжатие будет включаться только для файлов больше 2 ГБ, а видео
уходит через ваш сервер. Важно: токен бота начинает «жить» на локальном
сервере; чтобы вернуться на официальный API, вызовите у сервера `logOut`.

## Запуск на Replit

В репозитории уже лежат `.replit` и `replit.nix` (ffmpeg ставится автоматически).

1. На [replit.com](https://replit.com): **Create Repl → Import from GitHub** → укажите этот репозиторий.
2. Во вкладке **Secrets** (🔒) добавьте секрет `BOT_TOKEN` с токеном от @BotFather
   (файл `.env` на Replit не нужен — секреты попадают в переменные окружения).
3. В консоли (Shell): `pip install -r requirements.txt`.
4. Нажмите **Run** — бот запустится для проверки.
5. Чтобы бот работал 24/7, нажмите **Deploy → Reserved VM** (подписка Replit Core):
   без деплоя Repl засыпает через несколько минут после закрытия вкладки.

## Структура проекта

```
bot/
├── main.py        # точка входа, сборка приложения, логирование
├── config.py      # чтение .env
├── handlers.py    # команды, ссылки, inline-кнопки
├── keyboards.py   # клавиатуры
├── worker.py      # очередь и воркеры (скачать → сжать → отправить)
├── downloader.py  # yt-dlp: скачивание и валидация ссылок
├── compressor.py  # ffmpeg: сжатие под лимит Telegram
├── ratelimit.py   # лимит запросов на пользователя
├── updater.py     # автообновление yt-dlp с перезапуском
└── db.py          # статистика в SQLite
```
