"""两个 Streamlit 页面的冒烟测试：脚本能加载并渲染初始界面（不上传文件、不调模型）。
Streamlit 计划在阶段 5 下线，这里只保证阶段 1 改走 analyze() 后页面没坏。"""
import os

import pytest

from conftest import ROOT

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


@pytest.mark.parametrize("page", ["streamlit_app.py", "chat_app.py"])
def test_page_renders(page):
    at = AppTest.from_file(os.path.join(ROOT, "ui", page), default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value == "对话式数据分析 Agent"


def test_chat_app_turn_goes_through_analyze(monkeypatch, sample_path):
    """多轮页面：一轮提问经 analyze(agent="react", memory=...) 完成并渲染回答。"""
    import app.core
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import MemorySaver

    from app.core.testing import ScriptedChatModel

    real = app.core.analyze
    seen = {}

    def fake_analyze(*a, **k):
        seen.update(k)
        model = ScriptedChatModel(replies=[AIMessage(content="", tool_calls=[{
            "name": "run_python_on_data", "args": {"code": "result = 1"}, "id": "c1"}]), "答：1"], calls=[])
        return real(*a, chat_model=model, llm_config=app.core.LLMConfig(api_key="t"), **k)
    monkeypatch.setattr(app.core, "analyze", fake_analyze)

    at = AppTest.from_file(os.path.join(ROOT, "ui", "chat_app.py"), default_timeout=30)
    at.session_state["memory"] = MemorySaver()
    at.session_state["df_path"] = sample_path
    at.session_state["thread_id"] = "t1"
    at.session_state["history"] = []
    at.run()
    at.chat_input[0].set_value("总销量").run()
    assert not at.exception
    assert seen["agent"] == "react" and seen["thread_id"] == "t1"
    assert any("答：1" in m.value for m in at.markdown)
