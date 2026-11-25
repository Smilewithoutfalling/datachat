<!-- 草稿 I-21：创建到 GitHub 后把 I-21 替换为真实 #编号，并同步 INDEX.md -->
# I-21 [Wave-4][Serial-Gate] desktop：自动更新 + release 工作流

**标签**：`wave:4-pre-distribution` `exec:serial` `layer:desktop` `priority:P2`

## 依赖与并行编排

- **前置依赖**：
  - I-20（desktop：按 I-19 的选择分离安装目录与数据目录）：做自动更新之前必须先把安装目录和数据目录分开（phase6-desktop:75）；两者都改 desktop/src-tauri 配置，串行独占
- **可并行兄弟 Issue**：无
- **后续解锁**：
  - I-22（desktop/ci：依赖许可证审计 + THIRD_PARTY_NOTICES + 设置页「关于」）：THIRD_PARTY_NOTICES 要打进安装包，改 tauri.conf.json；该文件在 I-20→I-21 链上独占，所以 I-22 排在 I-21 之后（phase6-desktop §7 原计划把自动更新与许可证审计放在同一个实现 PR 2）
- **独占修改边界**：
  - `desktop/src-tauri/tauri.conf.json`
  - `desktop/src-tauri/Cargo.toml`
  - `desktop/src-tauri/src/`
  - `.github/workflows/release.yml（新）`
  - `ui/web/src/views/ui.tsx（顶栏「有新版本」提示）`

## 1. 标题

[Wave-4][Serial-Gate] desktop：自动更新 + release 工作流

## 2. 背景

- phase6 §4：tauri-plugin-updater 读 GitHub Releases 的 latest.json；启动 10 s 后检查，用户点了才更新；minisign 更新签名，私钥由 S 粘贴进 Secret `TAURI_SIGNING_PRIVATE_KEY`；`tauri.conf.json` version 为唯一来源，tag `v0.x.y` 触发 release。
- 出处汇总：phase6-desktop.md §4（:77-84）、:11

## 3. 范围

**本次只解决**
- phase6 §4 第 1–4 条

**明确不做（Non-Goals）**
- 不做 Authenticode 代码签名（I-23）

## 4. 输入

- I-20 合入

## 5. 输出

- 实现 PR
- 测试 Release v0.1.0→v0.1.1（pre-release）

## 6. 环境 / 前置条件

- S 粘贴 Secret（审批点）

## 7. 依赖

前置 I-20；解锁 I-22。

## 8. 实施步骤

- **节点 1**：实现 updater 与 release 工作流
  - 怎么验证：CI 发两版
  - 通过标准：runner 上旧版升级到新版，版本号变、旧会话在
- **节点 2**：S 本机验一次升级
  - 怎么验证：—
  - 通过标准：通过

## 9. 测试用例

- CI 升级验收（phase6 §4 验收）

## 10. 验收标准

- [ ] phase6 §4 验收全过

## 11. 交付物

- PR、DEVLOG 条目
- 审查对比表
- 节点语义一致性审查表（只读审查 subagent 输出，贴本 issue 评论；格式见 master-plan §6）
