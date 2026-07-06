"""Inline-клавиатуры бота."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

CB_HELP = "menu:help"
CB_STATS = "menu:stats"
CB_HOME = "menu:home"
CB_CANCEL_PREFIX = "cancel:"  # cancel:<job_id>


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📥 Как скачать", callback_data=CB_HELP),
                InlineKeyboardButton("📊 Моя статистика", callback_data=CB_STATS),
            ],
        ]
    )


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Назад", callback_data=CB_HOME)]]
    )


def cancel_job(job_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Отменить", callback_data=CB_CANCEL_PREFIX + job_id)]]
    )
