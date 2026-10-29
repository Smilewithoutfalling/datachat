# -*- coding: utf-8 -*-
"""多轮用例与多轮报告块的测试。

守三件事：
1. oracle 桩的"一轮 = 一个模型实例"前提。这条踩过：`chat_model` 建在轮次循环外，
   桩内部按调用次数计数（第 1 次发工具调用、第 2 次给结论），于是第 2 轮起只回文本、
   不执行代码，13 条多轮题全部 executed=False。
2. `multi_turn_block` 的分母口径（`any` 轮不计入"受约束轮次"）。
3. 逐轮字段真的落进 JSON —— 算了不落盘等于没测。
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import LLMConfig  # noqa: E402
from app.core.testing import oracle_model  # noqa: E402
from app.eval.case_model import EvalCase  # noqa: E402
from app.eval.cases import ALL_CASES  # noqa: E402
from app.eval.report import EvalReport  # noqa: E402
from app.eval.runner import EvalRunner  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sample_eval.csv")

MULTI = [c for c in ALL_CASES if c.turns]


# ---------------------------------------------------------------- 用例本身

def test_multi_cases_exist_and_are_multi_turn():
    """多轮题不能是 0 条 —— 0 条时 state 模式跑起来是空转，这个断言是那条链路的门闩。"""
    assert len(MULTI) >= 10
    assert all(len(c.turns) >= 2 for c in MULTI)


def test_multi_cases_last_turn_is_the_question():
    """question 必须逐字等于 turns[-1]。重复校验一次是因为 validate 是模块级跑的，
    报错信息只在 import 时出现一次，改坏了不容易被看见。"""
    for c in MULTI:
        assert c.question == c.turns[-1], c.id
        assert len(c.expect_turns) == len(c.turns), c.id


def test_multi_cases_have_own_category():
    """多轮单独成类。混进 aggregation 之类，分类表就读不出"多轮表现"这个数了。"""
    for c in MULTI:
        assert c.category == "multi_turn", c.id


def test_last_turn_is_never_self_contained():
    """最后一轮必须是"离开上文就答不了"的写法。

    机器判不了语义，只判一个弱条件：最后一轮不能把表名/筛选值重新说一遍 ——
    真重说一遍的话，这条用例退化成"连续两个单轮"，测不出记忆。
    """
    for c in MULTI:
        last = c.turns[-1]
        # 独立作答题通常会重复指标名与维度；用"本轮问题里出现上一轮的数字/地区"当反例太脆，
        # 这里只钉住最明显的一种：最后一轮不该原样重复第一轮的完整问句
        assert last != c.turns[0], c.id


# ---------------------------------------------------------------- 执行器：每轮一个模型实例

def test_oracle_runs_every_turn_of_a_multi_case():
    """回归：chat_model 建在循环外时，第 2 轮起 oracle 只回文本、不执行代码。

    这条用真执行器跑（不是 mock），因为 bug 在"实例被复用"这件事上，
    mock 掉执行器就复现不出来。
    """
    case = next(c for c in MULTI if c.id == "mul_003")
    runner = EvalRunner(DATA, agent="react", model_factory=lambda c: oracle_model(c.ground_truth, "react"),
                        llm_config=LLMConfig(api_key="t"))
    r = runner.run_single(case)
    assert r["executed"] is True, r.get("error")
    assert r["turn_status"] == ["ok", "ok"]
    assert len(r["turn_answers"]) == 2


def test_runner_passes_code_to_later_turns():
    """回归：history 只传 (q, a) 时，state 模式的工作状态块恒为空。

    `fold()` 只认 `snap.code` —— 没有代码就提取不出「筛选：dept == 研发」这类前提，
    于是 state 只剩历史文本块。实测 mul_013 第 3 轮因此把「研发部」丢了，算成全公司 52.92%。
    评测里跑 state 等于只跑了一半，这个断言是那条链路的门闩。
    """
    captured = []
    case = next(c for c in MULTI if c.id == "mul_013")       # 3 轮，前两轮都执行代码

    class Spy(EvalRunner):
        def _run_one(self, case, question, history, chat_model):
            captured.append(list(history or []))
            return super()._run_one(case, question, history, chat_model)

    runner = Spy(DATA, agent="react", model_factory=lambda c: oracle_model(c.ground_truth, "react"),
                 llm_config=LLMConfig(api_key="t"))
    runner.run_single(case)

    assert captured[0] == []                                  # 第 1 轮没有历史
    assert len(captured[1]) == 1 and len(captured[1][0]) == 3
    assert captured[1][0][2], "第 2 轮的 history 没带代码，state 的工作状态块会恒为空"
    assert captured[2][0][2] and captured[2][1][2]


def test_runner_passes_empty_code_when_turn_not_executed():
    """没执行的轮次必须传空代码。

    `fold()` 把「有 code 的快照」当作可信前提；把失败轮次的代码喂进去，
    下一轮就会基于一个从没成功过的筛选条件继续算 —— 错得很安静。
    """
    from types import SimpleNamespace

    from app.core.llm import TokenUsage

    captured = []
    case = next(c for c in MULTI if c.id == "mul_013")

    class Spy(EvalRunner):
        def _run_one(self, case, question, history, chat_model):
            captured.append(list(history or []))
            return SimpleNamespace(
                answer="a", code="result = 1", executed=False,   # 有代码但没执行成功
                error=None, error_kind=None, initial_error=None, attempts=0,
                expected=None, actual=None, result=None, chart_path=None,
                charts=[], chart_calls=0, chart_errors=[], chart_internal_errors=[],
                charts_discarded=0, timings={}, usage=TokenUsage(),
                memory_mode="off", history_tokens=0, memory_trimmed=[])

    runner = Spy(DATA, agent="react", llm_config=LLMConfig(api_key="t"))
    runner.run_single(case)
    assert captured[1][0][2] == ""


def test_off_path_ignores_the_code_element():
    """off 路径逐字节不变，这是「加代码不需要重跑 off 基线」的依据。

    `history_messages` 只取 h[0] / h[1]；多出来的第 3 个元素只给 state 的工作状态用。
    """
    from app.core.service import history_messages
    assert history_messages([("q1", "a1")]) == history_messages([("q1", "a1", "result = 1")])


def test_single_turn_case_has_empty_turn_fields():
    """单轮题的 turn_* 保持空列表（不是 None）：报告里的形状不随题目类型变。"""
    case = next(c for c in ALL_CASES if not c.turns)
    runner = EvalRunner(DATA, agent="react", model_factory=lambda c: oracle_model(c.ground_truth, "react"),
                        llm_config=LLMConfig(api_key="t"))
    r = runner.run_single(case)
    assert r["turn_answers"] == [] and r["turn_status"] == []


# ---------------------------------------------------------------- 报告块口径

def _res(case, turn_status):
    return {"case": case, "correct": True, "executed": True, "turn_status": turn_status,
            "memory_mode": "off", "history_tokens": 0, "memory_trimmed": []}


def _case(cid, n_turns, expects):
    return EvalCase(id=cid, category="multi_turn", question="q", ground_truth="result = 1",
                    turns=[f"t{i}" for i in range(n_turns)], expect_turns=expects)


def test_multi_turn_block_excludes_any_from_denominator():
    """`any` 轮不做检查，不能进分母 —— 否则"纯指令轮没执行代码"会被算成失败。"""
    c = _case("mul_901", 4, ["any", "any", "any", "inherit:已完成"])
    rep = EvalReport([_res(c, ["ok", "ok", "ok", "ok"])])
    mt = rep.multi_turn_block()
    assert mt["turns"] == 4
    assert mt["checked"] == 1
    assert mt["failed"] == 0
    assert mt["rate"] == 100.0
    assert mt["by_kind"] == {"inherit": {"checked": 1, "failed": 0}}


def test_multi_turn_block_lists_failures_with_turn_index():
    """失败要带轮次号。只说"这题有一条约束没过"，读的人还得自己数第几轮。"""
    c = _case("mul_902", 2, ["exec", "inherit:2024-03"])
    rep = EvalReport([_res(c, ["ok", "fail:inherit"])])
    mt = rep.multi_turn_block()
    assert mt["failed"] == 1
    assert mt["rate"] == 50.0
    assert mt["fails"] == [{"id": "mul_902", "turn": 2, "expect": "inherit:2024-03",
                            "status": "fail:inherit"}]


def test_multi_turn_block_none_without_multi_cases():
    """没有多轮题时返回 None，不返回一个全 0 的块 —— 全 0 会被读成"多轮全军覆没"。"""
    c = EvalCase(id="agg_001", category="aggregation", question="q", ground_truth="result = 1")
    assert EvalReport([_res(c, [])]).multi_turn_block() is None


def test_multi_turn_block_missing_status_counts_as_fail():
    """turn_status 比 expect_turns 短（执行器提前返回）时，缺的那轮算失败而不是跳过。"""
    c = _case("mul_903", 2, ["exec", "exec"])
    rep = EvalReport([_res(c, ["ok"])])
    mt = rep.multi_turn_block()
    assert mt["checked"] == 2 and mt["failed"] == 1


# ---------------------------------------------------------------- 落盘

def test_turn_fields_land_in_json(tmp_path):
    """逐轮字段必须进 JSON。算了不落盘，事后判断不了"第 2 轮是没继承还是算错了"。"""
    c = _case("mul_904", 2, ["exec", "exec"])
    r = _res(c, ["ok", "ok"])
    r["turn_answers"] = ["第一轮答案", "第二轮答案"]
    out = tmp_path / "r.json"
    EvalReport([r]).to_json(str(out))
    d = json.loads(out.read_text(encoding="utf-8"))
    row = d["cases"][0]
    assert row["turns"] == ["t0", "t1"]
    assert row["turn_status"] == ["ok", "ok"]
    assert row["turn_answers"] == ["第一轮答案", "第二轮答案"]
    assert d["multi_turn"]["cases"] == 1
