"""holdout runner 的测试。

守两件事：
1. 题库校验 —— 缺答案、题号重复、引用未注册的数据集、冻结哈希对不上，都要**硬失败**而不是
   带着不一致跑完 40 题再让人从报告里发现。
2. `EvalReport(rendered_cases=...)` 这个新参数在**默认路径上什么都不做**。它是为留出集加的
   （不传就会按 ALL_CASES 的 130 题渲染指纹，自定义数据集上直接 KeyError），但标准跑批不能
   因此有任何行为变化，否则新报告的 `rendered_set_sha12` 与历史报告全线不同，那条"等价可比"
   的诊断线就断了。
"""
import json
import os

import pytest

import scripts.holdout.run_holdout as H
from app.eval.case_model import EvalCase
from app.eval.report import EvalReport


# ---------------------------------------------------------------- 题库构造

def _spec(n=2, datasets=None, frozen_at="2026-11-02"):
    return {
        "version": 1,
        "frozen_at": frozen_at,
        "datasets": datasets or {"shop": "data/eval/biz"},
        "questions": [
            {"id": f"q{i}", "group": "multi", "category": "aggregation",
             "dataset": "shop", "question": f"问题 {i}"}
            for i in range(1, n + 1)
        ],
    }


def _answers(spec, sha="x" * 64, **extra):
    ans = {q["id"]: {"ground_truth": f"result = {i}"} for i, q in enumerate(spec["questions"], 1)}
    ans.update(extra)
    return {"questions_sha256": sha, "answers": ans}


# ---------------------------------------------------------------- 冻结校验

def test_check_frozen_accepts_matching_hash():
    spec = _spec()
    want = H._sha256(spec["questions"])
    assert H.check_frozen(spec, {"questions_sha256": want}) == want


def test_check_frozen_rejects_edited_questions():
    """题面改过就不许跑 —— 否则旧答案判新题，判错的会被记成模型错。"""
    spec = _spec()
    spec["questions"][0]["question"] = "改过的问题"
    with pytest.raises(SystemExit) as e:
        H.check_frozen(spec, {"questions_sha256": "a" * 64})
    msg = str(e.value.code)
    assert "不匹配" in msg
    assert H._sha256(spec["questions"]) in msg, "要打印当前哈希，方便对照"
    assert "a" * 64 in msg, "也要打印 answers 里记的那个"


def test_check_frozen_warns_when_hash_absent(capsys):
    """首次建库还没有哈希：警告放行，不拦。拦下来会逼人先算哈希才能试跑。"""
    spec = _spec()
    got = H.check_frozen(spec, {})
    assert got == H._sha256(spec["questions"])
    assert "questions_sha256" in capsys.readouterr().out


def test_sha256_is_order_insensitive_for_object_keys():
    """键排序：JSON 里键的书写顺序不该改变哈希。"""
    a = [{"id": "q1", "question": "x"}]
    b = [{"question": "x", "id": "q1"}]
    assert H._sha256(a) == H._sha256(b)


def test_sha256_changes_when_question_text_changes():
    assert H._sha256([{"id": "q1", "question": "x"}]) != H._sha256([{"id": "q1", "question": "y"}])


# ---------------------------------------------------------------- build_cases

def test_build_cases_maps_all_fields():
    spec = _spec(n=1)
    spec["questions"][0].update({"ordered": True, "percent_equiv": True,
                                 "expect_refusal": True, "multi_table": True,
                                 "gold_kind": "series", "keywords": ["groupby"]})
    ans = _answers(spec)
    ans["answers"]["q1"]["alt"] = ["result = 99"]
    (c,) = H.build_cases(spec, ans)
    assert (c.id, c.category, c.dataset) == ("q1", "aggregation", "shop")
    assert c.ordered and c.percent_equiv and c.expect_refusal and c.multi_table
    assert c.gold_kind == "series" and c.keywords == ["groupby"]
    assert c.alt_ground_truths == ["result = 99"]


def test_build_cases_rejects_missing_answer():
    with pytest.raises(SystemExit) as e:
        H.build_cases(_spec(), {"answers": {"q1": {"ground_truth": "result = 1"}}})
    assert "q2" in str(e.value.code)


def test_build_cases_rejects_empty_ground_truth():
    spec = _spec(n=1)
    with pytest.raises(SystemExit) as e:
        H.build_cases(spec, {"answers": {"q1": {"ground_truth": "   "}}})
    assert "空" in str(e.value.code)


def test_build_cases_rejects_duplicate_id():
    spec = _spec(n=1)
    spec["questions"].append(dict(spec["questions"][0]))
    with pytest.raises(SystemExit) as e:
        H.build_cases(spec, _answers(_spec(n=1)))
    assert "重复" in str(e.value.code)


def test_build_cases_rejects_unregistered_dataset():
    spec = _spec(n=1)
    spec["questions"][0]["dataset"] = "not_registered"
    with pytest.raises(SystemExit) as e:
        H.build_cases(spec, _answers(spec))
    assert "not_registered" in str(e.value.code)


def test_build_cases_rejects_orphan_answer():
    """answers.json 里有题库中没有的题号：多半是删题没删答案，跑起来会静默漏判。"""
    spec = _spec(n=1)
    with pytest.raises(SystemExit) as e:
        H.build_cases(spec, _answers(spec, q99={"ground_truth": "result = 9"}))
    assert "q99" in str(e.value.code)


# ---------------------------------------------------------------- datasets

def test_build_datasets_resolves_relative_to_bank_dir(tmp_path):
    """相对路径按**题库目录**解析，不是仓库根。题面里因此不用写机器相关的绝对路径。"""
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "a.csv").write_text("x\n1\n", encoding="utf-8")
    out = H.build_datasets({"datasets": {"t": "d/a.csv"}}, str(tmp_path))
    assert out["t"] == str(tmp_path / "d" / "a.csv")


def test_build_datasets_reports_every_missing_path():
    with pytest.raises(SystemExit) as e:
        H.build_datasets({"datasets": {"a": "no/a.csv", "b": "no/b.csv"}}, os.getcwd())
    msg = str(e.value.code)
    assert "a:" in msg and "b:" in msg, "要一次全列出来，不要修一个报一个"


def test_build_datasets_requires_non_empty_section():
    with pytest.raises(SystemExit) as e:
        H.build_datasets({"questions": []}, os.getcwd())
    assert "datasets" in str(e.value.code)


# ---------------------------------------------------------------- sales 占位键

def test_pad_sales_adds_placeholder_for_custom_datasets():
    """`runner.py:79` 是死赋值但会 KeyError（`self.df_path = self.datasets["sales"]`）。

    `runner.py` 在 A 组，改一个字就让 6 个基线失配，所以只能在这里补占位键。
    这条测试同时是「别顺手把这个补丁删掉」的提醒。
    """
    out = H._pad_sales({"shop": "/a/b", "air": "/c/d"})
    assert out["sales"] == "/a/b"
    assert out["shop"] == "/a/b" and out["air"] == "/c/d"


def test_pad_sales_keeps_real_sales():
    assert H._pad_sales({"sales": "/real"}) == {"sales": "/real"}


def test_eval_runner_really_needs_sales_key(tmp_path):
    """把上面那条补丁的前提钉死：不补就会 KeyError。补丁失效时这条会红。"""
    from app.eval.runner import EvalRunner
    with pytest.raises(KeyError):
        EvalRunner(None, datasets={"shop": str(tmp_path)})


# ---------------------------------------------------------------- 报告注入

def test_stamp_manual_fields(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"cases": [{"id": "q1"}]}), encoding="utf-8")
    H._stamp_manual_fields(str(p), {"n": 1, "questions_sha256": "abc"})
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["holdout"] == {"n": 1, "questions_sha256": "abc"}
    for k, v in H.MANUAL_DEFAULTS.items():
        assert d["cases"][0][k] == v, f"{k} 应该留默认空值，由人填"


def test_stamp_manual_fields_does_not_clobber_filled_values(tmp_path):
    """重跑一次 --verdict 之类的动作不该把人工填的判定冲掉。"""
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"cases": [{"id": "q1", "human_correct": False, "reason": "编数字"}]}),
                 encoding="utf-8")
    H._stamp_manual_fields(str(p), {})
    c = json.loads(p.read_text(encoding="utf-8"))["cases"][0]
    assert c["human_correct"] is False and c["reason"] == "编数字"


# ---------------------------------------------------------------- rendered_cases（防回归）

def _one_result(cid="q1", dataset="shop"):
    case = EvalCase(id=cid, category="aggregation", question="?", ground_truth="result = 1",
                    dataset=dataset)
    return {"case": case}


def test_report_passes_none_by_default(monkeypatch):
    """默认路径：`rendered_cases` 不传时，透传给 rendered_fingerprints 的是 None。

    None 会让它回落到 ALL_CASES —— 与这个参数出现之前逐字节相同。
    这条红了说明默认行为被改了，所有新报告的 rendered_set_sha12 会与历史不同。
    """
    seen = {}

    def fake(cases=None, datasets=None, agent="react", use_dictionary=True):
        seen["cases"] = cases
        return {"supported": False, "reason": "stub"}

    monkeypatch.setattr("app.eval.fingerprint.rendered_fingerprints", fake)
    EvalReport([_one_result()], meta={}).fingerprint()
    assert seen["cases"] is None


def test_report_forwards_given_cases(monkeypatch):
    """传了就用传的：留出集靠这个避免按 130 题渲染时 KeyError。"""
    seen = {}

    def fake(cases=None, datasets=None, agent="react", use_dictionary=True):
        seen["cases"] = cases
        return {"supported": False, "reason": "stub"}

    monkeypatch.setattr("app.eval.fingerprint.rendered_fingerprints", fake)
    cases = [EvalCase(id="q1", category="aggregation", question="?", ground_truth="result = 1",
                      dataset="shop")]
    EvalReport([_one_result()], meta={}, rendered_cases=cases).fingerprint()
    assert seen["cases"] is cases
