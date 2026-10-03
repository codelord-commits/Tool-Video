import json
import shutil
import threading
import time
from pathlib import Path

import psutil
import pytest

from tests import media as M
from vvb.__main__ import main as cli
from vvb.api import make_job
from vvb.batch import BatchRunner, find_unfinished
from vvb.events import EventBus
from vvb.plan import plan_job

pytestmark = pytest.mark.integration


@pytest.fixture
def proj(project_a, tmp_path):
    dst = tmp_path / "proj"
    shutil.copytree(project_a, dst)
    return dst


def run(proj, **kw):
    job = make_job("palm_bottom", project=str(proj), **kw)
    job.preset.run.cache_normalized = False
    job.preset.run.prevent_sleep = False
    job.preset.run.notify_done = False
    plan = plan_job(job)
    assert plan.ok, plan.blockers()
    r = BatchRunner(plan, EventBus(), workers=2)
    return r, r.run()


def test_full_then_skip_then_redo_one(proj):
    r, s = run(proj)
    assert (s.done, s.failed, s.skipped) == (6, 0, 0)
    out = proj / "Output"
    vids = sorted(out.rglob("*.mp4"))
    assert len(vids) == 6 and not list(out.rglob("*.part.*"))
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert len(man["videos"]) == 6 and (out / "manifest.csv").exists() and (out / "preset.json").exists()
    assert find_unfinished(out) is None
    _, s2 = run(proj)
    assert (s2.done, s2.skipped) == (0, 6)
    vids[0].unlink()
    _, s3 = run(proj)
    assert (s3.done, s3.skipped) == (1, 5)


def test_corrupt_clip_others_continue(proj):
    (proj / "Video" / "clip02.mp4").write_bytes(b"garbage" * 100)
    r, s = run(proj)
    assert s.done == 3 and s.failed == 3
    log = (proj / "Output" / "errors.log").read_text(encoding="utf-8")
    assert "clip02" in log


def test_cancel_cleans_up(proj):
    job = make_job("palm_bottom", project=str(proj))
    job.preset.run.cache_normalized = False
    job.preset.run.prevent_sleep = False
    job.preset.run.notify_done = False
    plan = plan_job(job)
    bus = EventBus()
    r = BatchRunner(plan, bus, workers=2)
    started = threading.Event()
    bus.subscribe(lambda e: started.set() if e.type == "task_progress" else None)
    th = threading.Thread(target=r.run)
    th.start()
    assert started.wait(60)
    r.cancel()
    th.join(60)
    assert not th.is_alive()
    assert r.summary.cancelled
    out = proj / "Output"
    assert not list(out.rglob("*.part.*"))
    me = psutil.Process()
    assert not [c for c in me.children(recursive=True) if "ffmpeg" in c.name().lower()]
    assert find_unfinished(out) is not None  # còn việc → resume được


def test_cli_dry_run_and_check(proj, capsys):
    assert cli(["check", "--preset", "palm_bottom", "--project", str(proj)]) == 0
    assert cli(["run", "--preset", "palm_bottom", "--project", str(proj), "--dry-run", "--groups", "arab"]) == 0
    outp = capsys.readouterr().out
    assert "2 video" in outp and "Sẵn sàng" in outp
    assert not (proj / "Output").exists() or not list((proj / "Output").rglob("*.mp4"))


def test_cli_explicit_slots(proj, tmp_path):
    rc = cli(["run", "--preset", "palm_bottom", "--intro", str(proj / "Intro"), "--source", str(proj / "Source"),
              "--pool", str(proj / "Video"), "--outtro", str(proj / "Outtro.mp4"), "--out", str(tmp_path / "O"),
              "--limit", "1", "--no-cache", "--no-sleep-block"])
    assert rc == 0
    assert len(list((tmp_path / "O").rglob("*.mp4"))) == 1


def test_output_same_as_input_blocked(proj):
    job = make_job("palm_bottom", project=str(proj), out_dir=str(proj / "Intro"))
    plan = plan_job(job)
    assert not plan.ok and any("trùng" in b for b in plan.blockers())


def test_missing_folder_blocks(tmp_path):
    job = make_job("palm_bottom", project=str(tmp_path))
    plan = plan_job(job)
    assert not plan.ok
