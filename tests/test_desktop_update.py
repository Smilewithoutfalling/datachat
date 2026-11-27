"""阶段 6 D3（phase6-desktop.md §4，#149）：桌面壳 → 后端 → 前端的「有新版本」通道。"""
from fastapi.testclient import TestClient

from app.server.app import create_app
from tests.test_server import H, TOKEN


def _c(tmp_path):
    return TestClient(create_app(str(tmp_path / "home"), TOKEN))


def test_desktop_update_needs_token(tmp_path):
    c = _c(tmp_path)
    assert c.get("/desktop/update").status_code == 401
    assert c.put("/desktop/update", json={"version": "0.1.1"}).status_code == 401


def test_desktop_update_roundtrip_in_memory(tmp_path):
    c = _c(tmp_path)
    assert c.get("/desktop/update", headers=H).json() == {"available": None}
    r = c.put("/desktop/update", json={"version": "0.1.1", "notes": "修复若干问题"}, headers=H)
    assert r.status_code == 200
    assert c.get("/desktop/update", headers=H).json() == {"available": {"version": "0.1.1", "notes": "修复若干问题"}}
    # 只在内存里：重启（新建 app）后清空
    assert _c(tmp_path).get("/desktop/update", headers=H).json() == {"available": None}


def test_desktop_update_rejects_odd_version(tmp_path):
    c = _c(tmp_path)
    for v in ("", "0.1.1<script>", "x" * 65):
        assert c.put("/desktop/update", json={"version": v}, headers=H).status_code == 422, v
