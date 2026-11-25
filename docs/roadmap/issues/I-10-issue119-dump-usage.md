<!-- 草稿 I-10：创建到 GitHub 后把 I-10 替换为真实 #编号，并同步 INDEX.md -->
# I-10 [Wave-2][External] 评测侧 #119 收尾：canary 增加 `--dump-usage`（原始 usage 回包可查）

**标签**：`wave:2-eval-downgrade` `exec:external` `layer:eval` `priority:P2`

## 依赖与并行编排

- **前置依赖**：无
- **可并行兄弟 Issue**：
  - I-08：均为评测侧外部节点；#119 收尾只动 canary 脚本与 CANARY.md，第 4 步动 runner/fingerprint/LEDGER，修改面不交（由评测侧确认）
- **后续解锁**：无
- **独占修改边界**：
  - （评测侧）scripts/eval/canary.py
  - `docs/eval/CANARY.md`

## 1. 标题

[Wave-2][External] 评测侧 #119 收尾：canary 增加 `--dump-usage`（原始 usage 回包可查）

## 2. 背景

- #119：canary 的 tokens_in 占比 +87.5% 是网关不再回报 cache_read/reasoning；建议核实原始 usage 响应，字段缺失时报「usage 字段覆盖变化」而非占比漂移。#123 已落档归因并重立基线，但「看原始回包」仍靠手工 curl。
- 出处汇总：issue #119「建议（评测侧）」；PR #123 描述「待办」第 1 条；任务书「#119 属评测侧（canary --dump-usage）」

## 3. 范围

**本次只解决**
- 我方提需求：canary 能导出原始 usage 结构，用于判断覆盖变化

**明确不做（Non-Goals）**
- 我方不改评测侧文件

## 4. 输入

- —

## 5. 输出

- 评测侧 PR

## 6. 环境 / 前置条件

- 无

## 7. 依赖

无前置；与 I-08 并行（评测侧内部排期）。

## 8. 实施步骤

- **节点 1**：评测侧实施
  - 怎么验证：评测侧自测
  - 通过标准：—

## 9. 测试用例

- 评测侧定义

## 10. 验收标准

- [ ] #119 关闭

## 11. 交付物

- PR 合并 SHA
