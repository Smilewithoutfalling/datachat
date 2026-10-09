from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    """在图中各节点间流转的状态。total=False 表示字段都可选。"""
    question: str        # 用户的自然语言问题（原样，不拼字典说明，B04）
    df_path: str         # 数据文件路径（CSV）
    schema: str          # 数据表结构描述（喂给模型）
    field_notes: str     # 数据字典检索到的字段说明（已格式化，独立于 question，B04）
    plan: str            # Planner 产出的分析步骤
    code: str            # CodeGen / Reviewer 产出的 pandas 代码
    result: Any          # Executor 得到的结构化结果（DataFrame/Series/标量，不截断，B07）
    result_text: str     # 结果的文本预览（给 summarizer 看，截断时会标注）
    error: str           # Executor 的报错信息（空字符串表示成功）
    initial_error: str   # 第一次执行的报错（用于统计 reviewer 修复率）
    chart_path: str      # 若生成图表，保存路径
    answer: str          # Summarizer 产出的自然语言结论
    attempts: int        # 已重试次数
    max_attempts: int    # 最大重试次数
    exec_timeout: int    # 单次代码执行超时（秒）
