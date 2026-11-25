<!-- 草稿 I-09：创建到 GitHub 后把 I-09 替换为真实 #编号，并同步 INDEX.md -->
# I-09 [Wave-2][External] 评测侧 v8 基线：内网空闲时连跑三次 202 题，取中位数重立

**标签**：`wave:2-eval-downgrade` `exec:external` `layer:eval` `priority:P1`

## 依赖与并行编排

- **前置依赖**：
  - I-03（eval/regress：#127 摘除后重跑本地闸门 + 内网回归一批 new（nightly_gate 判读 + canary），通过后 squash 合并）：v8 基线在第 3 步合并之后重立（phase75-assess:106、phase75-step3 §8）
  - I-08（评测侧第 4 步：回归范围表落地（含子集入口）、指纹降为报告元数据、LEDGER 机读）：顺序已定：第 4 步评测降级之后再重立 v8；第 4 步若改了 A 组，code_sha12 会变，先立基线会立即失效
- **可并行兄弟 Issue**：无
- **后续解锁**：
  - I-13（评测侧 scipy probe 批：t 检验、卡方、相关显著性 3 题单独跑（不入库、不断代））：内网只能串行；probe 批不在关键路径上，排在 v8 三跑之后，避免 v8 需要的「机器空闲」被占（phase75-assess:106）
- **独占修改边界**：
  - （评测侧台账）docs/eval/baselines.json 与 v8 基线文件
  - `docs/eval/LEDGER.md（v8 读数）`
- **内网串行链**：内网串行链第 4 环（前：I-08；后：I-13）

## 1. 标题

[Wave-2][External] 评测侧 v8 基线：内网空闲时连跑三次 202 题，取中位数重立

## 2. 背景

- phase75-assess §6:106：第 3 步合并之后重立 v8，机器空闲时连跑三次取中位数，按 v7 的做法；197 是 5a2ad4c 单跑一次，不能直接用（decisions-pending D2）。
- 顺序已定：第 3 步 → 第 4 步评测降级 → 重立 v8（任务书）。
- 执行方（S 11-25 定）：评测侧。内网跑批一直是评测侧在内网机上跑，baselines.json / LEDGER 也是评测侧台账，所以本 issue 为 External；链位不变（I-08 → I-09 → I-13）。
- 出处汇总：phase75-assess.md §6:106；phase75-step3.md §8；decisions-pending D2（:39，单跑不立基线）；任务书「顺序已定」

## 3. 范围

**本次只解决**
- 我方提验收需求：三次全量 + 取中位数 + 登记基线与 code_sha12/evalset 指纹；由评测侧执行

**明确不做（Non-Goals）**
- 我方不改评测侧台账文件；不改题库、gold、判分

## 4. 输入

- I-08 合入后的 master

## 5. 输出

- v8 基线文件与台账条目

## 6. 环境 / 前置条件

- 内网空闲，链上 I-08 已完成；评测侧在内网机上执行

## 7. 依赖

前置 I-03、I-08；完成后解锁 I-13（内网队列）。

## 8. 实施步骤

- **节点 1**：评测侧连跑三次
  - 怎么验证：三份报告同 code_sha12、同 evalset 指纹
  - 通过标准：三份均完整 202 题
- **节点 2**：评测侧取中位数立 v8
  - 怎么验证：按 v7 做法计算
  - 通过标准：baselines.json 新增 v8，可由报告复算
- **节点 3**：我方验收
  - 怎么验证：按 code_sha12 与 master 核对；复算中位数
  - 通过标准：一致

## 9. 测试用例

- nightly_gate 对 v8 自比 exit 0

## 10. 验收标准

- [ ] v8 登记，指纹与 master 一致；LEDGER 可复算（BACKLOG「不许做的」第 5 条）

## 11. 交付物

- v8 基线条目与三份报告路径
- DEVLOG 条目（评测侧按其惯例写）
