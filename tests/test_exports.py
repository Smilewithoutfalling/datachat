"""阶段 6 收尾：桌面端导出 PNG 落盘（app/server/exports.py、POST /exports/png）和 GET /settings 的 sources。"""
import os

import pytest
from fastapi.testclient import TestClient

from app.server.app import create_app
from app.server.exports import MAX_PNG_BYTES, PNG_MAGIC, ExportError, clean_filename, save_png

TOKEN = "t0ken"
H = {"Authorization": f"Bearer {TOKEN}"}
PNG = PNG_MAGIC + b"\x00" * 32


@pytest.mark.parametrize("raw, want", [
    ("各地区销量.png", "各地区销量"),
    ("各地区销量", "各地区销量"),
    ("a/b\\c:d*e?f\"g<h>i|j", "a_b_c_d_e_f_g_h_i_j"),
    ("gnp\u202eexe", "gnpexe"),                # RLO 删掉
    ("x\x00\x1fy\x7f\x9f", "xy"),
    ("  ..名字..  ", "名字"),
    ("", "图表"),
    (None, "图表"),
    ("...", "图表"),
    ("CON", "_CON"),
    ("lpt1.backup", "_lpt1.backup"),
    ("长" * 80, "长" * 60),
])
def test_clean_filename(raw, want):
    assert clean_filename(raw) == want


def test_save_png_numbers_duplicates_and_never_overwrites(tmp_path):
    d = str(tmp_path / "dl")
    p1 = save_png(d, "图.png", PNG)
    p2 = save_png(d, "图.png", PNG + b"2")
    p3 = save_png(d, "图", PNG + b"3")
    assert [os.path.basename(p) for p in (p1, p2, p3)] == ["图.png", "图 (1).png", "图 (2).png"]
    assert open(p1, "rb").read() == PNG                      # 第一份没被覆盖
    assert all(os.path.dirname(p) == os.path.realpath(d) for p in (p1, p2, p3))


def test_save_png_stays_in_dir(tmp_path):
    d = str(tmp_path / "dl")
    p = save_png(d, "../../evil.png", PNG)
    assert os.path.dirname(p) == os.path.realpath(d) and os.path.basename(p) == "evil.png"
    p = save_png(d, "..\\..\\evil2", PNG)
    assert os.path.dirname(p) == os.path.realpath(d) and os.path.basename(p) == "evil2.png"


def test_save_png_rejects_non_png_and_oversize(tmp_path):
    d = str(tmp_path / "dl")              # 子目录：conftest 的 autouse 夹具会在 tmp_path 下建 charts/
    with pytest.raises(ExportError):
        save_png(d, "x", b"GIF89a....")
    with pytest.raises(ExportError):
        save_png(d, "x", b"")
    with pytest.raises(ExportError):
        save_png(d, "x", PNG_MAGIC + b"\x00" * MAX_PNG_BYTES)
    assert not os.path.exists(d)          # 校验在建目录之前


def test_export_endpoint_desktop_only_and_auth(tmp_path):
    app = create_app(str(tmp_path / "home"), TOKEN)
    c = TestClient(app)
    hdr = {**H, "Content-Type": "image/png"}
    assert c.post("/exports/png?filename=a", content=PNG).status_code == 401
    assert c.post("/exports/png?filename=a", content=PNG, headers=hdr).status_code == 404     # 浏览器模式不开
    d = tmp_path / "dl"
    app.state.export_dir = str(d)
    r = c.post("/exports/png?filename=" + "各地区销量.png", content=PNG, headers=hdr)
    assert r.status_code == 200 and r.json()["path"] == os.path.join(os.path.realpath(d), "各地区销量.png")
    assert open(r.json()["path"], "rb").read() == PNG
    assert c.post("/exports/png?filename=a", content=b"not a png", headers=hdr).status_code == 400
    assert c.post("/exports/png?filename=a", content=PNG,
                  headers={**hdr, "Content-Length": str(MAX_PNG_BYTES + 1)}).status_code == 413
    assert sorted(os.listdir(d)) == ["各地区销量.png"]


def test_desktop_flag_sets_export_dir(monkeypatch, tmp_path):
    from app.server.exports import default_export_dir
    monkeypatch.setenv("DATACHAT_EXPORT_DIR", str(tmp_path / "x"))
    assert default_export_dir() == str(tmp_path / "x")
    monkeypatch.delenv("DATACHAT_EXPORT_DIR")
    if os.name != "nt":
        assert default_export_dir() == os.path.join(os.path.expanduser("~"), "Downloads")


def test_settings_sources(tmp_path, monkeypatch):
    for k in ("DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL", "DATACHAT_LLM_TIMEOUT"):
        monkeypatch.delenv(k, raising=False)
    c = TestClient(create_app(str(tmp_path / "home"), TOKEN))
    s = c.get("/settings", headers=H).json()
    assert s["sources"] == {"model": "default", "base_url": "default", "timeout": "default"}
    assert s["base_url"] == "https://api.deepseek.com/v1"
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://gw.example/v1")
    s = c.get("/settings", headers=H).json()
    assert s["sources"]["base_url"] == "env" and s["base_url"] == "https://gw.example/v1"
    s = c.put("/settings", json={"base_url": "https://mine.example/v1", "model": "qwen"}, headers=H).json()
    assert s["sources"] == {"model": "settings", "base_url": "settings", "timeout": "default"}
    s = c.put("/settings", json={"base_url": ""}, headers=H).json()        # 清空 → 回到环境变量
    assert s["sources"]["base_url"] == "env"
