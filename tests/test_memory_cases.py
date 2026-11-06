"""记忆专项题的离线验收（批 4 评测侧接线，R7/R10）。

判分绿不代表口径真的进了 prompt——oracle 假模型根本不读 prompt。这里的正控是：
拿 ScriptedChatModel 抓住每次调用的原始 messages，断言口径名与 body 片段
逐字出现在模型实际收到的文本里；off 档断言它们一个字都不出现。
"""
import pytest

from app.core.testing import oracle_model, prompt_text
from app.eval.cases import ALL_CASES
from app.eval.runner import EvalRunner
from app.eval.validate import validate_cases


def _case(cid: str):
    return next(c for c in ALL_CASES if c.id == cid)


# ---------------------------------------------------------------- 注入正控

def test_notes_reach_prompt_state():
    """state 档：口径名 + body 片段必须出现在模型实际收到的 prompt 里。"""
    c = _case("mem_001")
    m = oracle_model(c.ground_truth, "workflow")   # 单实例：跑完从 m.calls 抓原始 prompt
    r = EvalRunner(agent="workflow", memory_mode="state", model_factory=lambda _c: m)
    out = r.run_single(c)
    assert out["correct"], out.get("error")
    text = "\n".join(prompt_text(msgs) for msgs in m.calls)
    assert "实收销售额" in text, "口径名没出现在任何一次 prompt 里"
    assert "1.05" in text, "口径 body（含 1.05 公式）没出现在 prompt 里"
    # R10：抄录链路 —— runner 的 out 里必须有 notes（含 name）
    names = [n.get("name") for n in out["memory_notes"]]
    assert "实收销售额" in names, f"memory_notes 抄录断了：{out['memory_notes']}"


def test_notes_absent_when_off():
    """off 档：同一题、同一份口径，口径 body 不许出现在 prompt 里（P8 的评测侧镜像）。

    注意不能用口径名当判据 —— 问题原文「全表的实收销售额合计…」本身就含这四个字，
    它是用户输入不是注入；能证明"没注入"的是 body 独有的片段（1.05 / 渠道服务费）。
    """
    c = _case("mem_001")
    m = oracle_model(c.ground_truth, "workflow")
    r = EvalRunner(agent="workflow", memory_mode="off", model_factory=lambda _c: m)
    out = r.run_single(c)
    text = "\n".join(prompt_text(msgs) for msgs in m.calls)
    assert "1.05" not in text and "渠道服务费" not in text
    assert out["memory_notes"] == [], "off 档 memory_notes 必须是空列表"


# ---------------------------------------------------------------- runner 透传

def test_refusal_still_holds_with_notes():
    """反向回归（评测侧镜像记忆侧闸门）：口径引用缺失字段时，oracle 桩按 gold 走，
    negative 判据照常生效 —— 注入口径不许把拒答题变成可答题。
    （oracle 的 result 就是拒答文本，refusal_text 从 result/answer 取，判据照常命中。）"""
    c = _case("mem_003")
    m = oracle_model(c.ground_truth, "workflow")
    r = EvalRunner(agent="workflow", memory_mode="state", model_factory=lambda _c: m)
    out = r.run_single(c)
    assert out["correct"], (out.get("error"), out.get("negative_why"))
    assert out["match"] == "impossible"
    assert "net_amount" in str(out.get("actual"))


# ---------------------------------------------------------------- 校验规则

def _mk(**kw):
    from app.eval.case_model import EvalCase
    base = dict(id="mem_900", category="memory", dataset="sales",
                question="q", ground_truth="result = 1", keywords=[])
    base.update(kw)
    return EvalCase(**base)


def test_validate_requires_memory_rules():
    notes = [{"kind": "metric", "name": "x", "body": "y", "unit": "", "synonyms": ""}]
    assert validate_cases([_mk(dataset_notes=notes, requires_memory="state")]) == []
    errs = validate_cases([_mk(dataset_notes=notes)])           # 有口径没标档位
    assert any("requires_memory" in e for e in errs)
    errs = validate_cases([_mk(dataset_notes=[{"kind": "bad", "name": "x", "body": "y"}],
                               requires_memory="state")])
    assert any("kind" in e for e in errs)
    errs = validate_cases([_mk(requires_memory="bogus")])
    assert any("requires_memory" in e for e in errs)
    errs = validate_cases([_mk(rewrite=True)])                  # off 档改写不生效，必须标档位
    assert any("rewrite" in e for e in errs)
    errs = validate_cases([_mk(today="2024/01/01")])
    assert any("today" in e for e in errs)
    errs = validate_cases([_mk(requires_memory="full")])        # 什么都不依赖的档位题
    assert any("测不出档位差异" in e for e in errs)


# ---------------------------------------------------------------- 报告汇总

def test_report_memory_block_keys():
    """memory_block：四个 trimmed 键恒存在（列不随档位漂移），notes_used 汇总去重。"""
    from app.eval.report import EvalReport
    c = _case("mem_001")
    m = oracle_model(c.ground_truth, "workflow")
    r = EvalRunner(agent="workflow", memory_mode="state", model_factory=lambda _c: m)
    out = r.run_single(c)
    rep = EvalReport([out], meta={"memory_mode": "state"})
    mb = rep.memory_block()
    assert set(mb["trimmed_cases"]) == {"history", "state", "constraints", "notes"}
    assert "实收销售额" in mb["notes_used"]
