"""issue #118：result 里的数值答案保持数值类型，占比不拼 '%' 字符串（agg_009 把占比写成 "48.93%"）。

修法在提示词（codegen / reviewer 模板、react system），不在结果提取层，也不动 app/eval/。
这里只验约束确实进了三处会送给模型的文本；模型是否照做由内网回归验。
"""
from app.nodes import codegen, reviewer


def _react_system():
    from app.react_agent import build_react_agent
    from app.tools.dataset import load_data

    class _NoModel:
        def bind_tools(self, *_a, **_k):
            return self

    data, _desc = load_data("data/sample_eval.csv")
    cap = {}
    build_react_agent("data/sample_eval.csv", model=_NoModel(), df=data, out_system=cap)
    return cap["system"]


def _rendered_codegen():
    return codegen._PROMPT.format(schema="", data_access="", field_notes="", question="", plan="", chart_guide="")


def test_codegen_prompt_keeps_result_numeric():
    text = _rendered_codegen()
    assert "保持数值类型" in text
    assert "0–1 的小数或 ×100 后的数值" in text
    assert "f'{x:.2%}'" in text            # format 之后花括号原样出现，没被吞掉
    assert "格式化交给最终结论" in text


def test_reviewer_prompt_keeps_result_numeric():
    # reviewer 重写代码时「规则不变」，同一条约束也要在，否则修一轮就丢了
    assert "保持数值类型" in reviewer._PROMPT
    assert "不要格式化成带 '%' 的字符串" in reviewer._PROMPT


def test_react_system_keeps_result_numeric():
    system = _react_system()
    assert "result 里的数值答案（含 Series / 表里的数值列）保持数值类型" in system
    assert "f'{x:.2%}'" in system
    assert "格式化写进最终中文结论" in system


def test_rule_is_generic_not_case_specific():
    # 不针对题目 id / 具体数值特判
    for text in (_rendered_codegen(), reviewer._PROMPT, _react_system()):
        assert "agg_009" not in text and "48.93" not in text
