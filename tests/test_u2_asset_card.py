"""阶段 7.6 U2：数据资产卡的概要字段（GET /datasets/{id} 的 profile）。不调模型。

字段由这里和前端 vitest（ui/web/src/views/u2-asset-card.test.tsx）双向钉住，契约文件是
ui/web/src/fixtures/asset_card.json：这里断言接口返回与它逐字相等，前端断言卡片上的每个数字都在它里面。
"""
import json
import os
import re

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.server.app import create_app
from app.tools.schema import describe_df, profile_dataset, profile_df
from tests.test_server import H, TOKEN, upload

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "ui", "web", "src", "fixtures", "asset_card.json")


@pytest.fixture
def c(tmp_path):
    return TestClient(create_app(str(tmp_path / "home"), TOKEN))


def write(path, text):
    path.write_bytes(text.encode("utf-8"))
    return str(path)


def detail(c, ds_id, rows=None):
    r = c.get(f"/datasets/{ds_id}" + (f"?rows={rows}" if rows else ""), headers=H)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- profile_df / profile_dataset
def test_profile_rows_and_columns_match_describe_df_header():
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", None, "z"]})
    head = re.search(r"表共有 (\d+) 行、(\d+) 列", describe_df(df))
    p = profile_df(df)
    assert (p["rows"], p["columns"]) == (int(head[1]), int(head[2])) == (3, 2)


def test_profile_missing_columns_counts_real_nan_only():
    df = pd.DataFrame({"id": ["1", "2", "未登记"], "amt": [1.0, None, 3.0], "name": ["甲", "乙", None], "ok": [1, 2, 3]})
    assert profile_df(df)["missing_columns"] == 2          # 哨兵词「未登记」不算缺失（那是 B65 注解的事）


def test_profile_time_range_mixed_text_formats_by_full_column():
    s = ["2024-01-05", "2024/2/1 08:30", "2024.03.15", "2024年4月2日"] + ["2024-02-02"] * 300 + ["2022-07-09"]
    p = profile_df(pd.DataFrame({"n": range(len(s)), "日期": s}))
    assert p["time_range"] == {"column": "日期", "min": "2022-07-09", "max": "2024-04-02"}   # 采样之外的最早值也算进去


def test_profile_time_range_datetime_dtype_and_first_date_column_wins():
    df = pd.DataFrame({"t": pd.to_datetime(["2021-05-01", None, "2020-01-31"]), "u": ["2030-01-01"] * 3})
    assert profile_df(df)["time_range"] == {"column": "t", "min": "2020-01-31", "max": "2021-05-01"}


@pytest.mark.parametrize("vals", [
    ["01/05/2024", "02/06/2024", "03/07/2024"],             # 月日顺序有歧义：不认
    ["2024", "2025", "2026"],                               # 只有年份的数字
    ["华东", "华北", "2024-01-01"],                          # 日期形态占比不够
    [None, None, None],
])
def test_profile_no_time_range(vals):
    assert profile_df(pd.DataFrame({"x": vals}))["time_range"] is None


def test_profile_dataset_sums_and_unions_ranges():
    a = profile_df(pd.DataFrame({"d": ["2024-01-01", "2024-02-01"], "v": [1, None]}))
    b = profile_df(pd.DataFrame({"d": ["2023-06-01", "2023-07-01"], "w": [1, 2], "z": [None, 1]}))
    c = profile_df(pd.DataFrame({"k": [1]}))
    p = profile_dataset([("a", a), ("b", b), ("c", c)])
    assert {k: p[k] for k in ("table_count", "rows", "columns", "missing_columns", "time_range")} == {
        "table_count": 3, "rows": 5, "columns": 6, "missing_columns": 2,
        "time_range": {"min": "2023-06-01", "max": "2024-02-01"}}
    assert [t["name"] for t in p["tables"]] == ["a", "b", "c"] and p["tables"][2]["time_range"] is None
    assert profile_dataset([])["time_range"] is None and profile_dataset([])["table_count"] == 0


def test_describe_df_prompt_text_unchanged_by_profile():
    """profile 只给界面：describe_df 的输出不含任何 profile 新增的信息（prompt 字节不变）。"""
    df = pd.DataFrame({"日期": ["2024-01-05", "2024-02-01"], "v": [1, None]})
    text = describe_df(df)
    assert "2024-02-01" in text            # 样例行本来就有
    assert "缺失" not in text and "时间范围" not in text


# ---------------------------------------------------------------- GET /datasets/{id}（只加字段）
def test_detail_profile_equals_contract_fixture(c, tmp_path):
    fx = json.load(open(FIXTURE, encoding="utf-8"))
    ds = upload(c, write(tmp_path / fx["filename"], fx["csv"]))
    assert ds["profile"] == fx["profile"]                     # 上传响应
    body = detail(c, ds["id"])
    assert body["profile"] == fx["profile"]                   # 不带 rows 的详情也有
    assert detail(c, ds["id"], rows=20)["profile"] == fx["profile"]


def test_detail_profile_agrees_with_preview_and_old_fields_unchanged(c, sample_path):
    ds = upload(c, sample_path)
    body = detail(c, ds["id"], rows=20)
    t, p = body["preview"]["tables"][0], body["profile"]
    assert p["rows"] == t["total_rows"] and p["columns"] == t["total_columns"] == len(body["tables"]["df"])
    assert body["summary"] == f"{t['total_rows']} 行 × {t['total_columns']} 列，编码 {t['encoding']}"   # 旧字段原样
    assert {"id", "name", "created_at", "files", "tables", "summary", "preview", "profile"} == set(body)
    assert "profile" not in c.get("/datasets", headers=H).json()[0]        # 列表接口不读文件，不带


def test_detail_profile_multi_table_skips_broken_table(c, tmp_path):
    a = write(tmp_path / "orders.csv", "id,day,amt\n1,2024-01-02,\n2,2024-03-04,5\n")
    b = write(tmp_path / "users.csv", "uid,joined\n1,2023-11-30\n")
    bad = write(tmp_path / "zz.csv", "")
    body = detail(c, upload(c, a, b, bad)["id"])
    p = body["profile"]
    assert "zz.csv" in body["error"]
    assert [t["name"] for t in p["tables"]] == ["orders", "users"]
    assert (p["table_count"], p["rows"], p["columns"], p["missing_columns"]) == (2, 3, 5, 1)
    assert p["time_range"] == {"min": "2023-11-30", "max": "2024-03-04"}
    assert p["tables"][0]["time_range"]["column"] == "day"
