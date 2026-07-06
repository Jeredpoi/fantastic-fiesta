"""Сжатие видео через ffmpeg под лимит Telegram."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Callable


class CompressError(Exception):
    """Ошибка сжатия с понятным пользователю текстом."""


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


async def _probe_duration(path: Path) -> float:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        raise CompressError("Не удалось прочитать длительность видео.")
    try:
        return float(json.loads(out)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise CompressError("Не удалось прочитать длительность видео.") from exc


# Максимальное время сжатия — 3 минуты. Если не успело — отправляем оригинал.
_COMPRESS_TIMEOUT_SEC = 180


async def compress_to_limit(
    src: Path,
    limit_bytes: int,
    on_progress: Callable[[float], None] | None = None,
) -> Path:
    """Пережимает src так, чтобы результат влез в limit_bytes.

    Возвращает путь к новому файлу рядом с исходным.
    Кидает CompressError, если ужать не получается.
    on_progress, если задан, получает процент готовности (0–100).
    """
    duration = await _probe_duration(src)
    if duration <= 0:
        raise CompressError("Видео нулевой длительности — сжимать нечего.")

    # Целимся в 95% лимита, чтобы остался запас на контейнер
    target_bits = int(limit_bytes * 0.95) * 8
    audio_kbps = 96
    video_kbps = int(target_bits / duration / 1000) - audio_kbps

    if video_kbps < 100:
        raise CompressError(
            "Видео слишком длинное: даже при минимальном качестве оно не влезет в лимит Telegram."
        )

    dst = src.with_name(src.stem + "_compressed.mp4")
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-nostats",
        "-progress", "pipe:1",
        "-i", str(src),
        "-c:v", "libx264",
        # ultrafast в 3-5 раз быстрее fast при незначительно большем размере.
        # Для сжатия под лимит Telegram качество вторично — важна скорость.
        "-preset", "ultrafast",
        "-b:v", f"{video_kbps}k",
        "-maxrate", f"{video_kbps * 2}k",
        "-bufsize", f"{video_kbps * 4}k",
        "-vf", "scale='min(1280,iw)':-2",
        "-c:a", "aac",
        "-b:a", f"{audio_kbps}k",
        str(dst),
        stdout=asyncio.subprocess.PIPE,
        # DEVNULL для stderr — устраняет риск дедлока (заполненный pipe
        # блокирует ffmpeg, что блокирует наш stdout-reader).
        stderr=asyncio.subprocess.DEVNULL,
    )

    async def _drain_stdout() -> None:
        """Читает progress-строки и обновляет on_progress."""
        while line := await proc.stdout.readline():
            if on_progress is None:
                continue
            key, _, value = line.decode(errors="ignore").strip().partition("=")
            if key == "out_time_us":
                try:
                    done_sec = int(value) / 1_000_000
                except ValueError:
                    continue
            elif key == "out_time_ms":
                try:
                    done_sec = int(value) / 1_000
                except ValueError:
                    continue
            else:
                continue
            on_progress(min(done_sec / duration * 100, 100.0))

    try:
        # Единый таймаут на чтение прогресса + завершение процесса.
        await asyncio.wait_for(
            asyncio.gather(_drain_stdout(), proc.wait()),
            timeout=_COMPRESS_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise CompressError(
            f"Сжатие превысило лимит {_COMPRESS_TIMEOUT_SEC // 60} минут — "
            "видео слишком длинное для этого сервера."
        )

    if proc.returncode != 0:
        raise CompressError("ffmpeg завершился с ошибкой при сжатии.")

    if not dst.exists() or dst.stat().st_size == 0:
        raise CompressError("ffmpeg не создал выходной файл.")
    if dst.stat().st_size > limit_bytes:
        raise CompressError("Даже после сжатия файл больше лимита Telegram.")
    return dst
