<!-- 草稿 I-02：创建到 GitHub 后把 I-02 替换为真实 #编号，并同步 INDEX.md -->
# I-02 [Wave-1][Parallel-A] web：#127 摘除「重新规划」两版计划显示

**标签**：`wave:1-step3-closeout` `exec:parallel` `layer:web` `priority:P0`

## 依赖与并行编排

- **前置依赖**：无
- **可并行兄弟 Issue**：
  - I-01：修改面完全隔离：I-01 只动 app/ 与 tests/ 下列出的 Python 文件，I-02 只动 ui/web/src，I-04 只动 docs/eval/BACKLOG.md、docs/roadmap/phase75-step3.md 与 docs/eval/archives/step3-mul_005-replan/；受沙箱并行度上限 2 约束，分两批开（I-01+I-02，然后 I-04；独立节点 I-05 也计入这 2 个名额）
  - I-04：修改面完全隔离：I-01 只动 app/ 与 tests/ 下列出的 Python 文件，I-02 只动 ui/web/src，I-04 只动 docs/eval/BACKLOG.md、docs/roadmap/phase75-step3.md 与 docs/eval/archives/step3-mul_005-replan/；受沙箱并行度上限 2 约束，分两批开（I-01+I-02，然后 I-04；独立节点 I-05 也计入这 2 个名额）
  - I-07：I-07 是评测侧分支（docs/eval/CANARY.md、docs/eval/canary/baseline.json），与我方 Wave-1 各节点文件不交；DEVLOG 是追加型共享台账，按「后合者接号」处理，不计入独占边界
- **后续解锁**：
  - I-03（eval/regress：#127 摘除后重跑本地闸门 + 内网回归一批 new（nightly_gate 判读 + canary），通过后 squash 合并）：#127 的最终 head 需包含前端摘除；I-02 没落到分支上，本地闸门（vitest/e2e）和 CI 测的就不是最终内容
- **独占修改边界**：
  - `ui/web/src/turn.ts`
  - `ui/web/src/turn.test.ts`
  - `ui/web/src/views/TurnView.tsx`
  - `ui/web/src/views/v2a.test.tsx`

## 1. 标题

[Wave-1][Parallel-A] web：#127 摘除「重新规划」两版计划显示

## 2. 背景

- S 同意摘除 S3-2 产品闸，其中包括「前端两版计划」（任务书「当前事实」第 2 条）。#127 在 `ui/web/src/turn.ts` 新增 `isReplan / planLabel / plans`、`Ev` 的 plan data 加可选 `source`，`TurnView.tsx` 计划块标题按 `planLabel` 并给第二版加 `replan` class；vitest `turn.test.ts` +3、`v2a.test.tsx` +1（PR #127 描述）。
- 后端摘除（I-01）之后不再产生 `source="replan"` 的 plan 事件，这段前端代码成为死代码；方案出处 phase75-step3.md §4「事件与前端」。
- 出处汇总：S 11-24 摘除决定（前端两版计划）；PR #127 描述「前端」与 vitest 段

## 3. 范围

**本次只解决**
- 把上述 4 个前端文件还原为 master 9c40a97 内容

**明确不做（Non-Goals）**
- 不动后端（I-01）；不动 styles.css（#127 本就没加样式）；不改视觉基线

## 4. 输入

- feat/step3 head 19171d8
- master 9c40a97

## 5. 输出

- feat/step3 上的前端摘除 commit（本地）

## 6. 环境 / 前置条件

- node24、`npm ci`；vitest 用 `--pool=threads --maxWorkers=2`（DEVLOG [204] 闸门记录）；本机缺 libatk，e2e 交 CI

## 7. 依赖

无前置。与 I-01 同批并行（并行度 2）。

## 8. 实施步骤

- **节点 1**：还原 4 个文件
  - 怎么验证：`git diff origin/master -- ui/web/` 为空；`grep -rn 'replan\|planLabel\|isReplan' ui/web/src` 无命中
  - 通过标准：ui/web 与 master 逐字节一致
- **节点 2**：前端闸门
  - 怎么验证：eslint `--max-warnings 0`、`tsc --noEmit`、vitest 全量、`npm run build`、`playwright test --list`
  - 通过标准：vitest 32 个文件 984 passed（= master 9c40a97 读数，PR #127 闸门表）；其余全过；--list 53 条

## 9. 测试用例

- 无新增：被删的是 `turn.test.ts` 中 #127 新增的 3 条（plans 两版与标题、步骤条计数 2、无 replan 一版）和 `v2a.test.tsx` 的 1 条（展开过程两块计划）；vitest 总数回到 984

## 10. 验收标准

- [ ] `git diff --stat origin/master -- ui/web/` 为空
- [ ] vitest 984 passed、eslint 0/0、tsc 0、build 通过
- [ ] 审查对比表无未解释偏离

## 11. 交付物

- feat/step3 本地 commit（前端摘除）
- 前端闸门读数表
- 审查对比表（贴 issue 评论）
- 节点语义一致性审查表（只读审查 subagent 输出，贴本 issue 评论；格式见 master-plan §6）
