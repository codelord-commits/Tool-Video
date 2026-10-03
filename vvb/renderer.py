"""Render đoạn, cache asset chuẩn hoá, nối, kiểm tra output, preview."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import defaults as D
from .events import NULL_BUS, EventBus
from .ffmpeg import (FFResult, ProcessRegistry, GLOBAL_REGISTRY, encoder_works, find_ffmpeg, popen_kwargs,
                     run_ffmpeg, kill_tree)
from .filters import (OutSpec, SegGraph, SegmentSkip, SegmentError, build_segment, depends_on_pool, ffcolor,
                      _num)
from .models import Preset, Segment, TaskSpec, Transition
from .probe import probe

ProgressFn = Callable[[float], None]


class RenderError(RuntimeError):
    def __init__(self, msg: str, result: Optional[FFResult] = None):
        self.result = result
        super().__init__(msg)

    @property
    def cmd(self) -> list[str]:
        return self.result.cmd if self.result else []

    @property
    def stderr_tail(self) -> str:
        return self.result.error_text() if self.result else ""


class Cancelled(RuntimeError):
    pass


# ---------------------------------------------------------------- encoder
CPU_EQUIV = {"h264": "libx264", "h265": "libx265", "h264_nvenc": "libx264", "hevc_nvenc": "libx265",
             "h264_videotoolbox": "libx264", "h264_qsv": "libx264", "h264_amf": "libx264"}


def resolve_encoder(codec: str, force_cpu: bool = False) -> tuple[str, list[str]]:
    """Codec trong preset → tên encoder ffmpeg (tự quay về CPU nếu phần cứng không chạy)."""
    warns: list[str] = []
    if codec in ("h264", "h265") or force_cpu:
        return CPU_EQUIV[codec], warns
    if encoder_works(codec):
        return codec, warns
    warns.append(f"Encoder {codec} không dùng được trên máy này — chuyển sang {CPU_EQUIV[codec]}")
    return CPU_EQUIV[codec], warns


def video_encode_args(preset: Preset, encoder: str, fps: float, fast_preview: bool = False) -> list[str]:
    o = preset.output
    crf = D.QUALITY_CRF.get(o.quality, 20)
    speed = "ultrafast" if fast_preview else o.preset_speed
    if fast_preview:
        crf = 28
    gop = str(max(1, int(round(fps * 2))))
    if encoder in ("libx264", "libx265"):
        a = ["-c:v", encoder, "-preset", speed]
        if o.quality == "bitrate" and not fast_preview:
            br = o.bitrate_mbps
            a += ["-b:v", f"{br}M", "-maxrate", f"{br * 1.5}M", "-bufsize", f"{br * 2}M"]
        else:
            a += ["-crf", str(crf)]
        if encoder == "libx265":
            a += ["-tag:v", "hvc1", "-x265-params", "log-level=error"]
        else:
            a += ["-profile:v", "high"]
    elif encoder.endswith("_nvenc"):
        a = ["-c:v", encoder, "-preset", "p4", "-rc", "vbr", "-cq", str(crf + 2), "-b:v", "0"]
        if encoder.startswith("hevc"):
            a += ["-tag:v", "hvc1"]
    elif encoder.endswith("_qsv"):
        a = ["-c:v", encoder, "-global_quality", str(crf + 2), "-look_ahead", "0"]
    elif encoder.endswith("_amf"):
        a = ["-c:v", encoder, "-rc", "cqp", "-qp_i", str(crf), "-qp_p", str(crf + 2)]
    elif encoder.endswith("_videotoolbox"):
        a = ["-c:v", encoder, "-q:v", str(max(30, 100 - crf * 2))]
    else:
        a = ["-c:v", encoder]
    if o.quality == "bitrate" and not encoder.startswith("lib") and not fast_preview:
        a += ["-b:v", f"{o.bitrate_mbps}M"]
    return a + ["-g", gop, "-pix_fmt", "yuv420p"]


def resolve_out_spec(preset: Preset, sample: Optional[Path] = None, preview: bool = False) -> OutSpec:
    size = preset.out_size()
    fps = preset.output.fps
    info = probe(sample) if sample and (size is None or fps == "same_as_base") else None
    if size is None:
        if info is None:
            size = (1080, 1920)
        else:
            size = (info.width // 2 * 2, info.height // 2 * 2)
    if fps == "same_as_base":
        fps = 30.0 if info is None or info.vfr or not info.avg_fps else round(info.avg_fps, 3)
    W, H = size
    if preview:  # 540p, giữ tỷ lệ
        s = D.PREVIEW_HEIGHT / max(1, min(W, H)) if min(W, H) > D.PREVIEW_HEIGHT else 1.0
        W, H = int(W * s) // 2 * 2, int(H * s) // 2 * 2
    return OutSpec(W=W, H=H, fps=float(fps), sr=preset.audio.sample_rate,
                   micro_fade_ms=preset.audio.micro_fade_ms, normalize_lufs=preset.audio.normalize_lufs,
                   hdr_to_sdr=preset.output.hdr_to_sdr, alpha_bg=preset.output.alpha_background,
                   ken_burns=any(s.type == "pool" and s.ken_burns for s in preset.slots.values()))


def prune_cache(folder: Path, limit_gb: float = D.CACHE_LIMIT_GB) -> int:
    """Giữ cache dưới giới hạn: xoá file ít dùng nhất (LRU theo mtime). Trả số file đã xoá."""
    if not folder.exists():
        return 0
    files = sorted((f for f in folder.glob("*.mov") if ".tmp" not in f.name), key=lambda f: f.stat().st_mtime)
    total = sum(f.stat().st_size for f in files)
    limit = limit_gb * 1024 ** 3
    removed = 0
    for f in files:
        if total <= limit:
            break
        try:
            sz = f.stat().st_size
            f.unlink()
            total -= sz
            removed += 1
        except OSError:
            pass
    return removed


# ---------------------------------------------------------------- kết quả
@dataclass
class Part:
    path: Path
    duration: float
    transition: Transition
    cached: bool = False


@dataclass
class TaskResult:
    out_path: Path
    duration: float
    size_bytes: int
    elapsed: float
    sources: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    encoder: str = ""


def concat_escape(p: Path) -> str:
    """Dòng 'file' cho concat demuxer (F3: escape dấu nháy đơn)."""
    return "file '" + str(p).replace("\\", "/").replace("'", "'\\''") + "'"


def filter_path_escape(p: Path) -> str:
    """Đường dẫn trong tham số filter (fontfile=…): escape ':' và '\\'."""
    s = str(p).replace("\\", "/")
    return s.replace(":", "\\:").replace("'", "\\'")


# ---------------------------------------------------------------- renderer
class Renderer:
    def __init__(self, preset: Preset, out: OutSpec, temp_root: Path, *, cache_dir: Optional[Path] = None,
                 bus: EventBus = NULL_BUS, registry: ProcessRegistry = GLOBAL_REGISTRY,
                 force_cpu: bool = False, fast_preview: bool = False):
        self.preset = preset
        self.out = out
        self.temp_root = Path(temp_root)
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.cache_dir = cache_dir
        self.bus = bus
        self.registry = registry
        self.fast_preview = fast_preview
        self.encoder, warns = resolve_encoder(preset.output.video_codec, force_cpu)
        for w in warns:
            bus.log("warn", w)
        self.venc = video_encode_args(preset, self.encoder, out.fps, fast_preview)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._black_cache: dict[str, float] = {}

    # ------------------------------------------------------------ đoạn
    def _seg_cmd(self, g: SegGraph, out_file: Path) -> list[str]:
        ts = str(int(round(self.out.fps * 1000)))
        return [*g.input_args(), "-filter_complex", g.filter_complex(), "-map", f"[{g.vout}]", "-map", f"[{g.aout}]",
                *self.venc, "-c:a", "pcm_s16le", "-ar", str(self.out.sr), "-ac", "2",
                "-frames:v", str(g.frames), "-video_track_timescale", ts, "-f", "mov", str(out_file)]

    def render_graph(self, g: SegGraph, out_file: Path, cancel: Optional[threading.Event] = None,
                     on_progress: Optional[ProgressFn] = None) -> FFResult:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        args = self._seg_cmd(g, out_file)
        self.bus.log("debug", "ffmpeg " + " ".join(args[:6]) + " …", cmd=args)
        r = run_ffmpeg(args, duration=g.duration, on_progress=on_progress, cancel=cancel,
                       stall_timeout=self.preset.run.stall_timeout, registry=self.registry)
        if r.cancelled:
            raise Cancelled()
        if not r.ok:
            try:
                out_file.unlink(missing_ok=True)
            except OSError:
                pass
            raise RenderError("Render đoạn thất bại" + (" (ffmpeg treo)" if r.stalled else ""), r)
        return r

    def _key_lock(self, key: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    def _asset_key(self, seg: Segment, task: TaskSpec) -> str:
        files = []
        for slot in filter(None, [seg.slot, seg.base, seg.voice_slot]):
            p = task.assets.get(slot)
            if p is not None:
                st = p.stat()
                files.append([str(p.resolve()), st.st_size, st.st_mtime_ns])
        payload = {"files": files, "seg": seg.model_dump(mode="json", exclude={"transition_in"}),
                   "out": self.out.__dict__, "venc": self.venc, "v": 2}
        return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:24]

    def asset_part(self, seg: Segment, task: TaskSpec, cancel: Optional[threading.Event] = None,
                   on_progress: Optional[ProgressFn] = None) -> tuple[Path, float, bool]:
        """Đoạn không phụ thuộc pool → render 1 lần, cache theo hash."""
        g = build_segment(seg, task, self.out, probe)
        key = self._asset_key(seg, task)
        folder = self.cache_dir if self.cache_dir else self.temp_root / "assets"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{key}.mov"
        with self._key_lock(key):
            if target.exists() and target.stat().st_size > 0:
                try:
                    os.utime(target)  # LRU
                except OSError:
                    pass
                return target, g.duration, True
            tmp = folder / f"{key}.tmp{threading.get_ident()}.mov"
            self.render_graph(g, tmp, cancel, on_progress)
            os.replace(tmp, target)
        return target, g.duration, False

    def _black_start(self, clip: Path) -> float:
        k = str(clip)
        if k in self._black_cache:
            return self._black_cache[k]
        info = find_ffmpeg()
        r = subprocess.run([info.ffmpeg, "-hide_banner", "-nostdin", "-t", "5", "-i", str(clip), "-vf",
                            "blackdetect=d=0.05:pic_th=0.98", "-an", "-f", "null", "-"],
                           capture_output=True, timeout=60, **popen_kwargs())
        m = re.search(rb"black_start:0(?:\.0+)?\s+black_end:([\d.]+)", r.stderr)
        v = float(m.group(1)) if m else 0.0
        self._black_cache[k] = v
        return v

    def _prepare_seg(self, seg: Segment, task: TaskSpec) -> Segment:
        if self.preset.output.skip_black_start and task.clip and depends_on_pool(seg) \
                and seg.clip_start in (0, 0.0):
            bs = self._black_start(task.clip)
            if bs > 0:
                if seg.kind == "pool":
                    return seg.model_copy(update={"trim": seg.trim.model_copy(update={"start": bs})})
                return seg.model_copy(update={"clip_start": bs})
        return seg

    # ------------------------------------------------------------ task
    def render_parts(self, task: TaskSpec, work: Path, cancel: Optional[threading.Event] = None,
                     on_progress: Optional[ProgressFn] = None, until: Optional[float] = None,
                     warnings: Optional[list[str]] = None, sources: Optional[dict[str, str]] = None) -> list[Part]:
        parts: list[Part] = []
        segs = self.preset.timeline
        n = len(segs)
        acc = 0.0
        for i, seg in enumerate(segs):
            if cancel is not None and cancel.is_set():
                raise Cancelled()

            def prog(f: float, i=i) -> None:
                if on_progress:
                    on_progress((i + f) / n * 0.9)

            seg = self._prepare_seg(seg, task)
            try:
                if not depends_on_pool(seg) and seg.kind != "blank" and not self.fast_preview:
                    path, dur, cached = self.asset_part(seg, task, cancel, prog)
                    parts.append(Part(path, dur, seg.transition_in, cached))
                    if sources is not None:
                        g = build_segment(seg, task, self.out, probe)
                        sources.update({f"{i}:{k}": v for k, v in g.sources.items()})
                else:
                    g = build_segment(seg, task, self.out, probe)
                    if warnings is not None:
                        warnings.extend(g.warnings)
                    if sources is not None:
                        sources.update({f"{i}:{k}": v for k, v in g.sources.items()})
                    f = work / f"seg{i:02d}.mov"
                    self.render_graph(g, f, cancel, prog)
                    parts.append(Part(f, g.duration, seg.transition_in))
            except SegmentSkip:
                continue
            acc += parts[-1].duration
            if until is not None and acc >= until:
                break
        if not parts:
            raise RenderError("Không có đoạn nào để render (mọi đoạn đều bị bỏ qua)")
        return parts

    def render_task(self, task: TaskSpec, out_path: Path, cancel: Optional[threading.Event] = None,
                    on_progress: Optional[ProgressFn] = None) -> TaskResult:
        import time
        t0 = time.time()
        work = self.temp_root / f"task_{task.index:05d}_{threading.get_ident()}"
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        warns: list[str] = []
        sources: dict[str, str] = {}
        part_path = out_path.with_name(out_path.stem + ".part" + out_path.suffix)
        try:
            parts = self.render_parts(task, work, cancel, on_progress, warnings=warns, sources=sources)
            expected = self.concat(parts, part_path, task, work, cancel)
            if on_progress:
                on_progress(0.97)
            errs = self.verify(part_path, expected)
            if errs:
                raise RenderError("Kiểm tra output thất bại: " + "; ".join(errs))
            mfs = self.preset.output.max_file_size_mb
            if mfs and part_path.stat().st_size > mfs * 1024 * 1024:
                self._shrink(part_path, expected, mfs, work, cancel)
                warns.append(f"Vượt {mfs} MB — đã encode lại với bitrate thấp hơn")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(part_path, out_path)
            if on_progress:
                on_progress(1.0)
            return TaskResult(out_path, expected, out_path.stat().st_size, time.time() - t0, sources, warns,
                              self.encoder)
        except BaseException:
            try:
                part_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        finally:
            if not self.preset.run.keep_temp:
                shutil.rmtree(work, ignore_errors=True)

    # ------------------------------------------------------------ nối
    def _needs_filter_concat(self, parts: list[Part]) -> bool:
        o = self.preset.output
        if any(p.transition.type != "cut" and p.transition.duration > 0 for p in parts[1:]):
            return True
        return bool(o.watermark or o.text or o.subtitles_slot)

    def concat(self, parts: list[Part], out_file: Path, task: TaskSpec, work: Path,
               cancel: Optional[threading.Event] = None) -> float:
        """Nối các đoạn. Trả độ dài mong đợi."""
        out_file.parent.mkdir(parents=True, exist_ok=True)
        a = self.preset.audio
        fmt = "mov" if self.preset.output.container == "mov" else "mp4"
        if not self._needs_filter_concat(parts):
            total = sum(p.duration for p in parts)
            lst = work / "concat.txt"
            lst.write_text("ffconcat version 1.0\n" + "\n".join(concat_escape(p.path) for p in parts) + "\n",
                           encoding="utf-8")
            args = ["-f", "concat", "-safe", "0", "-i", str(lst)]
            afilt, extra_inputs = self._final_audio_chain("0:a", total, 1)
            args += extra_inputs
            if afilt:
                args += ["-filter_complex", afilt, "-map", "0:v", "-map", "[aout]"]
            else:
                args += ["-map", "0:v", "-map", "0:a"]
            args += ["-c:v", "copy", "-c:a", "aac", "-b:a", f"{a.bitrate_k}k", "-ar", str(a.sample_rate),
                     "-ac", "2", "-movflags", "+faststart", "-t", _num(total), "-f", fmt, str(out_file)]
            r = run_ffmpeg(args, duration=total, cancel=cancel, stall_timeout=self.preset.run.stall_timeout,
                           registry=self.registry)
        else:
            total, args = self._filter_concat_args(parts, task, work, out_file, fmt)
            r = run_ffmpeg(args, duration=total, cancel=cancel, stall_timeout=self.preset.run.stall_timeout,
                           registry=self.registry)
        if r.cancelled:
            raise Cancelled()
        if not r.ok:
            raise RenderError("Nối video thất bại", r)
        return total

    def _final_audio_chain(self, src: str, total: float, next_input: int) -> tuple[str, list[str]]:
        """Fade in/out, nhạc nền + ducking, chuẩn hoá cả video. Trả (filter, input args thêm)."""
        a = self.preset.audio
        f: list[str] = []
        inputs: list[str] = []
        cur = src
        if a.music and Path(a.music.path).exists():
            inputs += ["-stream_loop", "-1", "-i", a.music.path]
            mi = next_input
            f.append(f"[{mi}:a]aresample={a.sample_rate},aformat=channel_layouts=stereo,"
                     f"volume={_num(a.music.volume)},atrim=0:{_num(total)}[mus]")
            if a.music.ducking:
                f.append(f"[{cur}]asplit=2[v1][v2]")
                f.append("[mus][v2]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[musd]")
                f.append("[v1][musd]amix=inputs=2:duration=first:normalize=0[mx]")
            else:
                f.append(f"[{cur}][mus]amix=inputs=2:duration=first:normalize=0[mx]")
            cur = "mx"
        chain: list[str] = []
        if a.normalize_final and a.normalize_lufs is not None:
            chain.append(f"loudnorm=I={_num(a.normalize_lufs)}:TP=-1.5:LRA=11,aresample={a.sample_rate}")
        if a.fade_in > 0:
            chain.append(f"afade=t=in:d={_num(a.fade_in)}")
        if a.fade_out > 0:
            chain.append(f"afade=t=out:st={_num(max(0.0, total - a.fade_out))}:d={_num(a.fade_out)}")
        if not f and not chain:
            return "", []
        f.append(f"[{cur}]{','.join(chain) if chain else 'anull'}[aout]")
        return ";".join(f), inputs

    def _filter_concat_args(self, parts: list[Part], task: TaskSpec, work: Path, out_file: Path,
                            fmt: str) -> tuple[float, list[str]]:
        o = self.preset.output
        args: list[str] = []
        for p in parts:
            args += ["-i", str(p.path)]
        f: list[str] = []
        # cùng timebase cho mọi luồng (concat ra 1/1000000, xfade đòi 2 đầu vào giống nhau)
        for i in range(len(parts)):
            f.append(f"[{i}:v]settb=AVTB,setpts=PTS-STARTPTS[iv{i}]")
            f.append(f"[{i}:a]asetpts=PTS-STARTPTS[ia{i}]")
        cur_v, cur_a = "iv0", "ia0"
        total = parts[0].duration
        for i, p in enumerate(parts[1:], 1):
            t = p.transition
            nv, na = f"v{i}", f"a{i}"
            d = min(t.duration, total - 0.05, p.duration - 0.05) if t.type != "cut" else 0
            if t.type == "cut" or d <= 0:
                f.append(f"[{cur_v}][{cur_a}][iv{i}][ia{i}]concat=n=2:v=1:a=1[{nv}x][{na}]")
                f.append(f"[{nv}x]settb=AVTB[{nv}]")
                total += p.duration
            else:
                tr = {"fade": "fade", "crossfade": "dissolve", "fade_black": "fadeblack"}[t.type]
                off = total - d
                f.append(f"[{cur_v}][iv{i}]xfade=transition={tr}:duration={_num(d)}:offset={_num(off)}[{nv}]")
                f.append(f"[{cur_a}][ia{i}]acrossfade=d={_num(d)}[{na}]")
                total += p.duration - d
            cur_v, cur_a = nv, na
        n_in = len(parts)
        if o.watermark and Path(o.watermark.path).exists():
            wm = o.watermark
            args += ["-loop", "1", "-i", wm.path]
            ww = int(self.out.W * wm.w) // 2 * 2
            end = wm.end if wm.end is not None else total
            f.append(f"[{n_in}:v]scale={ww}:-2,format=rgba,colorchannelmixer=aa={_num(wm.opacity)}[wm]")
            f.append(f"[{cur_v}][wm]overlay={int(wm.x * self.out.W)}:{int(wm.y * self.out.H)}:shortest=1:"
                     f"enable='between(t,{_num(wm.start)},{_num(end)})'[vwm]")
            cur_v = "vwm"
            n_in += 1
        if o.text:
            txt = self._group_text(o.text.csv, task)
            if txt:
                tf = work / "text.txt"
                tf.write_text(txt, encoding="utf-8")
                font = o.text.font or _default_font()
                fopt = f"fontfile='{filter_path_escape(Path(font))}':" if font else ""
                f.append(f"[{cur_v}]drawtext={fopt}textfile='{filter_path_escape(tf)}':fontsize={o.text.size}:"
                         f"fontcolor={ffcolor(o.text.color)}:borderw={o.text.border_width}:"
                         f"bordercolor={ffcolor(o.text.border_color)}:x=(w-text_w)*{_num(o.text.x)}:"
                         f"y=(h-text_h)*{_num(o.text.y)}[vtx]")
                cur_v = "vtx"
        if o.subtitles_slot and task.assets.get(o.subtitles_slot):
            srt = work / "sub.srt"
            shutil.copyfile(task.assets[o.subtitles_slot], srt)
            f.append(f"[{cur_v}]subtitles='{filter_path_escape(srt)}'[vsb]")
            cur_v = "vsb"
        f.append(f"[{cur_v}]format=yuv420p[vout]")
        afilt, extra = self._final_audio_chain(cur_a, total, n_in)
        args += extra
        if afilt:
            f.append(afilt)
        else:
            f.append(f"[{cur_a}]anull[aout]")
        a = self.preset.audio
        args += ["-filter_complex", ";".join(f), "-map", "[vout]", "-map", "[aout]", *self.venc,
                 "-r", self.out.fps_str, "-c:a", "aac", "-b:a", f"{a.bitrate_k}k", "-ar", str(a.sample_rate),
                 "-ac", "2", "-movflags", "+faststart", "-t", _num(total), "-f", fmt, str(out_file)]
        return total, args

    @staticmethod
    def _group_text(csv_path: str, task: TaskSpec) -> str:
        p = Path(csv_path)
        if not p.exists():
            return ""
        with p.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
        if not rows:
            return ""
        head = [h.strip().lower() for h in rows[0]]
        keys = {task.group.lower(), task.group_display.lower(), task.group_raw.lower()}
        if "group" in head and "text" in head:
            gi, ti = head.index("group"), head.index("text")
            for r in rows[1:]:
                if len(r) > max(gi, ti) and r[gi].strip().lower() in keys:
                    return r[ti]
            return ""
        for i, h in enumerate(head):
            if h in keys and len(rows) > 1 and len(rows[1]) > i:
                return rows[1][i]
        return ""

    def _shrink(self, path: Path, dur: float, limit_mb: float, work: Path, cancel) -> None:
        a = self.preset.audio
        kbps = max(300, int(limit_mb * 8 * 1024 * 0.93 / max(dur, 0.1)) - a.bitrate_k)
        tmp = work / ("shrink" + path.suffix)
        enc = "libx264" if self.encoder in ("libx264",) or not self.encoder.startswith("lib") else self.encoder
        args = ["-i", str(path), "-c:v", enc, "-preset", self.preset.output.preset_speed, "-b:v", f"{kbps}k",
                "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k", "-pix_fmt", "yuv420p", "-c:a", "copy",
                "-movflags", "+faststart", str(tmp)]
        r = run_ffmpeg(args, duration=dur, cancel=cancel, registry=self.registry)
        if not r.ok:
            raise RenderError("Encode lại để giảm dung lượng thất bại", r)
        os.replace(tmp, path)

    # ------------------------------------------------------------ kiểm tra
    def verify(self, path: Path, expected: float) -> list[str]:
        errs: list[str] = []
        try:
            m = probe(path, use_cache=False)
        except Exception as e:  # noqa: BLE001
            return [f"không đọc được output ({e})"]
        if (m.width, m.height) != (self.out.W, self.out.H):
            errs.append(f"sai kích thước {m.width}×{m.height} (cần {self.out.W}×{self.out.H})")
        if not m.has_audio:
            errs.append("không có audio")
        tol = 1.0 / self.out.fps + 0.05
        if abs(m.video_duration - expected) > tol:
            errs.append(f"sai độ dài {m.video_duration:.3f}s (cần {expected:.3f}s)")
        return errs

    def thumbnail(self, video: Path, at: float, out_jpg: Path) -> None:
        run_ffmpeg(["-ss", _num(at), "-i", str(video), "-frames:v", "1", "-vf", "scale=-2:480", "-q:v", "3",
                    str(out_jpg)], registry=self.registry)


def _default_font() -> Optional[str]:
    cands = [D.REPO_ROOT / "assets" / "fonts" / "FiraSans-Bold.ttf",
             Path("C:/Windows/Fonts/arialbd.ttf"), Path("C:/Windows/Fonts/arial.ttf"),
             Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
             Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")]
    return next((str(p) for p in cands if p.exists()), None)


# ---------------------------------------------------------------- preview
class PreviewRunner:
    """Render 1 frame preview; request mới huỷ request cũ."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._gen = 0

    def frame(self, preset: Preset, task: TaskSpec, seg_index: int, t: float, before: bool = False) -> bytes:
        sample = next(iter(task.assets.values()), None)
        out = resolve_out_spec(preset, sample, preview=True)
        seg = preset.timeline[seg_index]
        g = build_segment(seg, task, out, probe, overlay_enabled=not before)
        t = max(0.0, min(t, g.duration - 1.0 / out.fps))
        g.add(f"[{g.aout}]anullsink")
        info = find_ffmpeg()
        cmd = [info.ffmpeg, "-hide_banner", "-nostdin", "-v", "error", *g.input_args(), "-filter_complex",
               g.filter_complex(), "-map", f"[{g.vout}]", "-ss", _num(t), "-frames:v", "1",
               "-f", "image2pipe", "-c:v", "png", "pipe:1"]
        with self._lock:
            self._gen += 1
            gen = self._gen
            if self._proc and self._proc.poll() is None:
                kill_tree(self._proc.pid)
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                 **popen_kwargs())
            self._proc = p
        out_b, err = p.communicate(timeout=120)
        if gen != self._gen:
            raise Cancelled()
        if p.returncode != 0 or not out_b:
            raise RenderError("Preview lỗi: " + err.decode("utf-8", "replace")[-800:])
        return out_b


def render_preview_clip(preset: Preset, task: TaskSpec, out_file: Path, seconds: float = 5.0,
                        temp_root: Optional[Path] = None, cancel: Optional[threading.Event] = None,
                        on_progress: Optional[ProgressFn] = None) -> Path:
    """Xem thử nhanh: 540p, ultrafast, `seconds` giây đầu."""
    sample = next(iter(task.assets.values()), None)
    out = resolve_out_spec(preset, sample, preview=True)
    tr = Path(temp_root or out_file.parent) / "pv_work"
    r = Renderer(preset, out, tr, fast_preview=True, force_cpu=True)
    work = tr / f"pv_{threading.get_ident()}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        parts = r.render_parts(task, work, cancel, on_progress, until=seconds)
        lst = work / "concat.txt"
        lst.write_text("ffconcat version 1.0\n" + "\n".join(concat_escape(p.path) for p in parts) + "\n",
                       encoding="utf-8")
        res = run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-t", _num(seconds), "-c:v", "copy",
                          "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out_file)], cancel=cancel)
        if not res.ok:
            raise RenderError("Xem thử lỗi", res)
        return out_file
    finally:
        shutil.rmtree(work, ignore_errors=True)
