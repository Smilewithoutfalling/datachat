"""clarify 判据（EV-B7 补充）：澄清不是「随便问一句」，是「缺的东西必须能指出来」。

## 为什么需要这个文件

`app/eval/cases_negative.py` 的 6 道 clarify 题原来只在注释里写「这题缺口径」——
散文。散文不能执行，也不能对账：谁都可以说「这题模糊」，谁也都可以说「这不模糊」。
更麻烦的是，`neg_005`（哪个品类表现最好）和 `ord_029`（哪个品类卖得最好）在题面上
是同构的，前者要求反问、后者要求直接算（还给了 5 个备选答案）。两句话差两个词，
任何提示词都做不到对一句反问、对另一句直接算。

所以把「缺什么」写成结构化字段 `EvalCase.clarify_gap`，再用本文件拿题面字面去核。
判据因此从「出题人的自述」变成「可以被机器反驳的断言」。

## 一条问题能被直接计算的三个条件

分析任何一张表，能算出答案要三件事同时落到字段上：

  object    算哪张表 / 按哪个维度分组 —— 可以是列，也可以是「这批数据」这种整表指代
  metric    算哪个量 —— 必须是字段、字段的算术组合，或字典里已定义的派生指标
  operator  怎么聚合 —— 求和 / 均值 / 计数 / 最大 / 占比 / 分布 / 排名 …

三者齐全，模型自己挑一个口径算下去是合理的（口径分叉写进结论即可）。
缺任何一个，**合理答案有无穷多个**，挑一个算等于替用户做决定 —— 这是 clarify。

缺的若是 metric 且数据里根本没有（不是「没说清」而是「不存在」），那就不是 clarify
而是拒答：**clarify 缺的是「怎么算」，拒答缺的是「算什么」。** 这句话是整批的分界线，
`emp_022`（离职的主要原因）走拒答线、`neg_001`（销售额怎么样）走澄清线，区别只在这里。

## 两个辅助维度

  scope     范围：时间窗口、城市、品类等筛选条件
  baseline  判断高低好坏的比较基准

它们不是「能不能算」的必要条件（`ord_028` 没有时间范围照样能算平均每单件数），
但在**问法是评价式**（怎么样 / 高不高 / 多吗 / 情况如何）时，缺了它们就没有落点：
「最近的订单多吗」——「最近」是多久、「多」跟什么比，两个都没给。

## 词表的边界（宁窄不宽）

`METRIC_MARKERS` / `OPERATOR_MARKERS` **只用来验证已声明的 gap**，不用来自动判定
一道新题该不该澄清。自动判定需要语义理解，词表做不到（实测：拿它扫 202 道题，
37 道「不可答」里 20 多道是正常题被误判）。这里的用法反过来 ——
「你声明缺 metric，那题面里就不许出现指标名词」，这是可判定的。
"""
from __future__ import annotations

import re

# 缺口的五种类型。前三种决定「能不能算」，后两种只影响评价式问法有没有落点。
GAP_KINDS = ("object", "metric", "operator", "scope", "baseline")

# 可计量的量。取自 data/eval/*.dict.csv 的字段说明，只保留**能量出数**的名词；
# 城市 / 渠道 / 品类 / 部门 / 日期这类纯维度不算（它们能 group by，但本身不是一个量）。
# 「买几件 / 多少件」单列：中文里「几件」既是算子（多少）又暗含指标（件数），
# 光靠「件数」收不到「平均每单买几件」。
METRIC_MARKERS = re.compile(
    r"金额|单价|价格|标价|成本|利润|毛利|销量|件数|买几件|多少件|数量|库存|到货"
    r"|工资|月薪|年薪|薪资|奖金|绩效|折扣|退款|销售额|营收|收入|客单价|复购率|流失率"
    r"|占比|比重|比例|比率|行数|条数|人数|员工|天数|司龄|年龄|评分|分数|时长|周转"
)

# 聚合 / 统计算子。注意不含「最好 / 最高」这类**选择**算子 ——
# 它们必须配一个指标才有意义（「哪个品类最好」说不出是按金额还是按件数）。
OPERATOR_MARKERS = re.compile(
    r"总|合计|求和|平均|均值|中位数|最大|最小|最多|最少|占比|比重|比率|数量|多少"
    r"|几个|几件|几条|几位|排名|排序|分布|趋势|走势|变化|交叉表|标准差|方差|去重|统计|列出|找出"
)

# 评价式最高级：没有指标时，它就是一个无法落地的选择算子。
SUPERLATIVE = re.compile(r"最好|最佳|最优|最差|表现最好")

# 具体的时间锚点。「最近」本身不是锚点 —— 它必须配数字或明确的周期才算划定了范围。
SCOPE_ANCHOR = re.compile(
    r"最近\s*\d|最近[一二三四五六七八九十\d]+[天周月年]|近\s*\d|本周|上周|本月|上月"
    r"|今年|去年|上半年|下半年|Q[1-4]|\d+\s*月|\d{4}\s*年"
)

# 比较基准的落点。
BASELINE_MARKERS = re.compile("比|相比|对比|行业|同行|平均|历史|标准|基准")

# 表名 / 可指认的对象。用于判断 neg_006「帮我看看这批数据」有没有 object。
# 「这批数据」「数据表」**不算**对象：它们只说明"整个数据集"，没有指认要看哪张表、
# 哪个维度 —— 这正是 neg_006 缺的东西。
OBJECT_MARKERS = re.compile(
    r"订单|员工|库存|商品|客户|退款|产品|销量|销售额|明细|记录"
)


def missing_items(question: str) -> set[str]:
    """题面字面上**没给**的项。口径从窄：词表没覆盖到的一律当作「没给」。

    这个方向是安全的一侧：声明缺口时如果多报，`check_declared_gap` 会拦住
    （声明缺 metric 却在题面里找到指标名词）。如果少报，只是漏掉一次核对机会，
    不会把「其实能算」的题判成 clarify。
    """
    gaps: set[str] = set()
    if not METRIC_MARKERS.search(question):
        gaps.add("metric")
    if not OPERATOR_MARKERS.search(question):
        gaps.add("operator")
    if not OBJECT_MARKERS.search(question):
        gaps.add("object")
    # scope / baseline 只在题面**声称**了范围或评价时才检查：
    # 「库存情况如何」没有「最近」，它缺的是 operator，不是 scope。
    if re.search(r"最近|现在|当前|目前|这(批|些|段)", question) and not SCOPE_ANCHOR.search(question):
        gaps.add("scope")
    if re.search(r"高不高|好不好|多吗|正常吗|合理吗|表现", question) and not BASELINE_MARKERS.search(question):
        gaps.add("baseline")
    return gaps


def check_declared_gap(case) -> list[str]:
    """声明的 gap 必须落在 `missing_items` 里 —— 不许声明题面里明明有的东西。

    返回错误信息列表（空 = 通过）。这是 validate 与测试共用的唯一实现，
    避免两处各写一遍然后漂掉。
    """
    declared = list(getattr(case, "clarify_gap", []) or [])
    if not declared:
        return [f"{case.id}: clarify 题必须声明 clarify_gap"]
    bad = [g for g in declared if g not in GAP_KINDS]
    if bad:
        return [f"{case.id}: clarify_gap 含未知项 {bad}，可选 {list(GAP_KINDS)}"]
    actual = missing_items(case.question)
    over = [g for g in declared if g not in actual]
    if over:
        return [f"{case.id}: 声明缺 {over}，但题面 {case.question!r} 里其实有 —— "
                f"判据与题面不符（实测缺：{sorted(actual)}）"]
    return []


def superlative_without_metric(question: str) -> str | None:
    """题面是「<维度> 最 X」但没有指标 —— 返回命中的最高级词，无则 None。

    专用于对账：这种形态和 `neg_005`（哪个品类表现最好）同构，
    如果它被期望「直接算」，就与 clarify 判据冲突，必须显式登记。
    """
    m = SUPERLATIVE.search(question)
    if not m:
        return None
    head = question[: m.start()]
    if METRIC_MARKERS.search(head):
        return None
    return m.group(0)
