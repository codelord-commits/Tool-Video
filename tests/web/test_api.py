import time

import pytest
from fastapi.testclient import TestClient

from vvb.preset_io import load_preset, preset_to_dict
from web.server import create_app

TOKEN = "test-token"
HOST = "testserver"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from vvb import defaults as D
    monkeypatch.setattr(D, "USER_PRESET_DIR", tmp_path / "presets")
    monkeypatch.setattr(D, "SETTINGS_FILE", tmp_path / "settings.json")
    app = create_app(TOKEN, {HOST})
    c = TestClient(app)
    c.headers["x-vvb-token"] = TOKEN
    return c


def body(project, **kw):
    return {"preset": preset_to_dict(load_preset("palm_bottom")), "preset_name": "palm_bottom",
            "paths": {"intro": str(project / "Intro"), "source": str(project / "Source"),
                      "pool": str(project / "Video"), "outtro": str(project / "Outtro.mp4")}, **kw}


def test_requires_token():
    c = TestClient(create_app(TOKEN, {HOST}))
    assert c.get("/api/presets").status_code == 401
    assert c.get("/").status_code == 401
    r = c.get(f"/?t={TOKEN}", follow_redirects=False)
    assert r.status_code == 303 and "vvb_token" in r.headers["set-cookie"]


def test_bad_host_and_origin(client):
    assert client.get("/api/presets", headers={"host": "evil.com"}).status_code == 403
    assert client.get("/api/presets", headers={"origin": "http://evil.com"}).status_code == 403


def test_fs(client, tmp_path):
    (tmp_path / "A").mkdir()
    (tmp_path / "x.mp4").write_bytes(b"1")
    (tmp_path / "Thumbs.db").write_bytes(b"1")
    d = client.get("/api/fs/list", params={"path": str(tmp_path)}).json()
    assert [x["name"] for x in d["dirs"]] == ["A"] and [x["name"] for x in d["files"]] == ["x.mp4"]
    assert client.get("/api/fs/roots").status_code == 200


def test_presets_crud(client):
    lst = client.get("/api/presets").json()
    assert any(p["id"] == "palm_bottom" for p in lst)
    p = client.get("/api/presets/palm_bottom").json()
    assert p["builtin"]
    p["preset"]["name"] = "Bản của tôi"
    r = client.put("/api/presets/ban_cua_toi", json={"preset": p["preset"]})
    assert r.status_code == 200
    assert client.get("/api/presets/ban_cua_toi").json()["builtin"] is False
    bad = dict(p["preset"])
    bad["timeline"] = []
    v = client.post("/api/presets/validate", json={"preset": bad}).json()
    assert not v["ok"]
    assert client.delete("/api/presets/ban_cua_toi").status_code == 200
    assert client.delete("/api/presets/palm_bottom").status_code == 400
    assert "properties" in client.get("/api/schema").json()


@pytest.mark.integration
def test_plan_preview_job(client, project_a, tmp_path):
    r = client.post("/api/project/resolve", json={"preset": body(project_a)["preset"], "project": str(project_a)})
    assert set(r.json()["paths"]) == {"intro", "source", "pool", "outtro"}
    q = client.post("/api/plan", json=body(project_a, out_dir=str(tmp_path / "O"))).json()
    assert q["count"] == 6 and q["match"]["rows"][0]["cells"]["intro"]["status"] == "ok"
    q2 = client.post("/api/plan", json=body(project_a, out_dir=str(tmp_path / "O"), probe=True)).json()
    assert q2["ok"] and q2["total_duration"] > 0
    f = client.post("/api/preview/frame", json=body(project_a, group="French", clip="clip01", t=0.5))
    assert f.status_code == 200 and f.content[:4] == b"\x89PNG"
    assert float(f.headers["x-duration"]) == pytest.approx(2.0, abs=0.05)
    bf = client.post("/api/preview/frame", json=body(project_a, before=True))
    assert bf.status_code == 200
    s = client.post("/api/jobs/start", json=body(project_a, out_dir=str(tmp_path / "O"), clips=["clip01"]))
    assert s.status_code == 200, s.text
    for _ in range(240):
        cur = client.get("/api/jobs/current").json()
        if cur["state"] in ("done", "cancelled", "error"):
            break
        time.sleep(0.5)
    assert cur["state"] == "done" and cur["summary"]["done"] == 3
    assert any("Xong" in l["msg"] for l in cur["logs"])
