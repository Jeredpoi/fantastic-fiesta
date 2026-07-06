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


async def _probe(path: Path) -> tuple[float, float]:
    """Возвращает (длительность в секундах, fps видеопотока)."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "format=duration:stream=avg_frame_rate",
        "-of", "json",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        raise CompressError("Не удалось прочитать параметры видео.")
    try:
        data = json.loads(out)
        duration = float(data["format"]["duration"])
        rate = (data.get("streams") or [{}])[0].get("avg_frame_rate", "30/1")
        num, _, den = rate.partition("/")
        fps = float(num) / float(den or 1) if float(den or 1) else 30.0
        return duration, fps
    except (KeyError, ValueError, json.JSONDecodeError, IndexError, ZeroDivisionError) as exc:
        raise CompressError("Не удалось прочитать параметры видео.") from exc


# Минимальный бюджет сжатия; для длинных видео растёт вместе с длительностью
_COMPRESS_TIMEOUT_MIN_SEC = 180


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
    duration, src_fps = await _probe(src)
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

    # Скейлим ОБЕ стороны (вертикальные TikTok/Shorts 1080x1920 иначе не
    # уменьшаются вовсе) и принудительно делаем размеры чётными — libx264
    # падает на нечётной ширине. Не апскейлим: цель не больше исходника.
    filters = (
        "scale='min(1280,iw)':'min(1280,ih)'"
        ":force_original_aspect_ratio=decrease:force_divisible_by=2"
    )
    # 30 кадров/с достаточно; для 60fps-видео это минус половина работы кодека
    if src_fps > 31:
        filters += ",fps=30"

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
        "-vf", filters,
        "-c:a", "aac",
        "-b:a", f"{audio_kbps}k",
        "-movflags", "+faststart",
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
            # ВНИМАНИЕ: out_time_ms у ffmpeg — исторический баг, это ТОЖЕ
            # микросекунды (значение идентично out_time_us), а не миллисекунды.
            if key not in ("out_time_us", "out_time_ms"):
                continue
            try:
                done_sec = int(value) / 1_000_000
            except ValueError:
                continue
            on_progress(min(done_sec / duration * 100, 100.0))

    # Бюджет: минимум 3 минуты, для длинных видео — 2x длительности
    # (ultrafast на слабой VM кодирует примерно в реальном времени)
    timeout_sec = max(_COMPRESS_TIMEOUT_MIN_SEC, int(duration * 2))
    try:
        # Единый таймаут на чтение прогресса + завершение процесса.
        await asyncio.wait_for(
            asyncio.gather(_drain_stdout(), proc.wait()),
            timeout=timeout_sec,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise CompressError(
            f"Сжатие не уложилось в {timeout_sec // 60} мин — "
            "видео слишком длинное для этого сервера."
        )

    if proc.returncode != 0:
        raise CompressError("ffmpeg завершился с ошибкой при сжатии.")

    if not dst.exists() or dst.stat().st_size == 0:
        raise CompressError("ffmpeg не создал выходной файл.")
    if dst.stat().st_size > limit_bytes:
        raise CompressError("Даже после сжатия файл больше лимита Telegram.")
    return dst
