import pytest

from vvb.ffmpeg import check_ffmpeg, find_ffmpeg
from vvb.probe import ProbeError, probe

pytestmark = pytest.mark.integration


def test_ffmpeg_ok():
    assert check_ffmpeg() == []
    assert "libx264" in find_ffmpeg().encoders
    assert "xfade" in find_ffmpeg().filters


def test_basic(fx):
    m = probe(fx["basic"])
    assert (m.width, m.height) == (1080, 1920)
    assert m.fps == 30 and not m.vfr and m.has_audio
    assert abs(m.video_duration - 2.0) < 0.05


def test_no_audio(fx):
    assert not probe(fx["no_audio"]).has_audio


def test_rotated(fx):
    m = probe(fx["rotated"])
    assert m.rotation in (90, 270)
    assert (m.width, m.height) == (360, 640)


def test_vfr(fx):
    assert probe(fx["vfr"]).vfr


def test_odd(fx):
    m = probe(fx["odd"])
    assert (m.width, m.height) == (1079, 1919)
    assert any("lẻ" in w for w in m.warnings)


def test_mono48(fx):
    m = probe(fx["mono48"])
    assert m.audio_channels == 1 and m.audio_rate == 48000


def test_short(fx):
    m = probe(fx["short"])
    assert m.video_duration < 0.5 and any("ngắn" in w for w in m.warnings)


def test_corrupt(fx):
    with pytest.raises(ProbeError):
        probe(fx["corrupt"])


def test_accent_name(fx):
    assert probe(fx["accent"]).has_audio


def test_cache(fx):
    assert probe(fx["basic"]) is probe(fx["basic"])
