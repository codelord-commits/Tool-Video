"""Pre-flight: quét, ghép, tổ hợp, probe, ước tính — trước khi render."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import defaults as D
from .combiner import CombineError, combine
from .events import NULL_BUS, EventBus
from .ffmpeg import check_ffmpeg
from .filters import SegmentError, SegmentSkip, build_segment
from .matcher import MatchResult, build_match
from .models import Job, MediaInfo, TaskSpec
from .naming import build_out_path, dedupe_paths
from .probe import ProbeError, probe
from .renderer import resolve_out_spec
from .filters import OutSpec
from .scanner import ScanResult, scan_slot
from .system import free_disk_gb, is_online_only, is_writable_dir


@dataclass
class Issue:
    level: str  # error | warning | info
    msg: str
    slot: Optional[str] = None
    file: Optional[str] = None
    group: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class JobPlan:
    job: Job
    scans: dict[str, ScanResult] = field(default_factory=dict)
    match: Optional[MatchResult] = None
    tasks: list[TaskSpec] = field(default_factory=list)
    out: Optional[OutSpec] = None
    issues: list[Issue] = field(default_factory=list)
    durations: dict[int, float] = field(default_factory=dict)
    bad_tasks: dict[int, str] = field(default_factory=dict)  # index -> lý do
    media: dict[str, MediaInfo] = field(default_factory=dict)
    existing: int = 0
    total_duration: float = 0.0
    est_bytes: int = 0
    workers: int = 1

    @property
    def ok(self) -> bool:
        return not any(i.level == "error" for i in self.issues) and bool(self.tasks)

    def add(self, level: str, msg: str, **kw: Any) -> None:
        self.issues.append(Issue(level, msg, **kw))

    def blockers(self) -> list[str]:
        out = [i.msg for i in self.issues if i.level == "error"]
        if not self.tasks and not out:
            out.append("Không có video nào để tạo")
        return out

    def to_dict(self, with_tasks: bool = True) -> dict[str, Any]:
        d: dict[str, Any] = {
            "ok": self.ok, "issues": [i.to_dict() for i in self.issues], "blockers": self.blockers(),
            "count": len(self.tasks), "existing": self.existing, "bad": len(self.bad_tasks),
            "total_duration": round(self.total_duration, 2), "est_bytes": self.est_bytes, "workers": self.workers,
            "groups": len({t.group for t in self.tasks}), "clips": len({t.clip for t in self.tasks if t.clip}),
            "out": {"w": self.out.W, "h": self.out.H, "fps": self.out.fps} if self.out else None,
            "scans": {n: {"path": str(s.path) if s.path else None, "count": len(s.files), "error": s.error,
                          "warnings": s.warnings, "files": [str(f) for f in s.files]} for n, s in self.scans.items()},
            "match": self.match.to_dict() if self.match else None,
            "media": {k: v.to_dict() for k, v in self.media.items()},
        }
        if with_tasks:
            d["tasks"] = [{"index": t.index, "group": t.group, "group_display": t.group_display,
                           "clip": t.clip_name, "clip_index": t.clip_index, "out": str(t.out_path),
                           "duration": round(self.durations.get(t.index, 0), 3),
                           "bad": self.bad_tasks.get(t.index)} for t in self.tasks]
        return d


def suggest_workers(job: Job, encoder: str = "libx264", out: Optional[OutSpec] = None) -> int:
    rc = job.preset.run
    if rc.workers:
        w = rc.workers
    else:
        w = max(1, min(4, (os.cpu_count() or 4) // 4))
    if not encoder.startswith("lib"):
        w = 1
    if out and out.W * out.H >= 3840 * 2160:
        w = max(1, w // 2)  # R7
    return w


def _bitrate_guess_mbps(job: Job, out: OutSpec) -> float:
    o = job.preset.output
    if o.quality == "bitrate":
        return o.bitrate_mbps
    base = {"fast": 2.5, "high": 3.5, "max": 6.0}.get(o.quality, 6.0)
    return base * (out.W * out.H) / (1080 * 1920) * (out.fps / 30.0) ** 0.5


def plan_job(job: Job, bus: EventBus = NULL_BUS, probe_media: bool = True) -> JobPlan:
    plan = JobPlan(job)
    preset = job.preset
    for e in check_ffmpeg():
        plan.add("error", e)
    if plan.issues:
        return plan
    out_dir = Path(job.out_dir)

    # F6: output trùng thư mục input
    for slot, p in job.paths.items():
        if p and Path(p).exists() and Path(p).resolve() == out_dir.resolve():
            plan.add("error", f"Thư mục Output trùng với thư mục nguồn ({slot}) — sẽ ghi đè nguồn", slot=slot)

    # quét
    for name, cfg in preset.slots.items():
        if preset.combine.mode == "no_pool" and cfg.type == "pool":
            continue
        sc = scan_slot(name, cfg, job.paths.get(name), exclude=[out_dir])
        plan.scans[name] = sc
        label = cfg.label or name
        if sc.error and (cfg.required or job.paths.get(name)):
            plan.add("error", f"{label}: {sc.error}", slot=name)
        for w in sc.warnings:
            plan.add("warning", f"{label}: {w}", slot=name)

    plan.match = build_match(preset, plan.scans, job.manual_match)
    for s, k, files in plan.match.conflicts:
        if job.groups_filter and k not in [g.lower() for g in job.groups_filter]:
            continue
        plan.add("error", f"Trùng khoá nhóm '{k}' ở {preset.slots[s].label or s}: "
                          + ", ".join(f.name for f in files) + " — hãy chọn 1 file", slot=s, group=k)
    for w in plan.match.warnings:
        if "trùng khoá" in w:
            continue
        plan.add("warning", w)
    for e in plan.match.errors:
        plan.add("error", e)
    if any(i.level == "error" for i in plan.issues):
        return plan

    try:
        plan.tasks, warns = combine(preset, plan.match, job.groups_filter, job.clips_filter)
    except CombineError as e:
        plan.add("error", str(e))
        return plan
    for w in warns:
        plan.add("warning", w)
    if not plan.tasks:
        plan.add("error", "Không có video nào để tạo (kiểm tra bảng ghép / bộ lọc)")
        return plan

    # probe toàn bộ file dùng tới
    files: set[Path] = set()
    for t in plan.tasks:
        files.update(t.assets.values())
        if t.clip:
            files.add(t.clip)
    bad: dict[Path, str] = {}
    if probe_media:
        def _p(f: Path):
            try:
                return f, probe(f), None
            except ProbeError as e:
                return f, None, str(e)
        with ThreadPoolExecutor(max_workers=8) as ex:
            for f, mi, err in ex.map(_p, sorted(files)):
                if err:
                    bad[f] = err
                    plan.add("warning", f"File lỗi, các video dùng file này sẽ bị bỏ qua: {err}",
                             file=str(f))
                else:
                    plan.media[str(f)] = mi
                    for w in mi.warnings:
                        plan.add("info", f"{f.name}: {w}", file=str(f))
                if is_online_only(f):
                    plan.add("warning", f"{f.name}: file chỉ có trên cloud (chưa tải về máy)", file=str(f))

    first = plan.tasks[0]
    sample = next((f for f in first.assets.values() if f not in bad), None)
    try:
        plan.out = resolve_out_spec(preset, sample)
    except ProbeError as e:
        plan.add("error", str(e))
        return plan

    # đường dẫn output + độ dài dự kiến
    raw_paths = [build_out_path(out_dir, t, preset, job.preset_name, (plan.out.W, plan.out.H)) for t in plan.tasks]
    paths, dwarns = dedupe_paths(raw_paths)
    for w in dwarns:
        plan.add("warning", w)
    for t, p in zip(plan.tasks, paths):
        t.out_path = p
        used = set(t.assets.values()) | ({t.clip} if t.clip else set())
        badf = [bad[f] for f in used if f in bad]
        if badf:
            plan.bad_tasks[t.index] = badf[0]
            continue
        if not probe_media:
            continue
        total = 0.0
        try:
            for seg in preset.timeline:
                try:
                    total += build_segment(seg, t, plan.out, probe).duration
                except SegmentSkip:
                    pass
        except (SegmentError, ProbeError, ValueError) as e:
            plan.bad_tasks[t.index] = str(e)
            plan.add("warning", f"{t.group_display}/{t.clip_name or '-'}: {e}", group=t.group)
            continue
        plan.durations[t.index] = total
        if p.exists() and p.stat().st_size > 0:
            plan.existing += 1
    plan.total_duration = sum(plan.durations.values())
    br = _bitrate_guess_mbps(job, plan.out) + preset.audio.bitrate_k / 1000
    by_idx = {t.index: t for t in plan.tasks}
    todo = plan.total_duration if preset.run.existing != "skip" else \
        sum(d for i, d in plan.durations.items() if not by_idx[i].out_path.exists())
    plan.est_bytes = int(todo * br * 1e6 / 8)

    err = is_writable_dir(out_dir) if probe_media else None
    if err:
        plan.add("error", f"Không ghi được vào thư mục Output: {err}")
    elif probe_media:
        free = free_disk_gb(out_dir)
        need = plan.est_bytes / 1024 ** 3 + preset.run.min_free_disk_gb
        if free < need:
            plan.add("error", f"Ổ đĩa còn {free:.1f} GB, cần khoảng {need:.1f} GB (thiếu {need - free:.1f} GB)")
    if len(plan.tasks) >= 500:
        plan.add("info", f"Số lượng lớn: {len(plan.tasks)} video — kiểm tra kỹ ước tính trước khi chạy")
    from .renderer import resolve_encoder
    enc, ewarns = resolve_encoder(preset.output.video_codec)
    for w in ewarns:
        plan.add("warning", w)
    plan.workers = suggest_workers(job, enc, plan.out)
    if len(plan.bad_tasks) == len(plan.tasks):
        plan.add("error", "Mọi video đều không tạo được do file lỗi")
    return plan
