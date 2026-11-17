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

    recall_turn: int = 0
    # 跨轮数字断言（EV-B5 规格的 mt_007 附加项）。0 = 不启用；n（1 起头，且 < len(turns)）
    # = 最后一轮 answer 里的"有分量"数字必须全部能在第 n 轮的 result_text 里找到
    # （用 consistency/grounding 的抽取与容差，年份自动豁免）。
    # 测的是"长会话后回头引用旧数字"——模型复述错第 1 轮的数，结果层完全测不到：
    # gold 是独立重算的，第 3 轮哪怕把第 1 轮的数记错，只要逻辑对照样判对。
    # 找不到 → correct=False，原因写 recall_why。

    # ---- 负向题三分类（EV-B7）。为空且 expect_refusal=True 时等价于 "refusal" ----
    expect_kind: str = ""          # "refusal" | "clarify" | "impossible" | ""

    missing_objects: list = field(default_factory=list)
    # impossible 题缺什么（列名 / 字段名 / 表名）。判据要求拒答原因里必须点名其中之一。
    #
    # 为什么不从 ground_truth 的拒答原因里抽：那是拿字符串切中文，抽出来的词要么太宽
    # （"数据"）要么太窄（把"成本或毛利"当成一个词）。出题人本来就知道缺什么，直接写。
    # validate 会强制每个词都出现在 gold 的拒答原因里 —— 字段与 gold 不许各说各话。

    clarify_gap: list = field(default_factory=list)
    # clarify 题缺哪一项，取值见 app/eval/clarify_spec.py 的 GAP_KINDS：
    #   "object"   没有可指认的分析对象（哪张表 / 哪个维度）
    #   "metric"   没有要算的量（不是字段、不是字段组合、也不是字典里已定义的派生指标）
    #   "operator" 没说怎么聚合（总/平均/最大/计数/占比/分布…）
    #   "scope"    没有范围（时间窗口、城市、品类等筛选条件）
    #   "baseline" 要判断高低好坏，却没给比较基准
    #
    # 为什么要写成结构化字段而不是只写在注释里：注释是散文，谁都能说"这题缺口径"。
    # 写进字段后 tests/test_clarify_spec.py 会拿题面字面去核 —— 声明缺什么，
    # 题面里就真的不能有那个东西。判据因此可执行、可对账，而不是出题人的自述。
    # 非 clarify 题带这个字段一律报错（validate 管）。

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

    # ---- 记忆批 4（R4/R7/R9/R10，docs/roadmap/memory-batch4.md §5.3） ----
    dataset_notes: list = field(default_factory=list)
    # 口径题（R7）：透传 analyze(dataset_notes=...)，格式 [{kind, name, body, unit, synonyms, sha?}]
    # （kind ∈ metric|rule；缺 sha 时 service 现算）。只在 memory_mode != off 时注入。
    # off 档跑口径题 = 口径根本不进 prompt，判分必然错 —— 所以口径题必须标 requires_memory。

    today: str = ""
    # 相对时间题固定日期（R4）：透传 analyze(today=...)，"YYYY-MM-DD"。
    # 不固定的话"本月/上月"类题的读数随运行日期漂移。

    rewrite: bool = False
    # 改写显式开关（R9）：透传 analyze(rewrite=...)。off 档改写不生效（service 直接短路）；
    # state 档生效。注意 runtime_config.rewrite 只读环境变量 DATACHAT_REWRITE，
    # 用例级 rewrite=True 跑批时报告的 rewrite 读数仍是 env 的 —— 偏差记在 DEVLOG。

    requires_memory: str = ""
    # 该题只在指定档位有效："state" | "full" | ""（不约束）。
    # --memory 为 off 时 run_eval 自动跳过这类题并提示；全量 oracle / canary 在 off 档也跳过。
    # 默认档 2026-11-16 起是 state（C-021），默认跑批会收录它们。
    # 没有这个标记，口径题会在 off 档被静默判错，污染准确率。
