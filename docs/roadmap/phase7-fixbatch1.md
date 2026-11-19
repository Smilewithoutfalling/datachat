# 阶段 7 · 修复批 1（F1–F3）

来源：v7 收口和 11-18 本机两跑中定位到代码层的三处生成失败（BACKLOG N6、P14，以及 v7 报告里的 mem_003）。
这三处都是产品修复，不改题库、gold 和判分，所以不断代。
验收用 docs/eval/README.md 里的命令一（全量结果对比 v7）。

## F1 拒答原因照抄了提示词里的示例（mem_003）

**现象**：mem_003 是反向回归题。口径写的是「净销售额 = net_amount 列合计」，但表里没有 net_amount，正确做法是拒答，并且点名缺的是 net_amount（`app/eval/negative.py:99`）。
v7 里 state 和 full 两档的 6 跑都拒答了，但给出的原因都是「没有成本字段」，所以全部判错。

**根因**：codegen、reviewer、react 三处提示词里拒答的示例都写成了 `'无法回答：数据中没有成本字段'`（`codegen.py:26`、`reviewer.py:29`、`react_agent.py:261`）。planner 的 `REFUSAL_RULE` 里也有一句同样的示例（`planner.py:43`，例子是毛利率缺成本）。workflow 先过 planner，所以这里同样可能被照抄。
codegen 本身看不到口径块，只能看到计划，于是模型直接照抄了示例原文。
v7 报告里把它归为「植入盖不过先验」，这个说法不对：拒答本身是对的，错的只是原因。

**修法**：
1. 把三处示例改成占位写法：`'无法回答：数据中没有 <缺少的字段或信息>'`，并要求「原因写清楚具体缺哪个字段；计划里已经点名的，照计划写」。
2. planner 的 `PLANNER_REFUSAL_LINE`（口径引用了不存在的字段时）补一句：要写明是哪条口径的哪个字段不存在。

**验收**：mem_003 由错转对；neg_* 拒答题不能退步。

## F2 沙箱能力边界没告诉模型（N6）

**现象 a**：模型写了 `globals()`，沙箱的 `_SAFE_NAMES` 里故意没有它，于是报 NameError。reviewer 修了三次都没修掉，因为错误信息里没说这是沙箱的限制（agg_002）。

**修法 a**：worker 在格式化 NameError 时，如果出错的名字是 Python 内置名（`hasattr(builtins, name)`），就在错误后面补一行：
「沙箱不提供内置名 X；df、pd、np、plt 已就绪，直接使用，不要判断变量是否存在」。
codegen 和 reviewer 的约定里也各加一行同样意思的说明。

**现象 b**：模型只写了裸表达式，没有赋给 `result`。结果 executed=True，但 result=None，直接进了 summarizer（corr_006）。

**修法 b**：workflow 的 executor 在执行成功后检查三个条件：result 是 None，没有出图，代码的 AST 里没有给 `result` 赋值。三个都满足时，记为错误「代码没有把最终答案赋给 result」，交给 reviewer 修一次。模型自己写了 `result = None` 的不改判。
react 不受影响，因为 react 的探索步骤本来就允许没有 result。

**验收**：新增单测覆盖两种形态；agg_002 和 corr_006 用命令一隔离复跑。

## F3 codegen 输出的不是代码（P14）

**现象**：mul_013 的 code 字段里是一段中文计划，执行报 `SyntaxError: invalid character '，'`。reviewer 拿到的「出错代码」就是这段计划，三次都在复述它。

**修法**：
1. executor 判断是不是「非代码」：报 SyntaxError，并且错误是全角或中文字符造成的（`invalid character` 指向 U+3000–U+FFEF 或 CJK 字符），同时出错行不在引号或注释里。
   实现时把「出错行不在引号或注释里」落成了更稳的判据：去掉引号和行尾注释之后，至少两行、且至少一半非注释行含汉字。这样正常代码里混进一个全角逗号时不会误判，那种情况 reviewer 对着原代码改一个字符就行。
   命中时把错误改写成「上一次输出的是文字说明而不是 Python 代码」。
2. 命中时，reviewer 的提示里不再附上那段「出错的代码」，改成「（上次没有输出代码，请按计划重新写）」，免得它接着复述。
3. 计划本身过长（mul_013 的计划超过 5000 字）这次先不处理。state 里已经有 plan，以后要分析长度可以直接从 trace 算，不新增字段。

**验收**：新增单测（用 mul_013 那种形态的文本）；mul_013 用命令一复跑。

## 不做

- 不加 `globals` 等内置名到白名单（有逃逸风险）。
- 不自动把最后一个表达式当成 result：那是隐式行为，模型写错时会悄悄给出一个错的答案。
- 不改题库、gold、判分，v7 基线不动。

## 影响面和闸门

- 改了 codegen、reviewer、react 的提示词，单轮 prompt 哈希会变。要重新钉住，并写明是因为 F1 的示例改了。
- 闸门：pytest 分段全绿、vitest、e2e off/state/full 都要过；S 在内网机器上跑一遍命令一，不能比 v7 差，并逐题报出 mem_003、agg_002、corr_006、mul_013 的结果。
