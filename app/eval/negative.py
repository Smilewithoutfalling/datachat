"""负向题判定（EV-B7）：把「不该答」和「该问清楚」分开。

三种 kind 的差别不是措辞，是三种不同的产品行为：

  refusal     数据里没有 → 按契约拒答（「无法回答：<原因>」）
  clarify     题目本身没说清 → 反问，不该猜着算
  impossible  数据里缺一个具体对象 → 拒答，且原因必须点名缺什么

为什么必须分开：合成一个「拒答率」会把「猜着算」和「问清再算」算成同一个分数。
在「销售额怎么样」上直接给个数是越界（用户拿到一个不知道口径的数字，比拿不到更糟）；
在「毛利率」上说「数据里没有成本字段」是本分。一个数看不出这个区别。

判定顺序有讲究（规格陷阱条目）：**先判拒答，再判澄清**。反过来的话，
「无法回答：您是指哪个口径？」会被答案里的问号命中，判成「问清了」—— 它没有，
它只是把球踢回去还顺带拒答了。
"""
from __future__ import annotations

from app.core.result import is_refusal, refusal_from_answer

# 反问的标志词。问号之外这几个是实测里真模型最常用的说法：
# 「您是指哪个时间范围？」「哪种口径？」「请确认是要按订单数还是金额」。
# 不追求穷举 —— 漏判的代价是这题记错（可见、可复核），误判的代价是逼模型
# 在无关回答里塞问号。所以宁可窄一点。
_CLARIFY_SIGNS = ("是指", "哪种", "哪一个", "请确认", "请明确", "需要确认",
                  "确认一下", "您想", "请选", "请从上面")


def refusal_text(res) -> str | None:
    """这一轮的拒答文本（含原因）；不是拒答返回 None。

    优先看 result：真按契约走的是「执行代码把 result 赋成拒答串」（gold 就是这么写的）。
    没执行时才看 answer 首行 —— ReAct 直接拒答时 result 是空的，判定在结论里。

    「执行了但 result 不是拒答」直接判不拒答，不再去看 answer：否则模型可以一边算出
    一个数、一边在文末补一句「数据里可能没有该字段」，两处都要算对。
    """
    if is_refusal(res.result):
        return str(res.result).strip()
    if res.executed:
        return None
    return refusal_from_answer(res.answer)


def _asks_back(answer: str) -> bool:
    if not isinstance(answer, str) or not answer.strip():
        return False
    if "？" in answer or "?" in answer:
        return True
    return any(s in answer for s in _CLARIFY_SIGNS)


def _gave_answer(res) -> bool:
    """用户是否拿到了一个具体答案 —— 判据是 result 有没有被赋值。

    为什么不再看 `executed`（2026-11-13 实测改）：模型为了把口径问对，常常要先探一下
    字段 —— `df.shape`、`df['status'].value_counts()` 看有哪些状态、确认日期范围。
    这些探查是"为了问得准"，不是"猜着算"。旧判据把它们一律判成越界，等于逼模型在
    不知道表里有什么的情况下反问，问出"您想看哪个字段？"这种废话。

    真正的分界是**有没有交卷**：result 被赋值（哪怕是错的）= 它擅自选了口径算完了；
    result 为空 = 它只查了没答，答案还在用户手里。
    现场：neg_001 本轮探查了 shape/状态枚举/日期范围后 result 为空，回答里让用户在
    「有效销售额 / 实付金额合计」×「趋势 / 结构 / 总量」里挑 —— 这是标准澄清。

    残余盲区（明知而不拦）：探查后用 print 打了数、result 留空、answer 里既报数又问口径 ——
    会判成澄清，而用户其实看到了数。不额外拦是因为「answer 里那个数算不算答案」需要语义理解，
    判分器不能依赖模型；宁可漏判（可见、可复核）也不误杀 ——
    「探查 + 反问」是确定该过的形态，实测出现过。
    """
    v = res.result
    if v is None:
        return False
    if isinstance(v, str) and not v.strip():
        return False
    return True


def negative_verdict(res, case) -> dict:
    """负向题判定。返回 {"match": str|None, "why": str}。

    match 的值就是靠哪一层判对（与 score_detail 的返回值同构，报告里能直接并排看）；
    why 在判错时给出现场，供报告与人工复核 —— 只写「判错」等于让人回去翻原始输出。

    `expect_kind` 为空时等价于旧的 `expect_refusal` 语义（§EV-B7 步骤 5）：
    既不新增行为，也不改历史报告的判定。
    """
    kind = case.expect_kind or ("refusal" if case.expect_refusal else "")
    text = refusal_text(res)

    if kind == "refusal":
        if text:
            return {"match": "refusal", "why": ""}
        return {"match": None, "why": "没有按契约拒答（result 与 answer 首行都不是「无法回答：<原因>」）"}

    if kind == "impossible":
        if not text:
            return {"match": None, "why": "没有拒答；这题数据里确实缺东西，给出数值就是越界"}
        missing = [o for o in (case.missing_objects or []) if o in text]
        if missing:
            return {"match": "impossible", "why": ""}
        # 拒答了但没说清缺什么 —— 用户只知道"答不了"，不知道"缺哪张表/哪个字段"，
        # 也就无从补数据。这不算通过，但比直接给数值好。
        return {"match": None,
                "why": f"拒答原因没点名缺什么（要求提到 {list(case.missing_objects)}），实际：" + text[:80]}

    if kind == "clarify":
        if text:
            return {"match": None, "why": "直接拒答了；这题该反问问清口径，不是拒答"}
        if _gave_answer(res):
            return {"match": None, "why": "交给了 result —— 没问清口径就猜着算，用户拿到的是某个假设下的数"}
        if _asks_back(res.answer):
            return {"match": "clarify", "why": ""}
        return {"match": None, "why": "既没交答案也没反问（答案里没有问号，也没有「是指/哪种/请确认/您想」）"}

    return {"match": None, "why": f"未知 expect_kind={kind!r}"}
