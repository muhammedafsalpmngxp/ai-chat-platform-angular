"""Tiny in-memory limiter for password attempts (single backend process)."""

import time
from collections import defaultdict


class AttemptLimiter:
    def __init__(self, max_attempts: int, window_seconds: float) -> None:
        self._max = max_attempts
        self._window = window_seconds
        self._failures: dict[str, list[float]] = defaultdict(list)

    def _recent(self, key: str) -> list[float]:
        cutoff = time.monotonic() - self._window
        recent = [t for t in self._failures[key] if t > cutoff]
        self._failures[key] = recent
        return recent

    def retry_after(self, key: str) -> int:
        """Seconds until another attempt is allowed (0 = allowed now)."""
        recent = self._recent(key)
        if len(recent) < self._max:
            return 0
        return max(1, int(recent[0] + self._window - time.monotonic()) + 1)

    def failed(self, key: str) -> None:
        self._failures[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
