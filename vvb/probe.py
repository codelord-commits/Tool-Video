"""ffprobe → MediaInfo (xoay, HDR, VFR, interlaced, alpha, audio…), có cache."""
from __future__ import annotations

import json
import threading
from fractions import Fraction
from pathlib import Path
from typing import Any, Optional

from . import defaults as D
from .ffmpeg import find_ffmpeg, run_capture
from .models import MediaInfo


class ProbeError(RuntimeError):
    def __init__(self, path: Path, msg: str):
        self.path = path
        super().__init__(f"{Path(path).name}: {msg}")


_cache: dict[tuple, MediaInfo] = {}
_lock = threading.Lock()

ALPHA_FMTS = ("yuva", "rgba", "bgra", "argb", "abgr", "gbrap", "ya8", "ya16")


def _frac(s: Optional[str]) -> float:
    try:
        f = Fraction(s or "0")
        return float(f) if f.denominator else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def _f(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _rotation(st: dict) -> int:
    rot = 0
    for sd in st.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(round(_f(sd["rotation"])))
    if not rot and "rotate" in (st.get("tags") or {}):
        rot = -int(_f(st["tags"]["rotate"]))  # tag rotate ngược chiều với displaymatrix
    return (-rot) % 360  # chiều kim đồng hồ, 0/90/180/270


def _count_packets_duration(path: Path, fps: float) -> float:
    info = find_ffmpeg()
    r = run_capture([info.ffprobe, "-v", "error", "-select_streams", "v:0", "-count_packets",
                     "-show_entries", "stream=nb_read_packets", "-of", "json", str(path)], timeout=300)
    try:
        n = int(json.loads(r.stdout)["streams"][0]["nb_read_packets"])
        return n / fps if fps else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def probe(path: Path | str, use_cache: bool = True) -> MediaInfo:
    path = Path(path)
    try:
        st = path.stat()
    except OSError as e:
        raise ProbeError(path, f"không đọc được file ({e.strerror or e})") from None
    key = (str(path.resolve()), st.st_size, st.st_mtime_ns)
    if use_cache:
        with _lock:
            if key in _cache:
                return _cache[key]
    mi = _probe(path, st.st_size)
    with _lock:
        _cache[key] = mi
    return mi


def _probe(path: Path, size: int) -> MediaInfo:
    info = find_ffmpeg()
    if size == 0:
        raise ProbeError(path, "file 0 byte")
    try:
        r = run_capture([info.ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                        timeout=120)
    except Exception as e:  # noqa: BLE001
        raise ProbeError(path, f"ffprobe lỗi: {e}") from None
    if r.returncode != 0:
        msg = r.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ProbeError(path, "file hỏng hoặc không đọc được" + (f" ({msg[-1]})" if msg else ""))
    data = json.loads(r.stdout.decode("utf-8", "replace") or "{}")
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    mi = MediaInfo(path=path, size_bytes=size, duration=_f(fmt.get("duration")))
    is_image = path.suffix.lower() in D.IMAGE_EXTS
    vids = [s for s in streams if s.get("codec_type") == "video"
            and not (s.get("disposition") or {}).get("attached_pic")]
    auds = [s for s in streams if s.get("codec_type") == "audio"]
    if not vids:
        raise ProbeError(path, "không có luồng video")
    v = vids[0]
    mi.vcodec = v.get("codec_name", "")
    mi.pix_fmt = v.get("pix_fmt", "") or ""
    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    if not w or not h:
        raise ProbeError(path, "không xác định được kích thước khung hình")
    mi.rotation = _rotation(v)
    if mi.rotation in (90, 270):
        w, h = h, w
    sar = v.get("sample_aspect_ratio") or "1:1"
    mi.sar = sar if sar not in ("0:1", "N/A") else "1:1"
    try:
        sn, sd = (int(x) for x in mi.sar.split(":"))
        if sn and sd and sn != sd:
            # kích thước hiển thị khi pixel không vuông
            w = int(round(w * sn / sd))
            mi.warnings.append(f"SAR {mi.sar} (pixel không vuông)")
    except ValueError:
        pass
    mi.width, mi.height = w, h
    mi.is_image = is_image
    mi.fps = _frac(v.get("r_frame_rate"))
    mi.avg_fps = _frac(v.get("avg_frame_rate")) or mi.fps
    if mi.fps > 240 or mi.fps <= 0:  # timebase lạ
        mi.fps = mi.avg_fps
    mi.vfr = bool(mi.fps and mi.avg_fps and abs(mi.fps - mi.avg_fps) > 0.01 * mi.fps)
    mi.start_time = _f(v.get("start_time"))
    mi.hdr = (v.get("color_transfer") or "") in ("smpte2084", "arib-std-b67")
    fo = v.get("field_order") or "progressive"
    mi.interlaced = fo not in ("progressive", "unknown")
    mi.has_alpha = mi.pix_fmt.startswith(ALPHA_FMTS) or (v.get("tags") or {}).get("alpha_mode") == "1"
    if is_image:
        mi.video_duration = 0.0
    else:
        vd = _f(v.get("duration"))
        if not vd:  # mkv/webm: độ dài nằm trong tag DURATION
            tag = (v.get("tags") or {}).get("DURATION")
            if tag:
                try:
                    hh, mm, ss = tag.split(":")
                    vd = int(hh) * 3600 + int(mm) * 60 + float(ss)
                except ValueError:
                    vd = 0.0
        if not vd and mi.avg_fps:
            vd = _count_packets_duration(path, mi.avg_fps)
            if vd:
                mi.warnings.append("Header thiếu độ dài — đã đo bằng đếm packet")
        if not vd:
            vd = mi.duration
        mi.video_duration = vd
        if mi.video_duration <= 0:
            raise ProbeError(path, "không xác định được độ dài")
        if mi.video_duration < 0.5:
            mi.warnings.append(f"Clip rất ngắn ({mi.video_duration:.2f}s)")
    if auds:
        default = next((a for a in auds if (a.get("disposition") or {}).get("default")), auds[0])
        mi.has_audio = True
        mi.audio_index = auds.index(default)
        mi.audio_channels = int(default.get("channels") or 0)
        mi.audio_rate = int(default.get("sample_rate") or 0)
        mi.audio_duration = _f(default.get("duration"))
        if len(auds) > 1:
            mi.warnings.append(f"{len(auds)} track audio — dùng track {mi.audio_index}")
    if mi.hdr:
        mi.warnings.append("Nguồn HDR — sẽ tonemap về SDR")
    if mi.vfr:
        mi.warnings.append("Frame rate thay đổi (VFR) — sẽ ép CFR")
    if mi.interlaced:
        mi.warnings.append("Video interlaced — sẽ deinterlace")
    if mi.rotation:
        mi.warnings.append(f"Metadata xoay {mi.rotation}°")
    if mi.width % 2 or mi.height % 2:
        mi.warnings.append(f"Kích thước lẻ {mi.width}×{mi.height}")
    return mi


def clear_cache() -> None:
    with _lock:
        _cache.clear()
