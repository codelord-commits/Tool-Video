"""Tìm ffmpeg, kiểm tra phiên bản/encoder, chạy có tiến trình, tạm dừng/huỷ."""
from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional, Sequence

import psutil

from . import defaults as D

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class FFmpegNotFound(RuntimeError):
    pass


@dataclass
class FFmpegInfo:
    ffmpeg: str
    ffprobe: str
    version: tuple[int, ...]
    version_str: str
    encoders: set[str] = field(default_factory=set)
    filters: set[str] = field(default_factory=set)

    def has(self, enc: str) -> bool:
        return enc in self.encoders


def _candidates(name: str) -> list[Path]:
    exe = name + (".exe" if os.name == "nt" else "")
    out = []
    if os.environ.get("VVB_FFMPEG_DIR"):
        out.append(Path(os.environ["VVB_FFMPEG_DIR"]) / exe)
    if getattr(sys, "_MEIPASS", None):
        out.append(Path(sys._MEIPASS) / "bin" / exe)  # type: ignore[attr-defined]
    out.append(Path(sys.executable).parent / "bin" / exe)
    out.append(D.REPO_ROOT / "bin" / exe)
    w = shutil.which(name)
    if w:
        out.append(Path(w))
    return out


def popen_kwargs() -> dict:
    kw: dict = {}
    if os.name == "nt":
        kw["creationflags"] = CREATE_NO_WINDOW
    return kw


def _parse_version(s: str) -> tuple[int, ...]:
    m = re.search(r"version\s+n?(\d+)\.(\d+)(?:\.(\d+))?", s)
    if not m:
        return (99, 0)  # bản build git không có số → coi như mới
    return tuple(int(x) for x in m.groups() if x is not None)


@lru_cache(maxsize=1)
def find_ffmpeg() -> FFmpegInfo:
    ff = next((p for p in _candidates("ffmpeg") if p.exists()), None)
    fp = next((p for p in _candidates("ffprobe") if p.exists()), None)
    if not ff or not fp:
        raise FFmpegNotFound("Không tìm thấy ffmpeg/ffprobe. Chạy: python scripts/get_ffmpeg.py hoặc cài ffmpeg vào PATH.")
    out = subprocess.run([str(ff), "-hide_banner", "-version"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", **popen_kwargs()).stdout
    ver = _parse_version(out)
    encs = subprocess.run([str(ff), "-hide_banner", "-encoders"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **popen_kwargs()).stdout
    fils = subprocess.run([str(ff), "-hide_banner", "-filters"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **popen_kwargs()).stdout
    info = FFmpegInfo(str(ff), str(fp), ver, out.splitlines()[0] if out else "?",
                      {m.group(1) for m in re.finditer(r"^\s*V\S*\s+(\S+)", encs, re.M)}
                      | {m.group(1) for m in re.finditer(r"^\s*A\S*\s+(\S+)", encs, re.M)},
                      {m.group(1) for m in re.finditer(r"^\s*\S+\s+(\S+)\s+\S+->\S+", fils, re.M)})
    return info


def check_ffmpeg() -> list[str]:
    """Trả danh sách lỗi (rỗng = ổn)."""
    try:
        info = find_ffmpeg()
    except FFmpegNotFound as e:
        return [str(e)]
    errs = []
    if info.version < D.MIN_FFMPEG_VERSION:
        errs.append(f"ffmpeg quá cũ ({info.version_str}); cần ≥ {'.'.join(map(str, D.MIN_FFMPEG_VERSION))}")
    if "libx264" not in info.encoders:
        errs.append("ffmpeg thiếu libx264")
    return errs


_enc_ok: dict[str, bool] = {}


def encoder_works(enc: str) -> bool:
    """Thử encode 1 frame để biết encoder phần cứng có thật sự dùng được không."""
    if enc in _enc_ok:
        return _enc_ok[enc]
    info = find_ffmpeg()
    if enc not in info.encoders:
        _enc_ok[enc] = False
        return False
    r = subprocess.run([info.ffmpeg, "-hide_banner", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1",
                        "-frames:v", "1", "-c:v", enc, "-f", "null", "-"],
                       capture_output=True, timeout=30, **popen_kwargs())
    _enc_ok[enc] = r.returncode == 0
    return _enc_ok[enc]


def available_encoders() -> list[str]:
    base = ["h264", "h265"]
    return base + [e for e in D.HW_ENCODERS if encoder_works(e)]


def cmd_str(cmd: Sequence[str]) -> str:
    return subprocess.list2cmdline(list(cmd)) if os.name == "nt" else " ".join(
        "'" + c.replace("'", "'\\''") + "'" if re.search(r"[^\w@%+=:,./-]", c) else c for c in cmd)


# ---------------------------------------------------------------- quản lý process
class ProcessRegistry:
    """Theo dõi mọi process ffmpeg đang chạy để tạm dừng/huỷ đồng loạt."""

    def __init__(self) -> None:
        self._procs: set[subprocess.Popen] = set()
        self._lock = threading.Lock()
        self.paused = threading.Event()

    def add(self, p: subprocess.Popen) -> None:
        with self._lock:
            self._procs.add(p)
        if self.paused.is_set():
            _signal_tree(p.pid, "suspend")

    def remove(self, p: subprocess.Popen) -> None:
        with self._lock:
            self._procs.discard(p)

    def _all(self) -> list[subprocess.Popen]:
        with self._lock:
            return list(self._procs)

    def suspend_all(self) -> None:
        self.paused.set()
        for p in self._all():
            _signal_tree(p.pid, "suspend")

    def resume_all(self) -> None:
        self.paused.clear()
        for p in self._all():
            _signal_tree(p.pid, "resume")

    def kill_all(self) -> None:
        for p in self._all():
            kill_tree(p.pid)


def _signal_tree(pid: int, action: str) -> None:
    try:
        root = psutil.Process(pid)
        for pr in [root, *root.children(recursive=True)]:
            try:
                getattr(pr, action)()
            except psutil.Error:
                pass
    except psutil.Error:
        pass


def kill_tree(pid: int) -> None:
    try:
        root = psutil.Process(pid)
        procs = [*root.children(recursive=True), root]
        for pr in procs:
            try:
                pr.resume()
            except psutil.Error:
                pass
            try:
                pr.kill()
            except psutil.Error:
                pass
        psutil.wait_procs(procs, timeout=5)
    except psutil.Error:
        pass


GLOBAL_REGISTRY = ProcessRegistry()


@dataclass
class FFResult:
    returncode: int
    cmd: list[str]
    stderr_tail: list[str]
    cancelled: bool = False
    stalled: bool = False
    elapsed: float = 0.0

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.cancelled and not self.stalled

    def error_text(self, n: int = 30) -> str:
        return "\n".join(self.stderr_tail[-n:])


class CancelledError(RuntimeError):
    pass


def run_ffmpeg(args: Sequence[str], *, duration: Optional[float] = None,
               on_progress: Optional[Callable[[float], None]] = None,
               cancel: Optional[threading.Event] = None, stall_timeout: float = D.STALL_TIMEOUT_S,
               registry: Optional[ProcessRegistry] = None, loglevel: str = "error") -> FFResult:
    """Chạy ffmpeg với list tham số (không shell). on_progress nhận tỷ lệ 0–1."""
    info = find_ffmpeg()
    registry = registry or GLOBAL_REGISTRY
    cmd = [info.ffmpeg, "-hide_banner", "-nostdin", "-y", "-v", loglevel, "-progress", "pipe:1", "-nostats", *args]
    t0 = time.time()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                         **popen_kwargs())
    registry.add(p)
    tail: deque[str] = deque(maxlen=200)
    q: "queue.Queue[Optional[str]]" = queue.Queue()

    def rd_out() -> None:
        assert p.stdout
        for raw in iter(p.stdout.readline, b""):
            q.put(raw.decode("utf-8", "replace").strip())
        q.put(None)

    def rd_err() -> None:
        assert p.stderr
        for raw in iter(p.stderr.readline, b""):
            tail.append(raw.decode("utf-8", "replace").rstrip())

    th_o = threading.Thread(target=rd_out, daemon=True)
    th_e = threading.Thread(target=rd_err, daemon=True)
    th_o.start()
    th_e.start()
    last_change = time.time()
    last_val = -1.0
    cancelled = stalled = False
    try:
        while True:
            try:
                line = q.get(timeout=0.5)
            except queue.Empty:
                line = ""
            if line is None:
                break
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    v = int(line.split("=", 1)[1]) / 1e6
                except ValueError:
                    v = last_val
                if v != last_val:
                    last_val = v
                    last_change = time.time()
                    if on_progress and duration:
                        on_progress(max(0.0, min(1.0, v / duration)))
            elif line.startswith("progress="):
                last_change = time.time()
            if cancel is not None and cancel.is_set():
                cancelled = True
                kill_tree(p.pid)
                break
            if registry.paused.is_set():
                last_change = time.time()
            elif time.time() - last_change > stall_timeout:
                stalled = True
                tail.append(f"[vvb] ffmpeg không tiến triển > {stall_timeout}s — đã huỷ")
                kill_tree(p.pid)
                break
        p.wait()
    finally:
        registry.remove(p)
        th_e.join(timeout=2)
    if on_progress and p.returncode == 0 and not cancelled:
        on_progress(1.0)
    return FFResult(p.returncode, cmd, list(tail), cancelled, stalled, time.time() - t0)


def run_capture(args: Sequence[str], timeout: float = 120) -> subprocess.CompletedProcess:
    """Chạy ffmpeg/ffprobe ngắn, lấy stdout bytes."""
    return subprocess.run(list(args), capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
                          **popen_kwargs())
