"""Dựng lệnh ffmpeg (inputs + filter_complex) cho từng đoạn timeline."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from .geometry import Rect, fit_plan, protect_rect, region_rect
from .models import MediaInfo, Preset, Region, Segment, TaskSpec


class SegmentSkip(Exception):
    """Đoạn optional thiếu file → bỏ qua."""


class SegmentError(ValueError):
    pass


@dataclass
class OutSpec:
    W: int
    H: int
    fps: float
    sr: int = 44100
    micro_fade_ms: int = 15
    normalize_lufs: Optional[float] = None
    hdr_to_sdr: bool = True
    alpha_bg: str = "#000000"
    ken_burns: bool = False  # ảnh tĩnh trong pool: zoom nhẹ (M18)

    @property
    def fps_str(self) -> str:
        f = self.fps
        return str(int(f)) if abs(f - round(f)) < 1e-6 else f"{f:.6f}"


@dataclass
class SegGraph:
    inputs: list[list[str]] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    vout: str = ""
    aout: str = ""
    frames: int = 0
    duration: float = 0.0
    warnings: list[str] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)  # vai trò -> đường dẫn (manifest)
    _n: int = 0

    def add_input(self, path: Union[Path, str], pre: Optional[list[str]] = None) -> int:
        self.inputs.append([*(pre or []), "-i", str(path)])
        return len(self.inputs) - 1

    def lbl(self, p: str = "x") -> str:
        self._n += 1
        return f"{p}{self._n}"

    def add(self, s: str) -> None:
        self.filters.append(s)

    def filter_complex(self) -> str:
        return ";\n".join(self.filters)

    def input_args(self) -> list[str]:
        out: list[str] = []
        for i in self.inputs:
            out += i
        return out


def _num(v: float) -> str:
    return f"{v:.6f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def ffcolor(c: str) -> str:
    c = c.strip()
    return "0x" + c[1:] if c.startswith("#") else c


def resolve_time(v: Union[float, str, None], total: float, default: float) -> float:
    if v is None:
        return default
    if isinstance(v, str):
        s = v.strip()
        if s.endswith("%"):
            return total * float(s[:-1]) / 100.0
        v = float(s)
    v = float(v)
    return total + v if v < 0 else v


def trim_range(seg: Segment, total: float) -> tuple[float, float]:
    a = max(0.0, resolve_time(seg.trim.start, total, 0.0))
    b = min(total, resolve_time(seg.trim.end, total, total)) if total > 0 else resolve_time(seg.trim.end, total, total)
    if b <= a:
        raise SegmentError(f"trim không hợp lệ ({a:.2f}–{b:.2f}s, file dài {total:.2f}s)")
    return a, b


def frames_for(d: float, fps: float) -> int:
    return max(1, int(round(d * fps)))


# ---------------------------------------------------------------- chuỗi video
def _pre_chain(info: MediaInfo, out: OutSpec, speed: float = 1.0, rotate: int = 0, flip: str = "none",
               color: Optional[object] = None) -> list[str]:
    """Chuẩn hoá chung: reset timestamp, SAR, deinterlace, HDR, xoay/lật, màu, tốc độ, fps."""
    f = ["setpts=PTS-STARTPTS"]
    if info.sar not in ("1:1", "0:1", "N/A", ""):
        f.append("scale=trunc(iw*sar/2)*2:ih,setsar=1")
    if info.interlaced:
        f.append("yadif=mode=0")
    if info.hdr and out.hdr_to_sdr:
        f.append("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
                 "zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
    if rotate == 90:
        f.append("transpose=1")
    elif rotate == 270:
        f.append("transpose=2")
    elif rotate == 180:
        f.append("hflip,vflip")
    if flip == "horizontal":
        f.append("hflip")
    elif flip == "vertical":
        f.append("vflip")
    if color is not None:
        f.append(f"eq=brightness={_num(color.brightness)}:contrast={_num(color.contrast)}:saturation={_num(color.saturation)}")
    if abs(speed - 1.0) > 1e-6:
        f.append(f"setpts=PTS/{_num(speed)}")
    f.append(f"fps={out.fps_str}")
    return f


def _fit(g: SegGraph, src: str, sw: int, sh: int, bw: int, bh: int, reg: Region, out: OutSpec,
         allow_transparent: bool = False) -> tuple[str, bool]:
    """Đặt luồng src (sw×sh) vào ô bw×bh theo fit/anchor/zoom/offset. Trả (nhãn, có_alpha)."""
    plan = fit_plan(sw, sh, bw, bh, reg.fit, reg.anchor, reg.zoom, reg.offset)
    if reg.fit == "cover" and plan.cut_ratio > 0.5:
        g.warnings.append(f"Clip bị cắt {plan.cut_ratio * 100:.0f}% hình khi lấp đầy vùng")
    o = g.lbl("fit")
    base = f"scale={plan.scale_w}:{plan.scale_h}:flags=bicubic,setsar=1"
    if plan.crop_w != plan.scale_w or plan.crop_h != plan.scale_h:
        base += f",crop={plan.crop_w}:{plan.crop_h}:{plan.crop_x}:{plan.crop_y}"
    if not plan.needs_pad:
        g.add(f"[{src}]{base}[{o}]")
        return o, False
    bg = reg.background
    if bg == "blur":
        a, b, bgl, fg = g.lbl("s"), g.lbl("s"), g.lbl("bg"), g.lbl("fg")
        cover = fit_plan(sw, sh, bw, bh, "cover")
        g.add(f"[{src}]split=2[{a}][{b}]")
        g.add(f"[{a}]scale={cover.scale_w}:{cover.scale_h},crop={bw}:{bh}:{cover.crop_x}:{cover.crop_y},"
              f"boxblur=luma_radius=min(h\\,w)/20:luma_power=2,setsar=1[{bgl}]")
        g.add(f"[{b}]{base}[{fg}]")
        g.add(f"[{bgl}][{fg}]overlay={plan.pad_x}:{plan.pad_y}[{o}]")
        return o, False
    if bg == "base" and allow_transparent:
        g.add(f"[{src}]{base},format=yuva420p,pad={bw}:{bh}:{plan.pad_x}:{plan.pad_y}:color=black@0[{o}]")
        return o, True
    col = ffcolor(bg if bg.startswith("#") or bg.startswith("0x") else "#000000")
    g.add(f"[{src}]{base},pad={bw}:{bh}:{plan.pad_x}:{plan.pad_y}:color={col}[{o}]")
    return o, False


def _full_frame_video(g: SegGraph, idx: int, info: MediaInfo, out: OutSpec, reg: Region, frames: int,
                      speed: float = 1.0) -> str:
    """Input → khung W×H đúng N frame (thiếu thì giữ khung cuối)."""
    pre = g.lbl("pre")
    chain = _pre_chain(info, out, speed, reg.rotate, reg.flip, reg.color_match)
    g.add(f"[{idx}:v:0]{','.join(chain)}[{pre}]")
    sw, sh = (info.height, info.width) if reg.rotate in (90, 270) else (info.width, info.height)
    fitted, _ = _fit(g, pre, sw, sh, out.W, out.H, reg, out)
    src = fitted
    if info.has_alpha:
        cb, ov = g.lbl("cb"), g.lbl("ab")
        g.add(f"color=c={ffcolor(out.alpha_bg)}:s={out.W}x{out.H}:r={out.fps_str}[{cb}]")
        g.add(f"[{cb}][{fitted}]overlay=shortest=1[{ov}]")
        src = ov
    o = g.lbl("v")
    g.add(f"[{src}]format=yuv420p,tpad=stop_mode=clone:stop=-1,trim=end_frame={frames},setpts=PTS-STARTPTS[{o}]")
    return o


# ---------------------------------------------------------------- audio
def _audio(g: SegGraph, idx: Optional[int], info: Optional[MediaInfo], out: OutSpec, duration: float,
           speed: float = 1.0, volume: float = 1.0, fades: bool = True) -> str:
    """Audio đúng độ dài, stereo, sample rate chuẩn. Không có audio → câm."""
    samples = int(round(duration * out.sr))
    o = g.lbl("a")
    if idx is None or info is None or not info.has_audio:
        g.add(f"anullsrc=r={out.sr}:cl=stereo,atrim=end_sample={samples}[{o}]")
        return o
    f = ["asetpts=PTS-STARTPTS"]
    if abs(speed - 1.0) > 1e-6:
        f.append(f"atempo={_num(speed)}")
    if abs(volume - 1.0) > 1e-6:
        f.append(f"volume={_num(volume)}")
    if out.normalize_lufs is not None:
        f.append(f"loudnorm=I={_num(out.normalize_lufs)}:TP=-1.5:LRA=11")
    f.append(f"aresample={out.sr}")
    f.append(f"aformat=sample_fmts=s16:sample_rates={out.sr}:channel_layouts=stereo")
    f.append(f"apad,atrim=end_sample={samples},asetpts=PTS-STARTPTS")
    if fades and out.micro_fade_ms > 0 and duration > 0.1:
        d = out.micro_fade_ms / 1000.0
        f.append(f"afade=t=in:d={_num(d)},afade=t=out:st={_num(max(0.0, duration - d))}:d={_num(d)}")
    g.add(f"[{idx}:a:{info.audio_index or 0}]{','.join(f)}[{o}]")
    return o


def _finish_audio(g: SegGraph, a: str, out: OutSpec, duration: float) -> str:
    """Áp micro-fade cho audio đã trộn."""
    if out.micro_fade_ms <= 0 or duration <= 0.1:
        return a
    d = out.micro_fade_ms / 1000.0
    o = g.lbl("af")
    g.add(f"[{a}]afade=t=in:d={_num(d)},afade=t=out:st={_num(max(0.0, duration - d))}:d={_num(d)}[{o}]")
    return o


# ---------------------------------------------------------------- input helpers
def _file_input_args(info: MediaInfo, start: float, length: float, loop: bool = False,
                     fps: Optional[str] = None) -> list[str]:
    if info.is_image:
        return ["-loop", "1", "-framerate", fps or "30", "-t", _num(length + 0.5)]
    pre: list[str] = []
    if loop:
        pre += ["-stream_loop", "-1"]
    if start > 0:
        pre += ["-ss", _num(start)]
    if not loop:
        pre += ["-t", _num(length + 0.5)]  # chỉ đọc phần cần dùng (M13)
    return pre


def _get_asset(task: TaskSpec, slot: str, seg: Segment, probe_fn) -> Optional[MediaInfo]:
    path = task.assets.get(slot)
    if path is None:
        if seg.optional:
            raise SegmentSkip(slot)
        raise SegmentError(f"Thiếu file cho slot '{slot}' (nhóm {task.group_display})")
    return probe_fn(path)


# ---------------------------------------------------------------- đoạn asset / pool / blank
def build_asset(seg: Segment, task: TaskSpec, out: OutSpec, probe_fn, source_path: Optional[Path] = None) -> SegGraph:
    g = SegGraph()
    if source_path is not None:
        info = probe_fn(source_path)
        role = "pool"
    else:
        info = _get_asset(task, seg.slot, seg, probe_fn)
        role = seg.slot
    if info.is_image:
        a, b = 0.0, float(seg.duration or 3.0)
    else:
        a, b = trim_range(seg, info.video_duration)
    dur = (b - a) / seg.speed
    n = frames_for(dur, out.fps)
    dur = n / out.fps
    g.frames, g.duration = n, dur
    g.sources[role] = str(info.path)
    idx = g.add_input(info.path, _file_input_args(info, a, b - a, fps=out.fps_str))
    g.vout = _full_frame_video(g, idx, info, out, seg.region, n, seg.speed)
    mode = seg.audio.mode
    if seg.voice_slot and task.assets.get(seg.voice_slot):
        vinfo = probe_fn(task.assets[seg.voice_slot])
        vi = g.add_input(vinfo.path, ["-t", _num(dur + 0.5)])
        g.aout = _audio(g, vi, vinfo, out, dur)
        g.sources["voice"] = str(vinfo.path)
    elif mode == "mute":
        g.aout = _audio(g, None, None, out, dur)
    else:
        vol = seg.audio.overlay_volume if role == "pool" else seg.audio.base_volume
        g.aout = _audio(g, idx, info, out, dur, seg.speed, vol)
    return g


def build_pool(seg: Segment, task: TaskSpec, out: OutSpec, probe_fn) -> SegGraph:
    if task.clip is None:
        if seg.optional:
            raise SegmentSkip("pool")
        raise SegmentError("Đoạn pool nhưng task không có clip")
    return build_asset(seg, task, out, probe_fn, source_path=task.clip)


def build_blank(seg: Segment, out: OutSpec) -> SegGraph:
    g = SegGraph()
    n = frames_for(seg.duration or 1.0, out.fps)
    g.frames, g.duration = n, n / out.fps
    v = g.lbl("v")
    if seg.image:
        idx = g.add_input(seg.image, ["-loop", "1", "-framerate", out.fps_str, "-t", _num(g.duration + 0.5)])
        from .models import MediaInfo as _MI
        info = _MI(path=Path(seg.image), width=out.W, height=out.H, is_image=True)
        g.vout = _full_frame_video(g, idx, info, out, seg.region, n)
    else:
        g.add(f"color=c={ffcolor(seg.color)}:s={out.W}x{out.H}:r={out.fps_str},format=yuv420p,trim=end_frame={n}[{v}]")
        g.vout = v
    g.aout = _audio(g, None, None, out, g.duration)
    return g


# ---------------------------------------------------------------- composite
def _clip_start(seg: Segment, clip_dur: float, seg_dur: float, seed: int) -> float:
    cs = seg.clip_start
    room = max(0.0, clip_dur - seg_dur)
    if cs == "center":
        return room / 2
    if cs == "random":
        return random.Random(seed).uniform(0, room)
    return max(0.0, min(float(cs), max(0.0, clip_dur - 0.1)))


def _mask(g: SegGraph, w: int, h: int, radius: int, feather: int, opacity: float, frames: int,
          out: OutSpec) -> str:
    """Mask alpha bo góc + làm mềm mép, sinh 1 frame rồi lặp lại."""
    a = int(round(255 * opacity))
    F, R = feather, min(radius, w // 2, h // 2)
    cx, cy = "abs(X-(W-1)/2)", "abs(Y-(H-1)/2)"
    hx, hy = f"(W/2-{F})", f"(H/2-{F})"
    dx, dy = f"({cx}-({hx}-{R}))", f"({cy}-({hy}-{R}))"
    if R > 0:
        expr = (f"if(gt({dx},0)*gt({dy},0),if(lte(hypot({dx},{dy}),{R}),{a},0),"
                f"if(lte({cx},{hx})*lte({cy},{hy}),{a},0))")
    else:
        expr = f"if(lte({cx},{hx})*lte({cy},{hy}),{a},0)"
    o = g.lbl("mk")
    blur = f",gblur=sigma={max(0.5, F / 2):.2f}" if F > 0 else ""
    g.add(f"color=c=black:s={w}x{h}:r={out.fps_str}:d={_num(1 / out.fps)},format=gray,geq=lum='{expr}'{blur},"
          f"loop=loop=-1:size=1,setpts=N/({out.fps_str}*TB),trim=end_frame={frames}[{o}]")
    return o


def build_composite(seg: Segment, task: TaskSpec, out: OutSpec, probe_fn, overlay_enabled: bool = True) -> SegGraph:
    g = SegGraph()
    binfo = _get_asset(task, seg.base, seg, probe_fn)
    a, b = trim_range(seg, binfo.video_duration)
    base_dur = (b - a) / seg.speed

    # clip overlay
    if seg.overlay == "pool":
        if task.clip is None:
            raise SegmentError("Đoạn composite cần clip pool nhưng task không có")
        cpath = task.clip
    else:
        cpath = task.assets.get(seg.overlay)
        if cpath is None:
            raise SegmentError(f"Thiếu file overlay '{seg.overlay}'")
    cinfo = probe_fn(cpath)
    clip_total = float("inf") if cinfo.is_image else cinfo.video_duration

    mode = seg.duration_mode
    if mode == "match_clip" and not cinfo.is_image:
        cs0 = _clip_start(seg, clip_total, 0, task.seed)
        dur = (clip_total - cs0)
    else:
        dur = base_dur
    n = frames_for(dur, out.fps)
    dur = n / out.fps
    g.frames, g.duration = n, dur
    cs = 0.0 if cinfo.is_image else _clip_start(seg, clip_total, dur, task.seed)
    avail = clip_total - cs

    # chế độ thời lượng clip
    clip_speed = 1.0
    loop = False
    freeze = False
    boomerang = False
    if not cinfo.is_image and avail < dur - 1e-3:
        if mode == "match_base":
            loop = True
        elif mode == "match_base_freeze":
            freeze = True
        elif mode == "match_base_boomerang":
            if avail > 15:
                g.warnings.append("Boomerang chỉ áp cho clip ≤ 15s — dùng loop")
                loop = True
            else:
                boomerang = True
        elif mode == "match_base_speed":
            f = avail / dur
            if f >= seg.min_speed:
                clip_speed = f
            else:
                loop = True
    elif not cinfo.is_image and mode == "match_base_speed" and avail > dur + 1e-3:
        f = avail / dur
        clip_speed = min(f, seg.max_speed)
    if cinfo.video_duration < 0.5 and not cinfo.is_image:
        g.warnings.append(f"Clip rất ngắn ({cinfo.video_duration:.2f}s) — sẽ lặp")

    bi = g.add_input(binfo.path, _file_input_args(binfo, a, b - a, fps=out.fps_str))
    g.sources[seg.base] = str(binfo.path)
    g.sources["overlay"] = str(cinfo.path)
    read_len = min(avail, dur * clip_speed + 1.0)
    ci = g.add_input(cinfo.path, _file_input_args(cinfo, cs, read_len, loop=loop or boomerang, fps=out.fps_str)) \
        if not boomerang else g.add_input(cinfo.path, _file_input_args(cinfo, cs, avail, fps=out.fps_str))

    base_v = _full_frame_video(g, bi, binfo, out, Region(preset="full"), n, seg.speed)
    rect = region_rect(seg.region, out.W, out.H, g.warnings)

    cur = base_v
    n_protect = sum(1 for p in seg.protect if p.from_ == "base")
    bsplits: list[str] = []
    if n_protect:
        labels = [g.lbl("b") for _ in range(n_protect + 1)]
        g.add(f"[{base_v}]split={n_protect + 1}" + "".join(f"[{x}]" for x in labels))
        cur, bsplits = labels[0], labels[1:]

    if overlay_enabled:
        reg = seg.region
        bw_, bh_ = rect.w, rect.h
        border = reg.border.width
        inner_w, inner_h = max(2, bw_ - 2 * border) // 2 * 2, max(2, bh_ - 2 * border) // 2 * 2
        pre = g.lbl("cpre")
        chain = _pre_chain(cinfo, out, clip_speed, reg.rotate, reg.flip, reg.color_match)
        if cinfo.is_image and out.ken_burns:
            kw, kh = cinfo.width // 2 * 2, cinfo.height // 2 * 2
            chain.append(f"scale={kw * 2}:{kh * 2},zoompan=z='min(zoom+0.0012,1.2)':x='iw/2-(iw/zoom/2)':"
                         f"y='ih/2-(ih/zoom/2)':d=1:s={kw}x{kh}:fps={out.fps_str}")
        g.add(f"[{ci}:v:0]{','.join(chain)}[{pre}]")
        sw, sh = (cinfo.height, cinfo.width) if reg.rotate in (90, 270) else (cinfo.width, cinfo.height)
        fitted, transparent = _fit(g, pre, sw, sh, inner_w, inner_h, reg, out, allow_transparent=True)
        src = fitted
        if border > 0:
            bo = g.lbl("bd")
            g.add(f"[{src}]pad={bw_}:{bh_}:{(bw_ - inner_w) // 2}:{(bh_ - inner_h) // 2}:color={ffcolor(reg.border.color)}[{bo}]")
            src = bo
        if boomerang:
            f1, f2, rv, bm = g.lbl("f"), g.lbl("r"), g.lbl("rv"), g.lbl("bm")
            nb = frames_for(avail, out.fps)
            g.add(f"[{src}]trim=end_frame={nb},setpts=PTS-STARTPTS,split=2[{f1}][{f2}]")
            g.add(f"[{f2}]reverse[{rv}]")
            g.add(f"[{f1}][{rv}]concat=n=2:v=1:a=0,loop=loop=-1:size={2 * nb},setpts=N/({out.fps_str}*TB)[{bm}]")
            src = bm
        # luôn giữ khung cuối nếu clip hụt (freeze); loop/cắt đã đủ frame nên tpad không ảnh hưởng
        ov = g.lbl("ov")
        g.add(f"[{src}]tpad=stop_mode=clone:stop=-1,trim=end_frame={n},setpts=PTS-STARTPTS[{ov}]")
        src = ov
        need_mask = reg.border.radius > 0 or reg.feather > 0 or reg.opacity < 1
        if need_mask:
            mk = _mask(g, bw_, bh_, reg.border.radius, reg.feather, reg.opacity, n, out)
            am = g.lbl("am")
            g.add(f"[{src}]format=yuva420p[{am}x];[{am}x][{mk}]alphamerge[{am}]")
            src = am
        en = ""
        if seg.active_time is not None:
            ta = seg.active_time.start
            tb = seg.active_time.end if seg.active_time.end is not None else dur
            en = f":enable='between(t,{_num(ta)},{_num(tb)})'"
        o = g.lbl("c")
        g.add(f"[{cur}][{src}]overlay={rect.x}:{rect.y}:format=auto:eof_action=pass{en}[{o}]")
        cur = o

    # vùng bảo vệ
    bi_iter = iter(bsplits)
    for p in seg.protect:
        pr = protect_rect(p, out.W, out.H, g.warnings)
        if p.from_ == "base":
            src_l = next(bi_iter)
            cr = g.lbl("pc")
            g.add(f"[{src_l}]crop={pr.w}:{pr.h}:{pr.x}:{pr.y}[{cr}]")
        elif p.from_ in task.assets:
            pinfo = probe_fn(task.assets[p.from_])
            pi = g.add_input(pinfo.path, _file_input_args(pinfo, 0, dur, fps=out.fps_str))
            full = _full_frame_video(g, pi, pinfo, out, Region(preset="full"), n)
            cr = g.lbl("pc")
            g.add(f"[{full}]crop={pr.w}:{pr.h}:{pr.x}:{pr.y}[{cr}]")
        else:
            ppath = Path(p.from_)
            if not ppath.exists():
                raise SegmentError(f"Vùng bảo vệ: không tìm thấy nguồn '{p.from_}'")
            pi = g.add_input(ppath, ["-loop", "1", "-framerate", out.fps_str, "-t", _num(dur + 0.5)])
            cr = g.lbl("pc")
            g.add(f"[{pi}:v:0]scale={pr.w}:{pr.h},format=yuva420p,setpts=PTS-STARTPTS,trim=end_frame={n}[{cr}]")
        o = g.lbl("p")
        g.add(f"[{cur}][{cr}]overlay={pr.x}:{pr.y}:format=auto:eof_action=pass[{o}]")
        cur = o

    vo = g.lbl("vout")
    g.add(f"[{cur}]format=yuv420p,trim=end_frame={n},setpts=PTS-STARTPTS[{vo}]")
    g.vout = vo

    # audio
    am_ = seg.audio
    if seg.voice_slot and task.assets.get(seg.voice_slot):
        vinfo = probe_fn(task.assets[seg.voice_slot])
        vi = g.add_input(vinfo.path, ["-t", _num(dur + 0.5)])
        g.aout = _audio(g, vi, vinfo, out, dur)
    elif am_.mode == "base":
        g.aout = _audio(g, bi, binfo, out, dur, seg.speed, am_.base_volume)
    elif am_.mode == "overlay":
        g.aout = _audio(g, ci, cinfo, out, dur, clip_speed if not boomerang else 1.0, am_.overlay_volume)
    elif am_.mode == "mute":
        g.aout = _audio(g, None, None, out, dur)
    else:  # mix
        x = _audio(g, bi, binfo, out, dur, seg.speed, am_.base_volume, fades=False)
        y = _audio(g, ci, cinfo, out, dur, clip_speed, am_.overlay_volume, fades=False)
        m = g.lbl("mix")
        samples = int(round(dur * out.sr))
        g.add(f"[{x}][{y}]amix=inputs=2:duration=longest:normalize=0,atrim=end_sample={samples}[{m}]")
        g.aout = _finish_audio(g, m, out, dur)
    return g


def build_segment(seg: Segment, task: TaskSpec, out: OutSpec, probe_fn, overlay_enabled: bool = True) -> SegGraph:
    if seg.kind == "asset":
        return build_asset(seg, task, out, probe_fn)
    if seg.kind == "pool":
        return build_pool(seg, task, out, probe_fn)
    if seg.kind == "blank":
        return build_blank(seg, out)
    return build_composite(seg, task, out, probe_fn, overlay_enabled)


def depends_on_pool(seg: Segment) -> bool:
    return seg.kind == "pool" or (seg.kind == "composite" and seg.overlay == "pool")
