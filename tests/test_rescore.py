"""apply_rescore：把重算的判定写回报告，且不丢"模型跑在哪份代码上"。

存在的理由：判分器在 A 组指纹里，改它会让 code_sha12 变。不把跑的指纹单独留一份，
之后看到一份报告就没法回答"这是哪套被测系统跑出来的、用哪套尺子判的"。
"""
import json

import app.eval.rescore as R


def _report(tmp_path, cases, correct=1):
    path = tmp_path / "r.json"
    data = {
        "git_sha": "deadbeef", "agent": "react",
        "fingerprints": {"code_sha12": "aaaaaaaaaaaa"},
        "overall": {"n": len(cases), "correct": correct, "executed": len(cases),
                    "correctness_rate": 0.0, "conditional_correctness_rate": 0.0, "match_kinds": {}},
        "by_category": {"aggregation": {"n": len(cases), "correct": correct,
                                        "correctness_rate": 0.0, "match_kinds": {}}},
        "by_dataset": {"sales": {"n": len(cases), "correct": correct,
                                 "correctness_rate": 0.0, "match_kinds": {}}},
        "cases": cases,
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


CASES = [
    {"id": "a", "category": "aggregation", "dataset": "sales", "correct": False, "match": None, "executed": True},
    {"id": "b", "category": "aggregation", "dataset": "sales", "correct": True, "match": "strict", "executed": True},
    {"id": "c", "category": "aggregation", "dataset": "sales", "correct": True, "match": "relaxed", "executed": False},
]


def _fake_result(changed_ids=("a",)):
    rows = [{"id": "a", "category": "aggregation", "dataset": "sales", "correct": True, "match": "extras"},
            {"id": "b", "category": "aggregation", "dataset": "sales", "correct": True, "match": "strict"},
            {"id": "c", "category": "aggregation", "dataset": "sales", "correct": False, "match": None}]
    return {"rows": rows, "changed": [{"id": i, "before": False, "after": True} for i in changed_ids],
            "correct": 2, "n": 3}


def test_apply_rescore_updates_verdicts_and_counts(tmp_path, monkeypatch):
    monkeypatch.setattr("app.eval.fingerprint.code_fingerprint",
                        lambda: {"affects_results_sha256": "bbbbbbbbbbbb"})
    path = _report(tmp_path, [dict(c) for c in CASES])
    out = R.apply_rescore(path, _fake_result())

    data = json.load(open(path, encoding="utf-8"))
    by_id = {c["id"]: c for c in data["cases"]}
    assert by_id["a"]["correct"] is True and by_id["a"]["match"] == "extras"
    assert by_id["c"]["correct"] is False
    assert data["overall"]["correct"] == 2
    assert data["overall"]["correctness_rate"] == 2 / 3 * 100
    # 只算执行过的：a、b 两条 executed 且都对（c 没执行，不进分母）
    assert data["overall"]["conditional_correctness_rate"] == 100.0
    assert data["overall"]["match_kinds"] == {"extras": 1, "strict": 1}
    assert data["by_category"]["aggregation"]["correct"] == 2
    assert data["by_dataset"]["sales"]["match_kinds"] == {"extras": 1, "strict": 1}
    assert out["scorer_sha12"] == "bbbbbbbbbbbb"


def test_apply_rescore_keeps_runner_fingerprint(tmp_path, monkeypatch):
    """跑时指纹必须留一份：判分器改了 code_sha12 会变，但没有它就无法溯源。"""
    monkeypatch.setattr("app.eval.fingerprint.code_fingerprint",
                        lambda: {"affects_results_sha256": "bbbbbbbbbbbb"})
    path = _report(tmp_path, [dict(c) for c in CASES])
    R.apply_rescore(path, _fake_result())

    data = json.load(open(path, encoding="utf-8"))
    assert data["run_code_sha12"] == "aaaaaaaaaaaa"      # 原来那份
    assert data["fingerprints"]["code_sha12"] == "bbbbbbbbbbbb"   # 现在的尺子
    assert data["rescored"][-1]["runner_before"] == "aaaaaaaaaaaa"
    assert data["rescored"][-1]["scorer"] == "bbbbbbbbbbbb"


def test_apply_rescore_second_time_keeps_original_runner(tmp_path, monkeypatch):
    """重复写回不能把 run_code_sha12 覆盖成上一轮的尺子指纹。"""
    monkeypatch.setattr("app.eval.fingerprint.code_fingerprint",
                        lambda: {"affects_results_sha256": "bbbbbbbbbbbb"})
    path = _report(tmp_path, [dict(c) for c in CASES])
    R.apply_rescore(path, _fake_result())
    R.apply_rescore(path, _fake_result(changed_ids=()))

    data = json.load(open(path, encoding="utf-8"))
    assert data["run_code_sha12"] == "aaaaaaaaaaaa"
    assert len(data["rescored"]) == 2
    assert data["rescored"][1]["changed"] == []


def test_apply_rescore_does_not_touch_model_output(tmp_path, monkeypatch):
    """只改判定。code / answer / actual 是证据，重打分不许动。"""
    monkeypatch.setattr("app.eval.fingerprint.code_fingerprint",
                        lambda: {"affects_results_sha256": "bbbbbbbbbbbb"})
    cases = [dict(c, code="result = 1", answer="1", actual="1") for c in CASES]
    path = _report(tmp_path, cases)
    R.apply_rescore(path, _fake_result())

    data = json.load(open(path, encoding="utf-8"))
    for c in data["cases"]:
        assert c["code"] == "result = 1"
        assert c["answer"] == "1"
        assert c["actual"] == "1"
