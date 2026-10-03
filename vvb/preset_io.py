"""Đọc / ghi / kiểm tra / nâng cấp preset."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Union

from pydantic import ValidationError

from . import defaults as D
from .models import Preset


class PresetError(ValueError):
    """Preset sai. `errors` = danh sách (đường dẫn trường, thông báo)."""

    def __init__(self, errors: list[tuple[str, str]], source: str = ""):
        self.errors = errors
        self.source = source
        lines = "\n".join(f"  - {loc}: {msg}" for loc, msg in errors)
        super().__init__(f"Preset không hợp lệ{(' (' + source + ')') if source else ''}:\n{lines}")


def upgrade(d: dict[str, Any]) -> dict[str, Any]:
    """Nâng cấp dict preset cũ lên schema hiện tại."""
    d = dict(d)
    ver = d.get("schema_version", 1)
    if ver > D.SCHEMA_VERSION:
        raise PresetError([("schema_version", f"preset mới hơn phiên bản tool ({ver} > {D.SCHEMA_VERSION})")])
    # v1 là bản đầu — chỗ để thêm bước nâng cấp v1->v2 sau này
    d["schema_version"] = D.SCHEMA_VERSION
    return d


def validate_preset_dict(d: dict[str, Any], source: str = "") -> Preset:
    try:
        return Preset.model_validate(upgrade(d))
    except ValidationError as e:
        errs = []
        for err in e.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "(gốc)"
            msg = err["msg"].removeprefix("Value error, ")
            errs.append((loc, msg))
        raise PresetError(errs, source) from None


def preset_dirs() -> list[Path]:
    return [D.BUILTIN_PRESET_DIR, D.USER_PRESET_DIR]


def find_preset(name_or_path: Union[str, Path]) -> Path:
    p = Path(name_or_path)
    if p.suffix.lower() == ".json" and p.exists():
        return p
    stem = p.stem if p.suffix.lower() == ".json" else str(name_or_path)
    for d in reversed(preset_dirs()):  # preset người dùng ưu tiên
        cand = d / f"{stem}.json"
        if cand.exists():
            return cand
    raise FileNotFoundError(f"Không tìm thấy preset: {name_or_path}")


def load_preset(name_or_path: Union[str, Path]) -> Preset:
    path = find_preset(name_or_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise PresetError([(f"dòng {e.lineno}", f"JSON lỗi: {e.msg}")], str(path)) from None
    return validate_preset_dict(data, str(path))


def preset_to_dict(p: Preset) -> dict[str, Any]:
    return p.model_dump(mode="json", by_alias=True, exclude_none=False)


def save_preset(p: Preset, path: Union[str, Path]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(preset_to_dict(p), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def list_presets() -> list[dict[str, Any]]:
    """Danh sách preset: id, tên, mô tả, builtin."""
    seen: dict[str, dict[str, Any]] = {}
    for d in preset_dirs():
        if not d.exists():
            continue
        builtin = d == D.BUILTIN_PRESET_DIR
        for f in sorted(d.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                seen[f.stem] = {"id": f.stem, "name": data.get("name", f.stem),
                                "description": data.get("description", ""),
                                "builtin": builtin, "path": str(f)}
            except Exception:  # noqa: BLE001
                seen[f.stem] = {"id": f.stem, "name": f.stem, "description": "(lỗi đọc)",
                                "builtin": builtin, "path": str(f), "broken": True}
    return list(seen.values())
