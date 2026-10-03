"""Tổ hợp nhóm × pool thành danh sách TaskSpec."""
from __future__ import annotations

import random
from pathlib import Path
from typing import Optional

from .matcher import MatchResult, normalize_key, build_alias_map
from .models import Preset, TaskSpec


class CombineError(ValueError):
    pass


def _match_filter(values: Optional[list[str]], candidates: list[str]) -> Optional[set[str]]:
    if not values:
        return None
    wanted = {v.strip().lower() for v in values if v.strip()}
    return {c for c in candidates if c.lower() in wanted}


def combine(preset: Preset, match: MatchResult, groups_filter: Optional[list[str]] = None,
            clips_filter: Optional[list[str]] = None) -> tuple[list[TaskSpec], list[str]]:
    """Trả (tasks, cảnh báo)."""
    cfg = preset.combine
    warns: list[str] = []
    rows = match.valid_rows
    if groups_filter:
        amap = build_alias_map(preset.groups)
        wanted = {normalize_key(g, preset.groups, amap) for g in groups_filter} | {g.lower() for g in groups_filter}
        rows = [r for r in rows if r.key in wanted or r.display.lower() in wanted]
    pool = list(match.pool)
    if clips_filter:
        wanted_c = {c.strip().lower() for c in clips_filter}
        pool = [p for p in pool if p.stem.lower() in wanted_c or p.name.lower() in wanted_c]

    use_pool = preset.uses_pool()
    if use_pool and not pool:
        raise CombineError("Pool rỗng — không có clip nào để tổ hợp")

    pairs: list[tuple] = []  # (row, clip_or_None, clip_index)
    if not use_pool:
        pairs = [(r, None, 0) for r in rows]
    elif cfg.mode == "cartesian":
        for r in rows:
            for i, c in enumerate(pool, 1):
                # clip có tên nhóm chỉ đi với nhóm đó; clip không tên nhóm dùng cho mọi nhóm
                if cfg.pool_match_group and match.pool_keys.get(c) not in (None, r.key):
                    continue
                pairs.append((r, c, i))
    elif cfg.mode == "zip":
        n = min(len(rows), len(pool))
        if len(rows) != len(pool):
            warns.append(f"zip: {len(rows)} nhóm nhưng {len(pool)} clip — chỉ lấy {n}")
        pairs = [(rows[i], pool[i], i + 1) for i in range(n)]
    elif cfg.mode == "per_group_subset":
        k = cfg.subset_k or 1
        if k > len(pool):
            warns.append(f"subset_k={k} lớn hơn số clip ({len(pool)}) — dùng {len(pool)}")
            k = len(pool)
        rng = random.Random(cfg.seed)
        for gi, r in enumerate(rows):
            if cfg.subset_strategy == "random":
                chosen = rng.sample(range(len(pool)), k)
            else:
                chosen = [(gi * k + j) % len(pool) for j in range(k)]
            for idx in sorted(chosen):
                pairs.append((r, pool[idx], idx + 1))

    if cfg.limit:
        pairs = pairs[: cfg.limit]

    tasks: list[TaskSpec] = []
    shared = {k: v for k, v in match.shared.items() if v is not None}
    for n, (r, clip, ci) in enumerate(pairs, 1):
        assets: dict[str, Path] = dict(shared)
        for slot, cell in r.cells.items():
            if cell.file is not None:
                assets[slot] = cell.file
        tasks.append(TaskSpec(index=n, group=r.key, group_display=r.display, group_raw=r.raw,
                              assets=assets, clip=clip, clip_index=ci, seed=cfg.seed + n))
    return tasks, warns
