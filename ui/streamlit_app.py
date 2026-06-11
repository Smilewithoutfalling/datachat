import os
import sys
import tempfile

import streamlit as st
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

load_dotenv(os.path.join(_ROOT, ".env"))

from app.graph import build_graph
from app.tools.schema import describe_csv

st.set_page_config(page_title="对话式数据分析 Agent", layout="wide")
st.title("对话式数据分析 Agent")

uploaded = st.file_uploader("上传 CSV 数据文件", type=["csv"])
question = st.text_input("用自然语言提问", value="哪个地区的总销售额最高？画个柱状图。")

if st.button("开始分析") and uploaded and question:
    # 把上传文件落地到临时路径，供 executor 读取
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    tmp.write(uploaded.getvalue())
    tmp.close()

    with st.spinner("Agent 正在规划、写代码、执行、纠错…"):
        app = build_graph()
        state = app.invoke(
            {
                "question": question,
                "df_path": tmp.name,
                "schema": describe_csv(tmp.name),
                "attempts": 0,
                "max_attempts": 3,
            }
        )

    st.subheader("最终回答")
    st.write(state.get("answer", ""))

    if state.get("chart_path") and os.path.exists(state["chart_path"]):
        st.image(state["chart_path"])

    with st.expander("查看 Agent 的过程（计划 / 代码 / 重试次数）"):
        st.markdown("**分析计划**")
        st.text(state.get("plan", ""))
        st.markdown("**生成代码**")
        st.code(state.get("code", ""), language="python")
        st.markdown(f"**重试次数**：{state.get('attempts', 0)}")
