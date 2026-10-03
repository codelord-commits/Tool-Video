"""Dạng job B–G + các chế độ duration/audio/transition — chỉ bằng preset."""
import shutil
from pathlib import Path

import pytest

from tests import media as M
from tests.integration.test_render_a import close, hexrgb, pixel
from vvb.api import make_job
from vvb.batch import BatchRunner
from vvb.events import EventBus
from vvb.plan import plan_job
from vvb.preset_io import load_preset, preset_to_dict, validate_preset_dict
from vvb.probe import probe

pytestmark = pytest.mark.integration

BODY = "0x404040"


@pytest.fixture(scope="module")
def body_proj(tmp_path_factory):
    root = tmp_path_factory.mktemp("body")
    for g in ["Arab", "French"]:
        src = M.make(f"B_body_{g}.mp4", lambda p: M.solid(p, BODY, 6.0, 1080, 1920, freq=500))
        (root / "Body").mkdir(exist_ok=True)
        shutil.copyfile(src, root / "Body" / f"{g}.mp4")
    pool = M.make("B_pool.mp4", lambda p: M.solid(p, M.POOL, 4.0, 720, 1280, freq=300))
    for d in ["Hook", "Insert", "Video"]:
        (root / d).mkdir(exist_ok=True)
        shutil.copyfile(pool, root / d / "h1.mp4")
    return root


def render(preset, root, out):
    job = make_job(preset, project=str(root), out_dir=str(out))
    r = job.preset.run
    r.cache_normalized, r.prevent_sleep, r.notify_done = False, False, False
    plan = plan_job(job)
    assert plan.ok, plan.blockers()
    s = BatchRunner(plan, EventBus(), workers=2).run()
    assert s.failed == 0, (out / "errors.log").read_text(encoding="utf-8") if (out / "errors.log").exists() else ""
    vids = sorted(out.rglob("*.mp4"))
    assert vids
    return vids, plan


def dur(p):
    return probe(p, use_cache=False).video_duration


TOL = 1 / 30 + 0.05


def test_B_hook3s(body_proj, tmp_path):
    vids, _ = render("hook3s", body_proj, tmp_path / "o")
    assert len(vids) == 2
    assert abs(dur(vids[0]) - 6.0) <= TOL
    assert close(pixel(vids[0], 1.0, 500, 500), hexrgb(M.POOL))
    assert close(pixel(vids[0], 4.5, 500, 500), hexrgb(BODY[2:]))


def test_C_hook_keep_voice(body_proj, tmp_path):
    vids, _ = render("hook_keep_voice", body_proj, tmp_path / "o")
    assert abs(dur(vids[0]) - 6.0) <= TOL
    assert close(pixel(vids[0], 1.0, 500, 500), hexrgb(M.POOL))
    assert close(pixel(vids[0], 4.0, 500, 500), hexrgb(BODY[2:]))


def test_D_top_half(project_a, tmp_path):
    vids, _ = render("top_half", project_a, tmp_path / "o")
    v = vids[0]
    assert close(pixel(v, 1.0, 500, 300), hexrgb(M.POOL))
    assert close(pixel(v, 1.0, 500, 1600), hexrgb(M.BOTTOM))
    assert abs(dur(v) - 4.5) <= TOL


def test_E_insert_middle_with_fades(body_proj, tmp_path):
    vids, _ = render("insert_middle", body_proj, tmp_path / "o")
    assert abs(dur(vids[0]) - (5 + 3 + 1 - 0.6)) <= TOL
    assert close(pixel(vids[0], 6.0, 500, 500), hexrgb(M.POOL))


def test_F_concat_only(project_a, tmp_path):
    vids, plan = render("concat_only", project_a, tmp_path / "o")
    assert len(vids) == 3 and abs(dur(vids[0]) - 4.5) <= TOL


def test_G_pip(body_proj, tmp_path):
    vids, _ = render("pip_corner", body_proj, tmp_path / "o")
    v = vids[0]
    # pip ô 378×672 ở góc dưới phải, lề 43px
    assert close(pixel(v, 1.0, 1080 - 43 - 190, 1920 - 43 - 336), hexrgb(M.POOL))
    assert close(pixel(v, 1.0, 200, 200), hexrgb(BODY[2:]))
    assert close(pixel(v, 1.0, 1080 - 43 - 4, 1920 - 43 - 4), hexrgb(BODY[2:]), tol=45)  # góc bo


def _custom(base: str, **seg_updates):
    d = preset_to_dict(load_preset(base))
    d["timeline"][0].update(seg_updates)
    return validate_preset_dict(d)


@pytest.mark.parametrize("mode", ["match_base_freeze", "match_base_boomerang", "match_base_speed"])
def test_duration_modes_short_clip(project_a, tmp_path, mode):
    p = _custom("palm_bottom", duration_mode=mode)
    vids, _ = render(p, project_a, tmp_path / "o")
    for v in vids:
        assert abs(dur(v) - 4.5) <= TOL


def test_match_clip_extends_base(project_a, tmp_path):
    p = _custom("palm_bottom", duration_mode="match_clip")
    p.combine.limit = 1  # clip01 dài 3s > intro 2s
    vids, _ = render(p, project_a, tmp_path / "o")
    assert abs(dur(vids[0]) - (3.0 + 1.5 + 1.0)) <= TOL


@pytest.mark.parametrize("amode", ["overlay", "mix", "mute"])
def test_audio_modes(project_a, tmp_path, amode):
    p = _custom("palm_bottom", audio={"mode": amode, "base_volume": 1.0, "overlay_volume": 0.5})
    p.combine.limit = 1
    vids, _ = render(p, project_a, tmp_path / "o")
    assert probe(vids[0], use_cache=False).has_audio


def test_custom_region_contain_blur_anchor(project_a, tmp_path):
    p = _custom("palm_bottom", region={"preset": None, "x": 0.1, "y": 0.6, "w": 0.8, "h": 0.3, "fit": "contain",
                                       "background": "blur", "feather": 10, "opacity": 0.9})
    p.combine.limit = 1
    vids, _ = render(p, project_a, tmp_path / "o")
    assert abs(dur(vids[0]) - 4.5) <= TOL


def test_blank_and_crossfade(project_a, tmp_path):
    d = preset_to_dict(load_preset("concat_only"))
    d["timeline"].append({"kind": "blank", "duration": 1.0, "color": "#FF00FF",
                          "transition_in": {"type": "fade_black", "duration": 0.4}})
    d["timeline"][1]["transition_in"] = {"type": "crossfade", "duration": 0.5}
    p = validate_preset_dict(d)
    p.combine.limit = 1
    vids, _ = render(p, project_a, tmp_path / "o")
    assert abs(dur(vids[0]) - (2 + 1.5 + 1 + 1 - 0.5 - 0.4)) <= TOL


def test_edge_media_in_pool(fx, project_a, tmp_path):
    """Pool chứa đủ loại media lạ: xoay, VFR, lẻ, mono 48k, ngang, rất ngắn, tên có dấu, 50fps, không audio."""
    root = tmp_path / "proj"
    shutil.copytree(project_a, root)
    shutil.rmtree(root / "Video")
    (root / "Video").mkdir()
    for k in ["rotated", "vfr", "odd", "mono48", "landscape", "short", "accent", "fps50", "no_audio"]:
        shutil.copyfile(fx[k], root / "Video" / fx[k].name)
    p = load_preset("palm_bottom")
    p.combine.limit = None
    vids, _ = render(p, root, tmp_path / "o")
    assert len(vids) == 3 * 9
    for v in vids[:9]:
        m = probe(v, use_cache=False)
        assert (m.width, m.height) == (1080, 1920) and m.has_audio
        assert abs(m.video_duration - 4.5) <= TOL


def test_images_in_pool(project_a, tmp_path):
    root = tmp_path / "proj"
    shutil.copytree(project_a, root)
    img = root / "Video" / "still.png"
    M.ff("-f", "lavfi", "-i", "color=c=0xD02020:s=800x800", "-frames:v", "1", str(img))
    d = preset_to_dict(load_preset("palm_bottom"))
    d["slots"]["pool"]["allow_images"] = True
    p = validate_preset_dict(d)
    p.combine.limit = None
    vids, _ = render(p, root, tmp_path / "o")
    still = [v for v in vids if "still" in v.name]
    assert still and abs(dur(still[0]) - 4.5) <= TOL
    assert close(pixel(still[0], 1.0, 500, 1600), hexrgb(M.POOL))


def test_overlays_music_normalize_thumbs(project_a, tmp_path):
    logo = tmp_path / "logo.png"
    M.ff("-f", "lavfi", "-i", "color=c=0x00FF00@0.8:s=200x100,format=rgba", "-frames:v", "1", str(logo))
    csvf = tmp_path / "texts.csv"
    csvf.write_text("group,text\nArab,Xin chào 'Ả Rập'\nFrench,Bonjour: à tous\n", encoding="utf-8")
    music = tmp_path / "music.m4a"
    M.ff("-f", "lavfi", "-i", "sine=frequency=200:duration=2", "-c:a", "aac", str(music))
    d = preset_to_dict(load_preset("palm_bottom"))
    d["output"].update({"watermark": {"path": str(logo), "x": 0.05, "y": 0.05, "w": 0.2},
                        "text": {"csv": str(csvf), "y": 0.1}, "thumbnails": True})
    d["audio"].update({"normalize_lufs": -14, "normalize_final": True, "fade_in": 0.3, "fade_out": 0.3,
                       "music": {"path": str(music), "volume": 0.3, "ducking": True}})
    p = validate_preset_dict(d)
    p.combine.limit = 2
    vids, _ = render(p, project_a, tmp_path / "o")
    assert abs(dur(vids[0]) - 4.5) <= TOL
    assert close(pixel(vids[0], 1.0, 54 + 40, 96 + 20), (0, 255, 0), tol=70)
    assert list((tmp_path / "o").rglob("*.jpg"))


def test_images_ken_burns(project_a, tmp_path):
    root = tmp_path / "proj"
    shutil.copytree(project_a, root)
    M.ff("-f", "lavfi", "-i", "testsrc2=s=800x800", "-frames:v", "1", str(root / "Video" / "still.png"))
    d = preset_to_dict(load_preset("palm_bottom"))
    d["slots"]["pool"].update({"allow_images": True, "ken_burns": True})
    p = validate_preset_dict(d)
    vids, _ = render(p, root, tmp_path / "o")
    still = [v for v in vids if "still" in v.name]
    assert still and abs(dur(still[0]) - 4.5) <= TOL


def test_prune_cache(tmp_path):
    import os
    from vvb.renderer import prune_cache
    for i in range(5):
        f = tmp_path / f"{i}.mov"
        f.write_bytes(b"x" * 1024 * 1024)
        os.utime(f, (1000 + i, 1000 + i))
    assert prune_cache(tmp_path, limit_gb=2.5 / 1024) == 3
    assert sorted(f.name for f in tmp_path.glob("*.mov")) == ["3.mov", "4.mov"]
