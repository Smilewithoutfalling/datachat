"""漂移哨兵（`scripts/eval/canary.py`）—— 只测比对逻辑，不调模型。

真跑由 `run_eval.py --canary` 负责，产物在 `outputs/`（不进库）。这里用合成报告钉住
三件事：**判对数取最少的一轮而不是均值**、**usage 只比两边都有数的维度**、
**换了尺子就不能叫漂移**。这三条任何一条写反，哨兵都会用假警报把人练到不看它。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.eval.canary import CANARY_IDS  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "canary_drift", os.path.join(ROOT, "scripts", "eval", "canary.py"))
drift = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drift)

C_OK = "c" * 12
K_OK = "k" * 12
J_OK = "j" * 12


def _report(tmp_path, name="r.json", *, wrong=(), code=K_OK, canary=C_OK, judge=J_OK,
            usage=None, answers=None, ids=None, run=1, missing=None, expected="42"):
    ids = list(ids or CANARY_IDS)
    rows = []
    for i in ids:
        u = dict((usage or {}).get(i, {"tokens_in": 100, "tokens_out": 10}))
        rows.append({"id": i, "correct": i not in wrong,
                     "answer": (answers or {}).get(i, f"{i}:{expected}"),
                     "expected": expected,
                     "result_missing": (missing or {}).get(i), **u})
    fps = {"code_sha12": code}
    if judge is not None:
        fps["judge_sha12"] = judge
    data = {"canary": canary is not None, "canary_sha12": canary,
            "fingerprints": fps, "model": "m", "agent": "react",
            "run": run, "cases": rows}
    p = tmp_path / name
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


def _runs(tmp_path, **kw):
    return [drift.load_run(_report(tmp_path, name=f"r{k}.json", run=k, **kw)) for k in (1, 2, 3)]


# ---------------------------------------------------------------- 读入


def test_load_rejects_non_canary_report(tmp_path):
    """全量报告当探针，读数变化里会混进选题变化 —— 必须当场拒绝，不是只警告。"""
    with pytest.raises(ValueError, match="不是 canary"):
        drift.load_run(_report(tmp_path, canary=None))


def test_load_rejects_missing_probe(tmp_path):
    with pytest.raises(ValueError, match="ord_013"):
        drift.load_run(_report(tmp_path, ids=[i for i in CANARY_IDS if i != "ord_013"]))


def test_load_keeps_answer_hash_not_raw_text(tmp_path):
    """基线里只该有哈希：探针比的是"是不是同一句话"，留全文既无用又占地方。"""
    run = drift.load_run(_report(tmp_path, answers={"ord_007": "832.54"}))
    assert run["cases"]["ord_007"]["answer_sha12"] == drift._sha12("832.54")
    assert "832.54" not in json.dumps(run, ensure_ascii=False)


# ---------------------------------------------------------------- 汇总口径


def test_min_correct_is_the_worst_run_not_the_mean(tmp_path):
    """三跑 10/10、10/10、9/10：均值 96.7% 会把"有一跑掉了题"摊平。基线要记 9。"""
    runs = [drift.load_run(_report(tmp_path, name=f"r{k}.json", run=k,
                                   wrong=("ts_010",) if k == 3 else ())) for k in (1, 2, 3)]
    s = drift.summarize(runs)
    assert s["correct_per_run"] == [10, 10, 9]
    assert s["min_correct"] == 9
    assert s["accuracy"] == round(29 / 30, 4)
    assert s["flips"] == 1


def test_answer_varied_is_recorded_but_flips_follow_verdict(tmp_path):
    """文本变了而判定没变 ≠ 翻转。两个数分开记，才能分清是模型在动还是判分器在动。"""
    runs = [drift.load_run(_report(tmp_path, name=f"r{k}.json", run=k,
                                   answers={"ord_007": f"832.5{k}"})) for k in (1, 2)]
    s = drift.summarize(runs)
    assert s["answer_varied"] == 1     # ord_007 的说法两轮不同
    assert s["flips"] == 0             # 但两轮都判对


def test_usage_ratio_only_over_components_that_exist(tmp_path):
    """本网关不回 cache_read / reasoning：比例只在 in/out 上算，不能凭空补 0。"""
    s = drift.summarize(_runs(tmp_path))
    assert s["usage_components"] == ["tokens_in", "tokens_out"]
    assert s["usage_ratio"] == {"tokens_in": round(1000 / 1100, 4),
                               "tokens_out": round(100 / 1100, 4)}


def test_summarize_refuses_to_mix_code_versions(tmp_path):
    """两份报告隔着一次 A 组改动：平均出来的数两边都不成立，且汇总上看不出来。"""
    runs = [drift.load_run(_report(tmp_path, name="a.json", run=1)),
            drift.load_run(_report(tmp_path, name="b.json", run=2, code="9" * 12))]
    with pytest.raises(ValueError, match="code_sha12"):
        drift.summarize(runs)


def test_summarize_refuses_to_mix_question_sets(tmp_path):
    runs = [drift.load_run(_report(tmp_path, name="a.json", run=1)),
            drift.load_run(_report(tmp_path, name="b.json", run=2, canary="d" * 12))]
    with pytest.raises(ValueError, match="不同题单"):
        drift.summarize(runs)


# ---------------------------------------------------------------- 判定


def test_clean_when_nothing_moved(tmp_path):
    base = drift.summarize(_runs(tmp_path))
    cur = drift.summarize(_runs(tmp_path))
    v = drift.compare(base, cur)
    assert v["verdict"] == "clean"
    assert drift._EXIT[v["verdict"]] == 0


def test_wrong_answer_is_drift_and_names_the_probe(tmp_path):
    """真的算错一次就该报：基线 50 次判定零误判，一次算错不是噪声。"""
    base = drift.summarize(_runs(tmp_path))
    cur = drift.summarize(_runs(tmp_path, wrong=("ord_013",)))
    v = drift.compare(base, cur)
    assert v["verdict"] == "drift"
    assert any("算错" in r and "ord_013" in r for r in v["reasons"])
    assert drift._EXIT[v["verdict"]] == 1


def test_unsubmitted_but_correct_is_contract_not_drift(tmp_path):
    """11-04 实测的形态：答 660（=gold）、代码只 print 没赋 `result`。换着题出，2/60。

    这类不是权重漂移（10-30 排除 ord_004 同一条理由），但也不能静默 —— 单独成档。
    """
    base = drift.summarize(_runs(tmp_path))
    cur = drift.summarize(_runs(tmp_path, wrong=("ord_013",),
                                missing={"ord_013": "no_assign"}))
    v = drift.compare(base, cur)
    assert v["verdict"] == "contract"
    assert drift._EXIT[v["verdict"]] == 0
    assert any("没交卷" in r and "ord_013" in r for r in v["reasons"])


def test_no_assign_without_gold_is_still_drift(tmp_path):
    """没赋值 + 答案里也没有 gold = 算错了顺手没交卷，不能拿"没交卷"当挡箭牌。"""
    base = drift.summarize(_runs(tmp_path))
    cur = drift.summarize(_runs(tmp_path, wrong=("ord_013",), missing={"ord_013": "no_assign"},
                                answers={"ord_013": "这题我算不出来"}))
    v = drift.compare(base, cur)
    assert v["verdict"] == "drift"
    assert any("算错" in r for r in v["reasons"])


def test_answer_mention_does_not_accept_substring(tmp_path):
    """`0.3` 是 `0.3665` 的子串：用 `in` 会把算错的判成算对，必须按数比。"""
    assert drift._mentions("相关系数 0.3665", "0.3665")
    assert not drift._mentions("相关系数 0.3665", "0.3")
    assert drift._mentions("合计 660 笔", "660")
    assert not drift._mentions("合计 6600 笔", "660")


def test_usage_ratio_moving_over_20_percent_is_drift(tmp_path):
    """out 占比从 9.1% 涨到 18.2%：相对 +100%，超容忍度。"""
    base = drift.summarize(_runs(tmp_path))
    heavy = {i: {"tokens_in": 100, "tokens_out": 100} for i in CANARY_IDS}
    cur = drift.summarize(_runs(tmp_path, usage=heavy))
    v = drift.compare(base, cur)
    assert v["verdict"] == "drift"
    assert any("tokens_out" in r for r in v["reasons"])


def test_usage_coverage_change_is_not_a_ratio_jump(tmp_path):
    """网关开始回 cache_read：这是"字段变了"，不是"比例涨了 100%"。
    算成比例会给出一个假数值，把真信号淹没。"""
    base = drift.summarize(_runs(tmp_path))
    with_cache = {i: {"tokens_in": 100, "tokens_out": 10, "tokens_cache_read": 50}
                  for i in CANARY_IDS}
    cur = drift.summarize(_runs(tmp_path, usage=with_cache))
    v = drift.compare(base, cur)
    assert v["verdict"] == "drift"
    assert any("覆盖变化" in r and "tokens_cache_read" in r for r in v["reasons"])


def test_answer_changed_alone_is_not_drift(tmp_path):
    """换了说法但答案对：不是漂移。把 answer sha 当判据会天天误报。"""
    base = drift.summarize(_runs(tmp_path))
    cur = drift.summarize(_runs(tmp_path, answers={i: f"{i}:换了说法" for i in CANARY_IDS}))
    assert drift.compare(base, cur)["verdict"] == "clean"


def test_judge_change_makes_the_baseline_stale_not_drift(tmp_path):
    """判分器或数据表动过，读数变化不能算到权重头上 —— 先重立基线，再谈漂移。"""
    base = drift.summarize(_runs(tmp_path))
    cur = drift.summarize(_runs(tmp_path, judge="9" * 12, wrong=("ord_013",)))
    v = drift.compare(base, cur)
    assert v["verdict"] == "stale_baseline"
    assert drift._EXIT[v["verdict"]] == 2
    # 仍然要说清观察到了什么，只是不下结论。
    assert any("ord_013" in r for r in v["reasons"])


def test_old_baseline_without_judge_sha_is_stale(tmp_path):
    """11-09 之前立的基线没有 judge_sha12：不能默认"同一把尺子"，要明说该重立。"""
    base = drift.summarize(_runs(tmp_path, judge=None))
    cur = drift.summarize(_runs(tmp_path))
    v = drift.compare(base, cur)
    assert v["verdict"] == "stale_baseline"
    assert any("judge_sha12" in r and "重立" in r for r in v["reasons"])


def test_product_code_change_alone_does_not_block_comparison(tmp_path):
    """2026-11-09 收窄：改 prompt / 工具不该让哨兵永久失效。

    code_sha12 覆盖 A 组全部源文件，一周改好几次。拿它当可比性判据，结果是每周一都是
    "该重立基线"（10 题 × 6 跑），而没人会为改一行 prompt 重跑六轮 —— 哨兵的失效方式
    不是报错，是被无视。所以只有 judge_sha12 变才 stale。
    """
    base = drift.summarize(_runs(tmp_path))
    cur = drift.summarize(_runs(tmp_path, code="9" * 12))
    v = drift.compare(base, cur)
    assert v["verdict"] == "clean"
    # 不拦，但必须留痕：出问题时这是最可能的解释。
    assert any("9" * 12 in r or "产品代码不同" in r for r in v["reasons"])


def test_product_code_change_still_surfaces_drift(tmp_path):
    """代码变了 + 读数掉了 → 仍判 drift（不是 stale），并把代码差异写进归因提示。"""
    base = drift.summarize(_runs(tmp_path))
    cur = drift.summarize(_runs(tmp_path, code="9" * 12, wrong=("ord_013",)))
    v = drift.compare(base, cur)
    assert v["verdict"] == "drift"
    assert any("ord_013" in r for r in v["reasons"])
    assert any("产品代码不同" in r for r in v["reasons"])


def test_canary_fingerprint_change_is_incomparable(tmp_path):
    """换了题单：读数压根不是同一件事，连"观察到的变化"都不该报成漂移。"""
    base = drift.summarize(_runs(tmp_path))
    cur = drift.summarize(_runs(tmp_path, canary="d" * 12))
    v = drift.compare(base, cur)
    assert v["verdict"] == "incomparable"
    assert drift._EXIT[v["verdict"]] == 2
    assert len(v["reasons"]) == 1


# ---------------------------------------------------------------- 命令行接线


def test_init_records_judge_sha12(tmp_path):
    """基线必须记下判分口径，否则下次比对只能得到"缺字段"。

    这是 11-09 收窄判据的配套设施：`_compare` 用 `judge_sha12` 判 stale，
    基线里没有它就是每次都 stale，等于哨兵刚装上就又废了。
    """
    paths = [_report(tmp_path, name=f"r{k}.json", run=k) for k in (1, 2, 3)]
    base = tmp_path / "baseline.json"
    assert drift.main(paths + ["--init", "--baseline", str(base)]) == 0
    saved = json.loads(base.read_text(encoding="utf-8"))
    assert saved["judge_sha12"] == J_OK
    assert saved["code_sha12"] == K_OK
    assert saved["canary_sha12"] == C_OK


def test_init_refuses_to_overwrite_without_force(tmp_path, capsys):
    """基线不许被悄悄覆盖：自动更新等于让哨兵自己闭嘴。"""
    paths = [_report(tmp_path, name=f"r{k}.json", run=k) for k in (1, 2)]
    base = tmp_path / "baseline.json"
    base.write_text("{}", encoding="utf-8")
    code = drift.main(paths + ["--init", "--baseline", str(base)])
    assert code == 2
    assert "--force" in capsys.readouterr().err
    assert base.read_text(encoding="utf-8") == "{}"


def test_init_then_compare_roundtrip(tmp_path, capsys):
    paths = [_report(tmp_path, name=f"r{k}.json", run=k) for k in (1, 2)]
    base = tmp_path / "baseline.json"
    assert drift.main(paths + ["--init", "--baseline", str(base)]) == 0
    saved = json.loads(base.read_text(encoding="utf-8"))
    assert saved["min_correct"] == 10 and saved["runs"] == 2
    assert drift.main(paths + ["--baseline", str(base)]) == 0
    assert "CLEAN" in capsys.readouterr().out
