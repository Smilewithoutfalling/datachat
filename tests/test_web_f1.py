"""阶段 5 F1：数据集预览、会话改名、设置里的超时。全部用假模型 / 不调模型。"""
import pytest
from fastapi.testclient import TestClient

from app.server.app import PREVIEW_CELL_MAX, PREVIEW_MAX_ROWS, create_app
from tests.test_server import H, TOKEN, upload


@pytest.fixture
def c(tmp_path):
    return TestClient(create_app(str(tmp_path / "home"), TOKEN))


def write(path, text, encoding="utf-8"):
    path.write_bytes(text.encode(encoding))
    return str(path)


# ---------------------------------------------------------------- 预览
def test_preview_single_table_matches_analysis_read(c, sample_path):
    import pandas as pd
    from app.tools.csv_io import read_csv
    ds = upload(c, sample_path)
    r = c.get(f"/datasets/{ds['id']}/preview", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] == 20 and body["dicts"] == []
    [t] = body["tables"]
    df = read_csv(sample_path)
    assert t["columns"] == [str(x) for x in df.columns]
    assert t["total_rows"] == len(df) and t["total_columns"] == len(df.columns)
    assert len(t["rows"]) == min(20, len(df))
    # 与分析时读到的逐格一致（缺失 → None，其余字符串）
    exp = [[None if pd.isna(v) else str(v) for v in row] for row in df.head(20).itertuples(index=False, name=None)]
    assert t["rows"] == exp


def test_preview_rows_bounds_and_auth(c, sample_path):
    ds = upload(c, sample_path)
    url = f"/datasets/{ds['id']}/preview"
    assert len(c.get(url + "?rows=3", headers=H).json()["tables"][0]["rows"]) == 3
    for bad in (0, -1, PREVIEW_MAX_ROWS + 1):
        assert c.get(f"{url}?rows={bad}", headers=H).status_code == 400
    assert c.get(url).status_code == 401
    assert c.get("/datasets/nope/preview", headers=H).status_code == 404


def test_preview_cells_missing_long_and_gbk(c, tmp_path):
    long = "x" * (PREVIEW_CELL_MAX + 50)
    p = write(tmp_path / "t.csv", f"名称,数量,备注\n苹果,,<img src=x onerror=alert(1)>\n梨,3,{long}\n", "gbk")
    t = c.get(f"/datasets/{upload(c, p)['id']}/preview", headers=H).json()["tables"][0]
    assert t["encoding"].lower() in ("gbk", "gb18030", "gb2312")
    assert t["columns"] == ["名称", "数量", "备注"]
    assert t["rows"][0] == ["苹果", None, "<img src=x onerror=alert(1)>"]    # 原样字符串，前端按文本渲染
    assert t["rows"][1][2] == "x" * PREVIEW_CELL_MAX + "…"
    assert t["dtypes"][1] == "float64"


def test_preview_multi_table_dict_and_one_broken(c, tmp_path):
    a = write(tmp_path / "orders.csv", "id,amt\n1,2\n")
    b = write(tmp_path / "users.csv", "")                        # 空文件：读失败，只影响这一张
    d = write(tmp_path / "orders.dict.csv", "列,含义\nid,编号\n")
    body = c.get(f"/datasets/{upload(c, a, b, d)['id']}/preview", headers=H).json()
    assert body["dicts"] == ["orders.dict.csv"]
    orders, users = body["tables"]
    assert orders["name"] == "orders" and orders["rows"] == [["1", "2"]]
    assert users["name"] == "users" and "error" in users and "rows" not in users


# ---------------------------------------------------------------- 会话改名
def test_session_rename(c, sample_path):
    ds = upload(c, sample_path)
    s = c.post("/sessions", json={"dataset_id": ds["id"]}, headers=H).json()
    r = c.patch(f"/sessions/{s['id']}", json={"title": "  月度\u202e销量\x07 "}, headers=H)
    assert r.status_code == 200 and r.json()["title"] == "月度销量"
    assert c.get(f"/sessions/{s['id']}", headers=H).json()["title"] == "月度销量"
    assert c.patch(f"/sessions/{s['id']}", json={"title": "x" * 201}, headers=H).status_code == 422
    assert c.patch("/sessions/nope", json={"title": "a"}, headers=H).status_code == 404
    assert c.patch(f"/sessions/{s['id']}", json={"title": "a"}).status_code == 401


# ---------------------------------------------------------------- 设置：超时
def test_settings_timeout(c, monkeypatch):
    monkeypatch.delenv("DATACHAT_LLM_TIMEOUT", raising=False)
    assert c.get("/settings", headers=H).json()["timeout"] == 60.0
    assert c.put("/settings", json={"timeout": 120}, headers=H).json()["timeout"] == 120.0
    for bad in (1, 601, "abc"):
        assert c.put("/settings", json={"timeout": bad}, headers=H).status_code == 422
    assert c.get("/settings", headers=H).json()["timeout"] == 120.0
    # 只改 model 不动 timeout
    r = c.put("/settings", json={"model": "m"}, headers=H).json()
    assert r["timeout"] == 120.0 and r["model"] == "m"


def test_settings_bad_stored_timeout_falls_back(tmp_path, monkeypatch):
    from app.server.db import Setting, make_sessionmaker
    monkeypatch.delenv("DATACHAT_LLM_TIMEOUT", raising=False)
    home = str(tmp_path / "home")
    c = TestClient(create_app(home, TOKEN))
    with make_sessionmaker(f"{home}/datachat.db")() as db:
        db.add(Setting(key="timeout", value="oops"))
        db.commit()
    assert c.get("/settings", headers=H).json()["timeout"] == 60.0
