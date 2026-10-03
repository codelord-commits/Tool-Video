"""Đặt tên file/thư mục output theo template + làm sạch tên."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import Preset, TaskSpec

_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
MAX_LEN = 120


def sanitize_filename(name: str, fallback: str = "video") -> str:
    s = _FORBIDDEN.sub("_", name).strip().rstrip(". ")
    if not s:
        s = fallback
    if s.split(".")[0].lower() in _RESERVED:
        s = "_" + s
    return s[:MAX_LEN].rstrip(". ") or fallback


class _SafeDict(dict):
    def __missing__(self, key):  # biến lạ giữ nguyên
        return "{" + key + "}"


def template_vars(task: TaskSpec, preset: Preset, preset_name: str, size: tuple[int, int],
                  now: Optional[datetime] = None) -> dict[str, str]:
    now = now or datetime.now()
    return {
        "group": task.group_display, "group_raw": task.group_raw, "group_key": task.group,
        "clip": task.clip_name, "clip_index": f"{task.clip_index:02d}", "index": f"{task.index:03d}",
        "date": now.strftime("%Y%m%d"), "time": now.strftime("%H%M%S"),
        "preset": preset_name or preset.name, "w": str(size[0]), "h": str(size[1]),
    }


def render_template(tpl: str, vars: dict[str, str]) -> str:
    out = tpl.format_map(_SafeDict(vars))
    return re.sub(r"_{2,}", "_", out).strip("_ ")


def build_out_path(out_dir: Path, task: TaskSpec, preset: Preset, preset_name: str,
                   size: tuple[int, int], now: Optional[datetime] = None) -> Path:
    v = template_vars(task, preset, preset_name, size, now)
    folder = render_template(preset.output.folder_template, v)
    parts = [sanitize_filename(p) for p in re.split(r"[\\/]+", folder) if p.strip()]
    name = sanitize_filename(render_template(preset.output.name_template, v), f"video_{task.index:03d}")
    return out_dir.joinpath(*parts) / f"{name}.{preset.output.container}"


def dedupe_paths(paths: list[Path]) -> tuple[list[Path], list[str]]:
    """Hai video trùng tên → thêm _2, _3."""
    seen: dict[str, int] = {}
    out, warns = [], []
    for p in paths:
        key = str(p).lower()
        if key in seen:
            seen[key] += 1
            np = p.with_name(f"{p.stem}_{seen[key]}{p.suffix}")
            while str(np).lower() in seen:
                seen[key] += 1
                np = p.with_name(f"{p.stem}_{seen[key]}{p.suffix}")
            seen[str(np).lower()] = 1
            warns.append(f"Trùng tên output: {p.name} → {np.name}")
            out.append(np)
        else:
            seen[key] = 1
            out.append(p)
    return out, warns


def unique_path(p: Path) -> Path:
    """Tên chưa tồn tại trên đĩa: x.mp4 → x_2.mp4 …"""
    if not p.exists():
        return p
    i = 2
    while True:
        np = p.with_name(f"{p.stem}_{i}{p.suffix}")
        if not np.exists():
            return np
        i += 1
