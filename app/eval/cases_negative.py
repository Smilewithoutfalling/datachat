"""负向题（EV-B7）：不该答的别答，没说清的别猜。

这批题与 `refusal`（数据里真没有）和 `ambiguity`（有多种合理解法）都不同：

  clarify     题目本身缺口径/缺指标/缺范围 → 正确行为是**反问**
  impossible  数据里缺一个具体对象 → 正确行为是拒答，且**点名缺什么**

为什么 clarify 要单独立起来：现有 8 条 ambiguity 题靠 `alt_ground_truths` 判分 ——
它们默认「模型会挑一种理解算下去」，只要算对其中一种就算过。但产品上更该做的是问一句
「您是指哪个口径？」。两套判分标准混在同一个 category 里，会让「ambiguity 准确率」
变成两个不同要求的平均值，谁都读不出来。分类按规格不新增（会改所有按类报表的分母），
但**判分必须分开**：这 6 条 `expect_kind="clarify"`，走 `negative.negative_verdict`。

clarify 题的 `ground_truth` 只占位（`result = None`）：它们没有唯一答案，
也不该有 —— 一旦写出 gold，就等于承认「猜某个口径」是对的。
`expected_all` 照常执行它，拿到 None，不影响判定（clarify 不看 gold）。
"""
from app.eval.case_model import EvalCase

# clarify 题共用的占位 gold：没有唯一答案。
_NONE = "result = None"


NEGATIVE_CASES = [
    # ============================================================
    # clarify（6 条）：题目缺东西，正确行为是反问
    # ============================================================
    EvalCase(id="neg_001", category="ambiguity", dataset="orders", expect_kind="clarify",
             question="这些订单的销售额怎么样？",
             # 三处都没定：算哪个金额（pay_amount / unit_price*qty / 含不含退款）、
             # 看什么维度（按城市？按品类？）、什么时间段。任挑一个算都是在替用户做决定。
             ground_truth=_NONE,
             keywords=[]),

    EvalCase(id="neg_002", category="ambiguity", dataset="orders", expect_kind="clarify",
             question="最近的订单多吗？",
             # 「最近」没有定义：最近 7 天？30 天？还是"时间上最后一批"？
             # 数据到 2024 年某日为止，用今天当"最近"会得到 0 笔 —— 一个技术上正确、
             # 实际上毫无意义的答案。
             ground_truth=_NONE,
             keywords=[]),

    EvalCase(id="neg_003", category="ambiguity", dataset="employees", expect_kind="clarify",
             question="大家的工资高不高？",
             # 「高」没有基准：跟谁比？跟什么行业/地区/职级比？数据里只有本公司月薪，
             # 没有任何外部参照。直接报平均月薪是在回答另一个问题。
             ground_truth=_NONE,
             keywords=[]),

    EvalCase(id="neg_004", category="ambiguity", dataset="inventory", expect_kind="clarify",
             question="现在的库存情况如何？",
             # 「情况」没有指标：库存量？周转天数？缺货 SKU？积压 SKU？
             # 四个问题对应四种算法，答错一个就等于答非所问。
             ground_truth=_NONE,
             keywords=[]),

    EvalCase(id="neg_005", category="ambiguity", dataset="orders", expect_kind="clarify",
             question="哪个品类表现最好？",
             # 「最好」没有指标：订单数最多？销售额最高？退款率最低？客单价最高？
             # 这是最典型的一类 —— 四个指标能选出四个不同品类。
             ground_truth=_NONE,
             keywords=[]),

    EvalCase(id="neg_006", category="ambiguity", dataset="biz", expect_kind="clarify",
             question="帮我看看这批数据",
             # 完全没有目标。多表场景下尤其危险：五张表能组合出的问题无穷多，
             # 随手给一张汇总表既不算错也不算对，纯属浪费用户的时间。
             ground_truth=_NONE,
             keywords=[]),

    # ============================================================
    # impossible（4 条）：数据里确实缺一个具体对象
    # ============================================================
    EvalCase(id="neg_007", category="refusal", dataset="orders", expect_kind="impossible",
             expect_refusal=True, missing_objects=["支付方式"],
             question="这些订单用微信支付和支付宝的各有多少笔？",
             # 表里只有 channel（APP / 小程序 / 网页…）——那是下单渠道，不是支付方式。
             # 这是这批题里最容易被答错的一条：两个词在中文里都叫"渠道"，模型很容易
             # 直接把 channel 的分布当成支付方式交上来，而且语法上完全说得通。
             # 所以 missing_objects 写死"支付方式"，validate 会查 gold 也必须提到它。
             ground_truth="result = '无法回答：数据中没有支付方式字段，只有下单渠道'",
             keywords=[]),

    EvalCase(id="neg_008", category="refusal", dataset="employees", expect_kind="impossible",
             expect_refusal=True, missing_objects=["技能评分"],
             question="员工的专业技能评分平均是多少分？",
             # 只有 perf_2023（绩效评级 A/B/C），没有技能评分，也没有任何分数制评价。
             # 绩效评级与技能评分相关但不是同一个东西 —— 拿 A/B/C 折算成分数是编数据。
             ground_truth="result = '无法回答：数据中没有员工的技能评分记录，只有绩效评级'",
             keywords=[]),

    EvalCase(id="neg_009", category="refusal", dataset="inventory", expect_kind="impossible",
             expect_refusal=True, missing_objects=["保质期"],
             question="哪些商品快到保质期了？",
             # inventory 只有进出存数量，没有生产日期、批次、保质期天数。
             # 「快过期」这个判断需要三个都不存在的字段，不是算不出来，是没法算。
             ground_truth="result = '无法回答：数据中没有保质期或生产日期字段'",
             keywords=[]),

    EvalCase(id="neg_010", category="refusal", dataset="biz", expect_kind="impossible",
             expect_refusal=True, missing_objects=["供应商"],
             question="这些商品的供应商是谁？",
             # biz 五张表（orders / order_items / products / customers / refunds）里
             # 没有任何供应商实体，products 也只有 sku / 名称 / 品类 / 两个价格。
             # 这是"表缺失"而非"列缺失"，判据同样要求原因里点名"供应商"。
             ground_truth="result = '无法回答：数据中没有供应商信息，商品表只有品类与价格'",
             keywords=[]),
]
