<!-- 草稿 I-08：创建到 GitHub 后把 I-08 替换为真实 #编号，并同步 INDEX.md -->
# I-08 [Wave-2][External] 评测侧第 4 步：回归范围表落地（含子集入口）、指纹降为报告元数据、LEDGER 机读

**标签**：`wave:2-eval-downgrade` `exec:external` `layer:eval` `priority:P1` `regress:intranet`

## 依赖与并行编排

- **前置依赖**：
  - I-03（eval/regress：#127 摘除后重跑本地闸门 + 内网回归一批 new（nightly_gate 判读 + canary），通过后 squash 合并）：第 4 步评测降级依赖第 1–3 步完成（phase75-assess:42）；且子集入口会改 app/eval/runner.py（A 组），按链序须排在 #127 的内网回归之后
- **可并行兄弟 Issue**：
  - I-10：均为评测侧外部节点；#119 收尾只动 canary 脚本与 CANARY.md，第 4 步动 runner/fingerprint/LEDGER，修改面不交（由评测侧确认）
- **后续解锁**：
  - I-09（评测侧 v8 基线：内网空闲时连跑三次 202 题，取中位数重立）：顺序已定：第 4 步评测降级之后再重立 v8；第 4 步若改了 A 组，code_sha12 会变，先立基线会立即失效
- **独占修改边界**：
  - （评测侧）app/eval/runner.py（子集入口，A 组）
  - `app/eval/fingerprint.py 与指纹相关测试`
  - `docs/eval/LEDGER.md 与 eval_ledger.py`
  - `docs/eval/README.md（回归范围表）`
- **内网串行链**：内网串行链第 3 环（前：I-03；后：I-09）——仅当改动命中 A 组（如 app/eval/runner.py）时需要内网回归

## 1. 标题

[Wave-2][External] 评测侧第 4 步：回归范围表落地（含子集入口）、指纹降为报告元数据、LEDGER 机读

## 2. 背景

- phase75-assess §2：第 4 步「落地回归范围表（§3），包括子集入口；指纹从测试断言降为报告元数据；LEDGER 改成机读格式」，依赖第 1–3 步；放在最后是因为它是删除动作。
- phase75-step3 §8：第 4 步交给评测侧，「四件一起做」。评测侧（题库、判分、runner、comparator）是外部节点，我方只提需求（任务书「规则」）。
- 「四件」口径（S 11-25 定）：四件 = 回归范围表 + 子集入口 + 指纹降为报告元数据 + LEDGER 机读。出处是 phase75-step3.md §8 原文「四件一起做」；phase75-assess §2 第 4 行第一句「落地回归范围表（§3），包括子集入口」本身含两件，加上后两句的指纹降级和 LEDGER 机读，正好四件。
- `app/eval/runner.py` 在 A 组（`fingerprint.py` `_AFFECTS_RESULTS`），子集入口若改它须走内网回归并排在串行链上。
- 出处汇总：phase75-assess.md §2 第 4 行（:42）、§3（:65-79）、§5（:95-99）；phase75-step3.md §8；任务书「顺序已定」

## 3. 范围

**本次只解决**
- 我方提交验收需求：§3 回归范围表的子集入口按 `category` 筛；硬规则「全局改动不许只跑子集」写进入口；指纹仍写入每份报告元数据（§5:99）；LEDGER 可由脚本复算

**明确不做（Non-Goals）**
- 我方不改评测侧文件；不缩题库（DEVLOG [194]「明确不做」）

## 4. 输入

- #127 合入后的 master

## 5. 输出

- 评测侧 PR（若干）

## 6. 环境 / 前置条件

- 若触 A 组：内网空闲、链上前一环（I-03）已完成

## 7. 依赖

前置 I-03（第 1–3 步完成，且链序）；完成后解锁 I-09。

## 8. 实施步骤

- **节点 1**：我方在 issue 中列验收需求
  - 怎么验证：需求逐条对应 phase75-assess §3/§5
  - 通过标准：评测侧确认接收
- **节点 2**：评测侧实施
  - 怎么验证：评测侧自测
  - 通过标准：—
- **节点 3**：如触 A 组，内网回归一次
  - 怎么验证：nightly_gate
  - 通过标准：GREEN

## 9. 测试用例

- 由评测侧定义；我方验收：`--rescore` 与子集入口在同一 code_sha12 上可复算

## 10. 验收标准

- [ ] 子集入口存在且拒绝对全局改动只跑子集
- [ ] 报告元数据含指纹
- [ ] LEDGER 机读可重建

## 11. 交付物

- 评测侧 PR 合并 SHA
- 如触 A 组：新 code_sha12 登记
