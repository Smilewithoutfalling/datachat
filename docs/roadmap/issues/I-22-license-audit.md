<!-- 草稿 I-22：创建到 GitHub 后把 I-22 替换为真实 #编号，并同步 INDEX.md -->
# I-22 [Wave-4][Serial-Gate] desktop/ci：依赖许可证审计 + THIRD_PARTY_NOTICES + 设置页「关于」

**标签**：`wave:4-pre-distribution` `exec:serial` `layer:desktop` `priority:P2`

## 依赖与并行编排

- **前置依赖**：
  - I-21（desktop：自动更新 + release 工作流）：THIRD_PARTY_NOTICES 要打进安装包，改 tauri.conf.json；该文件在 I-20→I-21 链上独占，所以 I-22 排在 I-21 之后（phase6-desktop §7 原计划把自动更新与许可证审计放在同一个实现 PR 2）
  - I-18（仓库许可证：MIT / Apache-2.0 / 不开源）：仓库许可证决定第三方声明怎么写（phase6-desktop:31）
- **可并行兄弟 Issue**：无
- **后续解锁**：无
- **独占修改边界**：
  - `.github/workflows/licenses.yml（新，文件名实施时可调）`
  - `THIRD_PARTY_NOTICES.txt（新）`
  - `desktop/src-tauri/tauri.conf.json（bundle resources，链上独占：I-20→I-21→I-22）`
  - `ui/web/src/views/SettingsView.tsx（「关于」入口）`

## 1. 标题

[Wave-4][Serial-Gate] desktop/ci：依赖许可证审计 + THIRD_PARTY_NOTICES + 设置页「关于」

## 2. 背景

- phase6 §5：pip-licenses / license-checker / cargo-about 三套扫描，产出 THIRD_PARTY_NOTICES 打进安装包、设置页「关于」可打开；CI 遇 GPL/AGPL/LGPL/SSPL/未知许可证即红，白名单逐条说明（PyInstaller bootloader 例外）。
- 出处汇总：phase6-desktop.md §5（:86-90）、§1 第 6 条

## 3. 范围

**本次只解决**
- phase6 §5 第 1–3 条

**明确不做（Non-Goals）**
- 不定仓库许可证（I-18）

## 4. 输入

- I-18 决定
- I-21 合入

## 5. 输出

- PR

## 6. 环境 / 前置条件

- CI

## 7. 依赖

前置 I-18、I-21；无后续。

## 8. 实施步骤

- **节点 1**：首跑出结果
  - 怎么验证：三套报告
  - 通过标准：问题依赖列表交 S
- **节点 2**：CI 闸门 + 白名单
  - 怎么验证：故意引入 GPL 依赖时 CI 红（回退红）
  - 通过标准：白名单每条有理由
- **节点 3**：打包与关于页
  - 怎么验证：安装包内含 NOTICES；vitest 覆盖关于入口
  - 通过标准：通过

## 9. 测试用例

- vitest：设置页「关于」能打开 NOTICES；CI 闸门的回退红实验

## 10. 验收标准

- [ ] CI 闸门生效；NOTICES 在安装包

## 11. 交付物

- PR、DEVLOG 条目
- 审查对比表
- 节点语义一致性审查表（只读审查 subagent 输出，贴本 issue 评论；格式见 master-plan §6）
