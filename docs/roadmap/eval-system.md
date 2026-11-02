# 评测体系扩写：从「10 个节点」到「四层 24 节点」

> 本文只做分析与取舍。**实现规格见 `eval-system-spec.md`**（任务卡、数据模型、验收命令）。两者冲突时以规格为准。
> 勘误：原标题写"20 节点"，§2 表格实际是 24 个（A 4 + B 10 + C 5 + D 5）；且 §2 里 `mde_pp: 12` 与 Wilson 半宽混用了，规格 §3.2 已拆成两个指标。

状态：草案（待 S 评审）。基线 master `906d98f`。
配套：`docs/roadmap/phase7-accuracy.md`（E0–E5）、`docs/roadmap/four-axes-mapping.md`（§三 现有评测）。

---

## 0 结论

1. 上一版 10 个节点缺的不是功能，是**归因**和**分辨率**：提示词没有单一来源也没有指纹，所以分数变了说不出是谁变的；25 题的信赖区间是 ±11pp，所以门禁只能防灾难，不能证明改进。
2. 与 star 前三比，datachat 的护城河恰恰是这套闸门（四家里只有 WrenAI 有一个 `evals/` 目录，内容是单功能 A/B），但**数据面**差一个量级：1 种 CSV 对 40+ 数据源、Excel 完全不支持。
3. 现在值得补的技术只有三件：**Excel/多表**、**口径库（语义层）**、**图表语义校验**。其余（MCP、结构化输出、向量词典、模型路由、WASM 沙箱）现在做是负债。

---

## 1 十二个洞

按严重度排。每条：证据 → 后果 → 修法。

### D1 提示词没有单一来源，也没有指纹（最严重）

- 证据：`app/react_agent.py:222` 一段内联字符串起头，`app/nodes/planner.py:3` 另一段；全仓 `grep PROMPT_VERSION|prompt_sha` 零命中。`app/eval/report.py:107-124` 的 `run_metadata` 只记 `model / temperature / base_url_host / pandas / python / data_sha256`，`report.py:311-314` 只额外记 `git_sha` 和 `evalset.sha256`。
- 后果：两份报告可以 `evalset.sha256` 完全相同、`git_sha` 相差 3 个 commit、分数差 4 题，而**你无法判断是提示词、是模型、还是网关**。m13 的基线是 10-14 的 `cdaf0f6`/`9430354`，中间隔了阶段 4 和 B20——DEVLOG [24] 自己写了"不是单变量对照"，但系统里没有任何机制阻止继续这么比。
- 修法：`prompt_fingerprint()`，哈希这五样：react system 串、`CHART_GUIDE`、planner/reviewer 模板、工具 description、字典渲染模板。写进 `meta`，报告头打印。两份报告 `prompt_sha` 不同 → `comparable=false`，`--verdict` 拒绝出结论。

### D2 25 题的分辨率是 ±11pp

- 数：23/25 = 92%，Wilson 95% 区间 **[75.0%, 97.8%]**；21/25 = 84%，区间 **[65.3%, 93.6%]**。
- 配对比较（McNemar 精确检验）的最低可检出量：6:0 翻转 p=0.031（显著），5:0 是 p=0.063（不显著），8:1 是 p=0.039，12:4 是 p=0.077（不显著）。
- 且 workflow 的 `allowed_fail` 有 4 题，**有效判定只有 21 题**。
- 后果：门禁抓不住 1–5 题的变化，而过去三个月的改进（B69/B70、nudge、CHART_GUIDE）量级正是"1–3 题"。所以"闸门无回归"这句话的信息量，比看起来小得多。
- 修法：报告里直接打 CI 和 MDE；`verdict` 增加 `resolution: {n: 25, wilson: [0.75, 0.98], mde_pp: 12}`。**门禁的职责重定义为护栏**，改进的证明交给 pass^k（C3）和 failure_class 分布（D2 层）。

### D3 宽容阶梯会吞掉回归

- 证据：`app/eval/comparator.py:112-140` 五级 `strict / rounded / scaled / extras / relaxed`；`runner.py` 的 `score_detail` 命中任一级即 `correct=True`。
- 后果：模型从 strict 退化到 relaxed，准确率 100% 不变，实际可靠性掉了。这是整条链路上**最安静的回归通道**——分数不动，用户开始骂。
- 修法：报告增加 `strict_rate` 与 `tier_mix`；对 `relaxed + extras` 占比设警戒线（建议 >15% 报警）；`--verdict` 把 strict 率下降单列一行，不混进 accuracy。

### D4 多轮零覆盖

- 证据：`ALL_CASES` 130 条的字段是 `id/category/question/ground_truth/keywords/has_chart/ordered/percent_equiv/dataset/expect_refusal/alt_ground_truths`——**没有 turns、没有 history**。而 `service.py:46-60` 的 `analyze()` 收 `history`，`:342` 有 `history_messages`，DEVLOG [29] 写着 B70 的 nudge 对 `history` 豁免。
- 后果：产品是多轮，评测是单轮。四类多轮失效全部无覆盖：指代（"这张表""它的占比"）、口径继承（第一轮定了"只算已付款"，第三轮没继承）、纠正（"不是这个意思，我要按门店"）、超窗（第 11 轮历史被 10 轮窗口截断）。而 nudge 豁免意味着多轮更容易"不执行就收尾"。
- 修法：`EvalCase.turns: list[str]`，gold 只算最后一轮，另加 `assert_turns`（每轮是否执行、是否继承了指定过滤）。先写 8 条。

### D5 只有"答案对错"，没有"数据形态"维度

- 证据：已登记的失败几乎全是数据病理——s02/s12 缺失哨兵、s04 合计行、s09 取消单未冲减（`thresholds.json` 的 `why`）。三类都不是推理错误。
- 后果：130 题都在干净数据上。模型在合成表上 92%，遇到用户真实的合并表头、两行表头、合计小计、文本数字、`20240101` 日期、全角括号就崩，而评测一个字都测不到。
- 修法：**脏数据语料**。同一份逻辑数据产出 N 个形态变体（合并表头 / 两行表头 / 合计行 / 千分位字符串 / 百分比字符串 / 日期三形态 / 重复列名 / 空列 / 表尾备注），gold 用清洗后数据算——改形态不改答案，天然可比。

### D6 扰动没有度量

- 修法：对同一题做四种变换（列名改中文别名 / 列顺序打乱 / 加空格与全角 / 单位改万元），测通过率衰减曲线。这就是"脆弱度"指标，比"再加 20 道新题"更能预测真实体验。

### D7 图表只验"有没有"，不验"对不对"

- 证据：`app/eval/chart_smoke.py` 全文只统计 `drew / options / pngs / chart_errors`；`_PLT` 是正则猜"有没有调 plt"。
- 后果：图可以又漂亮又错——y 轴取错列、饼图漏掉"其他"、堆叠把总和算成均值、类目少一个。matplotlib 那条连验证都不可能（只有 PNG）。
- 修法：`chart_check.py`，从 option 里读 `series.data` **反算**：bar 高度 vs gold 聚合值、pie 扇区和 vs 总计、类目集合 ⊆ 列值域、系列数 = groupby 组数、轴标题单位。matplotlib 单列"不可验证"，不计入通过率。这条比加 20 道题有用。

### D8 证据维度只有字符串匹配

- 证据：`unverified_numbers` 在 service 里做集合比对（数字是否出现在执行结果里）。
- 缺口：跨工件一致性（答案的数字 = 表格的数字 = 图的数字）、单位（万元/元）、时间范围（说"本季度"是否真的只筛了本季度）、因果措辞（"因为 A 所以 B"里 A 根本不在数据里）。
- 修法：`consistency.py` 三条断言：answer↔result 数值集合、chart↔result 聚合值、question 的时间词↔代码里的过滤条件。

### D9 有重复跑，但没有"每题翻转台账"

- 证据：`run_eval.py:79` 有 `--repeat`，`:196` 的 `_print_repeat` 出 `mean/min/max/stdev`（10-09 的 `eval_workflow_*_summary.json` 就是它产的，那批 stdev=0.0）。但 `scripts/gate/run_gate.py` **没有** `--repeat`，只有"名单外错题复跑 3 次 + 人工签字"（`:333`）。
- 后果：波动只有聚合标准差，没有"哪几题在翻"。所以 `allowed_fail` 只能靠人肉发现，m09/m10 是靠一次事故才被记下来的。
- 修法：`--repeat` 落到 gate，产出**逐题翻转率**；翻转率进 `thresholds.json`，作为 D12 名单管理的输入。

### D10 没有漂移哨兵

- 证据：`meta` 只有 `model` 字符串和 `base_url_host`。
- 后果：网关把模型静默升级/降级，代码零改动，分数漂移，你会去改提示词。
- 修法：canary 5 题 + `usage` 四元组指纹（in/out/cache/reasoning 的比例），每周跑一次，变了标 `drift=true` 并冻结基线。

### D11 没有数据出境审计

- 证据：`app/tools/schema.py` 采样 3 行、列名 64 字、单元格 40 字；`react_agent.py` 的 print 上限 2000 字、result 3000 字/60 行。但没有任何测试断言"发出去的请求体里不含全表"。
- 后果：这是本地化产品的核心承诺，靠人读代码守不住，一次改动就可能把整列塞进提示词。
- 修法：拦截层 dump 每次请求体，断言：样本行 ≤ N、单值 ≤ 40 字、不含未采样列的全量值、路径不含用户名。既是隐私证据，也是回归门禁。

### D12 `allowed_fail` 是只增不减的棘轮

- 证据：`thresholds.json` 的规则是"改门槛只能新增 profile，不改旧的"；m13 名单 react 2 题、workflow 4 题。
- 后果：每遇到一道会翻的题就往名单里加一条，半年后名单覆盖一半题，门禁形同虚设，而且没人记得每一条为什么在里面。
- 修法：每条带 `expires`（profile 版本）和 `flip_rate`（来自 D9）；翻转率 >40% 的题**移出闸门**进"稳定性专项"；名单总长设上限（≤20% 题量），超了就必须退役旧题。

---

## 2 四层 20 节点

| 层 | 节点 | 输入 | 输出 | 落点 | 验收 |
|---|---|---|---|---|---|
| A 可复现 | A1 用例与数据治理 | 题面、gold 脚本、许可证 | 冻结 sha256、私测集、污染隔离 | `docs/eval/` `scripts/holdout/` | 冻结 sha256 进 DEVLOG |
| | A2 执行器 | 用例 × 配置 | 报告 JSON | `run_eval.py` | `--repeat` 落到 gate |
| | A3 指纹 | 代码/提示词/模型/数据/依赖 | `fingerprints` 段 | `report.py` | 两份报告可比性自动判定 |
| | A4 Trace | 事件流 | `step_index / call_purpose / tokens_per_call` | `result.py:17` `Step` | 回放 13 份旧报告不报错 |
| B 测量 | B1 结果 | result + gold | `correct / strict_rate / tier_mix` | `runner.py` | 旧报告可 rescore 出 strict 率 |
| | B2 过程 | steps | 步数、无效调用、错误恢复、nudge | `app/eval/trajectory.py`（新） | 与人工判定的相关系数 |
| | B3 图表语义 | option + gold | 5 条反算断言 | `chart_check.py`（新） | 人造错误图能被抓出 |
| | B4 证据一致性 | answer/table/chart | 3 条断言 | `consistency.py`（新） | 单位/时间范围错配能抓 |
| | B5 多轮 | turns | 最后一轮对错 + 继承断言 | `cases.py` | 8 条用例 |
| | B6 扰动 | 变体数据 | 衰减曲线 | `scripts/perturb.py`（新） | 4 种变换 × 20 题 |
| | B7 负向 | 拒答/澄清/不可能 | 三分类准确率 | `cases.py` | 9 拒答 + 6 澄清 + 4 不可能 |
| | B8 judge | 答案+rubric | 二元 + 理由 | `app/eval/judge.py`（新） | 与人工一致率 ≥90%、κ ≥0.7 |
| | B9 注入 | 固定对抗语料 | 命中率 | `f3-inject` 上移 | 每次发布必跑 |
| | B10 出境审计 | 请求体 | 越界告警 | `tests/test_egress.py`（新） | 4 条断言 |
| C 统计 | C1 方差地板 | k 次重复 | 逐题翻转率 | `report.py` | 10 题 × 5 次 |
| | C2 区间与检验 | 两次报告 | Wilson / McNemar / bootstrap | `app/eval/stats.py`（新） | 手算对得上 |
| | C3 稳定性 | k 次独立 | pass@1 / pass^k | `run_gate.py --repeat` | 5 题实测缓存被打破 |
| | C4 门禁分层 | 触发场景 | PR 冒烟 8 / nightly 25 / release 130 | `.github/workflows/` | 三档都能跑 |
| | C5 成本与延迟 | usage/timings | p50/p95、每正确回答成本 | `report.py` | 跨报告可比 |
| D 运营 | D1 报告分层 | 原始行 | 概览/用例/单题/稳定性/执行 | `report.py` | 一份 MD 能按角色读 |
| | D2 失败归因路由 | `failure_class` | 文件:行 + owner | `docs/eval/failure-map.md` | 每类指向具体模块 |
| | D3 生命周期 | 翻转率/毕业 | 新增/退役/毕业 | `docs/eval/` 清单 | 5 题完成毕业 |
| | D4 反馈回流 | 👎 + trace | 草稿用例 | `scripts/draft_case.py`（新） | 一键出一条 |
| | D5 漂移哨兵 | canary | drift 标记 | `.github/workflows/` | 模型换版能报 |

**与上一版 10 节点的映射**（避免两个真相）：原 N0→A1、N1→A2、N2→A4、N3→B8、N4→B1/B2/B3/B4、N5→C3、N6→C5、N7→D1、N8→C4、N9→D2、N10→D3。新增：A3、B5、B6、B7、B9、B10、C1、C2、D4、D5。

---

## 3 统计：25 题到底能判什么

| n | 观测 | Wilson 95% | 含义 |
|---|---|---|---|
| 25 | 23 对 (92%) | 75.0–97.8 | ±11.4pp |
| 25 | 21 对 (84%) | 65.3–93.6 | ±14.1pp |
| 130 | 117 对 (90%) | 83.6–94.1 | ±5.3pp |
| 40 | 36 对 (90%) | 76.9–96.0 | ±9.6pp |

McNemar（同一批题、两次配置、只看翻转的）：

| 单向翻转 : 反向 | 双侧 p | 判读 |
|---|---|---|
| 6 : 0 | 0.031 | 显著 |
| 5 : 0 | 0.063 | 不显著 |
| 8 : 1 | 0.039 | 显著 |
| 10 : 2 | 0.039 | 显著 |
| 12 : 4 | 0.077 | 不显著 |

结论三条：

1. **25 题门禁的最低可检出量约 6 题单向翻转。** 1–5 题的变化在统计上与噪声不可区分，无论 `verdict` 写得多肯定。
2. **想测 5pp 的改进，至少需要 130 题量级。** 所以阶段 7 的 H1（40 题）也只能测 10pp 级别的变化，`pass^k` 和 `failure_class` 分布必须同时上报。
3. **`allowed_fail` 里 2 题天然会翻**，这已经吃掉了检测力的一大半。门禁的真实作用变成"防止 ≥6 题的灾难性回归"，这个定位要写进 `phase7` §4，否则每次 1 题差异都要开会。

---

## 4 与 star 前三的对照（2026-10-27 实测）

| 项目 | star | 最后 push | 形态 | 它有的 | 它没有的 |
|---|---|---|---|---|---|
| openinterpreter/openinterpreter | 68,694 | 2026-10-11 | 终端编码 agent | Rust harness、按廉价模型调优 | README 第一句已改成"A coding agent optimized for low-cost models"——**已经不是数据分析产品** |
| Chat2DB/Chat2DB | 28,341 | 2026-10-27 | 数据库客户端 | 40+ 数据源、SQL 工作台、本地优先、自带模型 | 不做统计分析、不出图、无评测门禁 |
| sinaptik-ai/pandas-ai | 23,905 | 2025-10-28 | Python 库 | 多 LLM、CSV/parquet/SQL | Python 3.8–3.11（**不支持 3.12**）、无桌面壳、无沙箱门禁 |
| vanna-ai/vanna | 23,811 | 2026-02-02 | RAG text-to-SQL | `train()` 把成功 SQL 回灌检索 | **停更 8 个月** |
| eosphoros-ai/DB-GPT | 20,201 | 2026-10-27 | Agentic 数据助手 | 多源、AWEL、微调 | 部署重，非单机产品 |
| Canner/WrenAI | 17,986 | 2026-10-27 | GenBI 语义层 | MDL 语义层、22+ 源、面向 MCP 客户端 | `evals/` 只有 `spodbtify_ab` 一个单功能 A/B |

**四家（pandas-ai / vanna / openinterpreter / Chat2DB）只有 `tests/`，没有准确率门禁。** datachat 的"冻结题 + 独立 gold 脚本 + thresholds profile + 人工签字 + 复跑规则"在开源同类里没有等价物。这是真护城河，不是自嗨。

反过来，差距也很硬：

| 维度 | datachat | 对标最好的一家 |
|---|---|---|
| 数据源 | **1 种：CSV**（`dataset.py:10` 明写"不做 DuckDB；不支持 Excel"） | Chat2DB 40+，WrenAI 22+ |
| Excel | 不支持 | 全部支持 |
| SQL | 无 | Chat2DB / WrenAI / vanna |
| 语义层/口径 | 无 | WrenAI MDL |
| 检索训练闭环 | 无（👍👎 只存不学） | vanna `train()` |
| 多表 join | 无（`ALL_CASES` 连 `multi_table` 字段都没有） | 都有 |
| 可复现准确率门禁 | **有** | 无 |
| 注入量化 | **有（9%/18% 实测）** | 无 |
| 桌面壳 + 钥匙串 + Job Object 沙箱 | **有** | Chat2DB 有壳无沙箱 |

一句不客气的话：**star 数跟严谨度无关，跟"能接多少数据"强相关。** 要用户，先补 Excel 和 SQL；要留存，才轮到评测。这两件事不冲突，但顺序反了就是给空气做质检。

---

## 5 技术扩写十项

按"现在做 / 缓做 / 不做"分，每项写清代价和评测含义。

### T1 Excel / 多 sheet / 多表 —— 现在做（最高优先）

- 理由：Windows 桌面产品 + 中文办公场景，xlsx 是默认格式。现在只收 `.csv`（`ui/web/src/views/Shell.tsx:318` 与 `:428` 两处 `accept=".csv"`）。
- 代价：合并单元格、两行表头、合计行、多 sheet 映射成多表。`openpyxl` 已在 CI 依赖里（`build_gate_data.py` 用它），不新增安装包体积。
- 评测含义：直接激活 D5（脏数据语料）和 B5（多表 join 用例），并把"表头识别"变成一等公民。
- 风险：pandas 3.0 的 `read_excel` 在 50 万行上比 CSV 慢一个量级，要加行数上限和进度反馈。

### T2 口径库（语义层）—— 现在做（第二优先）

- 理由：m10/B63"自拟利润口径"**不是提示词问题**，是定义问题。提示词再改也压不住，因为模型不知道这家公司的"利润"是什么。
- 形态：每数据集一份 `metrics.json`：`name / formula / unit / synonyms / owner / note`。进字典检索，进提示词，UI 里可编辑，"查看过程"里显示本次用了哪条口径。
- 代价：一张表 + 检索 + 注入 + 一个面板，2–3 天。
- 评测含义：新维度"口径服从率"——给了定义就必须用，没给就按通行定义或拒答。这比再加 20 道聚合题更能降错。
- 与 D4 的关系：口径也解决一半多轮问题（第一轮定的口径可以被后续轮继承）。

### T3 DuckDB 作为「工具」而不是「产品」—— Excel 之后

- 理由：多表 join、超内存数据、确定的查询计划（对评测友好）。
- 形态：沙箱里给一个 `sql(q)`，或 `duckdb.sql(q).df()`，**不放第二个 agent**。
- 代价：多一条执行面，评测矩阵翻倍；SQL 报错是新的失败类。
- 判断：如果 T1 做完多表需求被 pandas merge 满足了 80%，T3 可以再等。

### T4 schema linking（轻量）—— 现在可做，但要先量

- 现状：字典是 BM25 + jieba（`app/tools/dictionary.py:1`），同义词弱（"销售额" vs "营收"）。
- 做法：一次廉价调用把问题映射到候选列，结果缓存到会话。**不引入 embedding 模型**——bge-m3 一类要往安装包里塞 300MB+，桌面产品付不起。
- 验收：在 D6 的扰动集上比 BM25 的召回，提升 <5pp 就不做。

### T5 图表语义校验 —— 现在做（属评测，不是产品）

见 D7。这是唯一一条"只花 1 天、直接提高可信度"的改动。

### T6 结构化输出 / 约束解码 —— 缓

- 现状：模型写 Python，`chart()` 事后校验，错就 `ChartError`（永不抛异常，B44）。
- 触发条件：**先看 13 份报告里 `chart_errors` 的实际占比**。>5% 再考虑给 `render_chart(spec)` 加 JSON Schema 约束；<5% 就是过度工程。

### T7 MCP 出口 —— 缓

- 理由：生态确实往这走（WrenAI 明确定位 MCP 客户端）。但 datachat 的价值在 UI 和可解释性，做成 MCP 服务等于把自己降级成一个取数后端。
- 好消息：现在的工具面很干净（一个 `run_python_on_data` + 一个 `chart()` 注入），将来要包一层 MCP server 是 1 天的事，不用提前设计。

### T8 模型路由 + 提示缓存 —— 缓

- 理由：简单题（单表、无图）走小模型，失败升级，能省 40–60%。
- 为什么缓：路由一上，评测必须按路由归因，否则准确率混在一起没法解释。等 A3 指纹 + C5 成本先落地。

### T9 推理轨迹留存 —— 做开关，默认关

- 现状：只记 `tokens_reasoning`，不存文本。
- 价值：轨迹评分（B2）、失败诊断（"它读错了哪一列"）、注入检测。
- 代价：隐私。默认关，开启时明确写"存在本机 sqlite，可一键清空"。

### T10 反馈回流 —— 做

- 现状：👍👎 只存（`feedback` 表），不进评测。
- 做法：👎 → 打包 trace → 生成草稿用例（问题 + 实际结果 + 待填 gold）→ 人工确认 → 入集。
- 这是唯一能防止评测集老化的机制。vanna 用 `train()` 做类似的事，方向对但目标不同（它改检索，我们改题集）。

---

## 6 明确不做

| 不做 | 理由 |
|---|---|
| WASM / Pyodide 沙箱 | pandas 3 在 Pyodide 上启动慢、包大；现有 subprocess + Job Object + import 白名单已经过了三类逃逸测试 |
| 多 Agent（Router/Worker） | M13 §3.2 已定；单表场景没有可并行的子任务，加了只是多一次调用 |
| 100 分负分制 | 题目是数值/表格，布尔 + 一票否决更诚实；扣 10 分只是把布尔伪装成连续值 |
| LLM-judge 打总分 | judge 只做二元判定 + 理由，打分不可校准 |
| BIRD / Spider 进 CI | 许可证、体积、场景不匹配（单表 CSV vs 多库 schema）；只作外部校准，一季一次 |
| 向量词典进安装包 | 300MB+ 换 <5pp 召回，不划算 |
| Tableau 风色板 | 10-20 已否决（PALETTE 第三色与 WCAG 的账算过） |

---

## 7 分批与验收

### 批 0（离线，1–2 天，不花 token）

A3 指纹 + B1 `strict_rate` + D1 报告分层 + D7 图表语义 + C1 台账骨架。

验收：**回放 13 份 `docs/eval/gate_*.json`**，跑出新格式，`prompt_sha` 为空时标 `legacy`，strict 率与人工判定不矛盾。全程不调模型。

### 批 1（离线，2–3 天，不花 token）

B5 多轮 8 条 + D5 脏数据 12 条 + D6 扰动 + B7 澄清 6 条 + D11 出境审计 4 条 + C4 分层门禁。

验收：`--oracle` 全绿；假模型能跑通三档门禁；出境审计在故意放宽采样时变红。

### 批 2（要 Key，一次性）

A1 建 H1（40 题，含 ≥1/3 盲题）→ C2 统计 + C3 pass^3 → B8 judge 校准（要第二家 Key）→ D5 canary。

验收：H1 基线报告带 CI 和 MDE；pass^3 与 pass@1 同时上报；judge 与人工 κ ≥0.7 才启用。

### 批 3（产品，与评测并行）

T1 Excel → T2 口径库 →（视需要）T3 DuckDB。

验收：新格式用例 ≥12 条，其中 4 条是合并表头/合计行。

---

## 8 这套系统测不出来的

- **用户信不信。** 只能 F5 人眼 + 后续留存。any 指标都替代不了。
- **<6 题的改进。** 25 题的天花板，写在这里省得以后吵。
- **长尾语义题。** "这个月表现怎么样"没有唯一答案，只能 rubric，rubric 就只能 judge，judge 就只能是概率。
- **跨表因果。** "为什么下滑"需要外部信息，评测只能测"有没有指出可疑因素"，不能测"对不对"。
- **提示词的边际收益。** 当改进落到 1–2 题时，你已经分不清是提示词、模型波动，还是那天的网关。

---

## 9 需要 S 定的三件事

1. **H1 跑 k=1 还是 k=3**：k=1 约 230 万 token，k=3 约 700 万（上一版只算了 230 万，是缺口）。只对 react 做 k=3 可以压到 350 万。
2. **LLM-judge 做不做**：做就要第二家模型家族的 Key，否则 B8 空着，Evidence 只剩字符串匹配。
3. **Excel 现在做还是等阶段 8**：这是唯一一条"做了就扩大用户面"的改动，和评测不冲突，但会占 3–5 天。
