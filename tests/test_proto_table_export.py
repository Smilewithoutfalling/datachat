"""原型（proto/genie-shell）：预览表全表排序 / 按值筛选（/datasets/{id}/values、/view）与会话导出 HTML（/sessions/{id}/export）。"""
import base64
import os

from fastapi.testclient import TestClient

from app.server.app import create_app
from tests.test_server import H, TOKEN, upload

CSV = "城市,销量,备注\n北京,120,a\n上海,150,\n广州,90,b\n上海,30,c\n北京,,d\n"
PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 16).decode()


def setup(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text(CSV, encoding="utf-8")
    c = TestClient(create_app(str(tmp_path / "home"), TOKEN))
    return c, upload(c, str(p))["id"]


def test_values_counts_full_table(tmp_path):
    c, ds = setup(tmp_path)
    r = c.get(f"/datasets/{ds}/values", params={"table": "df", "col": 0}, headers=H)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["rows"] == 5 and d["distinct"] == 3 and not d["truncated"]
    assert {v["value"]: v["count"] for v in d["values"]} == {"北京": 2, "上海": 2, "广州": 1}
    nulls = c.get(f"/datasets/{ds}/values", params={"table": "df", "col": 1}, headers=H).json()
    assert any(v["value"] is None for v in nulls["values"])


def test_values_errors(tmp_path):
    c, ds = setup(tmp_path)
    assert c.get(f"/datasets/{ds}/values", params={"table": "nope", "col": 0}, headers=H).status_code == 404
    assert c.get(f"/datasets/{ds}/values", params={"table": "df", "col": 9}, headers=H).status_code == 422
    assert c.get(f"/datasets/{ds}/values", params={"table": "df", "col": 0}).status_code == 401


def test_view_filter_sort_numeric_nulls_last(tmp_path):
    c, ds = setup(tmp_path)
    body = {"table": "df", "sort_col": 1, "sort_dir": "desc", "filters": {}, "rows": 10}
    d = c.post(f"/datasets/{ds}/view", json=body, headers=H).json()
    vals = [r[1] for r in d["rows"]]
    assert vals[:4] == ["150.0", "120.0", "90.0", "30.0"] and vals[-1] is None      # 按数值，不按字符串；空值最后
    assert d["matched_rows"] == 5 and d["total_rows"] == 5
    assert d["row_numbers"][0] == 2                                            # 原表行号
    body = {"table": "df", "sort_col": 1, "sort_dir": "asc", "filters": {"0": ["上海"]}, "rows": 10}
    d = c.post(f"/datasets/{ds}/view", json=body, headers=H).json()
    assert d["matched_rows"] == 2 and [r[1] for r in d["rows"]] == ["30.0", "150.0"]
    d = c.post(f"/datasets/{ds}/view", json={"table": "df", "filters": {"2": [None]}}, headers=H).json()
    assert d["matched_rows"] == 1 and d["rows"][0][0] == "上海"               # 按「空」筛选


def test_view_rejects_bad_input(tmp_path):
    c, ds = setup(tmp_path)
    assert c.post(f"/datasets/{ds}/view", json={"table": "df", "filters": {"x": ["a"]}}, headers=H).status_code == 422
    assert c.post(f"/datasets/{ds}/view", json={"table": "df", "rows": 1000}, headers=H).status_code == 422


def test_view_cache_invalidates_when_file_changes(tmp_path):
    c, ds = setup(tmp_path)
    q = {"table": "df", "col": 0}
    assert c.get(f"/datasets/{ds}/values", params=q, headers=H).json()["rows"] == 5
    path = os.path.join(str(tmp_path / "home"), "datasets", ds, "t.csv")
    with open(path, "a", encoding="utf-8") as f:
        f.write("深圳,1,e\n")
    assert c.get(f"/datasets/{ds}/values", params=q, headers=H).json()["rows"] == 6


def test_export_html_escapes_and_validates_png(tmp_path):
    c, ds = setup(tmp_path)
    s = c.post("/sessions", json={"dataset_id": ds}, headers=H).json()
    r = c.post(f"/sessions/{s['id']}/export", params={"download": 1}, json={}, headers=H)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "<script" not in r.text.lower()
    bad = {"charts": {"m": {"0": "data:image/png;base64," + base64.b64encode(b"notpng").decode()}}}
    assert c.post(f"/sessions/{s['id']}/export", params={"download": 1}, json=bad, headers=H).status_code == 400
    ok = {"charts": {"m": {"0": PNG}}}
    assert c.post(f"/sessions/{s['id']}/export", params={"download": 1}, json=ok, headers=H).status_code == 200
    assert c.post("/sessions/nope/export", params={"download": 1}, json={}, headers=H).status_code == 404
