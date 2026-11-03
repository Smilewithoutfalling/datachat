"""replay.py 的验收测试：批 0 的硬指标是"全部报告可解析"，这条得能自动跑。

`--check` 的语义必须窄：只有"解析失败 / 结构坏了"才算红。待判、缺 match、
summary 的 run 文件不在本机，都是**已知的历史状态**（规格 §1.1.1），算成失败会让
这个红灯永远亮着，那样它就不传递任何信息了。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "dc_replay", os.path.join(ROOT, "scripts", "eval", "replay.py"))
replay = importlib.util.module_from_spec(_spec)
sys.modules["dc_replay"] = replay
_spec.loader.exec_module(replay)


def _write(tmp_path, name: str, data: dict) -> str:
    p = tmp_path / name
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


def _eval(tmp_path, cases, name="eval.json"):
    return _write(tmp_path, name, {"cases": cases})


def test_check_passes_on_readable_reports(tmp_path, capsys):
    p1 = _eval(tmp_path, [{"id": "a", "category": "x", "question": "q", "correct": True}], "a.json")
    p2 = _eval(tmp_path, [{"id": "b", "category": "x", "question": "q", "correct": False}], "b.json")
    assert replay.main([p1, p2, "--check"]) == 0
    out = capsys.readouterr().out
    assert "2 份报告解析成功" in out


def test_check_fails_on_broken_json(tmp_path, capsys):
    bad = tmp_path / "broken.json"
    bad.write_text("{not json", encoding="utf-8")
    assert replay.main([str(bad), "--check"]) == 1
    assert "失败" in capsys.readouterr().out


def test_check_fails_on_missing_hard_field(tmp_path, capsys):
    """缺 category 的报告能读，但结构坏了 —— 后续没法按类别统计，该红。"""
    p = _eval(tmp_path, [{"id": "a", "category": "", "question": "q", "correct": True}])
    assert replay.main([p, "--check"]) == 1
    assert "缺必填字段" in capsys.readouterr().out


def test_non_report_file_is_skipped_not_failed(tmp_path, capsys):
    """`baselines.json` 是登记表，不是报告。跳过，但要说出来是哪一份。"""
    p = _write(tmp_path, "baselines.json", {"_comment": "x", "eval-v0": {}})
    ok = _eval(tmp_path, [{"id": "a", "category": "x", "question": "q", "correct": True}])
    assert replay.main([p, ok, "--check"]) == 0
    out = capsys.readouterr().out
    assert "已跳过" in out and "baselines.json" in out


def test_pending_and_missing_match_are_not_failures(tmp_path, capsys):
    """闸门报告人工没签字、评测报告没有 match —— 都是已知状态，不是解析失败。"""
    gate = _write(tmp_path, "gate.json", {
        "questions_sha256": "x", "cases": [
            {"id": "s01", "category": "x", "question": "q", "executed": True},  # 待判
        ]})
    ev = _eval(tmp_path, [{"id": "a", "category": "x", "question": "q", "correct": True}])
    assert replay.main([gate, ev, "--check"]) == 0
    out = capsys.readouterr().out
    assert "待判" in out and "无match" in out


def test_summary_with_missing_runs_is_not_a_failure(tmp_path, capsys):
    """`outputs/` 被 gitignore，新克隆的仓库里 run 文件本来就不存在。"""
    s = _write(tmp_path, "s_summary.json", {
        "runs": [{"run": 1, "file": "D:\\nowhere\\missing_run1.json"}]})
    assert replay.main([s, "--check"]) == 0
    assert "缺 run 文件" in capsys.readouterr().out


def test_check_without_flag_never_returns_1(tmp_path):
    """不带 `--check` 是"看看"，不是验收。"""
    bad = tmp_path / "broken.json"
    bad.write_text("{not json", encoding="utf-8")
    assert replay.main([str(bad)]) == 0


def test_glob_pattern_expands(tmp_path, capsys):
    _eval(tmp_path, [{"id": "a", "category": "x", "question": "q", "correct": True}], "x1.json")
    _eval(tmp_path, [{"id": "b", "category": "x", "question": "q", "correct": True}], "x2.json")
    assert replay.main([os.path.join(str(tmp_path), "*.json"), "--check"]) == 0
    assert "2 份报告解析成功" in capsys.readouterr().out


def test_unmatched_glob_is_reported_as_failure(tmp_path, capsys):
    """glob 一个都没匹配上不能静默通过 —— 那等于验收了零份报告。"""
    assert replay.main([os.path.join(str(tmp_path), "*.nope"), "--check"]) == 1
