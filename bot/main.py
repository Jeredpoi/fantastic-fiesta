"""Точка входа: сборка приложения и запуск polling."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
from pathlib import Path

from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from . import handlers
from .config import Config, load_config
from .db import StatsDB
from .ratelimit import RateLimiter
from .updater import RESTART_FLAG, auto_update_loop
from .worker import DownloadQueue

logger = logging.getLogger(__name__)


def setup_logging(log_dir: Path) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx на каждый getUpdates пишет INFO — шумно
    logging.getLogger("httpx").setLevel(logging.WARNING)

    error_file = logging.FileHandler(log_dir / "errors.log", encoding="utf-8")
    error_file.setLevel(logging.ERROR)
    error_file.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logging.getLogger().addHandler(error_file)


async def on_startup(app: Application) -> None:
    db: StatsDB = app.bot_data["db"]
    await db.open()
    queue: DownloadQueue = app.bot_data["queue"]
    queue.start(app)
    cfg: Config = app.bot_data["cfg"]
    if cfg.update_check_hours > 0:
        app.bot_data["updater_task"] = asyncio.create_task(
            auto_update_loop(app, cfg.update_check_hours), name="yt-dlp-updater"
        )
    logger.info("Бот запущен, воркеров: %d", cfg.workers)


async def on_shutdown(app: Application) -> None:
    updater_task: asyncio.Task | None = app.bot_data.get("updater_task")
    if updater_task is not None:
        updater_task.cancel()
    queue: DownloadQueue = app.bot_data["queue"]
    await queue.stop()
    db: StatsDB = app.bot_data["db"]
    await db.close()
    # подчищаем недокачанные файлы
    cfg: Config = app.bot_data["cfg"]
    shutil.rmtree(cfg.temp_dir, ignore_errors=True)
    logger.info("Бот остановлен.")


def build_application(cfg: Config) -> Application:
    builder = (
        ApplicationBuilder()
        .token(cfg.bot_token)
        .connect_timeout(30)
        .read_timeout(60)
        .write_timeout(60)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
    )
    if cfg.bot_api_url:
        # локальный telegram-bot-api server: лимит на файлы вырастает до 2 ГБ
        builder = builder.base_url(f"{cfg.bot_api_url}/bot").base_file_url(
            f"{cfg.bot_api_url}/file/bot"
        )
        logger.info("Использую локальный Bot API server: %s", cfg.bot_api_url)
    app = builder.build()

    db = StatsDB(cfg.db_path)
    app.bot_data["cfg"] = cfg
    app.bot_data["db"] = db
    app.bot_data["queue"] = DownloadQueue(cfg, db)
    app.bot_data["limiter"] = RateLimiter(cfg.rate_limit_per_minute)

    app.add_handler(CommandHandler("start", handlers.cmd_start))
    app.add_handler(CommandHandler("help", handlers.cmd_help))
    app.add_handler(CallbackQueryHandler(handlers.handle_callback))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_message)
    )
    app.add_error_handler(handlers.on_error)
    return app


def main() -> None:
    cfg = load_config()
    setup_logging(cfg.log_dir)

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        logger.warning(
            "ffmpeg/ffprobe не найдены в PATH — сжатие больших файлов работать не будет!"
        )

    app = build_application(cfg)
    app.run_polling(allowed_updates=["message", "callback_query"])

    if app.bot_data.get(RESTART_FLAG):
        logger.info("Перезапускаюсь с обновлённым yt-dlp…")
        os.execv(sys.executable, [sys.executable, "-m", "bot.main"])


if __name__ == "__main__":
    sys.exit(main())
