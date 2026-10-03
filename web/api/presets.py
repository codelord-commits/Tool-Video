"""Quản lý preset: danh sách, đọc, lưu, xoá, kiểm tra, schema."""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from vvb import defaults as D
from vvb.models import Preset
from vvb.preset_io import PresetError, find_preset, list_presets, preset_to_dict, save_preset, validate_preset_dict

from . import parse_preset

router = APIRouter(prefix="/api", tags=["presets"])


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name.replace("đ", "d").replace("Đ", "D"))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[:60] or "preset"


def _is_builtin(pid: str) -> bool:
    return (D.BUILTIN_PRESET_DIR / f"{pid}.json").exists()


def _is_user(pid: str) -> bool:
    return (D.USER_PRESET_DIR / f"{pid}.json").exists()


@router.get("/presets")
def presets():
    return list_presets()


@router.get("/presets/{pid}")
def get_preset(pid: str):
    try:
        path = find_preset(pid)
    except FileNotFoundError:
        raise HTTPException(404, "Không tìm thấy preset") from None
    raw = json.loads(path.read_text(encoding="utf-8"))
    try:
        p = validate_preset_dict(raw, str(path))
        return {"id": pid, "builtin": not _is_user(pid), "preset": preset_to_dict(p)}
    except PresetError as e:
        raise HTTPException(422, {"message": str(e), "errors": [{"loc": l, "msg": m} for l, m in e.errors]}) from None


class SaveBody(BaseModel):
    preset: dict[str, Any]
    overwrite: bool = True


@router.put("/presets/{pid}")
def put_preset(pid: str, b: SaveBody):
    pid = slugify(pid)
    if _is_builtin(pid) and not _is_user(pid) and not b.overwrite:
        raise HTTPException(409, "Trùng tên preset có sẵn")
    p = parse_preset(b.preset)
    for slot in p.slots.values():  # preset không chứa đường dẫn tuyệt đối (13.4)
        for f in (slot.default_dir, *(slot.default_file or [])):
            if f and (":" in f or f.startswith(("/", "\\"))):
                raise HTTPException(422, "Preset không được chứa đường dẫn tuyệt đối (đường dẫn thuộc về job)")
    save_preset(p, D.USER_PRESET_DIR / f"{pid}.json")
    return {"id": pid, "builtin": False}


@router.delete("/presets/{pid}")
def delete_preset(pid: str):
    f = D.USER_PRESET_DIR / f"{pid}.json"
    if not f.exists():
        raise HTTPException(400, "Chỉ xoá được preset người dùng tạo")
    f.unlink()
    return {"ok": True}


@router.post("/presets/validate")
def validate(body: dict[str, Any]):
    try:
        validate_preset_dict(body.get("preset", body))
        return {"ok": True, "errors": []}
    except PresetError as e:
        return {"ok": False, "errors": [{"loc": l, "msg": m} for l, m in e.errors]}


@router.post("/presets/slug")
def slug(body: dict[str, Any]):
    base = slugify(str(body.get("name", "preset")))
    pid, i = base, 2
    while _is_user(pid) or _is_builtin(pid):
        pid = f"{base}_{i}"
        i += 1
    return {"id": pid}


@router.get("/schema")
def schema():
    return Preset.model_json_schema(by_alias=True)
