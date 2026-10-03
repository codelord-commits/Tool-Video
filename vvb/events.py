"""EventBus: phát sự kiện tiến trình/log cho CLI và web."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Event:
    type: str                 # log | task | progress | job | preflight
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "ts": self.ts, **self.data}


class EventBus:
    def __init__(self) -> None:
        self._subs: list[Callable[[Event], None]] = []
        self._lock = threading.Lock()

    def subscribe(self, fn: Callable[[Event], None]) -> Callable[[], None]:
        with self._lock:
            self._subs.append(fn)

        def unsub() -> None:
            with self._lock:
                if fn in self._subs:
                    self._subs.remove(fn)
        return unsub

    def emit(self, type: str, **data: Any) -> None:
        ev = Event(type, data)
        with self._lock:
            subs = list(self._subs)
        for s in subs:
            try:
                s(ev)
            except Exception:  # noqa: BLE001 — subscriber lỗi không được làm hỏng job
                pass

    def log(self, level: str, msg: str, **extra: Any) -> None:
        self.emit("log", level=level, msg=msg, **extra)


NULL_BUS = EventBus()
