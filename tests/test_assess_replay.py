"""阶段 7.5 第 1 步：单节点回放（app/assess/replay.py）。验收 ①（codegen prompt 逐字节一致、executor 结果一致）
与 ②（回放用快照里的 today，不读当天日期）。"""
import datetime as dt
import json
import math
import os

import numpy as np
import pandas as pd
import pytest

from app.assess import replay as rp
from app.assess import snapshot as snap
from app.core.llm import LLMClient, LLMConfig
from app.core.service import analyze
from app.core.testing import ScriptedChatModel, prompt_text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BAD = "result = df.groupby('regin')['units'].sum()"
GOOD = "result = df.groupby('region')['units'].sum()"


def _model():
    fixes = [GOOD]

    def respond(messages):
        t = prompt_text(messages)
        if "数据分析规划助手" in t:
            return "1. 按 `region` 分组求 `units` 之和"
        if "请修正它" in t:
            return fixes.pop(0)
        if "写一段 pandas 代码" in t:
            return BAD
        return "各地区总销量见结果"
    return ScriptedChatModel(responder=respond, calls=[])


@pytest.fixture
def snapshot_file(sample_path, tmp_path):
    analyze(sample_path, "各地区总销量", chat_model=_model(), snapshot_dir=str(tmp_path / "s"),
            today=dt.date(2024, 3, 9))
    return snap.list_snapshots(str(tmp_path / "s"))[0]


@pytest.mark.parametrize("node,occ", [("planner", 1), ("codegen", 1), ("reviewer", 1), ("summarizer", 1)])
def test_llm_node_recorded_replay_is_byte_identical(snapshot_file, node, occ):
    r = rp.replay_node(snapshot_file, node, occ, recorded=True)
    assert r.prompt_match is True and r.prompt_sha256 == r.recorded_prompt_sha256
    assert r.output_match is True, r.output_reason
    assert r.ok and r.mode == "recorded"


def test_codegen_live_replay_rebuilds_same_prompt(snapshot_file):
    """live 模式（这里注入一个假模型代替真 Key）：prompt 照样逐字节比对；模型输出不判（网关本就不确定）。"""
    seen = []

    def respond(messages):
        seen.append(prompt_text(messages))
        return "result = 1"
    client = LLMClient(LLMConfig(api_key="x"), model=ScriptedChatModel(responder=respond, calls=[]))
    r = rp.replay_node(snapshot_file, "codegen", client=client)
    assert r.prompt_match is True and r.output_match is None and r.updates["code"] == "result = 1"
    assert snap.sha256_text(seen[0]) == r.recorded_prompt_sha256


def test_codegen_prompt_mismatch_is_detected(snapshot_file, tmp_path):
    """上游一变（这里篡改快照里 codegen 的输入 plan），prompt 哈希就对不上。"""
    lines = open(snapshot_file, encoding="utf-8").read().splitlines()
    out = []
    for ln in lines:
        rec = json.loads(ln)
        if rec.get("node") == "codegen":
            rec["input_state"]["plan"] += " "
        out.append(json.dumps(rec, ensure_ascii=False))
    p = tmp_path / "tampered.jsonl"
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    r = rp.replay_node(str(p), "codegen", recorded=True)
    assert r.prompt_match is False and not r.ok


@pytest.mark.parametrize("occ", [1, 2])
def test_executor_replay_matches(snapshot_file, occ):
    r = rp.replay_node(snapshot_file, "executor", occ)
    assert r.mode == "exec" and r.output_match is True, r.output_reason
    if occ == 1:
        assert "KeyError" in r.updates["error"]
    else:
        assert isinstance(r.updates["result"], pd.Series)


def test_executor_replay_detects_changed_result(snapshot_file, tmp_path):
    lines = open(snapshot_file, encoding="utf-8").read().splitlines()
    out = []
    for ln in lines:
        rec = json.loads(ln)
        if rec.get("node") == "executor" and rec["occurrence"] == 2:
            rec["input_state"]["code"] = "result = df.groupby('region')['units'].sum() * 1.001"
        out.append(json.dumps(rec, ensure_ascii=False))
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    r = rp.replay_node(str(p), "executor", 2)
    assert r.output_match is False and "result" in r.output_reason


def test_replay_uses_snapshot_today_not_local_date(snapshot_file, monkeypatch):
    class _NoToday(dt.date):
        @classmethod
        def today(cls):
            raise AssertionError("回放不得取当天日期")
    monkeypatch.setattr(dt, "date", _NoToday)
    r = rp.replay_node(snapshot_file, "codegen", recorded=True)
    assert r.today == "2024-03-09"


def test_replay_refuses_snapshot_without_today(snapshot_file, tmp_path):
    lines = open(snapshot_file, encoding="utf-8").read().splitlines()
    run = json.loads(lines[0])
    del run["today"]
    p = tmp_path / "nt.jsonl"
    p.write_text("\n".join([json.dumps(run, ensure_ascii=False)] + lines[1:]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="today"):
        rp.replay_node(str(p), "codegen", recorded=True)


def test_executor_replay_refuses_changed_dataset(sample_path, tmp_path):
    data = tmp_path / "d.csv"
    data.write_bytes(open(sample_path, "rb").read())
    analyze(str(data), "各地区总销量", chat_model=_model(), snapshot_dir=str(tmp_path / "s"))
    f = snap.list_snapshots(str(tmp_path / "s"))[0]
    with open(data, "a", encoding="utf-8") as fh:
        fh.write("2024-02-01,华东,A,1,1.0\n")
    with pytest.raises(ValueError, match="指纹"):
        rp.replay_node(f, "executor", 1)


def test_replay_cli(snapshot_file):
    import importlib.util
    spec = importlib.util.spec_from_file_location("replay_cli", os.path.join(ROOT, "scripts", "assess", "replay_node.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main([snapshot_file, "codegen", "--recorded", "--json"]) == 0
    assert mod.main([snapshot_file, "executor", "--occurrence", "2"]) == 0


# ---------------------------------------------------------------- results_equal 的口径
def test_results_equal_tolerance_and_nan():
    a = pd.DataFrame({"x": [1.0, np.nan, 3.0], "y": ["a", None, "c"]})
    b = pd.DataFrame({"x": [1.0 + 1e-12, np.nan, 3.0], "y": ["a", None, "c"]})
    assert rp.results_equal(a, b)[0]
    assert rp.results_equal(0.0, 1e-13)[0]                 # abs 1e-12
    assert not rp.results_equal(1.0, 1.0 + 1e-6)[0]         # rel 1e-9 之外
    assert rp.results_equal(float("nan"), None)[0]
    assert not rp.results_equal(float("inf"), -math.inf)[0]


def test_results_equal_rejects_row_order_columns_and_shape():
    a = pd.DataFrame({"x": [1, 2]}, index=["p", "q"])
    assert not rp.results_equal(a, a.iloc[::-1])[0]                      # 行序必须一致
    assert not rp.results_equal(a, a.rename(columns={"x": "z"}))[0]      # 列名
    assert not rp.results_equal(a, a.iloc[:1])[0]                        # 行数
    assert not rp.results_equal(a["x"], a)[0]                            # 类型
    assert not rp.results_equal({"a": 1, "b": 2}, {"b": 2, "a": 1})[0]   # dict 键序
    assert rp.results_equal({"a": [1, 2.0]}, {"a": [1, 2.0 + 1e-15]})[0]
    assert not rp.results_equal(True, 1)[0]                               # bool 不按数值比


def test_multi_table_snapshot_and_executor_replay(tmp_path):
    d = tmp_path / "ds"
    d.mkdir()
    (d / "orders.csv").write_text("order_id,user_id,amount\n1,1,10.5\n2,2,20\n3,1,7\n", encoding="utf-8")
    (d / "users.csv").write_text("user_id,city\n1,上海\n2,北京\n", encoding="utf-8")
    code = "m = dfs['orders'].merge(dfs['users'], on='user_id')\nresult = m.groupby('city')['amount'].sum()"

    def respond(messages):
        t = prompt_text(messages)
        if "数据分析规划助手" in t:
            return "按城市汇总金额"
        if "写一段 pandas 代码" in t:
            return code
        return "见结果"
    analyze(str(d), "各城市金额", chat_model=ScriptedChatModel(responder=respond, calls=[]),
            snapshot_dir=str(tmp_path / "s"))
    f = snap.list_snapshots(str(tmp_path / "s"))[0]
    s = snap.load(f)
    assert s.run["multi"] is True and set(s.run["columns"]) == {"orders", "users"}
    assert [x["table"] for x in s.run["dataset_fingerprint"]["files"]] == ["orders", "users"]
    r = rp.replay_node(f, "executor")
    assert r.output_match is True, r.output_reason
    assert rp.replay_node(f, "codegen", recorded=True).ok
