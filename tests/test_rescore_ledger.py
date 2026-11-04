"""重评台账（`scripts/eval/rescore_ledger.py`）—— 只测分组、算术与渲染。

不跑 `rescore()`：一份报告要重算几十道题的 gold，单份十几秒，放进单测等于把
CI 拖成分钟级。重评本身由 `tests/test_rescore.py` / `test_rescore_holdout.py` 盯着，
这里只保证"两列数的摆法"不会骗人。
"""
from __future__ import annotations

import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    "rescore_ledger", os.path.join(ROOT, "scripts", "eval", "rescore_ledger.py"))
ledger = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ledger)


def _rec(name, n, recorded, current, changed=(), carried=0, drift=None):
    return {"report": name, "group": ledger.group_of(name), "n": n,
            "recorded": recorded, "current": current, "carried": carried,
            "changed": list(changed), "bank_drift": drift, "drift_note": ""}


def test_group_of_maps_each_family():
    """分组是给"旧结论"用的：分错了，读者会把 react 的数和 workflow 的对在一起。"""
    assert ledger.group_of("eval_react_20261009_163700_run1.json") == "react"
    assert ledger.group_of("eval_workflow_20261009_161035_run1.json") == "workflow + 字典"
    assert ledger.group_of("eval_workflow_nodict_20261009_162434_run1.json") == "workflow 无字典"
    assert ledger.group_of("holdout_20261103_145703_react_run1.json") == "holdout 63 题"
    assert ledger.group_of("whatever.json") == "其他"


def test_pp_is_point_difference_not_ratio():
    """40/50 → 44/50 是 +8pp，不是 +10%（相对提升）。台账里必须写成 pp。"""
    assert ledger._pp(40, 44, 50) == "+8.0pp"
    assert ledger._pp(44, 40, 50) == "-8.0pp"
    assert ledger._pp(1, 1, 0) == "-"


def test_render_has_both_columns_and_delta():
    rows = [_rec("eval_react_x_run1.json", 50, 40, 44,
                 changed=[{"id": "agg_1", "before": False, "after": True},
                          {"id": "agg_2", "before": True, "after": False}])]
    md = ledger.render_md(rows, [])
    assert "记录值" in md and "当前重评" in md
    assert "40/50 80.0%" in md and "44/50 88.0%" in md
    assert "+8.0pp" in md
    # 涨跌要分开数，不能只给净值 —— 2 涨 2 跌净 0 和"没有变化"是两件事。
    assert "1 涨 1 跌" in md
    assert "agg_1↑" in md and "agg_2↓" in md


def test_render_separates_carried_rows():
    """沿用原判的题不是重评结果。不单列就会把旧数当成新数。"""
    md = ledger.render_md([_rec("eval_react_x_run1.json", 50, 40, 40, carried=7)], [])
    assert "沿用原判" in md


def test_render_warns_on_bank_drift():
    """题库被改过时，差异里混着两件事，不能都算到判分器头上。"""
    rows = [_rec("holdout_x_run1.json", 63, 58, 58,
                 drift={"report": "aaaaaaaaaaaa", "bank": "bbbbbbbbbbbb"})]
    md = ledger.render_md(rows, [])
    assert "题库版本漂移" in md
    assert "aaaaaaaaaaaa" in md and "bbbbbbbbbbbb" in md
    # 两边哈希必须在同一条里给全：曾经只截了 rescore 输出的第一行，留下
    # "…（questions 哈希对不上）：" 后面什么都没有，读者拿不到要比的两个值。
    for ln in md.splitlines():
        assert not (ln.lstrip().startswith("- ") and ln.rstrip().endswith("：")), ln


def test_section_numbers_follow_what_is_rendered():
    """条件段不能写死序号：没有漂移时"跳过的文件"就是第三节。"""
    only_skipped = ledger.render_md([_rec("eval_react_x_run1.json", 50, 40, 40)], ["gate_x.json：gate"])
    assert "## 三、跳过的文件" in only_skipped
    assert "## 四、" not in only_skipped

    both = ledger.render_md(
        [_rec("holdout_x_run1.json", 63, 58, 58, drift={"report": "a" * 12, "bank": "b" * 12})],
        ["gate_x.json：gate"])
    assert "## 三、题库版本漂移" in both and "## 四、跳过的文件" in both


def test_skipped_reasons_differ_by_kind():
    """三种进不了表的文件原因不同，一句套话会把"不是报告"说成"少个字段"。"""
    gate = ledger._why_not_eval("gate")
    summary = ledger._why_not_eval("summary")
    not_a_report = ledger._why_not_eval("not_a_report")
    assert len({gate, summary, not_a_report}) == 3
    assert "human" in gate and "逐题行" in summary and "不是报告" in not_a_report


def test_render_lists_skipped_files():
    md = ledger.render_md([_rec("eval_react_x_run1.json", 50, 40, 40)], ["gate_x.json：gate，没有对照物"])
    assert "跳过的文件" in md and "gate_x.json" in md


def test_collect_skips_non_eval_without_rescoring():
    """闸门报告没有 `overall.correct`，summary 没有逐题行 —— 都不该去调 rescore。"""
    records, skipped = ledger.collect([
        os.path.join(ROOT, "docs", "eval", "baselines.json"),
        os.path.join(ROOT, "docs", "eval", "gate_20261014_162428_react.json"),
    ])
    assert records == []
    assert len(skipped) == 2
    assert all("没有" in s for s in skipped)
