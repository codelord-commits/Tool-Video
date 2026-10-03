import os
from pathlib import Path

import pytest

from tests import media as M


def _has_ffmpeg() -> bool:
    try:
        from vvb.ffmpeg import find_ffmpeg
        find_ffmpeg()
        return True
    except Exception:  # noqa: BLE001
        return False


HAS_FFMPEG = _has_ffmpeg()


def pytest_collection_modifyitems(config, items):
    skip_ff = pytest.mark.skip(reason="cần ffmpeg")
    skip_real = pytest.mark.skip(reason="đặt VVB_REAL_DATA để chạy")
    for it in items:
        if "integration" in it.keywords and not HAS_FFMPEG:
            it.add_marker(skip_ff)
        if "real" in it.keywords and not os.environ.get("VVB_REAL_DATA"):
            it.add_marker(skip_real)


@pytest.fixture(scope="session")
def fx():
    """Các file media edge case."""
    return {
        "basic": M.make("basic.mp4", lambda p: M.testsrc(p, 2.0, 1080, 1920)),
        "no_audio": M.make("no_audio.mp4", lambda p: M.testsrc(p, 1.0, 720, 1280, audio=False)),
        "rotated": M.make("rotated90.mp4", M.rotated),
        "vfr": M.make("vfr.mp4", M.vfr),
        "odd": M.make("odd_1079x1919.mp4", M.odd),
        "mono48": M.make("mono_48k.mp4", lambda p: M.solid(p, "0x808080", 1.0, 720, 1280, ar=48000, ac=1)),
        "landscape": M.make("landscape.mp4", lambda p: M.testsrc(p, 1.5, 1920, 1080)),
        "short": M.make("short.mp4", lambda p: M.testsrc(p, 0.3, 720, 1280)),
        "corrupt": M.make("corrupt.mp4", M.corrupt),
        "accent": M.make("Tiếng Việt 'nháy' 🎬.mp4", lambda p: M.testsrc(p, 1.0, 720, 1280)),
        "fps50": M.make("fps50.mp4", lambda p: M.testsrc(p, 1.0, 720, 1280, fps=50)),
    }


GROUP_COLORS = {"Arab": "0x804000", "French": "0x008080", "Hindi": "0x800080"}


@pytest.fixture(scope="session")
def project_a(tmp_path_factory):
    """Dự án giả lập dạng A: 3 nhóm × 2 clip."""
    root = tmp_path_factory.mktemp("projA")
    for g, col in GROUP_COLORS.items():
        (root / "Intro").mkdir(exist_ok=True)
        (root / "Source").mkdir(exist_ok=True)
        src_i = M.make(f"A_intro_{g}.mp4", lambda p: M.intro_layout(p, 2.0))
        src_s = M.make(f"A_source_{g}.mp4", lambda p, c=col: M.solid(p, c, 1.5, 1080, 1920, freq=880))
        _link(src_i, root / "Intro" / f"{g}.mp4")
        _link(src_s, root / "Source" / f"{g}.mov")
    (root / "Video").mkdir()
    c1 = M.make("A_pool1.mp4", lambda p: M.solid(p, M.POOL, 3.0, 720, 1280, freq=300))
    c2 = M.make("A_pool2.mp4", lambda p: M.solid(p, M.POOL, 0.8, 720, 1280, freq=300))  # ngắn → loop
    _link(c1, root / "Video" / "clip01.mp4")
    _link(c2, root / "Video" / "clip02.mp4")
    o = M.make("A_outtro.mp4", lambda p: M.solid(p, "0x000000", 1.0, 1080, 1920, freq=220))
    _link(o, root / "Outtro.mp4")
    return root


def _link(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        import shutil
        shutil.copyfile(src, dst)
