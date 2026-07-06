"""Загрузка конфигурации из .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    temp_dir: Path
    db_path: Path
    log_dir: Path
    max_file_size_mb: int
    rate_limit_per_minute: int
    workers: int
    max_duration_sec: int
    bot_api_url: str | None
    send_timeout_sec: int
    update_check_hours: int
    cookies_file: Path | None
    proxy_url: str | None

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        raise SystemExit(f"Переменная {name} должна быть целым числом, получено: {raw!r}")


def load_config() -> Config:
    load_dotenv()

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "Не задан BOT_TOKEN. Скопируйте .env.example в .env и впишите токен от @BotFather."
        )

    cfg = Config(
        bot_token=token,
        temp_dir=Path(os.getenv("TEMP_DIR", "./tmp")).resolve(),
        db_path=Path(os.getenv("DB_PATH", "./data/stats.db")).resolve(),
        log_dir=Path(os.getenv("LOG_DIR", "./logs")).resolve(),
        max_file_size_mb=_int_env("MAX_FILE_SIZE_MB", 50),
        rate_limit_per_minute=_int_env("RATE_LIMIT_PER_MINUTE", 3),
        workers=max(1, _int_env("WORKERS", 2)),
        max_duration_sec=_int_env("MAX_DURATION_SEC", 3600),
        bot_api_url=os.getenv("BOT_API_URL", "").strip().rstrip("/") or None,
        send_timeout_sec=_int_env("SEND_TIMEOUT_SEC", 300),
        update_check_hours=_int_env("UPDATE_CHECK_HOURS", 24),
        cookies_file=(
            Path(raw).resolve() if (raw := os.getenv("COOKIES_FILE", "").strip()) else None
        ),
        proxy_url=os.getenv("PROXY_URL", "").strip() or None,
    )

    if cfg.cookies_file is not None and not cfg.cookies_file.is_file():
        raise SystemExit(f"COOKIES_FILE указан, но файл не найден: {cfg.cookies_file}")

    cfg.temp_dir.mkdir(parents=True, exist_ok=True)
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    return cfg
