<!-- 草稿 I-19：创建到 GitHub 后把 I-19 替换为真实 #编号，并同步 INDEX.md -->
# I-19 [Wave-4][Decision] 安装目录与数据目录分离：改安装目录，还是改数据目录（需迁移）

**标签**：`wave:4-pre-distribution` `exec:decision` `layer:desktop` `priority:P2`

## 依赖与并行编排

- **前置依赖**：无
- **可并行兄弟 Issue**：
  - I-18：两个决策互不依赖，可同时交给 S
- **后续解锁**：
  - I-20（desktop：按 I-19 的选择分离安装目录与数据目录）：安装目录 / 数据目录分离有两条路，选哪条决定 I-20 改哪些文件（phase6-desktop:75）
- **独占修改边界**：
  - 无

## 1. 标题

[Wave-4][Decision] 安装目录与数据目录分离：改安装目录，还是改数据目录（需迁移）

## 2. 背景

- 安装目录写法（已定，S 11-25）：phase6-desktop.md §1 第 2 条（:27）写 `%LOCALAPPDATA%\Programs\DataChat`，:75「遗留」写 `%LOCALAPPDATA%\DataChat`，两处不一致；由本 issue 以实际安装包核实哪一个是真实安装路径（决定下面的问题是否成立），文档里的写法由 I-20 实施时顺手改成核实后的那一个。
- 安装目录 `%LOCALAPPDATA%\DataChat` 与数据目录 `%LOCALAPPDATA%\datachat` 在 NTFS 上是同一目录（phase6:75 的写法，待本 issue 核实）；自动更新之前必须分开。一是改安装目录（NSIS 模板或 productName），二是改数据目录（要迁移数据，并影响浏览器模式共用同一份数据）（phase6:75）。数据目录在 `app/server/app.py:115-118`（B 组）与 `desktop/src-tauri/src/sidecar.rs:47` 解析。
- 出处汇总：phase6-desktop.md :27、:75；notes/progress-history.md「安装目录」条（要求在自动更新 I-21 之前处理）；S 11-25 裁定（安装目录写法由本 issue 核实）

## 3. 范围

**本次只解决**
- 先以实际安装包核实安装路径（phase6 :27 与 :75 哪个对）
- S 二选一

**明确不做（Non-Goals）**
- 不实现；不改 phase6-desktop.md（写法由 I-20 实施时顺手改）

## 4. 输入

- phase6:27、:75
- 实际安装包（desktop CI 工件）

## 5. 输出

- 决定

## 6. 环境 / 前置条件

- 对外分发启动

## 7. 依赖

无前置；解锁 I-20。

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
