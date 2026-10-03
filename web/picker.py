"""Hộp chọn thư mục/file gốc của OS — chạy như process riêng, in JSON ra stdout."""
from __future__ import annotations

import json
import sys


def run(kind: str, initial: str = "") -> None:
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    if kind == "file":
        p = filedialog.askopenfilename(initialdir=initial or None, title="Chọn file")
    else:
        p = filedialog.askdirectory(initialdir=initial or None, title="Chọn thư mục", mustexist=True)
    root.destroy()
    sys.stdout.write(json.dumps({"path": p or None}) + "\n")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "dir", sys.argv[2] if len(sys.argv) > 2 else "")
