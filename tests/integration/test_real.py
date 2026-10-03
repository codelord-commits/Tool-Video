"""Kiểm tra trên dữ liệu thật (không chạy trên CI): VVB_REAL_DATA=<thư mục dự án dạng A>.

- Voice Intro giữ nguyên: tương quan audio 3s đầu output ↔ Intro gốc cao.
- Nửa trên giữ nguyên Intro (so từng pixel).
- Đoạn Source đúng ngôn ngữ: khung hình gần Source cùng nhóm nhất (Source các ngôn ngữ chỉ khác chữ trên màn hình,
  nên so màu trung bình/âm thanh không phân biệt được — phải so từng pixel).
"""
import array
import math
import os
import subprocess
from pathlib import Path

import pytest

from vvb.api import make_job
from vvb.batch import BatchRunner
from vvb.events import EventBus
from vvb.ffmpeg import find_ffmpeg, popen_kwargs
from vvb.plan import plan_job
from vvb.probe import probe

pytestmark = [pytest.mark.real, pytest.mark.integration]
SRC_T = float(os.environ.get("VVB_REAL_SOURCE_T", "6.0"))  # thời điểm trong Source có chữ khác nhau theo ngôn ngữ


def gray(video: Path, t: float, vf: str = "scale=108:192") -> bytes:
    r = subprocess.run([find_ffmpeg().ffmpeg, "-v", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1",
                        "-vf", vf, "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, **popen_kwargs())
    return r.stdout


def mad(a: bytes, b: bytes) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / max(1, min(len(a), len(b)))


def pcm(video: Path, t: float, d: float = 3.0) -> array.array:
    r = subprocess.run([find_ffmpeg().ffmpeg, "-v", "error", "-ss", str(t), "-t", str(d), "-i", str(video),
                        "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], capture_output=True, **popen_kwargs())
    return array.array("h", r.stdout)


def corr(a, b) -> float:
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return num / (da * db + 1e-9)


def test_real_one_per_group(tmp_path):
    root = Path(os.environ["VVB_REAL_DATA"])
    job = make_job("palm_bottom", project=str(root), out_dir=str(tmp_path / "O"))
    job.clips_filter = [sorted((root / "Video").iterdir())[0].stem]
    job.preset.run.prevent_sleep = job.preset.run.notify_done = False
    plan = plan_job(job)
    assert plan.ok, plan.blockers()
    s = BatchRunner(plan, EventBus()).run()
    assert s.failed == 0
    sources = {t.group: t.assets["source"] for t in plan.tasks}
    for t in plan.tasks:
        out = Path(t.out_path)
        intro, source = t.assets["intro"], t.assets["source"]
        di = probe(intro).video_duration
        m = probe(out, use_cache=False)
        assert (m.width, m.height) == (1080, 1920) and m.has_audio
        expect = di + probe(source).video_duration + probe(t.assets["outtro"]).video_duration
        assert abs(m.video_duration - expect) <= 2 / 30 + 0.05
        # voice Intro giữ nguyên
        assert corr(pcm(out, 0.5), pcm(intro, 0.5)) > 0.9, f"{t.group_display}: voice Intro bị đổi"
        # nửa trên giữ nguyên Intro
        top = "scale=1080:1920,crop=1080:900:0:0,scale=108:90"
        assert mad(gray(out, 1.0, top), gray(intro, 1.0, top)) < 3.0
        # Source đúng ngôn ngữ: khớp nhất với Source cùng nhóm
        o = gray(out, di + SRC_T)
        diffs = {g: mad(o, gray(p, SRC_T)) for g, p in sources.items()}
        best = min(diffs, key=diffs.get)
        assert best == t.group, f"{t.group_display}: Source khớp nhất là {best} ({diffs})"
