"""Preview: 1 frame PNG (debounce ở client, request mới huỷ request cũ) và video xem thử 5s."""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from vvb.filters import SegmentError, SegmentSkip
from vvb.matcher import build_match
from vvb.models import Job, TaskSpec
from vvb.probe import ProbeError
from vvb.renderer import Cancelled, RenderError, render_preview_clip, resolve_out_spec
from vvb.scanner import scan_slot

from . import JobBody, job_from_body
from ..state import STATE

router = APIRouter(prefix="/api/preview", tags=["preview"])


class PreviewBody(JobBody):
    group: Optional[str] = None
    clip: Optional[str] = None
    segment: Optional[int] = None
    t: float = 1.0
    before: bool = False
    seconds: float = 5.0


def task_for_preview(job: Job, group: Optional[str], clip: Optional[str]) -> TaskSpec:
    """Dựng 1 task để xem trước — kể cả khi nhóm chưa đủ slot (chỉ cần file của đoạn đang xem)."""
    p = job.preset
    scans = {n: scan_slot(n, s, job.paths.get(n)) for n, s in p.slots.items()}
    m = build_match(p, scans, job.manual_match)
    if not m.rows:
        raise HTTPException(422, "Chưa có nhóm nào — chọn thư mục nguồn trước")
    row = next((r for r in m.rows if group and (r.key == group or r.display == group)), m.rows[0])
    assets = {k: v for k, v in m.shared.items() if v}
    for s, c in row.cells.items():
        f = c.file or (c.candidates[0] if c.candidates else None)
        if f:
            assets[s] = f
    cl = None
    if p.uses_pool():
        if not m.pool:
            raise HTTPException(422, "Pool rỗng — chưa có clip để xem trước")
        cl = next((f for f in m.pool if clip and (f.stem == clip or f.name == clip)), m.pool[0])
    idx = (m.pool.index(cl) + 1) if cl else 0
    return TaskSpec(index=1, group=row.key, group_display=row.display, group_raw=row.raw, assets=assets,
                    clip=cl, clip_index=idx, seed=p.combine.seed + 1)


def _default_segment(job: Job) -> int:
    return next((i for i, s in enumerate(job.preset.timeline) if s.kind == "composite"), 0)


@router.post("/frame")
def frame(b: PreviewBody):
    job = job_from_body(b)
    task = task_for_preview(job, b.group, b.clip)
    seg = b.segment if b.segment is not None else _default_segment(job)
    if not 0 <= seg < len(job.preset.timeline):
        raise HTTPException(422, "Chỉ số đoạn không hợp lệ")
    try:
        from vvb.filters import build_segment
        from vvb.probe import probe
        sample = next(iter(task.assets.values()), None)
        full = resolve_out_spec(job.preset, sample)
        g = build_segment(job.preset.timeline[seg], task, full, probe)
        png = STATE.preview.frame(job.preset, task, seg, b.t, before=b.before)
    except Cancelled:
        return Response(status_code=204)
    except SegmentSkip:
        raise HTTPException(422, "Đoạn này bị bỏ qua với nhóm đang chọn (thiếu file, optional)") from None
    except (SegmentError, ProbeError, RenderError, ValueError) as e:
        raise HTTPException(422, str(e)) from None
    headers = {"X-Duration": f"{g.duration:.3f}", "X-W": str(full.W), "X-H": str(full.H),
               "X-Group": quote(task.group_display), "X-Clip": quote(task.clip_name),
               "X-Warnings": quote("|".join(g.warnings)), "Cache-Control": "no-store"}
    return Response(png, media_type="image/png", headers=headers)


@router.post("/clip")
def clip(b: PreviewBody):
    job = job_from_body(b)
    task = task_for_preview(job, b.group, b.clip)
    STATE.preview_dir.mkdir(parents=True, exist_ok=True)
    for old in STATE.preview_dir.glob("pv_*.mp4"):  # dọn bản cũ > 1 giờ
        if time.time() - old.stat().st_mtime > 3600:
            old.unlink(missing_ok=True)
    name = f"pv_{uuid.uuid4().hex[:10]}.mp4"
    try:
        render_preview_clip(job.preset, task, STATE.preview_dir / name, seconds=min(15.0, b.seconds),
                            temp_root=STATE.preview_dir)
    except (RenderError, SegmentError, ProbeError) as e:
        raise HTTPException(422, str(e)) from None
    return {"url": f"/api/preview/file/{name}"}


@router.get("/file/{name}")
def file(name: str):
    if "/" in name or "\\" in name or not name.startswith("pv_"):
        raise HTTPException(400)
    f = STATE.preview_dir / name
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="video/mp4")
