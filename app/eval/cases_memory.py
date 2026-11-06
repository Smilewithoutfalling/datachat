"""记忆专项题（批 4，R7/R4/R9 的消费端）。

三件套，对应记忆侧验收需求（DEVLOG [128]/[129] §14.4）：
- 口径题（M2）：有口径算对、口径引用缺失字段时仍拒答（反向回归）
- 改写题（M7）：省略指代的追问，改写 + state 组合下能答对
- 长历史题（M4）：轮次堆到触发遮罩，末轮仍能回头引用第 1 轮的数

**这些题全部带 requires_memory，默认（off）跑批自动跳过**——off 档口径不进 prompt、
改写被 service 短路，判分必错。要跑它们：`run_eval.py --memory state|full`。

判分口径写死在 gold 里（口径语义不是字面语义），所以这些题在 off 档没有"照常"对照——
"没口径照常"的对照由现有 agg/filt 类题承担，两类题的 question 措辞刻意不同，
不构成同一道题的两种答案。
"""
import os as _os

from app.eval.case_model import EvalCase

_NONE = "result = None"


def _note(kind: str, name: str, body: str, unit: str = "", synonyms="") -> dict:
    """构造一条口径（格式见 R7：[{kind, name, body, unit, synonyms, sha?}]，缺 sha 现算）。"""
    return {"kind": kind, "name": name, "body": body, "unit": unit, "synonyms": synonyms}


MEMORY_CASES = [
    # ---- 口径题（M2）：口径改变"销售额"的语义，gold 按口径语义写死 ----
    EvalCase(id="mem_001", category="memory", dataset="sales", gold_kind="scalar",
             requires_memory="state",
             dataset_notes=[_note("metric", "实收销售额",
                                  "实收销售额 = units × price × 1.05（含 5% 渠道服务费，按实收入账）",
                                  unit="元", synonyms="实收金额")],
             question="全表的实收销售额合计是多少元？",
             # 字面语义是 274673（units×price 合计），口径语义是 288407 —— 两者不同，
             # 模型若没拿到口径、按字面算，判分立刻错；拿到口径并按 1.05 倍算才算对。
             ground_truth="result = int((df['units'] * df['price'] * 1.05).sum())",
             keywords=["units", "price", "sum"]),

    EvalCase(id="mem_002", category="memory", dataset="sales", gold_kind="series",
             requires_memory="state",
             dataset_notes=[_note("rule", "停产剔除",
                                  "统计任何销量、销售额时必须剔除 product 为 'C' 的记录"
                                  "（C 系列已停产，历史数据未清理）")],
             question="各产品的总销量分别是多少件？",
             # 不剔除的话 C 也在 series 里且值更大 —— 判分是整表比对，多一行、少剔除都错。
             ground_truth="result = df[df['product'] != 'C'].groupby('product')['units'].sum()",
             keywords=["groupby", "units"]),

    # ---- 反向回归（记忆侧补的闸门，真模型读数要确认）：口径引用缺失字段仍拒答 ----
    EvalCase(id="mem_003", category="memory", dataset="sales", gold_kind="text",
             requires_memory="state", expect_kind="impossible", expect_refusal=True,
             missing_objects=["net_amount"],
             dataset_notes=[_note("metric", "净销售额",
                                  "净销售额 = net_amount 列合计（实收减退款）", unit="元")],
             question="全表的净销售额是多少元？",
             # 口径 body 引用了表里不存在的列。注入块末尾记忆侧已加"口径里用到的字段必须在
             # 表结构里真实存在，否则照旧拒答"——这题就是钉这句的：模型拿了口径，仍不许
             # 把 units×price 当 net_amount 交上来。missing_objects 与 gold 各说各话会被
             # validate 挡掉（规则 7）。
             ground_truth="result = '无法回答：数据中没有 net_amount 字段，无法计算净销售额'",
             keywords=[]),

    # ---- 改写题（M7）：省略指代的追问。off 档改写不生效，所以 requires_memory="state" ----
    # 判分只看末轮结果对不对，不区分"改写兜底"还是"state 块继承"——产品语义是
    # "组合起来用户拿到正确答案"，拆开归因是消融的事，不是判分的事。
    EvalCase(id="mem_004", category="memory", dataset="sales", gold_kind="scalar",
             requires_memory="state", rewrite=True,
             turns=["华东地区 2024 年 4 月的销售额是多少？",
                    "那 5 月呢？"],
             expect_turns=["exec", "exec"],
             question="那 5 月呢？",
             # 「那 5 月呢」脱离历史可以读成"全表 5 月"（50998），与正确答案"华东 5 月"
             # （15091）不同 —— 没有任何一条路能靠巧合答对。
             ground_truth="m = (pd.to_datetime(df['date']).dt.year == 2024) & (pd.to_datetime(df['date']).dt.month == 5) & (df['region'] == '华东')\nresult = int((df.loc[m, 'units'] * df.loc[m, 'price']).sum())",
             no_history_truth="m = pd.to_datetime(df['date']).dt.month == 5\nresult = int((df.loc[m, 'units'] * df.loc[m, 'price']).sum())",
             keywords=["groupby", "sum"]),

    EvalCase(id="mem_005", category="memory", dataset="sales", gold_kind="scalar",
             requires_memory="state", rewrite=True,
             turns=["华东地区 2024 年 3 月 A 产品卖了多少件？",
                    "那 C 产品呢？"],
             expect_turns=["exec", "exec"],
             question="那 C 产品呢？",
             # 华东 3 月 A=180、C=55，两个值都真实存在（避免"答 0"的边界）；
             # 脱离历史的直白读法"全表 3 月 C 的件数"是另一个值，写进 no_history 对照。
             ground_truth="m = (pd.to_datetime(df['date']).dt.month == 3) & (df['region'] == '华东') & (df['product'] == 'C')\nresult = int(df.loc[m, 'units'].sum())",
             no_history_truth="m = (pd.to_datetime(df['date']).dt.month == 3) & (df['product'] == 'C')\nresult = int(df.loc[m, 'units'].sum())",
             keywords=["groupby", "sum"]),

    # ---- 长历史题（M4）：轮次堆长，末轮回头引用第 1 轮。只在 full 档触发遮罩 ----
    # 注意：遮罩只在完整历史超本轮上限时发生。本题 8 轮刻意让每轮 result_text 较长，
    # 但不保证必超——没超时它退化成普通的"回头引用"题，recall_turn 照样抓数字复述错，
    # 不算白跑；是否真的触发了遮罩看报告 memory_trimmed 里有没有 history。
    EvalCase(id="mem_006", category="memory", dataset="sales", gold_kind="frame",
             requires_memory="full", recall_turn=1,
             turns=["2024 年 1 月各地区的销量明细（每个地区一行，含件数与销售额）",
                    "2024 年 2 月华东和华北各自的销售额是多少？",
                    "2024 年 3 月全表的销售额合计是多少元？",
                    "B 产品 1 月到 6 月每个月的销量序列",
                    "2024 年 4 月和 5 月各产品的销售额对比表",
                    "西南和华中两个地区谁的销售额更高？高多少？",
                    "2024 年 6 月华南的销量是多少件？",
                    "回到最开始的那个问题——2024 年 1 月各地区的销量明细，把那张表再报一遍"],
             expect_turns=["exec"] * 8,
             question="回到最开始的那个问题——2024 年 1 月各地区的销量明细，把那张表再报一遍",
             # gold 独立重算 1 月明细；answer 里的数字必须能在第 1 轮 result_text 里找到
             # （recall_turn=1）——复述错旧明细、末轮逻辑照对，只有这条路抓得住。
             ground_truth=("m = pd.to_datetime(df['date']).dt.month == 1\n"
                           "g = df.loc[m].groupby('region').apply(\n"
                           "    lambda x: int((x['units'] * x['price']).sum()))\n"
                           "result = g"),
             no_history_truth="",
             # 豁免：「那张表」指第 1 轮的计算结果，脱离历史没有指代对象；且本题考的是
             # 隔 7 轮之后还能不能复述，单轮重算测不出复述能力
             keywords=["groupby"]),
]
