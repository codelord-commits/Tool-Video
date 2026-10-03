"""Dự án: tự nhận slot, quét + ghép (nhanh) hoặc pre-flight đầy đủ, thông tin media."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from vvb.batch import find_unfinished
from vvb.plan import plan_job
from vvb.probe import ProbeError, probe
from vvb.scanner import resolve_project

from . import JobBody, job_from_body, parse_preset
from ..state import STATE

router = APIRouter(prefix="/api", tags=["project"])


class ResolveBody(BaseModel):
    preset: dict[str, Any]
    project: str


@router.post("/project/resolve")
def resolve(b: ResolveBody):
    p = parse_preset(b.preset)
    if not Path(b.project).is_dir():
        raise HTTPException(404, "Thư mục dự án không tồn tại")
    paths = resolve_project(p, b.project)
    s = STATE.load_settings()
    proj = str(Path(b.project).resolve())
    same = lambda x: os.path.normcase(str(Path(x).resolve())) == os.path.normcase(proj)  # noqa: E731 — D:\a == D:/a
    rec = [proj] + [x for x in s.get("recent_projects", []) if not same(x)]
    STATE.save_settings({"recent_projects": rec})
    return {"paths": paths, "out_dir": str(Path(b.project) / "Output"),
            "missing": [n for n in p.slots if n not in paths]}


class PlanBody(JobBody):
    probe: bool = False


@router.post("/plan")
def plan(b: PlanBody):
    job = job_from_body(b)
    pl = plan_job(job, STATE.bus, probe_media=b.probe)
    d = pl.to_dict(with_tasks=True)
    d["out_dir"] = str(job.out_dir)
    if b.probe:
        uf = find_unfinished(job.out_dir)
        d["unfinished"] = _unfinished_summary(uf) if uf and not STATE.running else None
    return d


def _unfinished_summary(d: dict[str, Any]) -> dict[str, Any]:
    tasks = d.get("tasks", [])
    done = sum(1 for t in tasks if t["status"] in ("done", "skipped"))
    return {"done": done, "total": len(tasks), "updated": d.get("updated"), "out_dir": d.get("out_dir"),
            "preset_name": d.get("preset_name")}


@router.get("/media")
def media(path: str):
    try:
        return probe(path).to_dict()
    except ProbeError as e:
        raise HTTPException(422, str(e)) from None
