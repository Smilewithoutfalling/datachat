"""不调用真实 LLM：用假模型跑通工作流图，验证节点衔接与纠错回路。"""
import pytest

from app import graph as graph_mod


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)

    def invoke(self, msg):
        class R:
            pass
        r = R()
        r.content = self.replies.pop(0)
        return r


def _patch(monkeypatch, plan, codes, fix_codes, answer):
    from app.nodes import codegen, planner, reviewer, summarizer
    monkeypatch.setattr(planner, "get_llm", lambda: FakeLLM([plan]))
    monkeypatch.setattr(codegen, "get_llm", lambda: FakeLLM(codes))
    fixes = list(fix_codes)
    monkeypatch.setattr(reviewer, "get_llm", lambda: FakeLLM([fixes.pop(0)]))
    monkeypatch.setattr(summarizer, "get_llm", lambda: FakeLLM([answer]))


def _state(sample_path):
    return {"question": "总销量", "df_path": sample_path, "schema": "s", "attempts": 0, "max_attempts": 3}


def test_happy_path(monkeypatch, sample_path):
    _patch(monkeypatch, "1. 求和", ["result = int(df['units'].sum())"], [], "答案")
    out = graph_mod.build_graph().invoke(_state(sample_path))
    assert out["error"] == "" and out["attempts"] == 0 and out["answer"] == "答案"


def test_reviewer_fixes_error(monkeypatch, sample_path):
    _patch(monkeypatch, "p", ["result = df['nope'].sum()"], ["result = int(df['units'].sum())"], "ok")
    out = graph_mod.build_graph().invoke(_state(sample_path))
    assert out["error"] == "" and out["attempts"] == 1


def test_gives_up_after_max_attempts(monkeypatch, sample_path):
    bad = "result = df['nope']"
    _patch(monkeypatch, "p", [bad], [bad, bad, bad], "失败说明")
    out = graph_mod.build_graph().invoke(_state(sample_path))
    assert out["error"] and out["attempts"] == 3 and out["answer"] == "失败说明"


@pytest.mark.parametrize("state,expected", [
    ({"error": "x", "attempts": 0, "max_attempts": 3}, "fix"),
    ({"error": "x", "attempts": 3, "max_attempts": 3}, "done"),
    ({"error": "", "attempts": 0, "max_attempts": 3}, "done"),
])
def test_route_after_exec(state, expected):
    assert graph_mod._route_after_exec(state) == expected
