"""单轮网页界面（工作流版）。经 app.core.analyze() 调用（B14/B16：与 CLI 同一条路径，自动带数据字典检索）。
注意：上传的 CSV 落在临时文件里，没有同名 .dict.csv，所以只有本地数据（如 data/sample.csv）才有字典；
Streamlit 界面计划在阶段 5 由 React 前端替代。

运行：streamlit run ui/streamlit_app.py
"""
import os
import sys
import tempfile

import streamlit as st
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

load_dotenv(os.path.join(_ROOT, ".env"))

from app.core import analyze

st.set_page_config(page_title="对话式数据分析 Agent", layout="wide")
st.title("对话式数据分析 Agent")

uploaded = st.file_uploader("上传 CSV 数据文件", type=["csv"])
dict_file = st.file_uploader("（可选）上传数据字典 .dict.csv（两列 field,description）", type=["csv"])
question = st.text_input("用自然语言提问", value="哪个地区的总销售额最高？画个柱状图。")

if st.button("开始分析") and uploaded and question:
    # 把上传文件落地到临时目录，供 analyze 读取；字典按"同名 .dict.csv"约定放在旁边
    tmpdir = tempfile.mkdtemp(prefix="datachat_")
    df_path = os.path.join(tmpdir, "data.csv")
    with open(df_path, "wb") as f:
        f.write(uploaded.getvalue())
    if dict_file is not None:
        with open(os.path.join(tmpdir, "data.dict.csv"), "wb") as f:
            f.write(dict_file.getvalue())

    with st.spinner("Agent 正在规划、写代码、执行、纠错…"):
        res = analyze(df_path, question, agent="workflow", log=True)

    if res.error_kind in ("dataset", "llm"):
        st.error(res.error)

    st.subheader("最终回答")
    st.write(res.answer)

    if res.chart_path and os.path.exists(res.chart_path):
        st.image(res.chart_path)

    with st.expander("查看 Agent 的过程（计划 / 代码 / 重试次数 / 耗时）"):
        if res.field_notes:
            st.markdown("**命中的字段说明**")
            st.text("\n".join(f"- {f}：{d}" for f, d in res.field_notes))
        st.markdown("**分析计划**")
        st.text(res.plan)
        st.markdown("**生成代码**")
        st.code(res.code, language="python")
        st.markdown(f"**重试次数**：{res.attempts}")
        u = res.usage
        st.markdown(f"**耗时**：{res.timings.get('total', 0):.1f} 秒；**token**：{u.total_tokens}（{u.calls} 次调用）")
