# 阶段 7.6：U3 收尾与 U5 会话标题（方案）

> 前置：U3 结果卡已合并（PR #122，d84363c；issue #120 已关闭）。本文件只写方案，不改代码。
> 写法沿用 `phase76-ui.md` 和 `phase75-assess.md`：先写已定规则，再写可自动判定的验收，最后列待定项和推荐。代码证据统一以 d84363c 为准。

## 0. 结论

| 事项 | 推荐 | A 组 | P8 哈希 | 内网回归 |
|---|---|---|---|---|
| U3-1 一句话结论与正文重复 | **前端在正文里隐去已摘出的那一句**（做法 A）；隐不干净就不出卡头结论 | 不碰 | 不变 | 不需要 |
| U3-2 `key_numbers` | **server 层确定性产出**：从 `result` 原对象取候选数，再和结论里的数字逐个对上，对上的才出；口径小字取自 result 的结构（字典键、Series 索引和名字、单行表列名），不取自正文 | 不碰（新文件在 `app/server/`） | 不变 | 不需要 |
| U5 会话标题 | 后端 `app/server/` 新增本地规则：jieba 词性标注取指标词前紧邻的名词短语 + 指标词，取不到就取第一个分句截断 12 字；只在标题为空时生成；同一数据集重名追加序号 | 不碰 | 不变 | 不需要 |

三件都落在 `app/server/` 和 `ui/web/`，按 `phase75-assess.md:75`（「UI、桌面壳、不碰分析链路的 server 路由：只跑现有闸门」）只跑现有闸门。

A 组的判定以 `app/eval/fingerprint.py:38-70` 的 `_AFFECTS_RESULTS` 为准：`app/core/`（:44）、`app/tools/`（:45）、`app/nodes/`（:46）、`app/react_agent.py`（:39）、`app/memory/`（:50）都是 A；`app/server/` 是 B（:139 `_EXEMPT_PREFIXES`），`app/sidecar.py` 也是 B（:136）。**只 import A 组模块、不改它的文件，A 组指纹不变。**

---

## 1. U3 收尾

### 1.1 一句话结论与正文重复

**现状（代码证据）**

- 卡头结论由前端从正文摘出：`TurnView.tsx:119` `const lead = ... conclusionOf(answer)`；`conclusionOf` 取结论正文第一段的第一句，逐字摘取，只去掉 Markdown 记号（`turn.ts:195-220`）。
- 正文原样整段渲染：`TurnView.tsx:214` `<Markdown text={answer} />`，于是第一句出现两次。
- 后端没有单独的结论字段：`AnalysisResult` 只有 `answer`（`app/core/result.py:35`），注释也写明了这一点（`turn.ts:197`）。
- 现有 vitest 钉的是「正文照常完整显示」（`u3-result-card.test.tsx:78-82`），没有钉「不重复」。
- fake 模型的结论只有一句：`ANSWER = "（fake）结论：数据共有若干行。"`（`tests/fake_llm.py:81`）。按 `conclusionOf` 的断句规则（`turn.ts:216`，全角冒号不算句末），整句都会被摘走，正文剩空。

**做法比较**

| | A 前端在正文里隐去已摘出的那一句 | B summarizer 单独输出 headline 字段 | C server 层确定性拆分（answer → headline + body） |
|---|---|---|---|
| 改哪里 | `ui/web/src/turn.ts`（`conclusionOf` 同时返回剩下的正文）、`TurnView.tsx:214` | `app/nodes/summarizer.py:4-12` 的 `_OK_PROMPT`，加上输出格式；`app/react_agent.py` 的 system prompt（react 没有 summarizer 节点，结论由 agent 最后一条消息给出，`service.py:663-666`）；`app/core/result.py` 加字段；`service.py` 两条链路各自解析 | `app/server/app.py` 的 done 分支（:973-983），把拆分逻辑从前端搬到后端 |
| A 组 | 不碰 | **碰**：`app/nodes/`、`app/react_agent.py`、`app/core/` 全是 A | 不碰（`app/server/` 属 B） |
| P8 哈希 | 不变 | **要重立五个**。workflow 的 digest 把 summarizer 那次调用也算在内（`tests/test_memory_p8.py:87-89` 用 `wf_model`，`tests/test_core_analyze.py:17-29` 对 summarizer 的 prompt 照样记录）；react 改 system prompt 会让三个 react 哈希一起变 | 不变 |
| 内网回归 | 不需要 | **要跑全量 202 题**：summarizer 主模板属于「全局 prompt」（`phase75-assess.md:71`），不许只跑子集 | 不需要 |
| 风险 | Markdown 记号跨句时，隐去后会残缺（如 `**深圳销量最高！**其余略`），要有退路 | 模型不一定按格式输出，要写解析和兜底；headline 也要过 grounding；两条链路的 prompt 各改一遍；`answer` 进入记忆和历史（`turn_snapshots`），格式一变还会牵动记忆哈希 | 与 A 等价，但前端已有 `conclusionOf` 和它的 11 条 vitest（`u3-result-card.test.tsx:20-40`），搬到后端等于在 Python 里重写一遍，旧消息还得回填 |

**推荐 A**。理由：这是纯显示问题，`answer` 本身没有错，不值得为它动 prompt、重立哈希、跑 25 分钟评测。C 比 A 多一份重复实现，没有额外收益。

**A 的规则（写死）**

1. `conclusionOf` 改成返回 `{ lead, body }`。lead 的取法不变（`turn.ts:199-220`）；body 等于原文去掉 lead 在**原始 Markdown**里对应的那段前缀，其余一个字符都不动。
2. 只在能干净去掉时才去掉。被去掉的原文前缀里，`**`、`__`、`` ` `` 必须成对，链接 `[..](..)` 必须完整，否则视为「隐不干净」，这时 **lead 返回 null，卡头不出结论，正文完整显示**（退回 U3 之前的样子）。原则：宁可不出卡头结论，也不让同一句话出现两次，也不让正文残缺。
3. 去掉后第一段只剩空白时，整段删除。它前面的小标题（如 `### 结论`）保留，不做额外清理。
4. body 为空（fake 那种一句话结论）时，`TurnView.tsx:214` 的正文块不渲染。
5. 只改显示。消息的 `content`、`result.answer`、导出、会话记忆读到的都还是完整原文（`app.py:982` 存的是 `r.answer`）。

### 1.2 后端补 `key_numbers`

**现状（代码证据）**

- 前端已经按 `result.key_numbers = [{value, label}]` 实现：最多 3 个（`turn.ts:226`），形状不对的丢掉，`unverified_numbers` 里有的不放大（`turn.ts:227-238`）。注释写明「不从结论正文里猜数字、猜口径」（`turn.ts:222-224`）。今天后端不产出这个字段，所以卡片永远不出数字（`u3-result-card.test.tsx:56-60`）。
- grounding 只做检测：`app/core/grounding.py:57-72` `unverified_numbers(answer, evidence)`，把结论里「有分量」的数字（带小数、带 %/万/亿，或绝对值 ≥ 100 的整数，年份跳过，`:36-43`）逐个到证据里找，按结论写出的精度比较（`:46-54`）。
- 证据来源两条链路不同：
  - workflow：`[question, res.result_text] + metrics_block`（`service.py:427-430`）。`result_text` 是 `format_result` 的预览，最多 60 行、3000 字（`result.py:155`）。
  - react：问题、本轮每次执行的 ToolMessage 内容和 stdout、`get_turn` 取回的历史原文（`service.py:645-660`），再加 metrics_block（`:750-752`）。
- summarizer 只产出 `answer` 和 `answer_truncated`（`app/nodes/summarizer.py:39-40`），prompt 里没有任何结构化输出（`:4-12`）。
- result 的组装：workflow 在 `service.py:406-430`，`res.result` 只在执行成功时取（:413-414）；react 在 `service.py:710-736`，`res.result` 取**最后一次成功执行**的结果（:724-729），拒答时是拒答字符串（:720-723、:733-736）。
- `AnalysisResult.to_record()` 不带 `result` 原对象（`result.py:81-82`），所以落库的 `result_json` 里没有原始值，只有 `result_text`。原对象只在 done 事件的 `Event.result` 上（`events.py:47-56`）。
- server 的 done 分支已经有往 result 里补字段的先例：`d["data"]["result"]["meta"] = meta`（`app.py:976`），补完再落库（:983）、再外发（:988-989 的 yield）。

**谁来产出：三种做法**

| | K1 summarizer 让模型给出 | K2 service 里确定性取 | K3 server 里确定性取（推荐） |
|---|---|---|---|
| 数从哪来 | 模型挑 | `res.result` 原对象 | 同 K2 |
| 口径小字 | 模型写 | result 的结构 | 同 K2 |
| A 组 | 碰（`app/nodes/`、`app/react_agent.py`、`app/core/`） | 碰（`app/core/service.py`） | 不碰 |
| P8 哈希 | 要重立（理由同 1.1 的 B） | 不变（不改 prompt） | 不变 |
| 内网回归 | 全量 202 题 | A 组指纹变了，报告会标成不可比；按 `phase75-assess.md` §3，这类改动不在任何一档的豁免里 | 不需要 |
| 能不能溯源 | 不能保证，事后还得再核一遍 | 能 | 能 |

**推荐 K3**：新文件 `app/server/key_numbers.py`，在 `app.py` done 分支补 meta 的同一处调用。

**规则（写死）**

1. **只在这些情况产出**：`r.ok`、`r.executed`、`not r.clarify`，且 `r.result` 不是拒答字符串。其余情况不写这个键（前端按缺键处理，`turn.ts:229`）。
2. **候选数（值，口径）全部来自 `r.result` 原对象，按 result 自己的顺序**：
   - 标量（数字，不含 bool）：口径取问题里的第一个指标词（`app/core/ambiguity.py:34-43` 的 `METRIC_MARKERS`，只 import 不改）；问题里没有指标词就不出（不编口径）。
   - dict：数值项，口径就是键（模型常写 `{'最高销售额': 54406.5, ...}`，见 `comparator.py:652` 的规则 16）。
   - 数值 Series：不超过 3 项时全取；超过 3 项时，只有值单调（已排序，Top-N 一类）才取前 3 项，否则不出（按月这类未排序的序列，「前 3 项」没有意义）。口径为「索引 · Series 名」，没有名字时只用索引；索引是零点时刻的 Timestamp 时写成日期。
   - 单行 DataFrame：数值列，口径就是列名。多行 DataFrame 不出：拿不准哪一列、哪一行是关键。
3. **和结论对上才出，值用结论里的原文写法**：把结论按 grounding 的规则切出有分量的数字（`grounding.py:22-43`），对每个候选数，找第一个按 `grounding._candidates` 的容差（`:46-54`）对得上的结论数字。对上了，`value` 取结论里的原文（如「82.2 万」「22.30%」「1,061」），`label` 取候选数的口径。每个结论数字最多用一次；最多 3 个。
   - 这样每个数字都**同时**满足两个条件：能在 result 里找到（候选数本来就从 result 取），也出现在结论里（不会把结论没提到的数放大）。
   - 值的写法和用户在正文里读到的一致，不用另定数字格式；占比 0.2230 对上「22.30%」也是靠 grounding 现成的「比例 ↔ 百分数」规则（`:54`）。
   - `value` 在 `r.unverified_numbers` 里的跳过。按构造它不应该出现在那里；这一条是双保险，前端 `turn.ts:230` 还有第三道。
4. 小整数（< 100、不带单位）不出：grounding 本来就不核它们（`:43`），没核过的数不放大。
5. 旧消息不回填：原对象没有落库（`result.py:81-82`），回填只能从 `result_text` 反解析，那就成了猜。旧消息照旧不出数字。

**两条链路怎么处理**

两条链路最后都汇到同一个 `AnalysisResult`，server 侧只有一份代码，不分支。差别只在 `r.result` 是什么：

- workflow：`r.result` 就是 summarizer 看到的那份结果（`service.py:413-415`、`summarizer.py:35-38`），结论里的数字基本都出自它，命中率最高。
- react：`r.result` 只是**最后一次成功执行**的结果（`service.py:724-729`），结论可能引用了更早几次执行的数字（证据里有，`service.py:656-660`）。这些数不进 key_numbers，所以 react 的数字可能更少，但不会出错。步数用完、强制收尾（`service.py:678-708`）时 `r.result` 仍是最后一次成功执行，规则不变；收尾判成拒答时 `r.result` 是字符串，不出数字（:720-723）。

**改哪些文件**

| 文件 | 改动 | 组 |
|---|---|---|
| `app/server/key_numbers.py`（新） | `key_numbers_of(r: AnalysisResult) -> list[dict]`；import `app.core.grounding` 的 `_tokens / _significant / _candidates` 和 `app.core.ambiguity.METRIC_MARKERS`，只读 | B |
| `app/server/app.py:976` 之后 | 加一行写入 `d["data"]["result"]["key_numbers"]`。**不改 :976 那一行本身**：`tests/test_inject_check.py:324` 按字面断言这一行；新加的这一行同样在 `test_inject_check.py` 里按字面钉住 | B |
| `ui/web/src/turn.ts:222-224` | 只改注释（「后端现在不产出」改成产出规则的出处），逻辑不动 | UI |
| `tests/test_key_numbers.py`（新） | 见 1.3 | — |

不加 `AnalysisResult` 字段，不改 `app/core/`，所以 CLI 和评测报告里没有 key_numbers。这是有意的：它只给界面用。

**原型核对**（在沙箱里拿 `grounding.py` 原文跑过，不进仓库）：

| result | 结论 | 问题 | 得到 |
|---|---|---|---|
| Series{深圳 1061, 上海 822023.63, 北京 300}，name=销量，降序 | 深圳销量最高，共 1,061 单；上海 82.2 万。 | 各城市销量 | `[{82.2 万, 上海 · 销量}, {1,061, 深圳 · 销量}]` |
| 8998790.914 | 总销售额为 8,998,790.91 元。 | 总销售额是多少 | `[{8,998,790.91, 销售额}]` |
| 1685 | 总销量 1685 | 哪个地区卖得最好 | `[]`（问题里没有指标词） |
| {占比 0.2230, 均值 3.1416, 行数 7} | 占比 22.30%，均值 3.14。 | — | `[{22.30%, 占比}, {3.14, 均值}]` |
| 4 个月、未排序的 Series | 2 月最高 900。 | 月度销量 | `[]` |

### 1.3 U3 收尾的验收

| 层 | 断言 |
|---|---|
| vitest（`u3-result-card.test.tsx` 扩充） | ① 对照表：`conclusionOf` 返回的 body 等于原文去掉 lead 对应的那段原始 Markdown 前缀，其余逐字不变；② 跨句的 Markdown 记号（`**深圳销量最高！**其余略`）→ lead 为 null，正文完整；③ 渲染后 lead 的文字在 `.answer .md` 里出现 0 次，现有用例「上海次之」照样在；④ 一句话结论（body 为空）不渲染正文块；⑤ `key_numbers` 用例改用 K3 的真实形状（`label` 带「 · 」）；原有 11 条 `conclusionOf` 用例（:21-39）lead 的期望不变 |
| pytest | `tests/test_key_numbers.py`：① 1.2 原型表的 5 行当期望；② 每个产出的 `value` 都满足「在结论原文里」且「按 grounding 规则能在 `str(r.result)` 里核到」，这一条对所有用例统一断言；③ clarify、未执行、拒答、多行 DataFrame 不产出；④ 走 `TestClient` 跑一轮 fake 分析：done 事件和 `GET /sessions/{id}` 里的 `result.key_numbers` 一致（落库与外发同源）；⑤ `tests/test_memory_p8.py` 五个哈希不变（不用改，跑绿即可）；⑥ `tests/test_fingerprint.py` 的 A 组分区不变 |
| e2e（`f4-result-card.spec.ts` 加一条） | 照 `stubFirstResult`（:17-29）的做法，给第一条助手消息的 result 桩上 `answer`、`key_numbers`、`unverified_numbers`：① `key-numbers` 里的 `.kn-value` 正好是桩里未核实之外的前 3 个；② `result-lead` 的文字在 `.answer .md` 里不出现；③ 重放（刷新页面）后两条照样成立。真跑 fake 的那条只断言「（fake）结论」仍在卡片里（现有 e2e 用 `toContainText` 断言整张卡，lead 在卡头，照样能过） |

---

## 2. U5 会话标题

### 2.1 现状（代码证据）

- **后端**：首问时 `if not s.title: s.title = body.content[:60]`（`app/server/app.py:933-934`），用户原话前 60 字。建会话可以带 title（`app.py:119-122`、:842），前端建会话时不带（`client.ts:54`）。改名 `PATCH /sessions/{id}`，去控制字符、strip、截 120 字，**允许空串**（`app.py:857-861`、`SessionPatch` :125-126）。库里只有一列 `title`，没有「是不是用户改过」的标记（`db.py:56`）；加列等于强制迁移（`app.py:911-912` 的注释写明 `create_all` 不会给旧表加列）。
- **前端**：
  - 首问时乐观地把标题设成 `question.slice(0, 60)`（`SessionView.tsx:96-105`），和后端的规则各写一份；流结束后再从库里同步（:122-131）。
  - 侧栏显示 `s.title || "未命名会话"`（`Shell.tsx:308`），改名时空串不提交（:309-312）。
  - 会话页标题框失焦就改名（`SessionView.tsx:235-243`），**空串也会提交**。
- **现有测试依赖原话标题**：`tests/test_server.py:80` 断言标题等于「哪个地区卖得最好」；`f3-charts.spec.ts:65`、`:122` 按 `startsWith("画 ")`、`startsWith("画 5000")` 找会话（提问分别是 `画 ${kind}`、`画 5000 点`，:52、:107）。
- **jieba**：
  - 依赖已在：`requirements.txt:16` `jieba==0.42.1`；`app/tools/dictionary.py:16,28`、`app/tools/value_hints.py:18,35` 在用 `jieba.lcut`。
  - sidecar 自检已探测：`app/sidecar.py:104` `import jieba`，`:108` `list(jieba.cut("各地区销量"))`。**只探测了分词，没探测词性标注 `jieba.posseg`。**
  - 打包：`packaging/build_sidecar.py:27` `--collect-data jieba` 收了词典数据。DEVLOG 记的打包体积里 jieba 占 29.6 MB（`docs/DEVLOG.md:771`）。
  - `jieba.posseg` 在 CPython 下 import 的是 `posseg/*.py` 里的大表（`char_state_tab`、`prob_emit` 等），不是 `.p` 数据文件。PyInstaller 只有静态分析到 `import jieba.posseg` 才会收这些模块；今天没人 import，所以冻结包里**大概率没有**，要靠自检证明。
- **实测**（沙箱 Linux、CPython 3.12、jieba 0.42.1，三次取值；Windows 打包版要另量）：

| 项 | 耗时或体积 |
|---|---|
| `import jieba` | 0.04 s |
| 首次分词（加载主词典，命中 `/tmp/jieba.cache` 9.2 MB） | 0.60–0.71 s |
| `import jieba.posseg` | 0.27–0.28 s |
| 词性标注，单句 | 0.42 ms |
| jieba 包目录 | 42 MB（其中 `posseg/` 15 MB，含 `.p` 5.6 MB、`.py` 大表 7.4 MB、pyc 3.3 MB） |

  主词典的加载今天在分析时就会发生（dictionary / value_hints），U5 只是把它提前到首问；**净增的是 posseg 一次 0.28 s，按进程算一次**。冻结包预计增加 posseg 的 pyc 约 3–4 MB（估计值，以打包实测为准）。

### 2.2 已定规则（S 2026-11-19，`phase76-ui.md:44`、`:80`）

不再直接用用户原话；本地规则：jieba 取第一个名词短语加指标词，取不到就截断 12 字；不调模型。

### 2.3 规则细节（本方案提议）

**放在哪里**：新文件 `app/server/titles.py`，函数 `session_title(question: str) -> str`，在 `app.py:933-934` 调用。属 B 组。

**指标词表**：复用 `app/core/ambiguity.py:34-43` 的 `METRIC_MARKERS`（只 import）。`dictionary.py` 和 `value_hints.py` 里没有现成的词表：前者是 BM25 检索器（`dictionary.py:37-60`），后者把问题分词去匹配列取值（`value_hints.py:33-41`），都只用 jieba，不带词表。`METRIC_MARKERS` 是仓库里唯一一张「能量出数的名词」表，来源和天花板在 `ambiguity.py:21-27` 写明了。
代价：`METRIC_MARKERS` 是 A 组的一部分，管 clarify 放行。以后谁为了 clarify 改这张表，标题的单测对照表会跟着变；反过来，**标题不许为了好看去改这张表**。标题要补词时，在 `titles.py` 里另加一张本地补充表。

**算法（逐步，全部确定性）**

1. 预处理：NFKC，去控制字符，连续空白合成一个，strip。结果为空时返回空串（前端显示「未命名会话」，`Shell.tsx:308`）。
2. 取第一个分句：在第一个 `：:，,。？?！!；;` 处截断，得到 head。
3. 在 head 里找指标词：取 `METRIC_MARKERS` 的第一个命中；紧挨着的后续命中并成一段（「离职」+「人数」→「离职人数」，「退款」+「金额」→「退款金额」）。
4. 名词短语：对 head 做 `jieba.posseg.cut`，在指标词**之前**找第一段连续的名词（词性以 `n` 开头，或是 `vn`、`an`、`eng`），跳过泛词（数据、这份、表、图、图表、情况、结果、分析……，写在 `titles.py` 里）。前面没有，再到指标词**之后**找。名词跨过指标词边界时截在边界处。
5. 有指标词也有名词短语时，按原文语序拼接，截到 12 字；否则用 head 截 12 字。不加省略号，溢出由侧栏 CSS 处理。
6. 不调模型，不读数据集。

**什么时候生成**：只在 `post_message` 里 `s.title` 为空时生成（`app.py:933`），也就是首问时。之后不再改。

**用户改过的标题不覆盖**：现在的判据「只在标题为空时写」已经够用，不加列。

- 用户在首问前改名（标题非空）→ 首问不覆盖。
- 首问之后，自动标题已经非空 → 以后的提问不会再写。
- 唯一的缝：会话页标题框可以清空并提交（`SessionView.tsx:237-239`，`PATCH` 允许空串），清空后下一问会重新生成。这和侧栏不一致（`Shell.tsx:312` 拦了空串）。建议把两处统一：清空就当成「还原自动标题」，见待定 3。

**重名**（`phase76-ui.md:55` 已列为验收）：同一数据集下已有同名会话时，追加「（2）」「（3）」……只对自动生成的标题去重，用户手动改的名字照原样保存。

**前端同步**：删掉 `SessionView.tsx:96-105` 那份乐观的 `question.slice(0, 60)`，规则只留在后端一份。为了不让首问期间标题空着（一轮分析常要几十秒），后端在流式响应头里加 `X-Session-Title`（百分号编码；HTTP 头只能是 latin-1），和现有的 `X-Message-Id` 放在一起（`app.py:1005-1007`）。前端读到后 `decodeURIComponent`。流结束后的同步（:122-131）不变。

**样例对照表**（沙箱里用 jieba 0.42.1 和仓库里的 `METRIC_MARKERS` 原文跑出来的；作为单测期望）

| # | 问题 | 标题 | 走的分支 |
|---|---|---|---|
| 1 | 各地区销售额是多少 | 地区销售额 | 名词 + 指标词 |
| 2 | 哪个品类的利润最高？ | 品类利润 | 名词 + 指标词 |
| 3 | 华东区客单价环比变化 | 华东区客单价 | 名词 + 指标词（「客单价」整段命中，不会被切成「客 / 单价」重复） |
| 4 | 按部门统计离职人数 | 部门离职人数 | 相邻指标词合并 |
| 5 | 商品退款金额前十 | 商品退款金额 | 相邻指标词合并 |
| 6 | 员工平均年龄是多少 | 员工平均年龄 | 指标词「员工」在前，名词短语在后，按原文语序 |
| 7 | 2024年各月的订单数量趋势 | 订单数量 | 名词 + 指标词 |
| 8 | 各城市销量 | 城市销量 | 名词 + 指标词 |
| 9 | 哪个地区卖得最好 | 哪个地区卖得最好 | 没有指标词 → 截断（`test_server.py:80` 不用改） |
| 10 | 看看这份数据有什么：有哪些表和字段、…（U4 卡片，`StarterCards.tsx:18`） | 看看这份数据有什么 | 第一个分句 |
| 11 | 找出这份数据里的异常值：…（`StarterCards.tsx:24`） | 找出这份数据里的异常值 | 第一个分句 |
| 12 | 生成你认为重要的分析图表 | 生成你认为重要的分析图表 | 截断（正好 12 字）；同一数据集第二个会话是「生成你认为重要的分析图表（2）」 |
| 13 | 画 5000 点 | 画 5000 点 | 截断（`f3-charts.spec.ts:122` 的 `startsWith("画 5000")` 照样成立） |
| 14 | 近三个月每周新增客户数的走势如何 | 近三个月每周新增客户数的 | 截断 12 字 |
| 15 | （全是空白） | 空串 → 界面显示「未命名会话」 | 预处理 |

第 12、14 行就是规则的天花板：没命中指标词的问题，标题仍是原话的前 12 字。要改善只能往 `titles.py` 的补充表里加词（如「图表」），见待定 2。

### 2.4 是否碰 A 组、分析链路，要不要内网回归

- 不碰 A 组：改动在 `app/server/`（B，`fingerprint.py:139`）、`app/sidecar.py`（B，:136）、`ui/web/`。`METRIC_MARKERS` 和 jieba 只 import 不改。
- 不碰分析链路：标题在 `post_message` 里、`analyze_stream` 之前算好，不进 `kwargs`（`app.py:939-941`），模型看不到。P8 哈希不变。
- 按 `phase75-assess.md:75`，只跑现有闸门，**不需要内网回归**。
- 要改的自检：`app/sidecar.py:104-108` 加上 `import jieba.posseg` 和一次 `posseg.cut`。这样冻结包缺 posseg 时自检会红；PyInstaller 也会因此把 posseg 收进包。

### 2.5 U5 的验收

| 层 | 断言 |
|---|---|
| pytest | ① `tests/test_titles.py`：2.3 的对照表逐行相等；② 标题长度 ≤ 12（去重后缀除外）；③ 同一数据集重名追加（2）（3），不同数据集同名不追加；④ 先 `PATCH` 改名再首问，标题不被覆盖；首问后再问，标题不变；⑤ 响应头 `X-Session-Title` 解码后等于库里的标题；⑥ `test_server.py:80` 不用改，照样绿；⑦ sidecar 自检的 imports 一项包含 posseg |
| vitest | ① 首问后顶栏和侧栏的标题取自响应头，不再出现 `question.slice(0, 60)`（删掉的代码要有用例证明行为没丢）；② 正在编辑标题时不被覆盖（`editingTitle`，:100、:129 的现有行为） |
| e2e | 上传、首问「各地区销售额是多少」后，侧栏会话按钮的名字是「地区销售额」；`f3-charts` 两处 `startsWith` 不用改，照样绿 |
| 打包 | Windows CI 打 sidecar 后跑 `--selftest` 全绿；记一次打包体积变化，写进 DEVLOG |

---

## 3. 顺序

U3-1（纯前端）→ U3-2（server + 前端注释）→ U5。三件都不碰 A 组，按 S 的大批次习惯合成一个实现 PR；不需要内网回归。

## 4. 已定（S 2026-11-24，7 条全部按推荐）

1. **U3-1 选 A**：隐不干净时，卡头不出结论，正文完整显示，丢的只是卡头这层装饰，内容不丢。B 要碰 A 组、重立 5 个 P8 哈希、跑全量 202 题，代价与收益不对称。**「lead 在正文里出现 0 次」必须写进 vitest**：A 方案只可能在这里回归。
2. **标题补充词表先不补**：没命中指标词时退回截 12 字，这样的标题仍然合格。以后某个词在真实标题里高频出现，再针对它补。
3. **清空标题等于还原自动标题**：自动标题是兜底，用户要么用它，要么改成自己的。侧栏不能提交空串、会话页能，这处不一致要改成两处一样，不许只改一边。
4. **重名后缀用序号**「（2）」「（3）」。
5. **标量的口径取问题里的第一个指标词**；问题里没有指标词就不出。
6. **直接 import grounding 的私有函数，并用 pytest 钉住**：`_tokens / _significant / _candidates` 三个名字和调用签名都写进测试，以后有人重构 grounding 时会看到。`app/core/grounding.py` 的内容不动，A 组指纹不变。
7. **jieba.posseg 进包**：不加新依赖（jieba==0.42.1 已在 requirements）。**sidecar 自检必须加 posseg 探测**（#109 openpyxl hidden-import 的教训）。lcut 加泛词表这条退路没有实测，不采用。

### 补充约定（S 2026-11-24）
- `app.py:976` 后面新加的那行 key_numbers 调用，**也要在 `tests/test_inject_check.py` 里按字面钉住**，与 :324 钉 :976 的做法相同，免得被当成孤立的一行「清理」掉。
