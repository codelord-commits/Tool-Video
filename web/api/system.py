"""Hệ thống: kiểm tra ffmpeg, encoder, settings, mở thư mục, thoát."""
from __future__ import annotations

import os
import platform
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from vvb import __version__
from vvb.ffmpeg import available_encoders, check_ffmpeg, find_ffmpeg
from vvb.system import open_folder

from ..state import STATE

router = APIRouter(prefix="/api", tags=["system"])
_enc_cache: list[str] = []


@router.get("/system")
def system():
    errs = check_ffmpeg()
    info = None
    if not errs:
        f = find_ffmpeg()
        info = {"path": f.ffmpeg, "version": f.version_str}
        if not _enc_cache:
            _enc_cache.extend(available_encoders())
    return {"app_version": __version__, "ffmpeg_ok": not errs, "ffmpeg_errors": errs, "ffmpeg": info,
            "encoders": list(_enc_cache), "cpu": os.cpu_count(), "platform": platform.system(),
            "running": STATE.running, "settings": STATE.load_settings()}


@router.get("/settings")
def get_settings():
    return STATE.load_settings()


@router.put("/settings")
def put_settings(body: dict[str, Any]):
    return STATE.save_settings(body)


class PathBody(BaseModel):
    path: str


@router.post("/system/open")
def open_path(b: PathBody):
    p = Path(b.path)
    if not p.exists():
        p = p.parent if p.parent.exists() else p
    if not p.exists():
        raise HTTPException(404, "Không tồn tại")
    open_folder(p)
    return {"ok": True}


class QuitBody(BaseModel):
    force: bool = False


@router.post("/system/quit")
def quit_app(b: QuitBody):
    if STATE.running and not b.force:
        raise HTTPException(409, "Đang có job chạy")
    if STATE.runner and STATE.running:
        STATE.runner.cancel()
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return {"ok": True}
