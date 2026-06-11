"""ReAct 版入口：模型自主决定调用工具。对比 run.py（固定工作流版）。

用法：
    python run_react.py
    python run_react.py data/sample.csv "各产品销量趋势如何？画折线图。"
"""
import os
import sys

from dotenv import load_dotenv

# Windows 控制台默认 GBK，强制 UTF-8 以正常打印中文与箭头等符号
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from langchain_core.messages import AIMessage, ToolMessage

from app.react_agent import build_react_agent
from app.tools.dictionary import augment_question, load_retriever
from app.tools.persist import log_run


def main():
    df_path = sys.argv[1] if len(sys.argv) > 1 else "data/sample.csv"
    question = sys.argv[2] if len(sys.argv) > 2 else "哪个地区的总销售额最高？画一张柱状图。"

    sink = {"charts": []}
    agent = build_react_agent(df_path, sink=sink)
    retriever = load_retriever(df_path)
    result = agent.invoke({"messages": [("user", augment_question(question, retriever))]})
    messages = result["messages"]

    # 打印 Agent 的思考轨迹：每次工具调用 + 观察结果（体现 ReAct 循环）
    print("\n===== Agent 执行轨迹 =====")
    step = 0
    for m in messages:
        if isinstance(m, AIMessage) and m.tool_calls:
            for tc in m.tool_calls:
                step += 1
                code = tc["args"].get("code", "")
                print(f"\n[第 {step} 步] 调用工具 {tc['name']}：")
                print(code)
        elif isinstance(m, ToolMessage):
            print(f"  ↳ 观察：{m.content[:300]}")

    answer = messages[-1].content
    print("\n===== 最终回答 =====")
    print(answer)

    charts = sink["charts"]
    if charts:
        print("\n图表已保存：" + charts[-1])

    log_run({
        "agent": "react",
        "df_path": df_path,
        "question": question,
        "answer": answer,
        "charts": charts,
    })


if __name__ == "__main__":
    main()
