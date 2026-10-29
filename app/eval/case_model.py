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

    # ---- 多轮（EV-A1）。全部带默认值，130 条旧用例不受影响 ----
    turns: list[str] = field(default_factory=list)
    # 按时间顺序的全部用户问题；空 = 单轮。
    # 非空时 question 必须等于 turns[-1]，gold 只判最后一轮。
    # 校验由 app/eval/validate.py 做，不在这里改写 question——静默改题面会让历史报告失真。

    expect_turns: list[str] = field(default_factory=list)
    # 每轮的期望，长度必须 == len(turns)：
    #   "exec"            该轮必须执行代码（executed=True）
    #   "refusal"         该轮必须按契约拒答（答案以「无法回答：」开头）
    #   "inherit:<regex>" 该轮最终代码必须匹配 regex（约束继承/纠正的机器断言）
    #   "any"             不约束，只记录

    no_history_truth: str = ""
    # 把 turns[-1] 当成独立单轮题时，一个称职模型会算出的答案（pandas 代码）。
    #
    # 用途：机器验证「这道题真的需要历史」。只靠题面文字判断是弱条件——"这些记录里卖得
    # 最好的产品是哪个"读起来像依赖上文，但如果数据上全表冠军碰巧也是同一个产品，这道题
    # 就测不出任何记忆（mul_014/mul_030 初稿就是这么废掉的）。tests/test_multi_cases.py
    # 会把 gold 和它都跑一遍，相等就报错。
    #
    # 留空 = 本题测的不是"记住上文"，而是下面两种之一，必须在用例注释里写明：
    #   - 防过度继承（该丢的约束要丢掉，如 mul_025 换表）
    #   - 指代对象是上一轮的**计算结果**（如"那个部门""这 3 个地区"），脱离历史无法定义
    #     一个"最直白的答案"，写不出 no_history 就等于没有对照，不能假装有。

    # ---- 负向题三分类（EV-B7）。为空且 expect_refusal=True 时等价于 "refusal" ----
    expect_kind: str = ""          # "refusal" | "clarify" | "impossible" | ""

    # ---- 脏数据/扰动题（EV-B6） ----
    gold_dataset: str = ""
    # gold 执行时用的数据文件；空 = 与 dataset 相同。
    # agent 看脏表、gold 在干净表上算，这样"答错"才归因到数据处理而不是期望值本身。

    variant_of: str = ""
    variant_kind: str = ""
    # 指向基线题 id + 变体类型

    multi_table: bool = False
    # 多表题标记；dataset 指向目录时也应为 True（冗余，但便于筛选）

    gold_kind: str = ""
    # "scalar" | "series" | "frame" | "text" | ""（空 = 不约束）
    # 只用于报告分组与图表反算的前置判断，不参与判分
