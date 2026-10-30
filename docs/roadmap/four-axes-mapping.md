# DataChat 的四板斧对照：已发生的设计过程

> 读法：每一步写三样——板斧问什么、DataChat 怎么答的、答案落在哪。**只收仓库里已经存在的东西**，每条带 `文件:行` 或文档章节。四板斧里有、项目里没有的集中放 §5，只陈述事实和当时的理由，不是改进建议。
>
> 对照对象：《通用Agent设计方法论（四板斧）》，飞书 wiki `AlQYwOAFDiIsANkdVrmcEoQLnne`（rev 16）。

## 0. 四板斧之前的起点：场景

四板斧说"不从接哪个模型开始，从场景开始"。DataChat 的场景约束在写第一行代码前就定了四条，后面所有取舍都是这四条的推论：

| 场景事实 | 直接推论 |
|---|---|
| 单用户、本机 | 不做多租户、不做登录、不做任务队列（阶段 8 才做） |
| 用户自带 Key | Key 必须进系统钥匙串、绝不能进沙箱子进程的环境变量 |
| 数据是用户的中文脏表 | 编码检测、缺失哨兵、合计行处理优先级高于模型能力 |
| 要卖给不碰命令行的用户 | 最终形态是桌面产品，不是脚本 |

证据：`docs/roadmap/plan.md`「目标与前提」、`docs/THREAT_MODEL.md`（桌面阶段目标与 (b) 条件）。

---

## 一 · 第一板斧：场景材料与外部能力

### 1.1 材料识别：什么进上下文

| 板斧的判断 | DataChat 的答案 | 落点 |
|---|---|---|
| 什么信息必须进上下文 | 表结构 + 抽样数据 + 字段说明 + 用户问题 + 上一轮结论 | `app/tools/schema.py:45` `describe_df` |
| 什么应该走 RAG | 数据字典（列的中文说明）——**真的建了检索器**，但用最轻的形态 | `app/tools/dictionary.py:1`「数据字典 RAG（BM25 词法检索）」 |
| 什么不进上下文 | 全表数据、全量 print、全量历史 | 见 1.2 |
| 什么通过工具拿 | 真实数值结果——不靠模型心算 | `run_python_on_data` |

RAG 这一条值得单说：它没有用向量库，用 BM25 词法检索，理由写在 `dictionary.py:4`——"几毫秒返回，对列名/字段中文说明这种短文本检索足够好"。检索结果也**不拼进用户问题**，而是作为独立的 `field_notes` 放进系统提示（`app/react_agent.py:160` 注释，B04）。这是"RAG 结果的位置也是设计决定"的一个实例。

### 1.2 上下文预算：每条材料都有截断线

| 材料 | 上限 | 落点 |
|---|---|---|
| 样例行数 | 3 行 | `schema.py:45` `describe_df(n=3)` |
| 列名长度 | 64 字 | `schema.py:14` `MAX_NAME_CHARS` |
| 样例单元格 | 40 字 | `schema.py:13` `MAX_CELL_CHARS` |
| 回给模型的 print | 2000 字 | `react_agent.py:31` `PRINT_CHARS` |
| 回给模型的 result | 1500 字 | `react_agent.py` 工具返回 `format_result(max_chars=1500)` |
| 存库/展示的 result | 3000 字 / 60 行 | `app/core/result.py:137` |
| 历史轮数 | 10 轮 × 结论 2000 字 | `app/core/service.py:334-335` |

### 1.3 能力：只做了一个 Tool Calling

板斧列了 Tool Calling / MCP / CLI 三条路。DataChat 只走第一条，且只有一个工具：

- `run_python_on_data(code)`（`app/react_agent.py:175`）——在沙箱里执行 pandas，返回 result 文本。
- 图表不是第二个工具，而是**注入到沙箱命名空间的 `chart()` 函数**（工具说明里写"pd、np、plt、chart 已就绪，无需 import"）。这是"工具数 vs 表达力"的取舍：一个代码执行工具能覆盖无穷种分析，代价是沙箱必须做厚。
- 多表时不加工具，而是把工具说明里的 `df` 换成 `dfs`（`react_agent.py:218-222`），并另给一条取数约定 `access_rule`（`app/tools/dataset.py:107`）与审查侧对应的 `review_access_rule`（`:116`）。

不用 MCP：没有企业系统、远程服务、跨客户端复用的需求。
不用 CLI：任务不是"操作本地工具链"，而是"在数据上算数"。

### 1.4 边界：权限、确认、审计

板斧问"哪些工具必须加权限、确认和审计"。DataChat 的回答是把风险全部压进**执行边界**，而不是加确认弹窗：

| 边界 | 做法 | 落点 |
|---|---|---|
| 导入白名单 | `ALLOWED_IMPORTS` 冻结集合，`__import__` 被替换 | `app/tools/sandbox_policy.py:13,20-24` |
| 进程隔离 | 子进程 + 干净环境变量（不含 Key） | `app/tools/sandbox.py:56` `_child_env` |
| 超时 | 主进程强杀，Windows 关 Job 连带杀，其他平台杀进程组 | `sandbox.py:6`、`:224` |
| 内存 | Windows Job Object / Linux RLIMIT_AS | `sandbox.py:209-213`、`app/tools/_winjob.py` |
| 文件系统 | 只允许写工作目录，读写外侧被拦 | `tests/test_sandbox.py:69,75,83` |
| Key 保护 | 钥匙串，不进子进程环境 | `app/core/keystore.py`、`test_api_key_not_in_child_env` |
| 网络边界 | 只监听 127.0.0.1 + TrustedHost 挡 DNS rebinding + 每次启动随机 token + CSP | `app/server/app.py:75,165,174-178` |
| 用户输入串 | 统一字符集，`_display_safe` 在 spec 校验前全路径替换 | `app/core/text.py`、`app/tools/charts.py` |

"哪些动作要人工确认"这一条，DataChat 的答案是：**没有**。因为所有写操作都在沙箱工作目录内、产物只有图和数据，没有任何外发动作。这本身就是场景约束（单机、自带 Key）的推论。

---

## 二 · 第二板斧：Agent 能力编排与推理

### 2.1 Prompt：按职责拆成五个节点，不是一个巨型提示

| 节点 | 解决的问题 | 落点 |
|---|---|---|
| planner | 这题该怎么拆 | `app/nodes/planner.py` |
| codegen | 计划转成 pandas 代码 | `app/nodes/codegen.py` |
| executor | 在沙箱里执行 | `app/nodes/executor.py` |
| reviewer | 报错后修代码，且保留原计划与图表要求 | `app/nodes/reviewer.py:1-25`（B06） |
| summarizer | 结论成文 | `app/nodes/summarizer.py` |

ReAct 侧则是一个系统提示装完（`react_agent.py:221` 起），因为循环本身负责拆步骤，不需要 planner 预先拆。

### 2.2 Agent Loop：两个实现，停止条件都写死了

**workflow**（`app/graph.py`）：`planner → codegen → executor → (报错且还有次数) reviewer → executor`，否则 `summarizer`。

- 错误恢复 = 条件回边 + 重试上限 `max_attempts`（默认 3）。
- 停止条件 = 执行成功，或重试耗尽，或**token 预算命中**——`_route_after_exec` 里 `over_budget()` 时即使还有次数也不进 reviewer（`graph.py:9-17`，V2d §2d）。

**react**（`react_agent.py:94-146`）：`agent → (有 tool_calls) tools → agent`，没有就结束。

- 停止条件 = 模型不再调工具。
- 错误恢复 = 工具返回错误文本让模型自己修正，外加 `nudge_no_exec`：一轮里既没执行也没按契约拒答就想收尾，提醒一次（`react_agent.py:157`，B70）。
- 递归兜底 = `GraphRecursionError` 时仍取已有消息（`service.py:350`，B61）。

两个实现共用同一套工具、同一份 schema、同一个沙箱，只换编排——这样评测时"编排差异"是唯一变量。

### 2.3 Memory：三层，且刻意不等同于聊天记录

| 层 | 内容 | 落点 |
|---|---|---|
| 图状态 | `MemorySaver` + `thread_id` 的 `checkpointer` 能力存在，但**产品路径不用**，只在测试里跑；`analyze()` 的 `memory` 与 `history` 互斥 | `react_agent.py:148`、`service.py:125-126` |
| 数据库 | `messages` / `events` 表，重启可重放 | `app/server/db.py` |
| 进上下文的窗口 | 最近 10 轮 `(问题, 结论)`，结论截 2000 字；只取 `status=="ok"` 的轮次 | `service.py:342` `history_messages`、`app.py:278` `turn_history` |

板斧说"Memory 不等同于聊天记录"——这里的对应做法是：**全量消息入库用于重放，但进提示词的只有裁剪后的 (问题, 结论) 对**，中间的代码和执行细节不进下一轮上下文（要看得去「查看过程」里展开）。

这个取舍的代价写在 `memory-system.md` 的 D3：前一层的图表 spec 和代码不进历史，所以"改刚才那张图"必须整轮重算。当时选它是为了控制 token，不是认为它最优。

### 2.4 Skill：没有

项目里没有 Skill 层。理由是可查证的：流程还在变（阶段 5 每一轮迭代都在改图表和标记卡），此时固化 Skill 会把未稳定的流程写成资产。已经稳定的部分（画图、取数约定）是用代码常量固化的：`CHART_GUIDE`（`app/tools/plotting.py`）、`access_rule` / `review_access_rule`（`dataset.py:107,116`）。

### 2.5 Multi-agent：没有上，而且是故意的

两个 agent（workflow / react）不是多 agent 协作，是**同一任务的两种单 agent 实现**，用来做同场 A/B（plan.md 阶段 3：「两个 Agent 同场比较准确率、耗时、token」）。

板斧的"何时升级"表里，DataChat 只碰到了"生成者自审流于形式"这一格——reviewer 是同一个模型修自己写的代码，不是独立 Critic。这一格没有升级成 Generator + Critic，而是换了个问法：把"自审"降级为"报错信息驱动的重试"，并让评测去发现它不够（`docs/roadmap/phase7-accuracy.md` E2 过程验证器就是为此准备的）。

---

## 三 · 第三板斧：评测与调优

### 3.1 Eval 五维，逐项对上

| 维度 | DataChat 的做法 | 落点 |
|---|---|---|
| **Outcome 结果** | 自造 130 题 + 闸门 25 题；比较器 `results_equal` / `match_kind` 给结构判定 | `app/eval/cases*.py`、`comparator.py:89,112` |
| **Trajectory 过程** | 每一步都成事件（plan / code / exec / answer / error / done），`result.steps` 留耗时 | `app/core/events.py:72-93`、`result.py:17` `Step` |
| **Evidence 证据** | 结论里的数字必须在执行结果里出现过，否则报未验证 | `app/core/grounding.py:57` `unverified_numbers` |
| **Safety 安全** | 沙箱三类逃逸用例（import / 读文件 / 写文件）+ 超时 + 内存 | `tests/test_sandbox.py` |
| **Cost 成本** | `TokenUsage` 拆分 prompt / completion / reasoning / cached，缺 usage 时按字符估算；单轮预算 + `budget_hit` | `app/core/llm.py:115-186`、`:172` `over_budget` |

"Agent 评测必须看 Trace"这一条，对应的是**比较器只作参考、判定权在人工**：`docs/gate/JUDGE-GUIDE.md` 第一句就是"不要看 `auto_correct` 判对错"，因为它在闸门上被实证双向失准（M02）。

### 3.2 Trace

`trace_id` 贯穿（`events.py:63`），每个事件 `str(ev.ts)` 落库（`app/server/app.py:507`），前端重放走同一条 reduce（`ui/web/src/turn.ts`）。这把"还原它做过什么"变成了默认能力，而不是事后加日志。

### 3.3 基线管理

`docs/gate/thresholds.json` 的规则写在文件头：「改门槛只能新增 profile，不改旧的」。三个 profile 各自带来源和日期：`phase35`（S 2026-10-12）、`m13`（S 2026-10-14 复核）。报告的 verdict 段记录所用 profile 的 sha256 前 12 位。

这是"基线可追溯"的具体实现，比"我们跑过基线"这句话硬。

### 3.4 失败回流

回流不是自动的，是编号制的：

```
评测/闸门发现问题 → B 编号（工程缺陷）或 M 编号（商业标尺）
   → DEVLOG 记状态与证据 → 修复 → 下一轮 DEVLOG 逐项标"已修 / 未修"
```

可查的两个实例：
- `s02` 缺失哨兵 → B65 → 登记进 `thresholds.json` 的 `m13.agents.react.single.why`，同时进阶段 7 A1。
- 图表未出图的两条文案 → 从带 `ChartError` 原文改成固定文案（P1-17），因为"对用户来说出口都是重新生成或换个问法"。

### 3.5 CI 回归

`tests.yml` 的矩阵：pytest × 4（ubuntu/windows × 3.11/3.12）、web（lint + vitest + 构建 + Playwright）、gate-oracle × 2。另有两道**生成物一致性**检查：`gen_eval_data.py --check`、`gen_ui_types.py --check`——后端改了枚举而前端没重新生成，CI 直接红。

---

## 四 · 第四板斧：全栈产品承载

### 4.1 进程边界：三层，且**没有 IPC 层**

板斧给的是 Renderer / IPC / Main / Runtime 四层。DataChat 是三层：

```
WebView2 (Renderer: React)  ──HTTP/SSE──▶  sidecar (Runtime: FastAPI + 沙箱子进程)
        ▲                                        ▲
        └──────────  壳 (Main: Tauri, Rust)  ─────┘  启动 / 握手 / Job / 退出
```

**IPC 层是被明确取消的**，理由写在 `plan.md`「目标与前提」：*前端只通过 HTTP / SSE 调 FastAPI，不使用 Tauri 的 invoke / IPC——外壳可替换，外壳 spike 失败不返工前端（M22）*。

这条是本对照里唯一一处"和四板斧不一样"的结构性选择，而且是先有理由后有实现的。代价是少了 IPC 的类型契约，收益是外壳（Tauri / Electron / 托盘）可以整体换掉而前端零改动——后来 D1 真换壳时这一条兑现了。

### 4.2 契约：写在文档里、钉在测试里

`docs/sidecar-contract.md` + `tests/test_sidecar_contract.py`：

- 启动必须 `--port 0`（TIME_WAIT 会撞端口），不设 `SO_REUSEADDR`（Windows 上它会允许别人抢占，"只有本进程能收"这个前提就没了）。
- stdout **第一行**是 `{port, token, home}`，日志走 stderr 和 `home/server.log`，不会污染握手。
- 就绪判定 = 轮询 `/health` 200；端口在打印前已 bind，不存在"打印后被抢"的窗口。
- `test_port_is_exclusive_while_running` 钉住端口独占。

这是"IPC 类型契约"缺位后的替代品：契约从"类型系统保证"降级为"文档 + 测试保证"，但保证的东西是具体的。

### 4.3 持久化

SQLite 七张表（`app/server/db.py:28-109`）：`Dataset` / `DatasetFile` / `ChatSession` / `Message` / `EventRow` / `Feedback` / `Setting`。

- 表结构兼容 PG，预留 `user_id`（阶段 8 才用）。
- 重启重放靠 `EventRow` 而不是重新算（`test_replay_returns_stored_chart_option_verbatim_without_validation`）。
- `message` 表没有 `error_kind` 列，是登记的已知技术债（DEVLOG [34]）。

### 4.4 产品状态

板斧列的 Loading / Empty / Partial / Stale / Error / Retry，在 DataChat 里落成了两套受约束的枚举：

- 消息状态 5 个：`running / ok / error / cancelled / interrupted`（`ui/web/src/turn.ts:8`，由后端 `events.json` 生成，前端不能自造）。
- 错误类型 6 个：`ERROR_KINDS`（`turn.ts:7` 同源生成）。
- 约束方式：AST 扫描器 + `gen_ui_types.py --check`，前端用了生成集以外的值 CI 直接红。
- 另外有 `Partial` 的实例：图表部分生成时出 `CHART_PARTIAL_WARNING`（`result.py:113`），"另有 N 张图没画出来"。
- `Retry` 的实例：`llmErrorText.ts` 按 kind 给不同的重试建议，而不是一句"出错了"。

### 4.5 打包发布门禁

`desktop.yml` 四步，每步都能失败：构建前端 → 打包 sidecar 放进壳 resources → 打包壳（NSIS）→ **安装冒烟**（静默安装 → `--smoke` → `--smoke-selftest` 八项 → 强杀壳 → 静默卸载）。

`--smoke-selftest` 是把"嵌套 Job 里内存上限仍然生效"变成可执行断言的产物：worker 的 Job 嵌套在壳的 Job 里，让它在 512 MB 上限下申请 1.6 GB，看是否被抓。这是"发布门禁"里唯一一条真正跑过产品二进制的能力断言。

---

## 五 · 四板斧里有、项目里没有的（事实，不是建议）

| 四板斧条目 | 项目状态 | 当时的理由 / 归属 |
|---|---|---|
| IPC 类型契约 | 故意不做 | M22：外壳可替换优先于 IPC 的类型安全 |
| Skill 层 | 没有 | 流程未稳定，稳定的部分用代码常量固化 |
| 独立 Critic / Auditor | 没有 | reviewer 是同模型自修；对应的替代是 E2 过程验证器（阶段 7） |
| 多 Agent（Router/Critic/权限隔离） | 没有 | 单 agent 两实现做 A/B，未出现板斧列出的升级信号 |
| pass^k 稳定性 | 没有 | 阶段 7 E3，方案已写未实现 |
| LLM-judge | 没有 | 阶段 7 E4，依赖第二家模型家族的 Key |
| 自动失败回流 | 没有 | 人工判定 + B/M 编号 + DEVLOG，量小阶段够用 |
| MCP | 不用 | 无企业系统 / 远程服务 / 跨客户端复用需求 |
| CLI 工具 | 不用 | 任务不是操作本地工具链 |
| 训练 / 微调 | 不做 | 自带 Key 的产品形态下不成立 |

---

## 六 · 一句话读法

DataChat 的设计过程可以压成一条链：

**场景（单机自带 Key）→ 材料（schema 抽样 + BM25 字段说明 + 截断线）→ 能力（一个代码执行工具，边界做厚）→ 编排（两个单 agent 实现做 A/B）→ 评测（五维 + Trace + 编号回流）→ 承载（三层进程、HTTP 代替 IPC、契约写进测试）**。

四板斧的顺序在这条链上是**倒着校验**的：先有阶段 0–3 的痛苦（口径不可信、逃逸没挡、失败不知道往哪归），才有阶段 3.5 的闸门和阶段 4 的隔离；先进了 Tauri 壳才发现导出 PNG 要落盘，才有 `exports.py`。四板斧不是当初照着走的路线图，是事后能对上的一张坐标系——对得上的部分，恰好都是踩过坑之后补的。
