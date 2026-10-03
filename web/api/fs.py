"""Duyệt thư mục trên máy (thay cho kéo thả — trình duyệt không lộ đường dẫn tuyệt đối)."""
from __future__ import annotations

import json
import os
import string
import subprocess
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from vvb import defaults as D
from vvb.ffmpeg import popen_kwargs
from vvb.scanner import _is_junk, natural_key

router = APIRouter(prefix="/api/fs", tags=["fs"])
MEDIA = set(D.VIDEO_EXTS) | set(D.IMAGE_EXTS) | {".srt", ".csv", ".json", ".mp3", ".m4a", ".wav", ".aac"}


@router.get("/roots")
def roots():
    out = []
    home = Path.home()
    out.append({"name": "Thư mục người dùng", "path": str(home), "kind": "home"})
    for sub in ("Desktop", "Downloads", "Videos", "Movies", "Documents"):
        p = home / sub
        if p.is_dir():
            out.append({"name": sub, "path": str(p), "kind": "folder"})
    if os.name == "nt":
        for L in string.ascii_uppercase:
            p = f"{L}:\\"
            if os.path.exists(p):
                out.append({"name": f"Ổ {L}:", "path": p, "kind": "drive"})
    else:
        out.append({"name": "/", "path": "/", "kind": "drive"})
        vol = Path("/Volumes")
        if vol.is_dir():
            out += [{"name": v.name, "path": str(v), "kind": "drive"} for v in vol.iterdir() if v.is_dir()]
    return out


@router.get("/list")
def list_dir(path: str, files: bool = True):
    p = Path(path).expanduser()
    if not p.exists():
        raise HTTPException(404, f"Không tồn tại: {p}")
    if p.is_file():
        p = p.parent
    dirs, fl = [], []
    try:
        entries = list(p.iterdir())
    except PermissionError:
        raise HTTPException(403, "Không có quyền đọc thư mục này") from None
    for e in entries:
        if _is_junk(e):
            continue
        try:
            if e.is_dir():
                dirs.append({"name": e.name, "path": str(e)})
            elif files and e.suffix.lower() in MEDIA:
                fl.append({"name": e.name, "path": str(e), "size": e.stat().st_size})
        except OSError:
            continue
    dirs.sort(key=lambda d: natural_key(d["name"]))
    fl.sort(key=lambda d: natural_key(d["name"]))
    parent = str(p.parent) if p.parent != p else None
    parts = []
    acc = Path(p.anchor) if p.anchor else None
    if acc:
        parts.append({"name": p.anchor, "path": str(acc)})
        for part in p.parts[1:]:
            acc = acc / part
            parts.append({"name": part, "path": str(acc)})
    return {"path": str(p), "parent": parent, "crumbs": parts, "dirs": dirs, "files": fl}


class DialogBody(BaseModel):
    kind: str = "dir"  # dir | file
    initial: Optional[str] = None


def pick_native(kind: str, initial: Optional[str]) -> Optional[str]:
    """Hộp chọn của OS chạy trong process con (tkinter cần main thread)."""
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--pick", kind, initial or ""]
    else:
        cmd = [sys.executable, "-m", "web.picker", kind, initial or ""]
    kw = popen_kwargs()
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=600, cwd=str(D.REPO_ROOT), **kw)
    except subprocess.TimeoutExpired:
        return None
    try:
        return json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1]).get("path")
    except (ValueError, IndexError):
        return None


@router.post("/dialog")
def dialog(b: DialogBody):
    return {"path": pick_native(b.kind, b.initial)}
