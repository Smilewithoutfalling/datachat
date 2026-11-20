"""B4 统计层与采集入库的单元测试（judge_calibrate 扩展 + judge_collect）。

覆盖四块：
1. Wilson CI 锚点值（手算可验）；
2. bootstrap κ CI：完美一致退化为 (1,1)、seed 固定可复现；
3. split_segments 两段标签比例守恒；
4. judge_collect：P0 逆反识别、轮转配额、ingest 人标闸（label 缺失拒收）、
   重复跳过、--confirm 才真写。
"""
import json
import os

import pytest

from scripts.eval.judge_calibrate import (
    bootstrap_kappa_ci,
    kappa_2x2,
    split_segments,
    wilson_ci,
)
from scripts.eval import judge_collect


# ---------- Wilson CI ----------

def test_wilson_ci_anchor_single_perfect():
    # 手算锚点：n=1, k=1 → (0.2066, 1.0)（n 小时 Wilson 才不会被正态近似带偏）
    lo, hi = wilson_ci(1, 1)
    assert lo == pytest.approx(0.2066, abs=1e-3)
    assert hi == 1.0


def test_wilson_ci_anchor_60_of_60():
    # 冒烟里见过的读数：60/60 → [0.940, 1.000]
    lo, hi = wilson_ci(60, 60)
    assert lo == pytest.approx(0.940, abs=5e-4)
    assert hi == pytest.approx(1.0, abs=1e-9)   # 浮点尾差 0.9999999999999999


def test_wilson_ci_empty():
    assert wilson_ci(0, 0) == (None, None)


# ---------- bootstrap κ CI ----------

def test_bootstrap_perfect_agreement_is_degenerate_one():
    pairs = [(True, True)] * 30 + [(False, False)] * 30
    lo, hi = bootstrap_kappa_ci(pairs, n_boot=200)
    assert (lo, hi) == (1.0, 1.0)


def test_bootstrap_is_reproducible_with_fixed_seed():
    pairs = [(True, True)] * 20 + [(False, False)] * 15 + [(True, False)] * 5
    a = bootstrap_kappa_ci(pairs, n_boot=200, seed=3)
    b = bootstrap_kappa_ci(pairs, n_boot=200, seed=3)
    assert a == b
    lo, hi = a
    assert lo < hi                       # 有分歧的样本区间必须有宽度
    assert 0.0 <= lo < 1.0 and 0.0 < hi <= 1.0


def test_kappa_anchor_mixed_matrix():
    # TP=18 FP=2 FN=2 TN=18：p_o=0.9, p_e=0.5 → κ=0.8
    cm = {(True, True): 18, (True, False): 2, (False, True): 2, (False, False): 18}
    assert kappa_2x2(cm) == pytest.approx(0.8)


# ---------- split_segments ----------

def _det(i, label):
    return {"idx": i, "id": f"c{i:02d}", "label": label, "judge_pass": label,
            "confidence": "high", "abstain": False, "reason": "", "order": "gold_first"}


def test_split_segments_keeps_label_balance():
    details = [_det(i, i % 3 != 0) for i in range(60)]      # 40 True / 20 False
    calib, gen = split_segments(details)
    n_pos = sum(1 for d in details if d["label"])
    for seg in (calib, gen):
        assert len(seg) == 30
        assert sum(1 for d in seg if d["label"]) == n_pos // 2   # 20/10 两段同比例
    assert {d["id"] for d in calib}.isdisjoint({d["id"] for d in gen})
    assert len(calib) + len(gen) == len(details)


# ---------- judge_collect：pool / 配额 / ingest ----------

def _write_gate(d, name, cases):
    json.dump({"cases": cases}, open(os.path.join(d, name), "w", encoding="utf-8"))


def _write_eval(d, name, cases):
    json.dump({"cases": cases}, open(os.path.join(d, name), "w", encoding="utf-8"))


LONG = "a sufficiently long answer text"


def _gate_case(cid, human, auto):
    return {"id": cid, "question": "q " + cid, "answer": LONG + " " + cid,
            "human_correct": human, "auto_correct": auto,
            "gold": {"kind": "scalar", "value": 42}}


def _eval_case(cid, correct, match):
    return {"id": cid, "question": "q " + cid, "answer": LONG + " " + cid,
            "expected": "42", "expected_obj": {"kind": "scalar", "value": 42},
            "correct": correct, "match": match}


def test_pool_wide_detects_clash_as_p0(tmp_path):
    _write_gate(tmp_path, "gate_a.json", [_gate_case("g1", True, False),   # P0 逆反
                                           _gate_case("g2", True, True)])  # 无逆反 → P3
    _write_eval(tmp_path, "eval_a.json", [_eval_case("e1", True, "value:scaled"),   # P1 放水
                                          _eval_case("e2", True, "value:strict"),   # P2 清晰对
                                          _eval_case("e3", False, "value:strict")])  # P3 清晰错
    pool = judge_collect.load_pool_wide(
        gate_glob=str(tmp_path / "gate_*.json"),
        out_glob=str(tmp_path / "eval_*.json"))
    by_id = {v["id"]: v for v in pool.values()}
    assert by_id["g1"]["priority"] == 0 and by_id["g1"]["clash"]
    assert by_id["g2"]["priority"] == 3
    assert by_id["e1"]["priority"] == 1
    assert by_id["e2"]["priority"] == 2
    assert by_id["e3"]["priority"] == 3


def test_collect_round_robin_quota(tmp_path, monkeypatch):
    # 池：P0×1、P1×10、P2×10、P3×10。target=9 → P0 全收 + 其余轮转，四档都有代表。
    _write_gate(tmp_path, "gate_a.json", [_gate_case("g1", True, False)])
    _write_eval(tmp_path, "eval_a.json",
                [_eval_case(f"s{i}", True, "value:scaled") for i in range(10)]
                + [_eval_case(f"k{i}", True, "value:strict") for i in range(10)]
                + [_eval_case(f"w{i}", False, "value:strict") for i in range(10)])
    monkeypatch.setattr(judge_collect, "_alt_values", lambda cid: [])   # 不跑真 gold
    gold = tmp_path / "gold.jsonl"
    gold.write_text("", encoding="utf-8")
    rows, stats = judge_collect.collect(9, gate_glob=str(tmp_path / "gate_*.json"),
                                        out_glob=str(tmp_path / "eval_*.json"),
                                        gold_path=str(gold))
    assert len(rows) == 9
    pr_counts = {}
    for r in rows:
        pr_counts[r["priority"]] = pr_counts.get(r["priority"], 0) + 1
    assert pr_counts.get(0) == 1
    for pr in (1, 2, 3):
        assert pr_counts.get(pr, 0) >= 2          # 轮转保证清晰对/清晰错也进清单
    assert all(r["label"] is None for r in rows)  # 出厂待人标


def _cand(cid, label, answer=None):
    return {"id": cid, "source": "gate_a.json", "question": "q " + cid,
            "answer": answer or (LONG + " " + cid),
            "gold": {"kind": "scalar", "value": 42}, "gold_summary": "标准答案：42",
            "category": None, "comparator_correct": True, "match": None,
            "priority": 0, "clash": False, "suggested_label": True, "label": label}


def test_ingest_requires_human_label(tmp_path):
    gold = tmp_path / "gold.jsonl"
    cand = tmp_path / "cand.jsonl"
    cand.write_text(json.dumps(_cand("g1", None), ensure_ascii=False) + "\n"
                    + json.dumps(_cand("g9", "maybe"), ensure_ascii=False) + "\n",
                    encoding="utf-8")
    accepted, skipped, existing = judge_collect.ingest(str(cand), gold_path=str(gold))
    assert accepted == []
    assert len(skipped) == 2
    assert not gold.exists()                     # 一条没标就一条都不进


def test_ingest_dry_run_then_confirm_then_duplicate(tmp_path):
    gold = tmp_path / "gold.jsonl"
    cand = tmp_path / "cand.jsonl"
    cand.write_text(json.dumps(_cand("g1", True), ensure_ascii=False) + "\n"
                    + json.dumps(_cand("g2", False), ensure_ascii=False) + "\n",
                    encoding="utf-8")
    accepted, skipped, existing = judge_collect.ingest(str(cand), gold_path=str(gold))
    assert len(accepted) == 2 and not gold.exists()      # 干跑不落盘

    accepted, skipped, existing = judge_collect.ingest(str(cand), gold_path=str(gold), confirm=True)
    assert len(accepted) == 2
    lines = [json.loads(l) for l in gold.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2
    assert all(r["human_labeled"] for r in lines)
    assert [r["order"] for r in lines] == ["gold_first", "answer_first"]   # 交替防位置偏

    accepted, skipped, existing = judge_collect.ingest(str(cand), gold_path=str(gold), confirm=True)
    assert accepted == []
    assert len(skipped) == 2                      # 同 (id, answer) 已在库 → 跳过
