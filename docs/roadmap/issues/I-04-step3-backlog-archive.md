<!-- 草稿 I-04：创建到 GitHub 后把 I-04 替换为真实 #编号，并同步 INDEX.md -->
# I-04 [Wave-1][Parallel-B] docs：摘下的 S3-3 与 S3-2 产品闸、react 注入挂 BACKLOG，存档 mul_005#2 快照作验收材料，更新第 3 步方案状态

**标签**：`wave:1-step3-closeout` `exec:parallel` `layer:docs` `priority:P1`

## 依赖与并行编排

- **前置依赖**：无
- **可并行兄弟 Issue**：
  - I-01：修改面完全隔离：I-01 只动 app/ 与 tests/ 下列出的 Python 文件，I-02 只动 ui/web/src，I-04 只动 docs/eval/BACKLOG.md、docs/roadmap/phase75-step3.md 与 docs/eval/archives/step3-mul_005-replan/；受沙箱并行度上限 2 约束，分两批开（I-01+I-02，然后 I-04；独立节点 I-05 也计入这 2 个名额）
  - I-02：修改面完全隔离：I-01 只动 app/ 与 tests/ 下列出的 Python 文件，I-02 只动 ui/web/src，I-04 只动 docs/eval/BACKLOG.md、docs/roadmap/phase75-step3.md 与 docs/eval/archives/step3-mul_005-replan/；受沙箱并行度上限 2 约束，分两批开（I-01+I-02，然后 I-04；独立节点 I-05 也计入这 2 个名额）
  - I-07：I-07 是评测侧分支（docs/eval/CANARY.md、docs/eval/canary/baseline.json），与我方 Wave-1 各节点文件不交；DEVLOG 是追加型共享台账，按「后合者接号」处理，不计入独占边界
- **后续解锁**：
  - I-03（eval/regress：#127 摘除后重跑本地闸门 + 内网回归一批 new（nightly_gate 判读 + canary），通过后 squash 合并）：挂账条目与方案状态更新随 #127 一起合入（S 要求「摘下的部分挂 BACKLOG」），I-03 合并前分支上必须已有这些文档
  - I-12（BACKLOG N9（mul_005）：放宽出境合同，还是让 reviewer 在沙箱里查 unique()）：N9 出境合同决策要用 I-04 存档的 mul_005#2 快照和挂账条目（被摘的字面量豁免）作为材料
- **独占修改边界**：
  - `docs/eval/BACKLOG.md（只动「阶段 7.5」分区表格，:574-579）`
  - `docs/roadmap/phase75-step3.md（状态行与 §7/§8 补记，不写 §5 附录）`
  - `docs/eval/archives/step3-mul_005-replan/（新目录，只放 mul_005#2 快照）`

## 1. 标题

[Wave-1][Parallel-B] docs：摘下的 S3-3 与 S3-2 产品闸、react 注入挂 BACKLOG，存档 mul_005#2 快照作验收材料，更新第 3 步方案状态

## 2. 背景

- phase75-assess.md 开头：本阶段产品任务放进 BACKLOG 新开的「阶段 7.5」分区，不受 11-17 冻结约束。该分区目前是空表（docs/eval/BACKLOG.md:574-579）。
- S 要求：摘下的部分（S3-3 REPLAN；S3-2 的 scope_gate、code_before_fix、字面量豁免、前端两版计划、recursion_limit 改动）挂 BACKLOG；mul_005#2 的快照作为验收材料存档；字面量豁免日后要覆盖同列 `==`↔`isin`（任务书「当前事实」第 2 条）。
- phase75-step3.md 状态行仍写「三件放一个 PR」（:3、§7 第 1 条），需补记 S 的摘除决定，否则方案与代码不一致（HANDOVER §3「方案先行」）。
- react 链路不同步注入 S3-1 能力说明：phase75-step3 §7 第 4 条（S 11-24 13:46）已定「不同步、挂账，等 react 下一次改 prompt 时一并做」。原计划的单独 Decision issue 取消，挂账条目并入本 issue。
- 快照入库已定（S 11-25）：放 `docs/eval/archives/step3-mul_005-replan/`，不放 tests/fixtures；数据来自 data/eval 下的合成数据，不涉及出境，也没有许可问题。
- 出处汇总：S 11-24 决定（摘下的挂 BACKLOG、mul_005#2 快照存档、豁免日后要覆盖同列 ==↔isin）；S 11-25 裁定（快照入库路径、来源；react 注入挂账并入本 issue）；docs/eval/BACKLOG.md:574-579 阶段 7.5 分区；phase75-step3.md §7 第 4 条、§8

## 3. 范围

**本次只解决**
- BACKLOG 阶段 7.5 分区新增 5 条：S3-3 REPLAN、S3-2 口径闸（产品链路）、字面量豁免（含 ==↔isin 要求）、前端两版计划、react 链路同步注入 S3-1 能力说明（挂账，触发条件：react 下一次改 prompt）；每条写来源、重新启用的前提、验收材料位置
- 把 mul_005#2 快照存入 `docs/eval/archives/step3-mul_005-replan/`，sha256 写进对应 BACKLOG 条目
- phase75-step3.md 补记摘除决定（日期、范围、保留项）

**明确不做（Non-Goals）**
- 不改 BACKLOG 冻结的「下一轮」节与 N 系列条目（N9 只引用不改）；不写 phase75-step3 §5 附录（归 I-06）；不写 DEVLOG（归 I-03）；不实现 react 注入；快照不放 tests/fixtures

## 4. 输入

- mul_005#2 快照：源文件在评测侧内网机上 `D:\Coding\claude\_ver\snap_new\20261125T011905485445Z_214afb99c9bd438d914facf8e1b2f34e.jsonl`（19171d8 内网回归的快照），由评测侧打包交付
- PR #127 描述的「偏离及理由」与被摘清单
- phase75-step3.md §7 第 4 条（react 不同步注入）

## 5. 输出

- BACKLOG 5 条挂账
- `docs/eval/archives/step3-mul_005-replan/` 下的快照文件及其 sha256
- phase75-step3.md 状态更新

## 6. 环境 / 前置条件

- 评测侧已打包交付快照文件（入库已定：合成数据，不涉出境、无许可问题）

## 7. 依赖

无前置（快照文件由评测侧交付，是输入而不是 issue 依赖）；commit 落在 feat/step3，随 #127 合入（解锁 I-03）；同时为 I-12 提供材料。

## 8. 实施步骤

- **节点 1**：写 BACKLOG 阶段 7.5 分区 5 条（含 react 注入挂账）
  - 怎么验证：表格列「编号 | 事项 | 步 | 状态」与分区表头一致；每条有出处（PR #127、phase75-step3 §节号；react 条引 §7 第 4 条）
  - 通过标准：5 条齐全；字面量豁免条写明「同列 ==↔isin 也算只换比较值」的待覆盖要求；react 条写明触发条件
- **节点 2**：收到评测侧交付的快照文件后先核对内容，再入库
  - 怎么验证：逐行解析 jsonl：存在 `case_id=mul_005` 的记录，且含 replan 节点的记录
  - 通过标准：两项都成立才入库；任一不成立，停下报 S，不入库
- **节点 3**：存档 mul_005#2 快照到 `docs/eval/archives/step3-mul_005-replan/`
  - 怎么验证：`sha256sum` 结果写进 BACKLOG 条目
  - 通过标准：BACKLOG 条目能按路径 + sha256 找回该快照；tests/fixtures 下无新增
- **节点 4**：更新 phase75-step3.md 状态
  - 怎么验证：diff 只在状态行、§7、§8
  - 通过标准：读者从文件能看出 S3-3 与产品闸已摘、何时、去了 BACKLOG 哪几条

## 9. 测试用例

- 文档变更，无代码测试；`git diff --stat` 只含边界内文件

## 10. 验收标准

- [ ] 边界外文件 diff 为空
- [ ] BACKLOG 条目可从编号反查到 #127 与方案节号
- [ ] 快照已核对（case_id=mul_005、含 replan 节点）且 sha256 与 BACKLOG 条目一致
- [ ] 审查对比表无未解释偏离

## 11. 交付物

- feat/step3 上的文档 commit（BACKLOG 5 条、快照、方案状态）
- 审查对比表（贴 issue 评论）
- 节点语义一致性审查表（只读审查 subagent 输出，贴本 issue 评论；格式见 master-plan §6）
