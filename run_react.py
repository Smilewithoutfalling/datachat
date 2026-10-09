"""ReAct 版入口：模型自主决定调用工具。对比 run.py（固定工作流版）。
经 app.core.analyze(agent="react") 调用，与评测/UI 同一条路径。

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

from app.core import analyze


def main():
    df_path = sys.argv[1] if len(sys.argv) > 1 else "data/sample.csv"
    question = sys.argv[2] if len(sys.argv) > 2 else "哪个地区的总销售额最高？画一张柱状图。"

    res = analyze(df_path, question, agent="react", log=True)

    # 打印 Agent 的思考轨迹：每次工具调用 + 观察结果（体现 ReAct 循环）
    print("\n===== Agent 执行轨迹 =====")
    step = 0
    for s in res.steps:
        if s.name == "tool_call":
            step += 1
            print(f"\n[第 {step} 步] 调用工具 run_python_on_data：")
            print(s.code or "")
        elif s.name == "observation":
            print(f"  ↳ 观察：{s.content[:300]}")

    print("\n===== 最终回答 =====")
    print(res.answer)
    if res.charts:
        print("\n图表已保存：" + res.charts[-1])
    u = res.usage
    print(f"\n耗时 {res.timings.get('total', 0):.1f} 秒；LLM 调用 {u.calls} 次，token {u.total_tokens}")
    if res.error:
        print(f"\n[失败 · {res.error_kind}] {res.error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
