<!-- 草稿 I-01：创建到 GitHub 后把 I-01 替换为真实 #编号，并同步 INDEX.md -->
# I-01 [Wave-1][Serial-Gate] nodes/graph：#127 摘除 S3-3 REPLAN 与 S3-2 产品闸（后端），保留 S3-1 与 code_scope 搬家

**标签**：`wave:1-step3-closeout` `exec:serial` `layer:nodes` `priority:P0` `regress:intranet`

## 依赖与并行编排

- **前置依赖**：无
- **可并行兄弟 Issue**：
  - I-02：修改面完全隔离：I-01 只动 app/ 与 tests/ 下列出的 Python 文件，I-02 只动 ui/web/src，I-04 只动 docs/eval/BACKLOG.md、docs/roadmap/phase75-step3.md 与 docs/eval/archives/step3-mul_005-replan/；受沙箱并行度上限 2 约束，分两批开（I-01+I-02，然后 I-04；独立节点 I-05 也计入这 2 个名额）
  - I-04：修改面完全隔离：I-01 只动 app/ 与 tests/ 下列出的 Python 文件，I-02 只动 ui/web/src，I-04 只动 docs/eval/BACKLOG.md、docs/roadmap/phase75-step3.md 与 docs/eval/archives/step3-mul_005-replan/；受沙箱并行度上限 2 约束，分两批开（I-01+I-02，然后 I-04；独立节点 I-05 也计入这 2 个名额）
  - I-07：I-07 是评测侧分支（docs/eval/CANARY.md、docs/eval/canary/baseline.json），与我方 Wave-1 各节点文件不交；DEVLOG 是追加型共享台账，按「后合者接号」处理，不计入独占边界
- **后续解锁**：
  - I-03（eval/regress：#127 摘除后重跑本地闸门 + 内网回归一批 new（nightly_gate 判读 + canary），通过后 squash 合并）：I-03 回归与合并的对象就是 I-01 摘除后的 #127 head；I-01 不完成就没有可回归的 head（A 组链序 1→2）
- **独占修改边界**：
  - `app/graph.py`
  - `app/state.py`
  - `app/nodes/planner.py`
  - `app/nodes/reviewer.py`
  - `app/nodes/summarizer.py`
  - `app/core/service.py`
  - `app/core/events.py`
  - `app/core/result.py`
  - `app/tools/sanity.py`
  - `app/tools/code_scope.py`
  - `app/assess/snapshot.py`
  - `app/assess/replay.py`
  - `app/assess/contracts.py`
  - `tests/fake_llm.py`
  - `tests/test_fake_llm.py`
  - `tests/test_step3_repair.py`
  - `tests/test_core_analyze.py`
  - `tests/test_workflow_mocked.py`
  - `tests/test_assess_snapshot.py`
  - `tests/test_assess_contracts.py`
  - `tests/test_memory_p8.py`
- **内网串行链**：内网串行链第 1 环（I-01 → I-03 → I-08 → I-09 → I-13）

## 1. 标题

[Wave-1][Serial-Gate] nodes/graph：#127 摘除 S3-3 REPLAN 与 S3-2 产品闸（后端），保留 S3-1 与 code_scope 搬家

## 2. 背景

- PR #127（feat/step3，head 19171d8）实现了第 3 步的 S3-1/S3-2/S3-3，内网回归 GREEN 196/202。S 已同意摘除 S3-3 REPLAN，以及 S3-2 的产品闸：`scope_gate` 节点、`code_before_fix`、字面量豁免、前端两版计划、`recursion_limit` 改动；保留 S3-1 能力注入与 code_scope 搬家（`app/tools/code_scope.py`、`app/assess/code_refs.py` re-export、contracts 改调用、golden 测试、`.gitattributes`）。出处：任务书「当前事实」第 2 条。
- 被摘部分在 #127 中的落点（PR #127 描述「改了什么」）：`app/graph.py:58 scope_gate` 与 `_route_after_exec/_route_after_gate/_can_replan`；`app/nodes/planner.py:224 replan` 与 `_prompt` 抽取；`app/nodes/summarizer.py` 的 `REPLAN_FAILED_PREFIX`；`app/state.py:44-47` 四个字段；`app/nodes/reviewer.py:65 code_before_fix`；`app/tools/code_scope.py:415 _literal_swap`、`:436 compare_scope(empty_before)`；`app/tools/sanity.py:39 is_empty_issue`；`app/core/service.py` 的 `recursion_limit 3·max+20`、`_workflow_step` 的 replan/scope_gate 分支、replan 事件；`app/core/events.py plan(**extra)`；`app/assess/snapshot.py LLM_NODES`、`app/assess/replay.py _node_fn`、`contracts.CONTRACTS["replan"]`；`tests/fake_llm.py` 三个 replan 场景。
- 方案依据：phase75-step3.md §3（S3-2）、§4（S3-3）、§7 第 1 条（「如果一题都没救回，就把 S3-3 摘出去」，S 这次改为无条件摘除 S3-3 并连同 S3-2 产品闸一起摘）。
- 出处汇总：S 11-24 摘除决定（任务书「当前事实」）；PR #127 描述；phase75-step3.md §1–§4、§7 第 1 条

## 3. 范围

**本次只解决**
- 在 feat/step3 上把 #127 的 S3-3 全部与 S3-2 产品闸部分还原为 master 9c40a97 的行为；
- 保留：S3-1（`app/tools/sandbox_caps.py` 的 `prompt_imports`/`prompt_lines`、`app/nodes/codegen.py` 与 `app/nodes/reviewer.py` 的 `{sandbox_lines}`/`{result_var}`、`app/tools/dataset.py is_multi_access`）；code_scope 搬家（`app/tools/code_scope.py` 中与 golden 对应的抽取与 `compare_scope` 判定、`app/assess/code_refs.py` re-export、`app/assess/contracts.py` 改调用、`tests/test_code_scope_golden.py`、`tests/fixtures/code_scope/*`、`.gitattributes`）；
- `tests/test_step3_repair.py` 只留 S3-1 与 compare_scope（不含字面量豁免）的用例；新增一条摘除哨兵测试。

**明确不做（Non-Goals）**
- 不动前端（归 I-02）；不写 BACKLOG、不改方案文件（归 I-04）；不写 DEVLOG、不跑内网、不 push（归 I-03）；
- 不改 golden（`tests/fixtures/code_scope/golden.json`）与 `.gitattributes`；不改 react 链路；不做 S3-4。

## 4. 输入

- worktree /workspace/work/dc_s3（feat/step3，head 19171d8）
- master 9c40a97 作为还原基准
- PR #127 描述（被摘/保留清单与测试清单）

## 5. 输出

- feat/step3 上的摘除 commit（本地，不 push）
- 与 master 相比 `app/` 下只剩 S3-1 + 搬家改动的 diff
- 本地闸门读数（相关文件）

## 6. 环境 / 前置条件

- aarch64 沙箱，Python venv 按 HANDOVER §6；跑 localhost 测试前按 HANDOVER §6 处理代理变量
- 并行度上限 2：本节点与 I-02 同批

## 7. 依赖

无前置。合入后（经 I-03）解锁第 4 步评测降级与 v8 基线。

## 8. 实施步骤

- **节点 1**：还原 S3-3：graph 路由与 replan 节点、planner `_prompt` 抽取、summarizer 前缀、state 的 replanned/replan_reason、service 的 replan 事件与步骤、events `plan(**extra)`、result 注释、snapshot `LLM_NODES`、replay `_node_fn`、contracts `CONTRACTS["replan"]`、fake_llm replan 场景
  - 怎么验证：`git diff origin/master -- app/graph.py app/state.py app/nodes/planner.py app/nodes/summarizer.py app/core/ app/assess/snapshot.py app/assess/replay.py` 为空；`grep -rn 'replan' app/ tests/fake_llm.py` 无产品命中
  - 通过标准：上述文件与 master 9c40a97 逐字节一致
- **节点 2**：还原 S3-2 产品闸：删 `scope_gate` 节点与 `_route_after_gate`、reviewer 的 `code_before_fix`、state 的 code_before_fix/scope_rejected、service `recursion_limit` 回到 `2 * max_attempts + 10`；删 `code_scope._literal_swap` 与 `compare_scope` 的 `empty_before` 参数、`sanity.is_empty_issue`（EMPTY_* 常量一并还原）
  - 怎么验证：`git diff origin/master -- app/tools/sanity.py app/core/service.py` 为空；`grep -n 'empty_before\|_literal_swap\|code_before_fix\|scope_gate' -r app/` 无命中
  - 通过标准：`git diff --stat origin/master -- app/` 只列出 7 个文件：app/tools/{sandbox_caps,code_scope,dataset}.py、app/nodes/{codegen,reviewer}.py、app/assess/{code_refs,contracts}.py
- **节点 3**：测试面：还原 #127 改过期望的 6 条（test_core_analyze ×2、test_workflow_mocked ×2、test_assess_snapshot ×1、test_assess_contracts::test_check_dispatch_covers_every_node）；删 test_fake_llm 的 replan 新增 15 条与 test_step3_repair 中 scope_gate/replan/字面量豁免用例；新增摘除哨兵
  - 怎么验证：逐条列出保留/删除/还原的测试名，贴进交接报告
  - 通过标准：保留的 S3-1 与 compare_scope 用例全绿；哨兵测试「回退红」为硬性要求：把 scope_gate 加回 graph 时必须红，撤回后绿，两次输出存证
- **节点 4**：指纹与哈希：重算 A 组 `code_sha12`；核对 `tests/test_memory_p8.py` workflow 两个哈希
  - 怎么验证：`python -c 'from app.eval.fingerprint import code_fingerprint; print(code_fingerprint()["affects_results_sha256"][:12])'`；跑 test_memory_p8
  - 通过标准：新 code_sha12 记录在报告中（预期 ≠ 8117bbb25d0a 且 ≠ 5436c54d3c6c，A 组文件数 69）；P8：workflow 仍为 #127 的 S3-1 值 `ad567ed3492f6002`、workflow_history `a52a7aa02434e505`（若不同须给出归因，不许直接改期望），react 三个哈希不变

## 9. 测试用例

- 保留：tests/test_code_scope_golden.py 全部 5 条（`test_new_path_matches_golden_byte_for_byte`、`test_contracts_wrappers_match_golden`、`test_assess_code_refs_is_reexport_only`、`test_golden_covers_required_shapes`、`test_tools_code_scope_does_not_import_assess`）
- 保留（test_step3_repair.py）：`test_prompt_imports_is_subset_without_private_and_runtime_only`、`test_prompt_lines_names_all_come_from_caps[单/多表]`、`test_prompt_lines_pinned_text`、`test_codegen_and_reviewer_use_rendered_lines_not_handwritten[单/多表]`、`test_rendered_codegen_prompt_is_stable`、`test_compare_scope_rejects_column_filter_denominator_changes`、`test_compare_scope_parse_and_not_code`、`test_assess_reviewer_scope_keeps_step1_semantics_without_literal_exemption`；`test_compare_scope_allows_typo_fix_and_literal_swap_on_empty` 拆掉字面量那半，只留拼错列名放行
- 删除：`test_literal_exemption_is_narrow`、`test_scope_gate_*`（3）、`test_reviewer_records_code_before_fix`、`test_route_after_exec_replan`、`test_no_replan_when_over_budget`、`test_route_after_gate`、`test_replan_prompt_appends_last_attempt_and_forbids_clarify`、`test_replan_reason_priority`、图测试 5 条、`test_snapshot_replan_node_checked_by_planner_contracts_and_replayable`；test_fake_llm 的 `test_real_chain_replan_*` 等 15 条
- 新增 `tests/test_step3_repair.py::test_step3_strip_no_replan_or_scope_gate`：断言编译后的 workflow 图节点集合 == master 的五节点；`AgentState` 不含 code_before_fix/scope_rejected/replanned/replan_reason；`snapshot.LLM_NODES == (planner, codegen, reviewer, summarizer)`；service 的 recursion_limit 表达式为 `2 * max_attempts + 10`
- 评测侧必跑三件：tests/test_assess_contracts.py、tests/test_b2_batch_pipeline.py、tests/test_nightly_gate.py（phase75-step3 §3 验收末条）

## 10. 验收标准

- [ ] `git diff --stat origin/master -- app/` 恰为 7 个文件（见节点 2）；graph/state/planner/summarizer/service/events/result/sanity/snapshot/replay 与 master 逐字节一致
- [ ] golden sha256 仍为 `2670e234d6da…`（文件未改）；`test_code_scope_golden.py` 5 passed
- [ ] 评测侧三件 64 passed（与 #127 报告同数，`test_check_dispatch_covers_every_node` 期望回到 master 值）
- [ ] 相关 pytest 文件全绿；新 code_sha12、全量 sha 记入交接报告
- [ ] 【硬性】哨兵测试 `test_step3_strip_no_replan_or_scope_gate` 必须做过「回退红」：把 scope_gate 节点（或 replan 节点）临时加回 graph 后该测试红，撤回后绿；红、绿两次的 pytest 输出贴进交接报告。没有这两次输出，I-01 不算完成，I-03 不得开始
- [ ] 语义一致性审查表（计划项→实际→偏离→证据）无未解释偏离

## 11. 交付物

- feat/step3 本地 commit（摘除后端）
- 交接报告：保留/删除/还原测试清单、code_sha12、P8 哈希、diff --stat
- 审查对比表（贴本 issue 评论）
- 节点语义一致性审查表（只读审查 subagent 输出，贴本 issue 评论；格式见 master-plan §6）
