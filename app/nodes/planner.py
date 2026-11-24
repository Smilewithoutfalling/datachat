"""规划节点，兼「口径不明时反问」的判断点（EV-B7，2026-11-13）。

## 为什么澄清放在 planner

workflow 是固定线性图：planner → codegen → executor → summarizer。codegen 的契约只有
「算出数」或「数据里没有，拒答」，它拿到一句「您想按哪个口径看？」只会当成代码去执行、
报 SyntaxError。所以「要不要先问」必须在写代码之前定，也就是 planner。

planner 的输出被解析成两条路：

- 第一行是 `CLARIFY: <反问>` → 图短路到 summarizer，codegen / executor 不跑，
  `executed=False`、`result=None`，用户拿到的是那句反问；
- 其他任何内容 → 照旧当分析步骤，走完整条链路。

## 判断标准与它的边界

只有同时满足「缺指标」和「缺聚合方式」才反问（见 `_PROMPT` 末段）。这条线是从评测量表
反推的：14 道歧义题里 13 道能靠它分开，剩下 1 道是量表自己的冲突 —— neg_005 与 ord_029
题面同构却期望相反，登记在 `tests/test_clarify_spec.py::KNOWN_SHAPE_CONFLICTS`。

**保守优先。** 误判成反问的代价是多一次往返，用户立刻能纠正；漏判的代价是给了一个口径
不明的数，用户可能拿着它去汇报。所以规则写成「两个条件同时满足」，并给了三个明确
不该反问的反例 —— 反例比定义更能约束模型。

## 和「数据不足以回答」的区别

那是数据里没有（拒答，走完整链路让 codegen 写 `result = '无法回答：…'`），
这是数据里有但没说清怎么算（反问，短路）。两者混起来，模型会把所有模糊问题都拒答掉，
用户看到「无法回答」会以为查不了，实际只是没定口径。
"""
import re

from app.core.ambiguity import answerable_by_terms, may_clarify
from app.core.llm import node_llm
from app.memory.metrics import PLANNER_REFUSAL_LINE

# 「答不了」的第一类：数据里没有。单独提出来是因为 tests/test_metrics.py 要断言这条规则
# 还在 —— 它原来是把这句话原样抄在测试里，prompt 一改写测试就红，红的原因不是功能坏了，
# 是字符串搬了家。常量只有一份，测试引它，就不会再出现这种假红灯。
REFUSAL_RULE = """A. **数据里没有**这个字段或信息 → 只写「数据不足以回答：缺少什么」，到这里就结束。
   判断依据是表结构里真没有，而不是"问题没说清"。表里有、只是没说怎么算，不属于 A。
   **不要追问，也不要给替代口径**（"不过您可以按销量看"这种也不行）—— 用户会以为换个说法
   就能算出来，实际是把编出来的数当真。例：表里没有成本字段，"哪个品类毛利率最高"
   只有一个正确输出：`数据不足以回答：没有成本字段`。这只是示例，要写的是**本题真正缺的那个字段名**
   （数据口径里引用了表里不存在的列时，就写那个列名），不要照抄「成本」。"""

_PROMPT = """你是数据分析规划助手。下面是数据表的结构：
{schema}

相关字段说明（来自数据字典）：
{field_notes}

用户问题：{question}

请用 3-5 个步骤说明如何用 pandas 分析得到答案。只描述思路，不要写代码。

「答不了」有两种，处理方式不同，别混：

""" + REFUSAL_RULE + """

B. **口径没定**：表里有数据，但问题没说清怎么算 → 第一行只写
   `CLARIFY: <一句反问，列出 2-3 个可选口径让用户挑>`，后面不要再写任何步骤。
   满足任一条就是 B：
     ① 没点明聚合方式 —— 句子里没有「总 / 合计 / 平均 / 最大 / 最小 / 数量 / 多少 / 占比 /
        排名 / 分布 / 趋势」这类词，只问「表现」「情况」「怎么样」「高不高」「多不多」；
     ② 连分析对象都没指认 —— 例如"帮我看看这批数据"，没说看哪张表、哪个方面。
   走 B 时**不要**写「无法回答」「无法直接回答」「数据不足以回答」—— 数据是有的，
   写成"无法回答"用户会以为查不了，实际只是没定口径。

不该走 B 的例子（照常写步骤）：
  - "总销售额是多少"：有「总」；含不含退款只是金额口径分歧，选主流算，结论里说明；
  - "平均每单几件"：有「平均」；
  - "复购率是多少"：复购率是已定义的比率，算它本身就是算法，不要再问怎么聚合。
反问要具体：说清缺的是哪一项，并给出候选（例如"您想按销售额还是订单数看？按总额还是分城市？"）。"""

# 标记可能被模型加上 markdown 装饰（`**CLARIFY**:`、`- CLARIFY：`、代码块），前后都认。
# 冒号全角半角都认：中文输出里全角更常见，只认半角会漏掉一半。
#
# **必须逐行找，不能只认开头。** 原来用 `^` + re.S 只匹配整串第 0 位，实测模型经常先写一段
# 「这题只给了筛选条件、没指明指标」的解释，再另起一行 `CLARIFY: …`。那种输出会整段被当成
# 分析计划送进 codegen，codegen 读到「口径未定」就写 `result = '无法回答：…'` —— 用户看到一句
# 没有候选、没有数字的拒答，程序还记成 executed=True（实测 mul_021 首轮）。加 re.M 让 ^ 匹配
# 每个行首，标记在哪一行都能认出来。
# 反问标记：行首（允许列表/引用/markdown 强调前缀）+ CLARIFY + 冒号。
# **前缀类不含反引号**（2026-11-16）：`CLARIFY: …` 这种反引号包裹是「引用格式示例」的
# 形态 —— prompt 自己的说明里就有（输出格式一节），模型复述格式时也会带。re.M 逐行匹配
# 后（C-011 为修 mul_021），反引号在前缀类里会把这类引用整段误判成反问：实测 Echo 桩
# 返回 prompt 原文时，第 19 行 `` `CLARIFY: <一句反问…>` `` 命中，标记之后的大半段
# prompt（含 FOLLOWUP_HINT）被切走当「反问内容」。误判的代价（整段计划被当反问展示、
# 分析全丢）远大于漏判（走完整链路），所以宁可收紧。
_CLARIFY_RE = re.compile(r"^[ \t]*[*_#>\-]*[ \t]*CLARIFY[ \t]*[*_]*[ \t]*[:：][ \t]*", re.I | re.M)

# 闸门拦下反问后交给 codegen 的兜底计划。**不能留空**：空计划配一个只有筛选条件的问题，
# codegen 会自由发挥（实测它把「口径未定」翻成一句拒答，而不是算一个数）。这段话把它按住：
# 按题面条件算，指标没点明就取最主流的那个，并在结论里说明选了哪个口径。
VETO_PLAN = ("按题面给出的条件筛选（含去重等约束）后直接计算。若问法没有点明指标，"
             "取最能回答它的单一指标（优先数量，其次金额）算出结果，"
             "并在结论里用一句话说明所选口径。")

# 两条「别问，直接算」的追加指令。提成常量有两个用处：一是测试能断言它到底进没进 prompt
# （而不是抄一份字符串在测试里，prompt 改一个字就假红灯）；二是这两句的分工要写在一处 ——
# 前者靠题面字面（代码判「能算」），后者靠会话状态（有上文说明口径定过了）。
ANSWERABLE_HINT = "\n本题的指标和聚合方式已经写清楚，直接写分析步骤，不要输出 CLARIFY。"
FOLLOWUP_HINT = "\n这是同一会话里的追问，上一轮已经定过口径：按上文继续写步骤，不要输出 CLARIFY。"


def split_clarify(text: str) -> tuple[str, str]:
    """把 planner 的输出拆成 (clarify, plan)。

    clarify 非空 = 这是一句反问，图要短路；此时 plan 取标记**之前**的文字（通常是模型
    在反问前写的解释），标记本身不进 plan —— `CLARIFY:` 是给图的协议，不该出现在
    「分析计划」里让用户看到。

    标记在但内容为空时不算反问：那种半截输出当分析步骤处理，走完整链路，由 codegen
    自己决定算还是拒答。宁可多算一次，也不要拿一句空话去答用户。
    """
    text = text or ""
    m = _CLARIFY_RE.search(text)
    if not m:
        return "", text
    body = text[m.end():].strip()
    if not body:
        return "", text
    return body, text[:m.start()].strip()


def _prompt(state) -> str:
    """planner 的 prompt（plan 与 replan 共用：replan 在它末尾再追加「上一次的尝试」）。"""
    msg = _PROMPT.format(
        schema=state["schema"],
        field_notes=state.get("field_notes") or "（无）",
        question=state["question"],
    )
    # 阶段 6.6 M1：工作状态块；批 4b M2：口径块（在状态块之前，优先级 表结构 > 口径 > 字段说明）；
    # P0：最近两轮的对话快照（问的原话 + 答案摘要 + 结果形态；折叠后的状态块没有指代，快照有）。
    # 三者都已带数据标记，插在表结构之后；都没有时 prompt 不变（P8 / state 哈希）。
    # 快照放最后：它是参考材料，不是本轮要遵守的口径 —— 口径块的优先级必须仍在它前面。
    blocks = [b for b in (state.get("metrics_block"), state.get("memory_state"),
                          state.get("memory_history")) if b]
    if blocks:
        joined = "\n\n".join(blocks)
        msg = msg.replace("\n\n相关字段说明（来自数据字典）：", f"\n\n{joined}\n\n相关字段说明（来自数据字典）：", 1)
    if state.get("metrics_block"):   # 拒答补句：只在有口径块时出现
        msg += "\n" + PLANNER_REFUSAL_LINE
    # 代码先放行一批：题面同时点了指标和聚合方式（「总销售额是多少」「平均库存」），
    # 就不给模型反问的机会。实测模型在这类题上 31% 会问回去（见 app/core/ambiguity.py）。
    if answerable_by_terms(state["question"]):
        msg += ANSWERABLE_HINT
    # 会话中的追问本轮往往很短（「那 S02 呢」），单看这半句确实没指标 —— 但上一轮定过。
    # 没有这一句，多轮题会被反问，而那正是记忆该起作用的地方。
    # 有原文也算有上文：P0 之后 planner 能看到最近几轮的对话，判「这是追问」不再依赖折叠状态。
    elif state.get("memory_state") or state.get("memory_history"):
        msg += FOLLOWUP_HINT
    return msg


def _parse(text: str, allow_clarify: bool) -> tuple[str, str]:
    clarify, plan_text = split_clarify(text)
    # 第二道闸门（2026-11-13 晚）：模型判「该问」不等于真该问。两类场景它看不出来 ——
    # 追问（前半句被上一轮省掉了）和设前提的祈使句 —— 由代码拦在路由之前。
    # 拦下时换成 VETO_PLAN 而不是把标记前的解释塞回去：反问是给图的协议，
    # 那段解释是在讲「为什么问不出口径」，两者都不能当分析步骤。
    if clarify and not allow_clarify:
        clarify = ""
        # 丢掉反问之后必须给 codegen 一条能执行的计划。用 VETO_PLAN 而不是把标记前的
        # 解释塞回去：那段话在讲「为什么问不出口径」，拿它当计划等于让 codegen 重走一遍
        # 「口径未定 → 拒答」的老路。
        plan_text = VETO_PLAN
    return clarify, plan_text


def plan(state, config=None):
    llm = node_llm(config)
    text = llm.invoke(_prompt(state))
    clarify, plan_text = _parse(text, may_clarify(state["question"], bool(state.get("followup")),
                                                 bool(state.get("prev_clarify"))))
    return {"plan": plan_text, "clarify": clarify}


# ------------------------------------------------------------------ 第 3 步 S3-3：replan
# docs/roadmap/phase75-step3.md §4。每轮最多一次（由 app/graph.py 的路由保证），带着失败原因回到 planner：
# 同一份 planner prompt，末尾追加「上一次的尝试」。拒答规则（A 类）照常生效，所以 replan 也可以得出「数据不足以回答」；
# **不允许反问**（may_clarify 强制为 False）：第一轮已经决定不问了，失败之后再问只会让用户觉得是在推卸。
REPLAN_MARK = "上一次的尝试"
REPLAN_CODE_CHARS = 1500       # 「最后一次的代码」截断上限（字符）
REPLAN_REASON_CHARS = 800      # 失败原因（报错取末尾）截断上限
REPLAN_TEMPLATE = """

## """ + REPLAN_MARK + """（没有算出来，仅供参考）
上一版计划：
{plan}

最后一次的代码：
{code}

失败原因：{reason}

请换一条思路重新写分析步骤：问题本身和口径保持不变（指标、筛选条件、分母都不能换），只换算法或实现的路子；
不要照抄上一版计划。数据确实回答不了时，按上面 A 类规则写「数据不足以回答：缺少什么」。不要输出 CLARIFY。"""


def _clip_head(text: str, n: int) -> str:
    text = text or ""
    return text if len(text) <= n else text[:n] + f"\n…（已截断，共 {len(text)} 字）"


def _clip_tail(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else "…" + text[-n:]


def replan_reason(state) -> str:
    """失败原因，按优先级：口径闸拒收（改了哪些列和过滤条件）> 执行报错 > 结果可疑。"""
    from app.tools.sanity import sanity_message
    if state.get("scope_rejected"):
        return "修复改了口径，已拒收（" + state["scope_rejected"] + "）"
    if state.get("error"):
        return "执行报错：" + _clip_tail(state["error"], REPLAN_REASON_CHARS)
    if state.get("sanity_issue"):
        return sanity_message(state["sanity_issue"])
    return "（未知）"


def replan(state, config=None):
    """S3-3 的 REPLAN 节点：再调一次 planner，然后由图走 codegen → executor，reviewer 预算重置为 1 次
    （max_attempts = 当前 attempts + 1；attempts 不清零，修复率统计还用它）。"""
    llm = node_llm(config)
    reason = replan_reason(state)
    msg = _prompt(state) + REPLAN_TEMPLATE.format(
        plan=state.get("plan") or "（无）",
        code=_clip_head(state.get("code") or "（无）", REPLAN_CODE_CHARS),
        reason=reason,
    )
    text = llm.invoke(msg)
    clarify, plan_text = _parse(text, allow_clarify=False)
    return {"plan": plan_text, "clarify": clarify, "replanned": True, "replan_reason": reason,
            "max_attempts": state.get("attempts", 0) + 1}
