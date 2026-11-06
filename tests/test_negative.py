"""EV-B7 负向题判据。

三类各两条（正例 / 反例）是规格的下限；这里把边界写全，因为这三条判据最容易
"看起来对、其实把别的东西判过了"：

- clarify 的「含问号」会命中「无法回答：您是指哪个口径？」—— 它拒答了，没有问清。
- impossible 的「拒答了」不等于「说清了缺什么」，用户得知道缺哪张表才能补数据。
- refusal 的兼容路径必须逐字节等于旧行为，否则历史报告全部不可比。
"""
from types import SimpleNamespace

import pytest

from app.eval import negative
from app.eval.case_model import EvalCase
from app.eval.cases import ALL_CASES


def _res(result=None, answer="", executed=False):
    """负向判据只看三个字段，别造整个 AnalysisResult。"""
    return SimpleNamespace(result=result, answer=answer, executed=executed)


def _case(kind, missing=(), expect_refusal=None):
    if expect_refusal is None:
        expect_refusal = kind in ("refusal", "impossible")
    return EvalCase(id="neg_999", category="refusal", question="q", ground_truth="result = None",
                    expect_kind=kind, expect_refusal=expect_refusal,
                    missing_objects=list(missing))


# ---------------------------------------------------------------- refusal

def test_refusal_kind_accepts_contract_refusal():
    v = negative.negative_verdict(_res(result="无法回答：数据中没有成本字段"), _case("refusal"))
    assert v["match"] == "refusal" and v["why"] == ""


def test_refusal_kind_accepts_refusal_in_answer_when_not_executed():
    """ReAct 直接在结论里拒答时 result 是空的，判定在 answer 首行。"""
    v = negative.negative_verdict(_res(answer="无法回答：数据中没有用户年龄信息\n\n补充说明…"),
                                  _case("refusal"))
    assert v["match"] == "refusal"


def test_refusal_kind_rejects_number():
    v = negative.negative_verdict(_res(result=123.0, executed=True), _case("refusal"))
    assert v["match"] is None and "没有按契约拒答" in v["why"]


def test_refusal_kind_rejects_bare_prefix_without_reason():
    """「无法回答：」后面没有原因不算拒答（is_refusal 要求原因 ≥2 字）。"""
    v = negative.negative_verdict(_res(result="无法回答："), _case("refusal"))
    assert v["match"] is None


def test_empty_expect_kind_falls_back_to_expect_refusal():
    """向后兼容：183 条旧题 expect_kind 为空，行为必须与改动前一致。"""
    case = EvalCase(id="ord_999", category="refusal", question="q", ground_truth="result = None",
                    expect_refusal=True)
    assert negative.negative_verdict(_res(result="无法回答：数据中没有该字段"), case)["match"] == "refusal"
    assert negative.negative_verdict(_res(result=42, executed=True), case)["match"] is None


def test_question_mark_does_not_turn_a_refusal_into_clarify():
    """规格陷阱：先判拒答再判澄清。「无法回答：您是指哪个口径？」是拒答，不是澄清。"""
    v = negative.negative_verdict(_res(result="无法回答：您是指哪个口径？数据里没有定义"),
                                  _case("clarify"))
    assert v["match"] is None
    assert "直接拒答了" in v["why"]


# ---------------------------------------------------------------- clarify

@pytest.mark.parametrize("answer", [
    "您是指按实付金额还是原价算？",
    "请问是指哪个时间范围?",
    "需要确认一下：是按城市还是按品类？",
    "哪种口径？",
])
def test_clarify_accepts_asking_back(answer):
    v = negative.negative_verdict(_res(answer=answer, executed=False), _case("clarify"))
    assert v["match"] == "clarify", v


def test_clarify_rejects_guessed_answer_with_code_executed():
    """没问清就猜着算 —— 用户拿到的是某个假设下的数，这是最该拦的一种。"""
    v = negative.negative_verdict(_res(result=1234.5, answer="按实付金额算是 1234.5 元",
                                       executed=True), _case("clarify"))
    assert v["match"] is None and "没问清口径就猜着算" in v["why"]


def test_clarify_rejects_silent_non_answer_without_question():
    """既不算也不问（"请提供更多信息"没有问号）不算通过：它没有把球踢回给用户。"""
    v = negative.negative_verdict(_res(answer="请提供更多信息。", executed=False), _case("clarify"))
    assert v["match"] is None and "既没执行代码也没反问" in v["why"]


def test_clarify_does_not_fire_on_empty_answer():
    v = negative.negative_verdict(_res(answer="", executed=False), _case("clarify"))
    assert v["match"] is None


# ---------------------------------------------------------------- impossible

def test_impossible_accepts_refusal_naming_the_missing_object():
    v = negative.negative_verdict(
        _res(result="无法回答：数据中没有支付方式字段，只有下单渠道"),
        _case("impossible", missing=["支付方式"]))
    assert v["match"] == "impossible"


def test_impossible_accepts_any_one_of_several_missing_objects():
    v = negative.negative_verdict(_res(result="无法回答：数据中没有保质期或生产日期字段"),
                                  _case("impossible", missing=["保质期", "生产日期"]))
    assert v["match"] == "impossible"


def test_impossible_rejects_vague_refusal():
    """拒答了但没点名缺什么，用户只知道"答不了"，不知道该补哪张表。"""
    v = negative.negative_verdict(_res(result="无法回答：数据不足"),
                                  _case("impossible", missing=["支付方式"]))
    assert v["match"] is None and "没点名缺什么" in v["why"]


def test_impossible_rejects_number_even_if_answer_mentions_missing_field():
    """执行出结果 = 越界。answer 里提到「支付方式」不能洗白已经交上去的数字。"""
    v = negative.negative_verdict(
        _res(result={"APP": 100}, answer="数据里没有支付方式，但按渠道看是 APP 100 笔",
             executed=True),
        _case("impossible", missing=["支付方式"]))
    assert v["match"] is None and "没有拒答" in v["why"]


# ---------------------------------------------------------------- 题库层面

def test_negative_cases_are_in_all_cases():
    """expect_kind 是负向题的注册表：neg_001..010 十条 + 记忆专项的反向回归 mem_003
    （口径引用缺失字段仍拒答，批 4 起 expect_kind 也被 memory 类合法使用）。"""
    from app.eval.cases import ALL_CASES
    ids = {c.id for c in ALL_CASES if c.expect_kind}
    assert ids == {f"neg_{i:03d}" for i in range(1, 11)} | {"mem_003"}, sorted(ids)


def test_negative_mix_matches_the_spec():
    """6 澄清 + 4 不可能（neg_* 十条的比例写死：全做成 impossible 也能"通过"，
    但那测不出"该反问却算了一个数"这件事）。mem_003 是记忆类的反向回归，不计入这个配比。"""
    from app.eval.cases import ALL_CASES
    kinds = [c.expect_kind for c in ALL_CASES if c.expect_kind and c.id.startswith("neg_")]
    assert kinds.count("clarify") == 6
    assert kinds.count("impossible") == 4


_IMPOSSIBLE = [c for c in ALL_CASES if c.expect_kind == "impossible"]


@pytest.mark.parametrize("case", _IMPOSSIBLE, ids=[c.id for c in _IMPOSSIBLE])
def test_impossible_gold_names_its_missing_object(case):
    """字段与 gold 必须一致，否则这条题永远判不过 —— 是出题人的错，不是模型的。"""
    assert case.missing_objects
    for obj in case.missing_objects:
        assert obj in case.ground_truth, f"{case.id}: {obj!r} 不在 gold 里"


def test_clarify_cases_have_no_gold_answer():
    """澄清题一旦写出唯一答案，就等于承认"猜某个口径"是对的。"""
    for c in ALL_CASES:
        if c.expect_kind == "clarify":
            assert c.ground_truth.strip() == "result = None", c.id


# ---------------------------------------------------------------- validate 的新规则

def _vcase(**kw):
    base = dict(id="neg_900", category="refusal", question="q",
                ground_truth="result = '无法回答：数据中没有该字段'", expect_kind="impossible",
                expect_refusal=True, missing_objects=["该字段"])
    base.update(kw)
    return EvalCase(**base)


def test_validate_accepts_a_well_formed_impossible_case():
    from app.eval.validate import validate_cases
    assert validate_cases([_vcase()]) == []


def test_validate_rejects_impossible_without_missing_objects():
    """不声明缺什么 = 判据无据可依，那条题会永远判不过。"""
    from app.eval.validate import validate_cases
    errs = validate_cases([_vcase(missing_objects=[])])
    assert any("必须声明 missing_objects" in e for e in errs), errs


def test_validate_rejects_missing_object_absent_from_gold():
    """字段与 gold 各说各话时，模型照着 gold 拒答也判不过 —— 是出题人的错。"""
    from app.eval.validate import validate_cases
    errs = validate_cases([_vcase(missing_objects=["供应商"])])
    assert any("在 ground_truth 里找不到" in e for e in errs), errs


def test_validate_rejects_missing_objects_on_non_impossible_case():
    from app.eval.validate import validate_cases
    errs = validate_cases([_vcase(expect_kind="clarify", expect_refusal=False)])
    assert any("只在 expect_kind=impossible 上有意义" in e for e in errs), errs


def test_validate_rejects_impossible_without_expect_refusal():
    """impossible 是拒答的一种：少了这个标记就不过 refusal_leak 越界检查。"""
    from app.eval.validate import validate_cases
    errs = validate_cases([_vcase(expect_refusal=False)])
    assert any("必须同时 expect_refusal=True" in e for e in errs), errs


def test_validate_rejects_clarify_with_expect_refusal():
    from app.eval.validate import validate_cases
    errs = validate_cases([_vcase(expect_kind="clarify", expect_refusal=True, missing_objects=[])])
    assert any("clarify 与 expect_refusal=True 矛盾" in e for e in errs), errs
