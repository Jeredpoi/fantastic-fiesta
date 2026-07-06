"""Простая статистика скачиваний в SQLite.

sqlite3 — блокирующий модуль, поэтому все обращения выполняются через
asyncio.to_thread, а от гонок соединение защищено asyncio.Lock.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    username   TEXT,
    url        TEXT NOT NULL,
    status     TEXT NOT NULL,          -- ok | error
    size_bytes INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_downloads_user ON downloads (user_id);
"""


class StatsDB:
    def __init__(self, path: Path):
        self._path = path
        self._lock = asyncio.Lock()
        self._conn: sqlite3.Connection | None = None

    async def open(self) -> None:
        def _open() -> sqlite3.Connection:
            conn = sqlite3.connect(self._path, check_same_thread=False)
            conn.executescript(_SCHEMA)
            conn.commit()
            return conn

        self._conn = await asyncio.to_thread(_open)

    async def close(self) -> None:
        if self._conn is not None:
            await asyncio.to_thread(self._conn.close)
            self._conn = None

    async def record(
        self, user_id: int, username: str | None, url: str, status: str, size_bytes: int | None = None
    ) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        def _write(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO downloads (user_id, username, url, status, size_bytes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, username, url, status, size_bytes, now),
            )
            conn.commit()

        async with self._lock:
            assert self._conn is not None
            await asyncio.to_thread(_write, self._conn)

    async def user_stats(self, user_id: int) -> tuple[int, int, str | None]:
        """Возвращает (успешных, ошибок, дата последнего успешного)."""

        def _read(conn: sqlite3.Connection) -> tuple[int, int, str | None]:
            ok = conn.execute(
                "SELECT COUNT(*) FROM downloads WHERE user_id = ? AND status = 'ok'", (user_id,)
            ).fetchone()[0]
            err = conn.execute(
                "SELECT COUNT(*) FROM downloads WHERE user_id = ? AND status = 'error'", (user_id,)
            ).fetchone()[0]
            last = conn.execute(
                "SELECT created_at FROM downloads WHERE user_id = ? AND status = 'ok' "
                "ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            return ok, err, last[0] if last else None

        async with self._lock:
            assert self._conn is not None
            return await asyncio.to_thread(_read, self._conn)
