"""阶段 3.5 闸门题目（预登记，2026-10-12 冻结；改动任何一题都会改变 docs/gate/answers.json 里的 questions_sha256）。

规则（docs/roadmap/gate-phase35.md）：先写题 → 后跑模型 → 再核答案；不许看了模型输出再改题。
题面写"用户会怎么问"，不写"模型能答什么"；口径确有两种合理读法的，在 verify_gate.py 里给备选答案（alt）。
本文件只有数据，不 import datachat。

dataset 是相对仓库根目录的路径（文件 = 单表，目录 = 多表）。
"""

RETAIL = "data/gate/retail/零售明细.csv"
REPORT = "data/gate/retail_report/零售报表.csv"
OLIST = "data/gate/olist"

QUESTIONS = [
    # ---------------- 单表组 15 题（UCI Online Retail，英国线上礼品零售商 2010-12 ~ 2011-12）
    # 聚合 4
    {"id": "s01", "group": "single", "category": "聚合", "dataset": RETAIL,
     "question": "2011 年全年的销售额是多少英镑？销售额按数量乘以单价算。"},
    {"id": "s02", "group": "single", "category": "聚合", "dataset": RETAIL,
     "question": "一共有多少个不同的客户？"},
    {"id": "s03", "group": "single", "category": "聚合", "dataset": RETAIL,
     "question": "平均每张发票的金额是多少英镑？"},
    {"id": "s04", "group": "single", "category": "聚合", "dataset": REPORT,
     "question": "英国以外的国家一共卖出了多少件商品？"},
    # 过滤 3
    {"id": "s05", "group": "single", "category": "过滤", "dataset": RETAIL,
     "question": "有多少张被取消的发票？"},
    {"id": "s06", "group": "single", "category": "过滤", "dataset": REPORT,
     "question": "单价超过 100 英镑的记录有多少条？"},
    {"id": "s07", "group": "single", "category": "过滤", "dataset": RETAIL,
     "question": "2011 年 12 月有哪些国家下过单？"},
    # 排序 2
    {"id": "s08", "group": "single", "category": "排序", "dataset": RETAIL,
     "question": "销售额最高的前 5 个国家是哪些？"},
    {"id": "s09", "group": "single", "category": "排序", "dataset": RETAIL,
     "question": "实际卖出数量最多的商品是哪个？"},
    # 时间 2
    {"id": "s10", "group": "single", "category": "时间", "dataset": REPORT,
     "question": "哪个月的销售额最高？"},
    {"id": "s11", "group": "single", "category": "时间", "dataset": RETAIL,
     "question": "2011 年每个季度的销售额分别是多少？"},
    # 占比 2
    {"id": "s12", "group": "single", "category": "占比", "dataset": RETAIL,
     "question": "没有客户编号的记录占全部记录的百分之几？"},
    {"id": "s13", "group": "single", "category": "占比", "dataset": RETAIL,
     "question": "英国的销售额占总销售额的比例是多少？"},
    # 应拒答 2（数据里没有所需信息）
    {"id": "s14", "group": "single", "category": "拒答", "dataset": RETAIL, "expect_refusal": True,
     "question": "整体毛利率是多少？"},
    {"id": "s15", "group": "single", "category": "拒答", "dataset": RETAIL, "expect_refusal": True,
     "question": "女性客户的消费总额是多少？"},

    # ---------------- 多表组 10 题（Olist 巴西电商，2016-09 ~ 2018-10，8 张表）
    # join 聚合 4
    {"id": "m01", "group": "multi", "category": "join聚合", "dataset": OLIST,
     "question": "各个州（按客户所在州）的订单数分别是多少？"},
    {"id": "m02", "group": "multi", "category": "join聚合", "dataset": OLIST,
     "question": "SP 州的客户一共付了多少钱？"},
    {"id": "m03", "group": "multi", "category": "join聚合", "dataset": OLIST,
     "question": "按卖家所在州统计，各州卖出商品的平均单价是多少？"},
    {"id": "m04", "group": "multi", "category": "join聚合", "dataset": OLIST,
     "question": "给了 1 星评价的订单，从下单到送达平均用了多少天？"},
    # join 过滤 2
    {"id": "m05", "group": "multi", "category": "join过滤", "dataset": OLIST,
     "question": "买过 health_beauty（健康美容）类商品的客户有多少个？"},
    {"id": "m06", "group": "multi", "category": "join过滤", "dataset": OLIST,
     "question": "2018 年 8 月下单但最终被取消的订单，一共涉及多少支付金额？"},
    # 跨表排序 2
    {"id": "m07", "group": "multi", "category": "跨表排序", "dataset": OLIST,
     "question": "销售额最高的 3 个商品类别是什么？用英文类别名。"},
    {"id": "m08", "group": "multi", "category": "跨表排序", "dataset": OLIST,
     "question": "订单数最多的 5 个城市（按客户所在城市）是哪些？"},
    # 应拒答 2
    {"id": "m09", "group": "multi", "category": "拒答", "dataset": OLIST, "expect_refusal": True,
     "question": "各个年龄段的客户分别贡献了多少销售额？"},
    {"id": "m10", "group": "multi", "category": "拒答", "dataset": OLIST, "expect_refusal": True,
     "question": "各商品类别的利润分别是多少？"},
]

# 预登记的 6 类失败（判错时人工填 failure_class）
FAILURE_CLASSES = {
    1: "编码/解析",
    2: "schema 理解",
    3: "口径歧义",
    4: "计算错",
    5: "result 契约违反",
    6: "拒答失当",
}
