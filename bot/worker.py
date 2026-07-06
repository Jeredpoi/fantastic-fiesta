"""Очередь задач: воркеры качают, сжимают и отправляют видео."""

from __future__ import annotations

import asyncio
import html
import logging
import shutil
import uuid
from dataclasses import dataclass, field

from telegram import Bot
from telegram.error import TelegramError, NetworkError, TimedOut
from telegram.ext import Application

from .compressor import CompressError, compress_to_limit
from .config import Config
from .db import StatsDB
from .downloader import DownloadError, ProgressState, download_video
from .keyboards import main_menu

# как часто обновляем статусное сообщение (Telegram не любит частые edit)
PROGRESS_INTERVAL_SEC = 2.5


def _format_progress(label: str, state: ProgressState) -> str:
    if state.percent is not None:
        text = f"{label} {state.percent:.0f}%"
        if state.total:
            text += f" ({state.downloaded / 1048576:.1f}/{state.total / 1048576:.1f} МБ)"
        return text
    if state.downloaded:
        return f"{label} {state.downloaded / 1048576:.1f} МБ"
    return f"{label}…"

logger = logging.getLogger(__name__)


@dataclass
class Job:
    chat_id: int
    user_id: int
    username: str | None
    url: str
    status_message_id: int
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    cancelled: bool = False
    started: bool = False


class DownloadQueue:
    """asyncio.Queue + реестр задач (для кнопки «Отменить»)."""

    def __init__(self, cfg: Config, db: StatsDB):
        self._cfg = cfg
        self._db = db
        self._queue: asyncio.Queue[Job] = asyncio.Queue()
        self._jobs: dict[str, Job] = {}
        self._workers: list[asyncio.Task] = []
        # True во время обновления: новые задачи не принимаются
        self.draining = False

    def start(self, app: Application) -> None:
        for i in range(self._cfg.workers):
            task = app.create_task(self._worker(app.bot), name=f"download-worker-{i}")
            self._workers.append(task)

    async def stop(self) -> None:
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def wait_idle(self) -> None:
        """Ждёт, пока очередь опустеет и все взятые задачи завершатся."""
        await self._queue.join()

    def put(self, job: Job) -> int:
        """Ставит задачу в очередь, возвращает позицию (1 = следующая)."""
        self._jobs[job.id] = job
        self._queue.put_nowait(job)
        return self._queue.qsize()

    def cancel(self, job_id: str, user_id: int) -> bool:
        """Помечает задачу отменённой.

        Работает только для её владельца и только пока она ждёт в очереди.
        """
        job = self._jobs.get(job_id)
        if job is None or job.user_id != user_id or job.started:
            return False
        job.cancelled = True
        return True

    async def _edit_status(self, bot: Bot, job: Job, text: str, keyboard=None) -> None:
        try:
            await bot.edit_message_text(
                chat_id=job.chat_id,
                message_id=job.status_message_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        except TelegramError:
            # сообщение могли удалить или текст не изменился — статус не критичен
            pass

    async def _progress_updater(self, bot: Bot, job: Job, label: str, state: ProgressState) -> None:
        """Фоново обновляет статусное сообщение, пока идёт скачивание/сжатие."""
        last_text = ""
        while True:
            await asyncio.sleep(PROGRESS_INTERVAL_SEC)
            text = _format_progress(label, state)
            if text != last_text:
                last_text = text
                await self._edit_status(bot, job, text)

    async def _with_progress(self, bot: Bot, job: Job, label: str, state: ProgressState, coro):
        """Выполняет coro, параллельно показывая прогресс из state."""
        task = asyncio.ensure_future(coro)
        updater = asyncio.ensure_future(self._progress_updater(bot, job, label, state))
        await self._edit_status(bot, job, f"{label}…")
        try:
            return await task
        finally:
            updater.cancel()

    async def _worker(self, bot: Bot) -> None:
        while True:
            job = await self._queue.get()
            try:
                await self._process(bot, job)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Необработанная ошибка воркера (url=%s)", job.url)
                await self._edit_status(
                    bot, job, "⚠️ Внутренняя ошибка. Попробуйте позже.", main_menu()
                )
                await self._db.record(job.user_id, job.username, job.url, "error")
            finally:
                self._jobs.pop(job.id, None)
                self._queue.task_done()

    async def _process(self, bot: Bot, job: Job) -> None:
        if job.cancelled:
            await self._edit_status(bot, job, "❌ Скачивание отменено.", main_menu())
            return
        job.started = True

        job_dir = self._cfg.temp_dir / job.id
        try:
            dl_state = ProgressState()
            result = await self._with_progress(
                bot, job, "⏬ Скачиваю видео",
                dl_state,
                download_video(job.url, job_dir, self._cfg.max_duration_sec, dl_state),
            )

            path = result.path
            compress_warning: str | None = None
            if path.stat().st_size > self._cfg.max_file_size_bytes:
                size_mb = path.stat().st_size / 1024 / 1024
                cmp_state = ProgressState()

                def _on_compress(percent: float) -> None:
                    cmp_state.percent = percent

                try:
                    path = await self._with_progress(
                        bot, job, f"🗜 Файл {size_mb:.0f} МБ — сжимаю",
                        cmp_state,
                        compress_to_limit(path, self._cfg.max_file_size_bytes, _on_compress),
                    )
                except CompressError as exc:
                    if not self._cfg.bot_api_url:
                        # официальный API всё равно отвергнет файл больше лимита —
                        # честнее сразу показать причину, чем ждать отказа Telegram
                        raise
                    logger.warning("Сжатие не удалось (url=%s): %s — отправляю оригинал", job.url, exc)
                    compress_warning = str(exc)
                    # path остаётся оригинальным файлом

            await self._edit_status(bot, job, "📤 Отправляю…")
            size = path.stat().st_size
            caption = result.title[:900]
            if compress_warning:
                caption += f"\n\n⚠️ Сжать не удалось, отправляю оригинал ({size / 1048576:.0f} МБ)."
            try:
                with path.open("rb") as fh:
                    await bot.send_video(
                        chat_id=job.chat_id,
                        video=fh,
                        caption=caption,
                        supports_streaming=True,
                        read_timeout=self._cfg.send_timeout_sec,
                        write_timeout=self._cfg.send_timeout_sec,
                    )
            except (TimedOut, NetworkError) as exc:
                raise CompressError(
                    "Не удалось отправить видео — проблема с сетью. Попробуйте ещё раз."
                ) from exc
            except TelegramError as exc:
                raise CompressError(
                    f"Telegram отклонил файл: {exc.message}"
                ) from exc
            await self._edit_status(bot, job, "✅ Готово! Пришлите следующую ссылку.", main_menu())
            await self._db.record(job.user_id, job.username, job.url, "ok", size)

        except (DownloadError, CompressError) as exc:
            logger.error("Задача не выполнена (url=%s): %s", job.url, exc)
            await self._edit_status(bot, job, f"⚠️ {html.escape(str(exc))}", main_menu())
            await self._db.record(job.user_id, job.username, job.url, "error")
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)
