<!-- 草稿 I-13：创建到 GitHub 后把 I-13 替换为真实 #编号，并同步 INDEX.md -->
# I-13 [Wave-3][External] 评测侧 scipy probe 批：t 检验、卡方、相关显著性 3 题单独跑（不入库、不断代）

**标签**：`wave:3-decisions` `exec:external` `layer:eval` `priority:P2`

## 依赖与并行编排

- **前置依赖**：
  - I-09（评测侧 v8 基线：内网空闲时连跑三次 202 题，取中位数重立）：内网只能串行；probe 批不在关键路径上，排在 v8 三跑之后，避免 v8 需要的「机器空闲」被占（phase75-assess:106）
  - I-03（eval/regress：#127 摘除后重跑本地闸门 + 内网回归一批 new（nightly_gate 判读 + canary），通过后 squash 合并）：S3-1 合入后 codegen prompt 会写明「只能用这些包」，probe 要在新 prompt 上测才有意义（phase75-scipy §3④ 补充②：没有能力说明时只能算下界）
- **可并行兄弟 Issue**：无
- **后续解锁**：
  - I-14（B3：codegen 是否加 scipy.stats 能力说明（看 probe 批读数后定））：B3 能力说明加不加，要先看 probe 批 3 题的读数（decisions-pending B3、phase75-scipy §3④）
- **独占修改边界**：
  - （评测侧）probe 批题面与报告，不进 ALL_CASES
- **内网串行链**：内网串行链第 5 环（前：I-09）

## 1. 标题

[Wave-3][External] 评测侧 scipy probe 批：t 检验、卡方、相关显著性 3 题单独跑（不入库、不断代）

## 2. 背景

- B3 决定：只做 probe 批，不入库、不断代（形式同 probe_flip_1118）；202→205 会改 evalset 指纹使 v7/v8 不可比。
- 出处汇总：decisions-pending B3（:22）；phase75-scipy.md §3④ 及 11-20 补充（:29-30）

## 3. 范围

**本次只解决**
- 我方提需求：3 题单独跑，报告注明「无能力说明，读数为下界」（若 I-14 尚未决定）

**明确不做（Non-Goals）**
- 不进 ALL_CASES；不加 scipy 库（B1 等题驱动）

## 4. 输入

- #127 合入后的 master（S3-1 prompt）

## 5. 输出

- probe 读数

## 6. 环境 / 前置条件

- 内网空闲，链上 I-09 已完成

## 7. 依赖

前置 I-03（S3-1 prompt 已在 master）、I-09（内网队列）；完成后解锁 I-14。

## 8. 实施步骤

- **节点 1**：评测侧出题并单独跑
  - 怎么验证：报告带 code_sha12
  - 通过标准：3 题读数齐全

## 9. 测试用例

- 评测侧定义

## 10. 验收标准

- [ ] 读数附带「下界」说明；evalset 指纹未变

## 11. 交付物

- probe 报告
