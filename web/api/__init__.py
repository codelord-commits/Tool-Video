"""Các router REST."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException
from pydantic import BaseModel

from vvb.models import Job, Preset
from vvb.preset_io import PresetError, validate_preset_dict


class JobBody(BaseModel):
    """Thân request chung: preset đang chỉnh + đường dẫn job."""
    preset: dict[str, Any]
    preset_name: str = ""
    paths: dict[str, str] = {}
    out_dir: Optional[str] = None
    groups: Optional[list[str]] = None
    clips: Optional[list[str]] = None
    manual: dict[str, dict[str, str]] = {}


def parse_preset(d: dict[str, Any]) -> Preset:
    try:
        return validate_preset_dict(d)
    except PresetError as e:
        raise HTTPException(422, {"message": "Preset không hợp lệ", "errors": [
            {"loc": loc, "msg": msg} for loc, msg in e.errors]}) from None


def job_from_body(b: JobBody) -> Job:
    from pathlib import Path
    preset = parse_preset(b.preset)
    out = b.out_dir
    if not out:
        first = next((p for p in b.paths.values() if p), None)
        base = Path(first).parent if first else Path.home()
        out = str(base / "Output")
    return Job(preset=preset, paths={k: v for k, v in b.paths.items() if v}, out_dir=Path(out),
               groups_filter=b.groups or None, clips_filter=b.clips or None, manual_match=b.manual or {},
               preset_name=b.preset_name)
