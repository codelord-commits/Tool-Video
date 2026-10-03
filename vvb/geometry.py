"""Toán hình học: vùng (region) → pixel chẵn, fit/anchor của clip trong ô."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Union

from .models import XY, Protect, Region


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    def as_ratio(self, W: int, H: int) -> dict[str, float]:
        return {"x": self.x / W, "y": self.y / H, "w": self.w / W, "h": self.h / H}


def even_floor(v: float) -> int:
    return int(math.floor(v / 2.0)) * 2


def even_round(v: float) -> int:
    return int(round(v / 2.0)) * 2


def clamp_rect(x: float, y: float, w: float, h: float, W: int, H: int, warns: list[str] | None = None,
               label: str = "vùng") -> Rect:
    """Quy về pixel chẵn và kẹp trong khung."""
    xi, yi = even_floor(x), even_floor(y)
    wi, hi = max(2, even_round(w)), max(2, even_round(h))
    if xi < 0:
        wi += xi
        xi = 0
    if yi < 0:
        hi += yi
        yi = 0
    clipped = False
    if xi + wi > W:
        wi = W - xi
        clipped = True
    if yi + hi > H:
        hi = H - yi
        clipped = True
    wi, hi = max(2, even_floor(wi)), max(2, even_floor(hi))
    xi, yi = min(xi, W - wi), min(yi, H - hi)
    if clipped and warns is not None:
        warns.append(f"{label} tràn ra ngoài khung — đã cắt bớt")
    return Rect(xi, yi, wi, hi)


def region_rect(r: Region, W: int, H: int, warns: list[str] | None = None) -> Rect:
    """Region (tỷ lệ hoặc preset) → Rect pixel trong khung W×H."""
    if r.preset is None:
        if None in (r.x, r.y, r.w, r.h):
            raise ValueError("region tuỳ chỉnh cần đủ x, y, w, h")
        return clamp_rect(r.x * W, r.y * H, r.w * W, r.h * H, W, H, warns)
    p, s = r.preset, r.split
    if p == "full":
        return Rect(0, 0, W, H)
    if p == "bottom":
        y = even_round(H * s)
        return clamp_rect(0, y, W, H - y, W, H, warns)
    if p == "top":
        return clamp_rect(0, 0, W, H * s, W, H, warns)
    if p == "left":
        return clamp_rect(0, 0, W * s, H, W, H, warns)
    if p == "right":
        x = even_round(W * s)
        return clamp_rect(x, 0, W - x, H, W, H, warns)
    if p == "center_box":
        w, h = W * r.size, H * r.size
        return clamp_rect((W - w) / 2, (H - h) / 2, w, h, W, H, warns)
    if p == "pip_corner":
        w = W * r.size
        h = w * H / W
        m = r.margin * W
        x = m if "left" in r.corner else W - m - w
        y = m if "top" in r.corner else H - m - h
        return clamp_rect(x, y, w, h, W, H, warns)
    raise ValueError(f"region preset không hỗ trợ: {p}")


def protect_rect(p: Protect, W: int, H: int, warns: list[str] | None = None) -> Rect:
    return clamp_rect(p.x * W, p.y * H, p.w * W, p.h * H, W, H, warns, label=f"vùng bảo vệ {p.label or ''}".strip())


def anchor_xy(anchor: Union[str, XY]) -> tuple[float, float]:
    if isinstance(anchor, XY):
        return max(0.0, min(1.0, anchor.x)), max(0.0, min(1.0, anchor.y))
    return {"center": (0.5, 0.5), "top": (0.5, 0.0), "bottom": (0.5, 1.0),
            "left": (0.0, 0.5), "right": (1.0, 0.5)}[anchor]


@dataclass
class FitPlan:
    """Kế hoạch đặt clip sw×sh vào ô bw×bh."""
    scale_w: int
    scale_h: int
    crop_x: int
    crop_y: int
    crop_w: int
    crop_h: int
    pad_x: int
    pad_y: int
    needs_pad: bool
    cut_ratio: float  # tỷ lệ diện tích bị cắt (cover)


def fit_plan(sw: int, sh: int, bw: int, bh: int, fit: str = "cover", anchor: Union[str, XY] = "center",
             zoom: float = 1.0, offset: XY | None = None) -> FitPlan:
    ax, ay = anchor_xy(anchor)
    ox, oy = (offset.x, offset.y) if offset else (0.0, 0.0)
    if fit == "stretch":
        return FitPlan(bw, bh, 0, 0, bw, bh, 0, 0, False, 0.0)
    if fit == "cover":
        s = max(bw / sw, bh / sh) * zoom
    else:
        s = min(bw / sw, bh / sh) * zoom
    scw, sch = max(2, even_round(sw * s)), max(2, even_round(sh * s))
    if fit == "cover":
        scw, sch = max(scw, bw), max(sch, bh)
    cw, ch = min(scw, bw), min(sch, bh)
    cx = int(round((scw - cw) * ax - ox * bw))
    cy = int(round((sch - ch) * ay - oy * bh))
    cx = max(0, min(scw - cw, cx))
    cy = max(0, min(sch - ch, cy))
    needs_pad = cw < bw or ch < bh
    px = int(round((bw - cw) * ax + ox * bw)) if needs_pad else 0
    py = int(round((bh - ch) * ay + oy * bh)) if needs_pad else 0
    px = max(0, min(bw - cw, px))
    py = max(0, min(bh - ch, py))
    cut = 1.0 - (cw * ch) / float(scw * sch)
    return FitPlan(scw, sch, cx, cy, cw, ch, px, py, needs_pad, cut)
