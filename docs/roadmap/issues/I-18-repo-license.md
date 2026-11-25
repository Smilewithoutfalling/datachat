<!-- 草稿 I-18：创建到 GitHub 后把 I-18 替换为真实 #编号，并同步 INDEX.md -->
# I-18 [Wave-4][Decision] 仓库许可证：MIT / Apache-2.0 / 不开源

**标签**：`wave:4-pre-distribution` `exec:decision` `layer:docs` `priority:P2`

## 依赖与并行编排

- **前置依赖**：无
- **可并行兄弟 Issue**：
  - I-19：两个决策互不依赖，可同时交给 S
- **后续解锁**：
  - I-22（desktop/ci：依赖许可证审计 + THIRD_PARTY_NOTICES + 设置页「关于」）：仓库许可证决定第三方声明怎么写（phase6-desktop:31）
  - I-23（代码签名：由有实名主体的一方申请证书并配置 CI Secret）：免费签名（SignPath Foundation）的前提是 OSI 许可证（phase6-desktop:101）
- **独占修改边界**：
  - 无（决定落档时新增 LICENSE，随后续实施 PR）

## 1. 标题

[Wave-4][Decision] 仓库许可证：MIT / Apache-2.0 / 不开源

## 2. 背景

- 仓库没有 LICENSE（GitHub API license=null），默认保留所有权利；影响代码签名（I-23）能否申请免费签名、依赖许可证审计（I-22）的第三方声明怎么写（phase6:31）。对外分发的前提：签名、许可证、THREAT_MODEL (a) 重新确认，三者缺一不可（phase6:11）。
- 出处汇总：phase6-desktop.md §1 第 6 条（:31）、:11；任务书「推迟到对外分发前」

## 3. 范围

**本次只解决**
- S 选许可证

**明确不做（Non-Goals）**
- 不做许可证审计（I-22）

## 4. 输入

- phase6 §1、§6

## 5. 输出

- 决定

## 6. 环境 / 前置条件

- 对外分发启动（Wave-4 门槛）

## 7. 依赖

无前置；解锁 I-22、I-23。

## 8. 实施步骤

- **节点 1**：S 拍板
  - 怎么验证：评论明示
  - 通过标准：可执行

## 9. 测试用例

- 无

## 10. 验收标准

- [ ] 决定明示

## 11. 交付物

- 决定记录
