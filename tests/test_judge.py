"""EV-B8 judge 的契约测试。

judge 的可校准性全靠契约：二元、弃权单列、调用失败抛异常而不是返回 False、
temperature 锁死 0、order 可复现。每条契约一条测试，坏了哪条哪条红。
"""
import json

import pytest

from app.eval.judge import JudgeError, judge
from scripts.eval.judge_calibrate import kappa_2x2


class FakeModel:
    """invoke 一次返回一段预设文本。"""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        assert len(messages) == 2  # system + human
        out = self.outputs.pop(0) if self.outputs else ""
        return type("R", (), {"content": out})()


def _ok(pass_, conf="high", abstain=False, reason="r"):
    return json.dumps({"pass": pass_, "reason": reason, "confidence": conf, "abstain": abstain})


def test_judge_returns_contract_shape():
    m = FakeModel([_ok(True)])
    r = judge("q", "a", "g", "rub", model=m)
    assert set(r) >= {"pass", "reason", "confidence", "abstain"}
    assert r["pass"] is True and r["confidence"] == "high" and r["abstain"] is False


def test_judge_abstain_forces_pass_false():
    """abtain=True 时样本退出统计分母——pass 字段同时压成 False，防止调用方误用。"""
    m = FakeModel([_ok(True, abstain=True)])
    r = judge("q", "a", "g", "rub", model=m)
    assert r["abstain"] is True and r["pass"] is False


def test_judge_low_confidence_passes_through():
    m = FakeModel([_ok(True, conf="low")])
    r = judge("q", "a", "g", "rub", model=m)
    assert r["pass"] is True and r["confidence"] == "low"


def test_judge_bad_json_retries_once_then_raises():
    m = FakeModel(["这不是 JSON", "仍然不是"])
    with pytest.raises(JudgeError):
        judge("q", "a", "g", "rub", model=m)
    assert m.calls == 2  # 重试恰好一次，不无限循环


def test_judge_retry_recovers_after_first_bad_output():
    m = FakeModel(["（思考中……）", _ok(False)])
    r = judge("q", "a", "g", "rub", model=m)
    assert r["pass"] is False and m.calls == 2


def test_judge_network_error_raises_not_false():
    """调用失败必须抛 JudgeError——绝不能把基础设施故障算成模型答错。"""

    class Boom:
        def invoke(self, messages):
            raise ConnectionError("gateway down")

    with pytest.raises(JudgeError):
        judge("q", "a", "g", "rub", model=Boom())


def test_judge_temperature_locked_to_zero():
    m = FakeModel([_ok(True)])
    with pytest.raises(ValueError):
        judge("q", "a", "g", "rub", model=m, temperature=0.3)


def test_judge_order_invalid_value_rejected():
    with pytest.raises(ValueError):
        judge("q", "a", "g", "rub", model=FakeModel([_ok(True)]), order="random")


def test_judge_order_seed_reproducible():
    """同 seed 同 order——校准集的顺序分配要能复现。"""
    orders = set()
    for _ in range(20):
        r = judge("q", "a", "g", "rub", model=FakeModel([_ok(True)]), order=None, seed=42)
        orders.add(r["order"])
    assert len(orders) == 1


def test_judge_reason_from_model_kept():
    m = FakeModel([_ok(True, reason="数值 850854.16 与标准答案一致")])
    r = judge("q", "a", "g", "rub", model=m)
    assert "850854.16" in r["reason"]


# ------------------------------------------------------------------ κ 手写实现

def test_kappa_perfect_agreement():
    cm = {(True, True): 10, (False, False): 10}
    assert kappa_2x2(cm) == 1.0


def test_kappa_known_value():
    """对照手算：p_o=0.8，p_j=0.5，p_l=0.5，p_e=0.5 → κ=(0.8-0.5)/0.5=0.6。"""
    cm = {(True, True): 4, (True, False): 1, (False, True): 1, (False, False): 4}
    assert abs(kappa_2x2(cm) - 0.6) < 1e-9


def test_kappa_worse_than_chance_is_negative():
    cm = {(True, False): 8, (False, True): 2}
    assert kappa_2x2(cm) < 0
