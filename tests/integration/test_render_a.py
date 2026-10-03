import os
import subprocess
from pathlib import Path

import pytest

from tests import media as M
from vvb.combiner import combine
from vvb.ffmpeg import find_ffmpeg, popen_kwargs
from vvb.matcher import build_match
from vvb.naming import build_out_path
from vvb.preset_io import load_preset
from vvb.probe import probe
from vvb.renderer import Renderer, resolve_out_spec
from vvb.scanner import resolve_project, scan_slot

pytestmark = pytest.mark.integration


def pixel(video: Path, t: float, x: int, y: int) -> tuple[int, int, int]:
    info = find_ffmpeg()
    r = subprocess.run([info.ffmpeg, "-v", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1",
                        "-vf", f"crop=8:8:{x}:{y},scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       capture_output=True, **popen_kwargs())
    b = r.stdout
    assert len(b) >= 3, r.stderr
    return b[0], b[1], b[2]


def hexrgb(h: str) -> tuple[int, int, int]:
    v = int(h, 16)
    return (v >> 16) & 255, (v >> 8) & 255, v & 255


def close(a, b, tol=30) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def build_tasks(preset, root):
    paths = resolve_project(preset, str(root))
    scans = {n: scan_slot(n, s, paths.get(n)) for n, s in preset.slots.items()}
    m = build_match(preset, scans)
    tasks, _ = combine(preset, m)
    return tasks


def test_job_a_render(project_a, tmp_path):
    p = load_preset("palm_bottom")
    tasks = build_tasks(p, project_a)
    assert len(tasks) == 6
    out = resolve_out_spec(p)
    r = Renderer(p, out, tmp_path / "tmp", cache_dir=tmp_path / "cache")
    # clip02 ngắn 0.8s → loop
    t = next(x for x in tasks if x.clip_name == "clip02" and x.group_display == "French")
    dest = build_out_path(tmp_path / "Output", t, p, "palm", (out.W, out.H))
    res = r.render_task(t, dest)
    assert dest.exists() and not dest.with_name(dest.stem + ".part.mp4").exists()
    m = probe(dest, use_cache=False)
    assert (m.width, m.height) == (1080, 1920) and m.has_audio
    assert abs(m.video_duration - (2.0 + 1.5 + 1.0)) <= 1 / 30 + 0.05
    assert abs(res.duration - 4.5) < 0.05
    # đoạn đầu: nửa trên = nền, dải caption = nền, nửa dưới = pool
    for tt in (0.3, 1.5):
        assert close(pixel(dest, tt, 500, 300), hexrgb(M.TOP))
        assert close(pixel(dest, tt, 500, int(1920 * 0.51)), hexrgb(M.BAND))
        assert close(pixel(dest, tt, 500, 1600), hexrgb(M.POOL))
    # đoạn Source đúng màu nhóm French
    from tests.conftest import GROUP_COLORS
    assert close(pixel(dest, 2.7, 500, 500), hexrgb(GROUP_COLORS["French"][2:]))
    # Outtro đen
    assert close(pixel(dest, 4.2, 500, 500), (0, 0, 0))


def test_cache_reused(project_a, tmp_path):
    p = load_preset("palm_bottom")
    tasks = build_tasks(p, project_a)
    out = resolve_out_spec(p)
    r = Renderer(p, out, tmp_path / "tmp", cache_dir=tmp_path / "cache")
    a = [x for x in tasks if x.group_display == "Arab"]
    r.render_task(a[0], tmp_path / "o1.mp4")
    n1 = len(list((tmp_path / "cache").glob("*.mov")))
    r.render_task(a[1], tmp_path / "o2.mp4")
    n2 = len(list((tmp_path / "cache").glob("*.mov")))
    assert n1 == 2 and n2 == 2  # Source[arab] + Outtro dùng lại
