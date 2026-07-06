"""Скользящее окно: не больше N скачиваний в минуту на пользователя."""

from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, per_minute: int, window_sec: float = 60.0):
        self._limit = per_minute
        self._window = window_sec
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    def check(self, user_id: int) -> float:
        """Пробует зарегистрировать запрос.

        Возвращает 0, если запрос разрешён (и учитывает его),
        иначе — сколько секунд осталось ждать.
        """
        now = time.monotonic()
        hits = self._hits[user_id]
        while hits and now - hits[0] > self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return self._window - (now - hits[0])
        hits.append(now)
        return 0.0
