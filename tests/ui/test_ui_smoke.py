"""Smoke test giao diện bằng Playwright: chọn dự án → ghép → kéo vùng → chạy → hoàn tất."""
import shutil
import socket
import threading
import time
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")
pytestmark = [pytest.mark.ui, pytest.mark.integration]

TOKEN = "ui-test"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    import uvicorn
    from vvb import defaults as D
    home = tmp_path_factory.mktemp("home")
    D.USER_PRESET_DIR = home / "presets"
    D.SETTINGS_FILE = home / "settings.json"
    from web.server import create_app
    port = _free_port()
    app = create_app(TOKEN, {f"127.0.0.1:{port}"})
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    th.join(5)


@pytest.fixture
def page(server):
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(f"{server}/?t={TOKEN}")
        pg.wait_for_function("window.Alpine && Alpine.$data(document.body).ready")
        yield pg
        assert not errors, errors
        b.close()


def test_full_flow(page, project_a, tmp_path):
    proj = tmp_path / "proj"
    shutil.copytree(project_a, proj)
    # chọn thư mục dự án qua hộp duyệt (gõ đường dẫn)
    page.get_by_role("button", name="Chọn thư mục").first.click()
    box = page.get_by_role("dialog")
    box.get_by_placeholder("Dán đường dẫn").fill(str(proj))
    box.get_by_role("button", name="Mở", exact=True).click()
    page.wait_for_timeout(300)
    box.get_by_role("button", name="Chọn thư mục này").click()
    page.wait_for_function("Alpine.$data(document.body).full?.ok === true", timeout=90000)
    assert "3 nhóm × 2 clip = 6 video" in page.locator(".run-summary .big").inner_text()

    # preview đã render + kéo cạnh trên vùng thay (preset bottom → đổi split)
    page.wait_for_function("Alpine.$data(document.body).pv.url !== ''", timeout=90000)
    region = page.locator(".r-box.region")
    region.click()
    handle = region.locator(".h-n")
    hb = handle.bounding_box()
    page.mouse.move(hb["x"] + 6, hb["y"] + 6)
    page.mouse.down()
    page.mouse.move(hb["x"] + 6, hb["y"] - 60, steps=8)
    page.mouse.up()
    split = page.evaluate("Alpine.$data(document.body).preset.timeline[0].region.split")
    assert split < 0.5
    assert page.locator(".dot").is_visible()  # dấu chưa lưu

    # bàn phím: dịch vùng bảo vệ
    page.locator(".r-box.protect").focus()
    y0 = page.evaluate("Alpine.$data(document.body).preset.timeline[0].protect[0].y")
    page.keyboard.press("Shift+ArrowDown")
    assert page.evaluate("Alpine.$data(document.body).preset.timeline[0].protect[0].y") > y0

    # đổi tab tuỳ chọn → Output
    page.get_by_role("tab", name="Output").click()
    assert page.get_by_text("Độ phân giải").first.is_visible()

    # chạy
    page.wait_for_function("Alpine.$data(document.body).canStart", timeout=90000)
    page.get_by_role("button", name="Bắt đầu").click()
    page.wait_for_selector("#done-title", timeout=180000)
    assert page.locator(".modal").get_by_text("Thành công").is_visible()
    assert len(list((proj / "Output").rglob("*.mp4"))) == 6


def test_theme_and_lang(page):
    page.get_by_role("button", name="Đổi giao diện sáng/tối").click()
    page.get_by_role("menuitemradio", name="Sáng").click()
    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    page.get_by_role("button", name="Ngôn ngữ").click()
    page.get_by_role("menuitemradio", name="English").click()
    page.wait_for_timeout(200)
    assert page.get_by_role("button", name="Start").count() == 1
    page.get_by_role("button", name="Language").click()
    page.get_by_role("menuitemradio", name="Tiếng Việt").click()
