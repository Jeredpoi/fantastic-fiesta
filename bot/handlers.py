"""Хендлеры Telegram: команды, сообщения со ссылками, inline-кнопки."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from . import keyboards
from .config import Config
from .db import StatsDB
from .downloader import extract_supported_url
from .ratelimit import RateLimiter
from .worker import DownloadQueue, Job

logger = logging.getLogger(__name__)

WELCOME = (
    "👋 <b>Привет! Я качаю видео по ссылке.</b>\n\n"
    "Поддерживаю: YouTube, TikTok, Instagram, VK.\n"
    "Просто пришлите ссылку на видео — остальное я сделаю сам."
)

HELP = (
    "📥 <b>Как скачать видео</b>\n\n"
    "1. Скопируйте ссылку на видео (YouTube, TikTok, Instagram, VK)\n"
    "2. Пришлите её мне обычным сообщением\n"
    "3. Дождитесь статуса: скачиваю → сжимаю (если нужно) → отправляю\n\n"
    "⚠️ Ограничения:\n"
    "• файлы больше {limit} МБ автоматически сжимаются\n"
    "• не больше {rate} скачиваний в минуту\n"
    "• приватные видео и прямые трансляции недоступны"
)

INVALID_LINK = (
    "🤔 Не вижу подходящей ссылки.\n\n"
    "Пришлите ссылку на видео с YouTube, TikTok, Instagram или VK, например:\n"
    "<code>https://youtu.be/dQw4w9WgXcQ</code>"
)


def _cfg(context: ContextTypes.DEFAULT_TYPE) -> Config:
    return context.bot_data["cfg"]


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(WELCOME, reply_markup=keyboards.main_menu())


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = _cfg(context)
    await update.message.reply_html(
        HELP.format(limit=cfg.max_file_size_mb, rate=cfg.rate_limit_per_minute),
        reply_markup=keyboards.back_to_menu(),
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None or not message.text:
        return

    url = extract_supported_url(message.text)
    if url is None:
        await message.reply_html(INVALID_LINK, reply_markup=keyboards.main_menu())
        return

    queue: DownloadQueue = context.bot_data["queue"]
    if queue.draining:
        await message.reply_html(
            "🔄 Бот обновляется и сейчас перезапустится. Попробуйте через минуту."
        )
        return

    limiter: RateLimiter = context.bot_data["limiter"]
    wait = limiter.check(message.from_user.id)
    if wait > 0:
        await message.reply_html(
            f"🐢 Слишком часто! Подождите ещё <b>{int(wait) + 1} сек.</b>",
        )
        return

    status = await message.reply_html("⏳ Добавляю в очередь…")
    job = Job(
        chat_id=message.chat_id,
        user_id=message.from_user.id,
        username=message.from_user.username,
        url=url,
        status_message_id=status.message_id,
    )
    position = queue.put(job)
    await status.edit_text(
        f"⏳ В очереди, позиция: <b>{position}</b>",
        parse_mode="HTML",
        reply_markup=keyboards.cancel_job(job.id),
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data or ""
    cfg = _cfg(context)

    if data == keyboards.CB_HOME:
        await query.answer()
        await query.edit_message_text(
            WELCOME, parse_mode="HTML", reply_markup=keyboards.main_menu()
        )

    elif data == keyboards.CB_HELP:
        await query.answer()
        await query.edit_message_text(
            HELP.format(limit=cfg.max_file_size_mb, rate=cfg.rate_limit_per_minute),
            parse_mode="HTML",
            reply_markup=keyboards.back_to_menu(),
        )

    elif data == keyboards.CB_STATS:
        db: StatsDB = context.bot_data["db"]
        ok, err, last = await db.user_stats(query.from_user.id)
        await query.answer()
        last_line = f"\nПоследнее: <code>{last}</code>" if last else ""
        await query.edit_message_text(
            f"📊 <b>Ваша статистика</b>\n\n"
            f"✅ Успешных скачиваний: <b>{ok}</b>\n"
            f"⚠️ Неудачных: <b>{err}</b>{last_line}",
            parse_mode="HTML",
            reply_markup=keyboards.back_to_menu(),
        )

    elif data.startswith(keyboards.CB_CANCEL_PREFIX):
        job_id = data[len(keyboards.CB_CANCEL_PREFIX):]
        queue: DownloadQueue = context.bot_data["queue"]
        if queue.cancel(job_id, query.from_user.id):
            await query.answer("Отменяю…")
            await query.edit_message_text("❌ Скачивание отменено.")
        else:
            await query.answer("Задачу уже нельзя отменить.", show_alert=True)

    else:
        await query.answer()


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Ошибка при обработке апдейта: %s", update, exc_info=context.error)
