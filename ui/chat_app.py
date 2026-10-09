"""对话式前端（多轮记忆 + 追问）。

基于 ReAct 智能体 + LangGraph MemorySaver：同一个 thread_id 下，
模型能记住前几轮问了什么、得出什么结论，因此可以自然追问
（"那华北呢？""再按产品拆一下"）。
阶段 1 起经 app.core.analyze(agent="react", memory=..., thread_id=...) 调用。

运行：streamlit run ui/chat_app.py
"""
import os
import sys
import tempfile
import uuid

import streamlit as st
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

load_dotenv(os.path.join(_ROOT, ".env"))

from langgraph.checkpoint.memory import MemorySaver

from app.core import analyze

st.set_page_config(page_title="对话式数据分析 Agent", layout="wide")
st.title("对话式数据分析 Agent")
st.caption("上传 CSV → 自然语言提问 → 自动写 pandas、执行、画图；支持多轮追问")

uploaded = st.file_uploader("上传 CSV 数据文件", type=["csv"])


def _reset_session(df_path: str):
    """为新上传的文件重建记忆与对话历史。"""
    st.session_state.df_path = df_path
    st.session_state.memory = MemorySaver()
    st.session_state.thread_id = uuid.uuid4().hex
    st.session_state.history = []  # [{role, content, charts}]


if uploaded is not None:
    sig = (uploaded.name, uploaded.size)
    if st.session_state.get("file_sig") != sig:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        tmp.write(uploaded.getvalue())
        tmp.close()
        st.session_state.file_sig = sig
        _reset_session(tmp.name)

if "memory" not in st.session_state:
    st.info("请先上传一个 CSV 文件。")
    st.stop()

# 渲染历史对话（含图表）
for turn in st.session_state.history:
    with st.chat_message(turn["role"]):
        st.write(turn["content"])
        for c in turn.get("charts", []):
            if os.path.exists(c):
                st.image(c)

question = st.chat_input("用自然语言提问，可继续追问…")
if question:
    st.session_state.history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        with st.spinner("Agent 正在思考、写代码、执行、画图…"):
            res = analyze(
                st.session_state.df_path, question, agent="react",
                memory=st.session_state.memory, thread_id=st.session_state.thread_id,
                log=True,
            )
        answer = res.answer or (f"（未能完成：{res.error}）" if res.error else "")
        st.write(answer)
        for c in res.charts:
            if os.path.exists(c):
                st.image(c)

    st.session_state.history.append(
        {"role": "assistant", "content": answer, "charts": list(res.charts)}
    )
