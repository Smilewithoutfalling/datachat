<!-- 草稿 I-07：创建到 GitHub 后把 I-07 替换为真实 #编号，并同步 INDEX.md -->
# I-07 [Wave-1][External] 评测侧 #123：rebase 让号到 [211]/[212]，先于 #127 合并

**标签**：`wave:1-step3-closeout` `exec:external` `layer:eval` `priority:P1`

## 依赖与并行编排

- **前置依赖**：无
- **可并行兄弟 Issue**：
  - I-01：I-07 是评测侧分支（docs/eval/CANARY.md、docs/eval/canary/baseline.json），与我方 Wave-1 各节点文件不交；DEVLOG 是追加型共享台账，按「后合者接号」处理，不计入独占边界
  - I-02：I-07 是评测侧分支（docs/eval/CANARY.md、docs/eval/canary/baseline.json），与我方 Wave-1 各节点文件不交；DEVLOG 是追加型共享台账，按「后合者接号」处理，不计入独占边界
  - I-04：I-07 是评测侧分支（docs/eval/CANARY.md、docs/eval/canary/baseline.json），与我方 Wave-1 各节点文件不交；DEVLOG 是追加型共享台账，按「后合者接号」处理，不计入独占边界
- **后续解锁**：
  - I-03（eval/regress：#127 摘除后重跑本地闸门 + 内网回归一批 new（nightly_gate 判读 + canary），通过后 squash 合并）：S 11-25 定：计划书 PR 占 DEVLOG [210]；#123 在计划书 PR 之后、#127 之前合并。I-07 合入后 #123 占 [211]/[212]，I-03 合并时 #127 接 [213]，不再撞号
- **独占修改边界**：
  - （评测侧分支 feat/eval-n119-usage）docs/eval/CANARY.md
  - `docs/eval/canary/baseline.json`
  - `docs/DEVLOG.md（追加型共享台账）`

## 1. 标题

[Wave-1][External] 评测侧 #123：rebase 让号到 [211]/[212]，先于 #127 合并

## 2. 背景

- #123 是 #119 的归因落档（docs-only，code/entry/judge/canary 四层指纹不变），head 6ba9de0，mergeable_state=dirty：其 DEVLOG 条目用 [209]/[210]，而 master 9c40a97 已占 [209]（第 3 步方案）。
- phase75b §3：DEVLOG 后合者 rebase 接号。S 11-25 定：计划书 PR 占 [210]（并回填 [209]=9c40a97）；#123 要等计划书 PR 合并后才执行，让号到 [211]/[212]，并先于 #127 合并；合入后 #127（I-03）接 [213]，三方不会再撞号。
- 执行方：评测侧（本 issue 仍是 External，我方不改评测侧分支）。
- 出处汇总：PR #123 评论（11-24 13:38 改用 [209]/[210]）；notes/progress-history.md「11-24 #126 合并」；DEVLOG:11400；S 11-25 裁定（计划书 PR 占 [210]，#123 改 [211]/[212]）

## 3. 范围

**本次只解决**
- 我方只提需求：计划书 PR 合并后，评测侧 rebase 到 master，DEVLOG 两条改为 [211]/[212]，回填 [210]（计划书 PR）的 commit 字段（HANDOVER §4 末条：下一次提交回填上一条），同步 CANARY.md 内的 DEVLOG 交叉引用，并在 I-03 合并之前合入

**明确不做（Non-Goals）**
- 我方不改评测侧分支

## 4. 输入

- 计划书 PR 合并后的 master（DEVLOG 末条 [210]），且必须早于 #127 合入

## 5. 输出

- #123 合并，DEVLOG 占 [211]/[212]

## 6. 环境 / 前置条件

- 计划书 PR（DEVLOG [210]）已合并入 master
- S 同意合并；由评测侧执行

## 7. 依赖

无 issue 前置；#123 要等计划书 PR（DEVLOG [210]）合并后才执行。先于 I-03 合并（解锁 I-03：#127 接 [213]）。

## 8. 实施步骤

- **节点 1**：计划书 PR 合并后，评测侧 rebase 并重编号为 [211]/[212]
  - 怎么验证：`git show origin/master:docs/DEVLOG.md` 末条为 [210]；分支上两条为 [211]/[212]；[210] 的 commit 字段已回填；CANARY.md 引用同步
  - 通过标准：无撞号
- **节点 2**：S 同意后合并（早于 #127）
  - 怎么验证：合并后 `git show origin/master:docs/DEVLOG.md` 末条为 [212]
  - 通过标准：master 含 #123，且 #127 尚未合入

## 9. 测试用例

- 评测侧自定

## 10. 验收标准

- [ ] #123 在计划书 PR 之后、#127 之前合入；DEVLOG [211]/[212] 归 #123，编号连续、无重复

## 11. 交付物

- #123 合并 SHA（I-03 回填用）
