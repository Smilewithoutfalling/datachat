import os
import sys

from dotenv import load_dotenv

# Windows 控制台默认 GBK，强制 UTF-8 以正常打印中文
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 按脚本所在目录加载 .env，无论从哪个工作目录运行都能读到 key
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from app.graph import build_graph
from app.tools.dictionary import augment_question, load_retriever
from app.tools.persist import log_run
from app.tools.schema import describe_csv


def main():
    df_path = sys.argv[1] if len(sys.argv) > 1 else "data/sample.csv"
    question = sys.argv[2] if len(sys.argv) > 2 else "哪个地区的总销售额最高？画个柱状图。"

    schema = describe_csv(df_path)
    retriever = load_retriever(df_path)
    app = build_graph()
    state = app.invoke(
        {
            "question": augment_question(question, retriever),
            "df_path": df_path,
            "schema": schema,
            "attempts": 0,
            "max_attempts": 3,
        }
    )

    print("\n===== 分析计划 =====\n" + (state.get("plan") or ""))
    print("\n===== 生成代码 =====\n" + (state.get("code") or ""))
    print("\n===== 重试次数 =====\n" + str(state.get("attempts", 0)))
    print("\n===== 最终回答 =====\n" + (state.get("answer") or ""))
    if state.get("chart_path"):
        print("\n图表已保存：" + state["chart_path"])

    log_run({
        "agent": "workflow",
        "df_path": df_path,
        "question": question,
        "attempts": state.get("attempts", 0),
        "answer": state.get("answer") or "",
        "charts": [state["chart_path"]] if state.get("chart_path") else [],
    })


if __name__ == "__main__":
    main()
