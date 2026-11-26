"""scripts/eval/grounding_fp.py（issue #132）：四类分类、两种证据口径、条目守恒。

报告和快照都在 tmp_path 里构造：快照按 app/assess/snapshot.py 的真格式写（run 行 + node 行），
读取走产品的 `snapshot.load`，不另写解析。
"""
import importlib.util
import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "grounding_fp", os.path.join(ROOT, "scripts", "eval", "grounding_fp.py"))
gfp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gfp)


def _case(cid, answer, missing=None, applicable=True, executed=True):
    return {"id": cid, "question": "q", "answer": answer, "executed": executed, "correct": True,
            "evidence": {"applicable": applicable, "failures": ["ANSWER_RESULT_MISMATCH"] if missing else [],
                         "detail": {"answer_nums_missing": missing} if missing else {}}}


def _snap(d, cid, question, result_text, metrics_block=None, original=None, started="2026-11-25T00:00:00+00:00",
          name=None, with_summarizer=True):
    state = {"question": question, "result_text": result_text}
    if metrics_block:
        state["metrics_block"] = metrics_block
    lines = [{"kind": "run", "case_id": cid, "question": original or question, "rewritten_question": question,
              "started_at_utc": started}]
    lines.append({"kind": "node", "seq": 1, "node": "executor", "occurrence": 1,
                  "input_state": {"question": question}, "updates": {"result_text": result_text}})
    if with_summarizer:
        lines.append({"kind": "node", "seq": 2, "node": "summarizer", "occurrence": 1,
                      "input_state": state, "updates": {"answer": "x"}})
    p = d / (name or f"{started[:10]}_{cid}.jsonl")
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ 节点 1：四类
@pytest.mark.parametrize("answer,raw,kind", [
    # 带单位的计数/金额：正例 3，反例见下面「其他」与「派生数」
    ("共有 1,061 单完成支付。", "1,061", gfp.K_COUNT),
    ("销售额为 ¥8,998.50。", "8,998.50", gfp.K_COUNT),
    ("华东区 82.2万 的营收最高。", "82.2万", gfp.K_COUNT),
    # 百分比
    ("毛利率为 24.93%。", "24.93%", gfp.K_PCT),
    ("退货率 3.5 个百分点的差别。", "3.5", gfp.K_PCT),
    ("占比 12.5％ 左右。", "12.5％", gfp.K_PCT),
    # 派生数
    ("比上月增长 1,200 单。", "1,200", gfp.K_DERIVED),
    ("各地区合计 952 单。", "952", gfp.K_DERIVED),
    ("是北京的 2.5 倍。", "2.5", gfp.K_DERIVED),
    # 其他
    ("编号 4521 的门店最好。", "4521", gfp.K_OTHER),
    ("评分 4.7 分。", "4.7", gfp.K_OTHER),
])
def test_classifies_four_kinds(answer, raw, kind):
    assert gfp.classify(raw, answer) == kind


def test_classify_counter_examples():
    # 反例：带单位但前面是派生词 → 派生数，不算计数/金额；百分号优先于派生词
    assert gfp.classify("300", "比去年减少 300 件。") == gfp.K_DERIVED
    assert gfp.classify("15%", "同比增长 15%。") == gfp.K_PCT
    # 反例：没有单位、没有派生词 → 其他，不算计数/金额
    assert gfp.classify("1234", "结果是 1234。") == gfp.K_OTHER


def test_two_evidence_scopes_differ_when_question_contains_number(tmp_path):
    # 问题原文有 500，result_text 没有：产品口径放行（证据含问题），评测口径列为未核实
    d = tmp_path / "snap"
    d.mkdir()
    _snap(d, "c1", "销售额超过 500 元的订单有多少？", "count    37")
    report = {"cases": [_case("c1", "超过 500 元的订单共 37 单，合计 1,061 单。", missing=["500", "1,061"])]}
    m = gfp.measure(report, gfp.index_snapshots(str(d)))
    got = {e["number"]: (e["product_unverified"], e["eval_unverified"]) for e in m["entries"]}
    assert got["500"] == (False, True)          # 只有评测口径认为未核实
    assert got["1,061"] == (True, True)         # 两种口径都未核实
    assert m["by_kind"][gfp.K_COUNT]["仅评测口径"] == 1


def test_product_scope_uses_metrics_block_and_original_question(tmp_path):
    d = tmp_path / "snap"
    d.mkdir()
    # metrics_block 里有 0.35，改写前的原问题里有 2,000
    _snap(d, "c2", "改写后的问题", "result 12", metrics_block="毛利口径：0.35",
          original="原问题提到 2,000 元")
    report = {"cases": [_case("c2", "毛利率 35%，门槛 2,000 元。", missing=["35%", "2,000"])]}
    m = gfp.measure(report, gfp.index_snapshots(str(d)))
    assert all(e["product_unverified"] is False for e in m["entries"])
    assert all(e["eval_unverified"] is True for e in m["entries"])


def test_every_unverified_entry_is_listed(tmp_path):
    d = tmp_path / "snap"
    d.mkdir()
    _snap(d, "a", "问题 a", "x 1")
    _snap(d, "b", "问题 b", "y 2", with_summarizer=False)   # 无 summarizer（如 ReAct）：产品口径算不出
    report = {"cases": [
        _case("a", "共 1,061 单，均值 88.8，占比 12%。", missing=["1,061", "88.8", "12%"]),
        _case("b", "共 300 件。", missing=["300"]),
        _case("c", "无法回答：缺列。", applicable=False, executed=False),
        _case("d", "共 777 单。", missing=None),                       # 评测口径无条目
    ]}
    m = gfp.measure(report, gfp.index_snapshots(str(d)))
    # 评测口径的每一条都在表里（逐条不丢）
    listed = [(e["id"], e["number"]) for e in m["entries"] if e["eval_unverified"]]
    assert len(listed) == m["eval_total"] == 4
    # 表的条目数 = 每题两种口径并集之和
    assert len(m["entries"]) == 4 + 0
    assert m["no_snapshot"] == ["b", "d"]
    b = [e for e in m["entries"] if e["id"] == "b"][0]
    assert b["product_unverified"] is None
    md = gfp.render_md(m, "r.json")
    assert md.count("\n| a |") == 3 and "| b | 300 |" in md


def test_multi_turn_takes_latest_snapshot(tmp_path):
    d = tmp_path / "snap"
    d.mkdir()
    _snap(d, "m1", "第 1 轮", "1,061", started="2026-11-25T00:00:00+00:00", name="1.jsonl")
    _snap(d, "m1", "第 2 轮", "84", started="2026-11-25T00:01:00+00:00", name="2.jsonl")
    report = {"cases": [_case("m1", "共 1,061 单。", missing=["1,061"])]}
    m = gfp.measure(report, gfp.index_snapshots(str(d)))
    assert m["entries"][0]["product_unverified"] is True   # 用的是第 2 轮（最后一轮）的证据


def test_cli_exit_codes(tmp_path, capsys):
    d = tmp_path / "snap"
    d.mkdir()
    r = tmp_path / "r.json"
    r.write_text(json.dumps({"cases": [_case("a", "共 1,061 单。", missing=["1,061"])]}), encoding="utf-8")
    out = tmp_path / "o.md"
    assert gfp.main([str(r), "--snapshots", str(d), "--md", str(out)]) == 0
    assert "待标注清单" in out.read_text(encoding="utf-8")
    assert gfp.main([str(tmp_path / "nope.json"), "--snapshots", str(d)]) == 2
    assert gfp.main([str(r), "--snapshots", str(tmp_path / "nodir")]) == 2
    g = tmp_path / "g.json"
    g.write_text(json.dumps({"cases": [], "auto_correct": 1}), encoding="utf-8")
    assert gfp.main([str(g), "--snapshots", str(d)]) == 2
