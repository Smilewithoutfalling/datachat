"""多轮用例（EV-A1/A2 的落地）。

为什么必须有这一批：`state` 模式把历史渲染成「工作状态块 + 数据块」，`off` 模式把原始
(q, a) 当消息回灌。单轮题两者都是空历史，跑 `state` 等于空转 —— 记忆系统的收益一分数
都测不出来。这批是让 `state` 第一次有真实负载的东西。

**每条的最后一句都不能单独作答。** 判据是：把 `turns[-1]` 单独发给 agent，它无法确定
要算什么。所以题面里大量用「这些记录」「那 S02 呢」「按职级拆开看呢」这类指代 ——
单轮题不敢这么写题面（那是 B32 那种歧义），多轮题必须这么写，否则测的是"连续两个单轮"。

`ground_truth` 只算最后一轮，且是**独立**的完整表达式：gold 执行时没有前面几轮的结果，
所以不许写「在上一步基础上再……」这种依赖运行时的答案。

`expect_turns` 的取值：
  exec / refusal  该轮必须执行代码 / 必须拒答
  any             该轮不约束（纯指令轮，模型可能只回"好的"而不执行代码）
  inherit:<regex> 该轮代码必须匹配。**只用来断言约束被继承，不用来断言答案** ——
                  答案对不对由 correctness 判，这里管的是"它有没有把上一轮的前提带下来"。

`turns` 里的代码不跨轮传递（每轮都是独立的 analyze 调用），历史里只有问答文本。
所以第 4 轮要算对，必须把 3 个条件重新写一遍 —— 这正好是 `inherit` 能断言的东西。
"""
from app.eval.case_model import EvalCase

# 表里有 18 条整行重复的录入，凡涉及金额/计数的题都要去掉
_D = "d = df.drop_duplicates('order_id'); "


MULTI_CASES = [
    # ============================================================
    # A 约束继承：最后一轮省略筛选条件，「这些记录」指上一轮那批
    # ============================================================
    EvalCase(id="mul_001", category="multi_turn", dataset="sales", gold_kind="scalar",
             turns=["只看华东地区的销售记录，这些记录的总销售额是多少元？",
                    "那这些记录的销量合计是多少件？"],
             question="那这些记录的销量合计是多少件？",
             ground_truth="result = int(df[df['region'] == '华东']['units'].sum())",
             keywords=["region", "units", "sum"],
             expect_turns=["exec", "exec"]),
    EvalCase(id="mul_002", category="multi_turn", dataset="orders", gold_kind="scalar",
             turns=["只看已完成的订单，重复录入的只算一次。这样的订单有多少笔？",
                    "其中来自 APP 渠道的有多少笔？"],
             question="其中来自 APP 渠道的有多少笔？",
             ground_truth=_D + "d = d[d['status'] == '已完成']; "
                               "result = int((d['channel'] == 'APP').sum())",
             keywords=["status", "channel", "APP"],
             expect_turns=["exec", "inherit:已完成"]),
    EvalCase(id="mul_003", category="multi_turn", dataset="inventory", gold_kind="scalar",
             turns=["S01 门店的累计销量是多少件？",
                    "那 S02 呢？"],
             question="那 S02 呢？",
             ground_truth="result = int(df[df['store'] == 'S02']['sold'].sum())",
             keywords=["store", "sold", "sum"],
             expect_turns=["exec", "exec"]),

    # ============================================================
    # B 纠正覆盖：第 2 轮推翻第 1 轮的前提，不是在上面叠加
    # ============================================================
    EvalCase(id="mul_004", category="multi_turn", dataset="sales", gold_kind="scalar",
             turns=["华南地区的总销售额是多少元？",
                    "不对，我看错了，应该是西南地区。"],
             question="不对，我看错了，应该是西南地区。",
             ground_truth="s = df[df['region'] == '西南']; "
                          "result = round(float((s['units'] * s['price']).sum()), 2)",
             keywords=["region", "西南", "units", "price"],
             # 第 1 轮只要执行代码：它答得对不对不参与判分（gold 只判最后一轮），
             # 在这儿写 inherit:华南 只是在测"题面关键词出现在代码里"，顺便还会被 --oracle
             # 打脸（桩每轮都吐同一段 gold，里面只有西南）。第 2 轮的 inherit 才是真断言：
             # 换了地区之后代码里必须是西南。
             expect_turns=["exec", "inherit:西南"]),
    EvalCase(id="mul_005", category="multi_turn", dataset="employees", gold_kind="scalar",
             turns=["研发部的平均月薪是多少元？",
                    "换成市场部，其他口径不变。"],
             question="换成市场部，其他口径不变。",
             ground_truth="result = round(float(df[df['dept'] == '市场']['monthly_salary'].mean()), 2)",
             keywords=["dept", "市场", "monthly_salary", "mean"],
             expect_turns=["exec", "inherit:市场"]),
    EvalCase(id="mul_006", category="multi_turn", dataset="orders", gold_kind="scalar",
             turns=["只看已完成订单，重复录入的只算一次，总实付金额是多少元？",
                    "把已退款的也加进来，重新算一遍。"],
             question="把已退款的也加进来，重新算一遍。",
             ground_truth=_D + "d = d[d['status'].isin(['已完成', '已退款'])]; "
                               "result = round(float(d['pay_amount'].sum()), 2)",
             keywords=["status", "已退款", "pay_amount", "sum"],
             # 「去重」这个前提只在第 1 轮说过，第 2 轮要自己带下来 —— 不去重金额就对不上
             expect_turns=["exec", "exec"]),

    # ============================================================
    # C 指代消解：最后一轮的动作对象是上一轮的**结果**
    # ============================================================
    EvalCase(id="mul_007", category="multi_turn", dataset="sales", gold_kind="scalar",
             turns=["各地区的总销售额分别是多少元？",
                    "最高和最低相差多少元？"],
             question="最高和最低相差多少元？",
             ground_truth="s = (df['units'] * df['price']).groupby(df['region']).sum(); "
                          "result = round(float(s.max() - s.min()), 2)",
             keywords=["groupby", "region", "max", "min"],
             expect_turns=["exec", "exec"]),
    EvalCase(id="mul_008", category="multi_turn", dataset="inventory", gold_kind="scalar",
             turns=["K100 这个 SKU 的期末库存合计是多少件？",
                    "把它按有记录的天数平均，每天是多少件？保留两位小数。"],
             question="把它按有记录的天数平均，每天是多少件？保留两位小数。",
             ground_truth="k = df[df['sku'] == 'K100']; "
                          "result = round(float(k['closing_stock'].sum() / k['date'].nunique()), 2)",
             keywords=["sku", "closing_stock", "nunique"],
             expect_turns=["exec", "exec"]),

    # ============================================================
    # D 分组粒度继承：最后一轮只改粒度，指标与筛选都不变
    # ============================================================
    EvalCase(id="mul_009", category="multi_turn", dataset="employees", gold_kind="series",
             turns=["研发部的平均月薪是多少元？",
                    "按职级拆开看呢？"],
             question="按职级拆开看呢？",
             ground_truth="result = df[df['dept'] == '研发'].groupby('level')['monthly_salary'].mean().round(2)",
             keywords=["dept", "level", "groupby", "mean"],
             expect_turns=["exec", "inherit:研发"]),

    # ============================================================
    # E 约束逐轮叠加（4 轮）：最能体现「工作状态块」的东西
    # ============================================================
    EvalCase(id="mul_010", category="multi_turn", dataset="orders", gold_kind="scalar",
             turns=["只看已完成的订单，重复录入的只算一次。",
                    "只看 APP 渠道的。",
                    "再看数码类的。",
                    "这些订单一共多少笔？"],
             question="这些订单一共多少笔？",
             ground_truth=_D + "d = d[(d['status'] == '已完成') & (d['channel'] == 'APP') "
                               "& (d['category'] == '数码')]; result = int(len(d))",
             keywords=["status", "channel", "category"],
             # 前三轮是纯指令，模型可能只回「好的」而不执行代码 → any
             # 第 4 轮必须把三个条件都重写（代码不跨轮传递），所以三代条件都要在
             expect_turns=["any", "any", "any", "inherit:已完成"]),

    # ============================================================
    # F 拒答之后继续：拒答不能污染后续轮次
    # ============================================================
    EvalCase(id="mul_011", category="multi_turn", dataset="orders", gold_kind="scalar",
             turns=["订单表里能算出毛利率吗？",
                    "那就把全部订单的实付金额合计算一下，重复录入的只算一次。"],
             question="那就把全部订单的实付金额合计算一下，重复录入的只算一次。",
             ground_truth=_D + "result = round(float(d['pay_amount'].sum()), 2)",
             keywords=["pay_amount", "sum"],
             # 这一条最后一句本身是自足的（不靠历史也能算），它测的是另一件事：
             # 第 1 轮拒答之后，第 2 轮会不会被「无法回答」带偏
             expect_turns=["refusal", "exec"]),

    # ============================================================
    # G 时间范围继承
    # ============================================================
    EvalCase(id="mul_012", category="multi_turn", dataset="orders", gold_kind="series",
             ordered=True, percent_equiv=True,
             turns=["只看 2024 年 3 月的订单，重复录入的只算一次。",
                    "这些订单里各品类的占比是多少？用百分数表示，保留两位小数，按占比从高到低排。"],
             question="这些订单里各品类的占比是多少？用百分数表示，保留两位小数，按占比从高到低排。",
             ground_truth=_D + "m = d[d['order_date'].str[:7] == '2024-03']; "
                               "result = (m['category'].value_counts(normalize=True) * 100).round(2)",
             keywords=["order_date", "category", "value_counts", "normalize"],
             expect_turns=["inherit:2024-03", "inherit:2024-03"]),

    # ============================================================
    # H 三级依赖：分子靠第 2 轮，分母靠第 1 轮
    # ============================================================
    EvalCase(id="mul_013", category="multi_turn", dataset="employees", gold_kind="scalar",
             percent_equiv=True,
             turns=["研发部在职的员工有多少人？",
                    "其中男性有多少人？",
                    "男性占比是多少？用百分数表示，保留两位小数。"],
             question="男性占比是多少？用百分数表示，保留两位小数。",
             ground_truth="x = df[(df['dept'] == '研发') & (df['leave_date'].isna())]; "
                          "result = round(float((x['gender'] == '男').sum() / len(x) * 100), 2)",
             keywords=["dept", "leave_date", "gender"],
             expect_turns=["exec", "exec", "exec"]),
]
