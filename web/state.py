"""Trạng thái dùng chung của server: job đang chạy, EventBus → WebSocket, settings, preview."""
from __future__ import annotations

import asyncio
import json
import threading
from collections import deque
from pathlib import Path
from typing import Any, Optional

from vvb import defaults as D
from vvb.batch import BatchRunner
from vvb.events import Event, EventBus
from vvb.renderer import PreviewRunner

DEFAULT_SETTINGS: dict[str, Any] = {"theme": "system", "lang": "vi", "recent_projects": [], "last_job": None,
                                    "options_collapsed": False}


class AppState:
    def __init__(self) -> None:
        self.bus = EventBus()
        self.runner: Optional[BatchRunner] = None
        self.job_thread: Optional[threading.Thread] = None
        self.last_job_args: Optional[dict[str, Any]] = None
        self.preview = PreviewRunner()
        self.log_buffer: deque[dict[str, Any]] = deque(maxlen=5000)
        self._clients: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self._lock = threading.Lock()
        self.bus.subscribe(self._on_event)
        self.token = ""
        self.port = 0
        self.preview_dir = D.USER_DIR / "preview"

    # ------------------------------------------------------------ websocket fan-out
    def _on_event(self, ev: Event) -> None:
        d = ev.to_dict()
        if ev.type == "log":
            self.log_buffer.append(d)
        with self._lock:
            clients = list(self._clients)
        for loop, q in clients:
            try:
                loop.call_soon_threadsafe(q.put_nowait, d)
            except RuntimeError:
                pass

    def add_client(self, loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=10000)
        with self._lock:
            self._clients.add((loop, q))
        return q

    def remove_client(self, loop: asyncio.AbstractEventLoop, q: asyncio.Queue) -> None:
        with self._lock:
            self._clients.discard((loop, q))

    # ------------------------------------------------------------ job
    @property
    def running(self) -> bool:
        return bool(self.job_thread and self.job_thread.is_alive())

    def snapshot(self) -> dict[str, Any]:
        if self.runner is None:
            return {"state": "idle"}
        snap = self.runner.snapshot()
        snap["plan"] = {"count": len(self.runner.plan.tasks), "total_duration": self.runner.plan.total_duration}
        return snap

    # ------------------------------------------------------------ settings
    def load_settings(self) -> dict[str, Any]:
        try:
            d = json.loads(D.SETTINGS_FILE.read_text(encoding="utf-8"))
            return {**DEFAULT_SETTINGS, **d}
        except (OSError, ValueError):
            return dict(DEFAULT_SETTINGS)

    def save_settings(self, d: dict[str, Any]) -> dict[str, Any]:
        cur = self.load_settings()
        cur.update({k: v for k, v in d.items() if k in DEFAULT_SETTINGS})
        cur["recent_projects"] = list(dict.fromkeys(cur.get("recent_projects") or []))[:8]
        D.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = D.SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(D.SETTINGS_FILE)
        return cur


STATE = AppState()
