import os

import pytest

from vvb import batch


def test_atomic_write_retries_transient_lock(tmp_path, monkeypatch):
    real = os.replace
    calls = {"n": 0}

    def flaky(a, b):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(5, "Access is denied")
        return real(a, b)

    monkeypatch.setattr(batch.os, "replace", flaky)
    batch._atomic_write(tmp_path / "job.json", "{}")
    assert (tmp_path / "job.json").read_text() == "{}" and calls["n"] == 3
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_write_gives_up(tmp_path, monkeypatch):
    monkeypatch.setattr(batch.os, "replace", lambda a, b: (_ for _ in ()).throw(PermissionError(5, "x")))
    monkeypatch.setattr(batch.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        batch._atomic_write(tmp_path / "job.json", "{}")
    assert not list(tmp_path.glob("*.tmp"))
