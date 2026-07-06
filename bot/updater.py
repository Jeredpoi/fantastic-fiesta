"""Автообновление yt-dlp.

Периодически сравнивает установленную версию с последней на PyPI.
Если вышла новая: ставит её через pip, дожидается завершения активных
задач и мягко останавливает приложение; main() после этого перезапускает
процесс через os.execv.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys

import httpx
from telegram.ext import Application

logger = logging.getLogger(__name__)

PYPI_URL = "https://pypi.org/pypi/yt-dlp/json"
RESTART_FLAG = "restart_after_shutdown"


def _ver_key(version: str) -> tuple[int, ...]:
    """'2025.1.15' -> (2025, 1, 15); годится для сравнения версий yt-dlp."""
    return tuple(int(p) for p in re.findall(r"\d+", version))


async def installed_version() -> str:
    """Версия yt-dlp на диске (свежий процесс — не врёт после pip install)."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import importlib.metadata as m; print(m.version('yt-dlp'))",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    return out.decode().strip()


async def latest_version() -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(PYPI_URL)
        resp.raise_for_status()
        return resp.json()["info"]["version"]


async def pip_upgrade() -> bool:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pip", "install", "-q", "--upgrade", "yt-dlp",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        logger.error("pip install -U yt-dlp: %s", err.decode(errors="ignore")[-300:])
        return False
    return True


async def try_update(app: Application) -> bool:
    """Одна проверка. Возвращает True, если запущен перезапуск бота."""
    current = await installed_version()
    latest = await latest_version()
    if _ver_key(latest) <= _ver_key(current):
        logger.info("yt-dlp %s актуален (на PyPI: %s)", current, latest)
        return False

    logger.info("Обновляю yt-dlp: %s -> %s", current, latest)
    if not await pip_upgrade():
        return False

    new_version = await installed_version()
    if _ver_key(new_version) <= _ver_key(current):
        # защита от бесконечных перезапусков, если pip ничего не поменял
        logger.error("pip отработал, но версия осталась %s — перезапуск отменён", new_version)
        return False

    queue = app.bot_data["queue"]
    queue.draining = True  # новые задачи не берём
    logger.info("yt-dlp обновлён до %s, жду завершения активных задач…", new_version)
    await queue.wait_idle()

    app.bot_data[RESTART_FLAG] = True
    app.stop_running()
    return True


async def auto_update_loop(app: Application, interval_hours: int) -> None:
    interval = interval_hours * 3600
    delay = min(300, interval)  # первая проверка через ~5 минут после старта
    while True:
        await asyncio.sleep(delay)
        delay = interval
        try:
            if await try_update(app):
                return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Проверка обновления yt-dlp не удалась")
