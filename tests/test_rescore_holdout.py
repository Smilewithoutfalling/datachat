"""rescore 的 holdout 支持：报告里的 63 道题不在 ALL_CASES 里，得从题库目录重建。

不重建的后果实测过一次：一份 54/63 的报告 rescore 出来是 **0/63 = 0.0%**，而且
`changed` 是空的（压根没进新旧对比），看上去像"新判分器把题全判错了"。

所以这组测试守两类事：
1. **重建要准** —— 与 `run_holdout.build_cases` 逐字段一致，否则同一份输出会在
   在线判分和离线重判之间漂移。
2. **缺东西必须炸** —— 目录不在、答案缺、数据集没注册、报告有题库没有的题号，
   一律抛错。静默归零/静默漏题比报错危险得多。
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "holdout"))

import run_holdout as RH                                    # noqa: E402
from app.eval.rescore import _holdout_setup, _questions_sha, rescore        # noqa: E402

QUESTIONS = {
    "version": 1,
    "datasets": {"shop": "data/shop.csv", "air": "data/air"},
    "questions": [
        {"id": "q1", "category": "aggregation", "dataset": "shop", "question": "有多少行？",
         "ordered": False, "percent_equiv": False, "expect_refusal": False, "has_chart": False},
        {"id": "q2", "category": "ranking", "dataset": "air", "question": "前三是谁？",
         "ordered": True, "keywords": ["排名"], "multi_table": True},
    ],
}
ANSWERS = {
    "questions_sha256": "x",
    "answers": {
        "q1": {"ground_truth": "len(df)", "note": ""},
        "q2": {"ground_truth": "df.nlargest(3,'v')", "alt": ["df.head(3)"]},
    },
}


def _make_setup(tmp_path, questions=None, answers=None):
    """造一份最小题库目录，返回 holdout meta dict。"""
    base = tmp_path / "holdout"
    base.mkdir(exist_ok=True)
    (base / "questions.json").write_text(
        json.dumps(questions if questions is not None else QUESTIONS, ensure_ascii=False), encoding="utf-8")
    (base / "answers.json").write_text(
        json.dumps(answers if answers is not None else ANSWERS, ensure_ascii=False), encoding="utf-8")
    # 报告里的 holdout.questions_sha256 默认与题库一致（不匹配的场景单独造）
    sha = _questions_sha((questions if questions is not None else QUESTIONS)["questions"])
    return {"dir": str(base), "questions_sha256": sha}


# ---- 1. 重建要准 ----

def test_rebuild_matches_run_holdout_build_cases(tmp_path):
    """rescore 重建出的 EvalCase 必须与 run_holdout 建的一模一样。

    两边字段列表目前是手抄的（一边在 scripts/holdout/run_holdout.py:190，
    一边在 app/eval/rescore.py:58），谁加了字段而另一边没加，同一份输出就会
    在线判对、离线判错 —— 这条测试就是那个漏字段的报警器。
    """
    meta = _make_setup(tmp_path)
    cases, _, _ = _holdout_setup(meta)
    mine = {c.id: asdict(c) for c in cases.values()}
    theirs = {c.id: asdict(c) for c in RH.build_cases(QUESTIONS, ANSWERS)}

    assert set(mine) == set(theirs) == {"q1", "q2"}
    for cid in theirs:
        for field, want in theirs[cid].items():
            assert mine[cid][field] == want, f"{cid}.{field} 不一致：rescore={mine[cid][field]!r} run_holdout={want!r}"


def test_rebuild_resolves_dataset_paths_absolute(tmp_path):
    """数据集路径要按题库目录解析成绝对路径 —— rescore 的 cwd 不是题库目录。"""
    meta = _make_setup(tmp_path)
    _, datasets, _ = _holdout_setup(meta)
    assert datasets["shop"] == str(tmp_path / "holdout" / "data" / "shop.csv")
    assert datasets["air"] == str(tmp_path / "holdout" / "data" / "air")


def test_rebuild_pads_sales_key(tmp_path):
    """runner.py:79 硬依赖 datasets["sales"]，没有就崩 —— 题库里没人叫这个名字。"""
    meta = _make_setup(tmp_path)
    _, datasets, _ = _holdout_setup(meta)
    assert "sales" in datasets
    assert datasets["sales"] in (datasets["shop"], datasets["air"])


def test_no_holdout_meta_returns_empty(tmp_path):
    """老报告（50 题那批）没有 holdout 段，不能因此报错。"""
    assert _holdout_setup(None) == ({}, None, None)
    assert _holdout_setup({}) == ({}, None, None)


# ---- 1b. 题库版本漂移 ----

def test_questions_sha_matches_run_holdout(tmp_path):
    """两边算法必须逐字节一致：rescore 抄了一份 run_holdout 的哈希实现。

    抄的原因是 scripts/ 不在包路径里。抄就有漂移风险 —— 谁改了算法而没改另一边，
    题库校验会永远对不上（或永远对上），这条测试是那个报警器。
    """
    assert _questions_sha(QUESTIONS["questions"]) == RH._sha256(QUESTIONS["questions"])
    assert _questions_sha([]) == RH._sha256([])


def test_same_bank_no_drift(tmp_path):
    meta = _make_setup(tmp_path)
    _, _, drift = _holdout_setup(meta)
    assert drift is None


def test_bank_drift_detected(tmp_path):
    """题库在报告跑完之后被改过（补题面提示、改答案）→ 记下两边哈希。

    不拦是因为"改过题面的报告"恰恰最需要重判；但必须留痕，
    否则就是用新答案判旧输出而一声不吭。
    """
    meta = _make_setup(tmp_path)
    meta["questions_sha256"] = "0" * 64          # 报告跑在另一版题库上
    _, _, drift = _holdout_setup(meta)
    assert drift is not None
    assert drift["report"] == "0" * 64
    assert drift["bank"] == _questions_sha(QUESTIONS["questions"])


def test_report_without_sha_does_not_warn(tmp_path):
    """老报告没记 questions_sha256（指纹机制早期）→ 无从比对，不该报漂移。"""
    meta = _make_setup(tmp_path)
    meta.pop("questions_sha256")
    _, _, drift = _holdout_setup(meta)
    assert drift is None


# ---- 2. 缺东西必须炸 ----

def test_missing_dir_raises(tmp_path):
    """题库目录被删/换机器没带 —— 必须抛，不能返回空 dict 然后判 0 分。"""
    with pytest.raises(FileNotFoundError, match="题库目录不可用"):
        _holdout_setup({"dir": str(tmp_path / "nope")})


def test_missing_answers_file_raises(tmp_path):
    meta = _make_setup(tmp_path)
    (Path(meta["dir"]) / "answers.json").unlink()
    with pytest.raises(FileNotFoundError):
        _holdout_setup(meta)


def test_question_without_answer_raises(tmp_path):
    """答案缺一条就等于漏一道题 —— 漏掉的会被判 False 且不进 changed。"""
    bad = json.loads(json.dumps(ANSWERS))
    del bad["answers"]["q2"]
    meta = _make_setup(tmp_path, answers=bad)
    with pytest.raises(ValueError, match="题面或答案缺失"):
        _holdout_setup(meta)


def test_empty_ground_truth_raises(tmp_path):
    bad = json.loads(json.dumps(ANSWERS))
    bad["answers"]["q1"]["ground_truth"] = "   "
    meta = _make_setup(tmp_path, answers=bad)
    with pytest.raises(ValueError, match="题面或答案缺失"):
        _holdout_setup(meta)


def test_unregistered_dataset_raises(tmp_path):
    bad = json.loads(json.dumps(QUESTIONS))
    bad["questions"][0]["dataset"] = "typo_table"
    meta = _make_setup(tmp_path, questions=bad)
    with pytest.raises(ValueError, match="未在 datasets 里注册"):
        _holdout_setup(meta)


# ---- 3. 报告与题库对不上 ----

def _holdout_report(tmp_path, ids, meta):
    path = tmp_path / "r.json"
    data = {
        "git_sha": "deadbeef", "agent": "react",
        "holdout": meta,
        "fingerprints": {"code_sha12": "aaaaaaaaaaaa"},
        "overall": {"n": len(ids), "correct": 0, "executed": len(ids),
                    "correctness_rate": 0.0, "conditional_correctness_rate": 0.0, "match_kinds": {}},
        "by_category": {}, "by_dataset": {},
        "cases": [{"id": i, "category": "aggregation", "dataset": "shop",
                   "correct": False, "match": None, "executed": True} for i in ids],
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_report_case_absent_from_bank_raises(tmp_path):
    """报告里有题库没有的题号（题库被换过/报告来自另一批）→ 抛，不静默判 False。"""
    meta = _make_setup(tmp_path)
    path = _holdout_report(tmp_path, ["q1", "q_from_another_batch"], meta)
    with pytest.raises(ValueError, match="在题库中找不到"):
        rescore(path)
