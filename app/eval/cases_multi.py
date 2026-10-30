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
             no_history_truth="result = int(df['units'].sum())",
             keywords=["region", "units", "sum"],
             expect_turns=["exec", "exec"]),
    EvalCase(id="mul_002", category="multi_turn", dataset="orders", gold_kind="scalar",
             turns=["只看已完成的订单，重复录入的只算一次。这样的订单有多少笔？",
                    "其中来自 APP 渠道的有多少笔？"],
             question="其中来自 APP 渠道的有多少笔？",
             ground_truth=_D + "d = d[d['status'] == '已完成']; "
                               "result = int((d['channel'] == 'APP').sum())",
             no_history_truth="result = int((df['channel'] == 'APP').sum())",
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
             no_history_truth="result = round(float(df['pay_amount'].sum()), 2)",
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
             no_history_truth="result = df.groupby('level')['monthly_salary'].mean().round(2)",
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
             no_history_truth="result = int(len(df))",
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
                    "这些订单里各品类的订单笔数占比是多少？用百分数表示，保留两位小数，按占比从高到低排。"],
             question="这些订单里各品类的订单笔数占比是多少？用百分数表示，保留两位小数，按占比从高到低排。",
             ground_truth=_D + "m = d[d['order_date'].str[:7] == '2024-03']; "
                               "result = (m['category'].value_counts(normalize=True) * 100).round(2)",
             no_history_truth="result = (df['category'].value_counts(normalize=True) * 100).round(2)",
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
             no_history_truth="result = round(float((df['gender'] == '男').sum() / len(df) * 100), 2)",
             keywords=["dept", "leave_date", "gender"],
             expect_turns=["exec", "exec", "exec"]),

    # ============================================================
    # 第二批（mul_014 起）：把 13 条扩到 33 条
    #
    # 为什么要扩：13 题时 `off` 对 `state` 的正确率是 5:0，McNemar 双尾 p=0.0625，
    # 差一个不一致对才显著。**注意题量本身不改变判据** —— McNemar 只看不一致对，
    # 6 对是 0.031、5 对是 0.0625，跟总题数无关。扩题改变的是两件事：能产生多少条
    # 不一致对（13 题只挤出 5 条），以及正确率区间的宽度（13 题约 ±13pp，33 题约 ±8pp）。
    #
    # 每条都带 no_history_truth（除下面注明豁免的 6 条），由 tests/test_multi_cases.py
    # 机械验证 gold 与它不相等。理由见 case_model.py 该字段的注释：题面读起来像依赖上文
    # 不够，数据上"不看历史也算得出同一个数"的题等于白跑。
    # ============================================================

    # ---- I 排除条件继承：否定条件在下一轮最容易丢 ----
    EvalCase(id="mul_014", category="multi_turn", dataset="sales", gold_kind="scalar",
             percent_equiv=True,
             turns=["排除华南地区，剩下地区的总销售额是多少元？",
                    "这些地区里，销售额最高的那个占这些地区总额的百分之多少？保留两位小数。"],
             question="这些地区里，销售额最高的那个占这些地区总额的百分之多少？保留两位小数。",
             ground_truth="s = df[df['region'] != '华南']; "
                          "g = (s['units'] * s['price']).groupby(s['region']).sum(); "
                          "result = round(float(g.max() / g.sum() * 100), 2)",
             no_history_truth="g = (df['units'] * df['price']).groupby(df['region']).sum(); "
                              "result = round(float(g.max() / g.sum() * 100), 2)",
             keywords=["region", "华南", "groupby"],
             expect_turns=["exec", "inherit:华南"]),
    EvalCase(id="mul_015", category="multi_turn", dataset="orders", gold_kind="scalar",
             turns=["去掉已取消的订单，重复录入的只算一次。这部分订单分布在哪些城市？",
                    "这些城市里，订单总金额最低的那个一共多少笔？"],
             question="这些城市里，订单总金额最低的那个一共多少笔？",
             ground_truth=_D + "d = d[d['status'] != '已取消']; "
                               "lo = d.groupby('city')['pay_amount'].sum().idxmin(); "
                               "result = int((d['city'] == lo).sum())",
             no_history_truth="lo = df.groupby('city')['pay_amount'].sum().idxmin(); "
                              "result = int((df['city'] == lo).sum())",
             keywords=["status", "city", "pay_amount"],
             expect_turns=["exec", "exec"]),

    # ---- J 指代上一轮算出的集合/实体 ----
    EvalCase(id="mul_016", category="multi_turn", dataset="sales", gold_kind="scalar",
             percent_equiv=True,
             turns=["按总销售额排，最高的 3 个地区是哪几个？",
                    "这 3 个地区的销售额合计占全部地区的百分之多少？保留两位小数。"],
             question="这 3 个地区的销售额合计占全部地区的百分之多少？保留两位小数。",
             ground_truth="s = (df['units'] * df['price']).groupby(df['region']).sum(); "
                          "top = s.nlargest(3); result = round(float(top.sum() / s.sum() * 100), 2)",
             # 豁免：指代的是上一轮算出的地区名单，脱离历史写不出"最直白的答案"
             keywords=["region", "nlargest", "sum"],
             expect_turns=["exec", "exec"]),
    EvalCase(id="mul_017", category="multi_turn", dataset="employees", gold_kind="scalar",
             turns=["绩效评级为 A 的员工有多少人？",
                    "这些人的平均月薪是多少元？"],
             question="这些人的平均月薪是多少元？",
             ground_truth="x = df[df['perf_2023'] == 'A']; "
                          "result = round(float(x['monthly_salary'].mean()), 2)",
             no_history_truth="round(float(df['monthly_salary'].mean()), 2)",
             keywords=["perf_2023", "monthly_salary", "mean"],
             expect_turns=["exec", "inherit:perf_2023"]),

    # ---- K 度量切换：只换指标，筛选范围必须原样带下来 ----
    EvalCase(id="mul_018", category="multi_turn", dataset="sales", gold_kind="scalar",
             turns=["华东地区的总销量是多少件？",
                    "同样这个范围，换成总销售额，是多少元？"],
             question="同样这个范围，换成总销售额，是多少元？",
             ground_truth="e = df[df['region'] == '华东']; "
                          "result = round(float((e['units'] * e['price']).sum()), 2)",
             no_history_truth="round(float((df['units'] * df['price']).sum()), 2)",
             keywords=["region", "华东", "units", "price"],
             expect_turns=["exec", "inherit:华东"]),
    EvalCase(id="mul_019", category="multi_turn", dataset="inventory", gold_kind="scalar",
             turns=["S03 门店的到货量合计是多少件？",
                    "同一个门店，换成销量合计呢？"],
             question="同一个门店，换成销量合计呢？",
             ground_truth="x = df[df['store'] == 'S03']; result = int(x['sold'].sum())",
             no_history_truth="int(df['sold'].sum())",
             keywords=["store", "S03", "sold"],
             expect_turns=["exec", "inherit:S03"]),

    # ---- L 条件逐轮叠加 ----
    EvalCase(id="mul_020", category="multi_turn", dataset="orders", gold_kind="scalar",
             turns=["只看 2024 年 3 月的订单，重复录入的只算一次。",
                    "其中广州的有多少笔？"],
             question="其中广州的有多少笔？",
             ground_truth=_D + "m = d[d['order_date'].str[:7] == '2024-03']; "
                               "result = int((m['city'] == '广州').sum())",
             no_history_truth="int((df['city'] == '广州').sum())",
             keywords=["order_date", "city", "广州"],
             expect_turns=["inherit:2024-03", "inherit:2024-03"]),
    EvalCase(id="mul_021", category="multi_turn", dataset="orders", gold_kind="scalar",
             turns=["只看数码类的已完成订单，重复录入的只算一次。",
                    "这些订单的平均实付金额是多少元？保留两位小数。"],
             question="这些订单的平均实付金额是多少元？保留两位小数。",
             ground_truth=_D + "d = d[(d['status'] == '已完成') & (d['category'] == '数码')]; "
                               "result = round(float(d['pay_amount'].mean()), 2)",
             no_history_truth="round(float(df['pay_amount'].mean()), 2)",
             keywords=["status", "category", "pay_amount", "mean"],
             expect_turns=["inherit:数码", "inherit:数码"]),

    # ---- M 干扰轮：中间夹一轮不改变约束的提问 ----
    EvalCase(id="mul_022", category="multi_turn", dataset="orders", gold_kind="scalar",
             turns=["只看 APP 渠道的订单。",
                    "顺便说一下这张表都有哪些字段？",
                    "再看已完成的。",
                    "这些订单的实付金额合计是多少元？重复录入的只算一次。"],
             question="这些订单的实付金额合计是多少元？重复录入的只算一次。",
             ground_truth=_D + "d = d[(d['channel'] == 'APP') & (d['status'] == '已完成')]; "
                               "result = round(float(d['pay_amount'].sum()), 2)",
             no_history_truth="round(float(df['pay_amount'].sum()), 2)",
             keywords=["channel", "APP", "status", "pay_amount"],
             # 第 2 轮问字段，答完什么都没变 —— 测它会不会把 APP 这个前提弄丢
             expect_turns=["any", "any", "any", "inherit:APP"]),

    # ---- N 口径纠正 ----
    EvalCase(id="mul_023", category="multi_turn", dataset="orders", gold_kind="scalar",
             turns=["已退款订单的实付金额合计是多少元？重复录入的只算一次。",
                    "我说反了，是已取消的，重新算。"],
             question="我说反了，是已取消的，重新算。",
             ground_truth=_D + "d = d[d['status'] == '已取消']; "
                               "result = round(float(d['pay_amount'].sum()), 2)",
             # 最后一轮自己说了"已取消"，唯一的隐藏前提是"去重"（首轮说过，末轮没说）
             no_history_truth="round(float(df[df['status'] == '已取消']['pay_amount'].sum()), 2)",
             keywords=["status", "已取消", "pay_amount"],
             expect_turns=["exec", "inherit:已取消"]),
    EvalCase(id="mul_024", category="multi_turn", dataset="employees", gold_kind="scalar",
             turns=["研发部员工的平均月薪是多少元？只用在职的。",
                    "刚才忘了说，离职的也要算进来，重新算。"],
             question="刚才忘了说，离职的也要算进来，重新算。",
             ground_truth="result = round(float(df[df['dept'] == '研发']['monthly_salary'].mean()), 2)",
             # 不带历史时的最直白答案 = 第 1 轮那个口径（只在职），正好是本题要推翻的那个数
             no_history_truth="x = df[(df['dept'] == '研发') & df['leave_date'].isna()]; "
                              "result = round(float(x['monthly_salary'].mean()), 2)",
             keywords=["dept", "monthly_salary", "mean"],
             expect_turns=["exec", "exec"]),

    # ---- O 换话题：该丢的约束必须丢掉（防过度继承） ----
    EvalCase(id="mul_025", category="multi_turn", dataset="employees", gold_kind="scalar",
             turns=["只看研发部的员工，平均月薪是多少元？",
                    "换个问题：全公司一共有多少名员工？"],
             question="换个问题：全公司一共有多少名员工？",
             ground_truth="result = int(len(df))",
             # 豁免：本题测的是**不要**继承（把「研发部」带下来会答成 40 上下）。
             # 无历史时的答案与 gold 相同，写 no_history 会得到「相等即报错」，所以不写。
             #
             # 原稿写的是"先在订单表问、再换到员工表问"，那条题是错的：runner 的 dataset
             # 是**整条用例固定**的（`path_for(case)` 每轮同一张表），第 1 轮说"订单表"
             # 实际喂的是员工表。多轮题不能跨表——评测器的形状就不支持。
             keywords=["len"],
             expect_turns=["exec", "exec"]),

    # ---- P 指代上一轮算出的实体 ----
    EvalCase(id="mul_026", category="multi_turn", dataset="employees", gold_kind="scalar",
             turns=["哪个部门的平均月薪最高？",
                    "那个部门的员工里，绩效为 A 的有多少人？"],
             question="那个部门的员工里，绩效为 A 的有多少人？",
             ground_truth="b = df.groupby('dept')['monthly_salary'].mean().idxmax(); "
                          "result = int(((df['dept'] == b) & (df['perf_2023'] == 'A')).sum())",
             # 豁免：「那个部门」的指代对象是上一轮的 argmax 结果，脱离历史没有"最直白答案"
             keywords=["dept", "monthly_salary", "perf_2023"],
             expect_turns=["exec", "exec"]),
    EvalCase(id="mul_027", category="multi_turn", dataset="inventory", gold_kind="scalar",
             turns=["累计销量最高的门店是哪个？",
                    "这个门店的期末库存合计是多少件？"],
             question="这个门店的期末库存合计是多少件？",
             ground_truth="s = df.groupby('store')['sold'].sum().idxmax(); "
                          "result = int(df[df['store'] == s]['closing_stock'].sum())",
             # 豁免：同上，「这个门店」是上一轮的 argmax 结果
             keywords=["store", "sold", "closing_stock"],
             expect_turns=["exec", "exec"]),

    # ---- Q 拒答链：连续拒答不能污染后续，也不能被上一轮带成编造 ----
    EvalCase(id="mul_028", category="multi_turn", dataset="orders", gold_kind="scalar",
             turns=["订单表里能算出售后满意度评分吗？",
                    "那能算出每个城市的平均配送天数吗？",
                    "那就只算广州的订单金额合计吧，重复录入的只算一次。"],
             question="那就只算广州的订单金额合计吧，重复录入的只算一次。",
             ground_truth=_D + "result = round(float(d[d['city'] == '广州']['pay_amount'].sum()), 2)",
             no_history_truth="round(float(df[df['city'] == '广州']['pay_amount'].sum()), 2)",
             keywords=["city", "广州", "pay_amount"],
             expect_turns=["refusal", "refusal", "exec"]),
    EvalCase(id="mul_029", category="multi_turn", dataset="employees", gold_kind="text",
             expect_refusal=True,
             turns=["员工的学历分布是怎样的？",
                    "那按部门拆开看学历分布呢？"],
             question="那按部门拆开看学历分布呢？",
             ground_truth="result = '无法回答：数据中没有学历信息'",
             # 豁免：两轮都该拒答，没有"算得出一个数"的对照
             keywords=[],
             # 第 2 轮最容易出事：换了个维度（按部门）看起来像"这次能算了"，实际还是缺字段
             expect_turns=["refusal", "refusal"]),

    # ---- R 时间窗 + 品类（扩 G 家族） ----
    EvalCase(id="mul_030", category="multi_turn", dataset="orders", gold_kind="scalar",
             turns=["只看 2024 年 2 月的订单，重复录入的只算一次。",
                    "这些订单里，食品类的实付金额合计是多少元？"],
             question="这些订单里，食品类的实付金额合计是多少元？",
             ground_truth=_D + "m = d[d['order_date'].str[:7] == '2024-02']; "
                               "result = round(float(m[m['category'] == '食品']['pay_amount'].sum()), 2)",
             no_history_truth="round(float(df[df['category'] == '食品']['pay_amount'].sum()), 2)",
             keywords=["order_date", "category", "食品"],
             expect_turns=["inherit:2024-02", "inherit:2024-02"]),

    # ---- S 粒度下钻 ----
    EvalCase(id="mul_031", category="multi_turn", dataset="sales", gold_kind="series",
             turns=["按产品汇总总销量。",
                    "再按地区拆一层呢？"],
             question="再按地区拆一层呢？",
             ground_truth="result = df.groupby(['product', 'region'])['units'].sum()",
             no_history_truth="df.groupby('region')['units'].sum()",
             keywords=["groupby", "product", "region", "units"],
             expect_turns=["exec", "exec"]),

    # ---- T 份额：分母指代上一轮的实体 ----
    EvalCase(id="mul_032", category="multi_turn", dataset="inventory", gold_kind="scalar",
             percent_equiv=True,
             turns=["K200 这个 SKU 的总销量是多少件？",
                    "它占总销量的百分之多少？保留两位小数。"],
             question="它占总销量的百分之多少？保留两位小数。",
             ground_truth="k = df[df['sku'] == 'K200']; "
                          "result = round(float(k['sold'].sum() / df['sold'].sum() * 100), 2)",
             # 豁免：「它」指上一轮的 SKU；脱离历史，「它」没有指代对象
             keywords=["sku", "K200", "sold"],
             expect_turns=["exec", "exec"]),

    # ---- U 选择性撤销：撤掉中间某轮的约束，保留更早的那个 ----
    EvalCase(id="mul_033", category="multi_turn", dataset="orders", gold_kind="scalar",
             turns=["只看已完成订单。",
                    "其中 APP 渠道的。",
                    "回到全部渠道，但仍只看已完成的，一共多少笔？重复录入的只算一次。"],
             question="回到全部渠道，但仍只看已完成的，一共多少笔？重复录入的只算一次。",
             ground_truth=_D + "d = d[d['status'] == '已完成']; result = int(len(d))",
             no_history_truth="int(len(df))",
             keywords=["status", "已完成"],
             # 末轮要撤掉 APP、保住已完成 —— 单纯"把历史全部叠加"会算成 APP 子集，判错
             expect_turns=["any", "any", "inherit:已完成"]),
]
