"""Tải ffmpeg + ffprobe bản static vào bin/ (Windows, macOS, Linux).

    python scripts/get_ffmpeg.py

- Windows / Linux: bản GPL của BtbN/FFmpeg-Builds (có libx264, libx265, NVENC, QSV, AMF), kiểm SHA256.
- macOS: bản static của evermeet.cx (Intel; chạy trên Apple Silicon qua Rosetta) — hoặc dùng `brew install ffmpeg`.
"""
from __future__ import annotations

import hashlib
import io
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
BTBN = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest"
VERSION = "n8.1"


def get(url: str) -> bytes:
    print(f"  tải {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "video-variant-builder"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def btbn_asset(target: str) -> str:
    """Tên file bản release mới nhất cho target (win64 / linux64 / linuxarm64)."""
    import json
    data = json.loads(get("https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest"))
    names = [a["name"] for a in data["assets"]]
    pat = re.compile(rf"ffmpeg-{VERSION}-latest-{target}-gpl-[\d.]+\.(zip|tar\.xz)$")
    for n in names:
        if pat.match(n):
            return n
    raise SystemExit(f"Không tìm thấy bản {VERSION} cho {target}. Có: {', '.join(names[:10])}…")


def verify_sha(name: str, blob: bytes) -> None:
    sums = get(f"{BTBN}/checksums.sha256").decode()
    want = next((l.split()[0] for l in sums.splitlines() if l.strip().endswith(name)), None)
    got = hashlib.sha256(blob).hexdigest()
    if want and want != got:
        raise SystemExit(f"SHA256 không khớp cho {name}")
    print("  SHA256 OK" if want else "  (không có checksum để so)")


def install_btbn(target: str) -> None:
    name = btbn_asset(target)
    blob = get(f"{BTBN}/{name}")
    verify_sha(name, blob)
    exe = ".exe" if target.startswith("win") else ""
    if name.endswith(".zip"):
        zf = zipfile.ZipFile(io.BytesIO(blob))
        members = {Path(m).name: m for m in zf.namelist()}
        for tool in ("ffmpeg", "ffprobe"):
            (BIN / f"{tool}{exe}").write_bytes(zf.read(members[f"{tool}{exe}"]))
        lic = next((m for m in zf.namelist() if m.endswith("LICENSE.txt")), None)
        if lic:
            (BIN / "FFMPEG_LICENSE.txt").write_bytes(zf.read(lic))
    else:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:xz") as tf:
            for m in tf.getmembers():
                base = Path(m.name).name
                if base in ("ffmpeg", "ffprobe", "LICENSE.txt") and m.isfile():
                    dst = BIN / ("FFMPEG_LICENSE.txt" if base == "LICENSE.txt" else base)
                    dst.write_bytes(tf.extractfile(m).read())


def install_mac() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        blob = get(f"https://evermeet.cx/ffmpeg/getrelease/{tool}/zip")
        zf = zipfile.ZipFile(io.BytesIO(blob))
        (BIN / tool).write_bytes(zf.read(tool))
    (BIN / "FFMPEG_LICENSE.txt").write_text(
        "ffmpeg (GPL) — bản build từ https://evermeet.cx/ffmpeg/ . Mã nguồn: https://ffmpeg.org/download.html\n",
        encoding="utf-8")


def check() -> None:
    exe = ".exe" if os.name == "nt" else ""
    ff = BIN / f"ffmpeg{exe}"
    out = subprocess.run([str(ff), "-hide_banner", "-version"], capture_output=True, text=True).stdout
    encs = subprocess.run([str(ff), "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    print("  " + out.splitlines()[0])
    if "libx264" not in encs:
        raise SystemExit("ffmpeg thiếu libx264")


def main() -> int:
    BIN.mkdir(exist_ok=True)
    sysname, mach = platform.system(), platform.machine().lower()
    print(f"Hệ điều hành: {sysname} {mach}")
    if sysname == "Windows":
        install_btbn("win64")
    elif sysname == "Linux":
        install_btbn("linuxarm64" if mach in ("aarch64", "arm64") else "linux64")
    elif sysname == "Darwin":
        install_mac()
    else:
        raise SystemExit(f"Chưa hỗ trợ {sysname} — hãy cài ffmpeg vào PATH")
    if os.name != "nt":
        for tool in ("ffmpeg", "ffprobe"):
            p = BIN / tool
            p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    check()
    print(f"Xong — ffmpeg nằm trong {BIN}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
