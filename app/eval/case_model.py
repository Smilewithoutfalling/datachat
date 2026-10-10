"""评测用例的数据结构。"""
from dataclasses import dataclass, field


@dataclass
class EvalCase:
    id: str
    category: str          # aggregation | filtering | correlation | timeseries | refusal | ambiguity
    question: str           # 中文自然语言问题
    ground_truth: str       # pandas代码，执行后 result = 期望结果
    keywords: list = field(default_factory=list)   # 生成代码应包含的关键词
    has_chart: bool = False
    # 结果顺序是否计分（B12）：只有题目明确要求排序/排名时为 True，比较器据此决定是否比较顺序
    ordered: bool = False
    # 题目问"占比"时，比例（0.49）与百分数（49%）都算对（B24 规则 12）；问"百分比"的不设
    percent_equiv: bool = False
    # 阶段 3：所用数据表（见 DATASETS）
    dataset: str = "sales"
    # 应拒答题：数据里没有回答所需的信息，期望 result = "无法回答：<原因>"
    expect_refusal: bool = False
    # 歧义题：其他合理理解的标准答案，命中 ground_truth 或其中任一即对
    alt_ground_truths: list = field(default_factory=list)
