# Issue 草稿总表（INDEX）

> 编号列 I-xx 是草稿编号（与文件名一致）；「GitHub #」列为 2026-11-25 建好的真实 issue，其余各列里的引用已替换为 #编号。追踪 issue：[#128](https://github.com/Smilewithoutfalling/datachat/issues/128)（25 个子 issue 已挂为它的 sub-issue）。本表最初由 issue 文件生成（依赖/解锁两列与文件内「依赖与并行编排」块一致，见 master-plan §10 自检）；重新运行生成器会把这里恢复成 I-xx。

| 编号 | 标题 | Wave | exec | layer | 前置 | 解锁 | 是否回归链 | 出处 | GitHub # |
|---|---|---|---|---|---|---|---|---|---|
| [I-01](I-01-strip-step3-backend.md) | [Wave-1][Serial-Gate] nodes/graph：#127 摘除 S3-3 REPLAN 与 S3-2 产品闸（后端），保留 S3-1 与 code_scope 搬家 | 1 | serial | nodes | — | #134 | 是（第 1 环） | S 11-24 摘除决定（任务书「当前事实」）；PR #127 描述；phase75-step3.md §1–§4、§7 第 1 条 | [#129](https://github.com/Smilewithoutfalling/datachat/issues/129) |
| [I-02](I-02-strip-step3-web.md) | [Wave-1][Parallel-A] web：#127 摘除「重新规划」两版计划显示 | 1 | parallel | web | — | #134 | 否 | S 11-24 摘除决定（前端两版计划）；PR #127 描述「前端」与 vitest 段 | [#130](https://github.com/Smilewithoutfalling/datachat/issues/130) |
| [I-03](I-03-step3-regress-merge.md) | [Wave-1][Serial-Gate] eval/regress：#127 摘除后重跑本地闸门 + 内网回归一批 new（nightly_gate 判读 + canary），通过后 squash 合并 | 1 | serial | eval | #129、#130、#131、#133 | #135、#136、#137、#141 | 是（第 2 环） | 任务书「当前事实」第 2 条（摘完重跑本地闸门，内网只跑一批 new）；phase75-assess §3:71；HANDOVER §3、§7；phase75-assess §5:98 | [#134](https://github.com/Smilewithoutfalling/datachat/issues/134) |
| [I-04](I-04-step3-backlog-archive.md) | [Wave-1][Parallel-B] docs：摘下的 S3-3 与 S3-2 产品闸、react 注入挂 BACKLOG，存档 mul_005#2 快照作验收材料，更新第 3 步方案状态 | 1 | parallel | docs | — | #134、#140 | 否 | S 11-24 决定（摘下的挂 BACKLOG、mul_005#2 快照存档、豁免日后要覆盖同列 ==↔isin）；S 11-25 裁定（快照入库路径、来源；react 注入挂账并入本 issue）；docs/eval/BACKLOG.md:574-579 阶段 7.5 分区；phase75-step3.md §7 第 4 条、§8 | [#131](https://github.com/Smilewithoutfalling/datachat/issues/131) |
| [I-05](I-05-grounding-fp-script.md) | [Wave-1][Independent] eval-script：S3-4 grounding 假阳率量测脚本（只量不改） | 1 | independent | eval | — | #135 | 否 | phase75-step3.md §5（:83-87）、§7 第 5 条；phase75-assess §4:93；评测侧 7.5b §4 第 3 条（notes/phase75b-eval-assess.md） | [#132](https://github.com/Smilewithoutfalling/datachat/issues/132) |
| [I-06](I-06-grounding-fp-decision.md) | [Wave-1][Decision] S3-4：标注假阳率后由 S 定 grounding 拦不拦、拦在哪、证据口径用哪一份 | 1 | decision | eval | #134、#132 | — | 否 | phase75-step3.md §5（:85-87）、§7 第 5 条；phase75-assess §4:93 | [#135](https://github.com/Smilewithoutfalling/datachat/issues/135) |
| [I-07](I-07-pr123-devlog-renumber.md) | [Wave-1][External] 评测侧 #123：rebase 让号到 [211]/[212]，先于 #127 合并 | 1 | external | eval | — | #134 | 否 | PR #123 评论（11-24 13:38 改用 [209]/[210]）；notes/progress-history.md「11-24 #126 合并」；DEVLOG:11400；S 11-25 裁定（计划书 PR 占 [210]，#123 改 [211]/[212]） | [#133](https://github.com/Smilewithoutfalling/datachat/issues/133) |
| [I-08](I-08-step4-eval-downgrade.md) | [Wave-2][External] 评测侧第 4 步：回归范围表落地（含子集入口）、指纹降为报告元数据、LEDGER 机读 | 2 | external | eval | #134 | #137 | 是（第 3 环） | phase75-assess.md §2 第 4 行（:42）、§3（:65-79）、§5（:95-99）；phase75-step3.md §8；任务书「顺序已定」 | [#136](https://github.com/Smilewithoutfalling/datachat/issues/136) |
| [I-09](I-09-baseline-v8.md) | [Wave-2][External] 评测侧 v8 基线：内网空闲时连跑三次 202 题，取中位数重立 | 2 | external | eval | #134、#136 | #141 | 是（第 4 环） | phase75-assess.md §6:106；phase75-step3.md §8；decisions-pending D2（:39，单跑不立基线）；任务书「顺序已定」 | [#137](https://github.com/Smilewithoutfalling/datachat/issues/137) |
| [I-10](I-10-issue119-dump-usage.md) | [Wave-2][External] 评测侧 #119 收尾：canary 增加 `--dump-usage`（原始 usage 回包可查） | 2 | external | eval | — | — | 否 | issue #119「建议（评测侧）」；PR #123 描述「待办」第 1 条；任务书「#119 属评测侧（canary --dump-usage）」 | [#138](https://github.com/Smilewithoutfalling/datachat/issues/138) |
| [I-11](I-11-phase7-s1-decisions.md) | [Wave-3][Decision] phase7 §1 待定四条：①评测模型/网关固定 ②每轮预算 ③留出集出题分工 ⑤数据许可 | 3 | decision | eval | — | — | 否 | phase7-accuracy.md §1（:19-27）；decisions-pending D1（:38，④已解决）；phase75-assess §6:107；B4 挂账：DEVLOG [199]（:11021）、[196]（:10926） | [#139](https://github.com/Smilewithoutfalling/datachat/issues/139) |
| [I-12](I-12-n9-egress-contract.md) | [Wave-3][Decision] BACKLOG N9（mul_005）：放宽出境合同，还是让 reviewer 在沙箱里查 unique() | 3 | decision | tools | #131 | — | 否 | decisions-pending-1120.md :40；BACKLOG N9（docs/eval/BACKLOG.md:572）；phase7-a2a3.md「出境合同」；phase75-step3.md §6；phase75-assess §6:105 | [#140](https://github.com/Smilewithoutfalling/datachat/issues/140) |
| [I-13](I-13-scipy-probe-batch.md) | [Wave-3][External] 评测侧 scipy probe 批：t 检验、卡方、相关显著性 3 题单独跑（不入库、不断代） | 3 | external | eval | #137、#134 | #142 | 是（第 5 环） | decisions-pending B3（:22）；phase75-scipy.md §3④ 及 11-20 补充（:29-30） | [#141](https://github.com/Smilewithoutfalling/datachat/issues/141) |
| [I-14](I-14-scipy-capability-note.md) | [Wave-3][Decision] B3：codegen 是否加 scipy.stats 能力说明（看 probe 批读数后定） | 3 | decision | nodes | #141 | — | 否 | decisions-pending B3（:22）；phase75-scipy.md §3④ 补充（:30）、§4（:32-36） | [#142](https://github.com/Smilewithoutfalling/datachat/issues/142) |
| [I-15](I-15-live-replay-key.md) | [Wave-3][Decision] 第 1 步 replay live 模式：S 提供真模型 Key，还是转给评测侧 | 3 | decision | eval | — | — | 否 | decisions-pending-1120.md :42 | [#143](https://github.com/Smilewithoutfalling/datachat/issues/143) |
| [I-16](I-16-u4-upload-landing.md) | [Wave-3][Decision] U4：上传后是否直接落到空态卡（现为进数据集页） | 3 | decision | web | — | — | 否 | DEVLOG [204]（:11199）；phase76-ui.md §2 U4（:43） | [#144](https://github.com/Smilewithoutfalling/datachat/issues/144) |
| [I-17](I-17-intranet-self-hosted-runner.md) | [Wave-3][Decision] 是否上内网自托管 runner（让真模型评测有自动门禁） | 3 | decision | eval | — | — | 否 | DEVLOG [187]「常驻纪律」与「下一轮（不做）」（:10585-10598）；DEVLOG [194]「明确不做」（CI 真模型评测：公网 runner 够不着内网网关） | [#145](https://github.com/Smilewithoutfalling/datachat/issues/145) |
| [I-18](I-18-repo-license.md) | [Wave-4][Decision] 仓库许可证：MIT / Apache-2.0 / 不开源 | 4 | decision | docs | — | #150、#151 | 否 | phase6-desktop.md §1 第 6 条（:31）、:11；任务书「推迟到对外分发前」 | [#146](https://github.com/Smilewithoutfalling/datachat/issues/146) |
| [I-19](I-19-dir-separation-decision.md) | [Wave-4][Decision] 安装目录与数据目录分离：改安装目录，还是改数据目录（需迁移） | 4 | decision | desktop | — | #148 | 否 | phase6-desktop.md :27、:75；notes/progress-history.md「安装目录」条（要求在自动更新 #149 之前处理）；S 11-25 裁定（安装目录写法由本 issue 核实） | [#147](https://github.com/Smilewithoutfalling/datachat/issues/147) |
| [I-20](I-20-dir-separation-impl.md) | [Wave-4][Serial-Gate] desktop：按 #147 的选择分离安装目录与数据目录 | 4 | serial | desktop | #147 | #149 | 否 | phase6-desktop.md :75、§1 第 2、4 条（:23-27） | [#148](https://github.com/Smilewithoutfalling/datachat/issues/148) |
| [I-21](I-21-auto-update.md) | [Wave-4][Serial-Gate] desktop：自动更新 + release 工作流 | 4 | serial | desktop | #148 | #150 | 否 | phase6-desktop.md §4（:77-84）、:11 | [#149](https://github.com/Smilewithoutfalling/datachat/issues/149) |
| [I-22](I-22-license-audit.md) | [Wave-4][Serial-Gate] desktop/ci：依赖许可证审计 + THIRD_PARTY_NOTICES + 设置页「关于」 | 4 | serial | desktop | #149、#146 | — | 否 | phase6-desktop.md §5（:86-90）、§1 第 6 条 | [#150](https://github.com/Smilewithoutfalling/datachat/issues/150) |
| [I-23](I-23-code-signing.md) | [Wave-4][External] 代码签名：由有实名主体的一方申请证书并配置 CI Secret | 4 | external | desktop | #146 | — | 否 | phase6-desktop.md §6（:92-106）；HANDOVER §5 第 5 条 | [#151](https://github.com/Smilewithoutfalling/datachat/issues/151) |
| [I-24](I-24-team-edition-rbac.md) | [Wave-5][Decision] 团队版 / 多用户 / RBAC 是否另开方案、何时开 | 5 | decision | server | — | — | 否 | decisions-pending-1120.md :41；phase75-assess.md §1（:27-33）、§6:108 | [#152](https://github.com/Smilewithoutfalling/datachat/issues/152) |
| [I-25](I-25-web-edition.md) | [Wave-5][Decision] 阶段 8 Web 版：何时另定方案 | 5 | decision | server | — | — | 否 | HANDOVER §11（阶段 8 Web 上线：另定）；plan.md:25、:55；任务书「后续还有 Web 版」 | [#153](https://github.com/Smilewithoutfalling/datachat/issues/153) |

## 计数

| Wave | 数量 |
|---|---|
| Wave-1（wave:1-step3-closeout） | 7 |
| Wave-2（wave:2-eval-downgrade） | 3 |
| Wave-3（wave:3-decisions） | 7 |
| Wave-4（wave:4-pre-distribution） | 6 |
| Wave-5（wave:5-next-form） | 2 |

| exec | 数量 |
|---|---|
| serial（串行闸） | 5 |
| parallel（并行） | 2 |
| independent（独立） | 1 |
| decision（决策） | 11 |
| external（外部） | 6 |

| Wave \ exec | serial | parallel | independent | decision | external |
|---|---|---|---|---|---|
| Wave-1 | 2 | 2 | 1 | 1 | 1 |
| Wave-2 | 0 | 0 | 0 | 0 | 3 |
| Wave-3 | 0 | 0 | 0 | 6 | 1 |
| Wave-4 | 3 | 0 | 0 | 2 | 1 |
| Wave-5 | 0 | 0 | 0 | 2 | 0 |

合计 25 个。
