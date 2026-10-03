"""Mặt tiền dùng chung cho CLI và web: dựng job, kiểm tra, chạy, preview."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from .batch import BatchRunner, Summary, find_unfinished, job_from_journal
from .events import NULL_BUS, EventBus
from .models import Job, Preset
from .plan import JobPlan, plan_job
from .preset_io import find_preset, load_preset
from .scanner import resolve_project


def make_job(preset: Union[str, Path, Preset], *, project: Optional[str] = None,
             paths: Optional[dict[str, str]] = None, out_dir: Optional[str] = None,
             groups: Optional[list[str]] = None, clips: Optional[list[str]] = None,
             manual_match: Optional[dict[str, dict[str, str]]] = None) -> Job:
    """Tạo Job: preset + thư mục dự án (tự nhận slot) + đường dẫn ghi đè."""
    if isinstance(preset, Preset):
        p, name = preset, preset.name
    else:
        p = load_preset(preset)
        name = find_preset(preset).stem
    resolved: dict[str, str] = {}
    if project:
        resolved.update(resolve_project(p, project))
    for k, v in (paths or {}).items():
        if v:
            resolved[k] = v
    if out_dir is None:
        base = Path(project) if project else Path.cwd()
        out_dir = str(base / "Output")
    return Job(preset=p, paths=resolved, out_dir=Path(out_dir), groups_filter=groups or None,
               clips_filter=clips or None, manual_match=manual_match or {}, preset_name=name)


def check_job(job: Job, bus: EventBus = NULL_BUS) -> JobPlan:
    return plan_job(job, bus)


def run_job(job: Job, bus: EventBus = NULL_BUS, workers: Optional[int] = None,
            plan: Optional[JobPlan] = None) -> Summary:
    """Chạy job đầy đủ (blocking)."""
    plan = plan or plan_job(job, bus)
    return BatchRunner(plan, bus, workers).run()


def resume_job(out_dir: str, bus: EventBus = NULL_BUS) -> Optional[Summary]:
    d = find_unfinished(Path(out_dir))
    if d is None:
        return None
    job = job_from_journal(d)
    job.preset.run.existing = "skip"
    return run_job(job, bus)
