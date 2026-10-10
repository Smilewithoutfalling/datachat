"""analyze() 的结构化结果（B07/B16）。

result 字段保留代码执行得到的**原始对象**（DataFrame/Series/标量），不再转成截断字符串；
给模型看的文本另由 format_result 生成，并明确标注是否截断。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Optional

import pandas as pd

from app.core.llm import TokenUsage


@dataclass
class Step:
    """执行轨迹中的一步。
    name：工作流版为节点名（planner/codegen/executor/reviewer/summarizer）；
          ReAct 版为 tool_call / observation / answer。"""
    name: str
    content: str = ""
    code: Optional[str] = None
    error: Optional[str] = None
    duration_s: Optional[float] = None


@dataclass
class AnalysisResult:
    agent: str                                  # "workflow" | "react"
    dataset: str                                # 数据文件路径
    question: str                               # 用户原始问题（不含字典注入，B04）
    answer: str = ""                            # 自然语言结论
    result: Any = None                          # 最终代码执行的结构化结果（未截断）
    result_text: str = ""                       # 结果的文本预览（给模型/界面用）
    code: str = ""                              # 最终执行成功（或最后一次尝试）的代码
    chart_path: Optional[str] = None            # 最后生成的图表
    charts: list = field(default_factory=list)  # 本次生成的全部图表
    plan: str = ""                              # 工作流版的分析计划
    field_notes: list = field(default_factory=list)  # 数据字典命中的 (field, description)
    attempts: int = 0                           # 修复/重试次数（工作流：reviewer 次数；ReAct：报错的执行次数）
    initial_error: Optional[str] = None         # 第一次执行的报错（无则 None），用于修复率统计
    executed: bool = False                      # 是否有代码执行成功并拿到结果
    error: Optional[str] = None                 # 最终错误（成功为 None）
    error_kind: Optional[str] = None            # dataset | llm | execution | agent
    steps: list = field(default_factory=list)   # list[Step]
    timings: dict = field(default_factory=dict) # {"total": 秒, "planner": 秒, ...}
    usage: TokenUsage = field(default_factory=TokenUsage)

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_record(self) -> dict:
        """可 JSON 序列化的字典（result 只保留文本预览），用于 runs.jsonl 与以后的 API。"""
        d = {}
        for f in fields(self):
            if f.name == "result":
                continue                     # 原始对象不进 JSON，用 result_text
            v = getattr(self, f.name)
            if f.name == "usage":
                v = asdict(v)
            elif f.name == "steps":
                v = [asdict(s) for s in v]
            elif f.name == "field_notes":
                v = [list(x) for x in v]
            d[f.name] = v
        d["ok"] = self.ok
        return d


def format_result(result: Any, max_chars: int = 3000, max_rows: int = 60) -> str:
    """把结果转成给模型看的文本。表格过大时显示头尾 + 形状，并写明已截断，
    让 summarizer 知道自己看到的是部分数据，而不是悄悄切掉（B07）。"""
    if result is None:
        return "（result 为空：代码没有给 result 赋值）"
    if isinstance(result, (pd.DataFrame, pd.Series)):
        n = len(result)
        kind = "表格" if isinstance(result, pd.DataFrame) else "序列"
        shape = f"{n} 行 × {result.shape[1]} 列" if isinstance(result, pd.DataFrame) else f"{n} 项"
        with pd.option_context("display.max_columns", 50, "display.width", 200):
            if n <= max_rows:
                body = result.to_string()
                note = ""
            else:
                head, tail = max_rows - 10, 10
                body = (result.head(head).to_string() + "\n...\n"
                        + result.tail(tail).to_string(header=isinstance(result, pd.DataFrame)))
                note = f"（共 {n} 行，此处仅显示前 {head} 行和后 {tail} 行）"
        text = f"[{kind}，{shape}]{note}\n{body}"
    else:
        text = str(result)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n…（文本已截断，原长 {len(text)} 字符）"
    return text


# ---- 拒答契约（阶段 3）：数据回答不了时 result = "无法回答：<原因>" ----
REFUSAL_PREFIX = "无法回答"


def is_refusal(v) -> bool:
    """结果契约（阶段 3）：数据回答不了时 result = "无法回答：<原因>"。只有前缀、没有原因的不算。"""
    if not isinstance(v, str):
        return False
    s = v.strip()
    if not s.startswith(REFUSAL_PREFIX):
        return False
    reason = s[len(REFUSAL_PREFIX):].strip(" ：:，,。.；;-—\n\t")
    return len(reason) >= 2


def refusal_from_answer(answer):
    """规则 19：ReAct 没调用工具、直接在结论里拒答时，取结论首行（须以"无法回答"开头）作为 result。"""
    if not isinstance(answer, str):
        return None
    first = answer.strip().splitlines()[0].strip() if answer.strip() else ""
    first = first.strip("*").strip()
    if first.startswith("我无法回答"):        # B49：结论写成"我无法回答：…"
        first = first[1:]
    return first if is_refusal(first) else None
