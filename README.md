# 📥 Telegram Video Downloader Bot

Бот для скачивания видео по ссылке: **YouTube, TikTok, Instagram, VK**.
Написан на [python-telegram-bot](https://python-telegram-bot.org/) v20+ и [yt-dlp](https://github.com/yt-dlp/yt-dlp).

## Возможности

- 🔗 Присылаете ссылку — получаете видео в чат
- 🧵 Очередь на `asyncio.Queue`: параллельные запросы не блокируют бота, число воркеров настраивается
- 🗜 Автосжатие через ffmpeg, если файл больше лимита Telegram (50 МБ)
- 📶 Живой статус: «В очереди» → «Скачиваю…» → «Сжимаю…» → «Отправляю…» → «Готово»
- 🎛 Inline-кнопки: меню, справка, личная статистика, отмена задачи в очереди
- 🧹 Автоматическая очистка временных файлов после отправки и при ошибках
- 🗄 Статистика скачиваний в SQLite (кто, что, когда, успех/ошибка)
- 🐢 Rate-limit: не больше N скачиваний в минуту на пользователя
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
| `MAX_FILE_SIZE_MB` | `50` | Лимит размера файла (лимит Telegram для ботов) |
| `RATE_LIMIT_PER_MINUTE` | `3` | Скачиваний в минуту на пользователя |
| `WORKERS` | `2` | Сколько видео скачивается одновременно |
| `MAX_DURATION_SEC` | `3600` | Максимальная длительность видео (0 — без лимита) |

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
└── db.py          # статистика в SQLite
```
