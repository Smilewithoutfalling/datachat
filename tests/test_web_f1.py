"""阶段 5 F1 / F1.1：数据集详情里的预览（合并后每个文件只读一遍）、会话改名、设置里的超时。不调模型。"""
import os

import pytest
from fastapi.testclient import TestClient

from app.server.app import PREVIEW_CELL_MAX, PREVIEW_DEFAULT_ROWS, PREVIEW_MAX_ROWS, create_app
from tests.test_server import H, TOKEN, upload


@pytest.fixture
def c(tmp_path):
    return TestClient(create_app(str(tmp_path / "home"), TOKEN))


def write(path, text, encoding="utf-8"):
    path.write_bytes(text.encode(encoding))
    return str(path)


# ---------------------------------------------------------------- 预览（F1.1 起并入 GET /datasets/{id}?rows=）
def detail(c, ds_id, rows=20):
    r = c.get(f"/datasets/{ds_id}" + (f"?rows={rows}" if rows is not None else ""), headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def test_preview_single_table_matches_analysis_read(c, sample_path):
    import pandas as pd
    from app.tools.csv_io import read_csv
    ds = upload(c, sample_path)
    body = detail(c, ds["id"])
    p = body["preview"]
    assert p["rows"] == 20 and p["dicts"] == []
    [t] = p["tables"]
    assert t["name"] == "df" and t["filename"] == "sample.csv"      # 单表沿用 "df"（与 prompt 里的变量名一致）
    df = read_csv(sample_path)
    assert t["columns"] == [str(x) for x in df.columns]
    assert t["total_rows"] == len(df) and t["total_columns"] == len(df.columns)
    exp = [[None if pd.isna(v) else str(v) for v in row] for row in df.head(20).itertuples(index=False, name=None)]
    assert t["rows"] == exp
    assert t["bidi_stripped"] == 0 and t["truncated_cells"] == 0
    assert body["tables"] == {"df": t["columns"]}


def test_upload_response_carries_preview_and_plain_detail_does_not(c, sample_path):
    ds = upload(c, sample_path)
    p = ds["preview"]                                          # 上传后不用再发请求
    assert p["rows"] == PREVIEW_DEFAULT_ROWS and p["tables"][0]["rows"] == detail(c, ds["id"])["preview"]["tables"][0]["rows"]
    assert "preview" not in detail(c, ds["id"], rows=None)     # 不传 rows 不带预览
    assert "preview" not in c.get("/datasets", headers=H).json()[0]


def test_preview_rows_bounds_and_auth(c, sample_path):
    ds = upload(c, sample_path)
    assert len(detail(c, ds["id"], rows=3)["preview"]["tables"][0]["rows"]) == 3
    for bad in ("0", "-1", str(PREVIEW_MAX_ROWS + 1), "abc", "1.5"):   # 越界与非整数同为 422
        assert c.get(f"/datasets/{ds['id']}?rows={bad}", headers=H).status_code == 422, bad
    assert c.get(f"/datasets/{ds['id']}?rows=3").status_code == 401
    assert c.get("/datasets/nope?rows=3", headers=H).status_code == 404
    assert c.get(f"/datasets/{ds['id']}/preview", headers=H).status_code == 404     # 旧接口已删


def test_preview_cells_missing_long_bidi_and_gbk(c, tmp_path):
    long = "x" * (PREVIEW_CELL_MAX + 50)
    text = (f"名称,数量,备注\u202e列\n苹果,,<img src=x onerror=alert(1)>\n"
            f"梨,3,{long}\n\u202egnp.exe\u200f,4,\u2066a\u2069\n")
    p = write(tmp_path / "t.csv", text, "utf-8")
    t = c.get(f"/datasets/{upload(c, p)['id']}?rows=20", headers=H).json()["preview"]["tables"][0]
    assert t["columns"] == ["名称", "数量", "备注列"]                      # 表头也清方向控制符
    assert t["rows"][0] == ["苹果", None, "<img src=x onerror=alert(1)>"]    # 原样字符串，前端按文本渲染
    assert t["rows"][1][2] == "x" * PREVIEW_CELL_MAX + "…"
    assert t["rows"][2] == ["gnp.exe", "4.0", "a"]   # 数量列有缺失 → float64，与分析时一致
    assert t["truncated_cells"] == 1 and t["bidi_stripped"] == 5
    assert t["dtypes"][1] == "float64"


def test_preview_gbk(c, tmp_path):
    p = write(tmp_path / "g.csv", "名称,数量\n苹果,1\n", "gbk")
    t = detail(c, upload(c, p)["id"])["preview"]["tables"][0]
    assert t["encoding"].lower() in ("gbk", "gb18030", "gb2312") and t["rows"] == [["苹果", "1"]]


def test_multi_table_one_broken_others_intact(c, tmp_path):
    a = write(tmp_path / "orders.csv", "id,amt\n1,2\n")
    b = write(tmp_path / "users.csv", "")                        # 空文件：读失败，只影响这一张
    d = write(tmp_path / "orders.dict.csv", "列,含义\nid,编号\n")
    body = detail(c, upload(c, a, b, d)["id"])
    assert body["preview"]["dicts"] == ["orders.dict.csv"]
    orders, users = body["preview"]["tables"]
    assert orders["name"] == "orders" and orders["rows"] == [["1", "2"]]
    assert users["name"] == "users" and "error" in users and "rows" not in users
    assert body["tables"] == {"orders": ["id", "amt"]}           # 好表的列名仍在（F1 之前整体失败就没有 tables）
    assert "users.csv" in body["error"]                           # 顶层也报：分析时 load_data 会整体失败
    assert body["summary"] == "2 张表：orders 1×2（utf-8），users 读取失败"


def test_table_names_and_order_follow_analysis_path(c, tmp_path):
    """表名、顺序与分析路径（table_paths / load_data）一致：B.csv + a.csv → [B, a]（按表名、大小写敏感）。"""
    from app.tools.dataset import load_data
    b = write(tmp_path / "B.csv", "x\n1\n")
    a = write(tmp_path / "a.csv", "y,z\n2,3\n")
    ds = upload(c, b, a)
    body = detail(c, ds["id"])
    names = [t["name"] for t in body["preview"]["tables"]]
    assert names == ["B", "a"] == list(body["tables"])
    folder = os.path.join(c.app.state.home, "datasets", ds["id"])
    data, _ = load_data(folder)
    assert list(data) == names and {k: [str(x) for x in v.columns] for k, v in data.items()} == body["tables"]



# ---------------------------------------------------------------- 会话改名
def test_session_rename(c, sample_path):
    ds = upload(c, sample_path)
    s = c.post("/sessions", json={"dataset_id": ds["id"]}, headers=H).json()
    r = c.patch(f"/sessions/{s['id']}", json={"title": "  月\u200f度\u202e销量\x07 "}, headers=H)
    assert r.status_code == 200 and r.json()["title"] == "月度销量"
    got = c.get(f"/sessions/{s['id']}", headers=H).json()
    assert got["title"] == "月度销量"
    assert got["updated_at"] == s["updated_at"]          # 改名不动"最近分析时间"排序（db.py 注释）
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
