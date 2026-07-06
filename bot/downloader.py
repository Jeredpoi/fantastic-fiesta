"""Скачивание видео через yt-dlp."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

import yt_dlp


@dataclass
class ProgressState:
    """Текущий прогресс задачи. Пишется из рабочего потока, читается из event loop.

    Присваивание атрибутов атомарно под GIL, поэтому блокировка не нужна.
    """

    percent: float | None = None
    downloaded: int = 0
    total: int | None = None

SUPPORTED_HOSTS = (
    r"(?:www\.|m\.)?youtube\.com",
    r"youtu\.be",
    r"(?:www\.|vm\.|vt\.)?tiktok\.com",
    r"(?:www\.)?instagram\.com",
    r"(?:www\.|m\.)?vk\.com",
    r"vkvideo\.ru",
)

_URL_RE = re.compile(
    r"https?://(?:" + "|".join(SUPPORTED_HOSTS) + r")/\S+",
    re.IGNORECASE,
)


class DownloadError(Exception):
    """Ошибка скачивания с понятным пользователю текстом."""


@dataclass
class DownloadResult:
    path: Path
    title: str


def extract_supported_url(text: str) -> str | None:
    """Достаёт из текста первую ссылку на поддерживаемый сервис."""
    match = _URL_RE.search(text)
    return match.group(0) if match else None


def _classify_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if "private" in msg or "login" in msg or "sign in" in msg or "cookies" in msg:
        return "Видео приватное или требует входа в аккаунт — скачать не получится."
    if "unavailable" in msg or "removed" in msg or "not exist" in msg or "404" in msg:
        return "Видео недоступно: удалено, скрыто или ссылка битая."
    if "unsupported url" in msg:
        return "Эта ссылка не поддерживается."
    if "live" in msg:
        return "Прямые трансляции скачивать нельзя, дождитесь окончания."
    return "Не удалось скачать видео. Проверьте ссылку и попробуйте ещё раз."


async def download_video(
    url: str,
    job_dir: Path,
    max_duration_sec: int,
    progress: ProgressState | None = None,
) -> DownloadResult:
    """Скачивает видео в job_dir (каталог одной задачи, чистит его вызывающий код).

    Блокирующий yt-dlp уходит в отдельный поток.
    """
    job_dir.mkdir(parents=True, exist_ok=True)

    opts = {
        # mp4 до 1080p, чтобы файл сразу был поменьше и Telegram его проигрывал
        "format": "bv*[ext=mp4][height<=1080]+ba[ext=m4a]/b[ext=mp4]/b",
        "outtmpl": str(job_dir / "%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "max_downloads": 1,
        "socket_timeout": 30,
        "retries": 3,
    }
    if progress is not None:
        def _hook(d: dict) -> None:
            if d.get("status") != "downloading":
                return
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            progress.downloaded = d.get("downloaded_bytes") or 0
            progress.total = total
            progress.percent = progress.downloaded / total * 100 if total else None

        opts["progress_hooks"] = [_hook]
    if max_duration_sec > 0:
        opts["match_filter"] = yt_dlp.utils.match_filter_func(
            f"duration <= {max_duration_sec}"
        )

    def _run() -> DownloadResult:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        if info is None:
            raise DownloadError(
                "Видео не прошло фильтр (возможно, оно длиннее разрешённого лимита)."
            )
        files = sorted(job_dir.glob("*"), key=lambda p: p.stat().st_size, reverse=True)
        if not files:
            duration = info.get("duration")
            if max_duration_sec > 0 and duration and duration > max_duration_sec:
                raise DownloadError(
                    f"Видео длиннее лимита ({max_duration_sec // 60} мин) — скачивание отклонено."
                )
            raise DownloadError("yt-dlp не сохранил файл — попробуйте другую ссылку.")
        return DownloadResult(path=files[0], title=info.get("title") or "video")

    try:
        return await asyncio.to_thread(_run)
    except DownloadError:
        raise
    except yt_dlp.utils.MaxDownloadsReached as exc:  # плейлист вместо одного видео
        raise DownloadError("Пришлите ссылку на одно видео, а не на плейлист.") from exc
    except Exception as exc:
        raise DownloadError(_classify_error(exc)) from exc
