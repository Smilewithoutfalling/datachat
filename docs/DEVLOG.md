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

## [1] 2026-10-09 · 阶段 0 基线对齐 · commit <待提交，基于 4e67c92>
注：2f67936 仍未推送，本条暂不含它；推送后 rebase 并核对 B03/B08。

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
