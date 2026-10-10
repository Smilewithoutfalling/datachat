"""阶段 3 新增评测题：3 张合成表（scripts/gen_eval_data.py 生成，data/eval/），共 80 题。

- 题面写清口径（是否去重、算哪些状态、保留几位小数），避免 B32 那种"两种理解都合理"的题混进普通题；
- 故意有歧义的题单列为 ambiguity 类，用 alt_ground_truths 列出所有合理理解，命中任一即对；
- 数据里没有的信息单列为 refusal 类，期望模型拒答并给出原因（result = "无法回答：原因"）。
"""
from app.eval.case_model import EvalCase

# 去重后的订单（表里有 18 条整行重复的录入）
_D = "d = df.drop_duplicates('order_id'); "
_DONE = _D + "d = d[d['status'] == '已完成']; "


def _refuse(reason: str) -> str:
    return f"result = '无法回答：{reason}'"


# ============================================================
# 电商订单 orders（30 题）
# ============================================================
ORDER_CASES = [
    # ---- 聚合
    EvalCase(id="ord_001", category="aggregation", dataset="orders",
             question="去掉重复录入的订单后，一共有多少笔订单？",
             ground_truth="result = df['order_id'].nunique()"),
    EvalCase(id="ord_002", category="aggregation", dataset="orders",
             question="已完成订单的实付金额合计是多少元？重复录入的订单只算一次，保留两位小数。",
             ground_truth=_DONE + "result = round(d['pay_amount'].sum(), 2)"),
    EvalCase(id="ord_003", category="aggregation", dataset="orders", ordered=True,
             question="各品类已完成订单的实付金额合计，按金额从高到低排列。重复录入的订单只算一次，保留两位小数。",
             ground_truth=_DONE + "result = d.groupby('category')['pay_amount'].sum().round(2).sort_values(ascending=False)"),
    EvalCase(id="ord_004", category="aggregation", dataset="orders",
             question="已完成订单的客单价（平均每笔订单的实付金额）是多少元？重复录入的订单只算一次，保留两位小数。",
             ground_truth=_DONE + "result = round(d['pay_amount'].mean(), 2)"),
    EvalCase(id="ord_005", category="aggregation", dataset="orders", percent_equiv=True,
             question="各渠道的订单数占全部订单的比例是多少？不论订单状态，重复录入的订单只算一次，用百分数表示并保留两位小数。",
             ground_truth=_D + "result = (d['channel'].value_counts(normalize=True) * 100).round(2)"),
    EvalCase(id="ord_006", category="aggregation", dataset="orders",
             question="哪个城市的已完成订单实付金额合计最高？城市为空的订单不计，重复录入的订单只算一次。",
             ground_truth=_DONE + "result = d.dropna(subset=['city']).groupby('city')['pay_amount'].sum().idxmax()"),
    EvalCase(id="ord_007", category="aggregation", dataset="orders",
             question="下过 3 笔及以上订单的用户有多少个？不论订单状态，重复录入的订单只算一次。",
             ground_truth=_D + "result = int((d.groupby('user_id').size() >= 3).sum())"),
    EvalCase(id="ord_008", category="aggregation", dataset="orders", percent_equiv=True,
             question="退款率是多少？即已退款订单数占全部订单数的比例，重复录入的订单只算一次，用百分数表示并保留两位小数。",
             ground_truth=_D + "result = round((d['status'] == '已退款').mean() * 100, 2)"),
    # ---- 过滤 / 数据质量
    EvalCase(id="ord_009", category="filtering", dataset="orders",
             question="城市字段为空的记录有多少条？按表中原始行数计。",
             ground_truth="result = int(df['city'].isna().sum())"),
    EvalCase(id="ord_010", category="filtering", dataset="orders",
             question="表中有多少条记录是与前面某条记录整行完全重复的？",
             ground_truth="result = int(df.duplicated().sum())"),
    EvalCase(id="ord_011", category="filtering", dataset="orders",
             question="数码品类中单价超过 2000 元的已完成订单有几笔？重复录入的订单只算一次。",
             ground_truth=_DONE + "result = int(((d['category'] == '数码') & (d['unit_price'] > 2000)).sum())"),
    EvalCase(id="ord_012", category="filtering", dataset="orders",
             question="2024 年 6 月通过小程序下单且已完成的订单，实付金额合计是多少元？重复录入的订单只算一次，保留两位小数。",
             ground_truth=_DONE + "m = d['order_date'].str.startswith('2024-06') & (d['channel'] == '小程序'); "
                                  "result = round(d.loc[m, 'pay_amount'].sum(), 2)"),
    EvalCase(id="ord_013", category="filtering", dataset="orders",
             question="享受了折扣的订单有多少笔？折扣为空视为无折扣，不论订单状态，重复录入的订单只算一次。",
             ground_truth=_D + "result = int((d['discount'].fillna(0) > 0).sum())"),
    EvalCase(id="ord_014", category="filtering", dataset="orders", ordered=True,
             question="实付金额最高的 5 笔已完成订单，订单号依次是什么？按实付金额从高到低，只列订单号。",
             ground_truth=_DONE + "result = d.nlargest(5, 'pay_amount')['order_id'].tolist()"),
    # ---- 关联
    EvalCase(id="ord_015", category="correlation", dataset="orders",
             question="各渠道已完成订单的平均折扣率是多少？折扣为空按 0 计，重复录入的订单只算一次，保留 4 位小数。",
             ground_truth=_DONE + "result = d.assign(discount=d['discount'].fillna(0)).groupby('channel')['discount'].mean().round(4)"),
    EvalCase(id="ord_016", category="correlation", dataset="orders",
             question="已完成订单按城市和品类汇总实付金额，做成城市为行、品类为列的交叉表。城市为空的不计，"
                      "重复录入的订单只算一次，没有订单的格子填 0，保留两位小数。",
             ground_truth=_DONE + "result = d.dropna(subset=['city']).pivot_table(index='city', columns='category', "
                                  "values='pay_amount', aggfunc='sum', fill_value=0).round(2)"),
    EvalCase(id="ord_017", category="correlation", dataset="orders",
             question="购买件数（qty）与实付金额的皮尔逊相关系数是多少？用去重后的全部订单计算，保留 4 位小数。",
             ground_truth=_D + "result = round(d['qty'].corr(d['pay_amount']), 4)"),
    EvalCase(id="ord_018", category="correlation", dataset="orders",
             question="哪个品类的退款比例（该品类已退款订单数 ÷ 该品类订单数）最高？重复录入的订单只算一次。",
             ground_truth=_D + "result = d.assign(r=d['status'] == '已退款').groupby('category')['r'].mean().idxmax()"),
    # ---- 时序
    EvalCase(id="ord_019", category="timeseries", dataset="orders",
             question="每个月已完成订单的实付金额合计是多少？重复录入的订单只算一次，保留两位小数。",
             ground_truth=_DONE + "d['order_date'] = pd.to_datetime(d['order_date']); "
                                  "result = d.set_index('order_date')['pay_amount'].resample('ME').sum().round(2)"),
    EvalCase(id="ord_020", category="timeseries", dataset="orders",
             question="已完成订单的月实付金额，环比增长率最高的是哪个月？重复录入的订单只算一次，答案格式如 2024-03。",
             ground_truth=_DONE + "m = d.groupby(d['order_date'].str[:7])['pay_amount'].sum(); "
                                  "result = m.pct_change().idxmax()"),
    EvalCase(id="ord_021", category="timeseries", dataset="orders",
             question="一周七天里哪一天的订单数最多？不论订单状态，重复录入的订单只算一次。答案用数字 0–6 表示，0 是周一、6 是周日。",
             ground_truth=_D + "result = int(pd.to_datetime(d['order_date']).dt.dayofweek.value_counts().idxmax())"),
    EvalCase(id="ord_022", category="timeseries", dataset="orders",
             question="2024 年第一季度和第二季度的已完成订单实付金额合计分别是多少？重复录入的订单只算一次，保留两位小数。",
             ground_truth=_DONE + "q = pd.to_datetime(d['order_date']).dt.quarter; "
                                  "result = d.groupby(q)['pay_amount'].sum().round(2)"),
    EvalCase(id="ord_023", category="timeseries", dataset="orders",
             question="每个月有多少个不同的下单用户？不论订单状态。",
             ground_truth="result = df.groupby(df['order_date'].str[:7])['user_id'].nunique()"),
    # ---- 应拒答
    EvalCase(id="ord_024", category="refusal", dataset="orders", expect_refusal=True,
             question="哪个品类的毛利率最高？", ground_truth=_refuse("数据中没有成本或毛利字段")),
    EvalCase(id="ord_025", category="refusal", dataset="orders", expect_refusal=True,
             question="下单用户的平均年龄是多少？", ground_truth=_refuse("数据中没有用户年龄信息")),
    EvalCase(id="ord_026", category="refusal", dataset="orders", expect_refusal=True,
             question="订单从下单到签收平均用了几天？", ground_truth=_refuse("数据中没有签收或物流时间")),
    # ---- 歧义（列出的理解都算对）
    EvalCase(id="ord_027", category="ambiguity", dataset="orders",
             question="总销售额是多少？",
             ground_truth=_DONE + "result = round(d['pay_amount'].sum(), 2)",
             alt_ground_truths=[
                 _D + "result = round(d['pay_amount'].sum(), 2)",                                  # 不区分状态
                 _DONE + "result = round((d['qty'] * d['unit_price']).sum(), 2)",                 # 折扣前
                 "d = df[df['status'] == '已完成']; result = round(d['pay_amount'].sum(), 2)",     # 未去重
             ]),
    EvalCase(id="ord_028", category="ambiguity", dataset="orders",
             question="平均每单买几件？保留两位小数。",
             ground_truth=_D + "result = round(d['qty'].mean(), 2)",
             alt_ground_truths=[_DONE + "result = round(d['qty'].mean(), 2)",
                                "result = round(df['qty'].mean(), 2)"]),
    EvalCase(id="ord_029", category="ambiguity", dataset="orders",
             question="哪个品类卖得最好？",
             ground_truth=_DONE + "result = d.groupby('category')['pay_amount'].sum().idxmax()",   # 按销售额
             alt_ground_truths=[_DONE + "result = d.groupby('category')['qty'].sum().idxmax()",   # 按件数
                                _DONE + "result = d['category'].value_counts().idxmax()",         # 按订单数
                                _D + "result = d.groupby('category')['pay_amount'].sum().idxmax()",
                                _D + "result = d.groupby('category')['qty'].sum().idxmax()",
                                _D + "result = d['category'].value_counts().idxmax()"]),
    EvalCase(id="ord_030", category="ambiguity", dataset="orders", percent_equiv=True,
             question="复购率是多少？",
             ground_truth=_D + "n = d.groupby('user_id').size(); result = round((n >= 2).mean() * 100, 2)",
             alt_ground_truths=[_DONE + "n = d.groupby('user_id').size(); result = round((n >= 2).mean() * 100, 2)",
                                _D + "n = d.groupby('user_id').size(); result = round(n[n >= 2].sum() / n.sum() * 100, 2)",
                                # B47：排除已退款的有效订单口径
                                _D + "d = d[d['status'] != '已退款']; n = d.groupby('user_id').size(); "
                                     "result = round((n >= 2).mean() * 100, 2)"]),
]


# ============================================================
# 员工花名册 employees（25 题）
# ============================================================
_ACT = "a = df[df['leave_date'].isna()]; "

EMP_CASES = [
    # ---- 聚合
    EvalCase(id="emp_001", category="aggregation", dataset="employees",
             question="目前在职员工有多少人？离职日期为空表示在职。",
             ground_truth="result = int(df['leave_date'].isna().sum())"),
    EvalCase(id="emp_002", category="aggregation", dataset="employees", ordered=True,
             question="各部门在职人数是多少？按人数从多到少排列。",
             ground_truth=_ACT + "result = a['dept'].value_counts()"),
    EvalCase(id="emp_003", category="aggregation", dataset="employees",
             question="在职员工中各职级的平均月薪是多少？保留两位小数。",
             ground_truth=_ACT + "result = a.groupby('level')['monthly_salary'].mean().round(2)"),
    EvalCase(id="emp_004", category="aggregation", dataset="employees",
             question="在职员工月薪的中位数是多少元？",
             ground_truth=_ACT + "result = float(a['monthly_salary'].median())"),
    EvalCase(id="emp_005", category="aggregation", dataset="employees", percent_equiv=True,
             question="在职员工中女性的占比是多少？用百分数表示并保留两位小数。",
             ground_truth=_ACT + "result = round((a['gender'] == '女').mean() * 100, 2)"),
    EvalCase(id="emp_006", category="aggregation", dataset="employees",
             question="哪个部门在职员工的平均月薪最高？",
             ground_truth=_ACT + "result = a.groupby('dept')['monthly_salary'].mean().idxmax()"),
    EvalCase(id="emp_007", category="aggregation", dataset="employees",
             question="2024 年离职了多少人？",
             ground_truth="result = int(df['leave_date'].str.startswith('2024').sum())"),
    EvalCase(id="emp_008", category="aggregation", dataset="employees",
             question="2023 年度绩效为 A 的员工有多少人？包括已离职员工。",
             ground_truth="result = int((df['perf_2023'] == 'A').sum())"),
    # ---- 过滤
    EvalCase(id="emp_009", category="filtering", dataset="employees",
             question="在上海工作、职级为 P7 及以上的在职员工有多少人？",
             ground_truth=_ACT + "result = int(((a['city'] == '上海') & a['level'].isin(['P7', 'P8'])).sum())"),
    EvalCase(id="emp_010", category="filtering", dataset="employees",
             question="2023 年度绩效为空的员工有多少人？包括已离职员工。",
             ground_truth="result = int(df['perf_2023'].isna().sum())"),
    EvalCase(id="emp_011", category="filtering", dataset="employees", ordered=True,
             question="月薪最高的 3 名在职员工，员工编号依次是什么？按月薪从高到低，只列员工编号。",
             ground_truth=_ACT + "result = a.nlargest(3, 'monthly_salary')['emp_id'].tolist()"),
    EvalCase(id="emp_012", category="filtering", dataset="employees",
             question="研发部在职员工中，月薪高于研发部在职员工平均月薪的有多少人？",
             ground_truth=_ACT + "r = a[a['dept'] == '研发']; result = int((r['monthly_salary'] > r['monthly_salary'].mean()).sum())"),
    # ---- 关联
    EvalCase(id="emp_013", category="correlation", dataset="employees",
             question="在职员工按城市和职级统计人数，做成城市为行、职级为列的交叉表。",
             ground_truth=_ACT + "result = pd.crosstab(a['city'], a['level'])"),
    EvalCase(id="emp_014", category="correlation", dataset="employees", percent_equiv=True,
             question="各部门 2023 年度绩效为 A 的比例是多少？只算有绩效记录的员工（含已离职），用百分数表示并保留两位小数。",
             ground_truth="p = df.dropna(subset=['perf_2023']); "
                          "result = (p.assign(a=p['perf_2023'] == 'A').groupby('dept')['a'].mean() * 100).round(2)"),
    EvalCase(id="emp_015", category="correlation", dataset="employees",
             question="在职员工的年龄（2024 减出生年份）与月薪的皮尔逊相关系数是多少？保留 4 位小数。",
             ground_truth=_ACT + "result = round((2024 - a['birth_year']).corr(a['monthly_salary']), 4)"),
    EvalCase(id="emp_016", category="correlation", dataset="employees",
             question="各部门在职员工中男、女各有多少人？做成部门为行、性别为列的交叉表。",
             ground_truth=_ACT + "result = pd.crosstab(a['dept'], a['gender'])"),
    # ---- 时序
    EvalCase(id="emp_017", category="timeseries", dataset="employees",
             question="每年各入职了多少人？包括已离职员工。",
             ground_truth="result = df.groupby(df['hire_date'].str[:4].astype(int)).size()"),
    EvalCase(id="emp_018", category="timeseries", dataset="employees",
             question="2022、2023、2024 年各离职了多少人？",
             ground_truth="y = df['leave_date'].dropna().str[:4].astype(int); "
                          "result = y.value_counts().reindex([2022, 2023, 2024], fill_value=0)"),
    EvalCase(id="emp_019", category="timeseries", dataset="employees",
             question="在职员工的平均司龄是多少年？司龄按 2024-09-30 减去入职日期的天数 ÷ 365 计算，保留两位小数。",
             ground_truth=_ACT + "days = (pd.Timestamp('2024-09-30') - pd.to_datetime(a['hire_date'])).dt.days; "
                                 "result = round((days / 365).mean(), 2)"),
    EvalCase(id="emp_020", category="timeseries", dataset="employees", percent_equiv=True,
             question="2023 年的员工流失率是多少？流失率 = 2023 年内离职人数 ÷ 2023-01-01 当天在职人数，用百分数表示并保留两位小数。",
             ground_truth="h = pd.to_datetime(df['hire_date']); l = pd.to_datetime(df['leave_date']); "
                          "base = ((h <= '2023-01-01') & (l.isna() | (l >= '2023-01-01'))).sum(); "
                          "left = ((l >= '2023-01-01') & (l <= '2023-12-31')).sum(); "
                          "result = round(left / base * 100, 2)"),
    # ---- 应拒答
    EvalCase(id="emp_021", category="refusal", dataset="employees", expect_refusal=True,
             question="各部门的平均加班时长是多少？", ground_truth=_refuse("数据中没有加班或考勤记录")),
    EvalCase(id="emp_022", category="refusal", dataset="employees", expect_refusal=True,
             question="员工离职的主要原因是什么？", ground_truth=_refuse("数据中只有离职日期，没有离职原因")),
    EvalCase(id="emp_023", category="refusal", dataset="employees", expect_refusal=True,
             question="今年各部门一共发了多少年终奖？", ground_truth=_refuse("数据中只有月薪，没有奖金字段")),
    # ---- 歧义
    EvalCase(id="emp_024", category="ambiguity", dataset="employees",
             question="公司有多少员工？",
             ground_truth="result = int(df['leave_date'].isna().sum())",
             alt_ground_truths=["result = len(df)"]),
    EvalCase(id="emp_025", category="ambiguity", dataset="employees",
             question="平均工资是多少？",
             ground_truth=_ACT + "result = round(a['monthly_salary'].mean(), 2)",
             alt_ground_truths=["result = round(df['monthly_salary'].mean(), 2)",
                                _ACT + "result = round(a['monthly_salary'].mean() * 12, 2)"]),   # 年薪口径
]


# ============================================================
# 门店日频库存 inventory（25 题）
# ============================================================
_DAY = "t = df.groupby('date')[['sold', 'closing_stock']].sum(); "

INV_CASES = [
    # ---- 聚合
    EvalCase(id="inv_001", category="aggregation", dataset="inventory",
             question="整个期间各门店的总销量是多少件？",
             ground_truth="result = df.groupby('store')['sold'].sum()"),
    EvalCase(id="inv_002", category="aggregation", dataset="inventory",
             question="哪个 SKU 的总销量最高？",
             ground_truth="result = df.groupby('sku')['sold'].sum().idxmax()"),
    EvalCase(id="inv_003", category="aggregation", dataset="inventory",
             question="2024 年 3 月所有门店的到货量合计是多少件？",
             ground_truth="result = int(df.loc[df['date'].str.startswith('2024-03'), 'received'].sum())"),
    EvalCase(id="inv_004", category="aggregation", dataset="inventory",
             question="各 SKU 平均每家门店每天卖多少件？即按每条记录（门店 × 日期）的销量求平均，保留两位小数。",
             ground_truth="result = df.groupby('sku')['sold'].mean().round(2)"),
    EvalCase(id="inv_005", category="aggregation", dataset="inventory",
             question="2024-05-31 当天，各门店所有 SKU 的期末库存合计是多少件？",
             ground_truth="result = df[df['date'] == '2024-05-31'].groupby('store')['closing_stock'].sum()"),
    # ---- 过滤
    EvalCase(id="inv_006", category="filtering", dataset="inventory",
             question="期末库存为 0（当日缺货）的记录有多少条？",
             ground_truth="result = int((df['closing_stock'] == 0).sum())"),
    EvalCase(id="inv_007", category="filtering", dataset="inventory",
             question="哪家门店期末库存为 0 的记录最多？",
             ground_truth="result = df[df['closing_stock'] == 0]['store'].value_counts().idxmax()"),
    EvalCase(id="inv_008", category="filtering", dataset="inventory",
             question="K400 在 S04 门店有多少天期末库存为 0？",
             ground_truth="result = int(((df['sku'] == 'K400') & (df['store'] == 'S04') & (df['closing_stock'] == 0)).sum())"),
    EvalCase(id="inv_009", category="filtering", dataset="inventory",
             question="只看有到货（received > 0）的记录，平均每次到货多少件？保留两位小数。",
             ground_truth="result = round(df.loc[df['received'] > 0, 'received'].mean(), 2)"),
    EvalCase(id="inv_010", category="filtering", dataset="inventory",
             question="单条记录日销量超过 60 件的有多少条？",
             ground_truth="result = int((df['sold'] > 60).sum())"),
    # ---- 关联
    EvalCase(id="inv_011", category="correlation", dataset="inventory",
             question="按门店和 SKU 汇总总销量，做成门店为行、SKU 为列的交叉表。",
             ground_truth="result = df.pivot_table(index='store', columns='sku', values='sold', aggfunc='sum')"),
    EvalCase(id="inv_012", category="correlation", dataset="inventory", percent_equiv=True,
             question="各 SKU 期末库存为 0 的记录占该 SKU 全部记录的比例是多少？用百分数表示并保留两位小数。",
             ground_truth="result = (df.assign(z=df['closing_stock'] == 0).groupby('sku')['z'].mean() * 100).round(2)"),
    EvalCase(id="inv_013", category="correlation", dataset="inventory",
             question="工作日和周末（周六、周日）的平均单条记录销量分别是多少？保留两位小数。",
             ground_truth="w = pd.to_datetime(df['date']).dt.dayofweek >= 5; "
                          "result = df.groupby(w.map({False: '工作日', True: '周末'}))['sold'].mean().round(2)"),
    EvalCase(id="inv_014", category="correlation", dataset="inventory",
             question="各门店的库存周转天数是多少？先把每家门店每天所有 SKU 的销量和期末库存各自加总，"
                      "周转天数 = 日均期末库存 ÷ 日均销量，保留两位小数。",
             ground_truth="s = df.groupby(['store', 'date'])[['sold', 'closing_stock']].sum().groupby(level=0).mean(); "
                          "result = (s['closing_stock'] / s['sold']).round(2)"),
    # ---- 时序
    EvalCase(id="inv_015", category="timeseries", dataset="inventory",
             question="每个月所有门店的总销量是多少件？",
             ground_truth="d = df.assign(date=pd.to_datetime(df['date'])); "
                          "result = d.set_index('date')['sold'].resample('ME').sum()"),
    EvalCase(id="inv_016", category="timeseries", dataset="inventory",
             question="按自然周（周一至周日）统计所有门店的总销量。",
             ground_truth="d = df.assign(date=pd.to_datetime(df['date'])); "
                          "result = d.set_index('date')['sold'].resample('W-SUN').sum()"),
    EvalCase(id="inv_017", category="timeseries", dataset="inventory",
             question="5 月 1 日至 5 日所有门店合计的日均销量，比 4 月的日均销量高百分之多少？保留两位小数。",
             ground_truth=_DAY + "may = t.loc['2024-05-01':'2024-05-05', 'sold'].mean(); "
                                 "apr = t.loc['2024-04-01':'2024-04-30', 'sold'].mean(); "
                                 "result = round((may / apr - 1) * 100, 2)"),
    EvalCase(id="inv_018", category="timeseries", dataset="inventory",
             question="S01 门店 K100 的 7 日移动平均销量，在 2024-05-31 这天是多少？保留两位小数。",
             ground_truth="s = df[(df['store'] == 'S01') & (df['sku'] == 'K100')].set_index('date')['sold']; "
                          "result = round(s.rolling(7).mean().loc['2024-05-31'], 2)"),
    EvalCase(id="inv_019", category="timeseries", dataset="inventory",
             question="哪一天所有门店合计的销量最高？日期格式 YYYY-MM-DD。",
             ground_truth=_DAY + "result = t['sold'].idxmax()"),
    EvalCase(id="inv_020", category="timeseries", dataset="inventory",
             question="3、4、5 月各有多少条期末库存为 0 的记录？",
             ground_truth="z = df[df['closing_stock'] == 0]; "
                          "result = z.groupby(z['date'].str[5:7].astype(int)).size().reindex([3, 4, 5], fill_value=0)"),
    # ---- 应拒答
    EvalCase(id="inv_021", category="refusal", dataset="inventory", expect_refusal=True,
             question="哪个 SKU 的销售额最高？", ground_truth=_refuse("数据中只有销量，没有价格或金额")),
    EvalCase(id="inv_022", category="refusal", dataset="inventory", expect_refusal=True,
             question="各门店的店长分别是谁？", ground_truth=_refuse("数据中没有门店人员信息")),
    EvalCase(id="inv_023", category="refusal", dataset="inventory", expect_refusal=True,
             question="哪个供应商的到货最及时？", ground_truth=_refuse("数据中没有供应商或订货时间")),
    # ---- 歧义
    EvalCase(id="inv_024", category="ambiguity", dataset="inventory",
             question="平均库存是多少？",
             ground_truth="result = round(df['closing_stock'].mean(), 2)",
             alt_ground_truths=[_DAY + "result = round(t['closing_stock'].mean(), 2)",
                                "result = round(df['opening_stock'].mean(), 2)",
                                "result = round(((df['opening_stock'] + df['closing_stock']) / 2).mean(), 2)"]),
    EvalCase(id="inv_025", category="ambiguity", dataset="inventory",
             question="平均每天卖多少件？",
             ground_truth=_DAY + "result = round(t['sold'].mean(), 2)",
             alt_ground_truths=["result = round(df['sold'].mean(), 2)"]),
]

EXTRA_CASES = ORDER_CASES + EMP_CASES + INV_CASES
