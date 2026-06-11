from typing import TypedDict


class AgentState(TypedDict, total=False):
    """在图中各节点间流转的状态。total=False 表示字段都可选。"""
    question: str        # 用户的自然语言问题
    df_path: str         # 数据文件路径（CSV）
    schema: str          # 数据表结构描述（喂给模型）
    plan: str            # Planner 产出的分析步骤
    code: str            # CodeGen / Reviewer 产出的 pandas 代码
    result: str          # Executor 执行得到的结果（已转字符串）
    error: str           # Executor 的报错信息（空字符串表示成功）
    chart_path: str      # 若生成图表，保存路径
    answer: str          # Summarizer 产出的自然语言结论
    attempts: int        # 已重试次数
    max_attempts: int    # 最大重试次数
