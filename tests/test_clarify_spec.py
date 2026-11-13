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
from app.eval.clarify_spec import (
    GAP_KINDS,
    check_declared_gap,
    missing_items,
    superlative_without_metric,
)

# 题面与 clarify 题同构、却被期望「直接算」的题。键 = 题号，值 = 冲突说明。
# 加进来的每一条都必须能回答「为什么它和 neg_005 不是同一件事」，否则就该改题而不是登记。
KNOWN_SHAPE_CONFLICTS = {
    "ord_029": (
        "「哪个品类卖得最好」与 neg_005「哪个品类表现最好」同构：都是维度 + 最高级、"
        "都没说按什么指标。ord_029 的 5 个 alt 恰恰说明出题人自己也认为有 5 种合法口径 —— "
        "既然没有默认口径，正确行为就应该是反问。二者不能同时成立，待产品决策后改一边。"
    ),
}


def _by_id(cid: str):
    return next(c for c in ALL_CASES if c.id == cid)


def _evaluative(question: str) -> bool:
    """问法是评价式（要多/高/好/正常，或问「怎么样」），而不是求值式（是多少/哪些）。"""
    return bool(re.search(r"多吗|高不高|好不好|正常吗|合理吗|表现|怎么样|如何|情况", question))


def test_every_clarify_case_declares_valid_gap():
    """6 道 clarify 题都声明了缺口，且声明不是随口写的（题面字面要核得上）。"""
    clarify = [c for c in ALL_CASES if c.expect_kind == "clarify"]
    assert len(clarify) == 6, f"clarify 题数变了：{len(clarify)}"
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
