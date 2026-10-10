# DataChat 开发日志（DEVLOG）

> 规则：每完成一个阶段或一次重要提交，追加一条记录。每条必须有基线 commit SHA，问题必须定位到 `文件:行` 或函数名，并与上一条逐项对照。
> 目标（2026-10-09 定）：做成产品。先做桌面客户端（用户自填 API Key），Web 服务器上线后续再做；不用 Streamlit，按目标架构实现。

## 记录模板
```
## [序号] YYYY-MM-DD · 阶段名 · commit <SHA>
### 当前技术栈
### 本次完成（对照上一条）
| 上一条的问题编号 | 状态 | 怎么解决的 / 证据（文件:行、测试名、评测数字） |
### 当前已知问题
| 编号 | 严重度 | 位置 | 描述 | 计划在哪个阶段解决 |
### 指标快照（评测集版本、准确率、平均耗时、平均 token）
### 下一步
```

---

## [0] 2026-10-09 · 基线 · commit 4e67c92（origin/master）
注：本地另有未推送提交 2f67936（2026-06-26），推送后在 [1] 中核对。

### 当前技术栈
Python · LangGraph（StateGraph 工作流版 + create_react_agent ReAct 版）· langchain-openai → DeepSeek · pandas · matplotlib · jieba + rank_bm25 · Streamlit（2 个 UI）· 本地文件持久化（outputs/、runs.jsonl）

### 当前已知问题
| 编号 | 严重度 | 位置 | 描述 | 计划阶段 |
|---|---|---|---|---|
| B01 | P0 | app/tools/sandbox.py run_code | 同进程 exec，可经 pd.io.common.os 执行 shell、读环境变量（含 API Key）、任意写文件、__subclasses__ 拿 Popen | 2 |
| B02 | P0 | sandbox.py 线程 join | 超时杀不掉线程，无内存上限 | 2 |
| B03 | P1 | sandbox.py 猴补丁 plt.savefig | 全局状态，并发互踩；恢复不完整（2f67936 声称已修） | 1/2 |
| B04 | P1 | schema.py / dictionary.py augment_question | prompt 注入入口；字典拼进 question 污染下游 | 1 |
| B05 | P1 | graph.py _route_after_exec | 只修报错不修答错，无结果合理性校验 | 7 |
| B06 | P1 | nodes/reviewer.py | prompt 缺 plan 与 CHART_GUIDE | 1 |
| B07 | P1 | nodes/executor.py:12 | str(result)[:3000] 丢结构化结果 → summarizer 截断、runner 双重执行 | 1 |
| B08 | P1 | nodes/summarizer.py | chart_note 硬编码 outputs/chart.png（2f67936 声称已修） | 1 |
| B09 | P1 | schema.py | 无枚举值/范围/空值率 | 7 |
| B10 | P1 | app/llm.py | 未显式配置超时与重试（库默认 max_retries=2），无 token 统计；ReAct 无 recursion_limit | 1 |
| B11 | P2 | eval/report.py:31-34, :40 | 正确率分母只算 executed（虚高）；无报错修复率记 100% | 1 |
| B12 | P2 | eval/comparator.py _normalize_obj | Series 转 dict 比较忽略顺序（虚高）；答案形态不一致（虚低） | 1 |
| B13 | P2 | eval/runner.py | 只测工作流版；双重执行；无耗时/token | 3 |
| B14 | P2 | ui/streamlit_app.py | 未接字典 RAG，与 README 不符 | 1（随 Streamlit 下线） |
| B15 | P2 | tools/csv_io.py | latin-1 兜底静默乱码 | 1 |
| B16 | P2 | 4 个入口 | 各自装配流程，无服务层 | 1 |
| B17 | P2 | requirements.txt | 未锁版本；无测试、CI、日志框架 | 0 |
| B18 | P1 | ui/chat_app.py | 无身份与持久化；临时文件不清理；记忆在进程内存 | 4 |

### 指标快照
50 题 / 60 行单表；未在新口径下跑过，暂无可信数字。

### 下一步
阶段 0：推送 2f67936 → 锁依赖 → pytest 骨架 → 更新本日志 [1]。

---

## [1] 2026-10-09 · 阶段 0 基线对齐 · commit 6c2b1e2
注：2f67936 仍未推送，本条暂不含它；推送后 rebase 并核对 B03/B08。
补记（阶段 1 时核对）：2f67936 已在合并提交 7fa1f75 并入 master。核对结果——
- B08 已解决：nodes/summarizer.py 用 state 里的 chart_path 生成图表说明，不再硬编码 outputs/chart.png。
- B03 部分解决：sandbox.py 把 plt.savefig 的恢复移进 finally，所有返回路径（成功/报错/超时）都会恢复；
  但"全局猴补丁 + 并发互踩"和"超时后线程继续运行"仍在，留到阶段 2 子进程沙箱。

### 当前技术栈
与 [0] 相同；新增 pytest 9.1.1。依赖锁定：Python 3.12、pandas 3.0.6、langgraph 1.2.14、langchain-openai 1.7.0、openai 3.26.1（完整列表见 requirements.txt）。

### 本次完成（对照 [0]）
| 问题 | 状态 | 证据 |
|---|---|---|
| B17 | 部分解决 | requirements.txt 全部锁版本；新增 requirements-dev.txt、pytest.ini；tests/ 共 81 项：73 通过、8 项以 xfail(strict) 登记已知问题。CI 与日志框架留到阶段 3 |
| B01 | 已登记 | tests/test_sandbox.py::test_escape_blocked（3 种逃逸）、test_file_write_blocked |
| B11 | 已登记 | tests/test_eval_cases.py 两项 xfail |
| B12 | 已登记 | tests/test_comparator.py::test_ranked_list_order_matters |
| B15 | 已登记 | tests/test_csv_io.py::test_undecodable_file_raises |
| B03 | 待核对 | 基线上 test_savefig_restored_after_error 已通过（异常路径能恢复 savefig）。2f67936 修的是哪条路径，需推送后对照 |

xfail 用 strict 模式：问题一旦修好，对应测试会"意外通过"并报错，提醒删掉标记，问题状态因此无法虚报。

### 新发现
| 编号 | 严重度 | 位置 | 描述 | 计划阶段 |
|---|---|---|---|---|
| B19 | P2 | app/tools/schema.py | pandas 3 把字符串列 dtype 显示为 `str`（pandas 2 为 `object`），喂给模型的 schema 文本随环境变化；锁版本后已固定 | 1（schema 重写时显式归一类型名） |

### 指标快照
50 道 ground truth 在 pandas 3.0.6 下全部可执行，且与自身比较相等。尚未跑 LLM 评测（需 DeepSeek Key）。

### 下一步
推送 2f67936 → rebase → 补全本条 SHA → 进入阶段 1（core/analyze() 服务层）。

---

## [2] 2026-10-09 · 阶段 1 内核重构 · commit b6568b9
基线：7fa1f75（含 6c2b1e2 与 2f67936）。

### 当前技术栈
与 [1] 相同，新增内核包 `app/core/`（放在 app 包内而不是顶层 core/：现有代码全部以 `app.*` 导入，不需要改导入方式）：
- `service.py` `analyze(dataset, question, *, agent="workflow"|"react", llm_config=None, chat_model=None, max_attempts=3, exec_timeout=20, recursion_limit=12, use_dictionary=True, memory=None, thread_id=None, encoding=None, log=False) -> AnalysisResult`
- `result.py` `AnalysisResult`：agent / dataset / question / answer / result（原始对象）/ result_text / code / chart_path / charts / plan / field_notes / attempts / initial_error / executed / error / error_kind（dataset｜llm｜execution｜agent）/ steps（Step 列表）/ timings / usage（TokenUsage），`to_record()` 可 JSON 序列化
- `llm.py` `LLMConfig`（timeout / max_retries / 退避参数，可由环境变量 DATACHAT_LLM_TIMEOUT、DATACHAT_LLM_MAX_RETRIES 覆盖）、`LLMClient`、`LLMError`、`UsageTracker`
- `testing.py` 脚本化假模型 `ScriptedChatModel` 与 `oracle_model`（单测与 `run_eval.py --oracle` 共用）

依赖：运行依赖无新增；requirements-dev.txt 显式锁定 httpx2==2.13.1（openai 的传输层依赖，测试直接导入它构造异常）。没有引入 charset-normalizer，原因见 B15。

### 本次完成（对照 [1]）
| 问题 | 状态 | 证据 |
|---|---|---|
| B16 | 已解决 | run.py:26、run_react.py:26、ui/streamlit_app.py:40、ui/chat_app.py:72、app/eval/runner.py:61（run_eval.py 经 runner）全部调用 `analyze()`；tests/test_entrypoints.py::test_cli_routes_through_analyze、::test_run_eval_oracle_cli，tests/test_ui_smoke.py::test_chat_app_turn_goes_through_analyze |
| B14 | 已解决 | Streamlit 单轮页经 analyze()，自动走字典检索，并新增可选的 .dict.csv 上传（ui/streamlit_app.py）；tests/test_ui_smoke.py::test_page_renders |
| B07 | 已解决 | nodes/executor.py:23-24 保留结构化 result，另生成 result_text；core/result.py format_result 超长时写明"共 N 行，仅显示前/后若干行"；评测直接用 analyze 的 result 打分，不再重跑（tests/test_eval_cases.py::test_no_double_execution：每题只执行 2 次 = ground truth + 模型代码）；数据表在 analyze 中只读一次，经 RunnableConfig 注入执行节点 |
| B10 | 已解决 | core/llm.py：build_chat_model 显式传 timeout（默认 60 秒）；工作流版 LLMClient.invoke_message 自己重试（只重试超时/连接/限流/5xx，指数退避 + 抖动，上限 backoff_max），鉴权/参数错误不重试；ReAct 版把同一份配置的 max_retries 交给 openai SDK（create_react_agent 不接受 RunnableRetry 包装）；token 由 usage_metadata 累计（ReAct 经回调 UsageCallbackHandler）；ReAct 默认 recursion_limit=12，超限返回 error_kind="agent"。测试：tests/test_llm.py（14 项，含退避序列 [1,2]、封顶、用尽重试、401 不重试）、tests/test_core_analyze.py::test_workflow_llm_timeout_is_captured_not_raised、::test_react_recursion_limit。另用无效 Key 实测真实 DeepSeek 接口：401 被归类为 auth、只尝试 1 次 |
| B11 | 已解决 | eval/report.py:50 正确率分母 = 全部题；:54 条件正确率单独列出并标注；:59 无初始报错时修复率为 None（显示 N/A）；:38 空分类不再退回全部题；另计基础设施失败数、平均耗时、平均 token。tests/test_eval_cases.py::test_correctness_rate_uses_all_cases、::test_fix_rate_undefined_without_errors、::test_empty_category_not_fallback_to_all、::test_infra_failure_counted_separately（已删 xfail） |
| B12 | 已解决（规则范围内） | eval/comparator.py 重写：顺序由 EvalCase.ordered 显式决定（filt_002、filt_007、ts_006 为 True），未给出时按 expected 索引是否被排过序推断；7 条答案形态归一规则写在文件头。tests/test_comparator.py::test_ranked_list_order_matters（已删 xfail）；tests/test_comparator_cases.py 在真实用例上跑 17 种"写法不同但正确"和 8 种"错误"答案，新比较器 25/25 判对；同一组答案旧比较器误判 14 个（12 个正确答案判错 → 虚低，2 个顺序错误判对 → 虚高） |
| B06 | 已解决 | nodes/reviewer.py 的 prompt 增加分析计划（:40）、字段说明和 CHART_GUIDE（:43），并要求保留原有绘图；tests/test_workflow_mocked.py::test_reviewer_prompt_has_plan_and_chart_guide。traceback limit=3 仍在 sandbox.py，随阶段 2 重写 |
| B15 | 已解决 | tools/csv_io.py:33 detect_encoding：BOM → 严格 utf-8 → 严格 gb18030，都失败抛 CSVEncodingError，不再用 latin-1 兜底；可显式传 encoding。tests/test_csv_io.py::test_undecodable_file_raises（已删 xfail）等 12 项。没有用 charset-normalizer：实测短文件上它把坏字节判成 utf_16_be、把 GBK 判成 cp949（chaos 都是 0），猜错比报错更糟 |
| B04 | 部分解决 | 污染：question 保持原样，字典说明作为独立 field_notes 进 planner/codegen/reviewer 的 prompt（ReAct 放系统提示），`use_dictionary=False` 可关掉以单独衡量 RAG 增益；tests/test_core_analyze.py::test_question_not_polluted_by_dictionary、::test_dictionary_can_be_disabled。注入：schema 样例单元格截到 40 字、列名 64 字、字段说明 200 字，并包进"只是数据、不是指令"的分隔块（tools/schema.py:20、dictionary.py:74-81）；tests/test_schema.py::test_schema_wrapped_and_long_cells_clipped。这只是缓解，提示注入无法靠 prompt 根治，真正防线是阶段 2 的子进程沙箱 |
| B19 | 已解决 | tools/schema.py:30 dtype_name 把类型映射为 int/float/str/bool/datetime/category；tests/test_schema.py::test_dtype_names_stable_across_string_backends |
| B13 | 部分解决 | runner 可测两种 Agent（run_eval.py --agent react）、每题记耗时与 token、不再双重执行、--out 输出带 commit SHA 的 JSON 报告、--no-dict 关字典、--oracle 离线自检。评测集扩充与多表留到阶段 3 |
| B03 | 不变（部分解决） | 见 [1] 补记，阶段 2 |
| B01 B02 | 不变 | 阶段 2；tests/test_sandbox.py 4 项 xfail 仍在 |

其它改动：tests/test_sandbox.py::test_timeout_reported 的死循环改成约 2 秒的有限循环——B02 泄漏的线程会一直抢 GIL，原写法让排在后面的测试慢了约 10 倍（UI 冒烟测试从 1 秒变 15 秒）。测试产物改写到临时目录（tests/conftest.py 自动 fixture），不再污染 outputs/。

### 假设与判断
- `analyze()` 不对分析过程中的失败抛异常，而是写进 error / error_kind，方便评测把"基础设施失败"（llm、dataset）和"代码写错"（execution）分开统计；只有参数错误（未知 agent）抛 ValueError。
- ReAct 版的"最终结果"取最后一次执行成功的工具调用；模型没写代码就直接回答时 executed=False，评测记为未执行。
- 比较器的宽松规则（多带列也算对、(标签, 数值) 也算对等）是判断题意后定的。"百分比"题返回 0~1 的比例仍判错（tests/test_comparator_cases.py 中 corr_002），因为题目明确要百分比。
- token 统计依赖服务商在响应里返回 usage；DeepSeek 的 OpenAI 兼容接口会返回，但本次没有有效 Key，未用真实调用核对数字。

### 当前已知问题
| 编号 | 严重度 | 位置 | 描述 | 计划阶段 |
|---|---|---|---|---|
| B01 | P0 | tools/sandbox.py run_code | 同进程 exec 可逃逸（读环境变量里的 Key、执行 shell、写文件） | 2 |
| B02 | P0 | sandbox.py 线程 join | 超时杀不掉线程，无内存上限 | 2 |
| B03 | P1 | sandbox.py 猴补丁 plt.savefig | 恢复已完整；全局状态并发互踩仍在 | 2 |
| B04 | P1 | schema.py / dictionary.py | 污染已除；注入只做了截断 + 分隔块缓解 | 2（沙箱兜底）/ 7 |
| B05 | P1 | graph.py _route_after_exec | 只修报错不修答错 | 7 |
| B09 | P1 | schema.py | 无枚举值/范围/空值率 | 7 |
| B12 | P2 | eval/comparator.py | 7 条规则之外的答案形态（如季度写成 "Q2"、比例与百分比互换）仍判错，需人工抽检定量 | 3 |
| B13 | P2 | eval/cases.py | 50 题 / 60 行单表，难度偏低 | 3 |
| B17 | P2 | — | 无 CI、无日志框架（入口仍用 print） | 3 |
| B18 | P1 | ui/chat_app.py | 无身份与持久化；临时文件不清理；记忆在进程内存 | 4 |
| B20 | P2 | app/react_agent.py | langgraph 1.2 提示 create_react_agent 已弃用、2.0 移除，应迁移到 langchain.agents.create_agent（需新增 langchain 依赖） | 4 |
| B21 | P2 | core/llm.py ReAct 路径 | ReAct 的重试在 openai SDK 内部完成，usage.retries 记为 None；要统一计数需自写 Agent 循环或包装模型 | 4 |
| B22 | P2 | tools/csv_io.py | Big5（繁体）文件多数能被 gb18030 严格解码，会得到错字而不报错；需要用户显式指定编码，上传 API 要提供 encoding 参数 | 4 |
| B23 | P2 | — | 无限流、无模型降级、无单次分析的 token 预算上限 | 4 |

### 指标快照
- 测试：173 项 = 169 通过 + 4 xfail（均为 B01）。[1] 为 81 项 = 73 通过 + 8 xfail；本次删掉 4 个已修问题的 xfail（B11×2、B12、B15）。全部离线，不需要 API Key，fresh venv 按 requirements-dev.txt 安装后通过。
- 评测流水线自检（`run_eval.py --oracle`，模型输出 = 标准答案）：工作流版 50/50、ReAct 版 50/50 判对，修复率 N/A，基础设施失败 0。这只证明评测流水线和打分口径能跑通，**不代表 Agent 准确率**。
- 真实 LLM 基线：本次环境没有 DeepSeek Key，尚未跑出。

### 下一步
1. S 用自己的 Key 跑 `python run_eval.py` 和 `python run_eval.py --agent react`（各约 50 题，可加 `--no-dict` 对比字典增益），把带 SHA 的 JSON 报告数字补进本条，作为第一组可信基线；再人工抽检判错的题，确认是模型错还是比较器规则没覆盖。
2. 提交本阶段改动并回填本条 SHA。
3. 进入阶段 2：子进程沙箱（B01 B02 B03）。

## [3] 2026-10-09 · 阶段 1.5 评测校准 · commit b710e23
基线：91575c5（b6568b9 + numpy 2.4.6 兼容 Python 3.11 + [2] 回填 SHA）。起因：S 在本地用真实 DeepSeek Key 跑了阶段 1 的评测（报告见 docs/eval/），逐题复核发现严格正确率严重低估，评测本身先要修准，否则阶段 2 改沙箱时没有可信的回归指标。

### 当前技术栈
与 [2] 相同，无新增依赖。新增 `app/eval/rescore.py`；`run_eval.py` 新增 `--repeat N`、`--rescore REPORT`。

### 阶段 1 真实评测（S 本地，2026-10-09，50 题，data/sample_eval.csv）
| 报告 | Agent | 字典 | 严格正确率 | 聚合 | 过滤 | 关联 | 时序 | 执行成功 | 首次报错 | 平均耗时 | 平均 token |
|---|---|---|---|---|---|---|---|---|---|---|---|
| eval_workflow_20261009_142257 | workflow | 开 | 56% | 11/15 | 11/12 | 5/10 | 1/13 | 100% | 1 | 22.7 s | 5788 |
| eval_workflow_20261009_145029 | workflow | 关 | 58% | 14/15 | 11/12 | 3/10 | 1/13 | 100% | 4 | 24.2 s | 5957 |
| eval_react_20261009_142854 | react | 开 | 46% | 8/15 | 7/12 | 4/10 | 4/13 | 100% | 13 | 6.2 s | 6297 |

- eval_workflow_20261009_140017：50 题全部 401（Key 未配好），被正确归为基础设施失败（error_kind=llm），不计入。
- 三份报告的 git_sha 都是 unknown，模型名未记录（见 B27），所以这组数字只能当参考，不能当基线。
- 逐题人工复核（Hark 读输出判定，非独立评审）：workflow+字典 22 道判错里，18 道数值全对、只是形态不同，2 道是标准答案有问题，1 道理解分歧（corr_001 给占比），1 道口径分歧（agg_002 用加权均价）→ 人工口径约 46–48/50；无字典那次约 47/50。react 27 道判错里，形态误判 13，答案在结果里但没抽出来 5（返回整列排序），真错或不完整 9 → 约 36–41/50。
- 字典开/关差 2 个百分点，人工口径也持平；两次 workflow 运行之间有 4–5 题翻转，单次运行看不出字典增益。

### 本次完成（对照 [2]）
| 问题 | 状态 | 证据 |
|---|---|---|
| B24 | 已解决（规则范围内） | eval/comparator.py 新增规则 8–12（文件头逐条说明）：8 按值找（标签列, 数值列）还原 Series、表的列按值匹配，不看列名；9 期望元组时 N 行表任一列按序相等即对；10 期望数值时单行汇总（1 行表或 ≤3 项文字标签的 Series/dict）含该值即对；11 期望月份/季度序号时接受 '2024-05'、Period、'Q2'、'2024Q2'；12 只对问"占比"的题（EvalCase.percent_equiv：agg_009、corr_003）接受 ×100/÷100，问"百分比"的 corr_002 仍要求百分数。tests/test_comparator_cases.py 按阶段 1 模型的真实输出新增 16 种应判对的写法、7 种应判错的答案（合计应判对 33、应判错 15）（含"整列碰巧包含中位数""加权均价""件数 vs 占比"）；tests/test_comparator.py 中"列名不同即判错"的断言改为按值判断 |
| B25 | 已解决 | eval/cases.py 修 6 道标准答案：filt_003 去掉 drop_duplicates（题目问记录）；corr_003 groupby(group_keys=False) 去掉重复的 product 索引层；corr_007 改为先按产品×地区汇总再求标准差（题目是"在不同地区"）；corr_008、ts_009 去掉 astype(int)（原来把 .5 截掉）；ts_010 用 pct_change（题目是增长率，原来用 diff；本数据两者都是 5 月）。oracle 自检两种 Agent 仍 50/50 |
| B26 | 部分解决 | 报告每题存 answer（最终回答）与可还原的 expected_obj / actual_obj；`run_eval.py --rescore` 不调模型、按当前比较器和标准答案重新打分，并逐题列出变化（oracle 报告往返 50/50，tests/test_comparator_cases.py::test_dump_load_keeps_judgement 覆盖全部 48 种写法）。codegen / reviewer / ReAct 提示词加"结果契约"：result 必须直接回答问题（问哪个给标签、问多少给数值、问各…给分组结果、问哪些记录给行），不用中间表或整张排序表收尾——这也是以后前端渲染需要的约定。仍未做：react 的最终文字回答不参与打分 |
| B27 | 已解决 | eval/report.py git_sha 用 `git -C <仓库>`，git 不可用时直接读 .git/HEAD 与 refs，末尾加 "?" 表示没检查改动（tests/test_eval_cases.py::test_git_sha_without_git_binary）；报告记录模型、temperature、接口主机、Python/pandas 版本、数据文件 sha256 前 12 位，不记 Key（::test_report_metadata_records_model_and_data）；`--repeat N` 每次一份报告 + 汇总（均值、区间、标准差）（tests/test_entrypoints.py::test_run_eval_repeat_and_rescore_cli） |

### 新发现
| 编号 | 严重度 | 位置 | 描述 | 计划阶段 |
|---|---|---|---|---|
| B24 | P1 | eval/comparator.py | 规则 3 靠"列名 = 期望索引名"把表还原成 Series，模型改中文列名或多带列就判错；比例尺度、序号标签、元组 vs 两行表也不认。阶段 1 真实评测 workflow 22 道判错中 18 道属此类 | 1.5（本次） |
| B25 | P1 | eval/cases.py | 6 道标准答案有误或与题意不符（见上） | 1.5（本次） |
| B26 | P1 | eval/runner.py、react_agent.py | ReAct 打分取最后一次执行的 result，常是中间表；报告不存最终回答与结构化结果，比较器一改就得重新花钱跑 | 1.5 部分 / 3 |
| B27 | P2 | eval/report.py | git_sha 在 S 的 Windows conda 环境里为 unknown；不记录模型；每配置只跑 1 次 | 1.5（本次） |
| B28 | P1 | tools/sandbox.py | 沙箱 builtins 缺 `__import__`，pandas 内部延迟导入的方法（如 `pd.Timestamp.strftime`）报 KeyError，模型写的正常代码会失败；tests/test_sandbox.py::test_timestamp_strftime_works 以 xfail(strict) 登记 | 2 |

### 假设与判断
- 规则 8 只按值匹配列：单列表即使列名完全不同、值相同也判对。代价是理论上可能把"另一列碰巧同值"判对，60 行数据上概率可忽略；收益是不再因为中文列名误判。
- 规则 10 限定"单行/≤3 项"：更长的容器不放行，否则"返回整列"会碰巧包含答案（tests 里的 agg_013 反例：中位数 58043.0 恰好等于华北总额）。
- "答案在整列里但没抽出来"（react 返回各地区排序而不是"华南"）仍判错：产品要直接回答，靠结果契约解决，不靠比较器放宽。
- 新规则对阶段 1 那三份报告的影响无法直接重算（旧报告只存了 500 字文本预览）。按逐题复核估计，workflow+字典的 22 道里规则可覆盖约 16 道（agg_009 corr_002 corr_003 ts_001–007 ts_010 ts_011 ts_013 filt_003 corr_007），剩下的 agg_008（一句话）、corr_004（多统计量 Series）、ts_008、ts_009（文字索引）靠结果契约。这是估计，以 S 下一轮实测为准。
- 结果契约会改变模型输出，所以阶段 1.5 之后的数字与阶段 1 不可直接比较，需重新定基线。

### 当前已知问题
| 编号 | 严重度 | 位置 | 描述 | 计划阶段 |
|---|---|---|---|---|
| B01 | P0 | tools/sandbox.py run_code | 同进程 exec 可逃逸（读环境变量里的 Key、执行 shell、写文件） | 2 |
| B02 | P0 | sandbox.py 线程 join | 超时杀不掉线程，无内存上限 | 2 |
| B03 | P1 | sandbox.py 猴补丁 plt.savefig | 恢复已完整；全局状态并发互踩仍在 | 2 |
| B28 | P1 | sandbox.py builtins | 缺 `__import__`，pandas 延迟导入失败 | 2 |
| B04 | P1 | schema.py / dictionary.py | 污染已除；注入只做了截断 + 分隔块缓解 | 2（沙箱兜底）/ 7 |
| B05 | P1 | graph.py _route_after_exec | 只修报错不修答错 | 7 |
| B09 | P1 | schema.py | 无枚举值/范围/空值率 | 7 |
| B26 | P2 | eval | ReAct 最终文字回答不参与打分 | 3 |
| B12 | P2 | eval/comparator.py | 12 条规则之外的形态（文字句子、多统计量 Series、文字索引）仍判错，需人工抽检 | 3 |
| B13 | P2 | eval/cases.py | 50 题 / 60 行单表，难度偏低 | 3 |
| B17 | P2 | — | 无 CI、无日志框架（入口仍用 print） | 3 |
| B18 | P1 | ui/chat_app.py | 无身份与持久化；临时文件不清理；记忆在进程内存 | 4 |
| B20 | P2 | app/react_agent.py | create_react_agent 已弃用，需迁移 | 4 |
| B21 | P2 | core/llm.py ReAct 路径 | ReAct 重试次数记为 None | 4 |
| B22 | P2 | tools/csv_io.py | Big5 可能被 gb18030 误解码 | 4 |
| B23 | P2 | — | 无限流、无模型降级、无 token 预算上限 | 4 |

### 指标快照
- 测试：248 项 = 243 通过 + 5 xfail（B01×4、B28×1）。[2] 为 173 项 = 169 通过 + 4 xfail。Python 3.11.17 与 3.12.15 各在 fresh venv 按 requirements-dev.txt 安装后结果相同。
- oracle 自检：workflow 50/50、react 50/50；两份 oracle 报告 `--rescore` 往返后仍 50/50。
- 真实 LLM 基线：S 实际用 Qwen3.5-397B-A17B 跑完，见 [4]。

### 下一步
1. S 在本地跑三组，每组 3 次（每次约 5 元）：
   `python run_eval.py --repeat 3`、`python run_eval.py --no-dict --repeat 3`、`python run_eval.py --agent react --repeat 3`；
   把 outputs/ 里的 *_run*.json 和 *_summary.json 放进 docs/eval/ 推到 eval-results 分支，Hark 复核后回填本条，作为第一组可信基线。预算紧可以先每组 1 次。
2. 提交本阶段改动并回填 SHA。
3. 进入阶段 2：子进程沙箱（B01 B02 B03 B28）。

## [4] 2026-10-09 · 阶段 1.5 第二轮（实测复核后修正）· commit 59e3625
上一条：[3]（b710e23）。

### 当前技术栈
同 [3]。

### 阶段 1.5 真实评测（S 本地，b710e23，50 题 × 3 次，docs/eval/*_20261009_16*）
模型 Qwen3.5-397B-A17B（公司网关，OpenAI 兼容协议，temperature 0）。报告 git_sha = "b710e23?"（S 的 conda 环境里没有 git，按 B27 的回退读 .git，可信）。GLM-5.1 只试了 1 题，接口失败，作废（160228）。

| 配置 | 3 次正确 | 均值 | 执行成功 | 首次报错 | 平均 token | 用 [4] 比较器重评 |
|---|---|---|---|---|---|---|
| workflow + 字典 | 35 / 35 / 35 | 70.0% | 43/50 | 9 | 2603 | 37 / 37 / 37 → 74.0% |
| workflow 无字典 | 35 / 38 / 37 | 73.3% | 43–46/50 | 5–9 | 2423 | 37 / 39 / 38 → 76.0% |
| react | 40 / 38 / 40 | 78.7% | 49/50 | 3–5 | 5319 | 43 / 42 / 46 → 87.3% |

- 这是第一组带模型名和 SHA 的基线，但模型换成了 Qwen，不能和阶段 1（DeepSeek，未记录模型）的 56% / 58% / 46% 比。
- workflow + 字典 3 次逐题完全相同，第 2、3 次平均耗时从 11.2 s 降到 2.6 s / 2.4 s：网关很可能缓存了 temperature 0 的相同请求，所以这组的标准差 0 不代表模型稳定（B31）。
- workflow 每次有 4–7 题代码没跑起来：Qwen 无视"不要 import"写 `import matplotlib.pyplot / numpy`，沙箱报 `ImportError: __import__ not found`，reviewer 改 3 次也没去掉（5 题）；用 np 但沙箱没给（agg_011）；代码块前加了 markdown 标题，strip_code 没剥掉（filt_005、corr_006）。
- 结果契约的副作用：react 把标签拼成句子（"华中，平均单价 90.88 元"、"产品A，总销量 2325 件"、"2024-05 环比增长率最高"）；workflow 的 ts_009 只给"第二季度"，summarizer 拿不到两季数字，回答"无法回答"。
- 重评后仍判错的主要是真错或口径分歧：ts_005（订单数算成件数）、ts_011（加权均价 vs 简单均价）、corr_003（占比方向）、corr_007（逐行标准差 vs 汇总后标准差）、corr_001（占比 vs 件数）、agg_015、ts_009；react 有 2 题 "Sorry, need more steps"（recursion_limit 12 触顶）。

### 本次完成（对照 [3]）
| 问题 | 状态 | 证据 |
|---|---|---|
| B28 | 已解决 | tools/sandbox.py 加白名单 `__import__`：numpy、pandas、matplotlib、math、statistics、datetime、calendar、re、collections、itertools、functools、decimal、json、warnings、time、locale、_strptime；其他（os、sys、subprocess、shutil、importlib…）报"沙箱不允许导入"。命名空间预置 np。builtins 补 any/all/reversed/repr 与常用异常类，没有加 getattr/type（避免多开 dunder 逃逸口）。test_timestamp_strftime_works 去掉 xfail；新增 test_whitelisted_imports_and_np、test_other_imports_blocked×5 |
| B29 | 已解决（规则范围内） | eval/comparator.py 新增规则 13–17（文件头逐条说明）：13 期望 1 行表、实际是该行 Series；14 期望索引是月份序号 1–12、实际是 '2024-01' 等；15 ISO 周标签 '2024-W01' 算时间索引；16 模型自起键名的汇总 dict（期望数值时 ≤4 项；期望标签元组时取 dict 里的标签值按序比）；17 去掉实际多出的 总计/合计/All/Total 行列。tests/test_comparator.py 每条规则一组正反例 |
| B30 | 已解决 | core/llm.py strip_code 改为在全文里找 ``` 代码块（前后有说明文字也行），多个取最长；无代码块原样返回。新增 tests/test_strip_code.py（5 例） |
| B25 | 补 1 道 | ts_008 标准答案去掉 `.astype(int)`（把 .5 截掉，4977.5 vs 4977 恰好超出 1e-4 相对误差） |
| 结果契约 | 修订 | codegen / reviewer / react 提示词：问"哪个"时 result 只放标签本身，不拼说明文字或数值；问题含多个小问时 result 用 dict 全部答上；"不要 import"改为"pd、np、plt 已就绪，无需 import，不要导入其他库" |

### 新发现
| 编号 | 严重度 | 位置 | 描述 | 计划阶段 |
|---|---|---|---|---|
| B29 | P1 | eval/comparator.py | 规则 1–12 之外的 5 种形态（见上） | 1.5（本次） |
| B30 | P1 | core/llm.py strip_code | 代码块前有文字时整段原样 exec → SyntaxError | 1.5（本次） |
| B31 | P2 | 评测方法 | 网关对 temperature 0 的相同请求可能有缓存，`--repeat` 不独立；需要时加请求扰动或换 temperature>0 | 3 |
| B32 | P2 | eval/cases.py | corr_003（占比方向）、corr_007（标准差口径）、ts_011（平均单价口径）题面有歧义，模型的另一种理解也合理；应在题面写清 | 3 |
| B33 | P2 | core/service.py | ReAct recursion_limit=12 偶尔触顶，回答 "Sorry, need more steps" | 4 |

### 假设与判断
- 白名单 import 不扩大攻击面：这些包本来就在命名空间里（pd 能直接拿到 os，B01），放行只是不让正常代码失败。阶段 2 子进程沙箱再整体收紧。
- 规则 16 放宽 dict 到 4 项只适用于 dict（模型自己起键名的汇总），Series 仍 ≤3；5 项 dict（像按地区汇总的整张表）仍判错，测试里有反例。
- 重评只能修判分，不能修"没跑起来"的题；沙箱和 strip_code 修好后 workflow 能多跑几题，需要新一轮实测才知道多多少。

### 当前已知问题
同 [3]，去掉 B28；加 B31、B32、B33。B12 改为"17 条规则之外的形态仍判错"。

### 指标快照
- 测试：264 项 = 260 通过 + 4 xfail（B01×4）。[3] 为 248 项 = 243 通过 + 5 xfail。Python 3.11。
- oracle 自检：workflow 50/50、react 50/50。
- 真实 LLM（b710e23，Qwen3.5-397B-A17B）：见上表；按本条比较器重评 workflow+字典 74.0%、无字典 76.0%、react 87.3%。

### 下一步
1. 提交本条改动并回填 SHA；把 eval-1.5 分支的 14 份报告并进 master 的 docs/eval/。
2. 可选：S 用本条代码再跑一轮 workflow（同模型），看沙箱 / strip_code 修复后执行成功率。
3. 进入阶段 2：子进程沙箱（B01 B02 B03）。


## [5] 2026-10-09 · 阶段 2 执行隔离（子进程沙箱）· commit e6a33b2
上一条：[4]（59e3625）。

### 当前技术栈
同 [4]；沙箱改为子进程。不新增依赖（Windows Job Object 用标准库 ctypes 调）。

### 设计
- `tools/sandbox.py::run_code()`（签名不变）：每次执行起一个子进程 `python -I -B -X utf8 tools/sandbox_worker.py <临时工作目录>`，执行一次就销毁。
  - 环境变量白名单（PATH、SYSTEMROOT、LANG、CONDA_PREFIX 等），API Key 与其他变量一概不传；TMP/TEMP 指向工作目录。
  - 输入：主进程把 df 存成 input.pkl、代码存成 job.json（主进程写，子进程读，方向可信）。
  - 输出：子进程把结果用 JSON 写到 out.json（`tools/wire.py`，保留 RangeIndex/MultiIndex/DatetimeIndex/PeriodIndex、列 dtype、Timestamp/Period/NaN、dict/list/tuple），图存成 chart.png，主进程再拷到 chart_path。**主进程不反序列化子进程产生的 pickle**。
  - 超时：主进程 `proc.wait(timeout)`，到点 Windows 用 TerminateJobObject、其他平台 killpg 强杀。
  - 内存：Windows 用 Job Object 的 ProcessMemoryLimit（`tools/_winjob.py`）；Linux/macOS 子进程在执行前对自己设 RLIMIT_AS（软硬一致，无法调高）。默认 2048 MB，`DATACHAT_SANDBOX_MEM_MB` 可调。
  - Windows Job 另外限制同时只能 1 个进程（无法再起子进程）、禁读写剪贴板等 UI 操作，关闭句柄连带杀掉。
  - 预启动：子进程导入 pandas/matplotlib 后报 READY 再等任务，主进程常备 1 个备用进程，把约 0.5 s（Linux）的导入开销藏到上一题执行期间。`DATACHAT_SANDBOX_PREWARM=0` 关闭。
- 子进程内的审计钩子（`sys.addaudithook`，装上后无法移除；只在模型代码执行前装）：
  - 禁止：subprocess / os.system / exec / spawn / fork / kill、socket、ctypes、winreg、_winapi、sqlite3、urllib/http 等网络库、webbrowser、gc.get_objects/get_referrers/get_referents、sys._current_frames、pickle.find_class、os.chdir；
  - 读 traceback / 生成器 / 协程的帧（tb_frame、gi_frame…）被禁，防止拿到外层帧；
  - 读文件只允许 Python 安装目录与 site-packages、matplotlib 数据与缓存、字体目录、时区目录、工作目录；写文件、删改文件只允许工作目录与 matplotlib 缓存目录；列目录同读规则。
  - 钩子和目录列表只存在于闭包里，没有名字指向它们；gc 遍历已禁。
- 受限 builtins + import 白名单沿用 [4]，抽到 `tools/sandbox_policy.py`。
- 报错格式：tb_frame 被禁后 traceback 模块用不了，改为自己拼 "File "<string>", line N" + 异常类型与消息（reviewer 依赖的信息不变）。
- `run_trusted()`：评测标准答案在本进程执行（可信代码），`eval/runner.py`、`eval/rescore.py` 改用它；模型代码仍全部走 run_code。

### 本次完成（对照 [4]）
| 问题 | 状态 | 证据 |
|---|---|---|
| B01 | 已解决（桌面威胁模型下） | tests/test_sandbox.py 的 test_escape_blocked×7（pandas 里的 os.popen / os.system、`__subclasses__` 找 Popen、ctypes、socket、gc 遍历、traceback 取帧）、test_api_key_not_in_child_env、test_file_write_blocked、test_file_read_outside_blocked（读临时目录里的 .env、列目录）全部通过，xfail 全部去掉 |
| B02 | 已解决 | test_timeout_kills_process：死循环 timeout=1 时 15 s 内返回 TimeoutError（实测约 timeout + 0.5 s），进程被杀，没有残留线程 |
| B03 | 已解决 | 每次执行独立进程与工作目录，plt.savefig 的重定向只在子进程里；test_concurrent_runs_isolated（4 线程并发出图，图与结果不串）、test_parent_matplotlib_untouched |
| 内存上限 | 新增 | test_memory_limit（1024 MB 上限下申请 4 GB 报 MemoryError） |
| 结果保真 | 新增 | test_result_types_round_trip；test_comparator_cases 的等价/错误写法全部经子进程执行仍判对 |

### 新发现
| 编号 | 严重度 | 位置 | 描述 | 计划阶段 |
|---|---|---|---|---|
| B34 | P1 | tools/sandbox_worker.py | 审计钩子不是严格安全边界（Python 文档原话）：C 扩展自己打开的文件不经过 open 事件；通过 sys._getframe 仍能走到 worker 的 main 帧（里面没有钩子与 Key，但能看到 df 等）。硬保证只有"Key 不在子进程环境变量里"和进程级限制；本机文件系统没有 OS 级隔离（Windows 要 AppContainer / 低完整性令牌）。阶段 4 把 Key 从 .env 挪进系统钥匙串后，磁盘上不再有明文 Key | 4（钥匙串）、8（容器） |
| B35 | P2 | tools/sandbox.py | 打包成 exe 后 sys.executable 是应用本身，需要 `<exe> --sandbox-worker` 入口 | 6 |
| B36 | P2 | tools/_winjob.py | Windows 代码路径（Job Object、内存上限、单进程限制）只能在 Windows 上测。2026-10-10 S 本地 Windows（Python 3.11）跑 tests/test_sandbox.py 28 项全过；首轮唯一失败是测试本身的问题（`CDLL(None)` 在 Windows 上先报 TypeError，到不了 dlopen），已把用例拆成按平台 dlopen 与 `string_at` 读内存两条。之后由 CI Windows runner 持续覆盖 | 2（已本地验证）、3（CI） |
| B37 | P2 | 性能 | 每次执行多一次进程启动：Linux 约 0.5 s，Windows 预计 1–3 s（未测）；预启动能藏掉大部分。全量测试从约 10 s 变为约 2 分钟 | 3 |

### 假设与判断
- 威胁模型按 plan.md：桌面单用户、本机数据、自带 Key，重点防恶意 CSV 经提示注入偷 Key、写文件。本条挡住的是 LLM 生成或被注入的常见手法；专门针对审计钩子的绕过（B34）留到容器沙箱。
- 内存上限 2048 MB：pandas + matplotlib 导入后约 300–600 MB 地址空间，余量够常规分析。Linux 上 RLIMIT_AS 管的是虚拟地址空间，偏保守。
- 标准答案走本进程：它是仓库里的固定代码，不是模型输出；这样评测不多付一倍的进程开销。

### 当前已知问题
同 [4]，去掉 B01、B02、B03；加 B34–B37。

### 指标快照
- 测试：274 项全部通过，0 xfail（[4] 为 260 通过 + 4 xfail）。Python 3.11 与 3.12（Linux）一致，全量约 2 分钟。
- oracle 自检：workflow 50/50、react 50/50（经子进程沙箱）。
- Windows（S 本地）：tests/test_sandbox.py 28 项全过；单次 run_code 约 2 s，首次约 4 s（冷启动 + 预启动备用进程）。

### 下一步
1. ~~S 在 Windows 本地验证 Job Object 路径（B36）~~ 已完成（28/28）。
2. 可选：S 用本条代码再跑一轮 Qwen 评测，看 [4] 的修复后 workflow 执行成功率。
3. 阶段 3：评测集扩到 100–150 题，GitHub Actions 跑单测（含 Windows runner，覆盖 B36）。

## [6] 2026-10-10 · 阶段 3 评测集扩展 + CI（进行中）· commit <待提交>

当前阶段：**阶段 3**。CI 已先行合入 master（25d55e2，首轮 4 个组合全过）。

### 当前技术栈
同 [5]。新增 GitHub Actions：ubuntu-latest / windows-latest × Python 3.11 / 3.12，只跑 pytest 与评测数据一致性检查，不调模型、不需要 Key。

### 本次完成（对照 [5]）
- 评测集 50 → **130 题**，4 张表：sales 50（原题）、orders 30、employees 25、inventory 25。
  - 新表由 `scripts/gen_eval_data.py` 固定种子（20261010）生成，数据虚构；`--check` 校验文件与脚本逐字节一致（CI 与单测都跑）。
  - orders 故意带脏数据：18 条整行重复、城市缺失 35 条、折扣空值（字典说明"空 = 无折扣"），题面写清是否去重、算哪些状态。
  - 新分类：**应拒答 9 题**（数据里没有成本/年龄/签收时间/加班/离职原因/奖金/价格/店长/供应商），**歧义 8 题**（"总销售额""复购率""平均库存"等，`alt_ground_truths` 列出所有合理理解，命中任一即对）。
  - 原 4 类在新表上各加题：聚合 21、过滤 16、关联 12、时序 14。
- 结果契约加拒答（S 2026-10-10 定）：数据回答不了时 `result = "无法回答：<一句原因>"`，原因必须有（≥2 字）。planner / codegen / reviewer / ReAct 提示词同步；ReAct 拒答也要执行一次代码，保证结果可打分。打分：应拒答题看是否拒答且有原因；普通题拒答即错。
- B32 修文案：corr_003 写明"每个产品内部各地区合计为 100%"，corr_007 写明"先按产品和地区汇总再求标准差"，ts_011 写明"按记录简单平均"。标准答案未变。
- 比较器规则 18：季度序号 vs 'Q1'/'2024Q1'/季度 Period/'第一季度'；月份时间索引 vs 同年月份序号；时间索引 vs 递增 ISO 周序号；时间/序号索引 vs 等长 list/tuple 按位置比。每条配反例（顺序错、未去重、周起始日错都判错）。
- runner 按 `case.dataset` 取表；`--data` 只替换 sales 表。`run_eval.py` 新增 `--dataset`、`--category refusal|ambiguity`、`--agent both`（两个 Agent 同批题并排比较正确率、执行成功率、耗时、token、分类、分表，另存 compare JSON）。报告新增 `by_dataset`、每题 `dataset`、`datasets`（每张表的 sha256 与是否有字典）。`--rescore` 支持新表、拒答、歧义。

### 新发现
| ID | 级别 | 位置 | 问题 | 处理 |
|---|---|---|---|---|
| B38 | P1 | data/sample_eval.csv | **评测数据旁一直没有 `sample_eval.dict.csv`**（只有 sample.dict.csv），所以阶段 1 与 1.5 的"workflow 有字典"和"workflow 无字典"其实是同一配置，两组差异只是运行波动；而且旧字典写的取值（3 个地区、3 个产品）与 sample_eval（5 个地区、5 个产品）不符。已新增 `sample_eval.dict.csv`，报告记录每张表是否有字典。RAG 增益需要用新基线重新测 | 3 |

### 假设与判断
- 歧义题按"任一合理理解都对"计分，衡量的是"不离谱"，不衡量"会不会追问"；追问能力等多轮对话（阶段 5）再测。
- 新增题里的口径说明（"重复录入只算一次""保留两位小数"）是有意的：普通题测执行，歧义题单独测歧义，避免两种因素混在一个数字里。
- 原 50 题只改了 3 题的文案，`--dataset sales` 的结果仍可与 [4] 的基线粗略对比（这 3 题除外）。

### 当前已知问题
同 [5]，加 B38。B31（网关缓存导致重复运行结果相同）仍待处理：建议 S 用 `--repeat` 时换不缓存的接口或在网关关缓存；B33 留阶段 4。

### 指标快照
- 单测：Linux Python 3.11 **365 passed**，约 3 分钟（oracle 130 题 × 2 个 Agent 占约 80 秒）。
- oracle：130/130（workflow、react）。
- 真实模型基线：待 S 跑 `python run_eval.py --agent both`。

### 下一步
1. S 跑新基线：`python run_eval.py --agent both`（约 130 × 2 次调用），以及 `--no-dict` 一组测 RAG 增益（B38 修复后第一次有效对比）。
2. 根据真实结果复核新题的比较器漏判，再补规则或改题面。
3. 阶段 4：ReAct 步数上限（B33）、Key 进系统钥匙串。
