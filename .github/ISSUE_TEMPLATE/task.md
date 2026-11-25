---
name: 任务（issue 驱动开发）
about: master-plan 里的一个节点：一个 issue 只覆盖一个模块或职责
title: "[Wave-N][Serial-Gate|Parallel-A|Independent|Decision|External] 模块：一句话"
labels: ""
assignees: ""
---

<!--
标题四选一（再加一种「独立」，见 docs/roadmap/master-plan.md §3）：
  [Wave-N][Serial-Gate] 模块：一句话
  [Wave-N][Parallel-A/B/C…] 模块：一句话
  [Wave-N][Independent] 模块：一句话
  [Wave-N][Decision] 一句话
  [Wave-N][External] 一句话
标签（必选四个，A 组再加一个）：
  wave:N-xxx
  exec:serial | parallel | independent | decision | external
  layer:core | tools | nodes | server | web | desktop | eval | docs
  priority:P0 | P1 | P2
  regress:intranet   ← 改动命中 app/eval/fingerprint.py:38 _AFFECTS_RESULTS（A 组）时必加
-->

## 依赖与并行编排

- **前置依赖**：#编号（为什么依赖：它合入后才能做什么）
- **可并行兄弟 Issue**：#编号（为什么能并行：例如修改目录完全隔离）
- **后续解锁**：#编号（本 issue 合入后对方才能做什么；必须与对方「前置依赖」互相对应）
- **独占修改边界**：
  - `具体文件或目录`（兄弟 issue 之间不得重叠；docs/DEVLOG.md 是追加型共享台账，不计入）
- **内网串行链**：第 k 环（前：#编号；后：#编号）——只有触 A 组的 issue 填

## 1. 标题

## 2. 背景

- 现状与问题（带出处：文件名 + 章节或行号，或 PR / issue 号）
- 出处汇总：

## 3. 范围

**本次只解决**
-

**明确不做（Non-Goals）**
-

## 4. 输入

-

## 5. 输出

-

## 6. 环境 / 前置条件

-

## 7. 依赖

（文字说明，与编排块一致）

## 8. 实施步骤

- **节点 1**：做什么
  - 怎么验证：
  - 通过标准：
- **节点 2**：…

## 9. 测试用例

- 已有测试名 / 新测试名：断言什么（新测试做一次「回退红」）

## 10. 验收标准

- [ ] 可执行判据：闸门数字（pytest / vitest / e2e）、指纹（A 组 code_sha12 前后值）、golden 逐字节、回归判据（nightly_gate 配对净退步 <6）
- [ ] 独占修改边界外 `git diff --stat` 为空
- [ ] 节点语义一致性审查表无未说明偏离

## 11. 交付物

- PR / commit
- DEVLOG 条目（`[待编号]`，合并时定号）
- 节点语义一致性审查表（贴本 issue 评论）
