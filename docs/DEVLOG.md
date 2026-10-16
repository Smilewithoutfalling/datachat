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
- 威胁模型按 docs/roadmap/plan.md（现见 docs/THREAT_MODEL.md）：桌面单用户、本机数据、自带 Key，重点防恶意 CSV 经提示注入偷 Key、写文件。本条挡住的是 LLM 生成或被注入的常见手法；专门针对审计钩子的绕过（B34）留到容器沙箱。
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

## [6] 2026-10-10 · 阶段 3 评测集扩展 + CI· commit 30df587（PR #6；CI 25d55e2）

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

### [6] 补记：真实模型基线（待运行）
- Windows CI 首轮失败：签出把 data/eval/*.csv 转成 CRLF，`--check` 逐字节对比不通过；已修复：对比前统一换行 + `.gitattributes` 固定 LF；actions 升到 checkout@v5 / setup-python@v6。
- 基线命令（在 30df587 之后的 master 上跑，报告自带 commit SHA 与各表 SHA）：
  `python run_eval.py --agent both` 与 `python run_eval.py --agent both --no-dict`
- 结果回填到此处，作为 130 题的第一条基线。

---

## [7] 2026-10-10 · 阶段 3b 基线复核与修复 · commit 69a63e0（PR #7）

### 基线（S 运行，分支 eval-3 b87aef3，docs/eval/phase3/）
- 模型 Qwen3.5-397B-A17B（网关 grg-aikits-test.grgbanking.com），temperature 0，Python 3.11.17，pandas 3.0.6，130 题，n=1。
- 代码 1b27da1。报告里 git_sha 为 "1b27da1?"："?" 表示 S 的环境里调用 git 失败，退回读 .git 文件，**无法判断工作区是否有改动**（不是 -dirty）。
- 表指纹：sales abe40a78ff53、orders b21bad987c65、employees 3fd0f03966b8、inventory 0aac24693528。

| 配置 | 原判 | 重评（本阶段比较器） | 应拒答 | 剩余错题（重评后） |
|---|---|---|---|---|
| workflow 有字典 | 93.8% | **98.5%**（128/130） | 9/9 | ts_001 画图报错，ord_028 题目没写精度（B43） |
| workflow 无字典 | 93.8% | **97.7%**（127/130） | 9/9 | corr_001 只给地区合计，ts_011、ord_019 画图报错 |
| react 有字典 | 86.9% | **90.8%**（118/130） | 6/9 | 拒答不守契约 2、步数上限 1，其余见报告 |
| react 无字典 | 83.8% | **87.7%**（114/130） | 6/9 | 同上，另 4 题撞步数上限 |

- 有/无字典差异在 1 题以内，属单次运行波动范围；在当前 4 张表上，字典没有带来可测的增益（列名已足够自解释）。要测 RAG 增益需要列名含糊的表。
- react 比 workflow 低约 8 个百分点，主要来自拒答（6/9 vs 9/9）和步数上限，不是计算能力。

### 本阶段修复
| ID | 级别 | 位置 | 问题与修复 |
|---|---|---|---|
| B39 | P1 | app/core/service.py | langgraph 剩余步数不足时不抛异常，而是返回英文占位 "Sorry, need more steps…"，被当成结论。改为记 error_kind=agent；ReAct 默认 recursion_limit 12→25 |
| B40 | P1 | app/core/service.py、rescore.py | ReAct 不调工具、直接在结论里写"无法回答：…"时 result 为空，拒答题判错。现在结论首行符合契约时取作 result（`refusal_from_answer`，移到 app/core/result.py）；--rescore 对旧报告同样处理。不守契约的说法（"无法直接回答""无法计算"）仍判错；ReAct 提示词要求结论首行原样以"无法回答："开头 |
| B41 | P1 | app/eval/comparator.py | 比较器规则 19：百分数字符串 '7.00%' 按数值比；dict 键里含季度/月份（'第一季度销售总额'、'3月'）对序号索引 Series 按序号对齐，忽略 dict 中的非数值项；问排名时给名次 1..n 且与期望值从大到小一致即对（并列时不放宽，期望本身是 1..n 时不放宽） |
| B42 | P2 | run_eval.py | `--agent both` 的 compare 文件固定写进 outputs/，单测因此往真实 outputs/ 落文件（S 的 eval-3 里那份 eval_compare_oracle 就来自 pytest 临时目录，应删除）。现在给了 --out 时写在同目录 |
| B43 | P2 | cases_extra.py ord_028 | "平均每单买几件？"没写精度，标准答案却 round 到 2 位，模型答 2.3 被判错。题目补"保留两位小数"。本次基线中这题人工判对 |
| B44 | P2 | app/tools/plotting.py | 横轴是 '2024-01' 这类字符串时，pandas 画图的横坐标实际是位置 0..n-1，模型用 ax.text('2024-01', y) 标注触发 matplotlib ConversionError，整段代码失败（结果其实已算对）。CHART_GUIDE 补了用位置标注的说明。是否在图表失败时保留已算出的 result 留到阶段 4 讨论 |
| — | P3 | report.py | datasets.*.dictionary 改名为 dictionary_file（只表示文件存在；本次是否使用看顶层 use_dictionary），避免 --no-dict 报告里显示 true 引起误读 |

### 指标快照
- 单测：Linux Python 3.11 **374 passed**，约 3 分钟。

### 下一步
- S 删除 eval-3 上的 eval_compare_oracle_20261010_092954.json 后合并（或由本次 PR 一并处理）。
- 合并后建议 S 再跑一次 `--agent react`，验证 B39/B40/B44 的实际效果；workflow 不必重跑。

## [8] 2026-10-10 · 阶段 3c ReAct 复跑复核与修复 · commit 16d51c3（PR #8）

### 复跑（S 运行，分支 eval-3b 4a435e0，docs/eval/phase3b/）
- 代码 69a63e0，模型 Qwen3.5-397B-A17B（同一网关），temperature 0，Python 3.11.17，pandas 3.0.6，130 题，n=1；只跑 react。
- 报告 git_sha 仍为 "69a63e0?"：S 的环境里 Python 调不到 git（B48）。

| 配置 | [7] 原判 | [7] 重评 | **3b 实跑** | 本阶段重评 | 应拒答 |
|---|---|---|---|---|---|
| react 有字典 | 86.9% | 90.8% | **92.3%**（120/130） | **96.9%**（126/130） | 8/9（另 1 题网关报错） |
| react 无字典 | 83.8% | 87.7% | **91.5%**（119/130） | **96.9%**（126/130） | 9/9 |

- B39 生效：两次都没有出现 "Sorry, need more steps"；B44 生效：没有出现 ConversionError；B40 生效：拒答 8/9、9/9。
- 用本阶段比较器重评旧报告：workflow 98.5% / 97.7%（不变，规则 20 没有改动 workflow 的任何判定），react（阶段 3 报告）92.3% / 90.8%。
- 本阶段重评后剩下的错题：有字典 agg_015（题意歧义，B47 改题）、corr_007（总体标准差且只留 1 位小数，B47 改题）、ord_030（没按 order_id 去重，75.77%）、ord_026（网关报错，B45）；无字典 corr_007（只留 1 位小数）、ord_027（没去重）、ord_029（同时给出按销售额、按销量两种答案）、ord_030（两种口径并列）。真正算错的只有“没去重”这类数据陷阱，两次各 1 题。

### 本阶段修复
| ID | 级别 | 位置 | 问题与修复 |
|---|---|---|---|
| B45 | P1 | app/core/llm.py、service.py、rescore.py | 网关以 200 状态码返回 `{"message":"prompt: A user's message must contain at least one image…"}` 作为回复内容，ReAct 把它当成结论（ord_026）。新增 `api_error_text()`：整段内容是只含错误字段（message/error/detail…）的 JSON 时识别为接口错误。ReAct 记 error_kind=llm（计入基础设施失败，不算答错）；工作流的 LLMClient 视为可重试的 gateway_error；--rescore 在 infra_errors 里列出旧报告中的这类题 |
| B46 | P1 | app/eval/comparator.py、react_agent.py | ReAct 常把答案装进带附加信息的 dict（样本数、明细、中间统计），或返回排好序的整张 Series 回答"哪个"。比较器规则 20（只在其他规则都不匹配时才用，且要求唯一匹配）：a) 期望标签、实际是按值排序的 Series 且榜首不并列 → 比较榜首；b) ≤8 项、键为文字的 dict：第一层恰好一个数值/标签等于期望，或恰好一个子对象等于期望 Series，或每个期望标签恰好对应一个含该标签的键；嵌套 dict 里的标量不参与，以免奖励罗列多种口径；全是数值且键 ≤4 字的视为分组表，不适用；c) 一句话字符串里恰好一个百分数（或恰好一个数字）。同时收紧 ReAct 提示词：单一问题不要把答案装进 dict 或附带样本数、明细、其他口径 |
| B47 | P2 | cases.py、cases_extra.py | agg_015 "平均每个地区的销售额"可读成各地区的单笔平均 → 改为"各地区总销售额的平均值是多少？"；corr_007 没写样本/总体口径和精度 → 题目写明"样本标准差（保留两位小数）"；ord_030 增加"排除已退款"的有效订单口径（73.15%）作为合理答案。注意：agg_015、corr_007 的题面变了，与之前的基线不完全可比 |
| B48 | P3 | app/eval/report.py | git_sha 带 "?" 的原因没有记录。现在依次找 DATACHAT_GIT 环境变量 → PATH → Windows 默认安装位置的 git；仍失败时报告写 git_sha_note（找不到 git，或 git 的退出码与 stderr，例如 safe.directory 拒绝），控制台也会打印 |

### 指标快照
- 单测：Linux Python 3.11 **386 passed**。

### 下一步
- S 再跑一次 `--agent react`（有字典 / 无字典），验证 B46 提示词收紧后 dict 形态是否减少、B47 改题后的效果；顺便看报告里有没有 git_sha_note。
- 阶段 3 收尾后进入阶段 4（见 docs/roadmap/plan.md）。

## [9] 2026-10-10 · 阶段 3d ReAct 复跑收尾 · commit ec9ac0f（PR #9）

### 复跑（S 运行，分支 eval-3c fc5d567，docs/eval/phase3c/）
- 代码 16d51c3，模型 Qwen3.5-397B-A17B（同一网关），temperature 0，130 题，n=1；只跑 react。
- 报告 git_sha 为 "16d51c3?"，git_sha_note 写的是"找不到 git（不在 PATH 上）"。但 S 的环境里 `where git` 和 `shutil.which('git')` 都返回 D:\Git\cmd\git.exe，说明是"找到了但启动失败"，原因待查（B53）。

| 配置 | 3b 实跑 | [8] 重评预计 | **3c 实跑** | 本阶段重评 | 应拒答 |
|---|---|---|---|---|---|
| react 有字典 | 92.3% | 96.9% | **97.7%**（127/130） | **98.5%**（128/130） | 8/9 → 9/9 |
| react 无字典 | 91.5% | 96.9% | **95.4%**（124/130） | **97.7%**（127/130） | 8/9 |
| workflow 有字典 / 无字典（阶段 3 报告重评） | — | 98.5% / 97.7% | — | 98.5% / 97.7%（不变） | — |

- 两次都没有网关错误（基础设施失败 0）；B47 改过的 agg_015、corr_007、ord_030 都答对了。
- result 是 dict 的题：有字典从 17 题降到 13 题，无字典从 19 题降到 14 题。B46 收紧提示词有效果，但没有消除。
- 本阶段重评后剩下的错题：
  - 有字典：agg_013（题意歧义，B52 已改题，重评仍按旧题计）、inv_018（问"是多少"却返回 8 行表，结论 43.14 是对的，属于违反 result 契约）。
  - 无字典：ts_010（result 是两个 Series 的 to_string 文本，结论正确，违反契约）、ord_024（应拒答却编了"美妆"，真错）、ord_027（没按 order_id 去重，真错）。

### 本阶段修复
| ID | 级别 | 位置 | 问题与修复 |
|---|---|---|---|
| B49 | P2 | app/core/result.py | 结论写成"我无法回答：…"（inv_021）时没有识别为拒答。refusal_from_answer 允许开头多一个"我"，其余仍要求"无法回答：<原因>" |
| B50 | P2 | app/eval/comparator.py | 规则 20 b 要求第一层"恰好一个"数值等于期望，几种口径算出同一个值时被拒（ord_011：整行去重、按 order_id 去重都是 40；ord_017 同理）。"恰好一个"其实拦不住罗列不同口径（一对一错照样唯一），所以改成"至少一项等于期望"；≤8 项、分组表排除、嵌套标量不参与这几条限制不变 |
| B51 | P3 | app/eval/comparator.py | 周标签写成 '2024-W09 (02-26)'（inv_016）没有识别为时间索引。规则 15 的周标签允许带括号说明 |
| B52 | P2 | app/eval/cases.py | agg_013 "各地区销售总额的中位数"和 agg_015 是同一种歧义，模型理解成了各地区单笔销售额的中位数 → 改为"先算出各地区的总销售额，这几个总额的中位数是多少？"，agg_015 统一成同样的写法。注意：题面变了，与之前的基线不完全可比 |
| B53 | P3 | app/eval/report.py | git_sha_note 只写"找不到 git"，分不清是真的找不到还是启动失败。现在写出实际使用的 exe 路径、它是否存在，以及系统原始报错 |

### 指标快照
- 单测：Linux Python 3.12 **386 passed**（新增断言，用例数不变）。

### 下一步
- 下次正式跑评测时看 git_sha_note 的原始报错，定位 B53。
- 剩下两类问题是 agent 能力问题：不去重（每次约 1 题）、result 形态违反契约（每次约 1 题）。留到阶段 4 之后用 n≥3 的重复运行来观察。
- 进入阶段 4（见 docs/roadmap/plan.md）。

## [10] 2026-10-12 · 阶段 3.5 外部验证闸门（准备）+ M 系列审查落地 · commit ebc4e7b（PR #10）

### 背景
S 从"完整商业产品"角度提了 M01–M22（docs/roadmap/review-M-series.md），两轮讨论后的决定见 docs/roadmap/review-M-series-response.md。核心：阶段 0–3 证明的是"流水线自洽"，不是"真实数据上有用"，所以在阶段 4 之前插入阶段 3.5 外部验证闸门，阈值由 S 预登记（docs/roadmap/gate-phase35.md）。本条只做闸门的准备，真实运行由 S 用自己的 Key 跑。

### 本阶段改动
| ID | 级别 | 位置 | 问题与修复 |
|---|---|---|---|
| B54 | P1 | app/tools/dataset.py（新）、sandbox.py、sandbox_worker.py、service.py、react_agent.py、nodes/codegen.py、reviewer.py、executor.py、state.py、dictionary.py | 只支持单表（M10），闸门多表组照跑就是 0/10。dataset 可以是目录或 CSV 路径列表：每个 CSV 一张表，代码里用 `dfs['表名']`（没有 df）；schema 逐表输出、各自包进数据分隔块；字典合并为"表名.字段"；**不提示 join key**（闸门要测 schema 理解）。单表时所有 prompt 与阶段 3 逐字一致 |
| B55 | P1 | app/eval/comparator.py、runner.py、report.py、rescore.py、run_eval.py | 比较器只给对错，看不出靠哪条放宽规则判对（M02）。新增 match_kind：strict / rounded / scaled / extras / relaxed，备选答案前缀 alt:，拒答题 refusal；报告逐题写 match，汇总写 match_kinds；重评输出 needs_audit（判对但不是 strict 的题）。对错仍以 results_equal 为准，阶段 3 报告重评结果逐题不变 |
| B56 | P2 | app/eval/report.py | 报告没有评测集指纹，改题后无法判断两份报告能否比较（M04）。新增 evalset：题面代码（cases.py / cases_extra.py / case_model.py）+ gen_eval_data.py + 数据与字典文件的 sha256（CRLF 统一为 LF）；重评时指纹变了会提示 |
| B57 | P2 | docs/ | 引用悬空（M12）：[7][8][9] 引用的 docs/eval/phase3*/ 只在 eval 分支上，plan.md 不在仓库里。eval-3 / 3b / 3c 的报告并入 master；plan.md 入库为 docs/roadmap/plan.md 并按审查修订（阶段 3.5、阶段 4/6 新增交付物、前端只走 HTTP 的约束）；[9] SHA 补为 ec9ac0f |
| B58 | P2 | docs/THREAT_MODEL.md（新） | 原文档容易读成"keyring 上线 = 偷 Key 已解决"（M03）。写明各道防线挡什么、挡不住什么：keyring 只解决明文落盘，挡不住同用户下的沙箱逃逸（DPAPI 按用户加密）；T1/T2 在阶段 8 OS 级隔离之前不算解决；阶段 6–7 选 (a) 只分析自己的数据 |
| B59 | P3 | docs/eval/FROZEN.md（新） | n=1 + 网关缓存 + 自造数据 + 比较器放宽 → 所有基线数字不得单独引用为准确率（M05） |
| B60 | P3 | .gitignore | 补 .venv/、.pytest_cache/（M11）和 data/gate/ |

### 闸门准备（scripts/gate/、docs/gate/）
- 数据：S 没有可用的工作真表，按 gate-phase35.md §1 的替代方案。单表 = UCI Online Retail（541,909 行）只改呈现的脏表：中文列名、GB18030、Excel 风格日期字符串、缺失客户编号写成"未登记"；其中 3 题用"报表导出"变体（多一行合并表头 + 末尾合计行）。多表 = Olist 8 张表（固定 commit d9e4980）。数据不入库，build_gate_data.py 下载并校验 sha256。
- 题目：questions.py 25 题（单表 15、多表 10，分布同预登记），由我起草（S 2026-10-12 授权）。
- 标准答案：verify_gate.py 在**原始**文件上独立计算（不 import datachat、不读脏表），给出 gold + 备选口径与说明 → docs/gate/answers.json（入库）。真实数据里的陷阱举例：s09 按正数量算会选中被整单取消的 80,995 件；s04 报表变体的合计行国家为空，按"国家≠英国"过滤会把合计算进去。
- 运行与结论：run_gate.py 跑模型并输出待人工判定的报告；`--verdict` 按预登记阈值（单表 11/15、8/15，多表 4/10）与失败分布规则出结论。补充两条规则（失败 <5 题不触发分布规则；2–3 类的中间区间前两类都列 P0），S 已同意。
- 自检（tests/test_gate.py）：脏化逐值可还原；题目分布与预登记一致；answers.json 的题面哈希与 questions.py 一致（改题不重跑 verify 会失败）；判定规则四种情形；数据已下载时，25 题手写正确解在**脏表**上经沙箱执行后比较器全部判对（证明题目在 datachat 看到的数据上可解，不说明模型能答对）。

### 判对层级的第一次统计（阶段 3 报告离线重评，对错不变）
| 报告 | 判对 | strict | alt:strict / alt:rounded | refusal | 需抽审 |
|---|---|---|---|---|---|
| react 有字典（phase3c） | 128/130 | 72 | 3 / 1 | 9 | 43 |
| react 无字典（phase3c） | 127/130 | 71（另 rounded 1） | 2 / 0 | 8 | 45 |
| workflow 无字典（phase3） | 127/130 | 81 | 4 / 0 | 9 | 33 |
| workflow 有字典（phase3） | 128/130 | 81 | 5 / 0 | 9 | 33 |

约三分之一的判对不是 strict，抽审清单用 `python run_eval.py --rescore <报告>` 查看。

### 指标快照
- 单测：Linux Python 3.11 / 3.12 均 **424 passed**（含闸门数据已下载时的 25 个 oracle；CI 没有数据时为 399 passed + 25 skipped）。新增 tests/test_multitable.py（8）、tests/test_gate.py（5 + 25 个依赖数据的 oracle，CI 里跳过）。

### 下一步
- S：`pip install -r requirements-dev.txt` → `python scripts/gate/build_gate_data.py` → `python -m pytest tests/test_gate.py` → `python scripts/gate/run_gate.py --agent react`（建议 workflow 也跑一次）→ 人工判定 → `--verdict`。
- 闸门结论出来后：重估工期（M18）、在闸门数据上定阶段 7 目标（M20），再进入阶段 4。

## [11] 2026-10-12 · 阶段 3.5 外部验证闸门 · 结论 · commit 1e93588（PR #11）

### 运行（S 运行，模型 Qwen3.5-397B-A17B，temperature 0，commit ebc4e7b）
- 报告：docs/eval/gate_20261012_104407_react.json、gate_20261012_104936_workflow.json；s15 复跑 gate_20261012_113135_react.json。
- 判定：AI 预标注 → Hark 复核（改判 react s04，补 m06 / s15 理由）→ S 终审采用。题面哈希 75a559642e4e，与 answers.json 一致。

### 结果
| | react | workflow |
|---|---|---|
| 单表（阈值 ≥11/15） | **12/15** | **11/15**（压线） |
| 多表（阈值 ≥4/10） | **8/10** | **10/10** |
| 执行成功 | 24/25 | 25/25 |
| 失败分布 | ②1 ⑤2 ⑥2（5 题） | ②3 ③1（4 题） |
| 读代码觉得在乱猜 | 2/25 | 0/25 |
| 比较器参考判对 | 17/25（人工 20） | 18/25（人工 21） |

**结论（按预登记规则）**：两个 Agent 单表都达到 11/15 → 可进入阶段 4；多表都 ≥4/10 → 阶段 7 的 DuckDB 路线有救。react 失败 5 题、最大类 40%、散落 3 类 → 中间区间，**⑤ result 契约、⑥ 拒答失当列为 P0**，方向不变。workflow 失败 4 题 <5，只记录分布（② 占 3 题）。

逐题失败：
| 题 | Agent | 类 | 原因 |
|---|---|---|---|
| s02 | 两者 | ② | 把缺失哨兵"未登记"当成一个客户（4373 vs 4372） |
| s04 | react | ⑤ | 结果对，但触到步数上限（recursion_limit=25），用户只看到报错 |
| s04 | workflow | ② | 报表变体的合计行（国家为空）被算进"非英国" |
| s09 | workflow | ③ | 按正数量汇总，选中被整单取消的 80,995 件 |
| s12 | workflow | ② | 没认出"未登记"是缺失，答 0.0% |
| s15 | react | ⑤ | 网关报错原文被当成回答交给用户、error_kind=null；复跑 1 次正确拒答，非稳定复现，正式结果仍记错 |
| m09 | react | ⑥ | 应拒答，却在步数上限前返回占位 result='ok' |
| m10 | react | ⑥ | 应拒答（无成本），自行把利润定义为"售价−运费"给出结果 |

### 闸门暴露的问题（待修）
| ID | 级别 | 位置 | 问题 |
|---|---|---|---|
| B61 | P1 | app/core/service.py、app/react_agent.py | ReAct 触到步数上限时没有结论（s04、m09），用户只看到报错；需要在上限前强制收尾，或按契约返回已有结果并如实说明 |
| B62 | P1 | app/core/service.py / LLM 调用层 | 网关返回的报错（`{"message":"prompt 必须包含字符串内容…`）被当成模型回答，error_kind=null（s15）；需识别为 llm 错误。"必须包含字符串内容"提示某条消息的 content 不是字符串，需排查 |
| B63 | P1 | app/react_agent.py 拒答提示 | 缺字段时自行重新定义指标而不拒答（m10）；阶段 3 的拒答契约在 ReAct 上没守住 |
| B64 | P1 | 结论生成 | 叙述与证据不符：m06 金额对，但"1,061 单 / 953 单有支付"是编的（真值 84 单、全部有支付，代码已 print 真值）；s03 脚注"约 5.4 万行"（实为 541,909）。不在预登记 6 类内，题仍判对；结论里的数字应能在工具输出里找到 |
| B65 | P2 | schema 摘要 / 提示 | 脏数据：缺失哨兵（"未登记"）、合计行没被识别（s02 两者、s04 / s12 workflow）。阶段 7 的列画像（枚举值、异常行）对口 |
| B66 | P2 | app/eval/comparator.py | 形态漏判 7 次：gold 是 list，结果是 Series / DataFrame / ArrowStringArray（s07、s08、m08），季度索引 Q1 对 1（s11） |
| B67 | P3 | scripts/gate/run_gate.py | git_sha 带"?"（没能检查工作区）时没写 git_sha_note |

### 注意
- 这 25 题已经被看过、被分析过，之后只能作**回归**用；阶段 7 的目标要在一套新的、留出的外部题上验证，否则就是对着闸门调参。

### 下一步（待 S 决定）
- 先修 B61–B64（P0 两类 + 叙述编造），用闸门 25 题做回归，再进入阶段 4 正式内容。
- 重估工期（M18）；定阶段 7 目标与留出集（M20）。

## [12] 2026-10-12 · 阶段 3.6 闸门问题修复（B61–B64、B66、B67）· commit 9430354（PR #12）

### 先说根因
复查闸门轨迹时发现：**沙箱一直丢弃模型代码的 print 输出**（sandbox_worker 把 stdout 重定向到一个不回传的 StringIO），而 ReAct 模型探索数据时大量用 print。于是：
- s04：print 了合计行想看，什么也没看到，反复试探直到步数用完；
- m09：`print(...)` 后 `result = 'ok'`，看不到输出，继续兜圈子直到步数用完；
- m06：代码 print 了真值（84 单），模型看不到，结论里的"1,061 单 / 953 单"只能是编的。
工作流版一次生成代码、只看 result，不受影响——这也解释了为什么 ⑤⑥ 只出现在 ReAct 上。

### 本阶段修复
| ID | 级别 | 位置 | 问题与修复 |
|---|---|---|---|
| B61 | P1 | app/tools/sandbox_worker.py、sandbox.py、app/react_agent.py、app/core/service.py | ① print 输出回传：run_code 新增 capture 参数，回传 stdout（上限 8000 字符，保留头尾；报错时也回传出错前的输出）；ReAct 的工具结果附上 print 输出（上限 2000 字符），工具说明写明"print 的输出也会返回给你"。② 步数用完不再只给一句报错：改为流式执行保留最后状态，撞上 GraphRecursionError 或 langgraph 的英文占位答复时，用已有执行结果再调一次模型（不带工具）强制收尾，结果记 warnings；收尾判定拒答时以拒答为准，不拿中途的占位 result 冒充答案；收尾也失败才记 agent 错误 |
| B62 | P1 | app/core/llm.py、service.py | 网关错误 JSON 被截断（`{"message":"prompt 必须包含字符串内容`）时 api_error_text 认不出，被当成回答。现在单个错误键 + 未闭合字符串也认作错误；ReAct 遇到网关错误内容时整轮重跑（最多 2 次，带多轮记忆时不重跑以免污染历史），仍失败记 llm 错误 |
| B63 | P1 | app/react_agent.py | 拒答契约补一句：指标在表里没有对应字段、也不能按通行定义由现有字段算出时属于回答不了，不要自己给指标另下定义（例如把"售价−运费"当利润），不要用代理变量估算 |
| B64 | P1 | app/core/grounding.py（新）、result.py、service.py、run_gate.py | 叙述与证据不符：结论里有分量的数字（带小数、%/万/亿、或 ≥100 的整数，年份除外）逐个到证据（问题 + 工具 result + print 输出；工作流为 result 文本）里找，按结论写出的精度匹配（82.2 万 ≈ 822,023.63；24.93% ≈ 0.2493）。找不到的记入 AnalysisResult.unverified_numbers，**只检测不改写**；闸门报告逐题记录。ReAct 系统提示加"结论里的数字必须来自工具返回的 result 或 print 输出" |
| B66 | P2 | app/eval/comparator.py、scripts/gate/run_gate.py | 比较器规则 21：无序标签集合（gold 用 frozenset）与 list / 数组 / Series / 表的某一列按集合比（不许重复）；Top-N 标签列表与"以这些标签为索引的 Series"按索引顺序比；ExtensionArray / Index 按 list 处理。run_gate 的有序列表改用 list、无序改用 frozenset，序列索引里的数字字符串还原为整数（s11）。阶段 3 评测集不出现 frozenset，其判分不受影响 |
| B67 | P3 | scripts/gate/run_gate.py | git_sha 带"?"时写 git_sha_note；报告逐题记录 warnings 与 unverified_numbers |

B65（缺失哨兵、合计行）不在本阶段，留给阶段 7 的列画像。

### 指标快照
- 新增 tests/test_phase36.py（19 个），每条对应一道闸门失败题；test_core_analyze 的网关错误用例按重跑次数调整。
- 闸门 7 次形态漏判用重建的结果对象复核：规则 21 下全部判对，打乱顺序、缺项、多重复项、错标签仍判错。

### 下一步
- S 用闸门 25 题重跑 react（建议 workflow 也跑），只作**回归**：看 ⑤⑥ 是否归零、其余题有无退步、unverified_numbers 有多少。
- 然后进入阶段 4；M18 重估工期、M20 阶段 7 目标与留出集。

## [13] 2026-10-12 · 阶段 3.6 回归（闸门 25 题，仅回归）+ B68、B69 · commit 9a3816b（PR #13）

报告：docs/eval/gate_20261012_140826_react.json、gate_20261012_142736_workflow.json（S 于 9430354 运行；Windows 上 git 不在 PATH，git_sha 带 "?"，git_sha_note 已写明）。**这 25 题已用于定位和修复问题，下面的数字只说明修复是否生效，不是准确率证据。**

### 对比阶段 3.5 正式结果（按比较器判分 + 本人逐题核对；新报告尚未由 S 人工判定）
| | 阶段 3.5（人工） | 回归 |
|---|---|---|
| React 单表 | 12/15 | 14/15（s04、s15 修复；s02 仍错 ②） |
| React 多表 | 8/10 | 8/10（m09、m10 仍错） |
| Workflow 单表 | 11/15 | 10/15 比较器；s07 实为 B68 漏判 → 11/15，与原来同（s02、s04、s09、s12 原样） |
| Workflow 多表 | 10/10 | 10/10 |

- ⑤ 归零：s04（912,621，正确）、s15（正确拒答）已修。
- ⑥ 未归零（m09、m10 仍错）：m09 这次只回了一个 "B"（约 4 秒，1 次调用，没执行代码），error 却为空、被记成成功 → B69，这次失败已不属于 ⑥ 而是管线问题；m10 仍给出营收表，但性质变了——结论第一句就说明"无法计算利润、没有成本字段"，再把"售价＋运费"明确标成替代口径；按预注册口径（应拒答题必须 result 为拒答）仍判错。
- m06 叙述已与真值一致（84 单、85 条支付、23,921.17），B64 的根因（print 不可见）确认修复。
- unverified_numbers：React 4 题有标记（s04 17.6%、s11 70%、m01 各州占比、m08 总单数/占比），**全部是模型由证据推算的比例或合计，没有编造**；Workflow 0 题。该信号目前精度不足以直接展示给用户，只作评测抽审。

### 回归暴露的问题
| ID | 级别 | 位置 | 问题与修复 |
|---|---|---|---|
| B68 | P2 | app/tools/wire.py | 沙箱回传不认识 pandas ExtensionArray：`.unique()` 在字符串列上返回 ArrowStringArray，落到 scalar 分支变成 repr 字符串，比较器当然判错（Workflow s07）。[12] 里说规则 21c 能修好 Workflow s07 是错的——当时的测试用的是进程内对象，没有经过沙箱。现在 ExtensionArray 按 ndarray 回传 |
| B69 | P1 | app/core/service.py | ReAct 一次代码都没执行、也没按契约拒答就收尾时（m09 的 "B"），记成了成功。现在先整轮重跑（与 B62 共用次数），仍如此记 agent 错误；多轮追问可以只用文字回答，不在此列 |

### 判断
m10 是提示词遵从问题，继续在这 25 题上调提示词就是对着测试集调参。建议不再为 m10 改提示词，B68、B69 合入后进入阶段 4；拒答遵从放到阶段 7 用新的留出题集（M20）检验。

---

## [14] 2026-10-12 · 阶段 4 第一步：API Key 进系统钥匙串 · commit cf277ed（PR #14）

### 改动
- 新增 app/core/keystore.py：Key 存在系统钥匙串（Windows 凭据管理器；service `datachat`，账户 `llm_api_key`）。`LLMConfig.from_env` 改调 `resolve_api_key()`：**环境变量 DEEPSEEK_API_KEY 显式设置时优先**（开发、CI、临时覆盖），否则读钥匙串。钥匙串没有后端（无桌面的 Linux / CI）时按"未配置"处理，不抛异常。
- 命令行 `python -m app.core.keystore status|set|migrate|delete`：set 用 getpass 输入，不回显；migrate 把 .env 里的 Key 搬进钥匙串，**不自动改 .env**，由用户手动删掉那一行；status 发现 .env 里还有明文 Key 时会提示。任何输出都不含 Key。
- 缺 Key 的报错改成指向 `keystore set`。README 与 .env.example 改为默认用钥匙串。
- requirements.txt 加 keyring 25.7.0 及其依赖，按平台和版本用环境标记锁定（用 uv pip compile 核对过 Windows/Linux × 3.11/3.12 四种组合，无版本冲突）。
- tests/conftest.py：autouse 换成内存钥匙串。**测试绝不读写开发机上真实的凭据管理器**；否则 S 本机钥匙串里有 Key 时，"缺 Key"相关测试的结果会变。

### 注意
- 入口脚本仍会 load_dotenv：.env 里留着 Key 时，它以环境变量身份优先于钥匙串。迁移后必须删掉 .env 里那一行，status 会提醒。
- THREAT_MODEL 不变：钥匙串只是缩小暴露面，同一用户身份下的程序都能读。沙箱 import 白名单里没有 keyring（新测试 test_sandbox_cannot_import_keyring），子进程环境变量本来就不含 Key。

### 测试
tests/test_keystore.py 新增 9 个（含参数化）；全量 455 通过（3.11 / 3.12）。

### 下一步
`analyze_stream()` + trace id → FastAPI + SSE → 会话持久化 → PyInstaller spike。

---

## [15] 2026-10-13 · 阶段 4：analyze_stream() + trace id（M09、M14 部分）· commit 9f9771c

### 改动
- `analyze_stream()`（app/core/service.py）是生成器，按发生顺序产出事件；`analyze()` 只是把它跑完、取 done 里的结果。两者走同一条代码路径，没有线程。`res.steps` 的内容和顺序不变，评测与报告不受影响（test_analyze_equals_stream_done 逐字段比对）。
- 事件定义在 app/core/events.py：`plan / code / exec / answer / error / done`，每个都带 trace_id、seq、ts。
  - 比 10-12 提议的五类**多了 done**：SSE 需要一个必有且唯一的终止事件来携带完整结果，"answer"在失败时没有，不能当终止符。
  - error 分两种：fatal=False 是过程中可恢复的情况（数据字典读取失败已跳过；ReAct 整轮重跑），fatal=True 只在 done 前出现一次，与结果里的 error 相同。
- **ReAct 是真流式**：code / exec 事件在图执行过程中逐条产出（test_react_events_arrive_before_run_finishes：第一个事件出来时模型只被调用过一次）。answer 要等收尾判定后才发，因为最后一条消息可能是网关错误或 "Sorry, need more steps" 占位，会被作废或强制收尾。所以 answer 每次最多一个，强制收尾得到的带 forced=True。
- 整轮重跑时，上一轮已发出的 code / exec 作废，以 error（"重跑本轮…"）为界。前端按这个界限清掉之前的步骤。
- 多轮记忆：第二轮只产出本轮的新事件，不重放历史。
- 调用方中途停止迭代（SSE 客户端断开）会关闭生成器，图执行随之停止；此时没有 done，也不写 runs.jsonl。
- trace_id：可由调用方传入（以后用消息 id），否则生成 uuid4 hex。写进 AnalysisResult.trace_id → runs.jsonl；`logging.getLogger("datachat.analyze")` 的开始/结束/失败日志都带 trace。logging 的配置（输出到哪里）留到 FastAPI 那一步统一做。

### 测试
tests/test_stream.py 新增 11 个；全量 466 通过（3.11 / 3.12）。

### 下一步
FastAPI + SSE（数据集上传、会话、消息、设置）+ SQLite。

---

## [16] 2026-10-13 · 阶段 4：本地后端 FastAPI + SSE + SQLite（B18 大部分、M08、M10、M14）· commit 667e0e8

### 改动
- 新包 app/server：`create_app(home, token)` 和 `python -m app.server [--port] [--home] [--token]`。接口列表在 app/server/app.py 顶部：数据集、会话、消息（SSE）、图表、设置、API Key。
- **SSE**：`POST /sessions/{id}/messages` 返回 text/event-stream，逐条转发 analyze_stream 事件（`id: seq`、`event: type`、`data: Event.to_dict()`）。助手消息 id = trace_id，放在响应头 X-Message-Id。图表本地路径换成 `/charts/<文件名>`，结果里的数据集绝对路径不外发。
  - 请求用 POST（要带 body 和 token），浏览器原生 EventSource 用不了，前端用 fetch 读流。
- **SQLite**（app/server/db.py，SQLAlchemy 2.0，只用通用类型，以后换 PG 不改模型；各表预留 user_id）：datasets、dataset_files、sessions、messages、events、settings。
  - 每个事件（done 除外）存进 events 表，完整结果存在 messages.result_json，所以历史可以完整回放步骤。
  - 服务端不再写 runs.jsonl（M14：DB 替代）；命令行入口照旧写。
- **数据集**：一次上传多个 CSV（M10）。*.dict.csv 作字典；单表直接传文件路径（字典自动生效），多表传目录。
  - 文件名只保留 basename，只收 .csv，单文件上限 1 GB，最多 50 个文件；落在 `<home>/datasets/<id>/` 下，算 sha256。删除数据集时级联删除会话并删掉文件。
- **设置**：模型名、base_url 存 settings 表，覆盖环境变量。API Key 只走钥匙串（PUT/DELETE /settings/api-key），GET 只返回 configured 和 source，**从不返回 Key**。
- **本机安全**（写进了 app.py 文档字符串，THREAT_MODEL 待补一节）：
  - 只绑定 127.0.0.1；
  - TrustedHost 只认 localhost / 127.0.0.1，挡 DNS rebinding；
  - 每次启动生成随机 token，挡本机网页对 localhost 的跨站请求；图表另接受 ?token= 给 `<img>` 用；
  - 不开 CORS，阶段 6 外壳确定后只放行外壳的源。
- **并发与中断**：同一会话已有一条在分析时返回 409。客户端断开时生成器被关闭，消息标为 cancelled。后端被杀后重启，遗留的 running 一律标成 cancelled。
- 日志：`python -m app.server` 把 logging 输出到 `<home>/server.log` 和 stderr，analyze 日志带 trace。
- 依赖：fastapi 0.143.0、annotated-doc、SQLAlchemy 2.1.4。starlette / uvicorn / python-multipart 原先已是传递依赖，这次显式锁定；dev 加 httpx（TestClient 需要）。四种平台/版本组合都 compile 通过。

### 已知限制
- **ReAct 多轮记忆在进程内**（MemorySaver）：重启后历史可查，但模型不再记得之前几轮。要做到重启后接着聊，需要 langgraph 的 SQLite checkpointer（多一个依赖），或者用 messages 表重建上下文。留到接前端时再定。
- M13 的"图表数据"目前只有 png 和结果文本（result_text）。结构化的图表数据（给前端自己画）要等前端确定图表库后再定格式。

### 验收（plan.md 阶段 4，前两条）
- "用 curl 走完 上传 → 提问 → 流式结果 → 历史可查"：沙箱里真起了 `python -m app.server --port 0`，用 curl 走通（没有 Key，走的是 error → done 路径）；带假模型的完整路径见 tests/test_server.py。
- "重启后会话还在"：test_full_flow_workflow_and_restart 用同一数据目录新建 app，会话、消息、事件、结果都在。
- 第三条（PyInstaller spike）还没做。

### 测试
tests/test_server.py 新增 12 个（含参数化 4 个）；全量 478 通过（3.11 / 3.12）。

---

## [17] 2026-10-13 · 阶段 4：ReAct 多轮上下文从 messages 表重建（S 选 B 方案）· commit 132788a

### 改动
- `analyze` / `analyze_stream` 新增参数 `history=[(问题, 结论), ...]`：作为 user / assistant 消息交替放在本轮问题前面。
  - 只取最近 10 轮（MAX_HISTORY_TURNS），每条结论截断到 2000 字。
  - 与 memory 互斥，同时传会报 ValueError；工作流版忽略这个参数。
- 后端不再用 MemorySaver。每次提问时从 messages 表取本会话**成功**的轮次（user + 紧跟的 ok 助手消息），交给 history。
  - 失败和取消的轮次不进上下文，因为用户通常会换个说法重问。
  - 上下文只有 DB 这一份来源，重启后照样接得上。
- 整轮重跑：不再传 memory，B62（网关错误内容）的整轮重跑在后端也开始生效，之前带 memory 时这个重跑是关掉的。
  - B69（"没执行代码也没按契约拒答"→重跑，最后仍是这样就判失败）在带 history 时**两处都不触发**，与原来带 memory 时一致：追问可以只凭上下文作答（比如"解释一下上面的结果"）。这个是第一版测试暴露出来的问题，已补测试。

### 与 MemorySaver 的语义差别
- history 只带问答，**不带**中间的工具调用和代码输出。追问"换成按月"时，模型要重新写代码（它本来也得重新算），但看不到上一轮的代码原文。
- 如果以后发现追问质量明显下降，再考虑把上一轮的最后一段代码放进 history。这一点要等前端可用后，用真实追问来验证。

### 测试
- test_stream：history 的截断、本轮步骤不混进历史、与 memory 互斥、带 history 的纯文字追问不重跑。
- test_server：同一会话第二轮带上了第一轮的问答；**重启后**第三轮仍然带着前两轮。
- 全量 481 通过（3.11 / 3.12）。

---

## [18] 2026-10-13 · 阶段 4 spike：PyInstaller sidecar + Windows runner（B35）· commit 3ca793a（PR #18）

### 改动
- `app/sidecar.py`：统一入口。默认启动后端；`--sandbox-worker <目录>` 分派到 sandbox_worker.main()；`--selftest` 输出 JSON 自检（不需要 Key）。
- B35：`app/tools/sandbox.py` 新增 `worker_cmd()`。打包后（sys.frozen）改用 `<exe> --sandbox-worker <目录>`，源码环境不变。
- 自检 8 项：计算、画图、print 回传、读工作目录外文件被**审计钩子**拦截（绕开受限 builtins，用 pd.read_csv 测）、import subprocess 被拦、超时强杀、**操作系统层**内存上限（512 MB 下申请 1.6 GB）、关键依赖导入 + create_app + jieba + keyring 后端名。
- `packaging/build_sidecar.py`（onedir；按名字收 app / uvicorn 子模块、jieba 词典、keyring 元数据；排除 streamlit 等）；`packaging/requirements-build.txt`（pyinstaller 6.22.3）。
- `packaging/smoke_sidecar.py`（只用标准库）：exe 自检 → 起后端 → 上传 → 建会话 → 提问（无 Key 应得 error → done）→ 重启 → 会话还在。报告写 JSON。
  - 请求一律不走代理：沙箱里 http_proxy 把 127.0.0.1 的请求转给代理，返回了 404。S 的机器也常配代理，**前端访问 sidecar 同样必须绕过系统代理**（记为阶段 6 的注意事项）。
- `.github/workflows/sidecar.yml`：windows-latest、Python 3.11 打包 → 冒烟。产物 zip 保留 7 天，报告（大小、最大的目录、smoke.json、PyInstaller 警告）保留 30 天。只在相关路径改动或手动触发时运行。

### 结果
- 源码环境（Linux 沙箱）用一个包装脚本当 exe：自检 8/8 通过，冒烟测试全过，启动约 1 秒。
- 沙箱里没有 objdump，Linux 打包没法试；Windows 上的打包结果以 runner 为准：

**Windows runner 结果**（windows-latest，Python 3.11.9，PyInstaller 6.22.3）

| | 第一次 run 38339431396 | 第二次 run 38340194855 |
|---|---|---|
| 打包耗时 | 45 s | 67 s |
| onedir | 1761 个文件，230.7 MB | 同左 |
| zip | 109 MB | 109 MB |
| selftest | **7/8，plot 失败** | 8/8（10.99 s，含逐项起 worker） |
| 后端启动 / 重启 | 1.29 s / 1.26 s | 1.54 s / 1.46 s |
| SSE（无 Key） | error → done | error → done |
| 重启后历史 | user ok + assistant error | 同左 |

- **第一次失败是 B35 的真问题之一**：PyInstaller 6 把纯 Python 模块的 PYZ 归档附在 exe 自身里，worker 画图时延迟导入要读 `datachat-sidecar.exe`，被审计钩子当成越界读文件拦下。修法：打包环境下把 `sys.executable` 和 `sys._MEIPASS` 加入可读根（`sandbox_worker._read_roots`）。读自己的 exe 和 `_internal` 不扩大攻击面（都是只读的程序文件）。
- **同一次 run 里 blocked_read 是假通过**：它被拦的同样是读 exe（pandas 延迟导入），根本没走到 win.ini。selftest 现在要求报错里出现目标路径才算过；第二次 run 报错为 `沙箱禁止读文件：C:/Windows/win.ini`，确认拦的是对的东西。
- memory 项：1.49 GiB 分配失败，runner 有 16 GB 内存，说明 Job Object 2048 MB 上限在打包后照样生效。keyring 后端 = WinVaultKeyring。
- 体积大头：pyarrow 78.5 MB、jieba 29.6 MB、numpy.libs 20 MB、matplotlib 13.7 MB、pandas 12.1 MB、PIL 10.7 MB。pyarrow 来自 streamlit 传递依赖；**暂不排除**：pandas 3.0 装了 pyarrow 时默认字符串后端用它，排除会让打包版与开发版的 str dtype 后端不一致，留到阶段 6 一并决定（要么开发环境也去掉 pyarrow，要么保留）。
- PyInstaller 警告只有 SQLAlchemy 方言的 hidden import 缺失（pysqlite2 / MySQLdb / psycopg2），都是不用的驱动，可忽略。
- spike 结论：**B35 关闭**；PyInstaller onedir 路线可行，冷启动 ~1.5 s，体积约 110 MB zip。


---

## [19] 2026-10-13 · 阶段 4 收尾：问题总表、本机后端威胁模型、重估 · commit 86bba0a（PR #19）

### 改动
- **问题总表**（下文）：B01–B69 逐条对照当前代码核对。以前每条记录只写"同 [n]，加/去掉 …"，未关问题要倒推好几条才能拼出来；从这条起**只维护这一张表**，后面的记录写"相对 [19] 的增减"。
- docs/THREAT_MODEL.md 补 §2.1 本机后端（T4–T8：只监听 127.0.0.1、TrustedHost 挡 DNS rebinding、启动随机 token、不开 CORS、从不返回 Key）和 §2.2 打包后的沙箱（可读根多出 exe 与 `_internal`）；keyring 一行从"待做"改为已上线。[16] 里欠的那一节补上了。
- B70（新，已修）：`auth()` 对**所有**接口都接受 `?token=`，和文档"只有图表接受"不符，token 会跟着 URL 进浏览器历史、Referer 和访问日志。现在只有 `/charts/*` 认 `?token=`；uvicorn 访问日志里 `token=` 的值写成 `***`。测试：tests/test_server.py 的 `?token=` 访问 /sessions → 401、test_access_log_redacts_token。
- docs/roadmap/plan.md：新增"进度与重估"一节（M18）；M13 顺延为阶段 5 第一件事；pyarrow 去留写进阶段 6。
- CI：sidecar.yml 的 upload-artifact v4 → v7（v4 跑在已弃用的 Node 20 上，runner 每次报警告）。
- [18] SHA 补为 3ca793a。

### 本次正式关闭（早就修好、但一直没在表里关）
| 编号 | 证据 |
|---|---|
| B13 | 评测集 130 题 / 4 张表 / 应拒答 / 歧义（[6]），外加闸门 25 题非自造数据（[10]） |
| B17 | CI：tests.yml，Linux + Windows × 3.11 / 3.12（[6]）；日志：logger `datachat.analyze` 带 trace（[15]），服务端写 server.log（[16]）。命令行入口的 print 是给人看的输出，保留 |
| B18 | FastAPI + SQLite：会话、消息、事件持久化，重启后可查（[16]），重启后可接着聊（[17]）。Streamlit 两个页面阶段 5 删除 |
| B33 | "Sorry, need more steps" 记为 agent 错误、上限 12→25（B39，[7]）；触顶时强制收尾出结论（B61，[12]） |
| B35 | PyInstaller 打包 + `--sandbox-worker`，Windows runner 自检 8/8（[18]） |
| B36 | Windows 路径由 CI windows-latest 每次覆盖（tests.yml），打包版也在 runner 上过了内存上限（[18]） |
| B37 | Windows runner 实测：打包版每次起 worker 约 0.7–0.9 s（selftest 的 compute 0.89 s、stdout 0.77 s、blocked_import 0.74 s，含执行），比原估 1–3 s 好；预启动不急，阶段 5 若体感慢再做 |

### 当前未关问题（唯一的总表）
| 编号 | 严重度 | 位置 | 描述 | 计划阶段 |
|---|---|---|---|---|
| B04 | P1 | schema.py / dictionary.py | 提示注入只做了截断 + 数据分隔块缓解，不是边界 | 8（与 T1 一起，见 THREAT_MODEL） |
| B34 | P1 | tools/sandbox_worker.py | 审计钩子不是安全边界（C 扩展开文件、`sys._getframe`） | 8（OS 级隔离） |
| B05 | P1 | graph.py _route_after_exec | 工作流只在报错时修，答错不修 | 7（结果合理性校验） |
| B09 | P1 | schema.py | 没有枚举值、范围、空值率 | 7（列画像） |
| B64 | P1 | core/grounding.py | 叙述数字与证据不符：已能检测（unverified_numbers），生成侧未约束 | 7 |
| B20 | P2 | app/react_agent.py | `create_react_agent` 已弃用 | **4 收尾（下一个 PR）** |
| B21 | P2 | core/service.py ReAct 路径 | ReAct 重试次数记为 None | 4 收尾，随 B20 一起看能否计数 |
| B44 | P2 | sandbox / 前端 | 图表失败时整段代码算失败，已算出的 result 丢掉；要不要保留并提示"图没画出来" | 5（前端怎么展示一起定） |
| B23 | P2 | — | 没有 token 预算上限、限流、模型降级；桌面版烧的是用户自己的额度 | 6（设置页加每条消息的 token 上限） |
| B12 | P2 | eval/comparator.py | 规则 1–21 之外的形态仍判错；needs_audit 标出非严格匹配 | 7（新留出集一起复核） |
| B26 | P2 | eval | ReAct 结论文字不参与打分（只看 result） | 7 |
| B31 | P2 | 评测方法 | 网关对 temperature 0 可能缓存，`--repeat` 不独立 | 7 |
| B65 | P2 | schema 摘要 | 缺失哨兵（"未登记"）、合计行没识别 | 7（列画像） |
| B22 | P3 | tools/csv_io.py | Big5 可能被 gb18030 误解码成错字（已写进文档，可显式传 encoding） | 7（DuckDB 读入时再看） |
| M13 | — | 接口 | 只有 png + 结果文本，没有给前端自己画的结构化图表数据 | 5 第一件事 |

不在表里的 B 编号都已解决，证据在各自的记录里。

### 测试
tests/test_server.py 13 项通过（新增 1 项、加 1 条断言）。全量见 PR 的 CI。

### 下一步
1. B20：迁移 `create_react_agent`（单独 PR），迁完 S 重跑闸门 25 题做回归。
2. 阶段 5：先定图表库和 M13 的数据格式。

---

## [20] 2026-10-13 · 阶段 4 收尾：ReAct 主循环自建，替代已弃用的 create_react_agent（B20、B21）· commit cdaf0f6（PR #20）

### 改动
- B20：app/react_agent.py 不再 import `langgraph.prebuilt`。`build_loop()` 用 StateGraph 搭"agent → tools → agent"循环（约 60 行），不新增依赖（没有选 langchain 1.x 的 `create_agent`，见 [19] 之后与 S 的讨论：多一个依赖要锁版本、进打包体积和许可证审计，且重试仍在 SDK 里）。
  - 与原来一致：系统提示在每次调用时放在最前，不进状态（多轮记忆里只有用户 / 助手 / 工具消息）；状态 messages 用 add_messages 合并，可接 checkpointer；步数仍由 recursion_limit 控制，一轮 = agent + tools 两步，用完抛 GraphRecursionError，由 service 强制收尾（B61）；一次多个工具调用按顺序执行，ToolMessage 顺序与 sink["execs"] 一致；未知工具名、参数缺失把错误作为工具结果回给模型（原 ToolNode 的行为）。
  - 不同：原来步数快用完时 prebuilt 会塞一条 "Sorry, need more steps…" 当回复，现在不会了，统一走 GraphRecursionError。service 对这句话的判断（B39）保留，无害。
- B21：模型调用的重试从 openai SDK 挪到 agent 节点（只重试超时 / 限流 / 连接 / 5xx，按 LLMConfig 的 max_retries 与指数退避），SDK 的 max_retries 改为 0，每次重试记进 usage.retries。ReAct 的 retries 不再是 None。B62 / B69 的整轮重跑照旧，也计入 retries。
- 文档：core/llm.py 文件头关于两种 Agent 重试方式的说明同步更新。

### 相对 [19] 总表的变化
- 关闭 B20、B21。其余不变。

### 测试
- 新增 tests/test_react_loop.py 7 项：不再 import prebuilt；超时 + 限流各重试一次计 2；重试用完记 llm 错误且调用 3 次；鉴权错误不重试；未知工具 / 缺参数回给模型后能改对；一次两个工具调用按顺序；多轮记忆里系统提示只有一条且在最前。
- test_core_analyze 的 ReAct 用例 retries 断言由 None 改为 0。
- 全量 489 passed（Linux Python 3.12）；pytest 警告从 175 条降到 1 条（原来大部分是 create_react_agent 的弃用警告）。

### 需要 S 做
- 主循环换了实现，按约定重跑闸门 25 题做回归：`python scripts/gate/run_gate.py --agent react`。对照 [13] 的回归结果（react 14/15 + 8/10）；预期持平，若出现 ⑤（步数用完无结论）类失败要先看是不是"Sorry"占位消失带来的差异。

## [21] 2026-10-14 · B20 之后的闸门回归（25 题，仅回归）· commit 98c9087（PR #21）

### 结果
- 正式回归：docs/eval/gate_20261013_153017_react.json（git_sha cdaf0f6，Qwen3.5-397B-A17B，公司网关，questions_sha256 75a559642e4e）。执行成功 25/25，比较器 23/25；人工判定 react **14/15 + 9/10**，对照 [13] 的 14/15 + 8/10，不低于基线。
- 两道错题都是老问题，不是 B20 引入的：
  - s02：4373，正确答案 4372（与同日旧代码结果相同；脏数据口径，B65 一类）。
  - m10：没有以「无法回答：」拒答，拿「售价 + 运费」当利润给出 73 个类别的表（⑥，B63 一类）。[13] 回归里 m10 同样错过，系统提示和工具说明这次没改，判为模型波动。
- [20] 担心的 ⑤（步数用完无结论，"Sorry" 占位消失带来的差异）：本次 0 例。
- 同日对照：docs/eval/gate_20261013_151425_react.json 在 S 本地旧代码（git_sha cf277ed）上跑，比较器 24/25，唯一差别是 m10 那次拒答正确。总耗时 295 s → 349 s、tokens 266k → 281k，多出的主要是 m10（15 s → 36 s）；单次运行，不作为性能结论。

### 作废的报告
- gate_20261013_145244_react.json、gate_20261013_145442_react.json 已删除：S 的 .env 整份被注释，DEEPSEEK_MODEL / DEEPSEEK_BASE_URL 回退到默认的 deepseek-chat + api.deepseek.com，用公司网关的 Key 每题都是 llm 错误（0/25）。Key 放钥匙串时，.env 里 Key 那行可以注释，模型和地址两行不能注释。

### 相对 [19] 总表的变化
- 无新增、无关闭。B63（拒答时自拟口径）仍开着，m10 是它的复现。

### 下一步
- 阶段 5 开始：先定图表库与 M13 结构化图表数据格式。

## [22] 2026-10-14 · 阶段 5 第 1 步：M13 图表格式、白名单、builder，静态覆盖率 · commit 89a9b05（PR #22）

### 决定（S 的 M13 方案 v3，与 H 两轮讨论后定稿）
- 不引入 pyecharts。前端用 ECharts；后端只产出 option JSON，样式（主题、开关、面板 DIY）全在前端。
- v1 唯一入口是 builder：模型只选图型、列和标题，数据层（xAxis.data / series[].data）全部从 df 生成，模型写不进数字；不产出 dataset。v1 图型 bar / line / area / pie / scatter，其他图型走 matplotlib PNG 退路；覆盖不足时加图型，不开放自由 option 字典。
- option 分数据层 / 样式层；轴范围、visualMap 分段、排序只允许用户手动改。层 2（一句话改样式）放 v2，用丢弃式白名单。
- 安全：前端统一 tooltip.renderMode = 'richText'，不开 dataView，aria 保持关闭；白名单禁 title.link / sublink / graphic / formatter / dataset / 函数值；字符串限长 + 清控制字符；校验不过整图拒绝并给原因。注入实测放第 5 步，结果写进 THREAT_MODEL。
- B44：chart() 不抛异常、返回 None（option 记在 worker 槽位，最多 4 张），chart_error 与 error 分开；exec 内模型自己的 matplotlib 异常不修。result.charts 升级为 [{png, option}]。
- 回归门槛（改提示词后）：单表 ≥ 14/15、多表 ≥ 8/10，m10 波动不计；图表冒烟两条：出图率（调了 chart() 或 plt 的题里每轮至多 1 题无图）、chart_option 链路（调了 chart() 的题全部产出合格 option），外加 cases.py 3 道 has_chart 题全部产出。不改闸门题面。
- 阶段归属：后端三步记在阶段 5，plan.md 第一件事已改写，阶段 5 重估 1–2 周 → 1.5–3 周。

### 改动
- 新增 app/tools/charts.py：
  - `build_option(kind, df, *, x=None, y=None, series=None, title=None)` 纯函数，返回 `{"v": 1, "kind", "truncated", "option"}`。df 可为 DataFrame 或 Series（Series 的索引作默认 x）；y 为一列或列表（宽表），series 为分组列（长表，按 x 首次出现顺序透视，同一 (x, series) 多行要求先聚合）；y 不给时若只有一个数值列就用它。NaN / ±inf → null，numpy 标量转原生，时间 → ISO；每图最多 5000 点（超出截断并置 truncated），最多 20 个系列，饼图最多 50 个扇区且不能为负。失败抛 ChartError（中文原因，给模型看）。
  - `validate_spec(spec)`：键白名单 + 叶子类型 + 枚举值（tooltip.trigger、series.type 等）+ 颜色必须 #RRGGBB + 按图型校验 data 形状和长度 + 点数上限 + `json.dumps(allow_nan=False)`；返回问题列表，非空即整图拒绝。builder 出口也过一遍。
  - 默认样式层：主色与 plotting.PALETTE 相同，标题居中，多系列才显示图例，grid containLabel。
- 新增 scripts/chart_coverage.py：静态扫描 docs/eval 下所有报告的 code，按 plt.x / ax.x / df.plot(kind=) / df.plot.x() 三种写法归类图型和结构（twinx、多子图、堆叠）。
- 尚未接入沙箱和接口（第 2、3 步）。

### 静态覆盖率（方向性，正则判断，不重放）
- 35 份报告、955 份画图代码（同一题跨多轮重复很多；去重后 109 道题）。
- 按样本：五类完整覆盖 899/955 = 94%；按题（多数票）：98/109 = 90%。两种口径都达到 ≥ 90%，v1 就做这五类。
- 缺口（口径有误，把"份"当"题"报了，以 [23] 为准）：直方图 6 题（8 份）；散点 + 趋势线混画 4 题（corr_004 等，v1 一次只出一种图型）；双轴 2 题（ts_010、ord_020）；热力图（相关矩阵）少数几次。
- 处理：直方图不加图型，提示词里写"先 pd.cut / np.histogram 分箱，再 chart('bar')"；双轴、热力图、散点加趋势线走 plt 退路。第 4 步重跑闸门时看实际情况。
- 局限：样本全部来自自造评测集和闸门，题型分布不代表真实用户；正则可能误判 stacked（如 subplots_adjust(bottom=)），不影响覆盖判定。

### 测试
- 新增 tests/test_charts.py 45 项：五种图型、宽表 / 长表、Series 输入、NaN / inf / 时间转换、不改输入、截断、控制字符与长度清洗、HTML 载荷按纯文本保留、各类报错，以及白名单拒绝（link / sublink / graphic / dataset / formatter / renderMode / aria / toolbox / visualMap / yAxis.min / 非法 data / 非法颜色 / 控制字符 / 函数值 / 点数超限）。

### 相对 [19] 总表的变化
- M13 进行中（第 1 步完成）。其余不变。

### 下一步
- 第 2 步：worker 注入 chart()、out 加 chart_error 与 option 槽位，result.charts 升级为 [{png, option}]（改 result.to_record 与 server/app.py 的消费点）。

## [23] 2026-10-14 · 阶段 5 第 1 步复核修正（S 复核 [22]）· commit 9c42819（PR #23）

### 复核结论（S 实跑脚本）
- 955 / 899 / 94%、45 项测试、plan.md 改动、docs/eval 已在主干：属实。
- [22] 的头条"98/109"用仓库里的脚本复现不出来（脚本只打印按样本的数字）；缺口数字把"份"当"题"报了。均已修，见下。

### 改动
- scripts/chart_coverage.py
  - 加 `--by-case`：按题多数票统计并列出未覆盖的题，平票单列 tie。
  - 原来的 mixed 拆成三类（S 指出混了两件事，人工看过后实际是三件）：multi_figure（多张独立的图，按 plt.figure / subplots / close 分段判定，v1 每次最多 4 张 → 覆盖）、degraded（折线 + 少量 scatter 高亮点，列表字面量或 zorder → 主图能出、高亮点丢 → 覆盖但降级）、overlay（同一张图叠两种图型，如散点 + 趋势线 → 未覆盖）。
  - stacked 注明只统计、不参与判定（堆叠是前端开关）。
  - tests/test_chart_coverage.py 3 项钉住判定规则。
- app/tools/charts.py
  - 缺失类目（pd.NA / NaN / None / NaT）统一显示为"（缺失）"。原来 pd.NA 会变成字符串 '<NA>'，被当成一个真实类目，和闸门 class 2 抓到的"缺失值被当有效取值"是同一类问题。饼图跳过缺失值的扇区。
  - 错误消息里的列名只清控制字符、限长，不转义（规则见 THREAT_MODEL §2.3）。
  - 白名单只保留 builder 实际产出的键：删了 stack / smooth / label / itemStyle / title.textStyle / axisLabel.rotate / areaStyle.opacity，等有消费方再加。radius / center 是饼图在用的，保留。
  - 新增 spec.kind 与 series[].type、areaStyle 的一致性校验（area = line + areaStyle）。
  - 注释写明 validate_spec 的定位：v1 里只校验 builder 自己的产出，防的是 builder 的 bug。**它不是 v1 的安全边界**：模型拿不到 option（chart() 返回 None），v1 的边界是 chart() 的签名（只能传图型、列名和标题字符串）；v2 层 2 的 patch 才是它的第一个外部输入。[22] 里把白名单写成安全措施，说法过头了。
- tests/test_charts.py 45 → 55 项：
  - 脏数据：pd.NA / NaN / None 类目、nullable string / Int64、GBK 中文列名（经 csv_io.read_csv 读入）、合并表头（多级列名报错）、合计行和"未登记"原样出图。
  - kind 不一致。
  - 错误消息里的列名：原样保留，但去掉控制字符。
  - HTML 用例改名为 test_builder_passes_html_payload_through_unescaped，注释写明它只证明载荷能到达前端。
- docs/THREAT_MODEL.md 新增 §2.3（T9）：后端不转义，渲染边界转义；逐个面写明怎么兜（canvas / richText / 白名单 / 错误、警告、结论、日志在 UI 层按纯文本渲染），第 5 步的断言打在渲染后的 DOM 上，至少测 tooltip、错误消息、结论文本三个面。

### 覆盖率（更正 [22]，`python scripts/chart_coverage.py --by-case` 可复现）
- 按样本：严格 899/955 = 94%；算上多图和降级 909/955 = 95%。
- 按题（109 题，多数票）：严格 98/109 = 90%；算上多图和降级 100/109 = 92%。
- 未覆盖 9 题：
  - 直方图 5 题：emp_004、emp_012、emp_025、inv_024、ord_028。
  - 散点 + 趋势线 2 题：corr_004、emp_015。
  - 双轴 1 题：ts_010。ord_020 按多数票算覆盖。
  - 平票 1 题：ord_016（柱状图 1 次，热力图 1 次）。
- 降级 2 题：inv_008、inv_018（折线 + 高亮点）。S 原先算进"散点 + 趋势线 4 题"，看代码后发现是折线加 scatter 标点。
- 仍然达到 ≥ 90%，v1 就做五类。处理方式不变：直方图写进提示词（先分箱，再画 bar）；散点 + 趋势线、双轴、热力图走 plt。

### 已定语义（第 2 步照此实现）
- **exec 失败时，槽位里已有的 option 一律丢弃，不随结果返回。** S 的建议是保留并标 exec_failed、前端降级显示，我没有采纳。理由：
  - 与现状一致。sandbox.py:229-230 在 exec 出错时已经不返回 PNG，option 也应该同样处理。
  - 和 S 已经接受的论证同构："exec 内失败，保留可能不完整的产物比丢弃更危险"，图是最强的视觉背书。
  - ReAct 失败后会重跑，图会在成功的那次重新出来。
  - 丢弃的张数写进 exec 事件（charts_discarded），可追溯。
- **truncated = True 必须在 UI 可见。** worker 写进 warnings（"图表只显示前 N 个点"），前端在图上加角标。不做静默降级。
- **chart_option 链路的口径**（删掉 v3 §8.3 的括号）：分母是调了 chart() 的题，分子是产出合格 option 的题。ChartError（模型选错列、参数冲突）单独列出，计为未通过；非 ChartError 的异常（我们自己的 bug）单列并报警，不算模型的错，但必须清零。

### 不做的（S 建议过，理由记下）
- builder 不识别"合计""未登记"这类行：同名的真实类目可能存在，猜错会静默删数据。清洗归上游代码 / 数据层（B65）。单测钉住的是"原样出图、不删行"。

### 测试
- CI 通过：PR #23 的 tests workflow run 38506506126（Linux / Windows × Python 3.11 / 3.12 全量 pytest）。另：本地沙箱 3.12 全量 547 passed。

### 下一步
- 第 2 步：worker 注入 chart()、out 加 chart_error 与 option 槽位、按上面的语义丢弃或告警；result.charts 升级为 [{png, option}]，同时改 result.to_record 和 server/app.py:137-138。

## [24] 2026-10-14 · 阶段 5 第 1 步二次复核（S 复核 [23]）+ 第 4 步闸门重跑预登记 · commit 8350e58（PR #24）

### 采纳 [23] 的两条待定（S 确认）
- exec 失败丢弃 option：S 核过 sandbox_worker.py，exec 出错时 savefig 被 `if out["error"] is None` 守卫跳过、本来就不返回 PNG，丢 option 是对齐现状。**补充（S）**：丢弃数量除了进 exec 事件的 `charts_discarded`，也写进 warnings（"本次执行失败，丢弃了 N 张图"），因为流式事件不一定被看到。
- builder 不识别"合计""未登记"：清洗归 read / clean 层（B65，阶段 7 列画像）。后果见下面的预登记。

### 改动
- docs/THREAT_MODEL.md §2.3：
  - 表格每行注明 v1 / v2 是否生效。v1 挡 T9 的是 chart() 签名 + 前端渲染（canvas、richText、纯文本）；白名单禁 formatter / link / sublink / graphic / aria / toolbox 在 v1 是不可达路径，v2 层 2 才生效。原表把它们列成防线，与 charts.py 注释"validate_spec 不是 v1 的安全边界"矛盾，已改。
  - 验证字段清单拆成"v1 可达"（title.text、series[].name、类目、轴名、错误消息里的列名）和"仅 v2 可达"（formatter 系、link/sublink、aria），后者放到层 2 再测。
  - 写明 renderMode 的矛盾：它在 BANNED_KEYS 里，前端又在校验之后统一加 richText，最终渲染产物必然不过白名单。规则：白名单只校验 builder 输出（v2 起含 patch），最终产物永不回验；回灌流程只传样式差量、重新走 builder，渲染端重新注入 richText；**不得从 BANNED_KEYS 删 renderMode**。charts.py 在 BANNED_KEYS 旁同样注明；tests/test_charts.py 原有用例已钉住 renderMode 在禁用集里。
- scripts/chart_coverage.py：uncovered_layout 拆开。多子图（subplots(r, c)，r×c ≤ 4，每格五类之一）新判 multi_panel，可拆成 N 次 chart()，与 multi_figure 同口径算进宽口径；双轴、子图 > 4 格或格数认不出，仍为 uncovered_layout。tests/test_chart_coverage.py +1 项（1×2 → multi_panel；2×3 → 未覆盖；子图里有双轴 → 未覆盖）。

### 覆盖率（更新 [23]）
- 原 uncovered_layout 15 份 = 双轴 13 份（ts_010 10、ord_020 3）+ 多子图 2 份（都是 corr_007，1×2 两张柱状图）。拆开后按样本：严格 899/955 = 94% 不变，宽口径 909 → 911/955 = 95%；按题不变（corr_007 本来就按多数票算覆盖）：严格 98/109 = 90%，宽口径 100/109 = 92%。
- 这些数都是**下界**：正则只认得出写法，认不出"能否改写成五类"。例如 overlay 里的趋势线可以去掉，tie 的 ord_016 有一次画的就是柱状图。缺口清单同样按下界读。
- **ts_010 是 10 : 9 接近平票**（双轴 10 份、单图 9 份），分类脆弱：再多一份单图就翻成覆盖。它不改变 ≥ 90% 的结论。
- 覆盖率脚本不在 CI 里跑，数字是方向性判断，不是 CI 验证的结果（局限同 [22]）。

### 第 4 步闸门重跑：预登记（在改提示词之前写下）
第 3 步会改 CHART_GUIDE（react_agent.py 和 workflow 的 codegen / reviewer 都用它），所以两个 Agent 都要重跑 25 题。M13 改的是画图，对 class ②（脏数据：缺失哨兵、合计行）的贡献上限是 0；B65 是 P2、阶段 7 列画像才修。下面这些失败**预期原样复现，复现不算回归，也不算 M13 的失败**：

| 题 | Agent | 类 | 已知原因 | 最近一次 |
|---|---|---|---|---|
| s02 | react、workflow | ② | "未登记"当成一个客户（4373 vs 4372） | [21] react 仍错；[12] workflow 仍错 |
| s04 | workflow | ② | 报表变体的合计行算进"非英国" | [12] workflow 仍错 |
| s12 | workflow | ② | 没认出"未登记"是缺失，答 0.0% | [12] workflow 仍错 |
| s09 | workflow | ③ | 按正数量汇总，选中被整单取消的 80,995 件 | [12] workflow 仍错 |
| m10 | react | ⑥ | 应拒答，自拟利润口径（B63，波动） | [21] 错，[13] 错，151425 对照对 |

注意（更正 S 原文的一处）：s04、s12 的 class ② 失败**只在 workflow**。react 上 s04 自 [12] 起是对的（912,621），s12 一直是对的；react 若在 s04 / s12 失败，**算回归**。

判定（沿用 [22] 的门槛，口径写死）：
- react：单表 ≥ 14/15，且唯一允许的错题是 s02；多表 ≥ 8/10（原文照抄 [22]），m10 错不计入回归判断，即 m10 之外最多再错 1 题。
- workflow：单表 ≥ 11/15，错题只能落在 s02 / s04 / s09 / s12；多表 ≥ 9/10（[12] 是 10/10，单次运行，留 1 题波动）。workflow 的门槛是本条新定的，[22] 只给了 react 的。
- 上表之外的任何新错题都算回归，先看是否与提示词改动有关再下结论。
- 预期失败的题若**意外答对**，记录但不改门槛（多半是波动，参考 m10）。
- 图表两条（出图率、chart_option 链路）按 [22] / [23] 的口径另算，与准确率分开报。

### 测试
- tests/test_chart_coverage.py 3 → 4 项；全量见提交说明。

### 相对 [19] 总表的变化
- 无新增、无关闭。B65 维持 P2 / 阶段 7，本条把它在闸门上的影响写成预登记。

### 下一步
- 第 2 步：worker 注入 chart()、option 槽位、chart_error；exec 失败丢弃 option 并写 charts_discarded + warnings；truncated 进 warnings；result.charts → [{png, option}]，改 result.to_record 和 server/app.py。

## [25] 2026-10-14 · 闸门判定机制修复：门槛进配置、基线报告补标注（S 复核 [24]）· commit ffe92c8（PR #25）

### S 复核 [24] 指出的问题（均核实属实）
1. react 多表门槛抄了 [22] 的旧值 8/10。[21] 的最新基线是 9/10（只错 m10），门槛比基线松一题。
2. 门槛没有代码化：run_gate.py 的 `--verdict` 仍用阶段 3.5 的常量 11 / 8 / 4，重跑后会把 react 11/15 判成"可用"；verdict 段也不记录用的是哪套门槛，事后无法从 JSON 反查。
3. 基线报告没有人工判定：gate_20261013_153017_react（[21] 的正式回归）、gate_20261012_142736_workflow（[12] 的 workflow 回归）human_correct 都是 0/25，[21] 的 14/15 + 9/10 和 [24] 的预期失败表只存在于 DEVLOG 文字里，`--verdict` 对它们直接退出。
4. [24] 的 SHA 未回填（按惯例在本次提交填：8350e58）。

### 改动
- 新增 docs/gate/thresholds.json，门槛只从这里读，分两套 profile：
  - phase35：阶段 3.5 原判（11 / 8 / 4 + 分布规则），从 run_gate.py 的常量原样搬出。tests 用 10-12 两份终审报告验证：用 phase35 重出结论，与报告里存的 verdict 逐项一致。
  - m13：阶段 5 改 CHART_GUIDE 后的回归。规则是错题必须全部落在 allowed_fail 里，之外的错题逐题列为回归；allowed_fail 里的题若答对，列为"意外答对"，只记录，不改门槛。
    - react：单表只允许 s02 错（≥ 14/15）；多表只允许 m10 错（≥ 9/10，**修正 [24] 的 8/10**）。
    - workflow：单表只允许 s02 / s04 / s09 / s12 错（≥ 11/15）；多表不允许错（10/10）。**这条比 [24] 写的 ≥ 9/10 严**：[24] 同时写了"上表之外的任何新错题都算回归"，两句矛盾，9/10 的那 1 题容差实际不可用。按"错题必须在名单里"统一口径，[12] 的 workflow 多表基线是 10/10。请 S 确认。
- scripts/gate/run_gate.py：
  - `--verdict` 必须带 `--profile`，不给就退出，不再有默认门槛。
  - verdict 段写入 profile 名、门槛原文、thresholds.json 的 sha256 前 12 位、labeled_by；m13 下再写每组的 min、regressions、unexpected_pass 和总的 regression_verdict。
  - labeled_by 含"待 S 终审"时 verdict 写 labels_final=false，表示结论建立在预标注上。
  - 改门槛只能在 thresholds.json 新增 profile，不改旧的（文件头注明）。
- 基线报告补标注（labeled_by："Hark 预标注……待 S 终审"），并用 `--profile m13` 出了 verdict：
  - gate_20261013_153017_react（cdaf0f6）：14/15 + 9/10。错题 s02（②，4373）、m10（⑥，首句说无法计算利润，但随后给出"售价 + 运费"的 73 类收入表，result 不是拒答）。逐题看过比较器判 relaxed / scaled 的 s07、s08、s13、m08，都与 gold 一致。m13 结论：无回归。
  - gate_20261012_142736_workflow（9430354）：11/15 + 10/10。错题 s02（②）、s04（②，6,089,071 = 912,621 + 合计行 5,176,450）、s09（③）、s12（②，答 0%）；s07 是比较器漏判（B68，已修），实为对。与 [12] 正文一致。m13 结论：无回归。
  - S 终审后把 labeled_by 改成"S 终审"，重跑 `--verdict … --profile m13`。
- docs/gate/README.md、docs/roadmap/gate-phase35.md 的用法同步。
- tests/test_gate.py +4 项：m13 回归判定（无回归 / 有回归 / 意外答对 / workflow 名单）、未知 profile 退出、phase35 复现 10-12 两份终审结论（2 项）。

### 仍不对称（记下，不在本条解决）
- react 基线是 cdaf0f6（B20 之后），workflow 基线是 9430354（阶段 3.6），中间隔了阶段 4 和 B20，不是单变量对照。建议：改 CHART_GUIDE **之前**，S 在当前 master 上把两个 Agent 各跑一次闸门，作为第 4 步的新基线；新基线若与 m13 名单不符，名单不改，在下一条 DEVLOG 写明差异，由 S 定是否新增 profile。

### 测试
- tests/test_gate.py 34 passed（沙箱 3.12）；全量见提交说明，CI 结论以 PR 的 tests workflow 为准。

### 相对 [19] 总表的变化
- 无新增、无关闭。

### 下一步
- S 终审两份基线标注、确认 workflow 多表 10/10；（建议）在当前 master 上重跑两个 Agent 作新基线。
- 然后第 2 步：worker 注入 chart()（charts_discarded 同时进 warnings），再第 3 步改 CHART_GUIDE。

## [26] 2026-10-14 · 阶段 5 第 2 步：沙箱 chart()、option 槽位、丢弃与告警、charts 条目化 · commit 7d21d63（PR #26）

### 做了什么（不改提示词，模型此时还不知道 chart() 存在；第 3 步才改 CHART_GUIDE）
- app/tools/charts.py
  - ChartSlot：注入沙箱命名空间的 `chart(kind, df, x=, y=, series=, title=)`。**永不抛异常、返回 None**（B44）；参数绑定也在 try 里做（参数个数 / 名字不对 → ChartError，不是 TypeError 冒出去）。每次执行最多 4 张，超出记 ChartError。
  - 错误分两类（[23] 口径）：ChartError（模型参数问题）→ chart_errors；其他异常 → chart_internal_errors（我们的 bug，logger.error 报警，必须清零）。
  - 新增 ChartBugError：build_option 自己的产物没过白名单时抛它，不再抛 ChartError——那是 builder 的 bug，不能记成模型的错。
  - accept_worker_charts：**主进程**对沙箱回传的图表字段做最终校验。模型能拿到 chart 对象本身（`chart.specs`），理论上也能改沙箱里的模块，所以 worker 里的一切只算候选：主进程限条数、每个 spec 重跑 validate_spec、消息清控制字符并限长、计数只收合法整数，truncated 警告也在这里生成。用例钉住"在沙箱里给 spec 塞 formatter → 主进程拒绝"。
- app/tools/sandbox_worker.py：exec 结束后在独立 try 里收尾槽位；exec 失败（含 result 无法回传）→ 槽位里的图全部丢弃、记 charts_discarded。
- app/tools/sandbox.py：run_code 返回值不变（仍是三元组），图表字段经 capture 回传：charts、chart_calls、chart_errors、chart_internal_errors、charts_discarded、chart_warnings；exec 失败时 charts 强制为空（双保险）。
- 结果与事件
  - AnalysisResult.charts 改为条目列表 `[{"png": 路径或 None, "option": spec 或 None}]`：同一次执行里 chart() 的图在前、matplotlib 的 PNG 在后（前端优先用 option，PNG 是退路）。chart_path 仍是最后一张 PNG。
  - 新增字段 chart_calls、chart_errors、chart_internal_errors、charts_discarded（chart_option 链路的分子分母从这里取）。
  - exec 事件新增 options、chart_errors、charts_discarded。
  - warnings（S 在 [24] 的补充：流式事件不一定被看到）：
    - truncated → "图表「标题」数据点超过 5000，只显示了前面的部分"；
    - 有丢弃 → "有代码执行失败，失败那次用 chart() 画的 N 张图已丢弃，不展示"，后来成功出过图的再加"，展示的是成功那次执行的图"，免得用户以为最终的图也有问题；
    - 调了 chart() 却一张 option 都没出 → "图表未生成：<最后一条 ChartError>"；
    - 有内部错误 → "图表生成遇到内部错误，已记录"（细节只进日志）。
  - ReAct 工具返回给模型的文本：出了图加"（chart() 已生成 N 张图表）"，ChartError 加"chart() 未出图：<原因>"，让模型能改；**没用 chart() 时文本与之前逐字一致**（有用例钉住），所以这一步对闸门零影响。
- app/server/app.py：对外的 charts 也是条目，png 换成 URL；[26] 之前存进库的记录是路径字符串，按 PNG 条目兼容读出。

### 测试
- 新增 tests/test_chart_slot.py 17 项：chart() 永不抛 / 用法错误归 ChartError / 内部错误单列 / builder bug 不算 ChartError / 4 张上限 / exec 失败丢弃 / 主进程拒绝篡改与脏输入 / truncated 警告；沙箱子进程里的成功、ChartError 不影响 result、exec 失败丢弃（含 PNG）、篡改被主进程拒绝；工作流条目化、重试前失败那次的丢弃进事件与 warnings；ReAct 的 ChartError 回给模型并进 warnings、option 与 PNG 混合、没用 chart() 时工具文本不变。
- test_core_analyze 的 PNG 用例改为条目断言。全量见提交说明。

### 相对 [19] 总表的变化
- B44（chart() 不得因图表失败让整次分析失败）：结构化图这一半已做；matplotlib 在 exec 里报错仍按执行失败处理（与 [22] 的决定一致，不修）。

### 下一步
- 第 3 步：改 CHART_GUIDE（优先 chart()，五类以外走 plt；直方图先分箱再 chart('bar')），按 [25] 的 m13 门槛重跑闸门，图表两条另报。改之前，建议 S 先在当前 master 上重跑两个 Agent 作新基线（[25]）。

## [27] 2026-10-14 · 阶段 5 第 3 步：绘图提示词改为优先 chart()，图表冒烟进报告 · commit 063f242（PR #27）

S 决定（10-14）：跳过"当前 master 先重跑一次基线"，直接改提示词。归因依据仍是 153017（react）与 142736（workflow）两份历史报告：[22]–[26] 没有改过提示词，它们和当前 master 改提示词之前的行为等价，区别只在网关与模型本身的波动。

### 提示词改动（这是本条唯一影响闸门的部分）
- CHART_GUIDE（app/tools/plotting.py）重写：
  - 优先 `chart(kind, df, x=, y=, series=, title=)`，列出五种 kind 各自的用途；df 传算好的汇总表；排序、Top-N、分箱都先用 pandas 做好；直方图先 pd.cut 分箱计数，再用 'bar'；多列对比用 y 列表，长表用 series（先 groupby 聚合）；title 写清指标与单位；配色、横向、堆叠、标签归界面；chart() 无返回值、出错不打断代码、每次最多 4 张。
  - 五种图型表达不了时（双轴、箱线、热力、多子图）才用 plt，旧版的 plt 要求压缩成一条保留（中文标题/轴标签、数值标注、按位置标注字符串横轴、savefig(chart_path)）。
  - 同一张图不要既用 chart() 又用 plt。
- 工作流 codegen / reviewer："pd、np、plt 已就绪"加上 chart；reviewer 的"原代码若画了图"注明 chart() 或 plt。
- ReAct：工具说明的出图一行改成优先 chart()；系统提示"请务必画图并保存"→"请务必出图"。
- summarizer 与 ReAct 工具返回：chart() 出了图时告诉模型"已生成 N 张图表：<标题>"，让结论能说明图表展示了什么（之前只认 PNG 路径）。

### 图表冒烟进报告（与准确率分开，不影响 regression_verdict）
- 新增 app/eval/chart_smoke.py：
  - chart_row(res)：单题的 chart_calls、used_plt（静态扫描本次所有尝试过的代码）、options / pngs 张数、chart_errors、chart_internal_errors、charts_discarded。
  - summarize(rows)：出图率（调了 chart() 或 plt 的题里无图的题，≤1 为通过）、chart_option 链路（调了 chart() 的题都要产出合格 option，内部错误必须为 0）。
- scripts/gate/run_gate.py：每题写 `chart`，报告顶层写 `chart_smoke`，跑完打印一行；`--verdict` 对有 chart 字段的报告附 `chart_smoke`（旧报告没有就不附）。
- run_eval：每题写 `chart`，汇总里加 `chart_smoke`，并加上 has_chart 三题（agg_006 等）是否全部出图；print_summary 打印一行。

### 需要 S 跑的（预登记）
- 两个 Agent 各跑一次闸门：`python scripts/gate/run_gate.py --agent react` / `--agent workflow`，人工标注后用 `--verdict … --profile m13` 判定。门槛与允许失败名单按 [25] 的 thresholds.json，不因本次改动调整。
- 图表另报：闸门题没有要求画图的题，所以两条的分母可能很小甚至为 0，分母为 0 时这两条记"无样本"，不算通过也不算失败；has_chart 三题用 `python run_eval.py` 跑（两个 Agent 各一次），三题必须全部出图。
- 名单外出现新错题时，先看那题的代码有没有调用 chart() 或受提示词影响，再决定是回退提示词，还是记作波动。

### 测试
- tests/test_chart_slot.py 加 6 项：两个 Agent 都拿到新 CHART_GUIDE、summarizer 看得到图表标题、ReAct 工具文本带标题、冒烟汇总口径、plt 在失败尝试里也算"画过图"、没用 chart() 时工具文本不变。test_workflow_mocked / test_eval_cases 断言随之更新。

## [28] 2026-10-14 · 第 3 步闸门结果：通过（两题名单外错题经复跑记为波动） · commit be5cfa8（PR #28）

报告：docs/eval/gate_20261014_162428_react.json、gate_20261014_163133_workflow.json（S 在 063f242 上跑，78de005 推送）。标注为 Hark 预标注，S 已于 2026-10-15 终审通过；判定 `--profile m13`。

| Agent | 单表 | 多表 | 名单外错题 | 意外答对 |
|---|---|---|---|---|
| react | 14/15（s02 ②，同基线） | 9/10 | m09 ⑤：未调工具，结论是网关吐出的英文 `[Assistant reasoning summary]` 推理摘要，未按契约拒答 | m10 |
| workflow | 10/15（s02 s04 s09 s12 同基线逐字一致） | 10/10 | s06 ②：两行表头，把 `Unnamed: 3`（数量）当单价 | — |

- 归因（预登记判据：同一 commit 单题重跑，答对 ≥4/5 记波动，否则对旧提示词 7d21d63 做 A/B；判据隐含 5 次，但没写次数）：实际 m09、s06 各复跑 2 次，均 2/2 答对。**原判据 ≥4/5 未被满足（样本不够，不是少跑了几次而是判据被换了）**，改按 [30] 起草的 A1 规则（名单外错题复跑 2 次、2 次都对记波动）认定为波动，由 S 追溯承认（2026-10-15）；第 3 步不回退提示词。复跑报告见下（[30] 已提交进仓库并补了标注）：

  | 题号 | Agent | 报告 | 结论 |
  |---|---|---|---|
  | m09 | react | `docs/eval/gate_20261014_165504_react.json` | ✅ 正确拒答（无客户年龄字段） |
  | m09 | react | `docs/eval/gate_20261014_165536_react.json` | ✅ 正确拒答（无客户年龄字段） |
  | s06 | workflow | `docs/eval/gate_20261014_165312_workflow.json` | ✅ 1036 条（与 gold 一致） |
  | s06 | workflow | `docs/eval/gate_20261014_165603_workflow.json` | ✅ 1036 条（与 gold 一致） |
- 图表另报：react 9 题出图，全部 chart()，option 9/9，0 plt；workflow 7 题，option 7/7，0 plt；内部错误均为 0。出图率、chart_option 两条通过；has_chart 三题 S 报告通过。
- token 与基线持平（react +2.5%，workflow +0.1%）。

遗留（独立于 M13）：
- m09 暴露 ReAct 收尾缺口：B69 的整轮重跑（输入不变）3 轮都没救回来。改为在同一会话里先提醒一次，见 [29]（B70）。（更正：本条原写"目前直接记 agent 错误"，不对，B69 已经会重跑。）
- s06 归入真实数据适配（多行表头）既有问题，不在 M13 修。

## [29] 2026-10-15 · B70：ReAct 没执行代码也没拒答就收尾 → 同一会话里提醒一次 · commit 513f6e1

起因：[28] 的 react m09 用了 13351 token（同组正常拒答约 9.3k，单轮约 4.4k），说明 B69 的整轮重跑 3 轮全部失败。重跑的输入跟原来逐字相同，temperature 0 下很容易复现同样的输出（这次是网关吐出的英文 `[Assistant reasoning summary]`）。

改动（相对 [19] 问题表新增 B70）：
- `app/react_agent.py`：`build_loop` 增加 `nudge` 节点。最后一条是不带工具调用的结论、本轮没执行过工具、没提醒过，且结论不是契约拒答（B40）、不是网关错误内容（B62）、也不是步数占位（B39）时，把 `NUDGE_NO_EXEC` 作为用户消息补进会话，回到 agent 再试一次。每轮只提醒一次；提醒次数记进 `sink["nudges"]`。
- 只在单轮分析里开（`nudge_no_exec = memory is None and not history`）。多轮追问可以只凭上下文作答，与 B69 的豁免一致。
- `app/core/service.py`：发生过提醒时记一条 `Step("nudge")`。B69 的整轮重跑保留，作为第二道兜底；新的一轮仍可以再提醒一次。最坏情况下调用次数从 3 次变成 6 次。
- 测试：test_phase36 里 B69 的两条改写，新增"只提醒一次后走 B69""拒答、网关错误、带 history 的追问都不提醒"两条；test_core_analyze 非契约拒答用例的脚本回复从 3 条改成 6 条。

影响：只改变原本会被 B69 判失败或重跑的路径，正常路径的输入和调用次数都不变，闸门门槛不变。闸门是否重跑由 S 决定；若重跑，看点是 m09 的 steps 里有没有 nudge。

## [30] 2026-10-15 · 闸门工具修复：labels_final 双向、门槛哈希与行尾无关、复跑证据入库 · commit 4497d2b（PR #31）

来源：阶段 5 前端方案 v1 评审（`docs/roadmap/review-phase5-frontend-v1.md`）附录 A。S 复核后指定在 F0 之前单独提这个 PR —— 前端改动不碰提示词，所以这些不挡 F0，但挡"下一次闸门能不能信"。

- `scripts/gate/run_gate.py`
  - `load_profile` 读门槛文件时先把 CRLF 规范化成 LF 再算 sha256。原来直接哈希原始字节，而本仓库 `core.autocrlf=true`（工作区 CRLF、git 对象 LF）→ 本机 `--verdict` 写出 `8703d010bbe3`，两份基线记的却是 `4992a4016355`（实测复现）。哈希的用途是证明"这次用的是哪一版门槛"，这样一来就失效了。同目录 `verify_gate.questions_sha256` 一直是规范化过的，这次对齐。
  - `labels_final` 改成显式写 True/False。原来只有 `if "待 S 终审" in labeled_by: out["labels_final"] = False`，没有 else → 这个字段永远只能是 False，"已终审"没法表达。实测把 `labeled_by` 改成"S 终审通过"后重跑，键会**整个消失**，于是被手改成终审态的报告里仍留着上一轮的 False（10-14 两份基线即此状态）。
- `.gitattributes`：加 `docs/gate/*.json text eol=lf`。和上一条哈希规范化两道都做，工作区签出即 LF。
- 证据入库：10-14 那 4 份单题复跑报告（m09 ×2、s06 ×2）提交进仓库，`[28]` 补一张复跑结果表。原来"复跑记波动"这个结论只依赖工作区里几个未跟踪文件，不可独立复核。
- `tests/test_gate.py` 新增 2 条：`labels_final` 双向（`test_labels_final_is_written_both_ways`）；门槛哈希不随行尾变（`test_thresholds_hash_is_line_ending_agnostic`，本机 CRLF 时额外断言规范化确实生效，避免这条测试在 LF 环境下变成恒真）。
- 两份基线 `gate_20261014_162428_react.json` / `gate_20261014_163133_workflow.json` 用新代码重跑 `--verdict --profile m13`，`thresholds_sha256` 与 `labels_final` 落到终态。
- 复跑报告补标注：4 份原来 `human_correct` 全是 null、没有 `labeled_by`，`--verdict` 读不了；现逐题填 `human_correct: true` + `reason`，`labeled_by` 写明依据。4 份的 `git_sha` 记作 `78de005?`（本机 git 状态未知），78de005 相对 063f242 只多了报告文件，源码零差异，可接受。
- `labels_final`：`labeled_by` 为空时不写这个键（没人署名不能算终审；10-12 的老报告没有 `labeled_by`）。
- 门槛哈希测试改为同一内容各写 LF / CRLF 两个临时文件分别算、断言相等。原写法在 LF 环境（CI）下恒真。
- `docs/roadmap/M13-图表方案.md`（v4，随本条进仓库）：新增的"开关 × 产出键"原编号 §10，和"其余注意点"重号，且 §11 已被"风险与判据一览"占用 → 改为 §12，文首注解和 review 文档两处引用同步。
- 留痕：workflow 多表门槛由 [24] 预登记的 ≥9/10 收严到 10/10（`thresholds.json` 的 `m13.agents.workflow.multi.allowed_fail=[]`，[25] 实现、S 10-14 确认），依据 [28] 实测 10/10。[24] 正文不改，以本条为准。
- 未做（等 S 定案）：A1 的"名单外错题自动复跑 2 次，2 次都对记波动、有 1 次错记回归"规则。现行 `m13` 的 `allowed_fail` 是逐题登记的，`m09`/`m10` 这类会翻的题会让参照基线自己报"有回归"。S 不同意放宽名单（会把 B70 的效果盖掉），改走自动复跑 —— 规则定下来后随下一个闸门 PR 落地。S 已定（10-15）：该规则**取代** [28] 的 ≥4/5；复跑报告存原始 answer / result_text 并人工标注，不只存布尔（B68 前车之鉴）；超时、网关错误归为无效复跑，最多补跑 1 次，不计答错；verdict 注明假阴性率 ≤25%（真错误率 p=0.5 时）。

## [31] 2026-10-15 · 阶段 5 F0：前端骨架、同源托管、token 流转、CSP、feedback 表、CI · commit 4beb924（PR #32）

当前阶段：**阶段 5 前端，F0 完成，下一步 F1**（数据集含预览、会话、设置）。方案：`docs/roadmap/phase5-frontend.md`（v2.1，随本条入库）。[30] 的 SHA 已回填 4497d2b。

按方案 §6 的 F0 顺序：
1. **feedback 表**（`app/server/db.py` `Feedback`）：单独成表，`message_id` 即主键、外键级联删除；`rating` ∈ up / down / NULL，NULL 保留这一行；不记改评价历史。`PUT /messages/{id}/feedback`：只限助手消息（用户消息 400）、running 时 409；note ≤1000 字（422），清控制字符与双向文本控制符（保留 \t \n）。会话详情里每条助手消息带 `feedback`。
   - 旧库兼容：`test_v1_database_gains_feedback_table_without_touching_old_tables` —— 建库跑一轮后删掉 feedback 表还原成 v1 库，记下 6 张旧表的行数和 `pragma table_info`，重新 `create_app`：新表出现，旧表结构与行数完全相同，旧消息可直接评价。
2. **托管与 auth 边界**（`app/server/app.py`）：`/` 返回 `ui/web/dist/index.html`，`/assets/*` 挂 StaticFiles，二者免 token；其余 API 和 `/charts/*` 照旧要 token（测试逐个断言 401）。dist 位置 `default_web_dist()`：`DATACHAT_WEB_DIST` → 打包后 `_internal/web` → 源码 `ui/web/dist`；不存在时 `/` 返回 503 并提示 `npm ci && npm run build`。静态文件也受 TrustedHost 约束；路径穿越用例返回 404。
3. **token 流转**：`python -m app.server --open` 打开 `http://127.0.0.1:端口/#token=…`（测试断言只走 fragment、不进查询串）。前端 `ui/web/src/token.ts` 在渲染前同步读出 → sessionStorage → `replaceState` 抹掉；`src/api.ts` 是唯一出口，401 或没有 token 统一进"会话已失效"页（提示回命令行重新 `--open`）。
4. **CSP**：index.html 带 `default-src 'self'; img-src 'self' data: blob:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'`，外加 no-store / nosniff / no-referrer。
   - 内联脚本：实测 Vite 8.3.4 的 modulepreload polyfill 打在入口 chunk 里，index.html 本来就没有内联 script；仍设 `build.modulePreload.polyfill=false`。`npm run build` 末尾 `scripts/check-dist.mjs` 检查内联 script 和内联事件处理器为 0，否则构建失败。
   - Playwright 对照用例：往页面塞一个内联 `<script>`，断言没执行且 `securitypolicyviolation` 记到 script-src 违规 —— 证明 CSP 真的在生效、监听也真能抓到，"无违规"那条用例才有意义。
5. **CI**（`.github/workflows/tests.yml` 新 job `web`，ubuntu，Node 24 + Python 3.12）：npm ci → eslint（`react/no-danger`、禁写 innerHTML/outerHTML）→ vitest 12 条 → build（含 check-dist）→ Playwright（后端 `python -m app.server` 托管 dist，5 条）→ 上传 dist。Playwright 浏览器只在 CI 装。
6. **sidecar**：`sidecar.yml` 先构建前端，`build_sidecar.py` 把 dist 打进 `_internal/web`；`smoke_sidecar.py` 加 `check_web`：`GET /` 不带 token 200、CSP 含 script-src 'self' 与 frame-ancestors 'none'、引用的 `/assets/*.js` 取得到（本地对源码后端实测 ok；exe 版待本 PR 的 sidecar run）。

前端技术栈（`ui/web`）：React 19、Vite 8、TypeScript 6、vitest 5 + jsdom + testing-library、eslint 9 + typescript-eslint、Playwright 1.64。`node_modules` 约 170 MB（S 本机放 `D:\Coding\claude\datachat\ui\web`）；`package.json` `engines.node >=24`。

本机怎么跑（S）：`cd ui/web; npm ci; npm run build; cd ../..; python -m app.server --open`。开发时 `npm run dev`（Vite 把 API 代理到 127.0.0.1:8765，后端另开）。

文档：THREAT_MODEL §2.1 加 T6'（免 token 面）、T7'（fragment token）、T10（CSP）；§2.3 面表加 feedback note、预览单元格（F1）、Markdown img / 链接（F2）。plan.md 阶段 5 改为"M13 后端三步已完成 + 前端 F0–F5 另计 3–4.5 周"。

验证：pytest 587 passed（3.12；[30] 后 578 + test_web 9）；`tests/test_web.py` 9 条；vitest 12；Playwright 5（沙箱本地跑通）。

未做 / 下一步：F1 的 `GET /datasets/{id}/preview`；F2 的 cancel（按 v2.1：CAS + finally CAS + `done_seen` + 分流 cancelled）和 `gen_ui_types.py`。A1 自动复跑规则仍按计划在下一次闸门 PR 落地。

## [32] 2026-10-15 · 阶段 5 F1：数据集预览、会话、设置 · commit 7f0cdcd（PR #33）

当前阶段：**阶段 5 前端，F1 完成，下一步 F2**（SSE、事件渲染、重放合成 done、cancel、👍👎、gen_ui_types）。[31] 的 SHA 已回填 4beb924（PR #32，CI tests 38694679388 含 web job、sidecar 38694679138 均绿）。

后端（`app/server/app.py`）：
1. **`GET /datasets/{id}/preview?rows=20`**：rows ∈ 1–100（越界 400）。每个非字典文件一张表，按文件名排序；用与分析时**同一个** `read_csv_with_encoding`（同一编码探测、同一 read_csv），即"用户看到的就是模型拿到的"。返回 `{name, filename, encoding, total_rows, total_columns, columns, dtypes, rows}`；单元格缺失 → `null`，其余 `str()` 后超 200 字截断加"…"，不做 HTML 处理（前端按文本渲染，T9）。一张表读失败只在该表返回 `error`，不影响其他表；字典文件列在 `dicts`。
   - 已知代价：预览读整表再取 head（与详情接口一样），大文件会慢；量到再说（可加按 sha256 的缓存或 nrows 只读头部——后者会让编码探测和 dtype 与分析时不一致，不默认采用）。
2. **`PATCH /sessions/{id}` `{title}`**：≤200 字（422），清控制字符与双向文本控制符后截到 120 字。
3. **设置加 `timeout`**（单次请求超时，秒，5–600，越界 422）：存 Setting 表，`llm_config()` 转 float；库里的坏值退回环境变量 / 默认 60，不让分析整个起不来。`GET /settings` 返回生效值。`SettingsIn` 的 model / base_url 加长度上限。PUT 里空串 = 清除，回到环境变量 / 默认（原行为）。

前端（`ui/web/src`）：
- `types.ts`（接口形状；F2 起事件类型改由 gen_ui_types 生成）、`client.ts`（各接口薄封装，全部经 `Api`）。
- `views/Shell.tsx`：左栏 上传（多选 CSV，可带 *.dict.csv）、数据集列表、会话列表、设置；没设 Key 时首屏直接进设置页，其他页顶部提示。
- `views/DatasetView.tsx` + `PreviewTable.tsx`：摘要、文件与大小、字典文件、多表切换、前 20 行预览（表头带 dtype；缺失值显示灰色"空"，与字符串 "null" 区分）；选工作流 / ReAct 新建会话；删除。
- `views/SessionView.tsx`：标题就地改名（回车 / 失焦提交）、删除、历史消息纯文本 + 状态徽标（失败 / 已取消 / 分析中）。事件流、图表、提问、停止、👍👎 是 F2 / F3。
- `views/SettingsView.tsx`：Key 只写不读（password 输入，保存后立即清空；显示来源 环境变量 / 钥匙串；env 优先时给说明；只有钥匙串来源才给删除）；model、base_url、超时（前端先拦 5–600，后端再拦）。
- 删除一律"点两次确认"（不用 window.confirm：WebView 与 Playwright 对原生对话框处理不一致）。
- 样式 `styles.css`（基础样式；4 套主题在 F3）。

测试：
- `tests/test_web_f1.py` 7 条：预览与 `read_csv` 逐格一致；rows 边界 / 401 / 404；GBK + 缺失 + 注入串原样 + 超长截断；多表 + 字典 + 一张空文件只坏一张；改名清控制字符 / 422 / 404 / 401；超时设置与越界、只改 model 不动 timeout；库里坏值回退 60。
- vitest 17（+5）：`views/views.test.tsx` 预览与消息里的注入串只作文本（无 img、`window.__pwned` 未定义）、"空"与 "null" 区分、改名走 PATCH 并刷新左栏、无 Key 进设置页且保存后输入清空、页面文本不含 Key、超时越界不发请求、删除要点两次；`fakeBackend.ts` 测试用路由。
- Playwright 6（+1）`e2e/f1.spec.ts`：在后端托管的 dist（带 CSP）上走 设置超时 → 上传含注入串的 CSV + 字典 → 预览按文本渲染、tbody 无 img → 建 ReAct 会话 → 改名 → 刷新后会话名与超时都在；全程无 CSP 违规。

验证：pytest 594 passed（3.12；587 + test_web_f1 7）；vitest 17；Playwright 6（沙箱本地）；lint、build（check-dist 0 内联）通过。

未做 / 下一步：F2。A1 自动复跑规则仍按计划在下一次闸门 PR 落地。

## [33] 2026-10-15 · 阶段 5 F1.1：F1 评审收尾（预览并入详情、方向控制符、截断计数、token 先存后抹） · commit cccddd5（PR #34）

当前阶段：**阶段 5 前端，F1.1 完成，下一步 F2**（SSE、事件渲染、重放合成 done、cancel、👍👎、gen_ui_types）。[32] 的 SHA 已回填 7f0cdcd（PR #33，CI tests 38699875135、sidecar 38699875296 均绿）。

起因（S 评审 F1）：
- 预览读整表的理由要写对：`detect_encoding` 对**整个文件**做严格解码；只读头部，前面全是 ASCII 的 GBK 文件会被判成 utf-8，整表读坏，而不只是 dtype 不一致。所以不改成 nrows。真正的代价不是"慢"：`DatasetView` 并发请求详情和 `/preview`，同一个 CSV 被整表读两遍，每遍 bytes / str / DataFrame 三份并存，1 GB 文件峰值 4–5 GB。
- 详情原来用 `load_data` 整体 try：多表任一张坏，整个详情都没有 `tables`；"一张坏、其余照常"只在 `/preview` 层成立。
- 表名、排序两条路径不一致：分析用 `table_paths`（`splitext(basename)`、按表名排、大小写敏感、`os.listdir`），`/preview` 按文件名小写排、用 DB 的 `ds.files`。`B.csv + a.csv`：前者 [B, a]，后者 [a, B]。

后端（`app/server/app.py`）：
1. **预览并入 `GET /datasets/{id}?rows=N`**：`rows: int | None = Query(None, ge=1, le=100)`；不传就不带预览，越界和非整数都是 422（原来越界 400、`abc` 422）。删掉 `/preview`（只在 F1 前端用过，未对外）。`POST /datasets` 的响应带 20 行预览（`create_dataset` 本来就返回 detail），前端上传后不用再请求。
2. **详情逐表读、每个文件只读一遍**：直接用分析路径的 `table_paths(dataset_target(ds))` 枚举（多表 → [(表名, 路径)]；单表 None → `[("df", target)]`），表名、排序、字典过滤、重名检查与 `load_data` 结构性一致；每张表单独 try，一次 `read_csv_with_encoding` 同时出列名、概要、预览。坏表在 preview 里只带 `error`，好表的 `tables` 列名照常；任一张坏时顶层也给 `error`（分析时 `load_data` 会整体失败），概要写"x 读取失败"。单表表名沿用 `"df"`（prompt 里单表变量就叫 df；前端单表不显示 tab）。`table_paths` 本身抛（目录空、表名重复）→ 顶层 error。
3. **方向控制符**：拆成 `_BIDI_CONTROLS`（U+200E/200F LRM/RLM、U+202A–202E、U+2066–2069）和 `_CONTROL_CHARS`（C0/C1 除 \t \n + 上面这些；标题、note 用，字符集与 F1 完全相同）。预览的单元格与表头只清 `_BIDI_CONTROLS`（数据里 \r \t \n 合法）。只影响显示，模型拿到的仍是原数据，所以每张表返回 `bidi_stripped` 计数，提示行写明。
4. **截断计数**：每张表返回 `truncated_cells`，提示行写"n 个单元格超 200 字，已截断（末尾带 …）"；用户能区分原值本来就以 … 结尾的情况。
5. `db.py`：`ChatSession.updated_at` 加注释——语义是"最后一次提问时间"，只在 post_message 更新，改名刻意不更新，故意没有 onupdate。

前端（`ui/web/src`）：
- `client.dataset(id, rows=20)` 一个请求拿详情 + 预览；删 `client.preview`；`types.ts` 的 `DatasetDetail.preview`、`bidi_stripped`、`truncated_cells`。
- `DatasetView`：单请求；上传后直接用响应（Shell 传 `initial`），不再请求。不再单列 `summary`：单表时与预览提示行重复；多表的跨表概览并进 tab 标签（`orders 100×3 · gbk`、坏表"读取失败"）。顶层 error 显示"有表读取失败，分析会失败"。
- `PreviewTable` 提示行加截断数与方向控制符数。
- 左栏会话标题旁写"按最近分析时间排序"。
- `token.ts`：先 `setItem`（try/catch），再无论成败都 `replaceState` 抹地址栏，然后返回 token；存失败时 token 只在内存，本页可用，刷新进"会话已失效"页（T7'：token 不进历史）。原实现先抹后存、注释写反了，`setItem` 一抛会冒到 `main.tsx` 顶层同步调用，导致白屏。

测试：
- `tests/test_web_f1.py`（10 条）：单表预览与 `read_csv` 逐格一致、名为 df；上传响应带预览且与详情一致、不传 rows 无预览、列表无预览；rows 0 / -1 / 101 / abc / 1.5 均 422、401、404、旧 `/preview` 404；表头与单元格清方向控制符（计数 5）、注入串原样、截断计数 1；GBK；多表一张空文件：好表列名与预览照常、坏表只有 error、顶层 error 与概要；`B.csv + a.csv` 表名顺序为 [B, a]，且与 `load_data` 的表名、列名一致（回归网）；改名清 LRM/RLO/BEL，**改名不动 updated_at**。
- vitest 21（+4）：提示行的截断数与方向控制符数；详情只发一个请求、上传后不再请求；多表 tab 标签带行列数和编码、坏表与顶层 error 的提示；token 存储抛异常仍返回 token 且地址栏已抹、replaceState 时 token 已在存储里。
- `docs/THREAT_MODEL.md` 预览一行改为：清方向控制符并计数、截断计数。

未做 / 下一步：F2。`read_csv_with_encoding` 内部 bytes / str / DataFrame 三份并存的峰值内存（分析路径也一样，属于读取函数本身，不在 F1.1 顺手改；需要时改成解码后释放 bytes、或按块解码）。A1 自动复跑规则仍按计划在下一次闸门 PR 落地。

## [34] 2026-10-16 · 阶段 5 F2：SSE、事件渲染、重放合成 done、停止、👍👎、gen_ui_types · commit <待提交>

当前阶段：**阶段 5 前端，F2 完成，下一步 F3**（ECharts、prepare、主题、开关、换图型、导出、注入实测）。后端停止的语义经 S 三轮评审。[33] 的 SHA 已回填 cccddd5。

后端（已完成，细节见 phase5-frontend.md §1「停止的已定规则」）：
- `analyze_stream(cancel=threading.Event)`：每个事件产出前检查（answer 也是检查点），内部跑完、done 之前再查一次；置位 → `error_kind="cancelled"`，照常 fatal error + done。
- `POST /messages/{id}/cancel`：CAS running → cancelled（已结束 409、用户消息 400）；`stream()` 的 finally 也 CAS，不覆盖先落库的取消；`done_seen`。
- 状态与文案：cancelled 只用于用户点停止；非用户动作的终止（后端重启、SSE 客户端断开）→ `status=interrupted`；流异常没有 done → error + 常量文案，详情只进日志。文案全是 `app/core/events.py` 的常量；`db.MESSAGE_STATUSES`。
- `scripts/gen_ui_types.py` → `ui/web/src/generated/{events,banned_keys}.json`（事件类型、error_kinds、message_statuses、常量文案、BANNED_KEYS），CI `--check`。
- 测试 `tests/test_web_f2.py`：取消各路径、CAS、late-cancel、answer 检查点、断开 → interrupted、先 cancel 后断开仍 cancelled、重启 → interrupted、流异常文案不带异常；AST 约定：只有 service.py 写 error_kind（评测 `ground_truth` 白名单）、service.py 写的 kind 恰为 ERROR_KINDS − interrupted、app/ 写进 status 的字面量 ⊆ MESSAGE_STATUSES 且全覆盖。

前端（`ui/web/src`）：
- `sse.ts`：fetch + ReadableStream 自写 SSE 解析（带 Authorization；CRLF / LF / CR、注释、多行 data、无 data 块、未收尾块丢弃；TextDecoder stream 模式处理跨 chunk 的多字节字符）。
- `turn.ts`：唯一的 reducer（按 seq 去重、未知类型忽略）；`replay()` 重放时合成 done（seq = max+1；没有 result 时按 status 合成，文案取库里的常量）；`settle()` 用库里的 status 收尾实时轮次；`outcome()` 只按 status / error_kind 分支。事件类型、error_kinds、消息状态、常量文案都读 `generated/events.json`。
- `views/TurnView.tsx`：plan、code（折叠）、exec（折叠，失败标红）、可恢复 error（黄）、answer（markdown）、终止原因（error 红并带失败类型；cancelled 灰；interrupted 黄 + 重试）、警告、未核实数字；图表只给张数（F3 渲染）。致命 error 只在终止原因里出现一次。
- `views/Markdown.tsx`：react-markdown 10.1.0 + remark-gfm 4.0.1（精确版本），不开 raw HTML，链接 `target=_blank rel="noreferrer noopener"`。
- `views/SessionView.tsx`：提问框（Ctrl+Enter）、实时气泡、停止（先 await cancel、不断开流，409 当已结束）、流结束后重新拉会话按 status 收尾、interrupted 重试同一问题、历史里的 running 也能停；`views/FeedbackBar.tsx` 👍👎（再点取消 = null）+ 补充说明。
- `client.ts`：`ask`（读 `X-Message-Id`）、`cancel`、`feedback`。

测试（前端）：
- vitest 37（+16）：`sse.test.ts` 在每个字节位置切 chunk 和逐字节结果一致；`turn.test.ts` 8 条（生成文件约定、reducer、重放 ok / cancelled 不出结论 / interrupted 两种文案 / error 无 result、late-cancel 实时轮次"已取消（未保存）"、每个状态都有明确分支）；`views/f2.test.tsx` 6 条（实时渲染与收尾、停止顺序与未保存气泡、重放与重试、409 不留气泡、👍👎 与 note 文本渲染、markdown 版本钉住 / raw HTML / javascript: / 链接属性）。
- Playwright 7（+1）`e2e/f2.spec.ts`：后端托管 dist（带 CSP）上真实 SSE：无 Key → 模型调用失败原因 → 👍 → 刷新重放一致，无 CSP 违规。停止的端到端要能挂住的假模型，随 F3 的假模型服务做。

验证：pytest 613 passed；vitest 37；Playwright 7（沙箱本地）；tsc、lint、build（check-dist 0 内联）、`gen_ui_types --check` 通过。

已知取舍（S 确认）：
- **晚到的取消算取消**：answer 事件可能已经发出，但 status=cancelled、result_json 为空，这个组合会传到前端。前端规则：status 是最终真相源；当场保留气泡并标"已取消（未保存）"，刷新后不出现，不把 answer 补写回库。窗口只剩 answer 发出后到 done 之前的收尾记账，加上 done 之后到 finally CAS 的一次 DB 写入。

未做：
- **messages 表没有 error_kind 列**：dataset / llm / agent / execution / stream_aborted 落库后都塌成 status=error，重放时只能靠 content 文案区分。短期够用；将来做"按失败类型重试"或错误分布统计要回头加列（不在 F2 动 schema）。
- 错误文案脱敏（THREAT_MODEL T10）：单独一个 PR。
- 停止的端到端测试（Playwright + 能挂住的假模型）、验收第 5 条的"实测停止耗时"：随 F3 的假模型服务。
- 切走会话时不中断流（分析在后端跑完、结果照常落库）；回来时按库里的 status 显示。
