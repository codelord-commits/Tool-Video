"""Server web local: FastAPI chỉ nghe 127.0.0.1, token + kiểm Host/Origin, tự mở trình duyệt."""
from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import socket
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Iterable, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from .api import fs, jobs, preview, presets, project, system
from .state import STATE

STATIC = Path(__file__).parent / "static"
COOKIE = "vvb_token"

EXPIRED_PAGE = """<!doctype html><html lang="vi"><meta charset="utf-8"><title>Video Variant Builder</title>
<style>body{font-family:system-ui,sans-serif;background:#0B0B14;color:#E7E7F5;display:grid;place-items:center;
height:100vh;margin:0}main{max-width:420px;text-align:center;line-height:1.6}</style>
<main><h1>Phiên đã hết hạn</h1><p>Vì lý do bảo mật, hãy mở lại giao diện từ ứng dụng
(cửa sổ dòng lệnh hoặc biểu tượng Video Variant Builder).</p></main></html>"""


def create_app(token: str, allowed_hosts: Iterable[str]) -> FastAPI:
    app = FastAPI(title="Video Variant Builder", docs_url=None, redoc_url=None, openapi_url=None)
    hosts = set(allowed_hosts)
    STATE.token = token

    def _authorized(req_headers, cookies, query) -> bool:
        tok = cookies.get(COOKIE) or req_headers.get("x-vvb-token") or query.get("t")
        return bool(tok) and secrets.compare_digest(tok, token)

    def _host_ok(headers) -> bool:
        host = headers.get("host", "")
        if hosts and host not in hosts:
            return False
        origin = headers.get("origin")
        if origin and origin.split("://", 1)[-1] not in hosts:
            return False
        return True

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if not _host_ok(request.headers):
            return JSONResponse({"detail": "Host không hợp lệ"}, status_code=403)
        if path.startswith("/api"):
            if not _authorized(request.headers, request.cookies, {}):
                return JSONResponse({"detail": "Phiên hết hạn — mở lại từ ứng dụng"}, status_code=401)
        resp: Response = await call_next(request)
        if path.startswith("/static"):
            resp.headers["Cache-Control"] = "no-cache"  # luôn kiểm tra lại (etag) — tránh UI cũ sau khi cập nhật
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        return resp

    @app.get("/", include_in_schema=False)
    async def index(request: Request):
        t = request.query_params.get("t")
        if t and secrets.compare_digest(t, token):
            r = RedirectResponse("/", status_code=303)
            r.set_cookie(COOKIE, token, httponly=True, samesite="strict")
            return r
        if not _authorized(request.headers, request.cookies, {}):
            return HTMLResponse(EXPIRED_PAGE, status_code=401)
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html, headers={"Cache-Control": "no-store",
                                           "Content-Security-Policy": "default-src 'self'; img-src 'self' blob: data:; "
                                           "media-src 'self' blob:; style-src 'self' 'unsafe-inline'; "
                                           "script-src 'self' 'unsafe-eval'; connect-src 'self' ws: wss:; "
                                           "font-src 'self'; frame-ancestors 'none'"})

    @app.websocket("/ws")
    async def ws(socket_: WebSocket):
        if not _host_ok(socket_.headers) or not _authorized(socket_.headers, socket_.cookies, {}):
            await socket_.close(code=4401)
            return
        await socket_.accept()
        loop = asyncio.get_running_loop()
        q = STATE.add_client(loop)
        try:
            await socket_.send_text(json.dumps({"type": "snapshot", **STATE.snapshot()}, default=str))
            while True:
                ev = await q.get()
                await socket_.send_text(json.dumps(ev, ensure_ascii=False, default=str))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            STATE.remove_client(loop, q)

    for r in (fs.router, presets.router, project.router, preview.router, jobs.router, system.router):
        app.include_router(r)
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
    return app


def free_port(preferred: int = 8765) -> int:
    for p in [preferred, *range(preferred + 1, preferred + 50), 0]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("Không tìm được cổng trống")


def main(argv: Optional[list[str]] = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--pick"]:  # bản đóng gói: hộp chọn thư mục gốc chạy trong process con
        from .picker import run
        run(argv[1] if len(argv) > 1 else "dir", argv[2] if len(argv) > 2 else "")
        return
    if argv[:1] == ["cli"]:  # bản đóng gói: dùng CLI qua cùng file exe
        from vvb.__main__ import main as cli_main
        sys.exit(cli_main(argv[1:]))
    ap = argparse.ArgumentParser(prog="vvb-web", description="Video Variant Builder — giao diện web")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--token", help="Token cố định (mặc định ngẫu nhiên mỗi lần chạy)")
    a = ap.parse_args(argv)
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
    import uvicorn
    port = free_port(a.port)
    token = a.token or secrets.token_urlsafe(24)
    STATE.port = port
    app = create_app(token, {f"127.0.0.1:{port}", f"localhost:{port}"})
    url = f"http://127.0.0.1:{port}/?t={token}"
    print(f"Video Variant Builder đang chạy: {url}\nĐóng cửa sổ này hoặc bấm Ctrl+C để thoát.", flush=True)
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
