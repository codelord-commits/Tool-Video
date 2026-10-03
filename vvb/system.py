"""Tiện ích hệ thống: chặn ngủ, dung lượng ổ, thông báo, mở thư mục."""
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterator, Optional

from .ffmpeg import popen_kwargs


def free_disk_gb(path: Path) -> float:
    p = Path(path)
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        return shutil.disk_usage(p).free / 1024 ** 3
    except OSError:
        return float("inf")


@contextlib.contextmanager
def prevent_sleep(enabled: bool = True) -> Iterator[None]:
    """Không cho máy ngủ trong khi render (O3)."""
    if not enabled:
        yield
        return
    proc: Optional[subprocess.Popen] = None
    try:
        if os.name == "nt":
            import ctypes
            ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        elif sys.platform == "darwin" and shutil.which("caffeinate"):
            proc = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
        elif shutil.which("systemd-inhibit"):
            proc = subprocess.Popen(["systemd-inhibit", "--what=idle:sleep", "--why=Video Variant Builder",
                                     "sleep", "infinity"])
    except Exception:  # noqa: BLE001
        pass
    try:
        yield
    finally:
        try:
            if os.name == "nt":
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            if proc:
                proc.terminate()
        except Exception:  # noqa: BLE001
            pass


def notify(title: str, message: str) -> None:
    """Thông báo hệ thống + âm báo (dự phòng cho web)."""
    try:
        if os.name == "nt":
            import winsound
            winsound.MessageBeep()
            ps = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null;"
                  "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(1);"
                  f"$t.GetElementsByTagName('text')[0].AppendChild($t.CreateTextNode('{_ps(title)}: {_ps(message)}')) > $null;"
                  "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Video Variant Builder')"
                  ".Show([Windows.UI.Notifications.ToastNotification]::new($t))")
            subprocess.Popen(["powershell", "-NoProfile", "-Command", ps], **popen_kwargs())
        elif sys.platform == "darwin":
            subprocess.Popen(["osascript", "-e", f'display notification "{message}" with title "{title}" sound name "Glass"'])
        elif shutil.which("notify-send"):
            subprocess.Popen(["notify-send", title, message])
    except Exception:  # noqa: BLE001
        pass


def _ps(s: str) -> str:
    return s.replace("'", "''")


def open_folder(path: Path) -> None:
    p = str(path)
    if os.name == "nt":
        os.startfile(p)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


def long_path(p: Path) -> str:
    """F4: tiền tố \\\\?\\ cho đường dẫn dài trên Windows."""
    s = str(Path(p).resolve())
    if os.name == "nt" and len(s) >= 240 and not s.startswith("\\\\?\\"):
        return "\\\\?\\" + s
    return s


def is_writable_dir(path: Path) -> Optional[str]:
    """None nếu ghi được, ngược lại trả lý do."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        t = path / ".vvb_write_test"
        t.write_bytes(b"ok")
        t.unlink()
        return None
    except OSError as e:
        return str(e.strerror or e)


def is_online_only(path: Path) -> bool:
    """F7: file OneDrive/Google Drive chưa tải về máy (Windows: thuộc tính RECALL/OFFLINE)."""
    if os.name != "nt":
        return False
    try:
        attrs = os.stat(path).st_file_attributes  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        return False
    FILE_ATTRIBUTE_OFFLINE = 0x1000
    FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
    FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
    return bool(attrs & (FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS | FILE_ATTRIBUTE_RECALL_ON_OPEN))
