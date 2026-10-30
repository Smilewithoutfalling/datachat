"""Canary 十条：锁模型权重的固定探针（台账缺口 3）。

**它要回答的问题只有一个**：代码没动、题没动、模型名字也没动，读数却变了——那是模型
权重换了。指纹体系管不到这件事，`fingerprints.model` 记的只是名字（`Qwen3.5-397B-A17B`），
网关后面换成哪个快照，报告里一个字符都不会变。eval-v0 三次运行 `attempts` 从 22 涨到
37/38/37、prompt 逐字未变，只能归到模型侧，但拿不出证据。这个文件就是那份证据工具。

**为什么只用单轮题。** 多轮题一拍上记忆机制（`off` 回灌 messages / `state` 渲染成数据块），
翻转就分不清是权重变了还是记忆编排变了。探针必须只有一个变量。

**为什么排除 ambiguity 类。** 那类题靠 `alt_ground_truths` 容错，模型换个合理口径也算对。
判定边界本身在晃，翻转不指向权重。同理排除题面留白的（`mul_028` 的 status 口径）和判分器
刚改过尺子的（`ord_018` / `ord_022`）——canary 混进尺度变化，等于自己拆自己的台。

**第一版选题作废了，教训写在这里（2026-10-30）。** 初版按「台账里翻过转的 id」挑，10 条
里 5 条的 gold 返回 Series/tuple（`ord_003` / `corr_003` / `corr_001` / `ts_007` / `inv_016`）。
3 跑下来翻 3 题，逐条查原始输出，**没有一条是算错**：

- `inv_016`：数值逐项相同（1070 / 2258 / 2108 …），只是索引换了写法——run1 给周起始
  `02-26`、run2 给区间 `02-26~03-03`、gold 是周结束 `2024-03-03`。判分器认前两种、不认区间串。
- `ord_004`：三跑答案都是 832.54（正确），但 run2/run3 只写了 `print(...)`、没给 `result`
  赋值，判分取到空值。这测的是「记不记得守赋值契约」，不是「算得对不对」。
- `emp_022`：「离职的主要原因」本来就允许回答成司龄/部门离职率分布，run3 就那样答了。

所以现在的入选条件多了一条硬门槛：**gold 必须返回标量**（`int` / `float` / `str` / `bool`）。
Series 与 DataFrame 的比对躲不开索引写法、行列顺序、标签格式，那些抖动是判分器的事，
放进探针只会把噪声记成信号。

**选题不是凭感觉。** 候选池 = 台账 `## 翻转题` 里出现过的 id（历史上真翻过，是唯一有
实证的敏感度信号），按下面三条筛完，再用类别均衡补齐：

1. 题面与 gold 一一对应，没有「看你怎么理解」的余地；
2. gold 的结果唯一（不并列、不靠容错命中）；
3. 判定是唯一值，不是 DataFrame 的宽松比对。

淘汰记录见 `docs/eval/CANARY.md`，那里有每条的入选理由和被排除的候选。

**这个指纹和全局 `code_sha12` 是两回事。** 全局那个覆盖 `app/**/*.py`，改任何一行都会漂，
canary 要的是「只有题目变了才变」——所以单独对十条题面取哈希。判读规则：
`canary_sha12` 相同 + `code_sha12` 相同 + 读数变了 = 归到模型侧；`code_sha12` 不同就
只能重立基准，不能算漂移。
"""
import hashlib
import json

CANARY_IDS = (
    "ord_007",   # 聚合 / orders：下过 ≥3 笔的用户数，去重 + groupby.size + 计数
    "agg_013",   # 聚合 / sales：各地区销售额总额的中位数，两级聚合
    "ord_013",   # 过滤 / orders：折扣订单笔数，去重 + fillna + 状态不设限
    "ord_012",   # 过滤 / orders：6 月小程序完成单金额，三重条件 + round
    "ord_017",   # 关联 / orders：qty 与实付金额皮尔逊系数，round 4
    "emp_015",   # 关联 / employees：年龄与月薪皮尔逊系数，在职筛选 + round 4
    "ts_010",    # 时序 / sales：环比增长最快的月份，resample('ME') + pct_change
    "emp_020",   # 时序 / employees：2023 流失率，公式写在题面
    "ord_026",   # 拒答 / orders：问下单到签收天数，数据里没有物流时间
    "inv_022",   # 拒答 / inventory：问各门店店长，数据里没有人员信息
)

# 入选理由。**这里记的是为什么它不抖**，不是为什么它难——探针要的是稳定，
# 难而抖的题放进来说不清读数变化来自权重还是来自它自己。
CANARY_WHY = {
    "ord_007": "答案是一个计数，无并列、无表示法歧义；链条 去重→分组→阈值→求和",
    "agg_013": "中位数只由中间两个值决定，任一边缘值抖动不改变答案",
    "ord_013": "翻转史 89d28c86ca74；fillna(0)>0 与「不论订单状态」两句都得读进去",
    "ord_012": "三重条件（月份 + 渠道 + 状态）漏一个就错，答案仍是唯一金额",
    "ord_017": "相关系数 round 4，答案唯一；皮尔逊算错一步数值就明显偏",
    "emp_015": "在职筛选（leave_date 为空）是唯一易错点，其余是纯计算",
    "ts_010": "链条 9 个调用，全题集最长；答案是月份整数，判定无歧义",
    "emp_020": "流失率公式整条写在题面，模型没有自选口径的余地",
    "ord_026": "数据里既无签收时间也无物流单号，没法用别的字段凑近似",
    "inv_022": "数据里没有人员信息，连近似都无从下手；与 ord_026 配成一对",
}

# 判分相关字段全进指纹。漏一个，改它的时候指纹不动、却可能改判定——那正是
# `EVALSET_FILES` 漏 comparator.py 犯过的错。
_FP_FIELDS = (
    "id", "category", "dataset", "question", "ground_truth", "keywords",
    "ordered", "percent_equiv", "expect_refusal", "alt_ground_truths",
    "gold_dataset", "multi_table", "turns",
)


def canary_cases(cases=None) -> list:
    """按 `CANARY_IDS` 的顺序取出十条用例；缺任何一条直接抛错。

    不返回「找到几条算几条」：缺题时静默少跑，读数会变成另一批题的平均值，
    而报告上仍写着 canary，这比跑失败坏得多。
    """
    if cases is None:
        from app.eval.cases import ALL_CASES
        cases = ALL_CASES
    by_id = {c.id: c for c in cases}
    missing = [i for i in CANARY_IDS if i not in by_id]
    if missing:
        raise ValueError(f"canary 缺用例: {', '.join(missing)}")
    return [by_id[i] for i in CANARY_IDS]


def canary_fingerprint(cases=None) -> str:
    """十条题面 + 判分字段的 sha256 前 12 位。题没变就恒等，与 app 代码改动无关。"""
    picked = canary_cases(cases)
    payload = [
        {k: getattr(c, k) for k in _FP_FIELDS}
        for c in picked
    ]
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
