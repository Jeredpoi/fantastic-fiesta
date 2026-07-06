"""Скачивание видео через yt-dlp."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

_VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov"}


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
    # проверяем ДО ветки про приватность: в этой ошибке тоже есть «sign in»,
    # но видео публичное — это YouTube не доверяет IP сервера
    if "not a bot" in msg or "confirm you" in msg:
        return (
            "YouTube требует подтвердить, что мы не бот (IP сервера под подозрением). "
            "Владельцу бота нужно добавить cookies — см. COOKIES_FILE в README."
        )
    if "private" in msg or "login" in msg or "sign in" in msg or "cookies" in msg:
        return "Видео приватное или требует входа в аккаунт — скачать не получится."
    if "unavailable" in msg or "not available" in msg or "removed" in msg or "not exist" in msg or "404" in msg:
        return "Видео недоступно: удалено, скрыто или ссылка битая."
    if "blocked" in msg or "ip address" in msg:
        return "Сервис заблокировал наш IP. Попробуйте ещё раз позже или попробуйте другую ссылку."
    if "unsupported" in msg:
        return "Эта ссылка не поддерживается."
    if "live event" in msg or "is live" in msg or "live stream" in msg or "ongoing live" in msg:
        return "Прямые трансляции скачивать нельзя, дождитесь окончания."
    return "Не удалось скачать видео. Проверьте ссылку и попробуйте ещё раз."


async def download_video(
    url: str,
    job_dir: Path,
    max_duration_sec: int,
    progress: ProgressState | None = None,
    cookies_file: Path | None = None,
) -> DownloadResult:
    """Скачивает видео в job_dir (каталог одной задачи, чистит его вызывающий код).

    Блокирующий yt-dlp уходит в отдельный поток.
    """
    job_dir.mkdir(parents=True, exist_ok=True)

    opts = {
        # До 1080p, чтобы реже требовалось сжатие; если таких форматов нет — любой лучший
        "format": "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b",
        "outtmpl": str(job_dir / "%(title).100s [%(id)s].%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "socket_timeout": 30,
        "retries": 3,
        "continuedl": True,
        "http_chunk_size": 10 * 1024 * 1024,
        # Гарантируем использование ffmpeg и ремуксинг в mp4
        "prefer_ffmpeg": True,
        "postprocessors": [{
            "key": "FFmpegVideoRemuxer",
            "preferedformat": "mp4",
        }],
        # ВАЖНО: player_client и app_name НЕ переопределяем.
        # Мейнтейнеры yt-dlp подбирают рабочие клиенты под текущие блокировки
        # (сейчас это android_vr + web_safari); зашитый здесь список устаревает
        # за пару месяцев и ломает YouTube/Shorts («Sign in to confirm…»).
        # TikTok: yt-dlp сам включает impersonation, если установлен curl_cffi
        # (он в requirements.txt — без него TikTok получает страницу-заглушку).
    }
    if cookies_file is not None:
        opts["cookiefile"] = str(cookies_file)
    if progress is not None:
        def _hook(d: dict) -> None:
            if d.get("status") != "downloading":
                return
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            progress.downloaded = d.get("downloaded_bytes") or 0
            progress.total = total
            if total:
                progress.percent = min(progress.downloaded / total * 100, 100.0)
            else:
                progress.percent = None

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
        # Ищем только видеофайлы, игнорируем .part / .ytdl / .info.json и т.д.
        files = sorted(
            (p for p in job_dir.iterdir() if p.suffix.lower() in _VIDEO_SUFFIXES),
            key=lambda p: p.stat().st_size,
            reverse=True,
        )
        if not files:
            raise DownloadError("yt-dlp не сохранил файл — попробуйте другую ссылку.")
        return DownloadResult(path=files[0], title=info.get("title") or "video")

    try:
        return await asyncio.to_thread(_run)
    except DownloadError:
        raise
    except yt_dlp.utils.MaxDownloadsReached as exc:
        raise DownloadError("Пришлите ссылку на одно видео, а не на плейлист.") from exc
    except Exception as exc:
        raise DownloadError(_classify_error(exc)) from exc
