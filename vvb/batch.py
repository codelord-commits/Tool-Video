"""Chạy batch: hàng đợi, song song, tạm dừng/huỷ, journal (resume), lock, manifest."""
from __future__ import annotations

import csv
import json
import os
import shutil
import socket
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import psutil

from . import defaults as D
from .events import NULL_BUS, EventBus
from .ffmpeg import ProcessRegistry, cmd_str
from .models import Job, TaskSpec
from .naming import unique_path
from .plan import JobPlan
from .preset_io import preset_to_dict, validate_preset_dict
from .renderer import Cancelled, RenderError, Renderer
from .system import free_disk_gb, notify, prevent_sleep

STATE_DIR = ".vvb"


class JobError(RuntimeError):
    pass


@dataclass
class TaskState:
    index: int
    group: str
    clip: str
    out: str
    status: str = "pending"  # pending|running|done|skipped|error|cancelled
    progress: float = 0.0
    error: str = ""
    duration: float = 0.0
    size_bytes: int = 0
    elapsed: float = 0.0
    attempts: int = 0
    warnings: list[str] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)
    seed: int = 0


@dataclass
class Summary:
    total: int = 0
    done: int = 0
    skipped: int = 0
    failed: int = 0
    cancelled: bool = False
    elapsed: float = 0.0
    out_dir: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class OutputLock:
    """O4: khoá Output để 2 cửa sổ không ghi chung."""

    def __init__(self, out_dir: Path):
        self.path = Path(out_dir) / STATE_DIR / "lock"

    def acquire(self) -> None:
        if self.path.exists():
            try:
                d = json.loads(self.path.read_text(encoding="utf-8"))
                if d.get("host") == socket.gethostname() and psutil.pid_exists(int(d.get("pid", 0))) \
                        and int(d.get("pid")) != os.getpid():
                    raise JobError(f"Thư mục Output đang được dùng bởi tiến trình khác (PID {d['pid']})")
            except (ValueError, OSError):
                pass
        _atomic_write(self.path, json.dumps({"pid": os.getpid(), "host": socket.gethostname(),
                                             "time": datetime.now().isoformat()}))

    def release(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


def journal_path(out_dir: Path) -> Path:
    return Path(out_dir) / STATE_DIR / "job.json"


def find_unfinished(out_dir: Path) -> Optional[dict[str, Any]]:
    """O2: job dang dở trong Output (journal còn task chưa xong)."""
    jp = journal_path(out_dir)
    if not jp.exists():
        return None
    try:
        d = json.loads(jp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if d.get("finished"):
        return None
    pending = [t for t in d.get("tasks", []) if t["status"] not in ("done", "skipped")]
    return d if pending else None


def job_from_journal(d: dict[str, Any]) -> Job:
    preset = validate_preset_dict(d["preset"])
    return Job(preset=preset, paths=d["paths"], out_dir=Path(d["out_dir"]), groups_filter=d.get("groups_filter"),
               clips_filter=d.get("clips_filter"), manual_match=d.get("manual_match") or {},
               preset_name=d.get("preset_name", ""))


class BatchRunner:
    def __init__(self, plan: JobPlan, bus: EventBus = NULL_BUS, workers: Optional[int] = None):
        if not plan.ok:
            raise JobError("Pre-flight chưa đạt: " + "; ".join(plan.blockers()))
        self.plan = plan
        self.job: Job = plan.job
        self.preset = plan.job.preset
        self.bus = bus
        self.workers = workers or plan.workers
        self.registry = ProcessRegistry()
        self.cancel_ev = threading.Event()
        self.pause_ev = threading.Event()
        self._resume_cv = threading.Condition()
        self._lock = threading.Lock()
        self.out_dir = Path(self.job.out_dir)
        self.states: dict[int, TaskState] = {
            t.index: TaskState(t.index, t.group_display, t.clip_name, str(t.out_path), seed=t.seed)
            for t in plan.tasks}
        self.summary = Summary(total=len(plan.tasks), out_dir=str(self.out_dir))
        self.state = "idle"
        self.started_at = 0.0
        self._first_rates: list[float] = []
        self._errors_log = self.out_dir / "errors.log"
        rc = self.preset.run
        self.temp_root = Path(rc.temp_dir) if rc.temp_dir else Path(tempfile.gettempdir())
        self.temp_root = self.temp_root / f"vvb_{os.getpid()}_{int(time.time())}"
        self.cache_dir = D.CACHE_DIR if rc.cache_normalized else None
        if self.cache_dir:
            from .renderer import prune_cache
            prune_cache(self.cache_dir)

    # ------------------------------------------------------------ điều khiển
    def pause(self) -> None:
        if self.state != "running":
            return
        self.pause_ev.set()
        self.registry.suspend_all()
        self._set_state("paused")

    def resume(self) -> None:
        if self.state != "paused":
            return
        self.pause_ev.clear()
        self.registry.resume_all()
        with self._resume_cv:
            self._resume_cv.notify_all()
        self._set_state("running")

    def cancel(self) -> None:
        self.cancel_ev.set()
        self.pause_ev.clear()
        self.registry.resume_all()
        self.registry.kill_all()
        with self._resume_cv:
            self._resume_cv.notify_all()

    # ------------------------------------------------------------ trạng thái
    def _set_state(self, s: str) -> None:
        self.state = s
        self.bus.emit("job", state=s, summary=self.summary.to_dict())

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"state": self.state, "summary": self.summary.to_dict(), "workers": self.workers,
                    "eta_s": self._eta(), "tasks": [asdict(s) for s in self.states.values()],
                    "out_dir": str(self.out_dir)}

    def _eta(self) -> Optional[float]:
        if not self._first_rates:
            return None
        remaining = [self.plan.durations.get(i, 0) * (1 - s.progress) for i, s in self.states.items()
                     if s.status in ("pending", "running")]
        rate = sum(self._first_rates) / len(self._first_rates)  # giây render / giây video
        return sum(remaining) * rate / max(1, self.workers)

    def _emit_task(self, st: TaskState) -> None:
        self.bus.emit("task", **asdict(st))

    def _emit_progress(self) -> None:
        s = self.summary
        fin = s.done + s.skipped + s.failed
        running = sum(st.progress for st in self.states.values() if st.status == "running")
        pct = (fin + running) / max(1, s.total)
        self.bus.emit("progress", done=s.done, skipped=s.skipped, failed=s.failed, total=s.total,
                      percent=round(pct * 100, 1), eta_s=self._eta())

    def _write_journal(self, finished: bool = False) -> None:
        d = {"version": 1, "finished": finished, "preset": preset_to_dict(self.preset),
             "preset_name": self.job.preset_name, "paths": self.job.paths, "out_dir": str(self.out_dir),
             "groups_filter": self.job.groups_filter, "clips_filter": self.job.clips_filter,
             "manual_match": self.job.manual_match, "updated": datetime.now().isoformat(),
             "tasks": [{"index": s.index, "status": s.status, "out": s.out} for s in self.states.values()]}
        with self._lock:
            _atomic_write(journal_path(self.out_dir), json.dumps(d, ensure_ascii=False, indent=1))

    # ------------------------------------------------------------ chạy
    def run(self) -> Summary:
        t0 = self.started_at = time.time()
        lock = OutputLock(self.out_dir)
        lock.acquire()
        self._cleanup_parts()
        self._set_state("running")
        self.bus.log("info", f"Bắt đầu: {len(self.plan.tasks)} video, {self.workers} luồng song song")
        renderer = Renderer(self.preset, self.plan.out, self.temp_root, cache_dir=self.cache_dir, bus=self.bus,
                            registry=self.registry)
        cpu_renderer: Optional[Renderer] = None
        if not renderer.encoder.startswith("lib"):
            cpu_renderer = Renderer(self.preset, self.plan.out, self.temp_root, cache_dir=self.cache_dir,
                                    bus=self.bus, registry=self.registry, force_cpu=True)
        self._write_journal()
        stop_disk = threading.Event()
        disk_th = threading.Thread(target=self._disk_monitor, args=(stop_disk,), daemon=True)
        disk_th.start()
        try:
            with prevent_sleep(self.preset.run.prevent_sleep):
                with ThreadPoolExecutor(max_workers=self.workers) as ex:
                    futs = [ex.submit(self._run_one, t, renderer, cpu_renderer) for t in self.plan.tasks]
                    for f in futs:
                        f.result()
        finally:
            stop_disk.set()
            self.summary.elapsed = time.time() - t0
            self.summary.cancelled = self.cancel_ev.is_set()
            if self.summary.cancelled:
                for s in self.states.values():
                    if s.status in ("pending", "running"):
                        s.status = "cancelled"
                self._cleanup_parts()
            finished = all(s.status in ("done", "skipped") for s in self.states.values())
            self._write_journal(finished=finished)
            self._write_outputs()
            lock.release()
            shutil.rmtree(self.temp_root, ignore_errors=True)
        state = "cancelled" if self.summary.cancelled else "done"
        self._set_state(state)
        s = self.summary
        msg = f"Xong: {s.done} thành công, {s.failed} lỗi, {s.skipped} bỏ qua — {s.elapsed / 60:.1f} phút"
        self.bus.log("success" if not s.failed else "warn", msg)
        if self.preset.run.notify_done and not s.cancelled:
            notify("Video Variant Builder", msg)
        return s

    def _wait_if_paused(self) -> None:
        with self._resume_cv:
            while self.pause_ev.is_set() and not self.cancel_ev.is_set():
                self._resume_cv.wait(timeout=0.5)

    def _run_one(self, task: TaskSpec, renderer: Renderer, cpu_renderer: Optional[Renderer]) -> None:
        st = self.states[task.index]
        self._wait_if_paused()
        if self.cancel_ev.is_set():
            return
        out = Path(st.out)
        existing = self.preset.run.existing
        if task.index in self.plan.bad_tasks:
            self._fail(st, self.plan.bad_tasks[task.index])
            return
        if out.exists() and out.stat().st_size > 0:
            if existing == "skip":
                st.status = "skipped"
                with self._lock:
                    self.summary.skipped += 1
                self._emit_task(st)
                self._emit_progress()
                return
            if existing == "rename":
                out = unique_path(out)
                st.out = str(out)
        st.status = "running"
        self._emit_task(st)
        retries = self.preset.run.retry
        last_err: Optional[BaseException] = None
        for attempt in range(retries + 1):
            st.attempts = attempt + 1
            r = renderer if attempt == 0 or cpu_renderer is None else cpu_renderer
            if attempt > 0:
                self.bus.log("warn", f"Thử lại {task.group_display}/{task.clip_name} (lần {attempt + 1})"
                             + (" bằng CPU" if cpu_renderer else ""))
            try:
                last_emit = [0.0]

                def prog(f: float) -> None:
                    st.progress = f
                    now = time.time()
                    if now - last_emit[0] > 0.25 or f >= 1:
                        last_emit[0] = now
                        self.bus.emit("task_progress", index=st.index, progress=round(f, 3))
                        self._emit_progress()

                target = out
                try:
                    res = r.render_task(task, target, self.cancel_ev, prog)
                except PermissionError:
                    target = unique_path(out)  # F11: file đang bị app khác khoá
                    st.out = str(target)
                    st.warnings.append(f"File output bị khoá — ghi ra {target.name}")
                    res = r.render_task(task, target, self.cancel_ev, prog)
                st.status, st.progress = "done", 1.0
                st.duration, st.size_bytes, st.elapsed = res.duration, res.size_bytes, res.elapsed
                st.warnings += res.warnings
                st.sources = res.sources
                if res.duration > 0:
                    with self._lock:
                        if len(self._first_rates) < 5:
                            self._first_rates.append(res.elapsed / res.duration)
                with self._lock:
                    self.summary.done += 1
                if self.preset.output.thumbnails:
                    try:
                        r.thumbnail(target, min(self.preset.output.thumbnail_at, res.duration / 2),
                                    target.with_suffix(".jpg"))
                    except Exception:  # noqa: BLE001
                        pass
                self.bus.log("success", f"✓ {target.name}", index=st.index)
                break
            except Cancelled:
                st.status = "cancelled"
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                if self.cancel_ev.is_set():
                    st.status = "cancelled"
                    break
        else:
            self._fail(st, str(last_err), last_err)
        self._emit_task(st)
        self._emit_progress()
        self._write_journal()
        if st.status == "error" and self.preset.run.stop_on_error:
            self.bus.log("error", "Dừng batch do gặp lỗi (stop_on_error)")
            self.cancel()

    def _fail(self, st: TaskState, msg: str, exc: Optional[BaseException] = None) -> None:
        st.status, st.error = "error", msg
        with self._lock:
            self.summary.failed += 1
        self.bus.log("error", f"✗ {st.group}/{st.clip or '-'}: {msg}", index=st.index)
        lines = [f"[{datetime.now():%Y-%m-%d %H:%M:%S}] #{st.index} {st.group}/{st.clip} → {st.out}", f"Lỗi: {msg}"]
        if isinstance(exc, RenderError) and exc.result:
            lines += ["Lệnh: " + cmd_str(exc.cmd), "stderr (30 dòng cuối):", exc.stderr_tail]
        with self._lock:
            self.out_dir.mkdir(parents=True, exist_ok=True)
            with self._errors_log.open("a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n\n")
        self._emit_task(st)

    def _disk_monitor(self, stop: threading.Event) -> None:
        need = self.preset.run.min_free_disk_gb
        while not stop.wait(10):
            free = free_disk_gb(self.out_dir)
            if free < need and self.state == "running":
                self.bus.log("error", f"Ổ đĩa sắp đầy (còn {free:.1f} GB < {need} GB) — đã tạm dừng. "
                                      "Giải phóng dung lượng rồi bấm Tiếp tục.")
                self.pause()

    def _cleanup_parts(self) -> None:
        for s in self.states.values():
            p = Path(s.out)
            part = p.with_name(p.stem + ".part" + p.suffix)
            try:
                part.unlink(missing_ok=True)
            except OSError:
                pass

    def _write_outputs(self) -> None:
        o = self.preset.output
        self.out_dir.mkdir(parents=True, exist_ok=True)
        if o.copy_preset:
            _atomic_write(self.out_dir / "preset.json", json.dumps(preset_to_dict(self.preset), ensure_ascii=False,
                                                                   indent=2))
        if not o.manifest:
            return
        rows = []
        for t in self.plan.tasks:
            s = self.states[t.index]
            rows.append({"index": s.index, "group": s.group, "clip": s.clip, "status": s.status, "out": s.out,
                         "duration": round(s.duration, 3), "size_bytes": s.size_bytes,
                         "elapsed_s": round(s.elapsed, 2), "error": s.error, "seed": s.seed,
                         "preset": self.job.preset_name or self.preset.name,
                         "schema_version": self.preset.schema_version,
                         "sources": json.dumps({k: str(v) for k, v in {**t.assets, "clip": t.clip}.items() if v},
                                               ensure_ascii=False)})
        _atomic_write(self.out_dir / "manifest.json", json.dumps(
            {"generated": datetime.now().isoformat(), "summary": self.summary.to_dict(),
             "seed": self.preset.combine.seed, "videos": rows}, ensure_ascii=False, indent=1))
        tmp = self.out_dir / "manifest.csv.tmp"
        with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["index"])
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, self.out_dir / "manifest.csv")
