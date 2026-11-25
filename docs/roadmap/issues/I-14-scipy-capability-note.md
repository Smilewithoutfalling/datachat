<!-- 草稿 I-14：创建到 GitHub 后把 I-14 替换为真实 #编号，并同步 INDEX.md -->
# I-14 [Wave-3][Decision] B3：codegen 是否加 scipy.stats 能力说明（看 probe 批读数后定）

**标签**：`wave:3-decisions` `exec:decision` `layer:nodes` `priority:P2`

## 依赖与并行编排

- **前置依赖**：
  - I-13（评测侧 scipy probe 批：t 检验、卡方、相关显著性 3 题单独跑（不入库、不断代））：B3 能力说明加不加，要先看 probe 批 3 题的读数（decisions-pending B3、phase75-scipy §3④）
- **可并行兄弟 Issue**：无
- **后续解锁**：无
- **独占修改边界**：
  - 无（不改仓库文件；决定以本 issue 评论为准，落档规则见 master-plan「审批点」）

## 1. 标题

[Wave-3][Decision] B3：codegen 是否加 scipy.stats 能力说明（看 probe 批读数后定）

## 2. 背景

- phase75-scipy §3④补充：没有能力说明时 probe 测出「模型不用检验」只能算下界；加不加属于 A 组 prompt 变更，需全量回归，由 S 定。B1 已定等题驱动、不加库。
- 出处汇总：decisions-pending B3（:22）；phase75-scipy.md §3④ 补充（:30）、§4（:32-36）

## 3. 范围

**本次只解决**
- 请 S 就下列问题拍板：是否加能力说明（加则另开 A 组实施 issue，接内网链尾，跑全量 202）

**明确不做（Non-Goals）**
- 本 issue 不含实现；定了之后如需实现，另开 issue，触 A 组的接到内网串行链尾

## 4. 输入

- 本 issue 背景中引用的方案与读数

## 5. 输出

- S 的决定（issue 评论）

## 6. 环境 / 前置条件

- 无

## 7. 依赖

前置 I-13（probe 读数）。

## 8. 实施步骤

- **节点 1**：整理选项与代价（只引用已有材料）
  - 怎么验证：每个选项都带出处
  - 通过标准：S 能直接选
- **节点 2**：S 拍板
  - 怎么验证：评论中明示选项
  - 通过标准：决定可执行

## 9. 测试用例

- 无

## 10. 验收标准

- [ ] 决定在评论中明示，且注明是否需要后续实施 issue

## 11. 交付物

- 决定记录
