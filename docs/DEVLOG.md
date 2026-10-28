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
| B14 | P2 | ui/streamlit_app.py | 未接字典 RAG，与 README 不符 | 1（随 Streamlit 下线，已删 [67]） |
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

## [34] 2026-10-16 · 阶段 5 F2：SSE、事件渲染、重放合成 done、停止、👍👎、gen_ui_types · commit 50e9add

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
- vitest 38（+17）：`sse.test.ts` 在每个字节位置切 chunk 和逐字节结果一致、开头 BOM 被去掉（BOM 单独成块也一样，正文里的 U+FEFF 保留）；`turn.test.ts` 8 条（生成文件约定、reducer、重放 ok / cancelled 不出结论 / interrupted 两种文案 / error 无 result、late-cancel 实时轮次"已取消（未保存）"、每个状态都有明确分支）；`views/f2.test.tsx` 6 条（实时渲染与收尾、停止顺序与未保存气泡、重放与重试、409 不留气泡、👍👎 与 note 文本渲染、markdown 版本钉住 / raw HTML / javascript: / 链接属性）。
- pytest 补 `test_real_tcp_disconnect_is_interrupted`：真 uvicorn + 真 socket，读到 plan 后关连接 → interrupted + DISCONNECTED_MESSAGE，会话立刻能再问。interrupted 的判据是显式的（只在 `except GeneratorExit` 里落），默认兜底是 error + STREAM_ABORTED_MESSAGE；`test_stream_ends_without_done_is_error_not_interrupted` 钉住"生成器正常结束却没 done"落 error，不显示"连接已断开"。
- Playwright 7（+1）`e2e/f2.spec.ts`（"没有 Key"由 playwright.config 显式固定：`DEEPSEEK_API_KEY=""` + `PYTHON_KEYRING_BACKEND` 强制 fail 后端，提问前断言 configured=false）：后端托管 dist（带 CSP）上真实 SSE：无 Key → 模型调用失败原因 → 👍 → 刷新重放一致，无 CSP 违规。停止的端到端要能挂住的假模型，随 F3 的假模型服务做。

验证：pytest 615 passed；vitest 38；Playwright 7（沙箱本地）；tsc、lint、build（check-dist 0 内联）、`gen_ui_types --check` 通过。

已知取舍（S 确认）：
- **晚到的取消算取消**：answer 事件可能已经发出，但 status=cancelled、result_json 为空，这个组合会传到前端。前端规则：status 是最终真相源；当场保留气泡并标"已取消（未保存）"，刷新后不出现，不把 answer 补写回库。窗口只剩 answer 发出后到 done 之前的收尾记账，加上 done 之后到 finally CAS 的一次 DB 写入。

未做：
- **messages 表没有 error_kind 列**：dataset / llm / agent / execution / stream_aborted 落库后都塌成 status=error，重放时只能靠 content 文案区分。短期够用；将来做"按失败类型重试"或错误分布统计要回头加列（不在 F2 动 schema）。
- 错误文案脱敏（THREAT_MODEL T11；原写 T10，与 §2.1 的 CSP 条目撞号，已改）：单独一个 PR。
- 停止的端到端测试（Playwright + 能挂住的假模型）、验收第 5 条的"实测停止耗时"：随 F3 的假模型服务。
- 切走会话时不中断流（分析在后端跑完、结果照常落库）；回来时按库里的 status 显示。

## [35] 2026-10-16 · 阶段 5 F3（进行中）：假模型服务 + 停止端到端 · commit 7aed8e8

当前阶段：**阶段 5 前端，F3 进行中**。第一步：公共的假模型服务 + 停止的端到端（验收第 5 条两个耗时都测出数）；下一步 ECharts 渲染。[34] 的 SHA 已回填 50e9add（PR #35 squash；DEVLOG 一律引用 CI run id 而不是分支中间 commit，squash 后零死引用）。

假模型服务 `tests/fake_llm.py`（S 10-16 定：独立进程、无状态、按 model 名分派）：
- OpenAI 兼容 `POST /v1/chat/completions`，标准库 `ThreadingHTTPServer`，不加依赖。产品代码不改，只把 base_url 指过去。
- model 名 `<scenario>[@step]`：`ok`、`hang-<N>s`、`fail-<code>`、`slow-<N>s`；step ∈ plan/codegen/fix/answer（工作流）、act/final（ReAct）。不写 @step = 第一次调用（工作流 plan、ReAct act），按请求内容就能判定，不需要计数。
- **fail loud**：未知 scenario / step、拼错（`hang-30`）、@step 不属于本次链路、认不出当前步骤（提示词变了）、`stream=true` → 一律 HTTP 400 + 原因。选 400 而不是 500：500 会被 LLMClient 当可重试错误退避重试，表现成"偶发慢"，400 立刻以 bad_request 失败。没有"认不出就走默认剧本"的分支。
- 和 S 的提议差一处：没做 `stream-<N>tps`。产品不用流式调用（ChatOpenAI 非流式，SSE 是事件粒度不是 token 粒度），控 token 速率测不到任何东西；用 `slow-<N>s`（每次调用都慢 N 秒，把事件拉开）测增量渲染。
- 测试 `tests/test_fake_llm.py`（39，四个 scenario 都在真链路上走过）：解析器正反例、认不出 → 400 且不先睡、跨链路 @step → 400、stream → 400、默认目标是第一次调用、同请求同回复；两种 agent 走真 HTTP + 真产品链路跑 ok / hang / 拼错——提示词一改这里先红（漂移守卫）；fail-500@codegen → server、退避重试 3 次（500 本来就是测重试路径，和认不出 → 400 不同），fail-401 → auth 1 次；slow-1s → 3 次调用总耗时 ≥ 3 s。ReAct 的 act/final 只按"最后一条是不是 tool"分，多轮工具调用分不出第几轮（代码注释写了边界）。

Playwright：
- 两个后端、两个 project：`nokey`（f0/f1/f2，没有 Key）和 `fake`（f3*，base_url → 假服务，`DATACHAT_LLM_MAX_RETRIES=0`）。场景用 `PUT /settings {model}` 按测试设；model 是后端全局设置，所以 `workers: 1`。
- `e2e/f3-stop.spec.ts`：`hang-8s@codegen`，plan 到了点停止。beforeAll 先用 ok 走一轮 API 预热：后端进程首次分析要 import pandas/matplotlib/langchain + 建字体缓存，沙箱里 20 多秒（不预热时 plan 45 秒都没到）；被测窗口里混着冷启动，8 秒的上界根本量不准。CI 的新 runner 同样是冷的，以后任何测耗时的 e2e 都要预热。断言：落 cancelled、显示"已取消"不是失败、没有"未保存"、立刻重问不撞 409 并正常出结论、刷新后重放一致。
- 实测（沙箱本地两次）：**感知延迟 1–2 ms**（点停止 → "正在停止…"，乐观 UI，门槛 < 500 ms）；点停止 → `POST /cancel` 返回 17–23 ms；**后端延迟 8048–8051 ms**（`POST /cancel` 200 → 界面"已取消"）。plan 一到就点，codegen 那次调用还剩约 8 秒，后端延迟就是这 8 秒：和"上界 ≈ 当前模型调用剩余时间"一致，只记录、不设门槛（断言只放 < 10 s 的健全性上界）。

验证：pytest 654 passed（+39）；vitest 38；Playwright 8（nokey 7 + fake 1，本地连跑两次）；tsc、lint 通过。

未做：
- ECharts 渲染、prepare、主题、开关、换图型、导出（F3 下一步）。
- late-cancel（answer 已发出后才取消）的端到端：answer 和 done 之间没有可挂住的模型调用，假服务造不出这个时序；单元测试已覆盖。

## [36] 2026-10-16 · 移交文档 docs/HANDOVER.md · commit 7ece7a2（PR #37）

当前阶段：**阶段 5 前端，F3 进行中**（第一步假模型服务 + 停止已合并，下一步 ECharts 渲染）。[35] 的 SHA 已回填 7aed8e8（PR #36）。

- 新增 `docs/HANDOVER.md`：给接手的 agent 用，内容包括项目目的、阅读顺序、和 S 协作的规则、设计不变量、下一步、环境搭建、提交流程、踩过的坑、仓库外记忆的要点。
- 只改文档，没有改代码。


## [37] 2026-10-16 · 阶段 5 F3-ECharts 第一步：后端 option 原样渲染、五种图型、零外部请求 · commit acaa8bf（PR #41）

当前阶段：**阶段 5 前端，F3 进行中**（第一步 ECharts 渲染完成；下一步 prepare 完整版 / 主题 / 开关 / 换图型 / 导出 / 注入实测）。方案见 phase5-frontend.md「F3-ECharts 第一步」（PR #40）。

后端 / 生成：
- `scripts/gen_ui_types.py` 新增 `chart_schema.json`（KINDS、kind→series.type、`_ALLOWED` 顶层键、`_ENUMS`）和 `chart_fixtures.json`（16 个夹具，全部是 `build_option` 在固定种子合成数据上的真实产出，存完整 spec，`indent=1`，838 KB）：五种 kind、无标题、时间列 line / area、缺失类目与缺失值、20 系列长表、50 扇区、多 y 宽表、bar / scatter 的 5000 与 5001。CI 已有的 `--check` 按字节比对。
- `tests/test_chart_fixtures.py`：夹具全部通过 `validate_spec`、覆盖每个 kind；5000 不截断、5001 输出 5000 点且 `truncated=true`。
- 假服务 `chart-<kind>`：同 ok，写代码的那一步（codegen / fix / act）多调一次 `chart()`，列按 dtype 选（第一个非数值列 + 第一个数值列；scatter 取前两个数值列）。kind 直接取 `app/tools/charts.py` 的 KINDS；未知 kind、带 @step（含空 `@`）一律 400。

前端：
- `echarts` 精确锁定 6.1.0（依赖 zrender 6.1.0、tslib 2.3.0），只从 `echarts/core` 按需引入；ESLint `no-restricted-imports` 禁止 `import "echarts"`。
- `src/charts/register.ts`：注册表的键 = 后端白名单（顶层键 + 每个枚举值），不需要组件的也显式写 NONE。产品只注册 CanvasRenderer。
- `src/charts/prepare.ts`（v0）：JSON 往返深拷贝 → 按 banned_keys.json 递归删除（含 renderMode）→ 强制 `tooltip.renderMode='richText'`（缺失或数组也处理）；不改输入。
- `src/charts/EChart.tsx`：一图一实例，挂载 init(canvas) + ResizeObserver，卸载 disconnect + dispose；option 变了 `setOption(..., {notMerge:true})`，不重建实例。
- `TurnView` 按 `result.charts` 顺序渲染：option 项 → EChart，png 项 → 同源 `<img src="/charts/<name>?token=">`（`Api.chartSrc` 只认 `/charts/<name>`）。截断提示只走后端 `result.warnings`，前端不另拼。

偏离方案（及理由）：
- **多注册了 `LegacyGridContainLabel`**（echarts/features）。夹具渲染测试抓到：后端产出 `grid.containLabel=true`，echarts 6 起它要单独注册这个 feature，否则生产构建里**静默不生效**（只在开发构建打一句 `console.log`，不是 warn），轴标签可能被裁。因此 console 断言把带 `[ECharts]` 前缀的 `console.log` 也算进去。后端改用 `grid.outerBounds` 留到主题那一步再议。
- **`slow-1s` 真链路测试原来就有**（[35] 的 `test_real_chain_slow_delays_every_call`，3 次调用总耗时 ≥ 3 s），方案里说"补"是我写错了，这次没有新增。
- 双向比对只覆盖顶层键和枚举值，嵌套键（如 `grid.containLabel`）不在 chart_schema 里——上面那个漏洞就是这样漏掉的，靠夹具渲染测试的 console 断言兜住。

测试：
- pytest：`test_fake_llm.py` 63（+24）：chart 场景的解析正反例；只改写代码的步骤、其余步骤与 ok 逐字节相同；**五种 kind × 两种 agent 走真 HTTP + 真沙箱**，`result.charts` 里恰好一张该 kind 的图且过 `validate_spec`；**5001 行 × 两条链路**：图截到 5000 点，`result.warnings` 里截断警告恰好一条（service 层）。
- vitest 67（+29）：`charts.test.ts` 注册表 ↔ chart_schema 双向比对（多一项、少一项都红）、16 个夹具 × 产品注册表 SSR SVG 渲染（series 数一致、有图元、console 无 warn / error / `[ECharts]` log）、prepare（各层级无被禁键、renderMode 只在 tooltip 下且为 richText、不改输入、人为注入的被禁键被删）；`register.control.test.ts` 对照：少注册 BarChart → 报错 / 报警；少注册 LegacyGridContainLabel → `[ECharts]` log 被抓到；`EChart.test.tsx`：4 张图 init 4 次、卸载 dispose 4 次、`getInstanceByDom` 为空、observer 全断开；resize 由 observer 触发；TurnView 5001 夹具图和截断警告同时出现且只有一条；png 项走 chartSrc。jsdom 没有 canvas，组件测试里 init 换成真 init + SVG renderer，并断言产品传入的是 canvas。
- Playwright 9（+1）`e2e/f3-charts.spec.ts`：后端托管 dist + CSP，五种 kind 各问一轮，每轮 1 个 canvas 图、`data-kind` 对得上、库里 `result.charts` 的 kind 序列一致；刷新后走重放仍在；全程**零外部请求**（对照：同源 `/assets/*` 请求被监听到）、**零 CSP 违规**。

实测（沙箱 aarch64，只记录、不设门槛）：
- 构建：主 chunk 399.93 → 964.38 kB（gzip 123.95 → 314.76 kB），增量 +564 kB（gzip +191 kB）。对照：全量 `import "echarts"` 是 1528.56 kB（gzip 498.73 kB），按需引入省 564 kB。Vite 报 chunk > 500 kB 警告，没压（拆包留到后续）。夹具没进产物（grep 确认）。
- `prepare` 耗时（Node 24 / jsdom，200 次）：bar-5001 中位 0.55 ms、p95 0.80 ms；scatter-5000 中位 1.50 ms、p95 2.08 ms；scatter-5001 中位 1.61 ms、p95 1.95 ms。
- 停止 e2e 本轮：感知 9 ms、POST /cancel 54 ms、后端 7984 ms（与 [35] 一致）。

验证：pytest 680 passed（+26，含本地闸门数据 25 条）；vitest 67；Playwright 9（nokey 7 + fake 2）；tsc、lint、build（check-dist 0 内联）、`gen_ui_types --check` 通过。

补记：首次推送后 CI web job 的 lint 红了（run 38871680030）。原因是 lint 在写 `e2e/f3-charts.spec.ts` 之前跑过，之后没有重跑。e2e 里的辅助函数叫 `useScenario`，在循环里调用，触发了 `react-hooks/rules-of-hooks`。改名为 `setScenario` 后，lint 和 tsc 都通过；行为没变，e2e 没有重跑。

补记二（S 10-16 评审）：
- vitest 里的边界夹具只在 SSR SVG 下渲染过，canvas 路径只覆盖了五种 kind 的普通情况。为此新增 Playwright 测试 `f3-charts.spec.ts`「边界：bar 5000 点在 canvas 上画出，console 干净」：上传 5000 行 CSV，跑 chart-bar；断言 canvas 可见、尺寸非 0，没有截断提示，库里存的 option 是 `truncated=false` 且 `series[0].data` 正好 5000 条，console 里没有 error、warning 或 `[ECharts]` log，也没有 pageerror。
- `charts.test.ts` 把双向比对改名为「（双向，仅顶层键 + 枚举值，不含嵌套键）」，并注明嵌套依赖靠夹具渲染兜底。
- `register.ts` 补了跨端隐式契约的规则：现在只有 `grid.containLabel` 这一条，不建机制；一旦出现第二条，就在 chart_schema.json 里声明"字段 → 需要的前端 feature"，纳入双向比对。后端改用 outerBounds 跟主题一起定。
- 验证：lint、tsc、vitest 67、build（check-dist）通过；Playwright **10 passed**（nokey 7 + fake 3），停止 e2e 本轮感知 1 ms、后端 8026 ms。`npm install --package-lock-only`（Node 24.22.0）重新生成后 lock 文件不变，lockfileVersion 3。

未做：
- 主题、显示开关、换图型、导出、注入实测、prepare 完整版（F3 后续）。
- chunk 拆分 / 懒加载 ECharts。
- 沙箱环境备注：Playwright 浏览器装到仓库外 `PLAYWRIGHT_BROWSERS_PATH=/workspace/work/ms-playwright`（home 不持久），系统依赖用 `playwright install-deps chromium`。


## [38] 2026-10-17 · 阶段 5 F3 第二步：注入实测，tooltip 会解析 `}` · commit 706e9b8（PR #43）

当前阶段：**阶段 5 前端，F3 进行中**（第二步注入实测完成；下一步是第三步 prepare 骨架 + outerBounds + tooltip 的 `{}` 处理）。方案见 phase5-frontend.md「F3 第二步」（PR #42）。[37] 的 SHA 已回填 acaa8bf（PR #41）。

结论（详见 THREAT_MODEL §2.3）：P1–P3 在所有面上都不执行，也不会变成元素。P4（`{a}{b}{c}`）在任何位置都**没有**被模板替换。但在 tooltip（richText）里，用户字符串中的第一个 `}` 会提前结束 ECharts 自己的 `{样式|名字}` 包装：`{a}{b}{c}` 实际画出来是 `{a` + `{b}{c}}`，`{x|富文本}` 是 `{x|富文本` + `}`，后半段换成了另一种字号。标题、轴名、类目轴标签、图例、饼图扇区标签都原样画出，不解析。所以第三步 prepare **必须**处理进 tooltip 的 `{` `}`。

后端 / 生成：
- `tests/fake_llm.py`：新增 `INJECT_PAYLOADS`（P1–P5，都短于 NAME_MAX）。`inject_csv()` 用 `csv.writer` 生成夹具 CSV：列名是 P4、P5、P2、P3，5 行，类目值按 `INJECT_ORDER`，系列值错开一位，P2 列全相等。新增场景 `inject-<kind>`：写代码的那一步，cartesian 和 scatter 各出两张图（宽表多 y，列名进图例；长表 `series=`，单元格值进图例），pie 出一张；结论里拼上 P1–P3，外加一个 `[点我](javascript:…)`。新增场景 `inject-error`：只调一次 `chart()`，x 传不存在的列名 P1。解析规则和 chart 一样：未知 kind 或带 @step 返回 400。
- `scripts/gen_ui_types.py`：新增 `inject.json`（`{payloads, order, csv}`）。`chart_fixtures.json` 加了 3 个注入例（inject-bar、inject-bar-series、inject-pie），用的是同一份数据、同样的调用。`--check` 照旧按字节比对。

前端测试：
- `src/charts/inject.test.ts`：3 个注入夹具做 SSR SVG 渲染，用 DOMParser 按 XML 结构判定：载荷以文本节点完整出现；没有 img / script / iframe / object / embed / foreignObject / a；只有根 svg；没有 `on*` 属性和 `javascript:` 链接。第一版用正则查原串时红了：转义后的文本里本来就有 ` onerror=` 这几个字（`&lt;img src=x onerror=&quot;…`），所以改成按结构判。
- `e2e/f3-inject.spec.ts`（fake project，托管 dist + CSP）：跑三轮（bar、pie、error）。断言包括：`fillText` / `strokeText` 包一层记录（原样转调）；MutationObserver 从页面就绪后开始记新增元素和 `on*` / `javascript:` 属性；`page.on('dialog')`；5 处真机悬停（宽表的 P4、P5 类目，长表的系列行，饼图的 P4、P5 扇区），每处都要求绘制记录里出现被悬停的名字，并且悬停前后像素不同（截图前等连续两次逐字节相同，最多 30 次，不改产品的 animation）；P4、P5 按位置的判定表用 `toEqual` 钉住；警告、结论、三轮的代码面板都按文本显示；`.echart` 的 textContent 为空，后代只有 div 和 canvas；零 CSP 违规、零外部请求。

偏离方案（及理由）：
- **chart_error 拆成单独的 `inject-error` 场景**，没有在 `inject-<kind>` 里多调一次。原因：`app/core/result.py` 的 `chart_warnings` 只在**没有** option 图时才把 chart_error 放进 warnings（`if res.chart_errors and not has_option`），照方案做的话，载荷根本到不了界面。
- **第二张图的标题是 `P4 P5`**（方案只写了 P1），这样标题这个位置上 P4、P5 也有结论。
- **类目顺序是 `INJECT_ORDER = P4, P1, P5, P2, P3`**，不是 P1–P5。`.view` 最宽 1200px，载荷标签又长，ECharts 会自动隔一个画一个（实测只画第 0、2、4 个）。按 P1–P5 排的话，P4 的类目标签画不出来，那个位置就没有结论。悬停坐标用画出来的标签线性推算。
- MutationObserver 从页面就绪后才开始记新增元素：第一次跑时 index.html 自己的 3 个 script 被记了进去。
- 判定口径：只要画出来的不是完整原串，或者出现了 `{a` 之类的残片，就算"解析"。

补测（S 评审后，本地 probe，脚本不入库，第三步会转成 e2e 用例）：直接加载 echarts 6.1.0 dist，renderMode 为 richText，真机悬停，记录 fillText（文本、坐标、字体）。
- `x}{y|999`：bar 的表头行、系列名行和饼图扇区名都画成 `x`（14px）+ `999`（12px），`}{y|` 消失。轴标签和饼图标签原样画出。
- 借样式：内部样式名是 `__EC_aUTo_<n>`，起点为 `round(random×9)`（echarts `util/number.js` 的 `getRandomIdBase`），在 `tooltipMarkup.js` 的 `wrapRichTextStyle` 里递增。载荷 `x}{__EC_aUTo_K|999`，K 取 3–12，每个 K 悬停 20 次：只放在类目里时命中 18/200，类目和系列名都放时命中 36/200（每个 tooltip 有两次机会）。命中时 999 画成 `900 14px`，和真值同款。命中率按配置分开记：单次机会 9%（18/200），两次机会 18%（36/200）。
- 落点：第一版只记了 fillText 的 x，没记 `textAlign`，"右对齐"的论证不成立（S 指出：x 是起点还是右边缘，取决于 textAlign）。补测时同时记 `textAlign` 和 `measureText` 宽度，伪造数字分别用 `9`、`999`、`99999999`，真值用 `7` 和 `12,345,678`：伪造文本和真值都是 `textAlign=right`，x 都等于 134，宽度分别是 8、23、62 和 8、70。所以 x 是右边缘，右对齐到数值列，落点由借到的样式决定（表头行的 `x` 在 x=10，伪造数字仍然出现在数值列）。系列名行里，伪造数字夹在名字和真值之间（上一轮记录是 `x 999 8`）。真值没有被替换。
- 换行：`上\n下` 在表头拆成两行；在系列名行里，`下` 从行首开始，真值跟着落在 `下` 那一行。确定性复现，定级排在借样式之前。
- tab：`上\t下` 作为一段字符整体画出（宽 32），数值列位置不变，不参与排版。
- 未证：多个 token 连写的稳定命中、借 marker 样式伪造色块。按 S 的决定，第三步在后端规范化 `{}`，让这些路径不可达，所以不再测。

验证（最后一次改代码之后全部重跑）：pytest **707 passed**（+27，含本地闸门数据 25 条；`test_fake_llm.py` 63 → 90，其中真链路 inject 5 kind × 2 agent + error × 2）；vitest **77**（+10：inject.test.ts 7，夹具多 3 个带来 charts.test.ts SSR 渲染 +3）；Playwright **11 passed**（nokey 7 + fake 4，新增 f3-inject 11.2 s）；lint、tsc、build（check-dist 0 内联，主 chunk 964.38 kB 没变）、`gen_ui_types --check` 都通过。

未做：
- v2 字段的注入（title.link / sublink、各类 formatter、aria.*），留到层 2 再测。
- tooltip 的 `{}` 处理：放在第三步，方案先由 S 评审。
- 固定端口连续跑 e2e 会撞上 TIME_WAIT。定性为测试工具问题加 sidecar 契约缺口（壳必须用 `--port 0`），不要加 SO_REUSEADDR，见 issue #44。
- `app/core/result.py:117`（`if res.chart_errors and not has_option`）：有图时 chart_error 被静默丢弃，用户少看到一张图却不知道。这是有意的"部分失败不打扰"还是遗漏，待定。
- 第三步要连带处理：后端 `_clean_str` / `_cat` 规范化 `{}` 和换行，`validate_spec` 加闸门：遍历整个 option，任何 string 值都不得含 `{`、`}`、`\n`，不按登记键逐个查；判定表的 `note()` 判据要跟着改（规范化后原串不再出现，判据不改的话会变成 raw 和 parsed 都为 false），改的是判据，不是期望值；重新生成 chart_fixtures 的注入例（inject.json 不变）。


## [39] 2026-10-17 · 阶段 5 F3 第三步：渲染面规范化 + 闸门、outerBounds、prepare 管线骨架 · commit 10e76ff（PR #46）

当前阶段：**阶段 5 前端，F3 进行中**（第三步完成；下一步是第四步主题，人眼验收，单独一个 PR）。方案见 phase5-frontend.md「F3 第三步」（PR #45）。[38] 的 SHA 已回填 706e9b8（PR #43）。

后端：
- `app/tools/charts.py`：新增模块常量 `DISPLAY_UNSAFE = {"{": "｛", "}": "｝", "\n": " "}`，由 `_display_safe` 和 `_check_strings` 共用。
  - `_display_safe(option)` 在 `build_option` 里、`validate_spec` 之前调用，递归处理 option 的每个 string 值（键不动）。
  - `_check_strings` 是 `validate_spec` 里的独立闸门，不看 `_ALLOWED`，string 值或键含不安全字符即报问题。builder 漏掉时变成 ChartBugError。
  - `_clean_str` 不改，补了 docstring 说明原因（它也是消息出口）。`\t` 不处理的依据写在常量注释里。
- grid：`containLabel: True` → `outerBoundsMode: "same", outerBoundsContain: "axisLabel"`（`_cartesian`、`_scatter`）。官方注释称两者等价，同时说明 'axisLabel' 更精确、与旧行为略有差异。`_ALLOWED.grid` 删 containLabel、加两个键，`_ENUMS` 加两项。clamp 保持默认 25%。
- `tests/fake_llm.py`：新增 P6 `x}{__EC_aUTo_4|999`、P7 `上\n下`。`INJECT_ORDER = P4, P1, P5, P2, P6, P3, P7`（7 行）。
- `scripts/gen_ui_types.py`：`inject.json` 加 `display`（后端 `_display_safe` 算出）；新夹具 `long-labels-bar`（3 个 120 字类目）。chart_schema / chart_fixtures 已重新生成。

前端：
- `register.ts`：去掉 `LegacyGridContainLabel` 和那段跨端隐式契约注释，`ENUMS` 加 `grid.outerBoundsMode` / `grid.outerBoundsContain`（都是 NONE）。跨端隐式契约现在是零条。
- `prepare.ts`：拆成 `applyLayer1` / `applySwitches`（恒等）/ `cleanup`，由 `runPipeline(option, ui, steps)` 串起来；`prepare(option, ui)` 固定用两个恒等步骤。`UiState` 是空类型。调用方都改成传 `{}`。

偏离方案（及理由）：
- **恒等步骤不声明 `ui` 形参**，而不是写 `_ui`。`_ui` 能过 tsc（noUnusedParameters 放过下划线），但 ESLint `@typescript-eslint/no-unused-vars` 会红（实测 2 errors）。TS 允许把参数更少的函数赋给 `Step`，第五步用到时再加。
- **`runPipeline` 单独导出**，用来注入替身步骤，产品只调 `prepare`。这样产品签名里没有只给测试用的参数。
- **第一根柱子的门槛**：width 用相对变化 < 5%；x 用平移量占画布宽 < 5%，没有用 x 自身的相对变化。实测 bar 的 x 51.91 → 54.82（自身相对变化 5.6%，占画布宽 0.45%），width 80.11 → 79.69（-0.5%）。bar-missing 的 x 56.41 → 59.30，width 100.13 → 99.62。x 平移来自新机制把轴标签的边距算得更精确（grid 由 [33.92, 60, 580.48, 290] 变成 [36.92, 66, 577.48, 284]），和官方注释说的"略有差异"一致。如果拿 x 自身比，这一条在没有缺陷的情况下也是红的。
- **long-labels-bar 的结论和方案预想不同**：3 个 120 字类目在 640×400 的 SSR 里，**新旧两种写法都一个类目标签都不画**，grid 也基本不缩（旧 [44, 60, 570, 290]，新 [47, 66, 567, 298]）。所以"标签都在画布内"对这个夹具来说是空真。测试里把"类目标签数 = 0"单独钉住，其他直角坐标夹具要求至少画出一个。按标签长度扫了一遍（同样 640 宽，3 个类目）：10 字时两者都画 3 个；20 字时都画 2 个；**30 字时旧写法画 1 个、左边溢出画布 41 px（x=-41），新写法一个都不画**（grid 左边缩进 103）；40 字及以上两者都不画。不是 clamp 导致的溢出，反而是旧写法会溢出。clamp 没调。注意：jsdom 没有 canvas，SSR 的文字宽度是 zrender 估算的（每个中文字 12 px），浏览器里的真实阈值会不同。
- **轴标签识别按结构**：用 echarts AxisBuilder 给文本元素父节点的 `anid`（`label_<tick>`；轴名是 `name`）。第一版按文本匹配，红在注入夹具上：P4 同时是轴名和类目，轴名在画布右边缘外（x=629.4，宽 91）。轴名是否纳入 outerBounds 是第四步的事，所以轴名不算在这条断言里。
- **e2e 位置分类器修正（判定表期望值没动）**：长表有 7 个系列后，图例折成两行（y=326 和 348，ch=360），第二行的 P5 图例被归成了"轴名"，判定表多出一格 `P5 axisName`。`posOf` 加了一条：`align=left` 且 y > 85% 高度 → 图例（x 轴名在 y=290）。
- **P7 按"每次绘制"判**：tooltip 过渡期间会重绘多帧（实测 24 次绘制都是 `上 下`），所以断言改成"所有含上 / 下的绘制文本都等于 `上 下`，且每一次都有同一 y 的真值 `2`"，不再要求只画一次。
- **PR #46 的 windows CI 红（P7）**：原因是测试夹具用文本模式写 CSV，Windows 会把单元格里的 `\n` 写成 `\r\n`，P7 变成了 `上  下`。修法：`test_fake_llm.py` 的 `inject_path` 改用 `write_text(..., newline="")`。顺带确认产品行为：`\r` 不在 `DISPLAY_UNSAFE` 里，但 `_clean_str` 的 `_CTRL`（覆盖 `\x0b-\x1f`）会先把它换成空格，所以画布上不会出现裸 `\r`。新增 `test_crlf_in_cells_leaves_no_raw_cr_on_canvas` 把这一点钉住。`\r\n` 会显示成两个空格，不合并（合并就要动 `_clean_str` 的消息出口，S 选了 A）。
- `register.control.test.ts`：原来"少注册 LegacyGridContainLabel 会被 `[ECharts]` log 抓到"那条，现在改为手工往 option 里塞 `containLabel`。这样仍能证明零 log 守卫在 vitest 里有效（守卫留在 vitest，没有挪到 e2e）。

测试：
- pytest `tests/test_charts.py` +14（含 `test_crlf_in_cells_leaves_no_raw_cr_on_canvas`）：`test_display_safe_replaces_unsafe_and_keeps_tab_and_pipe`（正反例）、`test_builder_output_has_no_unsafe_chars_anywhere`（四种图型、每个入口都带全部不安全字符）、`test_message_exits_keep_raw_text`（ChartError 的可用列和 `_msgs` 原样保留 `{a}` 和 `\n`）、`test_gate_rejects_hand_built_unsafe_spec` ×5（拒绝路径）、`test_gate_rejects_unsafe_dict_key`、`test_gate_covers_fields_not_in_allowed`（遍历覆盖）、`test_display_safe_and_gate_share_charset`（漂移：给常量加零宽字符，两侧同时生效）、`test_builder_slip_becomes_chart_bug_error`、`test_grid_uses_outer_bounds_and_contain_label_is_gone`。`test_chart_fixtures.py` +1：`test_no_fixture_contains_contain_label`。`test_fake_llm.py` 的真链路断言改成对比 `_display_safe` 后的载荷（结论仍是原文）。
- vitest：`charts.test.ts` 新增「outerBounds」（直角坐标夹具每个轴标签在画布内；bar、bar-missing 第一根柱子对照 2213aac 的取值）和「prepare 管线骨架」（恒等步骤逐字节一致；prepare 与 v0 逐字节一致；替身步骤在第一位或第二位塞的被禁键都被清掉；替身原地修改不影响输入；耗时记录）。原 v0 断言原样保留。
- e2e `f3-inject.spec.ts`：P6、P7 断言；前提断言 P4–P7 都画在宽表的类目轴标签上；`note()` 改成 `includes(display[P])`；tooltip 两格 PARSED → R（原因：后端 `_display_safe` 把 `{}` 规范化为全角，richText 包装不再能被提前闭合）；饼图悬停按 360/N 度算。

实测（沙箱 aarch64，只记录）：
- prepare 耗时：bar-5000 跑 20 次，中位数 1.022 ms（最小 0.927，最大 1.538）。
- e2e 里 P6 悬停：表头画成 `x｝｛__EC_aUTo_4|999`（14px，align=left），数值行是 `2`（900 14px，align=right），没有 999。P7：tooltip 行 `上 下`（14px）和真值 `2`（900 14px）在同一个 y=160。

验证（最后一次改动之后全部重跑）：pytest **722 passed**（+15，含本地闸门数据 25 条）；vitest **102**（+25）；Playwright **11 passed**（nokey 7 + fake 4，f3-inject 26.4 s；停止本轮感知 6 ms、POST /cancel 16 ms、后端 8039 ms）；lint、tsc、build（check-dist 0 内联，主 chunk 964.38 → 963.73 kB，少了 LegacyGridContainLabel）、`gen_ui_types --check` 都通过。

未做：
- 主题、轴名是否纳入 outerBounds（第四步）；开关和层 1 的实际内容（第五步）。
- `result.py:117` 有图时 chart_error 被丢弃（待定）；#44。
- 截断警告里的标题现在取自规范化后的 option（`_spec_title`），名字含 `{}` 时警告里显示全角。这条警告给用户看，不会回到模型的列名流程，所以没动。
- long-labels 在真实浏览器字体下的阈值没有测（SSR 是估算宽度）。

## [40] 2026-10-19 · 阶段 5 F3 第四步：四套主题、配色归主题、轴名纳入外边界 · commit 2373f24（PR #48）

当前阶段：**阶段 5 前端，F3 进行中**（第四步完成，等 S 人眼验收；下一步是第五步开关 + 换图型）。方案见 phase5-frontend.md「F3 第四步」（PR #47）。[39] 的 SHA 已回填 10e76ff（PR #46）。

后端：
- `app/tools/charts.py`：`build_option` 不再写顶层 `color`；`_ALLOWED["color"]`、`_HEX` 和 color 校验删除。原因：echarts 6.1.0 `mergeTheme` 在 `option.color` 存在时整条跳过主题配色。
- 调色板第 3 色 `#E2843B` → `#CD7D28`，`charts.py` 和 `plotting.py` 两处同步（白底 2.76 → 3.20；对 #C0392B ΔE00 25.0）。`chart_schema.json` 新增 `palette`、`axis_name_max_px`，前端默认主题从这里读。
- grid：`outerBoundsContain` `axisLabel` → `all`，显式写 `outerBoundsClampWidth/Height: "25%"`（白名单 + 枚举钉住）。
- 轴名：x/y 都加 `nameTruncate {maxWidth: 120, ellipsis: "…"}`；**x 轴名 `nameLocation: "middle", nameGap: 28`，y 轴名 `nameTextStyle.align: "left"`**（见偏离第 1 条）。
- 夹具：`long-axis-name-bar`（100 个汉字）、`long-ascii-axis-name-bar`（100 个 ASCII）、`long-y-axis-name-bar`（只有 y 长）。

前端：
- `src/charts/themes.ts`：经典（默认，color = schema.palette）、柔和、商务蓝、暗色画布（bg #15181C）。逐键写全，不含 rich / formatter / 被禁键。`resolveTheme` 收口未知名字；`localStorage["datachat.chartTheme"]` 持久化；全局订阅。
- `register.ts`：`registerTheme` 四套；TOP_LEVEL 去掉 color；ENUMS 跟后端同步。
- `prepare.ts` `cleanup`：删顶层 `color`（只为第四步之前存进库的 spec）。
- `EChart.tsx`：`init(el, theme)`；主题变化只调 `setTheme`，不 dispose、不重设 option；`data-theme` 属性给 e2e 用。
- `views/ThemePicker.tsx`：会话页头部的"图表主题"下拉框。

偏离方案（及理由）：
1. **轴名移位（方案没写）**。只换 `'all'` 时，轴名在默认位置（x 在轴末端右侧、y 居中骑在轴线上）会横向占宽：320 宽画布上，长轴名把 plot 区压到 31–39%（long-ascii 31%，long-axis 36%，inject-bar-series 39%），过不了"plot 区 ≥ 50%"。x 轴名挪到轴下方居中、y 轴名左对齐后，同样夹具 ≥ 82%。代价：x 轴名多占一行高度，400 高时 plot 区高 66% → 60%（640×200 时 32% → 19%，产品图高固定 360，不是实际档位）。另外 bar / bar-missing 的第一根柱子回到第三步取值（80.11 → 79.69、100.13 → 99.62），BEFORE 基线不用改。只换 'all' 不移位时会是 -7.7%。
2. **注入 e2e 的 `posOf`**：x 轴名移位后，也是 `align=center` 并且在下半部，旧规则会把它算成类目标签（判定表 `P4 axisName` 一格丢失，前提断言也可能被轴名冒充）。改为按行区分：下半部 center 的最上一行（y=279）是类目标签，下一行（y=299）是 x 轴名。判定表期望值没动。
3. 注入 e2e 改为经典、暗色画布两套主题各跑一遍，判定表相同。
4. 主题 e2e 读像素用 `getImageData`，Chrome 会打 willReadFrequently 提示。这是测试自己引起的，console 过滤里单独排除，没有放宽其他告警。

测试：
- pytest：`test_option_has_no_color_and_palettes_agree`、`test_axis_names_truncate_with_ellipsis`、`test_grid_uses_outer_bounds_and_contain_label_is_gone`（改判 axisLabel → all + clamp）、拒绝例 color → "不在白名单"；`tests/test_web_f2.py::test_replay_returns_stored_chart_option_verbatim_without_validation`（重放原样下发、不调 validate_spec）。
- vitest：`themes.test.ts`（结构 / 安全 / 必需键；文字 ≥ 4.5、系列 ≥ 3.0、相邻 ΔE00 ≥ 20，新色 ≥ 22；ΔE00 实现自检对 S 的数；暗色 bg 边界；4 主题 × 全部夹具零 [ECharts] log 且 series 0 颜色 = 主题 color[0]；历史 color 被删；setTheme 不重设 option；y 轴 nameTextStyle 深合并；持久化与回退）。`charts.test.ts`「轴名在画布内」：直角坐标夹具 × 320/640/1200 宽 + 640×200，轴名在画布内且 plot 宽 ≥ 50%；长轴名以 … 结尾、估算宽 ≤ 121；两条对照（第三步写法时 x 轴名出画布；只换 'all' 不移位时 plot < 50%）。
- e2e `f3-themes.spec.ts`：四套主题逐个切换，背景像素 = 主题 bg，没有新的分析请求；刷新后保持；未知名回退经典。
- e2e `f3-themes.spec.ts`「长轴名」（S 评审 PR #48 后重写）：320×360 / 640×360 / 1200×360 / 1200×220 四档。bbox 按 `getTransform()` 的 a–f 把 `measureText` 的 `actualBoundingBox*` 四角变换后取 min/max（不再假定不旋转）；按 `clearRect` 分帧，只判最后一次画 y 轴名的那一帧。断言：两个轴名、≥2 个 y 刻度、3 个类目标签都画了（前提）；轴名以 … 结尾、宽 ≤ 121、bbox 在画布内；y 轴名 bbox 不与任何 y 刻度 bbox 相交，底边 ≤ plot 顶；x 轴名行与类目行中线差 ≥ 8。
- e2e `f3-themes.spec.ts`「已知缺陷：1200×220 下 plot 区高 ≥ 画布 40%」：`test.fail`，只放这一个数（拆成独立测试，`test.fail` 不会吞掉不变式的断言）。plot 上下沿用画出的刻度线性映射到 v=3 / v=0（矮画布下两端刻度被藏）。
- e2e `f3-inject.spec.ts`：Draw 记 `w`（measureText）；前提断言 P1–P7 都有 fillText 记录、x 轴名 P4 一行确实存在；x 轴名行 − 类目行 ≥ 8（实测 299 − 279 = 20；分类器靠 |y − labelY| ≤ 2 区分两行，间距不够时先红在这里）。

实测：
- 主题配色（对背景 / 相邻 ΔE00 最小值）：经典 ≥ 3.20 / 25.0；柔和 ≥ 3.16 / 25.7；商务蓝 ≥ 4.11 / 26.3；暗色画布 ≥ 5.44 / 39.9。
- 真实字体下 320 宽：x 轴名 `x_total_revenue_by…` 宽 116.7，center x=172.2；y 轴名宽 116.7，left x=37.3。
- 轴名旋转：四档里 x、y 轴名的画布世界变换都是 a=1、b=0（0°），bbox 是 116×12 的横条（y 轴名 360 高时在 y 60.3–72.3，最上面的刻度"3"从 81.3 开始）。和源码一致：y 轴名元素自身 rotation = endTextLayout 的 3π/2，但先挂在 rotation=π/2 的 transformGroup 下，再 decomposeTransform 到 group（echarts 6.1.0 `lib/component/axis/AxisBuilder.js:566-585`），世界角 2π ≡ 0。所以旧写法（按 textAlign 算左右边界）在这个配置下结论碰巧成立，但它只验了横向，y 轴名与刻度、plot 区的关系此前没有断言——现在有了。
- plot 区占比：360 高时 198px / 55%（三档宽度相同）。**1200×220 时 58px / 26%**：top 60 + bottom 30 + nameGap 28 = 118px（220 的 54%），再扣类目行约 12 + y 轴名 27 → plot 58px，贴着 clamp 25%。这是结构性冲突，不是调参能解决的；40% 是 S 的经验值，不拿它逼改产品几何。跟踪见 issue #49。
- **矮画布下刻度丢失**（数据完整性，单列）：1200×220 时 y 刻度 0 和 3 被 hideOverlap 吞掉，只剩 0.5–2.5，用户会误读数据范围。和"截断要自述"是同一性质，记在 #49。

未做：
- 截图的人眼验收（S）。
- #49：矮画布 grid 固定开销 + 刻度丢失（e2e 里用 test.fail 钉着）。卡片高度不在第五步清单里，所以单独立 issue。
- S 评审 PR #48 的四、五、六，随第五步做：
  - 四：历史 spec 的几何没归一（旧 spec 还带 `outerBoundsContain: "axisLabel"`，也没有 nameLocation / nameTruncate，旧会话的 x 轴名照样出画布；换主题会让旧图换色，给人"已升级"的错觉）。S 倾向在 prepare 里把 grid.outerBounds* 和轴名参数一起归一到当前契约，理由和删 color 一样（渲染期归一，不动库），免得"哪些字段该归一"取决于当时有没有人想到。
  - 五：主题 e2e 只验了背景像素，配色没在真 canvas 上验。补法：classic 与 soft 各截一张，断言左上角 10×10 以外的像素有差异。
  - 六：LEGACY 余量豁免改成按 (theme, hex) 二元组，不按色值（否则任何主题复用 #1F6FB2 都会自动绕过 ≥22），和 error_kind 白名单同一套逻辑。
- 本条 SHA 等 squash 合并后回填 squash SHA（不填分支上的 da96f4b，同 [34]→50e9add）。
- `result.py:117`、#44、T11、A1、闸门 25 条上 CI，照旧。

## [41] 2026-10-19 · 阶段 5 F3 第五步：前端开关 + 换图型、历史 spec 几何归一 · commit d589d61（PR #51）

当前阶段：**阶段 5 前端，F3 进行中**（第五步完成；下一步第六步导出）。方案见 phase5-frontend.md「F3 第五步」（PR #50，ba5354c）。[40] 的 SHA 已回填 2373f24（PR #48）。没有拆 PR（见"未做"）。

后端：
- `app/tools/charts.py`：spec 加 `x_kind`（category / time / value），放在 spec 层、和 option 并列，不进 option；`validate_spec` 校验它（枚举 + scatter ⇔ value）。`SPEC_VERSION` 旁写升版规则（加字段不升，改语义 / 删字段才升，判据"老前端读新 spec 会不会误判"），所以仍是 1。
- 几何登记表 `GEOMETRY`（grid 的 outerBounds 四键、x / y 轴名参数 + nameTruncate），以及换图型要用的框架值 `_CART_GRID` / `_CART_BOTTOM` / `_PIE_LEGEND` / `_PIE_RADIUS` / `_PIE_CENTER`、阈值 `SHOW_SYMBOL_MAX`：builder 改为引用这些常量（产物不变，chart_fixtures.json 只多了 `x_kind` 和一个新夹具）。
- 白名单注释：例外层不止 renderMode，约束改由前端 FRONTEND_KEYS 承担（THREAT_MODEL §2.3 同步）。
- `scripts/gen_ui_types.py`：`chart_schema.json` 新增 geometry / x_kinds / pie_max_slices / show_symbol_max / frame；新增 `kind_fixtures.json`（同一份数据分别以 bar / line / area / pie 调 build_option，8 组：单系列类目、时间、宽表、类目数 61、饼图 50 扇区，以及换不了饼图的超 50 / 有空值 / 有负值）；`chart_fixtures.json` 加 `scatter-multi`。

前端：
- `src/charts/switches.ts`：COMPAT（9 开关 × 5 图型）、FRONTEND_KEYS（13 条路径 → 值集合：字面量 / 主题渐变 / 排列）、`applySwitchesTo`（只经 `lit()` 从表里取值）、`canChangeKind` / `changeKind`（从后端原始 option 出发，不链式；框架值从 schema 读）、`KIND_DIFF`（只有 pie → 直角坐标的 x 轴名）。
- `src/charts/prepare.ts`：`prepare(spec, ui, theme)`；管线 normalize → changeKind → applyLayer1 → applySwitches → cleanup。normalize 用 `schema.geometry` 归一历史 spec。
- `src/charts/uiPrefs.ts`：`datachat.chartUi:<kind>`，逐字段校验，读写 try/catch，同图型的图共享订阅。
- `src/charts/EChart.tsx`：图型下拉 + 开关面板（不兼容的 disabled，title 写原因）；图型 / 开关 / 主题任一变化：主题变了先 setTheme，再整体 `setOption(prepare(...), {notMerge: true})`，取代第四步"切主题只调 setTheme"；实例不重建（`data-instance`）。zoom 开着时：zr `dblclick` 先判 `e.target` 再还原；容器 capture 阶段拦不按 Shift 的滚轮（偏离 1）。
- `register.ts`：`FRONTEND_REG`（markLine / markPoint / dataZoom inside 三个组件）。
- `docs/roadmap/M13-图表方案.md` §12：加"前端实际写出"一列，测试读它比对 FRONTEND_KEYS。
- `vite.config.ts`：`server.fs.allow` 放开 `../../docs/roadmap`（vitest 用 `?raw` 读 M13）。

偏离方案（及理由）：
1. **普通滚轮仍被 ECharts 吞掉，只靠 option 做不到"不劫持页面滚动"**。echarts 6.1.0 `lib/component/dataZoom/roams.js:175-181` 给 RoamController 的是统一配置（`zoomOnMouseWheel: true`、`moveOnMouseWheel: true`），各 dataZoom 的 `'shift'` / `false` 到监听器里才判（roams.js:107）；`lib/component/helper/RoamController.js:316-322` 在触发监听器前、指针在 grid 内时先 `eventTool.stop(e.event)`。探针（e2e，已删）：zoom 开、指针在 plot 区中心，滚轮 −60 后 `.main` scrollTop 150 → 150，window 上 passive 监听器收到 0 个事件；指针在 grid 外边缘时 150 → 90。修法：容器 capture 阶段 `if (!e.shiftKey) e.stopPropagation()`，只在 zoom 开着时挂。option 不变。
2. `prepare` 第一参数是 spec 不是 option：changeKind 要 `spec.kind` 和 `spec.x_kind`，从 option 反推正是本步否掉的。现有测试的 `prepare(option, {})` 全部改成传 spec（裸 option 用 `{kind: "", option}`，不换图型、不开开关）。
3. 第四步的两条"对照"（第三步写法 x 轴名出画布；只换 'all' 不移位 plot < 50%）原来走 prepare，现在 normalize 会把旧形状修好，对照就失效了。改为只做 cleanup 的原始路径看缺陷，并补断言"同一旧形状走产品路径时修好了"。
4. COMPAT 的排序格条件写成 `single-nontime`：x_kind 缺失时不拦排序（S 第三轮第五条：降级只写"不可换饼图"）。
5. M13 §12 没覆盖原第三列"v1 `_ALLOWED`"，而是新加一列。
6. 注入 e2e 的分类器两处调整（判定表期望值没动）：`xLabelRow` 排除纯数字文本——开关全开时柱顶数值标签和极值标记也是下半部居中的文字，实测把类目行定到了数值标签行，P4 被分成 axisName；`posOf` 在开关全开那一轮把 `align=left && y < 40` 认作图例——图例位置开关把多系列图例挪到顶部，否则 P5 图例会被分成 axisName（实测判定表多出一格 "P5 axisName"，内容是 raw、不解析）。

测试：
- pytest：`test_x_kind_sits_beside_option_and_is_correct`、`test_validate_spec_checks_x_kind`、`test_geometry_registry_matches_builder_both_ways`（登记表每个键在产物里且值相同；产物里每个键要么登记、要么在逐图内容清单）、`test_schema_exports_step5_contract`；`test_validation_rejects_callable_and_bad_envelope` 的期望文案加 x_kind（结构改了，所以文案变）。
- vitest `switches.test.ts`：COMPAT 45 格逐格测生效（✅ 格开了键在、关了键不在；❌ 格开关产物相同，递归排序键再比较），共 70 个用例；例外层机制（4 主题 × 全部夹具 × 6 种目标图型 × 11 种开关组合求差，⊆ FRONTEND_KEYS、值在集合里），FRONTEND_KEYS 每条都被写到过，= FRONTEND_REG，= M13 §12 那一列（改文档少一条时实测变红），值集合没有用户串，加一组对照（表外路径 / 表外值 / 非排列 / 别的主题的渐变 / 用户串进标签都会被抓）；换图型契约（kind_fixtures 每组两两互换 = builder 的 B，只放 KIND_DIFF）、boundaryGap / areaStyle / showSymbol 对照、饼图置灰的 6 种原因、A → B → A、产品路径不链式、`spec_kind_is_backend_truth`、目标图型不可用时留在原图型；渐变（只写 series 层、无顶层 color、换主题 colorStops 跟着变）；排序（按 (类目, 值) 对比、null 最后、饼图）；标签位置 / 圆角在堆叠时；4 主题 × 全部夹具 × 全开零 [ECharts] log；历史 spec（手写第三步形状）normalize 后 = 当前 builder；偏好存取 / 非法值回退 / localStorage 抛错。
- vitest `EChart.test.tsx`：切主题先 setTheme 再 setOption(notMerge)、渐变色跟着变、实例不重建；开关写 localStorage、同图型另一张图立即跟着变；disabled + 原因；换饼图后 spec.kind 不变、重挂载回后端图型、有空值时饼图选项置灰；wheel capture 拦截；zr 双击 `e.target` 判断与解绑。
- vitest `themes.test.ts`：LEGACY 豁免按 (主题, 色值)。`inject.test.ts`：开关全关 / 全开各跑一遍。
- e2e `f3-switches.spec.ts`（新）：开关逐个开像素变化、关回原样、无新分析请求、不兼容 disabled、刷新保持、同会话新图继承；柱 → 饼 → 柱画面回到初始、data-kind 不变、刷新回后端图型；缩放（plot 区中心普通滚轮滚页面且图不动、Shift + 滚轮缩放、双击空白还原）；渐变开着切主题实例不重建、画面变、classic 与 soft 左上角 10×10 以外有像素差异（第四步评审五）。
- e2e `f3-inject.spec.ts`：加一轮"经典 + 开关全开"，判定表不变。

实测：
- prepare（bar-5000，20 次中位数）：见闸门输出。
- 例外层机制测试实际写到的路径 = FRONTEND_KEYS 全部 13 条。

未做：
- 没有拆成两个 PR：开关和换图型都在本 PR，估时没有超出到需要拆的程度（实现 + 测试一个上午）。
- Shift + 滚轮在 Windows 真鼠标上的行为没验证：Chrome 在 Windows 上会把 Shift + 竖滚轮转成横向 deltaX，zrender 的 wheelDelta 取值是否还非零，需要 S 本机手试（e2e 的 mouse.wheel 是合成事件，不经过系统这一层）。
- 历史 spec 的 e2e（真库里的老 spec）没做：重放路径要往库里写老 result，e2e 没有入口。由 vitest SSR 覆盖（`charts.test.ts` 两条对照的产品路径断言、`switches.test.ts`「第三步形状：几何键等于当前 builder 产出」）。
- 截图人眼验收（S）。#49、`result.py:117`、#44、T11、A1、闸门 25 条上 CI，照旧。


## [42] 2026-10-19 · 阶段 5 F3 第六步：导出 PNG、交互态 view、文件名清洗 · commit 3d2ec0a（PR #53）

当前阶段：**阶段 5 前端，F3 进行中**（第六步完成，F3 六步全部落地；下一步 F4）。方案见 phase5-frontend.md「F3 第六步」（PR #52，b3b2d10）。[41] 的 SHA 已回填 d589d61（PR #51）。

前端：
- `src/charts/exportPng.ts`（新）：离屏 div 不挂 DOM → `init(theme, {canvas, width, height})` → `prepare(spec, ui, theme)` + `animation: false` → `setOption(notMerge)` → `getDataURL({png, pixelRatio: 2})` → `finally dispose`。尺寸取屏幕容器的 `clientWidth × clientHeight`；为 0 或非有限数（display:none）时抛错，不建实例（S 第二轮）。init 之前自己调 `registerCharts`：主题模块级注册，离屏实例不依赖屏幕组件先挂载。`download()`：`<a download>` + data URL，a 不挂 DOM。
- `src/charts/filename.ts`（新）：`safeFilename(title, fallback)`，字符集本文件独立定义（不 import 任何模块）。顺序：NFC → 删 C0 / DEL / C1 / U+2028–2029 / bidi → 非法字符换 `_` → 合并空白 → 按码点限长 60 → 去首尾空格和点 → 空值回退 → 保留名按 `split(".")[0]` 判、加 `_` → `.png`。无标题时回退到当前显示的图型名。
- `src/charts/switches.ts`：`View = {zoom: {start, end} | null; hidden: number[]}`、`asZoom`（NaN / 越界 / start > end 都是 null，全量归 null）、`legendItems`（饼图是扇区）、`hiddenFromSelected`（名字只在这里换成 index）、`applyViewTo`（缩放只在开关已写出 dataZoom 时生效；hidden 越界丢弃；图例 `show: false` 时不写；写值经 `inRange()` 第二道校验）。FRONTEND_KEYS 加 `dataZoom[].start`、`dataZoom[].end`（range）、`legend.selected`（legendItems），共 16 条。
- `src/charts/prepare.ts`：`UiState.view?`；管线加 `applyView`（开关之后、cleanup 之前）。
- `src/charts/EChart.tsx`：监听 `datazoom`（参数两种形状：inside 漫游是 `batch[0]`，dispatchAction 是顶层）和 `legendselectchanged`，写进 view ref；每次重算 setOption 之后用 `viewFromRendered(chart.getOption(), shown)` 从实例回读一次（屏幕是真相源，S 第二轮）；换图型 / 换 spec 时先清空。"导出 PNG"按钮、darkCanvas 下"导出为浅色（经典配色）"勾选（不持久化）、失败时按钮旁"导出失败"（`role=alert`，不弹窗）。
- `src/views/TurnView.tsx`：png 项包一层 figure，标注"静态图（由 matplotlib 生成），可右键另存为"。
- `register.ts` FRONTEND_REG 加三条（都不需要新组件）；M13 §12 dataZoom 行补 start / end，加一行"图例显隐（交互态）"。

测试设施：`tests/fake_llm.py` 加 `chart-matplotlib` 场景（plt 画一张，结果里是 png 项），给 e2e 用。

文档：THREAT_MODEL §2.3 加"F3 第六步：交互态与导出"（view 只存数值；导出文件名是用户串离开画布的唯一出口，规则和不复用 `_CTRL` / `_CONTROL_CHARS` 的理由）。phase5「F3 第六步」末尾加"实现时的偏离"。

偏离方案（及理由）：
1. **view 变化不触发 setOption**（方案第 2 条写的是"view 变化也走整体 setOption(notMerge)，比较值相同就不 set"）。屏幕已经是 ECharts 画好的样子，重设结果相同；但 notMerge 会重建 dataZoom 组件，拖动 / Shift + 滚轮途中每个 datazoom 事件都重建一次会打断手势。现在 view 写进 ref，下一次重算（开关 / 主题）和导出都带上，屏幕和导出仍走同一条 prepare。`EChart.test.tsx`「缩放：datazoom 写进 view（本身不触发 setOption）…」钉住：dispatch 后 setOption 0 次；切主题后 setOption 收到的 dataZoom[0] 是 {start: 20, end: 70}。
2. **zoom 单开时导出和全关逐字节相同**，方案验收"六个 ✅ 逐个打开都不同"在这一格不成立：inside 型 dataZoom 不画任何东西。e2e 对 zoom 断言"相同"并写明原因。S 第二轮补对照钉住开关本身：关着时 Shift + 滚轮后导出与初始相同，开着时不同。另外五个（数值标签、渐变、圆角、平均线和极值、排序）逐个不同，全开不同。
   S 第二轮认可，同时指出连带缺口：view 只在换图型 / spec 时清空，"缩放 → 关开关 → 再开"会跳回旧区间。改为每次重算后从实例回读（`viewFromRendered`，只读 `dataZoom[0].start/end` 和 `legend[0].selected`），取代 14:46 定的"从不读实例"。`EChart.test.tsx`「屏幕是真相源：缩放后关掉缩放开关再打开，窗口回到全量…」钉住；e2e 交互态用例加"关掉再打开后导出等于全量"。
3. 饼图的图例项是扇区而不是系列：`hidden` 对饼图存 `series[0].data` 的 index（方案只写了 seriesIndex）。存 index、按名字应用是有意的（同名项 ECharts 本来就一起显隐，index 只换来 UiState 里没有用户串），注释写在 switches.ts（S 第二轮要求写死）。
4. 例外层机制测试的 `diff`：字面量路径的子键另有登记时（dataZoom 的 start / end），先摘出来按各自的值集合判，再比字面量。

测试：
- vitest `filename.test.ts`（新，36 条）：P1–P7 逐条期望值、RLO / LRI / ALM / C1 / 行分隔符、CON / con.txt / CON.png / Nul.tar.gz / lpt1（CONSOLE、COM0 不算）、`..` / 空格点 / 全控制字符回退、第 60 个码点是空格或点、65 个 emoji 不切代理对、NFC、全角空格合并、无标题回退图型名；源码不 import 任何模块。
- vitest `exportPng.test.ts`（新，7 条）：init 之前已注册（调用顺序 register → init）；尺寸 0 / NaN / 负数抛错且不 init；init 参数（div 未挂 DOM、主题、canvas、尺寸）、setOption 收到 `prepare(...) + animation:false`、getDataURL 参数、dispose；getDataURL 抛错时仍 dispose；prepare 产物里没有 animation；4 主题 × 全部夹具 × 全开 × 带 view 的导出 option 无被禁键、renderMode 是 richText；download 的 a 不挂 DOM。
- vitest `switches.test.ts`：例外层组合加"全开 + view / 全开 + 越界 view / 全关 + view"，16 条路径全部被写到过；对照加"缩放越界 / 图例键不是图例项 / 图例值不是布尔"会被抓、合法的不误报；新 describe「交互态 view → applyView」9 条（含 `viewFromRendered`）。
- vitest `EChart.test.tsx`：容器尺寸为 0 时导出失败不下载、屏幕是真相源两条（关开缩放回到全量；图例点掉后重算屏幕与 view 一致）、导出参数与文件名、注入标题清洗 / 无标题回退、浅色勾选只在 darkCanvas 出现且用 classic、导出失败提示、缩放 / 图例写进 view、换图型 / 换 spec 清空；png 项的静态图标注。
- pytest `test_real_chain_chart_matplotlib`（workflow / react 两条链路）。
- e2e `f3-export.spec.ts`（新，5 条，beforeAll 预热照 f3-stop）：缩放开关关着时 Shift + 滚轮导出不变、开着时变、关掉再开回到全量；真下载 PNG（签名、IHDR = 容器 × 2、非背景像素 > 1000）、注入标题的文件名、无新分析请求、零外部请求、console 干净；单系列类目 bar 先断言 UI 上 enabled 的正好是六个 ✅，再逐个比；图例点掉一项后导出不同、刷新后导出与初始逐字节相同；darkCanvas 左上角 #15181C / 勾浅色后 #FFFFFF；matplotlib 静态图有标注、无导出按钮。

未做：
- 人眼验收（S）：截图已出（4 主题 × 5 图型、darkCanvas 屏幕 / 导出 / 浅色导出、缩放 + 点掉一项的屏幕 / 导出）。截图里看到：饼图类目多于调色板 6 色时颜色循环，第 7 项和第 1 项同色（8 城市里北京、武汉同色），不是本步引入，待 S 定归属。
- Windows 真鼠标 Shift + 滚轮（[41] 留下的）仍待 S 手试；Tauri 壳里的下载行为到壳那一步。
- #49、`result.py:117`、#44、T11、A1、闸门 25 条上 CI，照旧。

## [43] 2026-10-20 · chart_errors 按执行记账（result.py:117）· commit ff7b8dc（PR #55）

方案见 phase5-frontend.md §7（PR #54，f7739ca）。

改了什么：
- `AnalysisResult.chart_errors_shown`：只收图被展示的执行（error 为空）自己的 ChartError。workflow 取最后一次成功 executor（只在失败时重试）；ReAct 取所有成功 exec（与 sink["charts"] 的口径一致）。`chart_errors` 原语义不变（评测计数）。
- `chart_warnings` 只看 `chart_errors_shown`：无图 →「图表未生成：…」（文案不变）；有图 →「另有 N 张图未生成：…」；只在失败执行里的错误不报（已由"已丢弃"覆盖）。
- fake 新场景 chart-partial：同一段代码一张 bar 成功、一张列名 `__nope__` 错。

测试（全走 analyze 完整路径）：test_chart_slot.py 的 test_workflow_partial_chart_error_reported、test_react_partial_chart_error_reported、test_workflow_failed_exec_chart_error_not_reported、test_react_failed_exec_chart_error_not_reported、test_react_two_ok_execs_first_error_still_reported；test_fake_llm.py 的 test_real_chain_partial_chart_error_reported[workflow/react]。

判定表：现有期望没有改。test_react_chart_error_reaches_model_and_warnings、test_real_chain_inject_error_reaches_warnings 的错误都出在成功执行里，而且没有出图，所以仍然是「图表未生成：」。

未做：前端不用改，exec 事件里的 chart_errors 本来就是单次执行的；饼图 >6 色归 F4。

## [44] 2026-10-20 · F4 层 1 面板（标记卡）+ Tableau 风主题 + 10 色 · commit 05e2e1d

方案见 phase5-frontend.md「F4：层 1 面板」（PR #56，aedf5bc）。

改了什么：
- `charts/layer1.ts`（新）：Edit = yMin / yMax / colors（系列或扇区 index → 主题调色板 index）/ font（s/m/l = 12/14/16）/ other；applyLayer1To、parseEdit 逐字段校验、mergeOther（前 9 + '其他'，加 title.subtext 标注）、localStorage `datachat.chartEdit:<message_id>:<图序号>`。
- `prepare.ts`：UiState 加 edit；applyLayer1 不再恒等。`switches.ts`：渐变以系列自己的 itemStyle.color（用户选的主题色）为底。
- `charts/MarksCard.tsx`（新）+ styles.css：Tableau「标记」卡外观——浅灰底、细边框、4 个小方块按钮（颜色 / 轴范围 / 字号 / 合并），点开各自浮层，右上角重置。饼图禁用轴范围；非饼图禁用合并。柱图 y 最小值 > 0 时提示"会夸大差异"。
- EChart 加 `editKey` 和工具栏"样式"按钮；TurnView / SessionView 传 `<message_id>:<图序号>`。没有 message id 时只在本页生效、不存。
- 主题加 `tableau`（Tableau 风）：10 色为 Tableau 10 色相压暗重排的候选（相邻 ΔE00 最小约 27.8），浅灰网格和轴线。其余 4 套各补到 10 色。
- PALETTE 两份（charts.py / plotting.py）同步扩到 10 色，前 6 色不动；chart_schema.json 重新生成。

偏离：
1. 层 1 的键单独登记在 `LAYER1_KEYS`，没有并进 `FRONTEND_KEYS`。理由：FRONTEND_KEYS 要和 M13 §12 开关表逐字比对（switches.test.ts），层 1 不在那张表里。机制测试另写在 layer1.test.ts，并且断言表里没有死条目。
2. 判定表：themes.test.ts「暗色画布 bg 边界」改为只比较 PALETTE 前 6 色。原因：这条边界当初就是为第四步的 6 色推出来的；新增的后 4 色是按白底选的（如 #172082），darkCanvas 用的是它自己的提亮色板。

测试：layer1.test.ts（新）——四种图型的轴范围、饼图不写 yAxis、min ≥ max 不生效、5 套主题 × index 取色、饼图扇区色、渐变底色、字号、合并（总和 / 降序 / ≤10 不合并 / pie-50）、空改动和原产物逐字节相同、机制测试、存储逐字段 / 坏 JSON / 重置删键。EChart.test.tsx 加「F4 层 1 面板」5 条：字号落到实例和存储、轴范围报错不生效、饼图按钮禁用、换主题后颜色跟着 index、TurnView 存储键读回。导出断言的 ui 加上 edit。

- e2e `f4-panel.spec.ts`（新，2 条，fake 项目的 testMatch 放宽到 f[34]）：柱图上字号、y 轴上限、系列色各自改变真导出的字节，min ≥ max 时报错且导出不变，存储键是 `datachat.chartEdit:<message_id>:0` 并且值逐字段相等，重置后回到原图的字节、键被删除；饼图 12 类上轴范围禁用，合并改变导出，并出 Tableau 风截图（f4-tableau-pie.png）。两条都断言零外部请求、console 干净。

未做：人眼验收 S 10-20 看过截图，结论是"很不好看"。这一版先提交，让 S 跑起来再反馈；标记卡和 Tableau 风的视觉设计后面迭代。

## [45] 2026-10-20 · issue #49 矮画布紧凑几何 · commit 0fc4891

S 10-20 说"先去修 49"。这次没有单独开方案 PR：规则和验收一起写在本条和 phase5「#49」小节里，和实现同一个 PR（偏离"方案先行"，理由是 S 要求快）。

问题（issue #49）：grid.top 60 + grid.bottom 30 + x 轴 nameGap 28 都是固定像素，1200×220 时一共 118px（54%），plot 区只剩 26%；值轴按 0.5 一档分出 7 个刻度，在 58px 里重叠，hideOverlap 把 0 和 3 吞掉，看起来数据范围只有 0.5–2.5。

改了什么：
- `charts/compact.ts`（新）：容器高 < 300（COMPACT_BELOW）时启用紧凑几何。grid.top：有标题收到 36、无标题 16；grid.bottom 减 16（最低 14，所以 30→14、50→34）；x 轴 nameGap 28→22；y 值轴 splitNumber 3，并设 showMinLabel / showMaxLabel。只收紧不放宽，饼图原样不动。
- `prepare.ts`：UiState 加 compact；STEPS 末尾加 applyCompact（排在开关之后，开关可能改 grid.bottom）。
- `EChart.tsx`：ResizeObserver 回调里量 clientHeight，跨过阈值才 setCompact。导出用同一个 ui，所以导出和屏幕一致。
- 后端 spec 和几何契约 GEOMETRY 不动，纯渲染期处理。写出的键登记在 COMPACT_KEYS，有机制测试。

实测（e2e，长轴名夹具）：1200×220 plot 区 26% → 46%，刻度 0 / 1 / 2 / 3 齐全（修之前只剩 0.5–2.5）。1200×360 不触发紧凑，仍是 55%，刻度 0–3 每 0.5 一档。截图 issue49-1200x220.png。

判定表：
- f3-themes.spec.ts 里原来的 `test.fail("已知缺陷：1200×220 下 plot 区高 ≥ 画布 40%")` 翻成 `test`，期望值不变；另外加了首末刻度 0 和 3 的断言。
- EChart.test.tsx 导出断言的 ui 加上 `compact: false`（UiState 新增字段，测试容器 450 高）。

测试：compact.test.ts（新，7 条：阈值、单系列数值、无标题 / 多系列、饼图原样、time 轴只动 y、默认关时逐字节相同、机制）；EChart.test.tsx 新增「#49：ResizeObserver…」（360→220→360，grid.top 60→36→60）。长轴名那条 e2e 在 1200×220 下仍然满足 x 轴名和类目行间隔 ≥ 8、bbox 在画布内。

未做：卡片高度本身没有改（仍是 360），紧凑只在用户把窗口 / 容器缩矮时生效。

## [46] 2026-10-20 · issue #44 sidecar 契约：壳必须用 --port 0 · commit 96350d1

定性沿用 S 10-17 的结论：这不是产品 bug，是测试工具的问题，外加契约文档有缺口。产品代码一行都没改，只改了 docstring。

改了什么：
- `docs/sidecar-contract.md`（新）：写清楚启动方式（--port 0）、握手（stdout 第一行 JSON + /health）、端口独占（不加 SO_REUSEADDR 的理由）和测试工具。HANDOVER §6 启动命令旁边加了指向这份文档的链接。
- `app/server/__main__.py` docstring：第一行的 JSON 补上 home，写明壳必须用 --port 0，默认的 8765 只给命令行调试用。
- `tests/test_sidecar_contract.py`（新，3 条，真起子进程）：
  - `test_port0_first_line_is_json_with_port_token_home`：第一行能 json.loads，键正好是 {port, token, home}，port > 0，token ≥ 16 位，/health 返回 200。
  - `test_port_is_exclusive_while_running`：sidecar 运行期间，另一个 socket bind 同一个端口会报 OSError。
  - `test_main_sets_no_reuse_options`：`__main__.py` 里没有 setsockopt 和 SO_REUSE。
- `ui/web/playwright.config.ts`：E2E_PORT 不设时，在主进程里随机选 10000 + 3k 作为一组端口，写回 env，worker 继承同一组。显式设了就用设的值（gates.sh 不用改）。

偏离：issue 里说 e2e"也可以改成 --port 0 加读 stdout"。但 Playwright 的 webServer 在启动前就要知道端口和 url，所以改用随机端口组；理由写在 config 注释和契约文档里。

未做：Tauri 壳还不存在（阶段 6），壳侧的读取代码到时候按这份契约写。

## [47] 2026-10-20 · T11 错误文案脱敏：方案 · commit d878ad2

方案写在 phase5「T11 错误文案脱敏」。S 10-20 第二轮评审后改定：
- 剥离只剥用户问题：整串匹配，≥ 4 字才判；另加最长前缀 ≥ 12 字兜截断回显。列名、代码、字典不剥，因为它们在屏幕上本来就可见，剥掉还会和「可用列」保持原文那条规则冲突。
- 编号统一由 user_error 追加，写进 content。
- 纳入按生成点算，不按字段算：Step.error 里的沙箱 exec 原文不脱敏。
- 补上漏掉的四处：service.py:464、431、525，以及剥离要移到 service.py（LLMError 加 upstream）。
- 多表逐表带文件名；上游原文洗控制符，复用同一份字符集（挪到 app/core/text.py）。
- 验收改成断言跑出来的串，不 grep 源码。

偏离：字符集从 app/server/app.py 挪到 app/core/text.py，不是让 core 直接 import server。理由是 core → server 会形成反向依赖；挪过去之后仍然只有一份。

## [48] 2026-10-20 · T11 错误文案脱敏：实现 · commit 87d49d2（PR #61）

**结论**：到界面的错误串唯一出口是 `app/core/errors.py` 的 `user_error`，返回 `UserText`，由 `Emitter.error` 机械断言。方案（phase5「T11」，含 S 第三轮补充）列出的生成点全部改完，keystore 也已纳入。

**新文件**：
- `app/core/errors.py`：user_error / scrub / upstream_message / dataset_message / UserText / LLM_KIND_TEXT
- `app/core/text.py`：界面文案用的控制符字符集，app.py 从这里 import。charts._CTRL 故意不并，原因写在注释里。
- `tests/test_t11_errors.py`
- `ui/web/e2e/f3-errors.spec.ts`

**改动**：
- `service.py`：175、184、244/246、412/414、431（重跑原因）、464（网关）、525 都改为经 user_error 生成。
  - 525 不再带答案的 repr，答案只进日志。
  - 三条自写文案（未配置 Key、步数上限、no-exec）经 `user_error("text")` 追加编号。
  - 文案只写详情，不再写种类前缀。
- `llm.py`：LLMError 新增 `upstream` 字段。GatewayErrorContent 只带上游原文。LLMError 的 message 只给日志用。
- `events.py`：F2 四个常量改为 UserText；`Emitter.error` 在 kind≠execution 时断言 message 是 UserText。
- `app.py`：数据集预览的两处改为 user_error，日志带 `dataset=<id> file=<名>`。
- `keystore.py`：:40、:49、:86/:97、:90 去掉类型名和后端全限定名，细节写进 `datachat.keystore` 日志。
- `dataset.py`：load_data 逐表捕获，抛 TableReadError(filename)；table_paths 的自写文案去掉完整路径。
- `fake_llm`：新增 `fail-echo-<code>` / `fail-echocut-<code>`。

**偏离和理由**：
1. 工作流里，模型抛出的异常经 `LLMClient.invoke_message` 的 `except Exception`（llm.py:239）包成 LLMError，走 llm 出口。节点自身代码的异常（strip_code 解析、state 取键）不经过模型，会落到 service.py:247 的 agent 常量。`test_agent_unknown_exception_constant[workflow]` 用图本身抛异常模拟的就是这条真实路径。
2. 数据集预览没有 trace_id，所以每条错误随机生成一个编号；日志行带 dataset id 和文件名，查到编号后能找到是哪个数据集的哪个文件。
3. DatasetError 系列放在 `app/tools/dataset.py`，因为 tools 不依赖 core。TableReadError 只继承 DatasetError(Exception)。dataset_message 的判定顺序是精确类在前、ValueError 兜底在后（pandas 实测：ParserError 和 EmptyDataError 都是 ValueError，但 EmptyDataError 不是 ParserError 的子类）。

**判定表**：
- `test_fake_llm::test_real_chain_fail_loud`：保留 `"[fake_llm]" in r.error`，并新增两条断言：不含 `Error`，以编号结尾。行为变化：去掉了类型名前缀，加上了编号。
- `test_fake_llm::test_real_chain_fail_code_goes_through_product_classification`：`"server" in r.error` 改为 `startswith("模型服务出错，共尝试 3 次")`，auth 同理。分类本身不变（kind 仍是 server / auth），只是界面文案从内部枚举换成了中文映射。
- `test_core_analyze::test_workflow_llm_timeout_is_captured_not_raised`：`"timeout" in res.error` 改为 `startswith("请求超时，共尝试 3 次")`。
- `test_core_analyze` 和 `test_phase36` 里两条网关用例：`"gateway_error" in res.error` 改为 `startswith("接口返回错误内容：")`。
- 这三条的理由相同：分类不变，内部枚举不再进入界面。

**未做**：执行错误（error_kind=execution，exec 原文）按规则不经 user_error，会照原样进入 content。

## [49] 2026-10-20 · A1 错题自动复跑：方案 · commit aec166d（PR #62）

**结论**：方案写在 phase5「A1 错题自动复跑」，已按 S 第二轮评审改定。本 PR 只有方案。

**依据**：
- [28]：m09 / s06 当时按"复跑都对"认定为波动，S 已追溯承认。
- [30]：S 10-15 定的规则。
- review-v1 A1：参照基线被自己的 m13 判成了"有回归"。

**S 第二轮改定**：
- 基线验收改为"除 thresholds_sha256 外逐字节相同"，另加断言 `m13r.agents == m13.agents`。
- match 只当筛选器：复跑全部 match=true 时落进 pending_review，人工签字后才写 flaky。
- valid 改用白名单，并和 ERROR_KINDS 做全覆盖断言。
- 复跑次数从 2 改为 3（p=0.5 时假阴性率 12.5%，p=0.7 时 34%），另记 observed_pass_rate。
- flaky 记 flaky_cause（model / env）。
- 结论分三种，退出码 0 / 1 / 2，rerun_invalid 不压成回归。
- sha 带 ? 时默认警告，加 `--require-sha` 才收紧。
- 选题用人工判定，`--only` 补进比较器漏判的题。
- `--rerun` 跑完直接写 verdict。
- 比对项补上 python、pandas、use_dictionary。
- 复跑行用 attempt + duration_s，不用 time。

**S 第三轮改定**：
- match 按三态处理：executed=False 算答错；executed=True 且 match=None 是比较器自己崩了，算无效观测，需要补跑。
- 回归和 flaky 都要人工签字（签在 reruns 行的 human_correct 上）。match 只用来决定人工先看哪几行；删掉了我补的"match=false 直接定回归"。
- 退出码分四档：0 通过 / 1 有回归 / 2 无法判定 / 3 前提不满足。run_gate.py 的前提失败统一改为 3。m13 / phase35 成功路径的退出码有意不改，这一点写进方案和 gate README。
- 防抽签只拦默认路径；`--only` 加 `--reason` 可以替换该题的复跑结果，并记一条 rerun_history。
- 每跑完一行原子落盘一次。

**偏离**：dataset 失败归为无效复跑。S 草案的 INVALID 里没有 dataset；这样做的理由和 flaky_cause=env 一致：闸门数据是冻结的本地文件，读取失败属于环境问题。

**已知前提偏弱，不修**：run() 没有把 data_path 传给 run_metadata，报告里没有 data_sha256。

## [50] 2026-10-21 · A1 错题自动复跑：实现 · commit cc4905d（PR #63，tests run 39523711448）

**结论**：按 [49] / phase5「A1」实现。scripts/gate/run_gate.py 新增 `--rerun`、profile m13r（docs/gate/thresholds.json）和退出码 0/1/2/3；m13 / phase35 的结论路径不变。

**改了什么**：
- run_gate.py：
  - 抽出 `_case_row`，主报告和复跑行同构；`_analyze` / `_current_env` 单独一层，供测试打桩。
  - `rerun()`：检查主报告已判完 → 逐项比对环境 → 选题（名单外错题 + `--only`）→ 逐题跑到 3 次有效或 4 次封顶 → 每行原子落盘 → 直接写 verdict。
  - `_verdict_rerun()`：复跑题分为 regressions / flaky / pending_review / rerun_invalid / not_rerun；flaky 带 flaky_cause 和 observed_pass_rate；verdict 写明假阴性率 p^3。
  - 前提失败统一走 `_fail()`（stderr + 退出码 3）。
- thresholds.json：新增 m13r（agents 和 m13 相同，另加 `rerun: {times: 3, max_makeup: 1}`）。
- docs/gate/README.md：补上用法和退出码，写明 m13 / phase35 的 0 不表示通过。

**实现细节（方案没写死的地方）**：
- `--rerun` 用 `--agent` / `--no-dict` 声明本次环境，再和报告比对，所以 agent 和 use_dictionary 能比出不一致。
- 带 `--only` 时，选题 = 尚未复跑的名单外错题 + `--only` 指定的题；`--only` 里已复跑过的题，旧行整组搬进 rerun_history 后替换。
- m13r 下 `{g}_regressions` 是复跑后人工确认的回归；名单外错题另列为 `{g}_rerun_candidates`。
- 有回归时退出码为 1，即使其他题还没签完也是 1。

**验收**：tests/test_gate.py 新增
- 用法与流程：`test_rerun_selection`、`test_rerun_refuses_undeclared_repeat_and_only_replaces`、`test_rerun_interrupted_keeps_complete_rows_and_resumes`、`test_rerun_attempt_counts`、`test_rerun_match_tristate`
- 判定：`test_rerun_verdict_requires_signatures`、`test_rerun_signed_false_is_regression`、`test_rerun_invalid_rows_need_no_signature_and_flaky_cause_env`、`test_m13r_without_reruns_is_pending`
- 前提：`test_rerun_env_mismatch_refused`（8 项）、`test_rerun_dirty_sha`、`test_rerun_requires_labeled_main_report`
- 结构约束：`test_cli_exit_codes`（子进程实测 0/1/2/3）、`test_m13_baseline_verdict_unchanged`（162428 / 163133）、`test_rerun_kinds_whitelist_covers_error_kinds`、`test_m13r_agents_equal_m13`

变异检查：去掉"executed=True 且 match=None 判无效"后，tristate 用例变红；去掉 pending 排序后，签字用例变红。

**未做**：真模型复跑（S 跑）；[28] 的旧复跑报告不迁移；data_sha256 仍缺。

## [51] 2026-10-21 · G1 闸门 25 条 oracle 上 CI：方案 · commit e2d6fe6（PR #64，tests run 39528333970）

**结论**：方案写在 phase5「G1」。本 PR 只有方案。

**依据**：
- tests/test_gate.py:234 / :302：没有数据时 25 条全部跳过，CI 上从来没跑过。
- HANDOVER §3：要求"改内核时一定要在本地跑"，但没有任何东西强制。

**本地实测**：
- data/gate 共 173 MB，下载约 90 MB。
- oracle 25 passed，耗时 65 s（其中 fixture 36 s）。
- verify_gate 36 s，重算出的 answers.json 和库里的逐字节相同。

**S 第一轮改定**：
- 新增 `build_gate_data.py --check`：只读现场文件，和指纹比对。缓存命中和未命中两条路径都要跑；源指纹和产物指纹分成两组常量。
- 缓存命中时完全跳过 build，避免 to_csv 随 pandas 变化导致指纹天天对不上。
- 数量断言改为 junitxml 加 python 解析（Windows 默认 shell 是 pwsh，没有 grep）；用 node id 精确选中测试，不用 `-k`。
- skipif 自己感知 REQUIRE 开关，缺数据时 `pytest.fail("闸门数据缺失…")`，不再靠数量断言间接报错。
- 写明缓存作用域和 7 天淘汰规则：合并后在 master 上 workflow_dispatch 预热一次；冷启动和 UCI 挂掉时的表现写进 README。
- timeout 改为 20 分钟。HANDOVER 改为"主矩阵 skip、gate-oracle 必跑"。.gitignore 注释从 110 MB 改为 173 MB。
- 许可补一条边界：将来商用时要重审 NC 条款。
**S 第二轮改定**：
- 显式 `read_excel(engine="openpyxl")`；单份 PRODUCT_SHA12 是否同时适用两个 OS，要在首次运行时实测，不等就拆成按 OS 两份。
- cache key 加入 requirements*.txt 和 fingerprints.py；不设 restore-keys；restore 和 save 拆开，save 只看 build 和 --check 的结果。
- `--check` 改为校验目录集合相等；放在 pytest 之前。
- junit 期望值取 `len(QUESTIONS)`。
- `DATACHAT_GATE_DATA_ROOT` 用一个 helper 统一提供，HAVE_DATA 和 fixture 共用。
- 验收：每个 OS 各跑一次 miss 和一次 hit；Windows 上验证非 ASCII 文件名经过缓存往返后不变。
**S 第三轮改定**：
- verify_gate.py 改了之后，verify_script_sha256 必然会变。选 A：在同一个 PR 里重新生成 answers.json，只允许这一个字段变化，并在 PR 描述里贴出这行 diff。
- check_junit.py 直接 `import questions`（scripts/gate 不是包）。
- 两处 read_excel（build:129、verify:56）都写死 engine="openpyxl"。
- 缓存命中时，用机器断言 build 被 skipped（shell: bash）。
- 验收要区分两跑和三跑：第一跑 --check 红算采样，不算失败；master 预热同理。
- timeout 改为 25；--check 只放在 gate-oracle 里；cancel-in-progress 的成本写明，不改。

## [52] 2026-10-21 · G1 闸门 25 条 oracle 上 CI：实现 · commit db7147f（PR #65，tests run 39535946877）

**结论**：按 [51] / phase5「G1」第三轮定稿实现。tests.yml 新增 gate-oracle job（ubuntu + windows × 3.12），缺数据报红；主矩阵里 25 条照旧 skip。

**改了什么**：
- `scripts/gate/fingerprints.py`（新）：源指纹 `UCI_XLSX_SHA256` / `OLIST_FILES` 原样从 build_gate_data.py 移过来；新登记产物指纹 `PRODUCT_SHA12`（零售明细 dbb0119d94e1、零售报表 ab8c674de110，本机 pandas 3.0.6 / openpyxl）。
- `build_gate_data.py`：`--check`（`check(out, expected)`：目录集合恰好相等，多余文件/目录、缺失、指纹不符逐条列出期望与实际；不下载、不写、xlsx 只算哈希）；build 结束时自动跑同一个校验；`read_excel(engine="openpyxl")`。
- `verify_gate.py:56`：`read_excel(engine="openpyxl")`。→ `answers.json` 重生成，**diff 只有 `verify_script_sha256` 一行**（69b9d43982d2 → 361020316d58），其余逐字节不变。
- `scripts/gate/check_junit.py`（新）：期望 = `len(questions.QUESTIONS)`，裸 `import questions`。
- `tests/test_gate.py`：`_gate_path()`（读 `DATACHAT_GATE_DATA_ROOT`）供 HAVE_DATA 和 gate_data fixture 共用；`skipif(not HAVE_DATA and not REQUIRE_DATA)` + 函数首行 `pytest.fail("闸门数据缺失…")`；新增 17 条 G1 测试（子进程 REQUIRE 红 / 不设照旧 skip；check 通过 + 6 种拒绝；check 只读且不下载不读 Excel；expected_files 覆盖登记常量；check_junit 以真实命令行跑，2 正 4 反）。
- `.github/workflows/tests.yml`：gate-oracle job（restore/save 拆开、精确 key v2、命中断言 build=skipped、--check 在 pytest 前、junit 断言、ubuntu 答案冻结、timeout 25）。
- docs/gate/README.md（CI 小节、怎么读红、缓存作用域、许可边界）、HANDOVER（主矩阵 skip / gate-oracle 必跑）。

**变异检查**：
- skipif 去掉 `not REQUIRE_DATA` → `test_g1_require_data_fails_with_plain_message` 红。
- fixture 改回写死 ROOT 且去掉首行 fail → 同一条红（子进程读到本机真数据、25 passed）：证明 helper 两处都要。
- check 不收集多余文件 → `test_g1_check_rejects` 的 4 个 extra 用例红。

**实测**：本地 `--check` 11 个文件全 ok；build（缓存未命中路径，本机已有源文件）30 s，产物指纹与登记一致；verify_gate 27 s；REQUIRE=1 下 oracle 25 passed + check_junit exit 0。CI（PR #65，tests run 39533487774）：
- **走的是两跑分支**：attempt 1 缓存未命中，两个 OS 都绿。ubuntu 的 gate-oracle job 119004615630 用时 2m22s，windows 的 job 119004616113 用时 3m05s，两边都打出 "Cache saved"。
- **两个 OS 的产物哈希相同**：零售明细 dbb0119d94e1，零售报表 ab8c674de110，都等于本机登记的值。所以单份 PRODUCT_SHA12 成立，不用拆成每个 OS 一份。
- attempt 2 用 re-run 触发，两个 OS 都命中缓存：ubuntu job 119007564605 用时 1m41s，windows job 119007564737 用时 1m59s。"命中时必须跳过 build" 这一步执行的是 `test "skipped" = "skipped"`，结果为绿。Windows 上非 ASCII 文件名经过一次缓存往返后，`--check` 11 个文件全部 ok。

**反向演示**（都只在 PR 分支上做，已 revert，squash 后不进 master）：
- **改坏 s01 的 oracle**（b79dddf，run 39535329095）：两个 OS 的 gate-oracle 都变红。日志依次出现 `FAILED …[s01]`、`1 failed, 24 passed`，check_junit 打出"实际 failures=1"并 exit 1。这次命中了缓存。
- **改产物指纹**（7ec10bc，run 39535612173）：两个 OS 都变红，报错为 `✗ 指纹不符：retail/零售明细.csv 期望 dbb0119d94e0 实际 dbb0119d94e1`。
  - 和方案的偏离：指纹改动会进 cache key，所以这次必然未命中，红在 build 末尾的同一个 `check()` 上，独立的 --check 步骤是 skipped。缓存命中路径上 --check 的拒绝逻辑，由 `test_g1_check_rejects` 的 6 个用例覆盖；常量改了却仍然命中的情况，按设计不会出现。
  - 同一次 run 里 save 也是 skipped，说明坏数据没有写进缓存。

合并后预热（master，db7147f）：第一次 workflow_dispatch（run 39537520731）两个 OS 都未命中缓存，Cache saved，oracle 25 passed；第二次（run 39538582322）两个 OS 都命中，"命中时 build 必须 skipped"为绿，25 passed。合并触发的 push run 39537509967 被 concurrency 取消，符合预期。G1 完成。

## [53] 2026-10-21 · F4 迭代 V1：工具栏和标记卡的视觉（方案）· commit 6167278（PR #66，tests run 39552676693）

方案见 phase5-frontend.md「F4 迭代 V1」。依据是 S 10-20 对 MVP 的评价"很不好看"，以及 10-21 的实拍截图（1400×900；柱图 8 类、饼图 12 类）。截图里看到的五个问题，S 在代码里逐条核对过。

S 第一轮评审提了五个阻断项，改定如下：
1. 卡宽：原稿是 360 宽、20px 色块、96px 名称，S 算出会溢出 42px。改为色块 16、名称 88、卡宽 380，可用 342，一行 326。
2. 验收改成"导出字节的期望值不变；选择器和禁用断言按分组重写"，并逐行列出 f3-switches :65 / :76-77 / :82-89、f4-panel :117-118、EChart.test :391 各自怎么改。
3. 浮层定位写死：锚点是 .chart-controls（relative），向上展开；可用高度按 .main 可视区算，不足 160 就改为向下展开；z-index 20。
4. 组级理由用静态组文案，按现有 COMPAT 只有三种情形，逐一列出；理由常显在 aria-describedby 指向的 .marks-why 里，tile 用 aria-disabled，不用 disabled 属性。role="tab" 改成 group + aria-pressed。
5. 形态和计数：卡里共 12 项（8 项来自 F3，4 项来自 F4），每项写明控件形态（legend 是两段按钮）。排序也走"不适用就隐藏"，不设例外。"样式"按钮没有不可用态。F4 第 9 条和 §3 的"置灰"在实现 PR 里同步改。

另外两处小纠正：f4-panel 本来就是先点"样式"，要改的只是内部选择器；chart-hint 照旧在工具栏，所以"四个控件"不等于"四个元素"。

S 第二轮评审提了 6 处问题和 3 处澄清，改定如下：
1. 标签列宽统一成 88，全卡只用这一个值；原第 3 条里的 72 作废。
2. f3-switches :76-77：作用域改到卡上，并且先打开卡和组，再加一条圆角 toHaveCount(1) 作正向对照。不改的话，开关搬家后这两行会无条件绿。
3. f4-panel 要改的地方补全为 4 处：:109、:117、:118、:120。
4. EChart.test：helper :366 和用到它的 4 个 test（:372、:380、:391、:397）一起改。
5. 组改成可以多开，这样 aria-pressed 的语义才正确；整页仍然同一时间只开一张卡。
6. 色块列表 max-height 改成 calc(8 × 24px) = 192px，第 9 个条目起滚动。
澄清：
- .marks-why 只占一行，多条用「 · 」连接，始终保留一行高。
- 向下展开的 e2e 要把工具栏滚到贴顶才能触发。
- right: 0 对齐的是工具栏右缘，这是有意的，不是对齐按钮。


## [54] 2026-10-21 · F4 迭代 V1：工具栏和标记卡的视觉（实现）· commit 28a6271（PR #67，tests run 39558589824，sidecar run 39558589898）

按 phase5「F4 迭代 V1」实现。[53] 已回填 6167278。

**改了什么**
- 新增 `marksGroups.ts`：5 组 12 项（GROUP_ITEMS）、项可见性 `itemOn`（只读 compat() / hasAxis()）、组状态 `groupStates`、理由行 `whyLine`。
- `MarksCard.tsx` 重写：tile 行 role=group（"样式分组"），每个 tile 是 toggle button（aria-pressed + aria-controls），展开区 role=region；整组不可用用 aria-disabled，理由常显在 `.marks-why`（aria-describedby）。8 个 F3 开关搬进卡；legend 改成两段按钮"下 / 上"；饼图类目多于色数时颜色 tile 有提示点、颜色组首行写「N 类，多于 M 色，颜色会重复」。
- `EChart.tsx`：工具栏只渲染图型、排序（compat 不过就不渲染）、样式、导出 PNG（+ chart-hint、暗色导出勾选）。卡挂在 `.chart-controls` 里（relative 锚点），`placeCard()` 按 .main 可视区算方向和 max-height；Esc、mousedown 在 chart-controls 之外、再点样式都关；整页只开一张卡（模块级 openCard + useSyncExternalStore）。
- `styles.css`：--ctl-* token；卡宽 380、标签列 88、色块 16、间隔 4、`--row-h` 24、色块列表 max-height calc(8 × 24px)。
- phase5 §3 第 65 行、F3 第二步 404/419 行"置灰"改为"不渲染（F4 迭代 V1 起）"；F4 第 9 条 tile 列表指向 5 组。

**判定表改动（行为为什么变了）**
- f3-switches「开关」：开关定位作用域从 chart-controls 改成卡（先开卡、再展开组），因为开关搬进了卡。:76-77 的 `toBeDisabled()` 改成卡内 `toHaveCount(0)`：不兼容开关从置灰改为不渲染；卡和组都先展开，并加圆角、数值标签 `toHaveCount(1)` 正向对照和形状 tile 无 aria-disabled。刷新后、同图型新图两处同样先开卡和标签组。
- f3-switches「缩放」「渐变切主题」：缩放 / 渐变 checkbox 改到卡内；缩放勾上后按 Esc 关卡，因为卡向上展开会盖住图中心，Shift + 滚轮要落在图上。
- f3-export「✅ 集合」：从"isEnabled"改成"渲染出来的个数 = 1"，因为不兼容的不再渲染（集合本身不变，仍是六个）；排序仍在工具栏。
- f3-export「交互态」：缩放 checkbox 改到卡内，勾完按 Esc（同上，滚轮和图例点击要落在图上）。期望字节不变。
- f4-panel：:109 tab /字号/ → button /^文字/；:117 → button /^轴/；:118 合并改为颜色组里的 "合并为'其他'" checkbox；:120 → button /^颜色/。饼图的轴 tile 从 `toBeDisabled()` 改为 aria-disabled（第 4 条不用 disabled 属性）。选主题后只在卡关着时才再点"样式"（selectOption 不一定派发 mousedown）。
- EChart.test：helper `tile` 改为 getByRole("button", { name: ^n })；「不兼容的开关 disabled」改为「不渲染：单系列柱图的形状组只有圆角；工具栏只有四个控件」；饼图那条改为形状、轴 aria-disabled + 理由行全文；数值标签、缩放的 4 处改到卡内对应组。

**偏离和理由**
- 验收里"色块列表 8/9 条滚动""marks-why 柱图饼图同高"写在 vitest 一栏，jsdom 没有布局（scrollHeight / 高度都是 0），改放 e2e（f4-panel「色块列表」「浮层」两条）。
- "色块的 ✓"是 CSS ::after，vitest 只断言 aria-pressed；✓ 在截图里人眼核。
- "自动"色块按下态不用 2px 外环，改用强调色边框和浅蓝底：实拍里饼图 8 行全是"自动"时，8 个粗黑环很抢眼。选中的调色板色块仍是外环 + ✓。
- 工具栏里的图型 select 显示偏灰：选中项是当前图型，canChangeKind(当前→当前) 不 ok，所以选中的 option 本身是 disabled 的样式。这是改前就有的（10-21 实拍里也是灰的），属于本步"不做：图型 select 的置灰选项"，没动，记一笔。

**测试**
- vitest 新增：marksGroups.test.ts 4 条（三种组不可用情形逐格枚举、颜色和文字恒可用、12 项并集且不含排序、理由行「 · 」连接）；EChart.test「F4 迭代 V1：标记卡」10 条（组多开、整页一张卡、三种关闭、placeCard 上下与 max-height、10 类不提示 / 11 类提示 / 合并后消失、散点标签组理由、工具栏控件集合 9 个夹具、隐藏不改生效、色块 aria-pressed）以及散点排序不渲染 1 条。
- e2e 新增：f4-panel「浮层：不推开文档流、压在最上层…」「工具栏滚到 .main 顶部时改向下展开」「色块列表：8 个条目不滚动，9 个起滚动」。

**实测**（最后一次改动之后全部重跑）：pytest 814 passed；vitest 750 passed（18 files，原 736，+14）；e2e 32 passed（原 29，+3；跑前执行了 prep.sh）；lint、tsc、gen --check、build 都过。

## [55] 2026-10-21 · F5 验收走查清单（方案）· commit b6769cd

[54] 回填为 28a6271。

改了什么：
- phase5 新增「F5：S 验收走查」：§0 的 7 条拆成五条手动路径（①②⑤由 S 用真 Key 跑；③④标为"技术已覆盖，只验真机手感"，并逐条列出覆盖它们的测试名）和两条已闭环的项（⑥ test_web.py:149，不用复核；⑦ THREAT_MODEL §2.3，只确认文档）。截图不入库，S 本机自存。
- phase5 §7「chart_errors 按执行记账」的状态从"已定（待 S 评审）"更正为"已实现（#55 / ff7b8dc，[43]）"。代码早已合并，只是文档没有同步（S 10-21 核出）。

偏离：④ 的 e2e 只刷新页面、没有重启后端；重启路径由 pytest（test_server.py:49、test_web_f2.py:265）覆盖，清单里写明了这一点。

S 10-21 评审补了四处，加两处小改：
- #49 产品不可达。.echart 固定 360px（styles.css:110），而 COMPACT_BELOW 是 300，所以 compact 恒为 false。清单写明"验不了"，并注明"契约、单测、e2e 已完成，产品行为不变"。
- 截图不入库，S 本机自存。证据以走查记录里的文字为准；只有暴露问题的截图才贴到 PR 或 issue。
- 代码签名证书挪到阶段 6 前置事项，附 DV / OV / EV 选型。之前写"由 S 办"不成立，S 没有主体，也没有付款能力。
- ① 只收 .csv（Shell.tsx:157），GBK 要用 Excel 另存为 CSV；Big5 会被 gb18030 静默读错，作为已知局限顺带验。
- ⑤ 的后端延迟改为从 DevTools 的 cancel 响应和 SSE 事件之差取数，不再用秒表。
- 多表要求每个文件的预览都对。⑥ 改为"测试本身即证明"，不用复核。

S 10-21 第二轮：
- [55] 第一段删去「截图统一放 docs/acceptance/f5/」，这句和后来定下的"截图不入库"矛盾。
- F5 标题改为"已定"。
- 删 Streamlit 的连带面列成清单，共 6 处，pytest 基线 814 → 811。
- ⑤ 的 ts 写明是 epoch 秒、3 位小数的字符串（events.py:65、app.py:450）。偏离 S 的建议：cancel 不落事件，库里只有 error(kind=cancelled) 这一条 ts，没法两条相减。所以主路径是 DevTools 里 cancel 的响应时刻减去库里 error 的 ts，EventStream 只作辅助。

走查记录：（S 跑完后填）


**走查记录（S，2026-10-23 ~ 10-26，Windows + Firefox 缩放 90%，真 Key）**
- 五条路径全部通过（S 10-26：「其他的没问题」「都是能接受的」）。⑥ 按 10-21 的约定不用复核。⑦ THREAT_MODEL §2.3 S 10-26 确认无异议。
- 10-23 第一批发现：白屏（Windows .js MIME，#74）和观感 8 条，进了 V2c（#75 / #76）。测试 agent 的基线报告（假模型 ①~⑥ 全过）也一并处理了。
- 10-26 真 Key 发现，S 定为**可接受、不处理**：
  - token 消耗偏高。多表题出 4 张图，没取到数字；单轮预算 130,000 兜底（[66]）。
  - 「写代码」阶段停不下来。停止只在事件之间检查（service.py:119-121），正在进行的模型调用要等它返回；单次 60 秒，加最多 3 次重试（llm.py:33-34）。这是 F2「不主动断流」的设计。
  - 图表标题选不中、复制不了。标题是画在 ECharts canvas 上的。
  - 会话页不显示模式（标准 / 边想边做），只能从步骤条有没有「理解问题」看出来。
- 本机环境：ui\web\dist 是用管理员身份解压的，ACL 锁住了，要在管理员 PowerShell 里用 C:\Windows\System32\takeown.exe / icacls.exe 解锁后才能删（PATH 里没有 System32）。

## [56] 2026-10-22 · F4 迭代 V2a 方案：按 S 设计稿改版 · commit e4b6ef1

[55] 回填为 b6769cd。

起因：10-21 用假模型走查了 UI，拍下 41 个状态，整理出 3 个 P1 和 6 个 P2。S 据此出了设计稿，10-22 交来交接包。经两轮讨论定下口径：不换栈，图表留 ECharts；只改现有 9 个 CSS 变量的值；图标用内联 SVG；需要后端的部分不做，但上传失败、部分完成、中断这三屏要做降级版；标记卡保留浮层，放到 V2b；字重只用 400 和 700。设计稿和交接包都不入库。

改了什么：phase5 在 §7 前新增「F4 迭代 V2a」，共 0–10 节。S 10-22 定了两条：模型错误按 llm_kind 子类给出不同出口，后端补字段这一步单独开一个小 PR，在 V2a 实现之前做；字典读取失败归为黄色。

和交接包 07 的出入，以代码为准：
- 上传失败分成两类。上传时被拒的只有 400 和 413（app.py:318-344）；读取失败的是已经建好的数据集，带 detail.error。Big5 和"表头异常"都捕捉不到（csv_io.py 文档）。
- 部分完成的第三个信号改用 unverified_numbers，不新增"合计对不上"这个启发式判断。
- 删除数据集是硬删，还会级联删除会话（app.py:356-361、db.py ondelete CASCADE），所以保留"输入名称确认"，并写明会删掉 N 个会话。
- 环形图会改到 chart_fixtures，V2a 先保留饼图。
- 输入区里的数据集胶囊只做展示，会话的数据集在创建时就绑定了。
- 上传进度要改用 XHR。
- 「总结」这一段对应 answer 事件，不是 done。

未做：代码。实现按 §9 分三段，放在同一个分支上一起提交。

## [57] 2026-10-22 · error 事件和结果加 llm_kind · commit 39c4741（PR #70，squash 进 V2a 实现；tests run 39882975369）

[56] 回填为 e4b6ef1。

起因：S 10-22 定下 llm 类错误要按子类分出口（phase5 V2a「S 10-22 已定」第 1 条）。前端只按 status、error_kind 分支，不看文案（turn.ts:90），所以需要后端把子类显式给出来。这是 V2a 不改后端原则唯一的破例。

改了什么：
- AnalysisResult 新增 llm_kind，经 to_record 进入 done.result 落库，重放时前端从库里取。error 事件的 data 加 llm_kind，非 llm 恒为 null；Emitter.error 校验"llm 必须给子类，非 llm 不许给"，不满足就抛 ValueError。
- 取值：LLMError.kind（工作流）或 classify_error 的结果（ReAct）；网关错误 JSON 记 gateway_error，包括非致命的整轮重跑事件；没配 Key 记 no_key。
- 停止可能把先前的 llm 错误盖成 cancelled，所以在收尾时统一处理：只要 error_kind 不是 llm，就把 llm_kind 清空（service.py 的 finally 里）。
- events.py 新增 LLM_KINDS（classify_error 的 8 个值加 no_key），docstring 的事件表也同步了；generated/events.json 新增 llm_kinds；turn.ts 的 Result 和 error 事件类型各加一个可选字段。前端界面这次不用这个字段，留到 V2a 的错误卡用。

偏离：no_key 是方案里没有的值。没配 Key 时根本没有发请求，不属于任何 classify_error 的类别；而前端要据此给出"去设置"的出口，所以单列一个值。方案表里已经补上。

判定表：两处断言加了 llm_kind 字段，行为本身没有变，只是事件多了一个键。
- test_web_f2::test_stream_cancel_stops_before_next_event：加 "llm_kind": None。
- test_stream::test_fatal_error_precedes_done：加 "llm_kind": "no_key"。

测试：新增 tests/test_llm_kind.py，共 23 条：
- 8 种异常（timeout、connection、rate_limit、401、403、400、500、409）× workflow / react，断言 res、致命 error 事件、done.result 三处一致；
- no_key、ReAct 网关重跑（非致命事件也带 gateway_error）；
- dataset 错误和成功时为 null；
- Emitter 的约束；
- LLM_KIND_TEXT 是 LLM_KINDS 的子集，classify_error 的输出都落在 LLM_KINDS 或 http_NNN 里；
- events.json 里有 llm_kinds。

## [58] 2026-10-22 · F4 迭代 V2a：按设计稿重做界面（三段合一） · commit 39c4741（PR #70，tests run 39882975369，sidecar run 39882975145）

起因：S 交了设计包（handoff2，07-落地范围为准），方案见 phase5「F4 迭代 V2a」（#69）。S 10-22 要求三段都做完再推，界面"基本和设计稿一样"，可以多改几轮。

改了什么（只动 ui/web，后端不动）：
- 第①段：styles.css 重写，改了原有 9 个变量的值，另外加 6 个（--bg-subtle、--bg-muted、--line-strong、--line-input、--line-muted、--accent-bg）；字重只用 400 和 700；卡片不加阴影。新增 views/icons.tsx，放内联 SVG 图标，都带 data-icon。新增 views/ui.tsx，放 Topbar、Dialog（原生 dialog）、MoreMenu、relTime、createdSuffix。侧栏 248 宽，含品牌行、上传区、数据集行（使用中 / 读取失败、sheet 胶囊、重名时追加创建时间）、会话行（悬停出 ···，可原地改名、弹出确认删除）、设置行。顶栏 60 高，有标题和副标题。输入区有三态：可用、分析中（按钮变"停止"）、禁用（首屏）。助手卡顺序：头（状态标签 6 态、耗时）→ 步骤条（理解问题 / 写代码 / 执行 / 总结，默认折叠，展开就是原来的事件流）→ 黄条 → 结论 → 图表卡 → 尾（👍👎、重新生成）。图表卡是 1px 边框、12px 圆角，工具栏放在卡底，用胶囊控件。
- 第②段：部分完成走黄条，来源是 warnings、unverified_numbers，以及可恢复的字典读取失败（turn.ts partialSignals）。错误卡按 error_kind 分 4 类；llm 类再按 llm_kind 分：rate_limit / 429 倒计时 10 秒后才能重试，auth / no_key / 401 / 403 给"去设置"，bad_request 和其他 4xx 给"重试 + 换个问法"，其余给"重试"。取消、中断给三个出口：重新问一次、换个问法、查看已生成的代码。数据集删除改成对话框：要输入名称才能确认，并写明会连带删除几个会话。读取失败的数据集显示失败卡。设置页凭证分三态（环境变量只读 / 钥匙串可更换、可删除 / 未设置时黄色提示）。会话失效页可以一键复制命令。没配 Key 时会话页横幅常驻，点发送会在前端拦下。首问时顶栏和侧栏的标题当场更新，正在编辑标题时不覆盖。
- 第③段：<1080 时侧栏收成 56 宽的图标条，点开以浮层展开，宽屏也可以手动收起。侧栏上传区和首屏上传卡都能拖放文件，前端拦下非 .csv 和超过 1 GB 的文件。上传改用 XHR（api.ts upload），拿到进度；测试注入 fetch 时退回 fetch。
- turn.ts 新增 steps(turn, agent)、partialSignals、totalSeconds；ECharts 的图型下拉不再把当前图型判成不可换（原来整个 select 显示灰色）。

偏离（带理由）：
- 页面底色改成白色，侧栏用 #F5F5F7，跟设计稿一致；补的 6 个变量名和方案草拟的不一样，个数没变。
- 会话删除按设计稿做成弹出确认，不再是方案里"两次点击"的写法。
- 失效页不做"重新连接"：后端每次启动都换新 token，刷新拿到的还是旧 token，按钮没有用。
- 图表卡不加卡头：标题已经画在 canvas 里（导出 PNG 也带着），再加一个卡头就重复了。
- .echart 高度保持 360，窄屏 300，没用设计稿的 292 / 210：292 低于 #49 的 compact 阈值（300），会改变图的排版。
- 对话列最宽 1214，不是 1140：保持改版前的最大图宽 1174，f3-inject 的类目标签前提依赖这个宽度。1440 视口下内容区本来就是 1140，看不出差别。
- 读取失败的数据集只有拿到详情（上传响应或打开详情）后，侧栏才标红：列表接口不带 error，而后端不改。

判定表（行为变化写明原因；只是选择器变了的单列）：
- 选择器：提问按钮 "提问" → "发送"（设计稿文案）；数据集行、会话行的可访问名带了元信息，测试改用前缀匹配；新建会话按钮移到顶栏，session-view / dataset-view 的 testid 挪到包住顶栏、内容和输入区的 view-root（display: contents）上。
- f2.test 提问：过程默认折叠，先点"查看过程"再断言计划文本；停止按钮在输入区。重放：错误卡标题和详情分成两行；中断的出口从"重试"改名为"重新问一次"，行为不变（同样重发原问题）。
- views.test：删除从"要点两次"改成对话框流程（新测试"删除数据集：输入名称才能确认…"）；注入串多出一处，在右侧字段卡里，同样按文本渲染（2 → 3）；设置页保存 Key 后输入框换成另一个元素（加了 key）。
- EChart.test 5001：警告从 li 挪进 .wbar-title，断言"只此一处"不变。
- e2e f1：副标题 "数据集：水果 · ReAct" → "水果 · ReAct · 0 轮"。
- e2e f2（nokey）：前端会拦下没 Key 的提问。改成先断言拦截（横幅、没有消息），再用 API 发起真实 SSE 走后端的 no_key 路径，刷新后断言错误卡、"去设置"出口、👍、重放一致。流式渲染由 fake 项目的 f3 系列覆盖。
- e2e f3-stop：plan 文本折叠起来了，改为等步骤条 data-step=plan done、code running 后再点停止，停止按钮在输入区。
- e2e f3-inject：先点"查看过程"再看代码面板；新增 DOM 元素的检查只放过 svg[data-icon]（源码写死的静态图标），其他 svg 照样记；钉住图宽 1174。

测试：新增 src/views/v2a.test.tsx，共 29 条：状态标签 6 态加正在停止；步骤条（工作流、修复重试 ×2、ReAct 无计划、出错标段、停止标段）；部分完成的信号；错误卡 10 种 error_kind / llm_kind 组合的标题和按钮，加 429 倒计时；没配 Key 的前端拦截；重名数据集后缀；非 .csv 上传在前端拦下。

未做（V2b 或方案外）：标记卡视觉对齐、按列着色、标题输入、应用到同类图表、"完成"按钮；环形图；继续追问；XLSX；表结构（DDL）和"从这张表开始"的建议；图表主题画廊页。

验收第一轮（S 的 v2a-验收清单.md，50 条）：
- P0：对话框遮罩改黑 32%；删除按钮禁用态改灰（原来是红色降透明度，看着像粉色的另一种红）；标记按钮从"样式"改名"标记"，打开时默认展开颜色组；markdown 只有 http(s)/mailto 渲染成链接，其余只留文字（span.md-link-blocked）；··· 菜单改 fixed 定位，按按钮位置夹在视口内，最小宽 200；暗色主题只染画布，控件行保持浅色；执行中去掉往复进度条，改骨架占位；输入区上方加渐隐，主区底部留白 28px。
- P1：错误卡正文只写发生了什么、能做什么和编号（取助手消息 id 前 8 位，与后端 trace_id 同源），后端原文收进"技术详情"；llm 类按 llm_kind 给标题；副标题去掉"工作流"，改"N 轮对话"；"分析方式：工作流/ReAct"改"模式：标准/边想边做"；预览说明按真实行数写；编码提示只在非 UTF-8 时出现；来源卡分"数据文件/字典文件"；读取失败的建议按错误映射；"钥匙串"统一改"系统凭据"；上传拦截文案改"只支持 .csv；a.xlsx 不支持"；会话删除标题改"删除这个会话？"；"主题"一词统一（顶栏"主题 经典"，调色板图标）。
- P2：上传改成对话框（两个入口共用，文件清单、名称、进度在一处）；侧栏数据集元信息去掉字节数；步骤 <0.05s 不写秒数；有别的轮次在跑时重试/重新生成置灰而不是消失；查看/收起过程用下/上箭头；过程区加浅底；表格行高 40；空会话下沉居中；设置页"已设置"改绿色加勾；正在停止用蓝色。
- 判定表：e2e f3-inject 的"对照：危险链接确实渲染成 <a>"改为"渲染成 span.md-link-blocked 且没有 <a>"，原因是 P0-4 的行为就是不再出链接；f4-panel 和 EChart.test 里点"颜色"的地方改为"未展开才点"（默认已展开，原样点会收起）；f2 e2e 错误卡标题按 no_key 断言"还没有配置 API Key"；f1 副标题、模式下拉跟着文案改。
- 没改、待 S 定：柱顶数值、y 轴上限、轴名间距、窄屏 grid（P2-18~22）都会改 chart_fixtures 和导出字节，07 §4 不许动；P1-16 失效页"重新打开应用"在浏览器里做不到，放阶段 6；P1-17 图表警告的文案在后端（chart_warnings），前端改写就是匹配后端文案。

验收第二轮（S 的 v2a-验收-r2核对.md）：
- P0-1 真修：删掉输入区上方的渐隐（它把"看不全"画成了设计）。根因不是 padding：输入区本来就是 flex 尾部、不占滚动区，但打开会话时停在顶部，最后一张图被视口下沿切掉；现在打开会话落在最新一轮，内容长高时只要用户在底部附近（≤ 80px）就跟到底（ResizeObserver 只盯 .messages），翻上去看旧内容时不打扰。.main 底部只留 24px。新增 e2e f4-layout「输入区不遮内容」钉住几何：1024×768 两轮带图，滚动区下沿 = 输入区上沿（±1px），最后一张卡下沿 ≤ 输入区上沿，距底 ≤ 2px，重开会话同样成立。
- 失败页：重新上传改蓝色实心主按钮，删除这个数据集降为灰色文字按钮放右边，间距 16。
- 删除确认：标签写明「输入「名称」以确认」，输了但不一致时下方灰字提示；aria-label 不变。
- 标记浮层：半透明（rgba(245,245,247,.80) + 1.5px 模糊），压着的柱子能看见改色。结构和方向判断不动。
- 停止中：骨架不再显示；按钮和徽标文字"正在停止…"改"停止中"（f3-stop 判定字符串随之改，原因是文案变了，测的仍是点击到文字变化的延迟）。
- 次要按钮（换个问法、重新问一次的旁边）统一白底描边；错误卡去掉红框只留浅底；技术详情改成和查看过程同一种下/上箭头折叠，正文默认 hidden（仍在 DOM，e2e 判定不变）；完成态时间写"用时 Xs"；骨架第三块高 360 和图一致；所有对话框加右上角 × 关闭。
- 失效页加「重试连接」：用手上的令牌再请求一次 /settings/key，成功回到应用；401 提示"后端换了访问令牌，需要用上面的命令重新打开"，网络错误提示"后端没有响应"。
- e2e 新增 2 条（f4-layout.spec.ts）：上面的几何；删除对话框 ::backdrop 不透明度 > 0.2 且是压暗；顶栏 ··· 菜单左右各距视口 ≥ 8px。
- 失败页居中：1024 下主区 56–1024、卡片 232–851，中心差 1.5px；S 量到的 25px 是侧栏抽屉展开时的截图（抽屉是浮层，不挤主区）。截图 24 改名 24-narrow-dataset-failed，抽屉另存 24b。
- 没做：设置页「测试连接」要后端新接口，不在"后端不改"范围内；P2-18/19 见下条待定。

验收第三轮（S 的 v2a-验收-r3判定.md；本地 commit 5baadba 之后）：
- P2-18 柱顶数值（S 定口径，非 A 非 B）：数值标签的存储态允许缺省（StoredSwitches.label?: boolean）。undefined = 用户没碰过，套设计默认 DESIGN_LABEL（柱 / 线 / 面积开，饼图 / 散点关）；false = 用户主动关。类目 > 30（LABEL_AUTO_MAX）时设计默认降为关，面板里写"类目过多，数值标签默认关闭"，用户手动开照画。applySwitches 只看解析后的布尔值，"全关 = 后端原样"契约、fixtures、switches.test 的夹具恒等断言都不变。改别的开关只落那一个键（不把 label 冻成显式值）；「重置」= 层 1 清空 + clearPrefs（回到设计默认，不是全关）。
- 判定表改动（行为为什么变：默认值从关改为开）：EChart.test「开关：点一下即重设」从勾上改为取消勾选、导出 ui.sw.label 期望 true；f3-export「逐个打开与全关不同」和 f3-switches「逐个打开像素有变化」的基线改为先主动关掉数值标签，并新增断言：默认态与全关不同。新增 EChart.test「P2-18 数值标签的设计默认」4 条、switches.test「P2-18 设计默认」2 条。
- P2-19 yMax：S 定放 V2b（'dataMax' 会顶到上沿），和数值标签一起调。
- 删除确认取 dataset.name：未命名时默认是第一个文件名（sales.csv），命名「门店销售」就要输「门店销售」。上轮汇报说"名称是 sales"是我说错，UI 没问题。
- follow-up：重试图标换 refresh-cw；浮层 .80 → .58 + 阴影（内层 .42）；骨架色 #ECECEE、补 40px 控件行占位；停止中徽标脉冲（reduced-motion 下关）；失败页和失效页统一垂直居中；失效页图标换时钟、底部说明色 #6B6B70；停止 / 出错的轮次步骤条保留没走到的段（灰），和运行中一样长（v2a.test 步骤条 3 条期望随之补齐）。
- 错误块圆角：代码里一直是 12px（styles.css .errcard），13 号截图放大可见圆角，未改。
- 验收第四轮（S 的 v2a-验收-r4判定.md）：24 失败卡改成 grid 居中后，子项按 max-content 收缩到 313px（P0 回归）→ `.failcard` 显式给 `width: min(620px, 100% - 48px)`；24 底注色同步为 #6B6B70；错误块底色 #FCE9E7 + 内描边 rgba(215,0,21,.08)（圆角一直有，只是 1.06:1 下看不见）。08 控件行与图块是同一条 shimmer 渐变，同一 x 采样一致（x=1000 均为 238），未改。f4-layout `--repeat-each=5`：先暴露测试自身问题（repeat 共用后端，同名数据集撞 strict mode；第一轮两轮带图在冷启动下超默认 30s）→ 文件名加时间戳、该用例 setTimeout 120s，之后 10/10 过。随后全量闸门再出 1 failed，这次拿到用例名：f4-layout「删除对话框…」等不到刚上传的数据集——真 bug：Shell 首屏 reload 还没回来就上传完成，旧列表回来后 setDatasets 把新数据集冲掉。修：Shell 加 dsGen，本地上传后发出前的 reload 结果不覆盖数据集列表；e2e 扣住首屏 GET /datasets 到上传完成后再放，回退修复时该用例红、修复后绿。r3 那次未取到名字的 1 failed 推测同因（未证实）。
- PR #70 评审（S 10-23）：可合并，合并前补两处，另顺手做 P2/P3：①竞态机制补全——`dsGen` 改名 `listGen`，reload 结果代际不符时 datasets/sessions 整体丢弃；新建/改名/删除会话（含 SessionView onChanged/onDeleted）都先 `touched()`；新增 vitest「列表竞态：reload 在飞时新建会话…」（回退到 365a21b 的 Shell 时红）。②`prefers-reduced-motion` 同时停骨架 shimmer。③f4-layout 两处 `waitForTimeout(400)` 换成 `expect(...).toPass({ timeout: 10_000 })` 整组几何重试。④`dirty` 改为按 SWITCHES 逐键比，不依赖 JSON 键序。⑤Markdown 白名单注释写明站内锚点 `#` 也被挡。⑥`effectiveKind` 签名收窄为 `Pick<UiState, "kind">`，EChart 不再传无用的 sw。
- S 复核（10-23 09:00，按描述做逻辑审查）：⑦DatasetView.onDeleted 也先 `touched()` 再 `reload()`（否则更早在飞的 reload 会把刚删的数据集带回来），入口共 6 处；⑧reload 失败分支同样判 gen，过时请求的失败不报错；⑨f4-layout 的 overflow 前提移到 toPass 外断言一次，前提不成立立刻红。
- 本地 e2e 环境：Linux 新环境/沙箱重置后先装 Chromium 系统依赖 `cd ui/web && npx playwright install-deps chromium`（症状：e2e 全部约 1ms 红，日志 `libatk-1.0.so.0: cannot open shared object file`）。CI runner 镜像自带，不用跑。

## [59] 2026-10-23 · 四屏视觉回归（toHaveScreenshot）+ HANDOVER 第二版 · commit 1c0b41a（PR #71，tests run 39891923237）

[57][58] 回填为 39c4741（#70 把 llm_kind 和 V2a 实现 squash 成了一个提交）。

起因：S 在 r4 判定里指出 V2a 验收"改一处塌一处"出了三次（r2 遮罩→删除按钮变粉，r3 居中→失败卡宽度塌 49%，r4 底注色只改一半），当时 4 条行为 e2e 全绿，没有一条看像素；建议给 24/25/11/08 四屏加 toHaveScreenshot，maxDiffPixelRatio 0.002。#70 评审时同意延后到下一批。S 10-23 说做这一批，并要交接给下一个 agent，所以 HANDOVER 一起重写。

改了什么：
- 新增 ui/web/e2e/f4-visual.spec.ts（fake project，4 条）+ e2e/f4-visual.spec.ts-snapshots/ 四张基线（*-fake-linux.png）：
  - 08 分析中（1440×900，slow-2s，骨架三块 + 控件行占位、步骤条）；
  - 11 标记浮层（1440×900，chart-bar，浮层半透明压在柱图上、柱顶数值）；
  - 24 窄屏失败页（1024×768，空 CSV，失败卡宽度和居中、主次按钮、底注色）；
  - 25 窄屏会话（1024×768，chart-bar，落底几何、输入区间距、图表卡）。
- 截整页：view-root 是 display: contents，元素截图报 "not visible"。
- 不可复现的部分：宽屏侧栏整块 mask（列表长度随共享后端变化，会把「会话」一节推下去，--repeat-each=2 实测 9% 像素差）；.acard-time、.topbar-sub mask；已结束轮次的 .stepbar mask（每步用时，< 0.05s 时不显示，宽度会变；步骤条样式由 08 钉住）。宽度随内容变的行内文字不 mask（mask 框跟着变宽，框边本身就是像素差），截图前用 freeze() 换成定值：失败卡原因行的 trace 编号、同名重复上传时名字后的「 · HH:MM」（顶栏标题、输入区胶囊）。
- beforeAll 预热（照 f4-panel）。
- HANDOVER.md 整份重写为第二版（接 39c4741）：进度、基线数字、S 的协作规则（含 10-20 以后新增的节奏、判定表纪律、汇报格式、zip 英文名）、不变量（加 llm_kind、chart_fixtures/导出字节契约、P2-18 数值标签、V2a 视觉口径）、下一步候选、视觉回归的基线流程、新踩的坑、前端代码地图和测试地图。

偏离：阈值没用 S 提的 maxDiffPixelRatio 0.002，改为 threshold 0.02 + maxDiffPixels 20。变异实测（改 CSS → build → 跑 f4-visual，跑完还原）：

| 变异 | 默认 threshold 0.2 的差异像素 | threshold 0.02 的差异像素 | 0.002 整页上限 | 新阈值 20 |
|---|---|---|---|---|
| 24 底注 #6B6B70 → #A0A0A5（r4 原样回归） | 82 | 609 | 2592（1440×900）/ 1573（1024×768） | 红 |
| 08 骨架图块圆角 12 → 6 | 0 | 36 | 2592 | 红 |
| 11 浮层底色透明度 .58 → .75 | — | 16134 | 2592 | 红 |
| 不变，--repeat-each=4（16 次） | — | 0 | — | 绿 |

即 S 的阈值下前两条（正是 r4 的那类回归）照样绿。不变时本地 16 次为 0 像素，留 20 像素余量给字体光栅的偶发差。

未验证 / 风险：基线是在沙箱（aarch64）生成的，CI 是 ubuntu x64。两边 Chromium 版本相同，字体都来自 install-deps，但抗锯齿可能有差。首次上 CI 若 f4-visual 红，按 HANDOVER §6「视觉回归」从 playwright-results 工件取 *-actual.png 换基线（先看 diff 确认只是抗锯齿），在本条补记。

CI 基线（PR #71，run 39889413891）：首跑 f4-visual 4 条全红，差异像素 3381–4953（ratio 0.01），其余 34 条和 pytest、gate-oracle 全绿。逐张看 diff：差异只在 DOM 文字字形上（中英文抗锯齿），canvas 内的图表文字、柱块、卡片边框、骨架、布局框都没有差异；最大通道差 132，超过 128 的每张至多 1 像素。判定为平台抗锯齿差异，四张基线换成该 run 的 *-actual.png。之后基线只在 CI 上能通过，本地 aarch64 跑 f4-visual 预期会红（HANDOVER §6 已写明换基线流程）。

测试：e2e 34 → 38（新增 4 条，其余不变）。pytest、vitest 条数不变。

当前阶段：阶段 5 收尾。下一步等 S 定：V2b（P2-19~22 + 标记卡对齐等，先写方案）、F5 真 Key 走查、测试连接（需后端接口）。

## [60] 2026-10-23 · 阶段 5 收尾方案：V2b、测试连接、P1-17 · commit 59a7dff（PR #72）

[59] 回填为 1c0b41a。

接手：新一任 agent 读完 HANDOVER 第二版和 §2 的文档后跑了基线（Linux aarch64 沙箱，Python 3.12，Node 24.22.1）：pytest 837 passed，vitest 790，e2e 34 passed + f4-visual 4 failed，lint / tsc / build / gen --check 全过。f4-visual 本地四屏差异像素 08=3514、11=4953、24=3381、25=4497，与 [59] 记的 CI 首跑差异一一相同，即本地渲染和生成旧基线的沙箱一致，差的是平台抗锯齿，符合 HANDOVER §6 的预期。

流程（S 10-23）：剩下三项方案合一个 PR（本条），实现合一个 PR，攒成一批、最后统一跑全量闸门；F5 后删 Streamlit 单独一个 PR。依据 S 10-23 交来的设计包第二版（英文文件名版，不入库）。

改了什么：
- phase5 新增「阶段 5 收尾：V2b、设置页「测试连接」、P1-17」：
  - A 组图表几何：P2-19 y 轴留顶随数值标签走、放前端（单独一步 applyHeadroom，写 yAxis.max + yAxis.interval，判据写死）；P2-20 nameGap 28 → 32；P2-21/22 grid.left/right 改固定 12 / 16 并登记进 GEOMETRY；单系列 grid.bottom 不动。
  - B 组标记卡：竖排组头 + 当前值、理由进组头、拨动开关、底部「应用到所有{图型}」和「完成」、按类目着色、标题输入（UiState 用户串的唯一例外，规则写死）、图型级层 1 默认。
  - C 组 POST /settings/test。D 组 chart_warnings 用户文案不带 ChartError 原文。
- plan.md 进度表补到阶段 5。

评审（S 10-23）后改的：
1. P1-17：初稿说"原文还在查看过程里"是错的——TurnView.tsx 的 exec 折叠区只渲染 stdout / result_text / error，前端零处读 chart_errors。改为明说用户界面不再出现原文，不加新 UI。
2. P2-19：判据写死（t = dmax × 1.08，候选 [1, 2, 2.5, 5] × 10^k 升序，取第一个 ceil(t / step) ≤ N 的），写明 2.5 何时被选中（12 < t ≤ 12.5 时给 12.5）。SSR 实测发现只写 max 时刻度对不齐（非紧凑 max 12.5 → 0, 3, 6, 9, 12, 12.5；紧凑 max 10 → 0, 3, 6, 9, 10；120 → 0, 50, 100, 120），所以同时写 interval = step，紧凑 N = 3。
3. chart_fixtures 影响面：24 条里 21 条变（所有带 grid 的），只有 pie、pie-50、inject-pie 不动；同 PR 重生成。
4. 标题：写成 UiState 例外规则——限长 100（= TITLE_MAX）、C0/C1/Bidi 控制符换空格、parseEdit 单独校验、chart_schema.json 新增 display 导出（unsafe 表 + title_max）。
5. nameGap 改 32（不是 34）：判据是字号「大」下刻度文字到轴名仍留 8px。
6. 单系列 bottom 30 → 16 撤回：会让 COMPACT.bottomMin 14 失去意义。
另：初稿的「90px / 60px」来源查不到，S 确认没给过，删掉，以实测 57 / 36 为准。

偏离（理由在方案各条里）：
- P2-19 不用写死步长 50（最大值 8 会被抬到 50）。
- 标记卡宽保持 380，不跟设计的 300–316：设计的颜色组是 4 色板，我们是每系列一行 × 自动 + 10 色。
- 按列着色只做按 x 轴类目着色，不列数据集的其他列（F4 第 9 条、M13 §3.2：换列属于层 2）。
- P1-17 不按 22 种 ChartError 分文案，用户侧统一两条固定文案。

实测（SSR，探针在仓库外没入库）：夹具 bar 自动 y 上限 = 数据最大值 8；x 轴刻度文字下沿到轴名 8px（1174 / 880 / 640 宽相同）；grid.right 4% 在 1174 / 880 / 640 宽下是 47 / 35 / 26px；刻度对齐见上面第 2 条。

未做：代码；文档 PR 不跑闸门（S 10-23 同意）。

当前阶段：阶段 5 收尾。下一步：S 评审本方案 → 三项实现合一个 PR → S 用真 Key 走 F5 → 删 Streamlit。

## [61] 2026-10-23 · 阶段 5 收尾实现：V2b（A 图表几何 + B 标记卡）、设置页「测试连接」、P1-17 · commit da8ac91（PR #73，tests run 39920953765）

[60] 回填为 59a7dff（PR #72）。

依据：phase5「阶段 5 收尾」一节（#72 合并的方案），逐条照做；分支 feat/phase5-closeout。

改了什么：
- A 图表几何：
  - P2-19：新增 ui/web/src/charts/headroom.ts（applyHeadroom，管线里排在 applySwitches 之后、applyView / applyCompact 之前）。判据照方案写死：t = dmax × 1.08，候选 [1, 2, 2.5, 5] × 10^k 升序，取第一个 ceil(t / step − 1e-12) ≤ N（非紧凑 6、紧凑 3）的 step，写 yAxis.max = n × step 和 yAxis.interval = step，按 step 的小数位 round。只在数值标签解析为开、柱 / 线 / 面积、值轴、层 1 之后 yAxis.min / max 都没设、dmax > 0 时写。写出的键登记为 HEADROOM_KEYS；M13 §12「数值标签」一行的"前端实际写出"补 yAxis.max、yAxis.interval。
  - P2-20：charts.py `_X_NAME.nameGap` 28 → 32。P2-21/22：grid.left / right 从 `_CART_GRID` 的 '3%' / '4%' 挪进 GEOMETRY.grid，改固定 12 / 16（`_GRID_SIDES`），旧图经 normalize 归一。单系列 grid.bottom 30 不动。chart_fixtures 24 条里 21 条变（pie、pie-50、inject-pie 不变），kind_fixtures 同步重生成。
- B 标记卡（MarksCard.tsx 重写，结构和无障碍语义保留）：
  - B1：卡头「标记」+「N 个图形元素」（颜色组列出的项数）+「重置」；组改竖排组头（h40：图标、组名、当前值、箭头），展开内容紧跟组头；整组不可用时组头仍在、当前值位置写 groupReason、aria-describedby 指向它，.marks-why 删掉（whyLine 一并删）；开关改拨动开关（input checkbox + role="switch"，「合并为'其他'」同样改）；底部固定区：提示 +「应用到所有{图型}」+「已单独改过的图保持不变」+「完成」（= 关卡）。宽度保持 380。
  - B2：Edit.colorBy "series" | "data"，只对单系列柱图出现「按列着色」下拉（选项「不按列（每个系列一色）」/ x 轴名）；选 data 写 series[0].colorBy = 'data'，颜色行换成类目，改色写到数值点（就地包成 {value, itemStyle}）；类目多于色数照饼图提示。LAYER1_KEYS 加 series[].colorBy、series[].data[].value。
  - B3：新增 title.ts（sanitizeTitle / isCleanTitle）。「文字」组加「标题」输入，占位符是后端标题，留空回到后端标题；只写 title.text。gen_ui_types 往 chart_schema.json 加 `display: {unsafe, title_max}`；parseEdit 对 title 单独校验（string、≤ 100 码点、sanitizeTitle(v) === v，否则只丢 title）。导出文件名取用户标题，仍经 safeFilename。THREAT_MODEL §2.3 加一行；prepare.ts / switches.ts 头注释按方案改。
  - B4：每张图只存自己设过的字段（EditPatch，parseEdit 不补默认，老数据里有的字段视为自己设过）；图型默认 `datachat.chartEditKind:<kind>` 只收 colors / colorBy / font / other；生效层 1 = EMPTY_EDIT ← 图型默认 ← 这张图自己设过的。「重置」只清这张图自己的（+ 开关回设计默认）；有图型默认时卡头多「清除{图型}默认」。
- C 测试连接：app/core/llm.py 加 PING_MESSAGE / PING_TIMEOUT_MAX / ping()（ChatOpenAI max_tokens=1、max_retries=0、超时 min(timeout, 15)，网关错误 JSON 同样判失败）；app.py 加 POST /settings/test（Bearer；用 llm_config() 即已保存的设置；没 Key 不发请求返回 no_key；失败 message 走 user_error；非阻塞锁，第二个 409；不落库、不写 events）。没 Key 的文案提成 errors.NO_KEY_MESSAGE，分析和测试连接共用。tests/fake_llm.py 加 MARK_PING 链路（整条消息等于 "ping" 才认，回 "pong"；fail / hang / slow 照常作用；带 @step 一律 400）。前端 SettingsView 在凭证卡和模型卡下面加「测试连接」：表单有未保存改动（模型三项和保存值不同，或填了新 Key 没保存）时不可点并写「先保存再测试」；测试中 / 连接正常 · 0.8s · 模型名（绿）/ 失败显示 message；auth、no_key 时焦点移到 Key 输入框。
- D P1-17：result.py chart_warnings 的两条改成固定文案（CHART_NONE_WARNING「图没画出来：模型给的画图参数和结果数据对不上。结论不受影响，可以重新生成。」、CHART_PARTIAL_WARNING「另有 N 张图没画出来：画图参数和结果数据对不上。」），ChartError 原文照旧经 chart_errors 回到模型。

偏离（按代码事实做的最小偏离）：
1. HEADROOM_KEYS 和 FRONTEND_KEYS 分开登记（方案只说"登记为 HEADROOM_KEYS"），但 switches.test 的例外层机制测试（prepare 产物相对全关的差 ⊆ FRONTEND_KEYS，switches.test.ts:94 起）和"M13 §12 前端实际写出 = FRONTEND_KEYS"那条会因此红：前者改为 HEADROOM_KEYS 的路径也算登记（值须是正的有限数、基线里原本没有），并断言两个键都被写到过；后者比对 FRONTEND_KEYS ∪ HEADROOM_KEYS。判据本身由新的 headroom.test.ts 钉。
2. 堆叠时的 dmax 取每个类目**正值**的堆叠和：ECharts 默认 samesign 堆叠，负值往下堆、不顶上沿；全正时与"堆叠和"相同。
3. 方案 D.4 的判定变更清单漏了三处，按代码事实一起改：ui/web/e2e/f3-inject.spec.ts:156–157（原断言警告里有 `图表未生成：x 列 '<P1>' 不存在` 和 P2–P5，现在是固定文案且不含 P1–P5）；THREAT_MODEL §2.3 验证表 :84、:87 两行（改写成"原文只回到模型、警告是固定文案"，测试名随改名更新）；tests/test_fake_llm.py 的 test_real_chain_inject_error_reaches_warnings 改名 test_real_chain_inject_error_reaches_model_not_warnings（名字和新行为一致）。
4. e2e f3-themes「#49：1200×220」方案没预告：柱图数值标签默认开 → 留顶生效，数据 [0, 3] 的轴变成 [0, 4]（紧凑 N = 3：t = 3.24，step 2，n = 2）。原测量把 plot 上沿按 v = 3 映射，实测 plotRatio 掉到 0.345（< 0.4）——量的是 3 的位置，不是 plot 上沿。改为按画出来的最高刻度 max(3, v1) 映射（没有留顶时 v1 ≤ 3，与原来相同），首末刻度断言 0 / 3 → 0 / 4（并断言没有 3）。
5. 「形状」组的当前值按"开且在当前图形状下兼容"判已改（堆叠在单系列图上开着也不生效，显示"已改"是假话）。
6. 切换「按列着色」时清空颜色改动（colors 的 index 一个是系列、一个是类目，含义变了）；colorBy = data 的颜色在换成非柱图（饼图除外，饼图 index 本来就是类目）时不套到系列上。
7. 「合并为'其他'」也改成拨动开关（卡内统一）；工具栏的「导出为浅色」仍是 checkbox。
8. 标题输入框 maxLength 200（UTF-16 单元，防大段粘贴），限长以 sanitizeTitle 的 100 码点为准。
9. ping 失败的 LLMError attempts = 1，所以文案里有「共尝试 1 次」（与 llm 错误卡同一个生成器，不另开口子）。
10. 底部固定区加了与 region 同样的半透明白底（.42）：浮层整体半透明（r2 决定）时，底部提示压在柱子上看不清。

实测数字（aarch64 沙箱，Node 24.22.1，Python 3.12；最后一次改动之后全部重跑）：

| 闸门 | 之前（[60]） | 现在 |
|---|---|---|
| build_gate_data | 通过 | 通过（11 个文件） |
| gen_eval_data --check | 通过 | 通过 |
| gen_ui_types --check | 通过 | 通过（重生成后） |
| pytest | 837 passed | 851 passed（1 warning 是 test_gate s04 的 DtypeWarning，原有），502 s |
| npm run lint / tsc --noEmit | 通过 | 通过 |
| vitest | 790 | 848（22 个文件） |
| npm run build | 1 外链 script，0 内联 | 1 外链 script，0 内联 |
| e2e（--grep-invert 视觉） | 34 passed | 38 passed |
| f4-visual（本地，预期红） | 08=3514 / 11=4953 / 24=3381 / 25=4497 | 08=3514 / 11=91905 / 24=3381 / 25=15695 |

- f4-visual：08（分析中，没有图和标记卡）和 24（失败页）差异像素与改前逐个相同，说明 A / B 组没碰这两屏，差的仍是平台抗锯齿；11 变化最大（标记卡整体换了布局：竖排组头、底部固定区、拨动开关）；25 是图本身（y 轴 0–500 刻度加数值标签、左 12 / 右 16、nameGap 32）。11、25 基线没换，要在 CI 上取 actual 后换（HANDOVER §6）。
- CI 基线（PR #73，run 39916248755）：web job 只有 f4-visual 11、25 两条红（11 差 87747 像素 ratio 0.07，25 差 11198 像素 ratio 0.02），08、24 和其余 40 条通过；pytest 六格、gate-oracle 两格、vitest 848 全绿。看过 actual / expected：11 是标记卡新布局（卡变高后向上翻，竖排组头、拨动开关、底部固定区），25 是 grid 左 12 / 右 16 与 nameGap 32 带来的图区平移，没有意外布局变化。两张基线换成该 run 的 *-actual.png。
- 1024 宽 25 屏：卡左缘到 y 轴线（plot 区左沿，读 canvas 像素）44px（改前 57，设计 44，验收 ≤ 46）；右侧 17px（16 + 卡边框 1）。
- SSR（夹具 bar，字号中 / 大，640 / 880 / 1174 宽）：x 轴刻度文字到轴名分别 ≥ 12 / ≥ 8px；bar 开标签 y 轴刻度 0 / 2 / 4 / 6 / 8 / 10。

判定表（行为为什么变；只是选择器变的单列）：
- pytest：test_chart_slot 的 test_react_chart_error_reaches_model_and_warnings、test_workflow_partial_chart_error_reported、test_react_partial_chart_error_reported、test_react_two_ok_execs_first_error_still_reported，test_fake_llm 的 inject-error（改名见偏离 3）、test_real_chain_partial_chart_error_reported：前缀「图表未生成：」/「另有 1 张图未生成：」和"原文在警告里"改成固定文案、原文不在警告里而在 chart_errors_shown（P1-17）；`_not_made` 过滤词「未生成」→「没画出来」。test_charts `_PER_CHART.grid` 去掉 left / right（已登记进 GEOMETRY，更严）。
- vitest：compact.test「单系列 bar」改前 nameGap 28 → 32（P2-20）；layer1.test 存储三条（parseEdit 不补默认、删键写 {}、坏 JSON 回 {}）和机制测试（加 colorBy / title）——B4 存储改成只存设过的字段；marksGroups.test 卡内项 12 → 14（加按列着色、标题），删「多条理由连成一行」（whyLine 随 .marks-why 删）；EChart.test 饼图 / 散点两条理由从 marks-why 改成读组头（文案不变）；switches.test 两条机制测试见偏离 1。
- e2e：f4-panel 柱图那条存储期望去掉没碰过的 `other: false`（B4）；f4-panel 浮层那条"理由行柱图饼图同高"改成"组头都是 40 高、不可用组的理由在组头一行放得下"（B1）；f3-inject 警告（P1-17）；f3-themes #49（偏离 4）。
- 只是选择器变：EChart.test、f3-switches、f3-export、f4-panel 里开关的 getByRole("checkbox") → "switch"；EChart.test 组头取 `.marks-ghead`、组名取 `.marks-gname`。

新增测试：
- pytest（+14）：tests/test_settings_test.py 11 条（test_ping_message_matches_fake_marker、test_requires_bearer、test_ok_uses_saved_settings、test_no_key_sends_nothing、test_failures_classified[fail-401 / fail-429 / fail-500]、test_timeout_capped、test_concurrent_second_is_409、test_key_never_in_response_even_if_upstream_echoes、test_nothing_persisted）；test_fake_llm 的 test_ping_recognized_and_scenarios_apply、test_ping_is_exact_message_only；test_charts 的 test_schema_exports_display_contract。
- vitest（+58）：headroom.test.ts 19（判据表 8→10 / 97→120 / 412→500 / 11.4→12.5 / 0.3→0.4 / 紧凑 8→10、2.5 不是死候选、浮点、≤0 不写、触发条件 6 条含机制、SSR 刻度 / 轴名间距 ×2 / 左右固定）；title.test.ts 22；marksV2b.test.tsx 13（组头当前值 5 组、竖排、N 个图形元素、拨动开关、完成；按类目着色 3 条；标题 2 条；应用到同类 3 条）；views.test「测试连接」4 条（三态、auth 焦点、server、未保存不可点）；layer1.test 老数据 1 条；marksGroups.test −1。
- e2e（+4）：f4-panel「应用到所有柱状图…」、f4-settings.spec.ts（ok、fail-401）、f4-layout「1024 宽会话：图表卡左缘到 y 轴线 ≤ 46px」。

未做：
- 方案 B5 列的不做项：形状选择、轴组「显示网格」、标签「位置」、复制结果、全屏、卡头 badge。
- 已知：按类目着色时再开「渐变」，渐变写在系列层，会盖掉每根柱子的类目色（方案没规定，未处理）。
- 环境：这次沙箱重置后 Playwright 浏览器缺失，重新 `npx playwright install chromium` + `install-deps chromium` 后跑的；08 / 24 差异像素与 [60] 相同，渲染环境一致。

当前阶段：阶段 5 收尾实现完成，待 S 评审 → 提交 / 推送（CI 上换 11、25 基线）→ S 用真 Key 走 F5 → 删 Streamlit。

## [62] 2026-10-23 · Windows 上 /assets 的 .js 被当成 text/plain，整页白屏 · commit 0c777a1（PR #74）

现象：S 在 Windows 本机走 F5，`python -m app.server --open` 打开后整页白屏。标签标题是 datachat，说明 index.html 已经拿到了；`<script type="module" src="/assets/index-*.js">` 没执行。

原因：S 本机 `python -c "import mimetypes;print(mimetypes.guess_type('a.js'))"` 输出 `('text/plain', None)`。Windows 上的 mimetypes 会读注册表 HKCR\.js 的 Content Type，这个值常被编辑器改掉。/assets 用 StaticFiles 挂载（app/server/app.py），它按 mimetypes 给出 Content-Type；module 脚本的 MIME 不是 JavaScript 时，浏览器拒绝执行。e2e 只在 ubuntu 上跑，所以一直没暴露。

改动：
- app/server/app.py 新增 `ASSET_MIME_TYPES`（.js/.mjs/.css/.svg/.json/.woff2）和 `_pin_asset_mime_types()`，在挂 /assets 之前调用，不信任平台注册表。
- 新增 `tests/test_web.py::test_assets_mime_ignores_platform_registry`：先把 mimetypes 表污染成 .js/.css → text/plain，再建 app，断言 /assets 返回 text/javascript 和 text/css。反向验证：去掉 `_pin_asset_mime_types()` 这一行，该测试红。

实测：`pytest tests/test_web.py -k "mime or static"` 4 passed。

S 本机临时绕过（不依赖本修复）：`reg add "HKCU\Software\Classes\.js" /v "Content Type" /t REG_SZ /d text/javascript /f`。


## [63] 2026-10-25 · F4 迭代 V2c 方案：F5 第一批发现 · commit 5f34e0b（PR #75）

[62] 回填为 0c777a1（PR #74）。

F5 走查记录（进行中）：
- 测试 agent 假模型预走（10-24~25，报告不入库）：①~⑥ 全过；本机 pytest 852、vitest 848、e2e 非视觉 35/35；#74 的 MIME 修复在 Windows 实机验证通过（`/assets/*.js` → text/javascript）。f3-inject 3 条本机红，定性为字体度量导致的测试可移植性问题（V2c §9）。
- S 真 Key 走查：已报第一批 8 条（V2c §1~8），五条路径尚未走完。

方案见 docs/roadmap/phase5-frontend.md「F4 迭代 V2c」：1、2 测试连接（旧结果 bug、失败文案折叠原文），3 返回入口，4 字号（先 px→rem 零变化，再根 13→14），5 结论 Markdown 排版，6 当前会话「⋯」常显，7 预览表去掉内层竖向滚动，8 Key 占位字体，9 f3-inject 前提限 linux。O1、O2 和本机环境问题只记录。

S 10-25 定：§2 上游原文折叠保留；§4 根字号 14。


## [64] 2026-10-25 · F4 迭代 V2c 实现 · commit 925465b（PR #76）

[63] 回填为 5f34e0b（PR #75）。按 phase5-frontend.md「F4 迭代 V2c」§1~9 实现。

- §1 测试连接旧结果：结果带着发起时的 form / newKey / key 引用，渲染时比对，不一致就不显示（派生，不在 effect 里 setState，过 react-hooks/set-state-in-effect）；在飞请求回来时引用已过期，也看不见。auth / no_key 只在结果仍有效时聚焦 Key。
- §2 失败文案：新增 views/llmErrorText.ts，按 llm_kind 给标题、建议，分 turn / settings 两种语境，TurnView 错误卡与测试连接共用；后端原文放默认折叠的「技术详情」。
- §3 返回：Shell 记 anchor（进入设置/数据集前的首页或会话），设置⇄数据集互切不改；anchor 会话被删回首页。Topbar 新增 onBack + IconChevronLeft。
- §4a（3143fd2，本 PR 内单独一个 commit）：styles.css 132 处固定字号改 `calc(N * var(--px))`，`--px: calc(1rem / 13)`。直接写 `N/13rem` 会被 Vite 压成有限小数，四屏出现 514 像素差；换变量表达式后四屏零差异。
- §4b：根字号 13 → 14。四张视觉基线（08/11/24/25）随之更新。
- §5 结论 Markdown：.answer 行高 1.7；h1~h4、ul/ol/li、table 间距与表头字重；首个子元素去上边距。新增 vitest「结论 Markdown：标题、列表、表格都渲染在 .md 下」。
- §6 当前会话「⋯」常显；`@media (hover: none)` 全部常显。
- §7 预览表去掉 `max-height: 60vh` 内层竖向滚动，只保留横向滚动。
- §8 Key 占位 / 只读说明用界面字体（font-family: inherit），实际 Key 输入仍等宽。
- §9 f3-inject：非 Linux 且缺 P4~P7 标签时 test.skip，Linux 仍严格断言。
- HANDOVER：补 web-dist 工件解压位置与管理员解压导致 dist ACL / EPERM 的说明。


## [65] 2026-10-26 · V2d 方案：token 观测与单轮预算 · commit 1144c27（PR #77）

[64] 回填为 925465b（PR #76）。**更正**：[64] 合并前我报的「CI run 40199559877 绿」引错了 run——那是 sidecar 工作流；同一提交 7381969 的 tests 工作流 run 40199559981 是红的，master 合并后 run 40200328630 同样红，红的都是 web job 的 f4-visual 08/11/24/25 四张（每张约 1% 像素，只差在 14px 的 DOM 文字抗锯齿上，ECharts 画布文字和布局零差异）。原因：§4b 根字号改成 14 后，四张基线是在沙箱 aarch64 上重生成的，13px 时 aarch64 与 CI x64 一致，14px 时文字栅格化不一致。本 PR 顺带把四张基线换成本 PR 首跑 CI run 40252555398 的 actual（x64），master 由此恢复绿。教训：报 CI 结果按 head_sha 列全部工作流，不只看一个 run。

来源：测试 agent 对照《AI Agent Book》第 7 章的审计 + 全书 × 竞品综合稿（报告不入库）。S 评审三轮：初版「真模型 usage 全盲、gate tokens 全空」不成立（13 份 gate 报告每题 tokens 都非零，runner.py:99 只在 reported 时写）；ReAct 上界按 recursion_limit 是图步数改为约 12 次模型调用；分节点紧 max_tokens 撤回；前缀重排、状态栏降级。

方案见 docs/roadmap/phase5-frontend.md「V2d」：1 usage 拆分（cache_read / reasoning / estimated，零调用 reported=None，报告导出 6 个字段）；2 单轮预算默认 130,000（ReAct 闸门实测最高 63,817 的约 2 倍），调用前判定并预留收尾量，ReAct 走强制收尾、工作流不进 reviewer，缺 usage 按字数估算，卡片显示 tokens；3 finish_reason=length 作为明确错误，本节不设 max_tokens。其余各项记进 plan.md「外部审计待办」。

## [66] 2026-10-26 · V2d 实现：token 观测与单轮预算 · commit 2b283b6（PR #78）

[65] 回填为 1144c27（PR #77；master tests run 40255033298 绿，这个提交只触发了 tests 工作流）。按 phase5-frontend.md「V2d」§1~3 实现，偏离写在该节「实现与偏离」。

- §1 llm.py：TokenUsage 新增 cache_read_tokens / reasoning_tokens（服务商没给为 None）、estimated_tokens / estimated、budget / budget_hit；reported 初值 None（零调用）。UsageCallbackHandler 在 on_chat_model_start 记输入字符数，LLMClient 用 prompt 字符数，缺 usage 时估算。runner.usage_fields + report.USAGE_KEYS 每题导出 6 个字段，`tokens` 不变。
- §2 预算：`DATACHAT_TOKEN_BUDGET`（默认 130,000，0 关闭）。UsageTracker.over_budget()：已用（真数 + 估算）+ 最近一次输入 ≥ 预算。ReAct：agent 节点调用前 check_budget() 抛 BudgetExceeded，_react_invoke 与 GraphRecursionError 一起接住，走原有强制收尾，warning / 失败文案按原因区分。工作流：_route_after_exec 读 config 里的 tracker，超限不进 reviewer。前端 turnTokens + 卡片头部 token 文字。
- §3：is_truncated（finish_reason=length）。codegen / reviewer 截断 → executor 不执行；summarizer、ReAct 结论、强制收尾截断 → 保留文字 + warning。
- 测试设施：ScriptedChatModel tokens_per_call=None 模拟不回 usage；fake_llm 新增 tokens-<N> 场景、MARK_FINALIZE。
- 判定变更：旧断言一条没改（零调用 reported=None 的路径以前没有测试断言）。新增 tests/test_v2d.py 20 条、src/views/v2d.test.tsx 5 条、e2e/f4-budget.spec.ts 1 条（fake 项目按文件名 f[34]* 匹配）。提示词、chart_fixtures 不变。视觉 11、25 两屏：token 文字让 `.acard-time` 遮罩框变宽（每张 1119 像素，只在遮罩框里），基线换成首跑 CI run 40260578380 的 x64 actual；我本地报的「基线不用重取」是错的——本地 aarch64 这 4 屏本来就红，看不出这个差异。


## [67] 2026-10-26 · F5 通过，删 Streamlit · commit c668ff4（PR #79）

[66] 回填为 2b283b6（PR #78；master tests run 40262438449 绿）。F5 走查记录补在 [55] 末尾：五条路径都过了；10-26 的 4 条发现 S 定为可接受，不处理。

按 phase5「F5 · 通过与收尾」的清单逐条删除：
- [x] `ui/streamlit_app.py`、`ui/chat_app.py`
- [x] `requirements.txt` 的 `streamlit==1.65.0`
- [x] `tests/test_ui_smoke.py`（3 个测试项：test_page_renders × 2 页 + test_chat_app_turn_goes_through_analyze）。pytest 基线从 872 降到 869，这是删除带来的，不是回归。
- [x] `packaging/build_sidecar.py` 的 `--exclude-module streamlit`
- [x] README 里的 Streamlit 界面介绍和两条 `streamlit run`
- [x] HANDOVER 第 20 行；DEVLOG B14 标成「已删」
- 另外改了：app/core/service.py 文件头的入口列表、plan.md 阶段 5 的状态（标成完成）。

pyarrow：它只是 streamlit 的传递依赖（[18]，DEVLOG 第 771 行），所以删掉 streamlit 后，新装的环境里不会再有 pyarrow。pandas 3.0 在没有 pyarrow 时字符串后端改用 python，开发和打包也因此一致了。这样 [18] 留到阶段 6 的「pyarrow 去留」问题就不用再定了，sidecar 体积预计少约 78 MB，以 CI 的 sidecar 工件为准。验证：我用全新 venv 装 requirements-dev.txt，确认没有 streamlit 和 pyarrow，再跑全量 pytest。

## [68] 2026-10-26 · 阶段 6 方案：桌面打包 · commit bf6413f（PR #80）

[67] 回填为 c668ff4（PR #79；master tests run 40283639951 绿）。

新文件 docs/roadmap/phase6-desktop.md。阶段 6 是新阶段，就不再往 phase5（已经 1300 多行）里写了。内容：
- D0：要 S 定的 6 件事——外壳、安装包格式、WebView2、卸载时是否保留数据、发布渠道、仓库许可证（仓库目前没有 LICENSE）。
- D1：壳的进程管理。sidecar 走 bundle.resources，不用 externalBin（onedir 的 `_internal` 会丢）；用 Job Object 防止留下孤儿进程；单实例；导航边界和空 capabilities；代理绕过要实测。CI 自动冒烟覆盖静默安装、`--smoke`、强杀壳后 sidecar 跟着退出、卸载后数据还在。
- D2：首次启动先进设置页；补上 THREAT_MODEL §4 (a) 欠的「来路不明」提示（现在代码里没有这句）。
- D3：自动更新，用 minisign 签名，和 Authenticode 无关。
- D4：许可证审计闸门。
- D5：签名路线表，D1~D4 按未签名先做完。

更正：phase5 F5 末尾和 plan.md 阶段 6 的验收里写着「EV 对 SmartScreen 立刻生效 / SmartScreen 不拦」，这在 2024 年以后已经不成立（微软 2024 年 8 月去掉了 EV OID，OV 和 EV 都要积累信誉）。验收改成「显示已验证的发布者」。Azure Artifact Signing 目前不对中国主体开放。

S 10-26 定：只在本机自用，D0 的建议全部采纳；D3~D5 推迟到对外分发之前再做，本阶段只做 D1 + D2（方案「范围」一节）。网页端（`--open` 浏览器模式）保留，壳的功能不能让它坏掉。

## [69] 2026-10-26 · 阶段 6 D1 壳 + D2 首次启动 · commit cdabfcf（PR #81）

[68] 回填为 bf6413f（PR #80；master tests run 40290000283 绿）。按 phase6-desktop.md §2、§3 实现，偏离写在该文档「D1/D2 实现与偏离」。

- 后端：`POST /shutdown`（Bearer；202；没挂退出钩子时 503）。`__main__` 把 `uvicorn.Server.should_exit` 挂到 `app.state.request_shutdown`，并设 `timeout_graceful_shutdown=2`（SSE 长连接不会自己断）。测试：test_server.py::test_shutdown_requires_token_and_hook、test_sidecar_contract.py::test_shutdown_endpoint_exits_process（真进程：无 token 401 → 带 token 202 → 退出码 0）。
- 壳：`desktop/src-tauri`（Tauri 2）。sidecar.rs：握手、/health 轮询、Job Object（KILL_ON_JOB_CLOSE）、stop（/shutdown → 3 s → 强杀）、`--smoke`、`--smoke-hold`。main.rs：单实例、窗口 1280×800 / 最小 1024×640 + window-state、导航边界（on_navigation + on_new_window，外链交给系统浏览器）、sidecar 中途退出 → 本地错误页、「重新启动」。没有 capabilities，页面拿不到 Tauri API。
- 前端：`desktop.ts` 能力探测（`#shell=desktop`，不看 UA）；失效页在壳里换成「重新启动 DataChat」（P1-16）；上传对话框常驻「来路不明」提示（THREAT_MODEL §4 (a)）；设置页引导文案改成「先填 API Key 并保存，再上传 CSV」。浏览器模式不变（App.test.tsx 两条对照）。
- CI：新工作流 desktop.yml（windows-latest）：打包 → 静默安装 → `--smoke` → 强杀壳查孤儿 → 静默卸载查数据目录。PR #81 head 393e1e0：desktop run 40295387628 绿（安装包 65.5 MB、打包 347 s、--smoke 启动 2027 ms / 退出 505 ms 退出码 0、强杀后无孤儿、卸载后数据保留），tests 40295387542、sidecar 40295387588 绿。
- 本地：Rust 只能 `cargo check --target x86_64-pc-windows-msvc`（沙箱 aarch64、没有 MSVC），真编译和安装冒烟以 CI 为准。

## [70] 2026-10-27 · 阶段 6 收尾：嵌套 Job 实测 + 重估 · commit 7085714（PR #82）

[69] 回填为 cdabfcf（PR #81，S 10-27 同意合并；合并前 head cb9e840 的 tests 40426911618、sidecar 40426911472、desktop 40426911624 都绿）。

- 壳新增 `--smoke-selftest <out.json>`（sidecar.rs::smoke_selftest）：用和正式启动同一个 `job_for`（KILL_ON_JOB_CLOSE）把 `sidecar --selftest` 放进 Job 里跑，stdout 的 JSON 原样落盘，退出码透传。selftest 的 memory 项会让 worker 在 512 MB 上限下申请约 1.6 GB，worker 自己的 Job 这时嵌套在壳的 Job 里面，所以这一项就是 phase6-desktop.md §2 第 3 条「嵌套后内存上限仍然生效」的实测。其余七项（读文件拦截、import 拦截、超时等）一起验证。
- desktop.yml 安装冒烟加 ①b：对安装好的 exe 跑 `--smoke-selftest`，八项全过才绿，`memory_ok` / `memory_seconds` 写进 desktop-report.txt，selftest-in-job.json 一起上传。
- 没覆盖：「壳被强杀时正在运行的 worker 也被带走」。worker 只在分析时存在，CI 上要先起一次真实分析才能测，留给 S 本机验收（分析进行中关掉窗口，任务管理器里不应留下 datachat-sidecar.exe）。
- plan.md：进度表补阶段 6 一行，并按 M18 重估一次（见该节）。
- 本地：`cargo check --target x86_64-pc-windows-msvc` 通过，无 warning。

### S 10-27 本机试装发现的两个问题

1. **点「导出 PNG」没有反应**。exportPng.ts 用的是 data URL 加 `<a download>`，而壳里没有下载处理器，WebView2 遇到这个链接什么也不做。修法是桌面模式改由后端写盘：
   - 新增 `POST /exports/png?filename=`（app/server/exports.py）。要带 Bearer，并且只在 sidecar 以 `--desktop` 启动时开启；浏览器模式下返回 404。壳的 sidecar.rs::start 会传 `--desktop`，sidecar-contract.md 已补上这一条。
   - 只接受 PNG：检查 8 字节文件头，大小上限 64 MB，超限时先按 Content-Length 返回 413。
   - 文件名在后端再清洗一遍，不信任前端：去掉控制字符和 bidi，替换路径分隔符和非法字符，限 60 字，保留名前面加 `_`，只取 basename。重名时自动编号成「名 (1).png」，用 `open(..., "xb")` 独占创建，所以不会覆盖已有文件。
   - 写到 Windows 已知文件夹 FOLDERID_Downloads（用户可能把它挪到别的盘），可以用 `DATACHAT_EXPORT_DIR` 覆盖。
   - 前端改动：Shell 只在 `inDesktopShell()` 时通过 charts/pngSaver.ts 注册 saver，EChart 有 saver 时交给它处理，并显示「已保存到 路径」；浏览器模式保持原来的 `<a download>`。
2. **连不上模型**（WinError 10054）。为了定位做了几组对照：A 浏览器模式能连；B 在 dc 窗口里直接运行安装好的 sidecar（用同一个 --home）能连；C 在普通 cmd 里运行也能连。这说明 exe、设置和证书都没问题。之后 S 再打开桌面端，就正常了。**根因没有实证**，推断是第一次连接时设置还没保存好、或者没有重启。不过桌面端不读 `.env` 这一点确实会让人误判，所以：
   - `GET /settings` 新增 `sources`，标出每一项当前生效的值来自 settings、env 还是 default。设置页显示一行「当前生效：…」，并写明桌面版不读取 .env。后端没有返回 sources 的旧版本不显示这一行。
   - README「安装」第 3 步说明了这一点。

**没做：** 安装目录 `%LOCALAPPDATA%\DataChat`（Tauri currentUser 默认的 `$LOCALAPPDATA\${PRODUCTNAME}`）和数据目录 `%LOCALAPPDATA%\datachat` 在 NTFS 上不区分大小写，其实是同一个目录。目前不出错的原因是：卸载器只删它自己装的文件，最后执行的是非递归的 RMDir；勾选「删除应用数据」时整个目录都会被删，而这本来就是卸载。要把两者分开，得改安装目录（需要改 NSIS 模板或 productName），或者改数据目录（会和浏览器模式分家，需要迁移已有数据），两种都超出收尾的范围，所以推迟到 D3 更新之前，记在 phase6-desktop.md 里。desktop.yml 卸载检查 ③ 的 data_kept 结论仍然成立，因为它验证的正是「卸载不递归删除」。

## [71] 2026-10-27 · 阶段 7 方案 · commit 906d98f（PR #83）

新文件 docs/roadmap/phase7-accuracy.md（P0 + E0~E4 + A1~A6）。要点：
- 先做评测，再做改进。闸门已经快满分（react 14/15 + 9/10，workflow 多表 10/10），而且已经被逐题分析过，不能再作为目标；M20 的目标改为定在新的留出集 H1 上：先测基线，再由 S 定 X。
- H1 约 40 题（单表 18 / 多表 12 / 画图 5 / 陷阱 5），流程照搬闸门（先写题 → 独立脚本算答案 → 冻结 → 再跑模型）。S 出 ≥ 1/3 的盲题，Hark 只看汇总。
- A4 DuckDB、A5 YAML 语义层是有条件做的（看 H1 的失败分布）；A6 反馈沉淀推迟。
- plan.md 阶段 7 的交付物和验收按上面改写。
- 待 S 定：§1 的 5 条（模型 / 网关、每轮预算、出题分工、judge 模型、数据许可）。

## [72] 2026-10-27 · 阶段 6.5 方案：多服务商模型接入 · commit 839d3d1（PR #84）

新文件 docs/roadmap/phase65-models.md。起因：S 10-27 要求模型接入要尽量兼容市面上所有接口，参考 LangBot。
- 调研了 LangBot、LobeChat、Cherry Studio、Cline、Pydantic AI、any-llm、Open WebUI、Aider、PandasAI 九个项目。共同的结构都是三层：协议（不超过 5 种）、服务商预设（是数据，不是代码）、模型怪癖和能力。LangBot 的 44 个预设里有 31 个是 OpenAI 兼容接口；LobeChat 的 88 个服务商里有 69 个走兼容工厂。
- 不用 LiteLLM：沙箱实测 litellm 1.106.4 安装后占 152 MB，还会带上 boto3/botocore（28 MB）和 tokenizers（11 MB）；sidecar 工件现在是 85.7 MB。
- S 10-27 定：每个服务商各存一个 Key，并且可以建多个用户自己命名的连接（同一个服务商可以有多份）；要做「获取模型列表」；真连接只实测 S 那一个连接；迁移后的连接默认名「我的连接」。
- plan.md 在阶段 6 和 7 之间插入 6.5 一行。

## [73] 2026-10-28 · 阶段 6.5 实现：多服务商模型接入 · commit a4d1a2d（PR #85）

按 docs/roadmap/phase65-models.md 实现。
- **协议**：app/core/llm.py 的 build_chat_model 按协议分发，共 4 种：openai_chat、openai_responses（`use_responses_api`）、azure、anthropic（`ChatAnthropic`）。重试、classify_error、UsageTracker 四种协议共用。classify_error 能识别 anthropic SDK 的异常，529 归为 server。新增 message_text，用来读内容块列表，service.py 和 react_agent.py 都改用它。
- **怪癖**：no_stream_options、no_array_content、reasoning_replay 三个用 ChatOpenAI 的子类实现；thinking_param 走 extra_body。每个怪癖各有一条单测。
- **预设**：app/core/providers.json 共 20 家，外加「自定义」。出处和核实情况见新文件 docs/providers-sources.md。除 fake 外都没有实测。
- **连接**：新表 connections；Key 存在钥匙串里，ACCOUNT=conn:<id>，接口一律不返回 Key。接口包括 /providers、/connections* 全套（见 sidecar-contract.md）、两步测试（连接 + 工具调用探测，结果存进 probe），以及 /models（10 秒超时，失败时退回预设）。旧的 /settings* 保留一个版本，作用于当前生效的连接。启动时迁移旧设置一次：api.deepseek.com 归为 DeepSeek，其余归为「自定义」，名字叫「我的连接」。分析结果的 meta 里记 connection_name 和 model。
- **前端**：设置页改成连接卡片 + ConnectionForm + TestResult。D2 引导变成新建第一个连接。生效连接的 probe.tools===false 时，「边想边做」置灰。
- **依赖**：langchain-anthropic==1.7.5、anthropic==1.17.0、docstring-parser==0.18.0，沙箱实测装上后共 14.8 MB（方案估的是约 28 MB）。sidecar 打包后增加多少要等 CI。packaging/build_sidecar.py 用 --add-data 把 providers.json 打进包。

**偏离方案**
1. **Azure 改走 v1 路径**：直接用 ChatOpenAI，地址是 `{资源}/openai/v1`，model 填部署名，不再需要 api-version，表单也去掉了「API 版本」。依据是 learn.microsoft.com/azure/ai-foundry/openai/api-version-lifecycle（2026-05-13 更新）。方案原写 AzureChatOpenAI 加 dated api-version。
2. schema 校验用 pydantic 写，没用 jsonschema。jsonschema 只是 altair 顺带装进来的，不在 requirements-dev 里，CI 上没有。
3. 一个连接都没有时，旧的 PUT /settings 写到环境变量那个虚拟连接上。现有十几个 e2e 靠它选场景。
4. 迁移时不读环境变量里的 DEEPSEEK_API_KEY。环境变量不是存储，每次启动都还在。
5. 第一个连接自动设为生效；删掉生效连接时，最早建的那个接替。
6. 「测试」按钮移到了卡片上，测的是已保存的配置。因此删掉了旧 vitest 里「先保存再测试」和「auth 失败时焦点移到 Key 输入框」两条。
7. meta 只放在卡头的 title 和「查看过程」里，卡头宽度不变，所以 f4-visual 的 08/11/24/25 不受影响。方案里说的「设置页那张视觉基线」其实不存在。
8. Responses 协议 ping 时用 max_tokens=16，这是 OpenAI 的下限。
9. 预设修正：Moonshot 加上 reasoning_replay（官方文档要求多轮时原样回传 reasoning_content）；Groq 把 llama-3.3-70b-versatile（现在只对 Enterprise 开放）换成 openai/gpt-oss-20b；Mistral 改成文档里能查到的 mistral-large-4 和 mistral-small-2603。

**实测**（最后一次改动之后重跑，沙箱 aarch64）

| 闸门 | 结果 | 耗时 |
|---|---|---|
| pytest 全量 | 985 passed | 684 s |
| vitest | 886 passed / 26 files | 287 s |
| lint、tsc、frontend build | 通过 | build 13 s |
| Playwright e2e（`--grep-invert 视觉`） | 41 passed | 251 s |
| git diff --check | 通过 | — |

- e2e 第一次跑出 1 条红，修的是测试本身，产品没问题。f4-connections 里有两处：`getByLabel("模型")` 会同时匹配到「推理模型」开关，改成 exact；Playwright 的 toBeDisabled 对 `<option>` 判成 enabled，但 aria 快照里是 [disabled]，所以改为断言 disabled 属性。
- 沙箱环境：chromium 缺 libatk，运行 `playwright install-deps` 后正常。
- 没实测：方案 §6 第 4 条（闸门回归）和第 5 条（S 那一个真连接）由 S 来跑；sidecar 体积增量要看 CI。

## [待编号] 2026-10-28 · 记忆系统方案（阶段 6.6） · commit <待提交>

新文件 docs/roadmap/memory-system.md 和 docs/roadmap/memory-system-spec.md。前者是分析（12 个洞 D1–D12、竞品对比、取舍），后者是实现规格（M0–M12）。两份原稿来自 S，入库前我对照 a4d1a2d 核了一遍，并做了以下修订：
- **行号重锚**：原稿基于 906d98f。6.5 之后 app.py 的行号下移了约 11–45 行；llm.py 下移 9 行，over_budget 从 172 到 198；db.py 的外键 pragma 从 119 到 139。service.py、react_agent.py、result.py 没有变化。新行号逐处核对过，都指向正确的那一行。
- **开关**：原稿只用环境变量 DATACHAT_MEMORY，但桌面版不读 .env（README.md:63），产品里永远打不开。改为存进 settings 表的 memory_mode，设置页加一个三选一；环境变量只留给测试和评测时覆盖。默认 off；off 时 prompt 与改动前逐字节一致，有测试钉住。
- **m10**：原稿说口径库能「修好 m10」。但 m10 是缺成本字段、必须拒答的题（scripts/gate/questions.py:76-77、verify_gate.py:156），拿来验收口径库是错的。改为：m10 不动；口径题放进 cases_memory.py；另加一条反向回归，口径里用到的字段在表里不存在时，仍然拒答。
- **VACUUM**：原稿放在 POST /shutdown，但壳的退出宽限只有 3 秒（sidecar.rs:17），会被强杀；放到后台线程又会和 WAL 写入抢排他锁。改为：新库设 auto_vacuum=INCREMENTAL，退出时只跑有上限的 incremental_vacuum；旧库在开始监听之前按 freelist 比例转换一次。
- **M3**：沙箱每轮都会重建 df，快照里也不放代码，所以做不到「不再重算 / exec 从 2 次降到 1 次」。目标改为「追问时知道上一轮做了什么」。取代码的工具另记为 M3b，等消融结果再定。重复计算率只报告，不设门槛。
- **流程**：仓库里没有 AGENTS.md，「先开 Issue」作废，按 HANDOVER §3 方案先行。原稿是一张卡一个 PR，改成一批一个 PR。命令统一写成 python（conda dc / venv），不再用 .venv/Scripts。
- **与阶段 7 对齐**：M2 对应 A5，M9 对应 A6。M2 做不做跟随 A5 的条件，M9 跟随 A6 推迟。闸门里人工判对的题不进产品记忆。
- **批次重排**：
  - 批 1：M0、开关、M12、M5、M1、M3，再加上评测要的接口字段。
  - 批 2：评测侧的多轮 runner，以及 history on/off 消融。
  - 批 3：看基线再定。
- **新增 §14：与评测 agent 的分工**：
  - 文件归属：service.py、react_agent.py、planner.py 归记忆独占；case_model.py 和多轮 schema 归评测。
  - result_json 新字段写死为四个：memory_mode、history_tokens、memory_trimmed、rewrite。
  - 指纹时序：从 M1 起，凡是改 prompt 的合并，都要先等指纹 v1 baseline 打好 tag。指纹按渲染后的 prompt 计算，并带上 memory_mode。
  - DEVLOG 条目在合并前写 [待编号]。
- plan.md 在 6.5 和 7 之间插入 6.6 一行。
- 本次只改文档，没跑闸门。eval-system*.md 和 four-axes-mapping.md 由评测 agent 另行提交，不在本 PR 里。

## [待编号] 2026-10-28 · 评测批 0：用例治理 + 统计 + 多轮执行器 · commit <待提交>

按 docs/roadmap/eval-system-spec.md 的 EV-A1 / EV-A2 / EV-C2 三张卡实现，基线 3ce6b77。

**完成（对照卡片）**

| 卡片 | 改动 | 证据 |
|---|---|---|
| EV-C2 | 新 `app/eval/stats.py`：`wilson` / `mcnemar_exact` / `mde_flips` / `bootstrap_mean_ci` / `percentile`，外加 `pass_at_1` / `pass_pow_k` / `flip_rate`。不引 scipy | `tests/test_stats.py` 21 passed。Wilson(23,25)=0.7503/0.9778、McNemar(12,4)=5034/65536=0.0768 都先手算再写死进断言 |
| EV-A1 | `case_model.py` 加 8 个字段；新 `app/eval/validate.py`；`cases.py` 末尾接校验（失败即 raise）；`report.py` 的 `EVALSET_FILES` 手写清单改成 glob；新 `scripts/holdout/README.md` | `tests/test_eval_cases.py` 156 passed（7:46）。7 条新测试逐条对应 5 条硬约束 + 枚举 + 指纹覆盖 |
| EV-A2 | `runner.py` 抽出 `_run_one`，多轮逐轮累积 `history`；行加 `turn_status` / `turn_answers`；多轮 tokens 与耗时按轮求和。闸门 `run_gate.py` 加 `--repeat`，主行恒为第 1 次 | `tests/test_eval_runner.py` 14 passed；`tests/test_gate.py` 79 passed（含 2 条 repeat） |

**指纹的一次性变化**（spec EV-A1 预告过，记下来备查）

- `evalset.sha256`：`8f0e9a4a0f09` → `478204bf6a7f`。原因是 `case_model.py` 多了 8 个字段、`cases.py` 末尾接了校验。**这是预期代价**：从这一版起，旧报告与新报告按 `comparable` 判必然不可比。
- `affects_results_sha256`：`6b325a6d647d`（A 组 41 个文件 / B 组 14 个）。
- `app/eval/stats.py` 与 `app/eval/validate.py` 都归 **A 组**，理由写在 `fingerprint.py` 的注释里：validate 决定哪些用例能进评测（放宽一条等于换题集），stats 产出报告里的区间与稳定性数字（改它就是改读数）。这两个文件让 `test_real_repo_partition_covers_every_file` 先红了一次——那条断言按设计工作。

**顺带修掉的隐患**

1. `EVALSET_FILES` 是手写四项白名单，**加 `cases_memory.py` / `cases_negative.py` 时指纹不会变**，两批会被判可比且报告完全正常。改成 `glob(app/eval/cases*.py)`，并加 `test_every_case_module_is_fingerprinted` 钉住。
2. 指纹分区表同样有"漏一个用例模块"的风险，改成 `_AFFECTS_RESULTS_PREFIXES = ("app/eval/cases",)`，新加用例文件不必回来改表。
3. 多轮只记最后一轮 tokens 会低估成本，改成各轮求和（`_merge_usage`）。

**当前已知问题**

| 编号 | 严重度 | 位置 | 描述 | 计划 |
|---|---|---|---|---|
| E01 | P0 | 环境 | conda `dc` 的激活脚本把 `SSL_CERT_FILE` 设成 `D:/Anaconda3/envs/dc/ssl/cacert.pem`（少一层 `Library`），文件不存在 → `httpx` 建 SSL 上下文直接 `FileNotFoundError`。跑任何真模型前必须 `export SSL_CERT_FILE=D:/Anaconda3/envs/dc/Library/ssl/cacert.pem` | 属于本机环境，不进仓库；CI 上不受影响 |
| E02 | P0 | 环境 | `DEEPSEEK_BASE_URL` 指向 `grg-aikits-test.grgbanking.com`（公司内网），公网 DNS 返回 NXDOMAIN，本机无 VPN 网卡 → 真模型 baseline 当前跑不了 | 等 H 接入内网后跑 `eval-v0` |
| E03 | P1 | `runner.py` | 多轮题还没有：`cases_memory.py` 归记忆系统那条线（M11 会把 8 条补到 15 条），本批只做执行器 | EV-B5 |
| E04 | P1 | `stats.py` | 已实现但报告还没用它算区间：`report.py` 目前仍只出点估计 | EV-C3 |

**指标快照**

- 评测集：130 题不变（本批不增题），`evalset 478204bf6a7f`
- `pytest tests/test_eval_cases.py`：156 passed / 466.53s
- `pytest tests/test_gate.py tests/test_eval_runner.py tests/test_stats.py`：114 passed / 100.44s
- `pytest tests/test_fingerprint.py`：20 passed
- 真模型：**未跑**（E02）

**下一步**

1. 等 H 接入内网 → `run_eval.py --agent react` 130 题 → 打 `eval-v0` tag。
2. EV-C3：`stability` 块 + 缓存检测（`pass^k` 只在 `valid=true` 时写）。
3. EV-B5 的 8 条多轮题由记忆那条线补，本批的 `_run_one` / `turn_status` 已就绪。

## [待编号] 2026-10-28 · 评测基线 eval-v0：真模型首次跑通 · commit 691187c

内网接入后跑通全量 130 题并打 `eval-v0` tag。**这是评测体系第一次在真模型上完整跑完。**

**结果**（`outputs/eval_react_20261028_135836.json`）

| 项 | 值 |
|---|---|
| 正确 | 125/130（96.15%） |
| 执行成功 | 130/130（100%） |
| 初始报错 / 修复率 | 1 次 / 100% |
| 平均耗时 | 7.54 秒/题（全程 992 秒） |
| 平均 token | 6055 /题 |
| 判对层级 | strict 79 / relaxed 34 / scaled 1 / refusal 7 / alt:strict 3 / extras 1 |

分类：聚合 36/36、相关 22/22、过滤 26/27、时序 27/28、拒答 7/9、歧义 7/8。

**`EXIT=1` 不是崩溃。** `run_eval.py:126` 是 `sys.exit(0 if all_correct else 1)`，凡有题没全对就返回 1，给 CI 判红用。别把它当运行失败读。

**5 道错题分三类，性质完全不同**

| 题 | 表面 | 实际 | 归属 |
|---|---|---|---|
| inv_020 | 期望 3/4/5 → 34/21/5；实际 '3月'/'4月'/'5月' → 34/21/5 | 数值全对，判分器不认中文月份 | 尺子 |
| ord_012 | `actual=None`，答案文字 61853.06 = 期望值 | 最后一轮代码只有 print，**没有 `result =`** | 模型未按契约产出 |
| ord_030 | 期望 75.46；模型给 70.85% / 75.77% | 模型**没去重**（gold 的 `_D` 含 `drop_duplicates('order_id')`） | 模型真错 |
| emp_022 | 期望拒答，模型给了"画像式归因" | 答案里明说"没有离职原因字段"，但仍给推测结论 | 契约执行 |
| inv_021 | 期望拒答，模型答 K100 | 明说"没有价格字段"，用累计销量当代理 | 契约执行 |

**inv_020 的硬证据**（同一组数值，只换标签写法）：

```
_month_key('3月')            = None        # 只有 _MONTH_RE = ^\d{4}-\d{2}$ 一种写法被认
_period_part('3月', 3)       = None
results_equal(Series([34,21,5], index=['3月','4月','5月']), Series([34,21,5], index=[3,4,5])) = False
results_equal(Series([34,21,5], index=['2024-03','2024-04','2024-05']), 同上)                  = True
```

同一个答案，写成 `2024-03` 判对，写成 `3月` 判错。修法是在 `_period_part` 的字符串分支补 `^\d{1,2}\s*月(份)?$`，属于补遗漏写法而非放宽标准。**但改 comparator 会改 `code_sha12`，`eval-v0` 立刻失效** —— 所以和记忆系统一起放进 `eval-v1` 那一轮重跑，不单独改。

**另外挖到一个产品 bug（不是评测问题）**

`ord_006` 判对（strict），但 `chart()` 记了一次内部错误：

```
chart('bar', s, x=s.index, y='pay_amount', ...)
→ TypeError: unhashable type: 'Index'
```

根因在 `app/tools/charts.py:161` 的 `_col()`：`if name not in df.columns` 对 `pd.Index` 这类不可哈希对象直接抛 `TypeError`，绕过了 `ChartError` 分支，于是被 `ChartSlot.__call__` 归进 `self.internal`（"我们的 bug"）而不是 `self.errors`（模型用法问题）。两个后果：

1. **模型拿不到可读提示**，不知道自己图画失败了 —— ord_006 的答案里照样写"图表：柱状图展示了七个城市…"，而实际没出图。用户看到的是"说得像有图，其实没图"。
2. **告警噪声**：`chart_smoke` 的规则是"内部错误必须为 0"，这类模型用法错误混进来会淹没真 bug。

修法：`_col()` 先判 `hashable`，不可哈希就抛 `ChartError`（带"x 要传列名，Series 出图请传 df=s 让索引自动成为 x"的提示）。

**顺带确认的两件事**

- `chart_smoke`：出图率 49 题通过、`chart_option` 41/42（唯一失败就是 ord_006）、`has_chart` 3/3。
- `ord_012` 归因为"没写 `result =`"这一点值得单独看：模型有能力答对（答案数字精确等于 gold），但把结论留在了 prose 里。`nudge_no_exec` 只提醒"没执行代码"，不提醒"执行了但没产出 result"。这是 ReAct 契约的一个空档。

**下一步**

1. `inv_020` 的中文月份写法 + `ord_006` 的 `_col` 可哈希判定，一起进 `eval-v1` 那一轮（两者都改 `code_sha12`）。
2. `ord_030` / `emp_022` / `inv_021` 是模型行为，不改判分器；`ord_030` 的"同一张表一题去重一题没去重"对记忆系统是个有意义的观察点。

## [待编号] 2026-10-28 · 修掉基线暴露的两个 bug，重跑并重指 eval-v0 · commit 4d3ab5e

上一节记的两个 bug 在本轮修掉，全量重跑后 `eval-v0` 重指到 `4d3ab5e`。
**结论先说：125/130 → 129/130，但只有 1 题是修复带来的，另外 3 题是同配置下重跑的行为差异。**

**修复 1：判分器不认中文月份（规则 22）**

`_MONTH_RE` 只认 `^\d{4}-\d{2}$`，`_period_part` 走月份号的路径因此认不出 `'3月'`。
inv_020 的数值 34/21/5 全对，只因索引写成 `'3月'` 被判 False。改动：

```
_CN_MONTH_RE = ^(?:(\d{4})\s*年\s*)?(1[0-2]|0?[1-9])\s*月(?:份)?$
```

- `_period_part` 认裸月份 `3月` / `03月` / `3月份`
- `_month_key` 认 `2024年3月`（有年份才算得出 `YYYY-MM`，裸月份算不出，不硬凑）
- 月份号限定 1–12，`13月` 不认

补的是"同一件事的另一种写法"，不是放宽：数值写错仍判错、月份错位仍判错，测试逐条钉住。
**注意** `results_equal('3月', 3)` 在改动前就是 True（规则 20 的文本取数），缺陷只在
Series 索引这条路（`_month_numbers`）——这一点写进测试注释，免得后来人读错归因。

**修复 2：chart 的 x 传不可哈希对象被记成 internal**

`_col()` 的 `name not in df.columns` 对 `pd.Index` / `ndarray` 直接抛 `TypeError`，绕过
`ChartError`，被 `ChartSlot` 归进 `internal`（"我们的 bug"）。改成先判 `Hashable`，
不可哈希抛 `ChartError` 并给出可照做的提示。重跑后 `chart_internal_errors` 为 **0**
（上一版有 1 条 `unhashable type: 'Index'`）。

**重跑结果**

| 项 | 旧（691187c） | 新（4d3ab5e） |
|---|---|---|
| 正确 | 125/130（96.15%） | **129/130（99.23%）** |
| 执行成功 | 130/130 | 130/130 |
| 平均耗时 | 7.54 s/题 | 6.59 s/题 |
| 平均 token | 6055 | 5629 |
| 判对层级 | strict 79 / relaxed 34 / scaled 1 / refusal 7 / alt 3 / extras 1 | strict 81 / relaxed 33 / scaled 2 / refusal 8 / alt 3 / extras 2 |
| chart_option | 41/42（ord_006，内部错误） | 43/44（ts_010，模型漏传 kind） |

**只有 inv_020 归因于修复**。其余三题（ord_012 补上了 `result =`、ord_030 这次做了去重、
inv_021 这次按契约拒答）都是同配置重跑的差异：temperature=0 也不保证网关侧逐字可复现。

**这是本轮最重要的观察**：同一份 prompt、同一组题，两次跑出来 **3/130 = 2.3% 的判定翻转**
（另有 3 题 match 层级漂移：ts_013 relaxed→strict、emp_013 relaxed→strict、emp_006 strict→extras）。
含义有两条：

1. **不能把两次单跑的差当成提升**。129−125=4 里只有 1 是真变化，剩下 3 是噪声。要报"涨了
   多少"必须 `--repeat`，用 `flip_rate`/`pass^k` 给出区间，而不是拿两个点估计相减。
2. `stats.py` 里的 `flip_rate` 和 EV-C3 的 `stability` 块不是锦上添花，是**读数的前提**。

**顺带作废一条设计：渲染哈希不能当"等价可比"的豁免凭据**

改动后 `rendered_set_sha12` 仍是 `6b23655c28a6`（逐题 system prompt 一个字节没变），
`code_sha12` 从 `6b325a6d647d` 变成 `af3d486c2e1b`。按原来的 `comparable()`，这两批会被判
`basis=rendered-equal` 的"等价可比"，那 +1 就被读成"代码变了但没影响"。

根因是渲染串只覆盖 system prompt：模型在循环里看到的工具回传、评分规则（comparator）、
循环控制（react_agent 的重试 / nudge）都不在里面。所以门禁项一个都不豁免，渲染串降级为
诊断与稳定性证据。实测端到端：

```
与基准: ✗ 不可比   差异项: code_sha12
comparable = {"comparable": false, "basis": "gate", "diffs": ["code_sha12"],
              "rendered_equal": true,
              "note": "逐题渲染串相同但代码不同，仍判不可比：渲染串只覆盖 system prompt，…"}
```

**仍然错的一题**：emp_022（员工离职原因）。模型先明说"数据里没有离职原因字段"，然后照样
给了画像式归因。这是拒答契约的执行问题，不是判分器问题。

**ts_010 的图表失败也是模型问题**：`chart(res, x=None, y='units')` 漏了第一个参数 `kind`，
被 `_CHART_SIG.bind` 拦下记成 `ChartError`（分类正确，不再是 internal）。同一段代码后面用
matplotlib 出了图，所以出图率仍通过，只有 `chart_option` 这一条不过。

**下一步**

1. EV-C3：`stability` 块 + `--repeat` 的 flip_rate，把上面这个 2.3% 量化成区间。
2. `emp_022` 的拒答契约（"说了没有这个字段，就不能接着推测"）需要单独看是否要加提示。
