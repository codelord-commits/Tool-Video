"""Điều khiển job: bắt đầu, tạm dừng, tiếp tục, dừng, chạy lại lỗi, resume sau crash."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from vvb.batch import BatchRunner, JobError, find_unfinished, job_from_journal
from vvb.models import Job
from vvb.plan import plan_job

from . import JobBody, job_from_body
from ..state import STATE

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class StartBody(JobBody):
    workers: Optional[int] = None


def _start(job: Job, workers: Optional[int] = None) -> dict:
    if STATE.running:
        raise HTTPException(409, "Đang có job chạy")
    plan = plan_job(job, STATE.bus)
    if not plan.ok:
        raise HTTPException(422, {"message": "Pre-flight chưa đạt", "blockers": plan.blockers(),
                                  "plan": plan.to_dict(with_tasks=False)})
    try:
        runner = BatchRunner(plan, STATE.bus, workers)
    except JobError as e:
        raise HTTPException(422, str(e)) from None
    STATE.runner = runner
    STATE.log_buffer.clear()

    def target():
        try:
            runner.run()
        except Exception as e:  # noqa: BLE001
            STATE.bus.log("error", f"Job dừng do lỗi: {e}")
            STATE.bus.emit("job", state="error", summary=runner.summary.to_dict(), error=str(e))

    STATE.job_thread = threading.Thread(target=target, daemon=True, name="vvb-job")
    STATE.job_thread.start()
    return {"ok": True, "count": len(plan.tasks), "workers": runner.workers}


@router.post("/start")
def start(b: StartBody):
    job = job_from_body(b)
    STATE.last_job_args = {"body": b.model_dump()}
    STATE.save_settings({"last_job": {"preset_name": b.preset_name, "paths": b.paths, "out_dir": str(job.out_dir)}})
    return _start(job, b.workers)


@router.post("/retry")
def retry():
    """Chạy lại các video lỗi: chạy lại job với existing=skip → chỉ làm video chưa có."""
    if not STATE.last_job_args:
        raise HTTPException(400, "Chưa có job để chạy lại")
    b = StartBody(**STATE.last_job_args["body"])
    job = job_from_body(b)
    job.preset.run.existing = "skip"
    return _start(job, b.workers)


@router.post("/pause")
def pause():
    if STATE.runner:
        STATE.runner.pause()
    return STATE.snapshot()


@router.post("/resume")
def resume_running():
    if STATE.runner:
        STATE.runner.resume()
    return STATE.snapshot()


@router.post("/cancel")
def cancel():
    if STATE.runner:
        STATE.runner.cancel()
    return {"ok": True}


@router.get("/current")
def current():
    snap = STATE.snapshot()
    snap["logs"] = list(STATE.log_buffer)[-2000:]
    return snap


@router.get("/unfinished")
def unfinished(out: str):
    d = find_unfinished(Path(out))
    if not d or STATE.running:
        return {"unfinished": None}
    tasks = d.get("tasks", [])
    return {"unfinished": {"done": sum(t["status"] in ("done", "skipped") for t in tasks), "total": len(tasks),
                           "updated": d.get("updated"), "out_dir": d.get("out_dir"),
                           "preset_name": d.get("preset_name")}}


class ResumeBody(BaseModel):
    out_dir: str


@router.post("/resume-unfinished")
def resume_unfinished(b: ResumeBody):
    d = find_unfinished(Path(b.out_dir))
    if not d:
        raise HTTPException(404, "Không có job dang dở")
    job = job_from_journal(d)
    job.preset.run.existing = "skip"
    return _start(job)
