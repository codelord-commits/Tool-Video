"""Quét file cho từng slot: lọc rác, natural sort, loại thư mục Output."""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from . import defaults as D
from .models import Preset, SlotCfg


def natural_key(s: str) -> list:
    """clip2 đứng trước clip10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


@dataclass
class ScanResult:
    slot: str
    path: Optional[Path]
    files: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: Optional[str] = None


def _is_junk(p: Path) -> bool:
    n = p.name.lower()
    if n in D.JUNK_NAMES or p.name.startswith(D.JUNK_PREFIXES):
        return True
    if any(n.endswith(s) for s in D.PARTIAL_SUFFIXES):
        return True
    stem_l = p.stem.lower()
    return stem_l.endswith(".part")


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def slot_extensions(cfg: SlotCfg) -> tuple[str, ...]:
    exts = tuple(e.lower() if e.startswith(".") else "." + e.lower() for e in (cfg.extensions or D.VIDEO_EXTS))
    if cfg.allow_images:
        exts += D.IMAGE_EXTS
    return exts


def list_media(folder: Path, exts: Iterable[str], recursive: bool, exclude: Iterable[Path] = (),
               warnings: Optional[list[str]] = None) -> list[Path]:
    exts = tuple(exts)
    exclude = [Path(e) for e in exclude]
    it = folder.rglob("*") if recursive else folder.iterdir()
    out: list[Path] = []
    for p in it:
        if any(_is_within(p, e) for e in exclude):
            continue
        if not p.is_file() or _is_junk(p):
            continue
        if p.suffix.lower() not in exts:
            continue
        try:
            if p.stat().st_size == 0:
                if warnings is not None:
                    warnings.append(f"Bỏ qua file 0 byte: {p.name}")
                continue
        except OSError as e:
            if warnings is not None:
                warnings.append(f"Không đọc được {p.name}: {e}")
            continue
        out.append(p)
    out.sort(key=lambda p: natural_key(str(p.relative_to(folder))))
    return out


def scan_slot(name: str, cfg: SlotCfg, path: Optional[str], exclude: Iterable[Path] = ()) -> ScanResult:
    """Quét 1 slot. path: folder (per_group/pool) hoặc file/folder chứa 1 file (shared)."""
    if not path:
        return ScanResult(name, None, error=None if not cfg.required else "Chưa chọn đường dẫn")
    p = Path(path)
    res = ScanResult(name, p)
    if not p.exists():
        res.error = f"Không tồn tại: {p}"
        return res
    exts = slot_extensions(cfg)
    if cfg.type == "shared":
        if p.is_file():
            res.files = [p] if p.suffix.lower() in exts else []
            if not res.files:
                res.error = f"Định dạng không hỗ trợ: {p.name}"
        else:
            files = list_media(p, exts, False, exclude, res.warnings)
            if len(files) == 1:
                res.files = files
            elif not files:
                res.error = "Thư mục không có file hợp lệ"
            else:
                res.error = f"Thư mục shared phải chứa đúng 1 file (đang có {len(files)})"
        return res
    if not p.is_dir():
        res.error = f"Cần thư mục, không phải file: {p.name}"
        return res
    recursive = cfg.recursive
    res.files = list_media(p, exts, recursive, exclude, res.warnings)
    if not res.files:
        res.error = "Thư mục rỗng"
    return res


def resolve_project(preset: Preset, project_dir: str) -> dict[str, str]:
    """Tự nhận slot theo tên thư mục/file mặc định trong preset (không phân biệt hoa thường)."""
    root = Path(project_dir)
    found: dict[str, str] = {}
    if not root.is_dir():
        return found
    entries = {e.name.lower(): e for e in root.iterdir() if not _is_junk(e)}
    for name, cfg in preset.slots.items():
        if cfg.type in ("per_group", "pool"):
            cands = [cfg.default_dir] if cfg.default_dir else []
            cands.append(name)
            for c in cands:
                if c and c.lower() in entries and entries[c.lower()].is_dir():
                    found[name] = str(entries[c.lower()])
                    break
        else:
            pats = [x.lower() for x in (cfg.default_file or [])] + [f"{name.lower()}.*"]
            match = None
            for pat in pats:
                for lname, e in sorted(entries.items()):
                    if fnmatch.fnmatch(lname, pat):
                        match = e
                        break
                if match:
                    break
            if match:
                found[name] = str(match)
    return found
