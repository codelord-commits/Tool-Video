"""Ghép nhóm: lấy khoá từ tên file, chuẩn hoá, alias, dựng bảng nhóm × slot."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import defaults as D
from .models import GroupsCfg, Preset
from .scanner import ScanResult, natural_key


def build_alias_map(cfg: GroupsCfg) -> dict[str, str]:
    """tên đã chuẩn hoá -> khoá chuẩn."""
    merged: dict[str, list[str]] = {k: list(v) for k, v in D.DEFAULT_ALIASES.items()} if cfg.use_aliases else {}
    for k, v in cfg.aliases.items():
        merged.setdefault(k, []).extend(v)
    out: dict[str, str] = {}
    for canon, names in merged.items():
        c = _basic_norm(canon, cfg)
        out[c] = c
        for n in names:
            out[_basic_norm(n, cfg)] = c
    return out


def _basic_norm(s: str, cfg: GroupsCfg) -> str:
    if cfg.strip_accents:
        s = s.replace("đ", "d").replace("Đ", "D")
        s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    if cfg.case_insensitive:
        s = s.lower()
    if cfg.strip_chars:
        s = s.strip(" -_.\t")
        s = re.sub(r"\s+", " ", s)
    return s


def normalize_key(raw: str, cfg: GroupsCfg, alias_map: Optional[dict[str, str]] = None) -> str:
    k = _basic_norm(raw, cfg)
    if alias_map is not None:
        if k in alias_map:
            return alias_map[k]
        compact = re.sub(r"[\s\-_.]", "", k)
        if compact in alias_map:
            return alias_map[compact]
    return k


def extract_raw_key(path: Path, slot_root: Optional[Path], cfg: GroupsCfg) -> Optional[str]:
    stem = path.stem
    mode = cfg.key_mode
    if mode == "stem":
        return stem
    if mode == "regex":
        if not cfg.regex:
            return None
        m = re.search(cfg.regex, stem, re.IGNORECASE if cfg.case_insensitive else 0)
        if not m:
            return None
        return m.group(1) if m.groups() else m.group(0)
    if mode in ("prefix", "suffix"):
        parts = stem.split(cfg.separator)
        if len(parts) < 2:
            return stem
        return parts[0] if mode == "prefix" else parts[-1]
    if mode == "subfolder":
        if slot_root is None:
            return path.parent.name
        try:
            rel = path.relative_to(slot_root)
        except ValueError:
            return path.parent.name
        return rel.parts[0] if len(rel.parts) > 1 else None
    return stem


@dataclass
class Cell:
    status: str  # ok | missing | duplicate | shared
    file: Optional[Path] = None
    candidates: list[Path] = field(default_factory=list)


@dataclass
class GroupRow:
    key: str
    display: str
    raw: str
    cells: dict[str, Cell] = field(default_factory=dict)
    valid: bool = True
    reasons: list[str] = field(default_factory=list)

    def file(self, slot: str) -> Optional[Path]:
        c = self.cells.get(slot)
        return c.file if c else None


@dataclass
class MatchResult:
    key_slot: Optional[str]
    rows: list[GroupRow] = field(default_factory=list)
    shared: dict[str, Optional[Path]] = field(default_factory=dict)
    pool: list[Path] = field(default_factory=list)
    pool_keys: dict[Path, Optional[str]] = field(default_factory=dict)
    unused: list[tuple[str, Path]] = field(default_factory=list)
    conflicts: list[tuple[str, str, list[Path]]] = field(default_factory=list)  # slot, key, files
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def valid_rows(self) -> list[GroupRow]:
        return [r for r in self.rows if r.valid]

    def to_dict(self) -> dict:
        return {
            "key_slot": self.key_slot,
            "rows": [{"key": r.key, "display": r.display, "raw": r.raw, "valid": r.valid, "reasons": r.reasons,
                      "cells": {s: {"status": c.status, "file": str(c.file) if c.file else None,
                                    "candidates": [str(x) for x in c.candidates]} for s, c in r.cells.items()}}
                     for r in self.rows],
            "shared": {k: str(v) if v else None for k, v in self.shared.items()},
            "pool": [str(p) for p in self.pool],
            "unused": [{"slot": s, "file": str(f)} for s, f in self.unused],
            "conflicts": [{"slot": s, "key": k, "files": [str(f) for f in fs]} for s, k, fs in self.conflicts],
            "warnings": self.warnings, "errors": self.errors,
        }


def _index_slot(scan: ScanResult, cfg: GroupsCfg, amap: dict[str, str]) -> tuple[dict[str, list[Path]], dict[str, str]]:
    idx: dict[str, list[Path]] = {}
    raw: dict[str, str] = {}
    for f in scan.files:
        r = extract_raw_key(f, scan.path, cfg)
        if r is None:
            continue
        k = normalize_key(r, cfg, amap)
        idx.setdefault(k, []).append(f)
        raw.setdefault(k, r)
    return idx, raw


def _pool_key(f: Path, keys: set[str], cfg: GroupsCfg, amap: dict[str, str]) -> Optional[str]:
    for tok in re.split(r"[\s\-_.]+", f.stem):
        if tok and normalize_key(tok, cfg, amap) in keys:
            return normalize_key(tok, cfg, amap)
    return None


def build_match(preset: Preset, scans: dict[str, ScanResult],
                manual: Optional[dict[str, dict[str, str]]] = None) -> MatchResult:
    """Dựng bảng ghép nhóm × slot từ kết quả quét."""
    cfg = preset.groups
    amap = build_alias_map(cfg)
    key_slot = preset.key_slot()
    res = MatchResult(key_slot=key_slot)
    manual = manual or {}

    for name, s in preset.slots.items():
        sc = scans.get(name)
        if s.type == "shared":
            res.shared[name] = sc.files[0] if sc and sc.files else None
            if s.required and res.shared[name] is None:
                res.errors.append(f"Thiếu file dùng chung: {s.label or name}")
        elif s.type == "pool" and sc:
            res.pool = list(sc.files)

    if key_slot is None:
        # Không có slot per_group: một "nhóm" duy nhất
        row = GroupRow(key="all", display="all", raw="all")
        res.rows.append(row)
        return res

    per_group = [n for n, s in preset.slots.items() if s.type == "per_group"]
    indexes = {}
    raws = {}
    for n in per_group:
        sc = scans.get(n)
        if sc is None:
            indexes[n], raws[n] = {}, {}
        else:
            indexes[n], raws[n] = _index_slot(sc, cfg, amap)

    keys = sorted(indexes[key_slot].keys(), key=lambda k: natural_key(raws[key_slot].get(k, k)))
    for k in keys:
        raw = raws[key_slot][k]
        disp = raw if cfg.display_name == "original" else k
        row = GroupRow(key=k, display=disp, raw=raw)
        for n in per_group:
            files = indexes[n].get(k, [])
            if len(files) == 1:
                row.cells[n] = Cell("ok", files[0])
            elif len(files) > 1:
                row.cells[n] = Cell("duplicate", None, files)
            else:
                row.cells[n] = Cell("missing")
        for n, path in manual.get(k, {}).items():
            if n in row.cells and path:
                row.cells[n] = Cell("ok", Path(path))
        for n in per_group:
            c = row.cells[n]
            slot_cfg = preset.slots[n]
            if c.status == "duplicate":
                row.valid = False
                row.reasons.append(f"{slot_cfg.label or n}: trùng khoá ({', '.join(f.name for f in c.candidates)})")
                res.conflicts.append((n, k, c.candidates))
            elif c.status == "missing" and slot_cfg.required:
                row.valid = False
                row.reasons.append(f"Thiếu {slot_cfg.label or n}")
        if not row.valid:
            res.warnings.append(f"Bỏ nhóm '{disp}': " + "; ".join(row.reasons))
        res.rows.append(row)

    key_set = set(keys)
    for n in per_group:
        if n == key_slot:
            continue
        for k, files in indexes[n].items():
            if k not in key_set:
                for f in files:
                    res.unused.append((n, f))
                    res.warnings.append(f"Không dùng tới: {preset.slots[n].label or n}/{f.name}")

    if preset.combine.pool_match_group:
        res.pool_keys = {f: _pool_key(f, key_set, cfg, amap) for f in res.pool}
    return res
