"""`scripts/eval/compare.py` —— 两份报告的逐题配对比较。

重点不是"能跑"，而是三件容易悄悄错的事：
1. 同一份文件自比必须 Δ=0 / 翻转 0:0 / p=1.0（规格 §8 批 0）；
2. 混着用比较器结论和人工结论时，必须拒绝给出模型层面的结论；
3. 待判的题不能混进 McNemar 的 b/c。
"""
from __future__ import annotations

import importlib.util
import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "compare_mod", os.path.join(ROOT, "scripts", "eval", "compare.py"))
compare_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare_mod)

load_report = compare_mod.load_report
compare = compare_mod.compare
format_report = compare_mod.format_report
ReportError = compare_mod.ReportError


def _eval_report(path, rows, *, model="m1", evalset="e" * 12, run_sha=None, now_sha=None):
    """rows: (id, correct, match) 或 dict(id=..., human_correct=..., auto_correct=...)"""
    cases = []
    for r in rows:
        if isinstance(r, dict):
            cases.append(r)
        else:
            cid, ok = r
            cases.append({"id": cid, "correct": ok, "match": "strict" if ok else None})
    data = {
        "model": model,
        "agent": "react",
        "fingerprints": {"evalset_sha12": evalset},
        "cases": cases,
    }
    if run_sha:
        data["run_code_sha12"] = run_sha
        data["fingerprints"]["code_sha12"] = now_sha or run_sha
    p = path / "r.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_self_compare_is_a_no_op(tmp_path):
    """同一份文件比自己：Δ=0、0:0、p=1.0。这是脚本唯一能自证算错没错的方式。"""
    p = _eval_report(tmp_path, [("a", True), ("b", False), ("c", True)])
    res = compare(load_report(p), load_report(p))
    assert res["delta_pp"] == 0.0
    assert (res["flips"]["b_only"], res["flips"]["c_only"]) == (0, 0)
    assert res["mcnemar_p"] == 1.0
    assert "完全一致" in res["conclusion"]


def test_mcnemar_matches_hand_calculation(tmp_path):
    """b=5 / c=2 → p = 2×(1+7+21)/128 = 0.4531。手算，不是拿函数对函数。"""
    # 20 题：10 题都对、5 题 A 错 B 对、2 题 A 对 B 错、3 题都错
    a_rows = ([(f"c{i}", True) for i in range(10)]
              + [(f"x{i}", False) for i in range(5)]     # A 错，B 对
              + [(f"y{i}", True) for i in range(2)]      # A 对，B 错
              + [(f"z{i}", False) for i in range(3)])
    b_rows = ([(f"c{i}", True) for i in range(10)]
              + [(f"x{i}", True) for i in range(5)]
              + [(f"y{i}", False) for i in range(2)]
              + [(f"z{i}", False) for i in range(3)])

    a = _eval_report(tmp_path, a_rows)
    b_dir = tmp_path / "b"
    b_dir.mkdir()
    b = _eval_report(b_dir, b_rows)
    res = compare(load_report(a), load_report(b))

    assert (res["flips"]["b_only"], res["flips"]["c_only"]) == (5, 2)
    assert res["mcnemar_p"] == 0.4531          # 2 × 29 / 128
    assert res["significant"] is False
    # A 对 12、B 对 15，n=20
    assert (res["a"]["correct"], res["b"]["correct"]) == (12, 15)
    assert res["delta_pp"] == 15.0


def test_six_one_way_flips_is_significant(tmp_path):
    """6:0 → p=0.03125 < 0.05。MDE 的定义就是这个数。"""
    a = _eval_report(tmp_path, [(f"c{i}", False) for i in range(6)])
    b_dir = tmp_path / "b"
    b_dir.mkdir()
    b = _eval_report(b_dir, [(f"c{i}", True) for i in range(6)])
    res = compare(load_report(a), load_report(b))
    assert (res["flips"]["b_only"], res["flips"]["c_only"]) == (6, 0)
    assert res["mcnemar_p"] == 0.0312
    assert res["significant"] is True
    assert res["mde_flips"] == 6


def test_pending_rows_do_not_enter_pairing(tmp_path):
    """闸门报告人工没填的题是"待判"，不能当成"答错"塞进 b/c。"""
    a = _eval_report(tmp_path, [{"id": "x", "auto_correct": True}])
    b_dir = tmp_path / "b"
    b_dir.mkdir()
    b = _eval_report(b_dir, [{"id": "x", "auto_correct": None}])
    res = compare(load_report(a), load_report(b))
    assert res["flips"]["pending"] == 1
    assert (res["flips"]["b_only"], res["flips"]["c_only"]) == (0, 0)
    assert res["mcnemar_p"] == 1.0


def test_mixed_sources_are_flagged(tmp_path):
    """一边比较器判、一边人判 —— 这个 Δ 不是模型差异，必须拒绝给结论。"""
    a = _eval_report(tmp_path, [{"id": "x", "auto_correct": True}])
    b_dir = tmp_path / "b"
    b_dir.mkdir()
    b = _eval_report(b_dir, [{"id": "x", "human_correct": False}])
    res = compare(load_report(a), load_report(b))
    assert res["source_mix"]["mixed"] is True
    assert res["source_mix"]["mismatch_n"] == 1
    text = format_report(res, "A", "B")
    assert "不能读成模型差异" in text
    assert "不作数" in text


def test_human_verdict_beats_auto(tmp_path):
    """闸门报告人判优先于比较器 —— 规格 §1.2 的既有语义，不许改。"""
    a = _eval_report(tmp_path, [{"id": "x", "human_correct": True,
                                 "auto_correct": False, "correct": False}])
    r = load_report(a)
    assert r["rows"]["x"]["correct"] is True
    assert r["rows"]["x"]["source"] == "human"


def test_same_source_on_both_sides_is_not_flagged(tmp_path):
    a = _eval_report(tmp_path, [("x", True)])
    b_dir = tmp_path / "b"
    b_dir.mkdir()
    b = _eval_report(b_dir, [("x", False)])
    res = compare(load_report(a), load_report(b))
    assert res["source_mix"]["mixed"] is False
    assert "两边一致" in format_report(res, "A", "B")


def test_different_models_make_reports_incomparable(tmp_path):
    a = _eval_report(tmp_path, [("x", True)], model="m1")
    b_dir = tmp_path / "b"
    b_dir.mkdir()
    b = _eval_report(b_dir, [("x", True)], model="m2")
    res = compare(load_report(a), load_report(b))
    assert res["comparable"]["fields"]["model"] is False
    assert res["comparable"]["verdict"] == "different"
    assert "model" in res["comparable"]["diffs"]


def test_different_agent_is_incomparable(tmp_path):
    """react 比 workflow 不是"模型差异"——两个执行器不是同一个被测对象。

    实测传错过：三项（prompt/evalset/model）全 yes，脚本照常给 Δ。
    """
    a = _eval_report(tmp_path, [("x", True)])
    b_dir = tmp_path / "b"
    b_dir.mkdir()
    p = b_dir / "r.json"
    p.write_text(json.dumps({"model": "m1", "agent": "workflow",
                             "fingerprints": {"evalset_sha12": "e" * 12},
                             "cases": [{"id": "x", "correct": True}]}), encoding="utf-8")
    res = compare(load_report(a), load_report(p))
    assert res["comparable"]["fields"]["agent"] is False
    assert res["comparable"]["verdict"] == "different"
    assert "agent" in res["comparable"]["diffs"]


def test_missing_fingerprint_is_legacy_not_different(tmp_path):
    """缺指纹只能说"不能声称可比"；说成"不可比"是没数据却下断言。"""
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"cases": [{"id": "x", "correct": True}]}), encoding="utf-8")
    res = compare(load_report(str(p)), load_report(str(p)))
    assert res["comparable"]["verdict"] == "legacy"
    assert res["comparable"]["ok"] is False
    assert "prompt_sha12" in res["comparable"]["unknown"]


def test_only_in_one_report_is_reported_not_pairwise(tmp_path):
    a = _eval_report(tmp_path, [("x", True), ("y", True)])
    b_dir = tmp_path / "b"
    b_dir.mkdir()
    b = _eval_report(b_dir, [("x", True), ("z", True)])
    res = compare(load_report(a), load_report(b))
    assert res["only_a"] == ["y"]
    assert res["only_b"] == ["z"]
    assert res["n_common"] == 1
    assert res["flips"]["b_only"] == res["flips"]["c_only"] == 0


def test_no_common_ids_is_an_error(tmp_path):
    a = _eval_report(tmp_path, [("x", True)])
    b_dir = tmp_path / "b"
    b_dir.mkdir()
    b = _eval_report(b_dir, [("y", True)])
    with pytest.raises(ReportError, match="没有共同题号"):
        compare(load_report(a), load_report(b))


def test_summary_report_is_rejected_with_pointer(tmp_path):
    """`*_summary.json` 没有逐题行，报错要告诉人该传哪份。"""
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"runs": [{"file": "x.json"}]}), encoding="utf-8")
    with pytest.raises(ReportError, match="请传它引用的那份 run 报告"):
        load_report(str(p))


def test_missing_file_and_bad_json(tmp_path):
    with pytest.raises(ReportError, match="文件不存在"):
        load_report(str(tmp_path / "nope.json"))
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ReportError, match="不是合法 JSON"):
        load_report(str(p))


def test_duplicate_id_is_rejected(tmp_path):
    """同号两行配对会静默覆盖一行，必须在读入时报错。"""
    p = tmp_path / "d.json"
    p.write_text(json.dumps({"cases": [{"id": "x", "correct": True},
                                       {"id": "x", "correct": False}]}), encoding="utf-8")
    with pytest.raises(ReportError, match="重复出现"):
        load_report(str(p))


def test_tier_moves_counted_only_when_both_correct(tmp_path):
    """strict→relaxed 只在两边都判对时才有意义；判错的题没有层级。"""
    a = _eval_report(tmp_path, [("x", True)])
    b_dir = tmp_path / "b"
    b_dir.mkdir()
    p = b_dir / "r.json"
    p.write_text(json.dumps({"cases": [{"id": "x", "correct": True, "match": "relaxed"}]}),
                 encoding="utf-8")
    res = compare(load_report(a), load_report(p))
    assert res["tier"]["moves"] == {"strict->relaxed": 1}
    assert res["tier"]["delta_pp"] == -100.0


def test_conclusion_refuses_to_claim_improvement_below_mde(tmp_path):
    a = _eval_report(tmp_path, [(f"c{i}", False) for i in range(20)])
    b_dir = tmp_path / "b"
    b_dir.mkdir()
    b = _eval_report(b_dir, [(f"c{i}", True) for i in range(3)]
                     + [(f"c{i}", False) for i in range(3, 20)])
    res = compare(load_report(a), load_report(b))
    assert res["significant"] is False
    assert "不能宣称改进" in res["conclusion"]


def test_small_n_cannot_reach_significance(tmp_path):
    """3 道题上要 6 个翻转才显著 —— 是设计测不出来，不是"差异小"。"""
    a = _eval_report(tmp_path, [("x", False), ("y", False), ("z", False)])
    b_dir = tmp_path / "b"
    b_dir.mkdir()
    b = _eval_report(b_dir, [("x", True), ("y", True), ("z", True)])
    res = compare(load_report(a), load_report(b))
    assert res["significant"] is False
    assert "不可能显著" in res["conclusion"]
    assert "不可达" in format_report(res, "A", "B")


def test_main_returns_1_on_unreadable_report(tmp_path, capsys):
    code = compare_mod.main([str(tmp_path / "nope.json"), str(tmp_path / "nope.json")])
    assert code == 1
    assert "文件不存在" in capsys.readouterr().err


def test_main_writes_json_sidecar(tmp_path):
    p = _eval_report(tmp_path, [("x", True)])
    out = tmp_path / "out.json"
    assert compare_mod.main([p, p, "--json", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["mcnemar_p"] == 1.0
    assert data["_paths"]["a"] == p
