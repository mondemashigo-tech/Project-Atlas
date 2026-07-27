"""Process-wide live fan-out for SSE clients — thread-safe, SQLite-free.

The engine persists events on its own thread via its own store connection; this
hub only handles *streaming* the already-published event dicts to connected
browsers. Keeping it free of any database handle avoids cross-thread SQLite use
(a sqlite3 connection may not be shared between threads).

Each connected client gets a bounded queue; if a slow client's queue fills, its
oldest events are dropped (it will still catch up via the persisted-event replay
endpoint on reconnect), so one stuck browser can never block emission.
"""
from __future__ import annotations

import queue
import threading
from typing import Dict, List


class Hub:
    def __init__(self, client_buffer: int = 2000):
        self._clients: List[queue.Queue] = []
        self._lock = threading.Lock()
        self._buffer = client_buffer

    def register(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=self._buffer)
        with self._lock:
            self._clients.append(q)
        return q

    def unregister(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def broadcast(self, item: Dict) -> None:
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait(item)
            except queue.Full:
                # drop the oldest, then enqueue the newest — reconnect fills gaps
                try:
                    q.get_nowait()
                    q.put_nowait(item)
                except queue.Empty:
                    pass
