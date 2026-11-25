<!-- 草稿 I-20：创建到 GitHub 后把 I-20 替换为真实 #编号，并同步 INDEX.md -->
# I-20 [Wave-4][Serial-Gate] desktop：按 I-19 的选择分离安装目录与数据目录

**标签**：`wave:4-pre-distribution` `exec:serial` `layer:desktop` `priority:P2`

## 依赖与并行编排

- **前置依赖**：
  - I-19（安装目录与数据目录分离：改安装目录，还是改数据目录（需迁移））：安装目录 / 数据目录分离有两条路，选哪条决定 I-20 改哪些文件（phase6-desktop:75）
- **可并行兄弟 Issue**：无
- **后续解锁**：
  - I-21（desktop：自动更新 + release 工作流）：做自动更新之前必须先把安装目录和数据目录分开（phase6-desktop:75）；两者都改 desktop/src-tauri 配置，串行独占
- **独占修改边界**：
  - `desktop/src-tauri/tauri.conf.json`
  - `desktop/src-tauri/hooks.nsh`
  - `desktop/src-tauri/src/sidecar.rs`
  - `app/server/app.py（仅数据目录解析 :115-118，选方案二时）`
  - `app/server/__main__.py（--home 帮助文字，选方案二时）`
  - `docs/roadmap/phase6-desktop.md（只改 :27、:75 两处安装目录写法）`

## 1. 标题

[Wave-4][Serial-Gate] desktop：按 I-19 的选择分离安装目录与数据目录

## 2. 背景

- 安装目录写法（已定，S 11-25）：以 I-19 核实的实际安装路径为准，本 issue 实施时顺手把 phase6-desktop.md :27、:75 两处写法统一成核实后的那一个。
- 见 I-19；卸载页「删除应用数据」由 `hooks.nsh` POSTUNINSTALL 补删数据目录（phase6 §3），分离后要同步。`app/server/` 属 B 组（fingerprint.py:139），不触内网回归。
- 出处汇总：phase6-desktop.md :75、§1 第 2、4 条（:23-27）

## 3. 范围

**本次只解决**
- 按选定方案分离两目录，旧数据可用
- 顺手统一 phase6-desktop.md 的安装目录写法（以 I-19 核实结果为准）

**明确不做（Non-Goals）**
- 不做自动更新（I-21）

## 4. 输入

- I-19 决定

## 5. 输出

- 实现 PR

## 6. 环境 / 前置条件

- Windows CI（desktop.yml、sidecar.yml）；S 本机验一次安装/卸载（phase6 验收须 S 本人）

## 7. 依赖

前置 I-19；解锁 I-21。

## 8. 实施步骤

- **节点 1**：实现
  - 怎么验证：desktop / sidecar CI 绿
  - 通过标准：安装包可装
- **节点 2**：旧库兼容
  - 怎么验证：旧数据目录启动测试
  - 通过标准：旧会话还在
- **节点 3**：S 本机验
  - 怎么验证：安装→卸载（勾/不勾删数据）
  - 通过标准：行为符合 phase6 §1 第 4 条

## 9. 测试用例

- 新增「旧数据目录启动」用例（沿用 `test_v1_database_gains_feedback_table_without_touching_old_tables` 的做法，phase6 §4 第 4 条）

## 10. 验收标准

- [ ] 两目录不同；卸载不删数据（默认）；CI 绿；S 本机通过

## 11. 交付物

- PR、DEVLOG 条目
- 审查对比表
- 节点语义一致性审查表（只读审查 subagent 输出，贴本 issue 评论；格式见 master-plan §6）
