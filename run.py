"""工作流版入口（固定状态图）。经 app.core.analyze() 调用，与评测/UI 同一条路径。

用法：
    python run.py
    python run.py data/sample.csv "各产品的平均单价是多少？画柱状图。"
"""
import os
import sys

from dotenv import load_dotenv

# Windows 控制台默认 GBK，强制 UTF-8 以正常打印中文
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 按脚本所在目录加载 .env，无论从哪个工作目录运行都能读到 key
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from app.core import analyze


def main():
    df_path = sys.argv[1] if len(sys.argv) > 1 else "data/sample.csv"
    question = sys.argv[2] if len(sys.argv) > 2 else "哪个地区的总销售额最高？画个柱状图。"

    res = analyze(df_path, question, agent="workflow", log=True)

    print("\n===== 分析计划 =====\n" + (res.plan or ""))
    print("\n===== 生成代码 =====\n" + (res.code or ""))
    print("\n===== 重试次数 =====\n" + str(res.attempts))
    print("\n===== 最终回答 =====\n" + (res.answer or ""))
    if res.chart_path:
        print("\n图表已保存：" + res.chart_path)
    u = res.usage
    print(f"\n耗时 {res.timings.get('total', 0):.1f} 秒；LLM 调用 {u.calls} 次，"
          f"token {u.total_tokens}（输入 {u.input_tokens} / 输出 {u.output_tokens}），重试 {u.retries} 次")
    if res.error:
        print(f"\n[失败 · {res.error_kind}] {res.error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
