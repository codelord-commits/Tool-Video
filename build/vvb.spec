# PyInstaller spec — bản onedir cho Windows (.exe) và macOS (.app).
#   pyinstaller build/vvb.spec --noconfirm
# Cần chạy `python scripts/get_ffmpeg.py` trước để có bin/ffmpeg + bin/ffprobe.
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
exe_suffix = ".exe" if sys.platform == "win32" else ""

datas = [
    (str(ROOT / "web" / "static"), "web/static"),
    (str(ROOT / "presets"), "presets"),
    (str(ROOT / "README.md"), "."),
    (str(ROOT / "LICENSE"), "."),
]
binaries = []
for tool in ("ffmpeg", "ffprobe"):
    p = ROOT / "bin" / f"{tool}{exe_suffix}"
    if not p.exists():
        raise SystemExit(f"Thiếu {p} — chạy: python scripts/get_ffmpeg.py")
    binaries.append((str(p), "bin"))
lic = ROOT / "bin" / "FFMPEG_LICENSE.txt"
if lic.exists():
    datas.append((str(lic), "bin"))

hidden = ["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
          "uvicorn.protocols.websockets.auto", "uvicorn.protocols.websockets.websockets_impl",
          "uvicorn.lifespan.on", "tkinter", "tkinter.filedialog"]

a = Analysis([str(ROOT / "build" / "launcher.py")], pathex=[str(ROOT)], binaries=binaries, datas=datas,
             hiddenimports=hidden, excludes=["pytest", "playwright"], noarchive=False)
pyz = PYZ(a.pure)
icon = ROOT / "build" / ("icon.ico" if sys.platform == "win32" else "icon.icns")
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="VideoVariantBuilder", console=True,
          icon=str(icon) if icon.exists() else None, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="VideoVariantBuilder", upx=False)
if sys.platform == "darwin":
    app = BUNDLE(coll, name="VideoVariantBuilder.app", icon=str(icon) if icon.exists() else None,
                 bundle_identifier="io.github.videovariantbuilder")
