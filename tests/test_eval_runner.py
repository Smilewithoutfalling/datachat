"""执行器的多轮编排（EV-A2）。

这里不造假模型，直接替换 `runner.analyze`：要验的是"history 有没有逐轮累积"、
"某个 turn 失败会不会中断最后一轮"，这两件事都发生在 analyze 之外。
用假模型还得让模型把 history 反射到回答里，绕远且更容易写错测试本身。
"""
import pytest

from app.core.llm import TokenUsage
from app.core.result import AnalysisResult
from app.eval import runner as runner_mod
from app.eval.case_model import EvalCase
from app.eval.runner import EvalRunner


def _res(question, *, answer=None, code="", executed=True, result="x",
         error_kind=None, total=1.0, tokens=10, result_text=""):
    return AnalysisResult(
        agent="react", dataset="d.csv", question=question,
        answer=answer if answer is not None else f"答{question}",
        code=code, executed=executed, result=result if executed else None,
        result_text=result_text,
        error=None if error_kind is None else "boom", error_kind=error_kind,
        timings={"total": total},
        usage=TokenUsage(calls=1, total_tokens=tokens, reported=True),
    )


def _multi(**kw):
    base = dict(id="tmp_001", category="aggregation", question="第二轮",
                ground_truth="result = len(df)",
                turns=["第一轮", "第二轮"], expect_turns=["exec", "exec"])
    base.update(kw)
    return EvalCase(**base)


def test_multiturn_history_is_passed_incrementally(monkeypatch):
    seen = []

    def fake_analyze(path, question, **kw):
        # 必须存快照：history 是同一个列表被逐轮 append 的，存引用会让第 1 次也显示成满的
        seen.append((question, list(kw.get("history") or [])))
        return _res(question, code=f"result = '{question}'")

    monkeypatch.setattr(runner_mod, "analyze", fake_analyze)
    r = EvalRunner(agent="react").run_single(_multi())

    assert [q for q, _ in seen] == ["第一轮", "第二轮"]
    assert seen[0][1] == []                              # 多轮首轮：有 history 概念，但还没内容
    # 第三个元素是代码：state 模式靠它抽出「筛选 / 分组 / 时间范围」，不给就只剩历史文本块
    assert seen[1][1] == [("第一轮", "答第一轮", "result = '第一轮'")]
    assert r["turn_answers"] == ["答第一轮", "答第二轮"]
    assert r["turn_status"] == ["ok", "ok"]


def test_single_turn_passes_none_not_empty_list(monkeypatch):
    seen = []

    def fake_analyze(path, question, **kw):
        seen.append(kw.get("history"))
        return _res(question)

    monkeypatch.setattr(runner_mod, "analyze", fake_analyze)
    case = EvalCase(id="tmp_002", category="aggregation", question="只有一个问题",
                    ground_truth="result = len(df)")
    r = EvalRunner(agent="react").run_single(case)
    assert seen == [None]                                # 不是 []：单轮不该被当成多轮首轮
    assert r["turn_answers"] == [] and r["turn_status"] == []


def test_turn_error_does_not_abort_final_turn(monkeypatch):
    """中间轮 LLM 失败时，最后一轮照跑；失败轮的答案按空串进 history，不塞占位文案。"""
    calls = []

    def fake_analyze(path, question, **kw):
        calls.append((question, list(kw.get("history") or [])))
        if question == "第一轮":
            return _res(question, answer="", executed=False, error_kind="llm")
        return _res(question)

    monkeypatch.setattr(runner_mod, "analyze", fake_analyze)
    case = _multi(ground_truth="result = 'x'")   # 假结果就是 'x'，让打分这一层也能走通
    r = EvalRunner(agent="react").run_single(case)

    assert len(calls) == 2
    # 第三个元素是代码；这一轮 LLM 失败（executed=False），代码位必须是空串——
    # fold() 把「有 code 的快照」当可信前提，把失败轮的代码喂进去等于给下一轮一个假前提
    assert calls[1][1] == [("第一轮", "", "")]
    assert r["turn_status"] == ["error", "ok"]
    assert r["executed"] is True and r["correct"] is True   # 最后一轮照常打分
    assert r["infra_error"] is False                       # 最终有答案，不算基础设施失败


def test_failed_turn_marks_infra_when_last_turn_fails(monkeypatch):
    monkeypatch.setattr(runner_mod, "analyze",
                        lambda p, q, **kw: _res(q, answer="", executed=False, error_kind="llm"))
    r = EvalRunner(agent="react").run_single(_multi())
    assert r["infra_error"] is True and r["executed"] is False


@pytest.mark.parametrize("expect,fields,status", [
    ("exec", dict(executed=True), "ok"),
    ("exec", dict(executed=False), "fail:exec"),
    ("refusal", dict(executed=False, result=None, answer="无法回答：表里没有成本字段"), "ok"),
    ("refusal", dict(executed=False, result=None, answer="我觉得是华东"), "fail:refusal"),
    ("any", dict(executed=False), "ok"),
    ("inherit:region", dict(executed=True, code="df.groupby('region').sum()"), "ok"),
    ("inherit:region", dict(executed=True, code="df.sum()"), "fail:inherit"),
    ("inherit:", dict(executed=True, code="df.sum()"), "ok"),   # 空 regex 匹配一切，但 validate 会挡
])
def test_turn_status_semantics(expect, fields, status):
    fields.setdefault("answer", "答")
    r = _res("q", **fields)
    assert EvalRunner._turn_status(r, expect) == status


def test_infra_error_wins_over_fail(monkeypatch):
    """超时导致没执行代码，记 fail:exec 会把基础设施问题算成能力问题。"""
    r = _res("q", executed=False, error_kind="llm")
    assert EvalRunner._turn_status(r, "exec") == "error"


def test_multiturn_tokens_are_summed(monkeypatch):
    """多轮成本是各轮之和；只记最后一轮会低估，报告里的 tokens 就没人敢用了。"""
    monkeypatch.setattr(runner_mod, "analyze", lambda p, q, **kw: _res(q, total=2.0, tokens=100))
    r = EvalRunner(agent="react").run_single(_multi())
    assert r["tokens"] == 200
    assert r["duration_s"] == pytest.approx(4.0)


# ---------------------------------------------------------------- 记忆字段（阶段 6.6）

def test_memory_fields_default_when_module_absent(monkeypatch):
    """批 1 合入前 AnalysisResult 没有 memory_* 字段：报告照跑，值恒为 off / 0 / []。

    这不是"容忍缺失"，是要报告形状稳定——同一条用例不能因为记忆模块合没合入，
    结果里就多一列或少一列，否则拼 CSV 和对比脚本会在某一版突然错位。
    """
    monkeypatch.setattr(runner_mod, "analyze", lambda p, q, **kw: _res(q))
    r = EvalRunner(agent="react").run_single(_multi())
    assert r["memory_mode"] == "off"
    assert r["history_tokens"] == 0
    assert r["memory_trimmed"] == []


def test_memory_trimmed_is_union_over_turns(monkeypatch):
    """多轮取全轮并集：消融要看"这条用例被裁过没有"，只看最后一轮会把前几轮的裁剪漏掉。"""
    rounds = {"第一轮": ("state", 1200, ["state"]), "第二轮": ("state", 3000, ["history"])}

    def fake_analyze(path, question, **kw):
        res = _res(question)
        res.memory_mode, res.history_tokens, res.memory_trimmed = rounds[question]
        return res

    monkeypatch.setattr(runner_mod, "analyze", fake_analyze)
    r = EvalRunner(agent="react").run_single(_multi())
    assert r["memory_mode"] == "state"
    assert r["history_tokens"] == 3000                   # 最后一轮：多轮里历史最长
    assert r["memory_trimmed"] == ["history", "state"]   # 并集且排序稳定


def test_memory_block_flags_mixed_modes():
    """一批里混了 off 和 state，报告必须标出来：混跑的分数不能当消融结果。"""
    from app.eval.report import EvalReport
    c1 = _multi(id="tmp_mem_1")
    c2 = EvalCase(id="tmp_mem_2", category="aggregation", question="q", ground_truth="result = 1")
    base = {"correct": False, "executed": False, "agent": "react", "duration_s": None,
            "tokens": None, "initial_error": False, "error": None}
    rep = EvalReport([
        dict(base, case=c1, memory_mode="off", history_tokens=0, memory_trimmed=[]),
        dict(base, case=c2, memory_mode="state", history_tokens=900, memory_trimmed=["history"]),
    ])
    mem = rep.memory_block()
    assert mem["modes"] == {"off": 1, "state": 1}
    assert mem["uniform"] is False
    # 2026-11-06（批 4）：恒四键 {"history","state","constraints","notes"} —— 有意从
    # "0 的不出现"改掉的：消融表的列不随档位漂移，没有的就是 0（见 report.memory_block）。
    assert mem["trimmed_cases"] == {"history": 1, "state": 0, "constraints": 0, "notes": 0}
    assert mem["trimmed_any"] == 1
    assert mem["avg_history_tokens"] == 450.0
    assert mem["notes_used"] == []          # 没跑口径题 → 空，当场能核对"口径没进 prompt"



# ---------------------------------------------------- 跨轮数字断言（recall_turn）
def _recall_runner(monkeypatch, turns_answers, turns_texts, *, recall_turn=1, last_answer):
    """多轮跑一遍 recall 断言：判分只看末轮，断言扫末轮 answer 里的数字能否追溯到前几轮。"""
    answers = list(turns_answers)
    answers[-1] = last_answer        # 末轮以 last_answer 为准，调用点不必再抄一遍
    it = iter(zip(answers, turns_texts))

    def fake_analyze(path, question, **kw):
        a, t = next(it)
        return _res(question, answer=a, code="result = 1", result_text=t)

    monkeypatch.setattr(runner_mod, "analyze", fake_analyze)
    case = _multi(id="tmp_recall", recall_turn=recall_turn,
                  ground_truth="result = 'x'",      # 与 _res 的 result 对齐，先让数值层判对
                  turns=["先算明细", "回到最初那个问题，再报一遍"],
                  expect_turns=["exec", "exec"])
    return EvalRunner(agent="react").run_single(case)


def test_recall_counts_prior_answer_as_evidence(monkeypatch):
    """派生数字只出现在前一轮 answer 里，也算有据 —— mem_006 三跑全挂的现场。

    第 1 轮 result_text 只有逐地区明细（模型 print 的东西），合计 952 / 49286 是它
    在 answer 里补的。末轮把这些一起复述，是"一致复述"，不是编造。
    """
    r = _recall_runner(
        monkeypatch,
        turns_answers=[
            "各地区明细如上；合计 952 件、49286 元",     # 第 1 轮 answer（派生值在这里）
            "回到最初：合计 952 件、49286 元",           # 末轮复述同一份
        ],
        turns_texts=["region\n华东 9480\n华中 12906", ""],
        last_answer="合计 952 件、49286 元",
    )
    assert r["correct"] is True
    assert r["recall_why"] == ""


def test_recall_still_catches_misremembered_number(monkeypatch):
    """反向：末轮把合计记成前几轮谁都没说过的值 → 照样抓得住。放宽只放宽"出处"，不放过"对不上"。"""
    r = _recall_runner(
        monkeypatch,
        turns_answers=["各地区明细如上；合计 952 件、49286 元", ""],
        turns_texts=["region\n华东 9480\n华中 12906", ""],
        last_answer="合计 962 件、49286 元",          # 952 → 962
    )
    assert r["correct"] is False
    assert "962" in r["recall_why"]


def test_recall_evidence_scope_is_prior_turns_only(monkeypatch):
    """末轮自己的 answer 不能当证据 —— 否则这断言恒真（自己证明自己）。"""
    r = _recall_runner(
        monkeypatch,
        turns_answers=["第一轮没提过任何合计", ""],
        turns_texts=["region\n华东 9480", ""],
        last_answer="合计 49286 元",                  # 只出现在末轮自己嘴里
    )
    assert r["correct"] is False
    assert "49,286" in r["recall_why"] or "49286" in r["recall_why"]


# ------------------------------------------------------------------ E3 run-id（破缓存后缀）

class _NoModel:
    """只让 build_react_agent 走完构造流程，不会被调用（与 fingerprint.py 同款）。"""

    def bind_tools(self, tools):
        return self


def test_run_suffix_appended_to_system_tail():
    """E3：run_suffix 原样出现在 system 最末尾，且只出现一次。

    位置必须是末尾：网关缓存按请求前缀命中，尾部的无语义行改的是缓存键的最后一截，
    对模型则是不带信息的指令，不应改变它对任务的理解。
    """
    from app.react_agent import build_react_agent
    from app.tools.dataset import load_data
    data, _desc = load_data("data/sample_eval.csv")
    cap = {}
    build_react_agent("data/sample_eval.csv", model=_NoModel(), df=data,
                      out_system=cap, run_suffix="\n\nrun-id: 2")
    assert cap["system"].endswith("run-id: 2")
    assert cap["system"].count("run-id") == 1


def test_run_suffix_default_keeps_system_byte_identical():
    """不传 run_suffix 与传空串的 system 逐字节一致，且串里不含 run-id 字样。

    P8 风格：单轮评测、指纹渲染都不传这个参数，prompt 必须和 E3 之前完全一样。
    渲染指纹（render_system）不传它，所以 run-id 不进指纹——k 轮报告仍然可比。
    """
    from app.react_agent import build_react_agent
    from app.tools.dataset import load_data
    data, _desc = load_data("data/sample_eval.csv")
    cap_a, cap_b = {}, {}
    build_react_agent("data/sample_eval.csv", model=_NoModel(), df=data, out_system=cap_a)
    build_react_agent("data/sample_eval.csv", model=_NoModel(), df=data,
                      out_system=cap_b, run_suffix="")
    assert cap_a["system"] == cap_b["system"]
    assert "run-id" not in cap_a["system"]


def test_runner_run_suffix_reaches_analyze(monkeypatch):
    """执行器把 run_suffix 透传给 analyze；默认显式 None，不让 analyze 侧靠猜。"""
    seen = []

    def fake_analyze(path, question, **kw):
        seen.append(kw.get("run_suffix"))
        return _res(question)

    monkeypatch.setattr(runner_mod, "analyze", fake_analyze)
    case = EvalCase(id="tmp_sfx", category="aggregation", question="q", ground_truth="result = 1")

    runner = EvalRunner(agent="react", run_suffix="\n\nrun-id: 2")
    runner._run_one(case, "q", None, None)
    assert seen[-1] == "\n\nrun-id: 2"

    runner_default = EvalRunner(agent="react")
    runner_default._run_one(case, "q", None, None)
    assert seen[-1] is None
