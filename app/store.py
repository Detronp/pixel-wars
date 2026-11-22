"""Board storage. Uses Redis when REDIS_URL is set, otherwise an in-memory store.

The board is a string of WIDTH*HEIGHT characters, one hex digit (0-f) per pixel,
which maps onto a 16-colour palette. That keeps a full board at 4 KB, so clients
can fetch the whole thing cheaply.
"""

import os
import threading
import time

WIDTH = HEIGHT = 64
SIZE = WIDTH * HEIGHT
BLANK = "0" * SIZE  # colour 0 = white


class MemoryStore:
    """Single-process fallback, used for local dev and tests."""

    def __init__(self):
        self._lock = threading.Lock()
        self._board = list(BLANK)
        self._version = 0
        self._placed = 0
        self._cooldowns: dict[str, float] = {}

    def ping(self) -> bool:
        return True

    def board(self) -> tuple[int, str]:
        with self._lock:
            return self._version, "".join(self._board)

    def version(self) -> int:
        return self._version

    def try_cooldown(self, who: str, seconds: int) -> int:
        """Return 0 if `who` may paint now (and start their cooldown), else seconds left."""
        now = time.time()
        with self._lock:
            until = self._cooldowns.get(who, 0)
            if until > now:
                return int(until - now) + 1
            self._cooldowns[who] = now + seconds
            return 0

    def place(self, index: int, colour: str) -> int:
        with self._lock:
            self._board[index] = colour
            self._version += 1
            self._placed += 1
            return self._version

    def placed(self) -> int:
        return self._placed

    def reset(self):
        with self._lock:
            self._board = list(BLANK)
            self._version += 1


class RedisStore:
    """Shared store: every app replica reads and writes the same board."""

    def __init__(self, url: str):
        import redis  # imported here so local dev works without the package

        self.r = redis.Redis.from_url(url, decode_responses=True)

    def ping(self) -> bool:
        return bool(self.r.ping())

    def _ensure(self):
        # SET NX: create the blank board once, no matter how many replicas race.
        self.r.set("pw:board", BLANK, nx=True)

    def board(self) -> tuple[int, str]:
        self._ensure()
        pipe = self.r.pipeline()
        pipe.get("pw:version")
        pipe.get("pw:board")
        version, board = pipe.execute()
        return int(version or 0), board

    def version(self) -> int:
        return int(self.r.get("pw:version") or 0)

    def try_cooldown(self, who: str, seconds: int) -> int:
        key = f"pw:cd:{who}"
        if self.r.set(key, 1, nx=True, ex=seconds):
            return 0
        return max(int(self.r.ttl(key)), 1)

    def place(self, index: int, colour: str) -> int:
        self._ensure()
        pipe = self.r.pipeline()
        pipe.setrange("pw:board", index, colour)
        pipe.incr("pw:version")
        pipe.incr("pw:placed")
        _, version, _ = pipe.execute()
        return int(version)

    def placed(self) -> int:
        return int(self.r.get("pw:placed") or 0)

    def reset(self):
        pipe = self.r.pipeline()
        pipe.set("pw:board", BLANK)
        pipe.incr("pw:version")
        pipe.execute()


def make_store():
    url = os.getenv("REDIS_URL")
    return RedisStore(url) if url else MemoryStore()
