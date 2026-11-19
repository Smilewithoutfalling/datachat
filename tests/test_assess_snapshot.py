"""阶段 7.5 第 1 步：节点边界快照（app/assess/snapshot.py）。"""
import datetime as dt
import json
import os

import pytest

from app.assess import snapshot as snap
from app.core.service import analyze, analyze_stream
from app.core.testing import ScriptedChatModel, prompt_text

_VOLATILE = {"trace_id", "timings", "duration_s", "ts", "chart_path", "png"}


def _model(code="result = df.groupby('region')['units'].sum()", fix=None, answer="华东最多"):
    fixes = list(fix or [])
    seen = []

    def respond(messages):
        t = prompt_text(messages)
        seen.append(t)
        if "数据分析规划助手" in t:
            return "1. 按 `region` 分组\n2. 对 `units` 求和"
        if "请修正它" in t:
            return fixes.pop(0)
        if "写一段 pandas 代码" in t:
            return code
        return answer
    return ScriptedChatModel(responder=respond, calls=[]), seen


def _scrub(x):
    if isinstance(x, dict):
        return {k: _scrub(v) for k, v in x.items() if k not in _VOLATILE}
    if isinstance(x, list):
        return [_scrub(v) for v in x]
    return x


def _events(gen):
    out = []
    for ev in gen:
        d = {"type": ev.type, "seq": ev.seq, "data": _scrub(ev.data)}
        if ev.result is not None:
            d["result"] = _scrub(ev.result.to_record())
        out.append(d)
    return out


def test_snapshot_off_is_byte_identical(sample_path, tmp_path, monkeypatch):
    """开关关闭：不建记录器、不落文件；打开只观测：事件、结果、发给模型的每个 prompt 都与关闭时一致。"""
    monkeypatch.delenv(snap.ENV, raising=False)
    built = []
    real = snap.SnapshotRecorder
    monkeypatch.setattr(snap, "SnapshotRecorder", lambda *a, **k: built.append(1) or real(*a, **k))
    m_off, seen_off = _model()
    off = _events(analyze_stream(sample_path, "各地区总销量", chat_model=m_off))
    assert built == []
    assert not (tmp_path / "snaps").exists()

    m_on, seen_on = _model()
    on = _events(analyze_stream(sample_path, "各地区总销量", chat_model=m_on,
                                snapshot_dir=str(tmp_path / "snaps")))
    assert built == [1]
    assert json.dumps(off, ensure_ascii=False, default=str) == json.dumps(on, ensure_ascii=False, default=str)
    assert seen_off == seen_on and len(seen_on) == 3
    assert len(os.listdir(tmp_path / "snaps")) == 1


def _one_file(d):
    files = snap.list_snapshots(str(d))
    assert len(files) == 1, files
    return snap.load(files[0])


def test_snapshot_records_nodes_state_tokens_and_today(sample_path, tmp_path):
    res = analyze(sample_path, "各地区总销量", chat_model=_model(code="result = df.groupby('regin')['units'].sum()",
                                                            fix=["result = df.groupby('region')['units'].sum()"])[0],
                  snapshot_dir=str(tmp_path), today=dt.date(2024, 3, 9))
    assert res.ok
    s = _one_file(tmp_path)
    run = s.run
    assert run["today"] == "2024-03-09" and run["today_source"] == "param"
    assert run["injected_timestamps"] == {"today": "2024-03-09"}
    assert run["columns"] == {"": ["date", "region", "product", "units", "price"]}
    assert run["dataset_fingerprint"]["files"][0]["bytes"] == os.path.getsize(sample_path)
    assert [(r["node"], r["occurrence"]) for r in s.nodes] == [
        ("planner", 1), ("codegen", 1), ("executor", 1), ("reviewer", 1), ("executor", 2), ("summarizer", 1)]
    for r in s.nodes:
        assert r["today"] == "2024-03-09"
        assert r["dataset"]["fingerprint"] == run["dataset_fingerprint"]["sha256"]
        assert r["duration_s"] >= 0
        assert "df" not in r["input_state"]                  # df 不存
    by = {(r["node"], r["occurrence"]): r for r in s.nodes}
    # 输入 state = 合并本节点 updates 之前的 state
    assert "plan" not in by[("planner", 1)]["input_state"]
    assert by[("codegen", 1)]["input_state"]["plan"] == by[("planner", 1)]["updates"]["plan"]
    assert by[("executor", 2)]["input_state"]["code"] == by[("reviewer", 1)]["updates"]["code"]
    # token：模型节点各一次调用，executor 零次
    assert by[("codegen", 1)]["tokens"]["calls"] == 1 and by[("codegen", 1)]["tokens"]["total_tokens"] == 15
    assert by[("executor", 1)]["tokens"]["calls"] == 0
    assert len(by[("codegen", 1)]["llm_calls"]) == 1
    assert by[("codegen", 1)]["llm_calls"][0]["response"] == "result = df.groupby('regin')['units'].sum()"
    assert by[("executor", 1)]["llm_calls"] == []
    # 结构化结果走 wire，能还原
    got = snap.decode_value(by[("executor", 2)]["updates"]["result"])
    assert list(got.index) == list(res.result.index) and list(got) == list(res.result)
    assert s.end["error"] is None and s.end["usage"]["calls"] == 4


def test_snapshot_today_defaults_to_local_date(sample_path, tmp_path):
    analyze(sample_path, "各地区总销量", chat_model=_model()[0], snapshot_dir=str(tmp_path))
    run = _one_file(tmp_path).run
    assert run["today_source"] == "local_date"
    assert dt.date.fromisoformat(run["today"]) <= dt.date.today()


def test_snapshot_env_var_enables(sample_path, tmp_path, monkeypatch):
    monkeypatch.setenv(snap.ENV, str(tmp_path / "env"))
    analyze(sample_path, "各地区总销量", chat_model=_model()[0])
    assert len(snap.list_snapshots(str(tmp_path / "env"))) == 1


def test_snapshot_one_file_per_run(sample_path, tmp_path):
    for _ in range(2):
        analyze(sample_path, "各地区总销量", chat_model=_model()[0], snapshot_dir=str(tmp_path))
    assert len(snap.list_snapshots(str(tmp_path))) == 2


def test_snapshot_write_failure_does_not_affect_analysis(sample_path, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    res = analyze(sample_path, "各地区总销量", chat_model=_model()[0], snapshot_dir=str(blocker / "sub"))
    assert res.ok and res.answer == "华东最多"


def test_snapshot_no_file_when_run_ends_before_graph(tmp_path):
    res = analyze(str(tmp_path / "missing.csv"), "q", chat_model=_model()[0], snapshot_dir=str(tmp_path / "s"))
    assert res.error_kind == "dataset"
    assert not (tmp_path / "s").exists()


@pytest.mark.parametrize("value", [1, "x", [1, 2], {"a": 1}, None, (1, 2), float("nan")])
def test_encode_value_roundtrip(value):
    enc = snap.encode_value("k", value)
    json.dumps(enc, allow_nan=False)
    dec = snap.decode_value(enc)
    if isinstance(value, float):
        assert dec != dec
    else:
        assert dec == value and type(dec) is type(value)


def test_fingerprint_partition_for_assess():
    """评测指纹的分区：快照在 analyze 执行路径上归 A；评估层其余文件只读快照，归 B。"""
    from app.eval import fingerprint as fp
    assert fp._group("app/assess/snapshot.py") == "A"
    for f in ("contracts.py", "code_refs.py", "replay.py", "runner.py", "__init__.py"):
        assert fp._group(f"app/assess/{f}") == "B"
    assert fp._group("app/tools/sandbox_caps.py") == "A"
