"""Sinh video giả lập bằng ffmpeg lavfi cho test (cache trong tests/fixtures/_generated)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from vvb.ffmpeg import find_ffmpeg, popen_kwargs

GEN = Path(__file__).parent / "fixtures" / "_generated"

# Màu dùng để kiểm pixel
TOP = "0x2040C0"      # xanh dương
BOTTOM = "0x20A040"   # xanh lá
BAND = "0xF0F0F0"     # dải caption
POOL = "0xD02020"     # đỏ


def ff(*args: str) -> None:
    info = find_ffmpeg()
    r = subprocess.run([info.ffmpeg, "-hide_banner", "-v", "error", "-y", *args], capture_output=True, **popen_kwargs())
    if r.returncode:
        raise RuntimeError(r.stderr.decode("utf-8", "replace"))


def _x264(*extra: str) -> list[str]:
    return ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", *extra]


def make(name: str, builder, regenerate: bool = False) -> Path:
    GEN.mkdir(parents=True, exist_ok=True)
    out = GEN / name
    if regenerate or not out.exists():
        tmp = out.with_name("tmp_" + out.name)
        builder(tmp)
        os.replace(tmp, out)
    return out


def intro_layout(path: Path, dur: float = 2.0, w: int = 1080, h: int = 1920, freq: int = 440) -> None:
    """Nửa trên xanh dương, nửa dưới xanh lá, dải caption trắng ở y 0.48–0.545, có tiếng sine."""
    band_y, band_h = int(h * 0.48), int(h * 0.065)
    vf = (f"drawbox=x=0:y={h // 2}:w={w}:h={h // 2}:color={BOTTOM}:t=fill,"
          f"drawbox=x=0:y={band_y}:w={w}:h={band_h}:color={BAND}:t=fill")
    ff("-f", "lavfi", "-i", f"color=c={TOP}:s={w}x{h}:r=30:d={dur}",
       "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=44100:duration={dur}",
       "-vf", vf, *_x264(), "-c:a", "aac", "-shortest", str(path))


def solid(path: Path, color: str, dur: float, w: int, h: int, fps: int = 30, audio: bool = True,
          freq: int = 660, ar: int = 44100, ac: int = 2) -> None:
    args = ["-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:r={fps}:d={dur}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate={ar}:duration={dur}",
                 "-ac", str(ac), "-c:a", "aac"]
    ff(*args, *_x264(), "-t", str(dur), str(path))


def testsrc(path: Path, dur: float, w: int, h: int, fps: int = 30, audio: bool = True) -> None:
    args = ["-f", "lavfi", "-i", f"testsrc2=s={w}x{h}:r={fps}:d={dur}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=550:duration={dur}", "-c:a", "aac"]
    ff(*args, *_x264(), "-t", str(dur), str(path))


def rotated(path: Path) -> None:
    src = make("land_src.mp4", lambda p: testsrc(p, 1.0, 640, 360))
    ff("-display_rotation:v:0", "90", "-i", str(src), "-c", "copy", str(path))


def vfr(path: Path) -> None:
    ff("-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=2", "-vf", "select='if(lt(t,1),not(mod(n,3)),1)'",
       "-fps_mode", "vfr", *_x264(), str(path))


def odd(path: Path) -> None:
    ff("-f", "lavfi", "-i", "color=c=gray:s=1080x1920:r=30:d=1", "-f", "lavfi", "-i", "sine=duration=1", "-vf", "scale=1079:1919",
       "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv444p", "-c:a", "aac", "-shortest", str(path))


def corrupt(path: Path) -> None:
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + os.urandom(4096))
