"""`eval_merge.py` 的回归：合并器自己不能变成第二个判据来源。

真正要钉的三件事：
  1. 覆盖是**按 case id 逐条**替换，不是把两份的题堆在一起（堆起来总数会变）
  2. `overall` / `multi_turn` 是从合并后的 cases **重算**的（所以 EvalReport 说什么就是什么，
     合并器不自己算百分比）
  3. 三种错配必须报错退出，而不是静默产出一份看起来正常的报告
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import eval_merge  # noqa: E402
from app.eval.cases import ALL_CASES  # noqa: E402

MULTI = [c for c in ALL_CASES if c.category == "multi_turn"][:2]
SINGLE = [c for c in ALL_CASES if c.category == "aggregation"][:1]


def _rec(case, correct, **kw):
    r = {
        "id": case.id, "category": case.category, "dataset": case.dataset,
        "question": case.question, "correct": correct, "executed": True,
        "match": "strict" if correct else None, "tokens": 100, "duration_s": 1.0,
        "turn_status": ["ok"] * len(case.turns), "turn_answers": ["答"] * len(case.turns),
        "turns": list(case.turns), "memory_mode": "state",
    }
    r.update(kw)
    return r


def _report(cases, agent="workflow", evalset="aaaaaaaaaaaa", mode="state"):
    return {
        "time": "2026-11-17T00:00:00", "agent": agent, "memory_mode": mode,
        "git_sha": "deadbeef", "cases": cases,
        "fingerprints": {"evalset_sha12": evalset},
        "overall": {"n": len(cases), "correct": sum(1 for c in cases if c["correct"])},
    }


def _write(tmp_path, name, payload):
    p = tmp_path / name
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_patch_overrides_by_id_and_recomputes(tmp_path):
    a, b = MULTI[0], MULTI[1]
    main = _report([_rec(a, True), _rec(b, True), _rec(SINGLE[0], True)])
    patch = _report([_rec(b, False)])
    out = str(tmp_path / "merged.json")
    rc = eval_merge.main([_write(tmp_path, "main.json", main),
                          _write(tmp_path, "patch.json", patch), "--out", out])
    assert rc == 0
    d = json.loads(open(out, encoding="utf-8").read())
    assert d["overall"]["n"] == 3, "合并是覆盖，不是相加"
    assert d["overall"]["correct"] == 2, "overall 必须按覆盖后的判定重算"
    assert d["merged_from"] == ["main.json", "patch.json"]


def test_multi_turn_block_follows_the_override(tmp_path):
    """多轮块的 failed 必须随覆盖变化 —— 这是 P2"能复算"的核心。"""
    a = MULTI[0]
    main = _report([_rec(a, True)])
    patch = _report([_rec(a, False, turn_status=["fail:inherit"] * len(a.turns))])
    out = str(tmp_path / "m.json")
    assert eval_merge.main([_write(tmp_path, "m.json.base", main),
                            _write(tmp_path, "p.json", patch), "--out", out]) == 0
    d = json.loads(open(out, encoding="utf-8").read())
    assert d["multi_turn"]["failed"] > 0
    assert d["multi_turn"]["checked"] == len(a.expect_turns) - a.expect_turns.count("any")


@pytest.mark.parametrize("bad, msg", [
    ({"evalset": "bbbbbbbbbbbb"}, "evalset"),
    ({"ids": ["no_such_case_999"]}, "不在主报告"),
    ({"agent": "react"}, "agent"),
])
def test_mismatch_aborts(tmp_path, bad, msg):
    a = MULTI[0]
    main = _report([_rec(a, True)])
    payload = _report([_rec(a, True)],
                      evalset=bad.get("evalset", "aaaaaaaaaaaa"),
                      agent=bad.get("agent", "workflow"))
    if "ids" in bad:
        payload["cases"][0]["id"] = bad["ids"][0]
    with pytest.raises(SystemExit) as ei:
        eval_merge.main([_write(tmp_path, "main.json", main),
                         _write(tmp_path, "p.json", payload),
                         "--out", str(tmp_path / "x.json")])
    assert msg in str(ei.value)


def test_drop_category_recomputes(tmp_path):
    """`off` 档跳过 requires_memory 的题：把 202 题的报告当 195 题读会虚高。"""
    keep, drop = SINGLE[0], [c for c in ALL_CASES if c.category == "memory"][0]
    main = _report([_rec(keep, True), _rec(drop, True)])
    out = str(tmp_path / "d.json")
    assert eval_merge.main([_write(tmp_path, "main.json", main),
                            "--drop-category", "memory", "--out", out]) == 0
    d = json.loads(open(out, encoding="utf-8").read())
    assert d["overall"]["n"] == 1 and d["merged_dropped"] == {"memory": 1}
