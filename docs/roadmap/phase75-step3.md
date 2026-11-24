# 阶段 7.5 第 3 步：修复回路（方案）

> 状态：已定（S 于 2026-11-24 13:46 裁定 §7 五条：前三条按推荐执行，另补两条内容）。
> 依据：phase75-assess.md 中第 3 步那一行（:41）、§4 中 reviewer 一行（:88）、§6 的 N9 和 v8 基线（:105–106）；评测侧 7.5b 方案的 §2 第 2 条和 §4 三条验收边界（该文件不在仓库里，下面 §0 摘了原文）。
> 范围：workflow 链路（默认模式，`app/server/app.py:124`、`DatasetView.tsx:26`）。react 链路不在本步，见 §6。

## 0. 必须遵守的边界（评测侧 7.5b §4，原文照录）

1. **熔断的目的地是 replan**（预算内）。降级话术只在 replan 用尽之后才出现。
2. **codegen 列缺失、executor 异常不设为拦截点**。这两类是自愈回路的输入（7.5b §2 第 2 条）。
3. **grounding 从标黄改为拦截之前，先量假阳率**（`report_adapter` 的 unverified 计数可直接用）。只拦带单位的计数和金额，派生数继续只提示。

## 1. 结论先行

第 3 步分四件，前三件一个实现 PR，第四件只出读数：

| 件 | 内容 | 组别 | 要不要内网回归 |
|---|---|---|---|
| S3-1 能力注入 | codegen 和 reviewer 两处 prompt 里关于沙箱的那两行，改由 `CAPS` 渲染，不再手写 | A（`app/nodes/`、`app/tools/`） | 要，全局 prompt |
| S3-2 口径闸 | reviewer 出的代码先比口径，改了口径就拒收这次修复 | A（`app/graph.py`，口径判定挪进 `app/tools/`） | 要 |
| S3-3 REPLAN 边 | 每轮最多一次：带着失败原因回到 planner，再走 codegen 和 executor | A（`app/graph.py`、`app/state.py`、`app/nodes/planner.py`） | 要 |
| S3-4 grounding 假阳率 | 只量不改：给出「带单位的计数和金额」这一类的假阳率表，拦不拦由 S 看数再定 | B（脚本） | 不要 |

三件 A 组改动放在一个 PR 里，内网只回归一次。按 11-21 的规则，可以叠链只跑链尾。

## 2. S3-1 能力注入

**现状**：两处 prompt 都是手写的，而且和 `CAPS` 对不上。
- `app/nodes/codegen.py:129-130`：「pd、np、plt、chart 已就绪，无需 import；**不要导入其他库**」，以及「没有 globals / locals / eval / exec / open 等内置函数」。
- `app/nodes/reviewer.py:184-185`：同样的内容，措辞略有不同。
- `app/tools/sandbox_caps.py:261-266` 实际允许 import 的包有 `math`、`statistics`、`datetime`、`calendar`、`re`、`collections`、`itertools`、`functools`、`decimal`、`json` 等，但 prompt 告诉模型不许导入。`sandbox_caps.py:223` 的 docstring 写明了「本步不注入 prompt（那是第 3 步）」。

**做法**：
- 在 `sandbox_caps.py` 加一个纯函数 `prompt_lines(multi: bool) -> str`，渲染三句话，全部从 `CAPS` 取：
  1. 已就绪的变量：`common_vars`，加上 `single_data_vars` 或 `multi_data_vars`；
  2. 可以 import 的包：`allowed_imports` 里去掉 `_` 开头的私有名（如 `_strptime`）和 `time`、`locale`、`warnings` 这类只给运行时用的包，其余列出；「只能用这些」；
  3. 不给的内建：从 `forbidden_builtins` 里取一份**固定的示例子集**（globals、locals、eval、exec、open、getattr、`__import__`），后面加「等」。不全量列出，因为全量有 100 多个名字，而且按解释器版本现算，会让 prompt 跟着 Python 版本变。
- 「对 prompt 可见」的包放进 `CAPS` 的新字段 `prompt_imports`，由测试钉住它是 `allowed_imports` 的子集。这样仍然只有一处来源。
- 结果变量那一句（「把最终答案赋值给 result」）保持原样，只是变量名改从 `CAPS.result_var` 取。

**行为变化**：模型会被告知可以 `import math` 等包（原来写的是「不要导入其他库」）。这不是新引入的 bug：#107 立评估时，`sandbox_caps` 和 prompt 就一直没对齐。回归读数如有变化，先归因到这一条：模型开始 import，executor 的行为分布可能随之变动。这属于全局 prompt 改动，按 phase75 §3 必须跑全量 202 题。scipy 不在 `CAPS` 里，所以不会出现在 prompt 里，B3（scipy 能力说明）仍按 phase75-scipy.md 等 S 定。

**验收**：渲染结果里的每个包名、变量名都能在 `CAPS` 里找到（测试反查）；两处 prompt 不再出现手写的包名清单（测试按字面断言旧句子已不存在）；codegen prompt 在上游固定时逐字节一致（沿用第 1 步的回放测试，期望哈希按新 prompt 重立，理由写进 DEVLOG）。

## 3. S3-2 口径闸

**现状**：口径比较已经写好了，但只用于观测：`app/assess/contracts.py:285` `reviewer_scope`（列集合与过滤条件集合，豁免 k 个拼错的列），抽取逻辑在 `app/assess/code_refs.py`（325 行，AST）。产品链路不调用它。

**做法**：
- 把 `code_refs.py` 和 `scope_of` 的判定挪到 `app/tools/code_scope.py`（A 组）。`app/assess/code_refs.py` 和 `contracts.reviewer_scope` 改为从那里 import，判定逻辑只保留一份。评估这边只是 import 路径变了，verdict 的形状不变，B1 的 `after_fix.*` 不受影响。**这一处动的是评测侧写的文件，提交前把改动面发给评测侧过目。**
- `review_and_fix` 出代码之后，在 graph 里加一个确定性的判定（不调用模型）：口径变了，就丢弃这次修复（`code` 回退成修复前的代码），在 state 里记下 `scope_rejected` 和原因，路由到 replan（§4）。
- 判定规则沿用 `reviewer_scope`，只加一条**字面量豁免**（为 N9 准备，见 §7 第 2 条）：修复前结果为空（`sanity_issue` 是空表）时，同一列、同一运算符的过滤条件只换了比较值，不算换口径。这条和「k 个拼错的列」是同一类：都是把写错的东西改对，不是换问题。
- 解析不了（`scope_of` 返回 None）：修复前的代码解析不了时，不拦（与 `reviewer_scope` 的 NOT_CHECKED 一致）；修复后的代码解析不了时，交给 executor，让它的报错进入下一轮修复。这一条遵守边界 2，不把异常变成拦截点。

**验收**（phase75 第 3 步验收 ①）：
- 单元测试：reviewer 增加或删除一个真实列、改掉过滤条件、换掉分母，都被拒收；把拼错的列名改对、在空结果下替换字面量，都放行；
- graph 测试（fake_llm 新场景）：reviewer 改口径之后，下一个节点是 replan，而不是 executor；
- **搬家 golden 测试**（S 补充）：构造十几份代码快照，覆盖列增删、过滤条件变化、拼错列名、多表、解析失败等情况。旧路径（搬家前的 `app/assess/code_refs.py` 输出，冻结成 golden 文件）和新路径（`app/tools/code_scope.py`）对同一输入的输出 diff 必须为空；`reviewer_scope` 的 verdict 也逐字节对比。
- 评测侧搬家后必跑：`tests/test_assess_contracts.py`、`tests/test_b2_batch_pipeline.py`、`tests/test_nightly_gate.py`。改动面发给评测侧，由他们直接跑。S3-1 新增的 `prompt_imports` 字段同时会触动 `tests/test_assess_caps.py` 的 worker 一致性测试，以及 P8 哈希重立。

## 4. S3-3 REPLAN 边

**触发**（三选一，都要求本轮还没 replan 过，且 tracker 没有超预算）：
1. 口径闸拒收（§3）；
2. reviewer 次数用尽，仍然报错（现在 `graph.py:30` 走 done，去 summarizer 写失败说明）；
3. reviewer 次数用尽，结果仍然可疑（A2 的 `sanity_issue`）。

**不触发**：codegen 列缺失、executor 第一次报错。这些照旧进 reviewer（边界 2）。

**replan 做什么**：
- 再调一次 planner，prompt 末尾追加一段「上一次的尝试」：上一版计划、最后一次的代码（截断）、失败原因（报错、可疑点，或口径闸给出的「改了哪些列和过滤条件」），并要求「换一条思路，口径与问题保持一致」。planner 原有的拒答规则（A 类）照常生效，所以 replan 也可以得出「数据不足以回答」。replan 时**不允许反问**（`may_clarify` 强制为 False）：第一轮已经决定不问了，失败之后再问，只会让用户觉得是在推卸。
- 然后走 codegen → executor，reviewer 的预算重置为 **1 次**。最坏情况下，模型调用次数从现在的 1+1+3+1=6 次，变为 6+1+1+1=9 次。具体数字待 S 定，见 §7 第 3 条。
- state 新增字段：`replanned: bool`、`replan_reason: str`、`scope_rejected: str`。`attempts` 照旧计数，不清零（修复率统计还用它）。

**用尽之后**（边界 1 的「降级话术」）：仍然去 summarizer，沿用现在的失败说明链路，只在 `error` 前加一句「换了一种思路仍然没能算出来」，不新增模板。口径闸拒收后 replan 也失败时，result 用的是**修复前**的结果（被拒的修复没有执行），所以 summarizer 看不到改过口径的数。

**事件与前端**：多一个 `replan` 节点事件，复用 `em.plan`，带 `source="replan"`。前端不用加新的段：步骤条按事件类型分段（`turn.ts:128-158`），第二个 plan 事件会让「计划」段计数变成 2，下一段仍然顺延到写代码；只需要让计划段的内容同时显示两版，并给第二版加上「重新规划」标签。快照里 replan 节点按 planner 契约检查；replan 之后的 codegen 输出天然被 codegen 五条契约覆盖（评测侧的提示：B1 现成可用）。

**验收**（phase75 第 3 步验收 ②）：
- 单元测试：每轮最多 replan 一次；超预算时不 replan；codegen 列缺失、executor 第一次报错时不 replan。
- 内网：同一 commit 前后两批快照（`DATACHAT_SNAPSHOT_DIR`），跑 `assess --diff`，列出发生过 replan 的题，以及这些题 executor 环和评测对错的 ok↔fail 翻转。**判据：replan 让一道以上原来失败的题变对，并且配对净退步 <6**（nightly_gate 的现行口径）。**归因要求**（S 补充）：每一道「救回」的题，都必须在快照里有 replan 节点的证据。快照带 case_id（B2），能对到具体的题；对救回题逐一检查 replan 计数 ≥1。没有 replan 的翻转算当轮抖动，不计入。原因是 n=202 时净进步 1 题本身就在噪声带内。如果一题都没救回，就把 S3-3 从 PR 里摘出去，只合并 S3-1 和 S3-2。

## 5. S3-4 grounding 假阳率（只量不改）

- 新脚本 `scripts/eval/grounding_fp.py`（B 组）：读最近一次 202 题报告，用 `report_adapter` 的 `unverified` 条目，把未核实的数字分成「带单位的计数/金额」「百分比」「派生数」「其他」四类，逐条列出题号、数字和结论原句。
- 人工标注其中「带单位的计数/金额」这一类，判断每条是不是真编造，算出假阳率，写进本文件附录。**拦不拦、拦在哪儿，由 S 看数再定**，本步不改 `service.py:428/751`。S 给的门槛建议：带单位的计数/金额这一类，假阳率 <5% 才考虑拦；拦的方式优先是「标记，并换成降级话术」，而不是拒答。
- 一并解决的口径分歧：产品侧证据含问题原文（`service.py:429`），`eval/consistency.py:10` 不含。量的时候两种口径都算，差异列进表里，S 定用哪个之后再统一成一份（phase75 §4 末段）。

## 6. 不做

- **react 链路**：它没有 planner/reviewer 节点，修复靠模型自己多次调用工具，replan 无从挂起。能力注入可以顺手给 react 的 system prompt 也加上（同一个 `prompt_lines`），但这样回归时会多一条链路发生变化。建议本步不加，见 §7 第 4 条。
- **不在 codegen 列缺失、executor 异常处熔断**（边界 2）。
- **不让 reviewer 查 `unique()`**：N9 的另一条路（phase75 §6）要把数据取值发给模型，属于出境合同的问题，仍由 S 定（phase7 §1）。本步的字面量豁免只做到「改对了不拦」，不负责「让它知道该改成什么」。
- **不改判分**：comparator、gold、题库都不动。

## 7. 已定（S，2026-11-24 13:46）

1. **三件放一个 PR**：同意，判据加上 §4 的归因要求。如果一题都没救回，就把 S3-3 摘出去，只合并 S3-1 和 S3-2。
2. **字面量豁免**：加。条件是同一列、同一运算符、只换比较值、且修复前结果为空，范围足够窄。
3. **replan 后 reviewer 给 1 次**：同意。replan 的价值在于换思路，不在于再试一次；P14 已经实证，试三次也救不回。
4. **react 不同步注入**：同意。同步注入会让 react 侧的 P8 基线断代，回归面翻倍。挂账，等 react 下一次改 prompt 时一并做。
5. **S3-4 看数再定**：同意，门槛建议见 §5。

## 8. 合并之后

- 按 phase75 §6 重立 v8 基线：机器空闲时连跑三次，取中位数。
- 第 4 步（评测降级）交给评测侧，四件一起做。
