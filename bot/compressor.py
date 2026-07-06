"""Сжатие видео через ffmpeg под лимит Telegram."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path


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


async def compress_to_limit(src: Path, limit_bytes: int) -> Path:
    """Пережимает src так, чтобы результат влез в limit_bytes.

    Возвращает путь к новому файлу рядом с исходным.
    Кидает CompressError, если ужать не получается.
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
        "-i", str(src),
        "-c:v", "libx264",
        "-preset", "fast",
        "-b:v", f"{video_kbps}k",
        "-maxrate", f"{video_kbps}k",
        "-bufsize", f"{video_kbps * 2}k",
        "-vf", "scale='min(1280,iw)':-2",
        "-c:a", "aac",
        "-b:a", f"{audio_kbps}k",
        "-movflags", "+faststart",
        str(dst),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise CompressError(f"ffmpeg завершился с ошибкой: {err.decode(errors='ignore')[-300:]}")

    if not dst.exists() or dst.stat().st_size == 0:
        raise CompressError("ffmpeg не создал выходной файл.")
    if dst.stat().st_size > limit_bytes:
        raise CompressError("Даже после сжатия файл больше лимита Telegram.")
    return dst
