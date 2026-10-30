"""多表业务题（20 条）：dataset="biz"，五张表 + 真实脏数据。

为什么单独一批：现有 130 道单轮题全部是单表。`analyze()` 早就支持多表（`dfs['表名']`），
但评测侧只 read_csv，所以"多表 join"这条能力从来没有被任何读数覆盖过。这批题补的就是它。

难度从三处来，不是从"猜出题人口径"来：
1. **多表** —— 销售额只在明细表、品类/成本在商品表、城市/等级在客户表，不 join 算不出来；
2. **脏数据** —— 整行重复、状态带空格、日期带时间戳、金额带千分位或 ¥、SKU 混大小写、
   商品表重复行、客户表编号带前导空格。每一条都在题面里点明，做不做得到是能力问题；
3. **口径** —— 时间窗、状态、去重、分母全部写死在题面，不留"该问就问"的空间。

第 3 点是有意的：这批题要回答"模型能不能在真实数据上把活干完"，不是"模型能不能猜对
我想要什么"。留白类的能力由 ambiguity 那 8 条和多轮题去测，两者混在一起会互相污染归因。

题面里统一出现的清洗约定（gold 用同样的写法，不搞"题面一套、标准答案一套"）：
- 订单表按 order_id 去重（整行重复的录入错误）
- status 先 strip 再比较
- order_date 只取前 10 位（少量带 00:00:00）
- 金额列去掉 ¥ 和千分位逗号后转数值
- SKU 统一大写；商品表按 sku 去重；品类/商品名/城市/等级都 strip
"""

from app.eval.case_model import EvalCase

# ---------------------------------------------------------------- 公共清洗片段
# 20 道题每题都重抄一遍清洗代码既没必要，也容易抄错一个字符就变成两道不同的题。
# 这里按表拆成片段，各题只拼自己用得到的部分；每题最终仍是一段完整可执行的代码。
_ORDERS = (
    "o = dfs['orders'].drop_duplicates('order_id').copy()\n"
    "o['status'] = o['status'].str.strip()\n"
    "o['order_date'] = pd.to_datetime(o['order_date'].astype(str).str[:10])\n"
    "o['customer_id'] = o['customer_id'].str.strip()\n"
)
_ITEMS = (
    "it = dfs['order_items'].copy()\n"
    "it['sku'] = it['sku'].str.upper()\n"
    "it['price'] = (it['unit_price'].astype(str).str.replace('¥', '', regex=False)"
    ".str.replace(',', '', regex=False).astype(float))\n"
    "it['amount'] = it['qty'] * it['price']\n"
)
_PRODUCTS = (
    "p = dfs['products'].drop_duplicates('sku').copy()\n"
    "p['category'] = p['category'].str.strip()\n"
    "p['product_name'] = p['product_name'].str.strip()\n"
)
_CUSTOMERS = (
    "c = dfs['customers'].copy()\n"
    "c['customer_id'] = c['customer_id'].str.strip()\n"
    "c['city'] = c['city'].fillna('').str.strip().replace('', '未知')\n"
    "c['member_level'] = c['member_level'].str.strip().str.title()\n"
)
_REFUNDS = (
    "r = dfs['refunds'].drop_duplicates().copy()\n"
    "r['amount'] = (r['refund_amount'].astype(str).str.replace('¥', '', regex=False)"
    ".str.replace(',', '', regex=False).astype(float))\n"
)
# 已完成订单的明细（销售额口径统一在这里，避免每题各写一遍就各偏一点）
_SALE = (
    "done = o[o['status'] == '已完成']\n"
    "sale = it.merge(done[['order_id', 'order_date', 'channel']], on='order_id')\n"
)
# 明细挂上商品维度（品类 / 成本 / 商品名）
_SALE_PROD = _SALE + "sp = sale.merge(p[['sku', 'category', 'cost', 'product_name']], on='sku')\n"

_ORDER_NOTE = "订单表有整行重复的录入错误，需按订单号去重。"
_MONEY_NOTE = "金额列可能带千分位逗号或人民币符号。"

BIZ_CASES = [
    # 1. 多表入门：日期/状态/去重三处脏点 + join。答案是标量，判定无表示法空间。
    EvalCase(
        id="biz_001", category="correlation", dataset="biz", multi_table=True, gold_kind="scalar",
        question=("2024 年第二季度（4 月 1 日至 6 月 30 日）已完成的订单，销售额合计是多少元？"
                  "销售额按订单明细逐行「件数 × 成交单价」加总。"
                  + _ORDER_NOTE + "状态值前后可能有空格；日期列少量带 00:00:00 的时间部分。" + _MONEY_NOTE + "保留两位小数。"),
        ground_truth=_ORDERS + _ITEMS + _SALE + (
            "q2 = sale[(sale['order_date'] >= '2024-04-01') & (sale['order_date'] <= '2024-06-30')]\n"
            "result = round(float(q2['amount'].sum()), 2)"
        ),
        keywords=["merge", "drop_duplicates", "str.strip", "sum", "round"],
    ),
    # 2. 只考去重语义，不掺 join。题面写「整行完全相同」，避免和「按订单号去重」混淆。
    EvalCase(
        id="biz_002", category="aggregation", dataset="biz", multi_table=True, gold_kind="scalar",
        question="订单表里有多少条「整行完全相同」的重复录入记录（即去掉完全重复的行之后消失的行数）？",
        ground_truth="result = int(dfs['orders'].duplicated().sum())",
        keywords=["duplicated", "sum"],
    ),
    # 3. 商品表重复行不去重会把金额放大一倍——这是最容易被忽略的一处脏点。
    EvalCase(
        id="biz_003", category="correlation", dataset="biz", multi_table=True, gold_kind="series",
        question=("按商品品类统计已完成订单的销售额（元，保留两位小数）。"
                  "品类名去掉首尾空格；商品表有整行重复，需按 SKU 去重；明细的 SKU 混有小写，需统一大写。" + _MONEY_NOTE),
        ground_truth=_ORDERS + _ITEMS + _PRODUCTS + _SALE_PROD + (
            "result = sp.groupby('category')['amount'].sum().round(2)"
        ),
        keywords=["merge", "groupby", "sum", "drop_duplicates", "str.upper"],
    ),
    # 4. left join + 两处缺失来源（客户表没有、城市为空）都归「未知」，必须合并成一类。
    EvalCase(
        id="biz_004", category="correlation", dataset="biz", multi_table=True, gold_kind="series",
        question=("按客户所在城市统计已完成订单的订单数。客户表里查不到的客户、或城市为空的，"
                  "统一记为「未知」。客户编号前后可能带空格。结果按订单数从高到低。"),
        ground_truth=_ORDERS + _CUSTOMERS + (
            "done = o[o['status'] == '已完成']\n"
            "m = done.merge(c[['customer_id', 'city']], on='customer_id', how='left')\n"
            "result = m['city'].fillna('未知').value_counts()"
        ),
        keywords=["merge", "how='left'", "fillna", "value_counts"],
        ordered=True,
    ),
    # 5. 退款表既有已退款订单的退款（不进销售额、也不扣），也有已完成订单的部分退款（要扣）。
    EvalCase(
        id="biz_005", category="correlation", dataset="biz", multi_table=True, gold_kind="scalar",
        question=("已完成订单的净销售额 = 这些订单的销售额合计 减去 这些订单上已发生的退款合计。"
                  "退款表有整行重复的录入错误；退款金额列可能带千分位或人民币符号。"
                  + _ORDER_NOTE + "结果保留两位小数。"),
        ground_truth=_ORDERS + _ITEMS + _REFUNDS + _SALE + (
            "ref_done = r.merge(done[['order_id']], on='order_id')\n"
            "result = round(float(sale['amount'].sum() - ref_done['amount'].sum()), 2)"
        ),
        keywords=["merge", "sum", "drop_duplicates", "round"],
    ),
    # 6. 毛利率必须按金额加权，不能用各 SKU 毛利率的算术平均——这是本题的主要失分点。
    EvalCase(
        id="biz_006", category="correlation", dataset="biz", multi_table=True, gold_kind="series",
        question=("各品类的毛利率（%），口径 = Σ(成交单价 − 成本) × 件数 ÷ Σ 件数 × 成交单价 × 100，保留两位小数。"
                  "只算已完成订单；品类与商品名去掉首尾空格；商品表按 SKU 去重。"),
        ground_truth=_ORDERS + _ITEMS + _PRODUCTS + _SALE_PROD + (
            "t = sp.assign(gp=(sp['price'] - sp['cost']) * sp['qty']).groupby('category')[['gp', 'amount']].sum()\n"
            "result = (t['gp'] / t['amount'] * 100).round(2)"
        ),
        keywords=["assign", "groupby", "sum"],
    ),
    # 7. 分母是去重后的订单数 800，不是明细行数，也不是状态为已退款的数量。
    EvalCase(
        id="biz_007", category="aggregation", dataset="biz", multi_table=True, gold_kind="scalar",
        question=("退款率 = 发生过退款的订单数 ÷ 全部订单数 × 100%，保留两位小数。"
                  "订单表按订单号去重后计算；退款表有整行重复。"),
        ground_truth=_ORDERS + _REFUNDS + (
            "result = round(float(r['order_id'].nunique() / len(o) * 100), 2)"
        ),
        keywords=["nunique", "len", "round"],
    ),
    # 8. 不 strip 会把「已完成」「已完成  」「 已完成」算成三类。
    EvalCase(
        id="biz_008", category="aggregation", dataset="biz", multi_table=True, gold_kind="series",
        question="按订单状态统计订单数（状态值前后可能带空格，先去掉再统计）。结果按订单数从高到低。",
        ground_truth=_ORDERS + "result = o['status'].value_counts()",
        keywords=["value_counts", "str.strip"],
        ordered=True,
    ),
    # 9. 8 个客户在客户表里查不到，但他们确实下过单，要算进去——本题只看订单表。
    EvalCase(
        id="biz_009", category="aggregation", dataset="biz", multi_table=True, gold_kind="scalar",
        question="在已完成订单中，下单 2 次及以上的客户有多少人？" + _ORDER_NOTE,
        ground_truth=_ORDERS + (
            "done = o[o['status'] == '已完成']\n"
            "result = int((done.groupby('customer_id')['order_id'].nunique() >= 2).sum())"
        ),
        keywords=["groupby", "nunique", "sum"],
    ),
    # 10. 二维筛选 + 品类聚合，答案唯一。
    EvalCase(
        id="biz_010", category="correlation", dataset="biz", multi_table=True, gold_kind="text",
        question="小程序渠道中，哪个品类的销售额最高？",
        ground_truth=_ORDERS + _ITEMS + _PRODUCTS + _SALE_PROD + (
            "result = sp[sp['channel'] == '小程序'].groupby('category')['amount'].sum().idxmax()"
        ),
        keywords=["merge", "groupby", "idxmax"],
    ),
    # 11. 刻意要字符串 YYYY-MM 而不是时间索引：canary 那轮踩过「同一件事的索引表示法不同」
    #     被判错的坑（周起始/周结束/区间串），这里把表示法写死在题面上。
    EvalCase(
        id="biz_011", category="timeseries", dataset="biz", multi_table=True, gold_kind="text",
        question="2024 年上半年销售额最高的月份是哪一个？格式 YYYY-MM。" + _ORDER_NOTE + _MONEY_NOTE,
        ground_truth=_ORDERS + _ITEMS + _SALE + (
            "result = sale.set_index('order_date')['amount'].resample('ME').sum().idxmax().strftime('%Y-%m')"
        ),
        keywords=["resample", "idxmax", "strftime"],
    ),
    # 12. 分母是订单数 670，不是明细行数。
    EvalCase(
        id="biz_012", category="aggregation", dataset="biz", multi_table=True, gold_kind="scalar",
        question="已完成订单的平均客单价（销售额 ÷ 订单数）是多少元？保留两位小数。" + _ORDER_NOTE,
        ground_truth=_ORDERS + _ITEMS + _SALE + (
            "result = round(float(sale['amount'].sum() / len(done)), 2)"
        ),
        keywords=["sum", "len", "round"],
    ),
    # 13. 明细 SKU 混小写，不统一大写会把同一个 SKU 拆成两组，排名直接变。
    EvalCase(
        id="biz_013", category="aggregation", dataset="biz", multi_table=True, gold_kind="series",
        question="销售额最高的 5 个商品编码（SKU）是哪些？给出编码和销售额（保留两位小数），按销售额从高到低。",
        ground_truth=_ORDERS + _ITEMS + _PRODUCTS + _SALE_PROD + (
            "result = sp.groupby('sku')['amount'].sum().sort_values(ascending=False).head(5).round(2)"
        ),
        keywords=["groupby", "sort_values", "head"],
        ordered=True,
    ),
    # 14. 两级聚合（先按订单求和、再按等级求均值），先求明细均值会算成件均价。
    EvalCase(
        id="biz_014", category="correlation", dataset="biz", multi_table=True, gold_kind="scalar",
        question=("Gold 会员的平均订单金额是多少元？保留两位小数。会员等级列大小写混写，需统一。"
                  "订单金额 = 该订单明细金额合计；只算已完成订单。"),
        ground_truth=_ORDERS + _ITEMS + _CUSTOMERS + _SALE + (
            "rev = sale.groupby('order_id')['amount'].sum()\n"
            "mg = done.merge(c[['customer_id', 'member_level']], on='customer_id', how='left').merge(rev.rename('rev'), on='order_id')\n"
            "result = round(float(mg[mg['member_level'] == 'Gold']['rev'].mean()), 2)"
        ),
        keywords=["merge", "groupby", "mean", "str.title"],
    ),
    # 15. 去重 + 金额清洗，答案唯一。
    EvalCase(
        id="biz_015", category="aggregation", dataset="biz", multi_table=True, gold_kind="text",
        question="退款金额合计最高的退款原因是什么？退款表有整行重复，退款金额列可能带千分位或人民币符号。",
        ground_truth=_REFUNDS + "result = r.groupby('reason')['amount'].sum().idxmax()",
        keywords=["groupby", "sum", "idxmax"],
    ),
    # 16. 时间窗 + 品类双条件，品类名不 strip 会漏掉带尾空格的那些。
    EvalCase(
        id="biz_016", category="filtering", dataset="biz", multi_table=True, gold_kind="scalar",
        question=("2024 年 3 月 1 日至 4 月 30 日，食品品类的销量合计是多少件？"
                  "只算已完成订单；品类名去掉首尾空格；明细 SKU 混有小写。"),
        ground_truth=_ORDERS + _ITEMS + _PRODUCTS + _SALE_PROD + (
            "w = sp[(sp['order_date'] >= '2024-03-01') & (sp['order_date'] <= '2024-04-30')]\n"
            "result = int(w[w['category'] == '食品']['qty'].sum())"
        ),
        keywords=["merge", "loc", "sum"],
    ),
    # 17. 占比题，percent_equiv 允许 0.5249 与 52.49 两种写法。
    EvalCase(
        id="biz_017", category="correlation", dataset="biz", multi_table=True, gold_kind="scalar",
        question="数码品类的销售额占全部已完成订单销售额的比例是多少？（小数或百分数都算对）",
        ground_truth=_ORDERS + _ITEMS + _PRODUCTS + _SALE_PROD + (
            "result = round(float(sp[sp['category'] == '数码']['amount'].sum() / sp['amount'].sum()), 4)"
        ),
        keywords=["groupby", "sum", "round"],
        percent_equiv=True,
    ),
    # 18. 集合包含判断，不是「买过数码的人数 + 买过食品的人数」。
    EvalCase(
        id="biz_018", category="correlation", dataset="biz", multi_table=True, gold_kind="scalar",
        question="既买过数码品类、也买过食品品类的客户有多少人？只算已完成订单。",
        ground_truth=_ORDERS + _ITEMS + _PRODUCTS + _SALE_PROD + (
            "s = sp.merge(done[['order_id', 'customer_id']], on='order_id')\n"
            "g = s.groupby('customer_id')['category'].agg(set)\n"
            "result = int(sum(1 for x in g if {'数码', '食品'} <= x))"
        ),
        keywords=["merge", "groupby", "agg", "set"],
    ),
    # 19. 先按订单聚合再按渠道求均值（正确），直接对明细求均值是件均价（错误）。
    EvalCase(
        id="biz_019", category="correlation", dataset="biz", multi_table=True, gold_kind="series",
        question="各下单渠道的平均客单价（销售额 ÷ 该渠道订单数）分别是多少元？保留两位小数。只算已完成订单。",
        ground_truth=_ORDERS + _ITEMS + _SALE + (
            "rev = sale.groupby(['channel', 'order_id'])['amount'].sum().reset_index()\n"
            "result = rev.groupby('channel')['amount'].mean().round(2)"
        ),
        keywords=["groupby", "mean", "round"],
    ),
    # 20. 商品名不 strip 会因尾空格把同名商品拆开（本题每个名称唯一，但 strip 后顺序会变）。
    EvalCase(
        id="biz_020", category="correlation", dataset="biz", multi_table=True, gold_kind="text",
        question="数码品类中，销售额最高的商品名称是什么？商品名称需去掉首尾空格；商品表有整行重复。",
        ground_truth=_ORDERS + _ITEMS + _PRODUCTS + _SALE_PROD + (
            "result = sp[sp['category'] == '数码'].groupby('product_name')['amount'].sum().idxmax()"
        ),
        keywords=["merge", "groupby", "idxmax", "str.strip"],
    ),
]

# 订单表去重是这批题里唯一一处「题面不写、gold 却做了」的口径。第一批实测就吃了这个亏：
# 20 题里 7 题判错，逐条看输出全是各城市/各状态多出 1~4 单，正是那 12 行整行重复被算了两次。
# ord_ 系列的老规矩是「重复录入的订单只算一次」写在题面上，这里照同一套办，不另立标准。
# 按 id 显式列出，不用「题面里有没有『去重』二字」判断：biz_006/020 说的是「商品表按 SKU 去重」
# 和「商品表整行重复」，那是另一张表的脏点，拿它当已写明的判据会把订单去重说明整个挡掉。
_ALREADY_SAID = {"biz_001", "biz_005", "biz_007", "biz_009", "biz_011", "biz_012"}  # 已写 _ORDER_NOTE
_NOT_ABOUT_ORDERS = {"biz_002", "biz_015"}   # 002 问的就是重复条数；015 只查退款表
for _c in BIZ_CASES:
    if _c.id in _ALREADY_SAID or _c.id in _NOT_ABOUT_ORDERS:
        continue
    _c.question = _c.question + "订单表有整行重复的录入错误，重复录入的订单只算一次。"

# 第二批实测暴露的是同一个毛病：题面里「销售额」被我默认成「只算已完成订单」，
# join 商品表被我默认成「按 SKU 去重」，但这两句只在部分题里写了。
# 010/011/013/020 全都按「所有状态」算，020 还把已退款订单算了进去；016 没去重商品表，
# 两个重复 SKU 的食品明细被双算（269 件 vs 208 件）。口径只要有一题没写死，就不是能力题。
_NEEDS_DONE = {"biz_010", "biz_011", "biz_013", "biz_020"}      # 用 _SALE/_SALE_PROD 但没写状态
_NEEDS_PROD = {"biz_010", "biz_013", "biz_016", "biz_017", "biz_018"}  # join 了商品表但没写重复
for _c in BIZ_CASES:
    if _c.id in _NEEDS_DONE:
        _c.question = _c.question + "只算已完成订单。"
    if _c.id in _NEEDS_PROD:
        _c.question = _c.question + "商品表有整行重复的录入错误，需按 SKU 去重。"
