<!-- 草稿 I-03：创建到 GitHub 后把 I-03 替换为真实 #编号，并同步 INDEX.md -->
# I-03 [Wave-1][Serial-Gate] eval/regress：#127 摘除后重跑本地闸门 + 内网回归一批 new（nightly_gate 判读 + canary），通过后 squash 合并

**标签**：`wave:1-step3-closeout` `exec:serial` `layer:eval` `priority:P0` `regress:intranet`

## 依赖与并行编排

- **前置依赖**：
  - I-01（nodes/graph：#127 摘除 S3-3 REPLAN 与 S3-2 产品闸（后端），保留 S3-1 与 code_scope 搬家）：I-03 回归与合并的对象就是 I-01 摘除后的 #127 head；I-01 不完成就没有可回归的 head（A 组链序 1→2）
  - I-02（web：#127 摘除「重新规划」两版计划显示）：#127 的最终 head 需包含前端摘除；I-02 没落到分支上，本地闸门（vitest/e2e）和 CI 测的就不是最终内容
  - I-04（docs：摘下的 S3-3 与 S3-2 产品闸、react 注入挂 BACKLOG，存档 mul_005#2 快照作验收材料，更新第 3 步方案状态）：挂账条目与方案状态更新随 #127 一起合入（S 要求「摘下的部分挂 BACKLOG」），I-03 合并前分支上必须已有这些文档
  - I-07（评测侧 #123：rebase 让号到 [211]/[212]，先于 #127 合并）：S 11-25 定：计划书 PR 占 DEVLOG [210]；#123 在计划书 PR 之后、#127 之前合并。I-07 合入后 #123 占 [211]/[212]，I-03 合并时 #127 接 [213]，不再撞号
- **可并行兄弟 Issue**：无
- **后续解锁**：
  - I-06（S3-4：标注假阳率后由 S 定 grounding 拦不拦、拦在哪、证据口径用哪一份）：I-06 要把假阳率表和 S 的决定写进 phase75-step3.md 附录；该文件在 #127 分支上被 I-04 修改，#127 合入（I-03）后才能在 master 上改，避免两分支同改一文件
  - I-08（评测侧第 4 步：回归范围表落地（含子集入口）、指纹降为报告元数据、LEDGER 机读）：第 4 步评测降级依赖第 1–3 步完成（phase75-assess:42）；且子集入口会改 app/eval/runner.py（A 组），按链序须排在 #127 的内网回归之后
  - I-09（评测侧 v8 基线：内网空闲时连跑三次 202 题，取中位数重立）：v8 基线在第 3 步合并之后重立（phase75-assess:106、phase75-step3 §8）
  - I-13（评测侧 scipy probe 批：t 检验、卡方、相关显著性 3 题单独跑（不入库、不断代））：S3-1 合入后 codegen prompt 会写明「只能用这些包」，probe 要在新 prompt 上测才有意义（phase75-scipy §3④ 补充②：没有能力说明时只能算下界）
- **独占修改边界**：
  - `docs/DEVLOG.md（#127 条目 [213]：重写「改了什么/偏离/闸门」，回填此前未回填的 commit 字段；追加型共享台账）`
  - `PR #127 描述（GitHub）`
- **内网串行链**：内网串行链第 2 环（前：I-01；后：I-08）

## 1. 标题

[Wave-1][Serial-Gate] eval/regress：#127 摘除后重跑本地闸门 + 内网回归一批 new（nightly_gate 判读 + canary），通过后 squash 合并

## 2. 背景

- A 组文件（`app/eval/fingerprint.py:38` `_AFFECTS_RESULTS`）改动必须跑内网回归，且内网只能串行（任务书「规则」）。摘除后 head 的 A 组内容与 19171d8 不同，原 GREEN 196/202 不再适用于新 head，需重跑；S 已定内网只跑一批 new（含 gate 和 canary；这里的 gate 指 nightly_gate 判读，见「环境 / 前置条件」）。
- phase75-assess §3:71：全局 prompt / graph / nodes 改动须评测全量 202 题，不许只跑子集；判读口径为 nightly_gate 配对净退步 <6（decisions-pending A1、#111 B5）。
- DEVLOG 编号链（S 11-25 定）：计划书 PR 占 [210]，并在其中回填 [209]=9c40a97（HANDOVER §4 末条）；#123（I-07）在计划书 PR 合并之后让号到 [211]/[212]；本节点 #127 的 squash 条目写 [213]——前提是计划书 PR 与 I-07 都已先合入。#123 原与 [209] 撞号（#123 评论 11-24 13:38）。phase75-assess §5:98：squash 的 commit body 必须承接 PR 描述全文。
- 执行分工（S 11-25 定）：节点 1/2（本地闸门、push、CI）由我方在 worktree 里做；节点 3（一批 new → nightly_gate 判读 → canary）由评测侧在内网执行；S 在本 issue 只做两件事：批准 push、批准合并。
- 出处汇总：任务书「当前事实」第 2 条（摘完重跑本地闸门，内网只跑一批 new）；phase75-assess §3:71；HANDOVER §3、§7；phase75-assess §5:98

## 3. 范围

**本次只解决**
- 在 I-01、I-02、I-04 都落到 feat/step3、且计划书 PR（[210]）与 I-07（#123）已先合入 master 后：我方在 worktree 重跑本地闸门 → 汇报 → S 批准后我方 push → CI → 评测侧在内网跑一批 new（nightly_gate 判读 + canary）→ 我方写 DEVLOG 与 PR 描述 → S 批准后我方 squash 合并

**明确不做（Non-Goals）**
- 不跑前后两批快照的 `assess --diff`（S3-3 已摘，归因要求随之失效）；不重立 v8（I-09）；不改任何 A 组文件（如回归红，回到 I-01 修，不在本节点改代码）

## 4. 输入

- feat/step3 摘除后 head（含 I-01/I-02/I-04 的 commit）
- v7 基线（docs/eval/baseline_v7.json）
- 评测侧内网回贴的 nightly_gate / canary 报告

## 5. 输出

- 本地闸门全量读数表（与 master 9c40a97 对照）
- CI 三工作流按 head_sha 的 run id
- 内网读数（通过数、配对净退步、canary 判读）
- DEVLOG 条目与 PR 描述
- 合并后的 master SHA

## 6. 环境 / 前置条件

- 内网机器空闲且链上无其他节点占用（链序：I-01 完成后才轮到本节点）
- 执行分工（S 11-25 定）：节点 1/2（本地闸门、push、CI）由我方在 worktree（/workspace/work/dc_s3，分支 feat/step3）里做；节点 3 由评测侧在内网执行；S 只做两件事——批准 push、批准合并
- 节点 3 内网环境（评测侧，既定路径）：用 codeload tarball 取待回归 head（`https://codeload.github.com/Smilewithoutfalling/datachat/tar.gz/<完整 40 位 SHA>`，必须写完整 40 位 SHA，不用短 SHA 或分支名）→ 解压到 `D:\Coding\claude\_ver` → 从原仓库拷 `.env`（不进仓库，M03）→ `set PYTHONUTF8=1` → 在 conda 环境 `dc` 里用 python 跑（回归命令见 docs/eval/README.md「命令一」）
- 本节点所说的 gate 只指 nightly_gate 对 v7 的判读，不含 docs/gate 的 25 题外部验证闸门：#127 与本次摘除都没有动判分、gold 和 gate answers，外部闸门的输入没变，不需要重跑
- 计划书 PR（[210]）与 I-07（#123，[211]/[212]）已先合入 master，DEVLOG 末条为 [212]；核对 DEVLOG 一律以 `git show origin/master:docs/DEVLOG.md` 为准，不看任何本地工作树（S 本机 D:\Coding\claude\datachat 停在 d84363c 且带未提交 DEVLOG 改动，见 master-plan §9）
- push 与合并须 S 明确批准（HANDOVER §3）；PR 更新随 push 一并汇报

## 7. 依赖

前置 I-01、I-02、I-04 全部完成，且计划书 PR（DEVLOG [210]）与 I-07（#123）先合入；合入后解锁 I-06、I-08、I-09、I-13。

## 8. 实施步骤

- **节点 1**：本地闸门全量重跑（我方在 worktree 做，最后一次改动之后）
  - 怎么验证：pytest 分三段 + oracle 单独跑；评测侧三件；gen_ui_types --check；`python -m app.sidecar --selftest`；vitest/eslint/tsc/build/playwright --list（同 PR #127 闸门表）
  - 通过标准：pytest 0 failed 0 skipped；sidecar selftest 全过（项数与 master 相同）；vitest 984 passed；与 master 对照表无无法解释的增减
- **节点 2**：汇报，S 批准后由我方 push（force-with-lease 到 feat/step3），等 CI
  - 怎么验证：按 head_sha 列 tests / sidecar / desktop 三个 workflow
  - 通过标准：被触发的 workflow 全部 success；视觉基线若红按 HANDOVER §6 处理
- **节点 3**：内网一批 new（评测侧在内网执行）：跑一批 new，再做 nightly_gate 判读和 canary
  - 怎么验证：评测侧按「环境 / 前置条件」的既定路径取 push 后 head 的完整 40 位 SHA tarball 运行；nightly_gate 对 v7 判读；canary 同批；报告回贴本 issue
  - 通过标准：nightly_gate GREEN（配对净退步 <6，退出码 0）；canary 无阻断（CLEAN 或只列不拦的提示）；读数里的 code_sha12 = I-01 报告的新值；报告所测 SHA = push 后 head 的完整 SHA
- **节点 4**：写 DEVLOG 条目与 PR 描述（我方）
  - 怎么验证：fetch 后用 `git show origin/master:docs/DEVLOG.md` 核对末条为 [212]（#123），本条写 [213]；条目注明摘除范围、保留范围、偏离、闸门、内网读数、A 组指纹登记（base 8117bbb25d0a → 新值）；回填此前仍为 `<待提交>` 的 commit 字段（#123 的 [211]/[212]，以及 [210] 若仍未回填）
  - 通过标准：条目号为 [213]、与 master 末条连续，无撞号；若末条不是 [212]，停下报告，不自行改号；PR 描述 = DEVLOG 条目全文
- **节点 5**：S 批准后由我方 squash 合并、删分支
  - 怎么验证：合并 commit message 用 PR 描述全文
  - 通过标准：master 前进到新 SHA；分支 feat/step3 与 worktree dc_s3 已删

## 9. 测试用例

- 本节点不新增测试；以 I-01/I-02 的测试和全量闸门为准
- 回归判据：nightly_gate 配对净退步 <6；参考值为 19171d8 的 GREEN 196/202（仅作对照，不作判据）

## 10. 验收标准

- [ ] 本地闸门全绿（数字表贴 PR）
- [ ] CI 三工作流 success（run id 列出）
- [ ] 内网 nightly_gate GREEN + canary 无阻断
- [ ] 读数注解：摘除后一批 new 的预期读数在 196/202 ± 噪声带（n=202 约 ±6 题，phase75-assess §0）附近；若跌到 190 以下，首先怀疑摘除不干净（I-01 哨兵测试该红而没红），回 I-01 排查，不按能力退化处理
- [ ] DEVLOG 条目号为 [213]（计划书 PR 与 I-07 先合的前提成立）；A 组 code_sha12 在 DEVLOG 登记
- [ ] S 明确批准后 squash 合并

## 11. 交付物

- 合并后的 master SHA
- DEVLOG 条目
- 回归读数（贴本 issue 评论）
- 审查对比表（贴本 issue 评论）
- 节点语义一致性审查表（只读审查 subagent 输出，贴本 issue 评论；格式见 master-plan §6）
