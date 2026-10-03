"""Tải asset front-end vào web/static (chạy 1 lần khi phát triển; kết quả được commit).

- Alpine.js
- Icon Lucide → 1 file sprite SVG
- Font Fira Sans (latin, latin-ext, vietnamese) + Fira Code (latin)
"""
from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "web" / "static"
CDN = "https://cdn.jsdelivr.net/npm"

ICONS = [
    "folder", "folder-open", "folder-search", "film", "music", "image", "circle-check", "triangle-alert", "circle-x",
    "refresh-cw", "play", "pause", "square", "save", "plus", "copy", "pencil", "trash-2", "download", "upload",
    "sun", "moon", "monitor", "languages", "chevron-down", "chevron-right", "chevron-up", "chevron-left",
    "settings-2", "sliders-horizontal", "layers", "grid-3x3", "smartphone", "columns-2", "info", "external-link",
    "hard-drive", "house", "list", "x", "eye", "rotate-ccw", "power", "clock", "file-video", "wand-sparkles",
    "hand", "circle-play", "loader-circle", "arrow-up", "menu", "panel-right", "check", "minus", "scissors",
    "audio-lines", "timer", "zap", "wrench", "file-json", "circle-dashed", "keyboard", "shield", "scan",
    "circle-help", "history", "square-dashed", "move", "crop", "ellipsis",
]

FONTS = [("fira-sans", s, w) for s in ("latin", "latin-ext", "vietnamese") for w in (400, 500, 600, 700)] + \
        [("fira-code", "latin", w) for w in (400, 500, 600)]


def get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def main() -> int:
    (STATIC / "vendor").mkdir(parents=True, exist_ok=True)
    (STATIC / "fonts").mkdir(parents=True, exist_ok=True)
    print("Alpine.js…")
    (STATIC / "vendor" / "alpine.min.js").write_bytes(get(f"{CDN}/alpinejs@3.14.9/dist/cdn.min.js"))
    print("Lucide icons…")
    symbols, missing = [], []
    for name in ICONS:
        try:
            svg = get(f"{CDN}/lucide-static@0.469.0/icons/{name}.svg").decode("utf-8")
        except Exception:  # noqa: BLE001
            missing.append(name)
            continue
        inner = re.sub(r"^.*?<svg[^>]*>|</svg>\s*$", "", svg, flags=re.S).strip()
        inner = re.sub(r"<!--.*?-->", "", inner, flags=re.S)
        symbols.append(f'<symbol id="i-{name}" viewBox="0 0 24 24">{inner}</symbol>')
    sprite = ('<svg xmlns="http://www.w3.org/2000/svg" style="display:none" fill="none" stroke="currentColor" '
              'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + "".join(symbols) + "</svg>")
    (STATIC / "vendor" / "icons.svg").write_text(sprite, encoding="utf-8")
    print("Fonts…")
    for fam, subset, w in FONTS:
        fn = f"{fam}-{subset}-{w}-normal.woff2"
        (STATIC / "fonts" / fn).write_bytes(get(f"{CDN}/@fontsource/{fam}@5/files/{fn}"))
    (STATIC / "vendor" / "LICENSES.txt").write_text(
        "Alpine.js — MIT (https://github.com/alpinejs/alpine)\n"
        "Lucide icons — ISC (https://lucide.dev)\n"
        "Fira Sans, Fira Code — SIL Open Font License 1.1 (via Fontsource)\n", encoding="utf-8")
    if missing:
        print("Thiếu icon:", ", ".join(missing))
    print("Xong.")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
