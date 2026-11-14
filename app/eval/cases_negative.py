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
             # 「销售额」是有的（pay_amount、或 单价×件数），缺的是**怎么给**：
             # 总额？均值？按城市/品类拆？还是逐月走势？「怎么样」一个都没指定。
             # 注意这和 ord_027「总销售额是多少」不是一回事 —— 那道点了「总」，
             # 剩下的只是口径分岔（含不含退款/取消），挑一个算、结论里说明就够。
             # 分界线是**有没有指定聚合方式**，不是有没有口径分歧。
             clarify_gap=["operator"],
             ground_truth=_NONE,
             keywords=[]),

    EvalCase(id="neg_002", category="ambiguity", dataset="orders", expect_kind="clarify",
             question="最近的订单多吗？",
             # 两处都没落地：「最近」没有窗口（最近 7 天？30 天？还是"时间上最后一批"），
             # 「多」没有基准（比上个月多？比去年同期多？还是跟日均比？）。
             # 数据到 2024-06-30 为止，用今天当"最近"会得到 0 笔 —— 技术上正确、实际无意义。
             clarify_gap=["scope", "baseline"],
             ground_truth=_NONE,
             keywords=[]),

    EvalCase(id="neg_003", category="ambiguity", dataset="employees", expect_kind="clarify",
             question="大家的工资高不高？",
             # 「高」没有基准：跟谁比？跟什么行业/地区/职级比？数据里只有本公司月薪，
             # 没有任何外部参照。直接报平均月薪是在回答另一个问题。
             # 「高不高」也没有指定怎么算高 —— 看均值？中位数？还是分位数？
             clarify_gap=["operator", "baseline"],
             ground_truth=_NONE,
             keywords=[]),

    EvalCase(id="neg_004", category="ambiguity", dataset="inventory", expect_kind="clarify",
             question="现在的库存情况如何？",
             # 「情况」不是指标：库存量？周转天数？缺货 SKU？积压 SKU？
             # 四个问题对应四种算法，答错一个就等于答非所问。
             clarify_gap=["operator"],
             ground_truth=_NONE,
             keywords=[]),

    EvalCase(id="neg_005", category="ambiguity", dataset="orders", expect_kind="clarify",
             question="哪个品类表现最好？",
             # 「表现」不是字段，也不是能由字段算出的量；「最好」是一个选择算子，
             # 没有指标就没有落点（订单数最多？销售额最高？退款率最低？客单价最高？）。
             #
             # 这道题曾和 ord_029「哪个品类卖得最好」冲突（后者给了 5 个备选答案）。
             # 2026-11-13 把 ord_029 也改成了 clarify —— 那 5 个口径实测选出 3 个不同品类
             # （数码 / 服饰 / 食品），说明"没有默认口径"对两道题同时成立。
             clarify_gap=["metric"],
             ground_truth=_NONE,
             keywords=[]),

    EvalCase(id="neg_006", category="ambiguity", dataset="biz", expect_kind="clarify",
             question="帮我看看这批数据",
             # 完全没有目标。多表场景下尤其危险：五张表能组合出的问题无穷多，
             # 随手给一张汇总表既不算错也不算对，纯属浪费用户的时间。
             clarify_gap=["object", "metric", "operator"],
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
