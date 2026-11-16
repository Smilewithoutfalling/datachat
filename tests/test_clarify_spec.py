"""clarify 判据的可执行部分（EV-B7 补充）。

这里钉的不是「模型该不该反问」——那是产品决策。钉的是**判据本身站不站得住**：

1. 每道 clarify 题声明了缺什么（`clarify_gap`），且声明与题面字面对得上；
2. 没有一道「期望直接算」的题带着这个字段（否则等于两套标准混用）；
3. 没有一道「期望直接算」的题和 clarify 题在题面上同构 —— 同构就是判据自相矛盾，
   必须显式登记，不许假装看不见。

第 3 条现在会抓到 `ord_029`，登记在 `KNOWN_SHAPE_CONFLICTS`。那不是测试写错了，
是题集本身的冲突被写进了代码：`neg_005`（哪个品类表现最好）要反问，
`ord_029`（哪个品类卖得最好）要直接算，还给了 5 个备选答案。两句话差两个词。

处理这个冲突只有三条路，都要产品拍板：
  A. 把 neg_005 的题面改成真正无指标的（保住 clarify 判据，改题集）；
  B. 把 ord_029 改成 clarify（承认「卖得最好」也没口径，删掉 5 个 alt）；
  C. 放弃 clarify 这一维（6 道题按「给全口径就算对」重写）。
在拍板之前，`KNOWN_SHAPE_CONFLICTS` 就是这条冲突的账本 —— 它可以存在，
但不能悄悄存在。
"""
import re

from app.eval.cases import ALL_CASES
from app.core.ambiguity import answerable_by_terms, may_clarify
from app.eval.clarify_spec import (
    GAP_KINDS,
    check_declared_gap,
    missing_items,
    superlative_without_metric,
)

# 题面与 clarify 题同构、却被期望「直接算」的题。键 = 题号，值 = 冲突说明。
# 加进来的每一条都必须能回答「为什么它和 neg_005 不是同一件事」，否则就该改题而不是登记。
#
# 2026-11-13 清空：原来只有 ord_029（「哪个品类卖得最好」，带 5 个备选答案）。
# 它和 neg_005 是同一句话，改一边才能继续 —— 最后改的是 ord_029：转成 clarify。
# 理由是实测那 5 个口径选出 3 个不同品类（数码 / 服饰 / 食品），
# 「没有默认口径」这件事对两道题同时成立，不可能只对一边。
# 保留这张表是因为将来还可能撞上同样的形态：登记过就不许悄悄放过。
KNOWN_SHAPE_CONFLICTS: dict[str, str] = {}


def _by_id(cid: str):
    return next(c for c in ALL_CASES if c.id == cid)


def _evaluative(question: str) -> bool:
    """问法是评价式（要多/高/好/正常，或问「怎么样」），而不是求值式（是多少/哪些）。"""
    return bool(re.search(r"多吗|高不高|好不好|正常吗|合理吗|表现|怎么样|如何|情况", question))


def test_every_clarify_case_declares_valid_gap():
    """clarify 题都声明了缺口，且声明不是随口写的（题面字面要核得上）。"""
    clarify = [c for c in ALL_CASES if c.expect_kind == "clarify"]
    # 6 道 neg_* + ord_029（2026-11-13 从「带 5 个 alt 的歧义题」转来，见 KNOWN_SHAPE_CONFLICTS 的注释）
    assert len(clarify) == 7, f"clarify 题数变了：{len(clarify)}"
    problems = []
    for c in clarify:
        problems.extend(check_declared_gap(c))
    assert problems == [], "\n".join(problems)
    # 缺口要能解释「为什么算不出来」，两种成立方式：
    #   ① 缺 object / metric / operator 之一 —— 合理答案有无穷多个，一定不可算；
    #   ② 只缺 scope / baseline，但问法是评价式 —— 数能算出来，可这个数回答不了问题。
    #      「最近的订单多吗」算出 269 笔，用户还是不知道多不多：缺的是窗口和基准，
    #      不是指标（订单数）也不是算子（数一数）。这种也必须反问。
    # 反例：一道求值式的题（"是多少/哪些"）只声明缺 scope，那不构成 clarify ——
    # 它缺的只是筛选条件，挑一个常见范围算、结论里说明就够。
    for c in clarify:
        core = set(c.clarify_gap) & {"object", "metric", "operator"}
        assert core or _evaluative(c.question), (
            f"{c.id}: clarify_gap={c.clarify_gap} 既不含 object/metric/operator，"
            f"问法也不是评价式 —— 缺范围或缺基准不足以否定可计算性"
        )


def test_gap_kinds_are_closed_set():
    """gap 的取值是封闭集合，新增一类要先改 clarify_spec 的文档。"""
    used = {g for c in ALL_CASES for g in (getattr(c, "clarify_gap", []) or [])}
    assert used <= set(GAP_KINDS), f"出现了未定义的 gap：{sorted(used - set(GAP_KINDS))}"
    assert used == set(GAP_KINDS), (
        f"GAP_KINDS 里有从未用过的项：{sorted(set(GAP_KINDS) - used)} —— "
        f"要么补题，要么从文档里删掉，别留一个没人验证的分类"
    )


def test_answerable_cases_do_not_declare_gap():
    """非 clarify 题不许带 clarify_gap：否则同一道题既是「该反问」又是「该直接算」。"""
    bad = [c.id for c in ALL_CASES
           if c.expect_kind != "clarify" and (getattr(c, "clarify_gap", []) or [])]
    assert bad == [], f"这些题不是 clarify 却声明了缺口：{bad}"


def test_superlative_without_metric_is_registered():
    """「维度 + 最高级、没有指标」的题，除了 clarify 的，其余必须登记冲突。

    这一条就是判据的自洽性检查：如果一道题题面上「没说按什么指标选最好」，
    那它和 neg_005 是同一件事，判分口径就必须一致。
    """
    unregistered, stale = [], []
    hits = {}
    for c in ALL_CASES:
        word = superlative_without_metric(c.question)
        if not word:
            continue
        if c.expect_kind == "clarify":
            continue
        hits[c.id] = word
    for cid, word in hits.items():
        if cid not in KNOWN_SHAPE_CONFLICTS:
            unregistered.append(f"{cid}（命中「{word}」）：{next(c.question for c in ALL_CASES if c.id == cid)}")
    for cid in KNOWN_SHAPE_CONFLICTS:
        if cid not in hits:
            stale.append(f"{cid} 已不再是同构形态（题面或判据变了），请删掉这条登记")
    assert unregistered == [], (
        "这些题与 clarify 题同构却被期望直接算，判据自相矛盾：\n" + "\n".join(unregistered)
    )
    assert stale == [], "\n".join(stale)


def test_known_conflict_points_at_real_case():
    """登记项必须指向真实存在的题，且它至今仍是「直接算」的题。"""
    for cid in KNOWN_SHAPE_CONFLICTS:
        c = _by_id(cid)
        assert c.expect_kind != "clarify", f"{cid} 已经改成 clarify 了，删掉这条冲突登记"


def test_missing_items_is_a_validator_not_a_classifier():
    """词表只用来验证声明，不用来判定新题 —— 这里钉住它的能力边界。

    四道明确可算的题（点了指标 + 聚合方式）必须扫不出缺口；
    词表做不到的事（例如 ord_029 缺指标但含「哪个」）不在这里断言，
    因为把「扫得出/扫不出」当成分类器用，正是上一版方案翻车的地方。
    """
    for cid in ("ord_027", "ord_028", "ord_030", "emp_024", "emp_025", "inv_024", "inv_025"):
        c = _by_id(cid)
        assert "operator" not in missing_items(c.question), (
            f"{cid} 明确写了聚合方式，却被判缺 operator —— 词表太宽：{c.question}"
        )
        assert "metric" not in missing_items(c.question), (
            f"{cid} 明确点了指标，却被判缺 metric —— 词表太窄：{c.question}"
        )


# ---------------------------------------------------------------- planner 的代码放行
def test_answerable_by_terms_lets_clear_questions_through():
    """题面同时有指标和聚合方式 → 放行，不给模型反问的机会。

    这批是实测里真模型判错的（16 道明确可算的题有 5 道被反问，31%）：
    它把「含不含退款」「期初还是期末」这类口径分歧都当成"该问"，而这些题的正确
    行为是选主流口径算、分歧写进结论。
    """
    for q in ("总销售额是多少？", "平均库存是多少？", "产品A的月度销量变化情况",
              "各地区的产品销量分布是怎样的？", "哪个地区的总销售额最高？",
              "平均每单买几件？保留两位小数。", "产品A在华北地区的所有销售记录"):
        assert answerable_by_terms(q), f"应放行却被拦下：{q}"


def test_answerable_by_terms_does_not_gate_the_clarify_cases():
    """6 道 clarify 题一个都不能被放行 —— 放行等于绕过判据，它们又会去算。"""
    for c in ALL_CASES:
        if c.expect_kind != "clarify":
            continue
        assert not answerable_by_terms(c.question), (
            f"{c.id} 是 clarify 题，却被词表放行：{c.question} —— "
            f"词表把维度词或评价词当成指标了"
        )


# ---------------------------------------------------------------- 第二道闸门（2026-11-13 晚）
#
# 第一版 clarify 上线后跑 195 题全量，31 处反问里有 28 处落在多轮题上。
# 下面两段就是那份读数里的原题面，一个字没改 —— 它们是这条闸门的账本：
# 判据改松了，clarify 题会被算掉；改紧了，这些题又会被反问回去。

# 追问轮：本轮之前有轮次。这类半句天然缺指标，但上一轮定过口径，反问等于让用户复述。
_FOLLOWUP_ASKS = [
    "那 S02 呢？",
    "不对，我看错了，应该是西南地区。",
    "换成市场部，其他口径不变。",
    "把已退款的也加进来，重新算一遍。",
    "按职级拆开看呢？",
    "我说反了，是已取消的，重新算。",
    "刚才忘了说，离职的也要算进来，重新算。",
    "再按地区拆一层呢？",
    "只看华东地区呢？",
    "再看已完成的。",
    "其中 APP 渠道的。",
]

# 首轮祈使句：在设前提，用户下一句才说要看什么。这些是 followup=False 也要拦的。
_PREMISE_ASKS = [
    "只看 2024 年 3 月的订单，重复录入的只算一次。",
    "只看 2024 年 2 月的订单，重复录入的只算一次。",
    "只看数码类的已完成订单，重复录入的只算一次。",
    "只看已完成的订单，重复录入的只算一次。",
    "只看 APP 渠道的订单。",
    "只看已完成订单。",
]


def test_may_clarify_rejects_followups():
    """有上文就不许反问 —— 这一条单独成立，不依赖题面里有没有疑问词。"""
    for q in _FOLLOWUP_ASKS:
        assert not may_clarify(q, followup=True), f"追问被反问：{q}"


def test_may_clarify_rejects_premise_setting_imperatives():
    """没有疑问词的祈使句是在设前提，即使没有上文也不该反问。"""
    for q in _PREMISE_ASKS:
        assert not may_clarify(q, followup=False), f"设前提的祈使句被反问：{q}"


def test_may_clarify_still_allows_every_clarify_case():
    """闸门不能把该问的也拦掉：7 道 clarify 题必须都能反问。"""
    for c in ALL_CASES:
        if c.expect_kind != "clarify":
            continue
        assert may_clarify(c.question, followup=False), (
            f"{c.id} 是 clarify 题，却被闸门拦下，只能硬算：{c.question}"
        )


def test_first_turn_of_multi_turn_cases_is_never_refused():
    """多轮题的首轮要么能算（词表放行）、要么在设前提（闸门拦下），没有一道该在开场反问。

    这条比逐个列题面更狠：它是结构性断言 —— 只要有人往题集里加一道「开场就问不出口径」
    的多轮题，这里就红。理由是多轮的设计意图：第 1 轮建立范围，第 2 轮才要数。
    注意两条闸门是串联的，所以判据是「或」：`answerable_by_terms` 先放行能算的，
    剩下的 `may_clarify` 再拦设前提的，两者都不管才会真的反问回去。
    """
    bad = []
    for c in ALL_CASES:
        turns = getattr(c, "turns", None) or []
        if not turns:
            continue
        q = turns[0]
        if answerable_by_terms(q) or not may_clarify(q, followup=False):
            continue
        bad.append(f"{c.id}: {q}")
    assert bad == [], (
        "这些多轮题第 1 轮就会被反问，第 2 轮再问也没有上文可继承：\n" + "\n".join(bad)
    )


# ---------------------------------------------------------------- prev_clarify（2026-11-16）

def test_prev_clarify_lets_every_natural_answer_through():
    """出口判据：上一轮在反问时，用户任何形式的回答都不许再反问。

    这 7 种答法在 2026-11-16 之前（没有 prev_clarify 时）实测全部 may_clarify=True ——
    产品默认配置（workflow + off）下，每个 clarify 都是一次没有出口的往返。
    """
    for a in ("按销售额算", "按销售额", "按销售额最高的", "用销售额这个指标",
              "我想知道哪个产品卖得最多", "销售额", "就看销售额"):
        assert not may_clarify(a, followup=False, prev_clarify=True), f"出口失效，仍被反问：{a}"


def test_prev_clarify_overrides_word_table():
    """prev_clarify 优先级最高：答话里带评价式词（「高不高呢」）也不许再反问。

    死循环比一次口径猜测更伤。反问的代价是用户重复三轮后断定产品坏了。
    """
    assert may_clarify("销售额怎么样", followup=False, prev_clarify=False) is True   # 词表照常
    assert not may_clarify("销售额怎么样", followup=False, prev_clarify=True)        # 出口压过词表
    assert not may_clarify("能算出毛利吗", followup=False, prev_clarify=True)        # 与可行性询问一致
