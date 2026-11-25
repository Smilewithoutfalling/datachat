<!-- 草稿 I-23：创建到 GitHub 后把 I-23 替换为真实 #编号，并同步 INDEX.md -->
# I-23 [Wave-4][External] 代码签名：由有实名主体的一方申请证书并配置 CI Secret

**标签**：`wave:4-pre-distribution` `exec:external` `layer:desktop` `priority:P2`

## 依赖与并行编排

- **前置依赖**：
  - I-18（仓库许可证：MIT / Apache-2.0 / 不开源）：免费签名（SignPath Foundation）的前提是 OSI 许可证（phase6-desktop:101）
- **可并行兄弟 Issue**：无
- **后续解锁**：无
- **独占修改边界**：
  - （外部）证书申请；CI 签名步骤已预留（Secret 存在就签）

## 1. 标题

[Wave-4][External] 代码签名：由有实名主体的一方申请证书并配置 CI Secret

## 2. 背景

- 签名证书须由有实名主体、能付款的一方办（S 没有）；OV/EV 对 SmartScreen 都需信誉积累；SignPath Foundation 需 OSI 许可证（phase6 §6）。
- 出处汇总：phase6-desktop.md §6（:92-106）；HANDOVER §5 第 5 条

## 3. 范围

**本次只解决**
- 我方提需求：证书类型与材料清单按 phase6 §6

**明确不做（Non-Goals）**
- 我方不申请证书

## 4. 输入

- I-18 决定

## 5. 输出

- 证书与 Secret

## 6. 环境 / 前置条件

- 有主体的一方

## 7. 依赖

前置 I-18。

## 8. 实施步骤

- **节点 1**：外部申请
  - 怎么验证：—
  - 通过标准：拿到证书
- **节点 2**：S 配置 Secret
  - 怎么验证：CI 工件名不再标 unsigned
  - 通过标准：签名后显示已验证发布者

## 9. 测试用例

- 无

## 10. 验收标准

- [ ] 安装包显示已验证的发布者名称（phase6 §6 改写后的验收）

## 11. 交付物

- 签名后的工件
