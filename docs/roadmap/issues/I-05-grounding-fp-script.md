<!-- 草稿 I-05：创建到 GitHub 后把 I-05 替换为真实 #编号，并同步 INDEX.md -->
# I-05 [Wave-1][Independent] eval-script：S3-4 grounding 假阳率量测脚本（只量不改）

**标签**：`wave:1-step3-closeout` `exec:independent` `layer:eval` `priority:P1`

## 依赖与并行编排

- **前置依赖**：无
- **可并行兄弟 Issue**：无
- **后续解锁**：
  - I-06（S3-4：标注假阳率后由 S 定 grounding 拦不拦、拦在哪、证据口径用哪一份）：S 要看 I-05 产出的假阳率表才能定拦不拦（phase75-step3 §5、§7 第 5 条）
- **独占修改边界**：
  - `scripts/eval/grounding_fp.py（新）`
  - `tests/test_grounding_fp.py（新）`

## 1. 标题

[Wave-1][Independent] eval-script：S3-4 grounding 假阳率量测脚本（只量不改）

## 2. 背景

- phase75-step3 §5：新脚本 `scripts/eval/grounding_fp.py`（B 组）读最近一次 202 题报告，用 `report_adapter` 的 `unverified` 条目把未核实数字分成「带单位的计数/金额」「百分比」「派生数」「其他」四类，逐条列题号、数字、结论原句；两种证据口径都算——产品侧含问题原文（`service.py:429`），`eval/consistency.py:10` 不含。
- 边界：grounding 从标黄改拦截之前先量假阳率（7.5b §4 第 3 条）；本步不改 `service.py:428/751`。S 门槛：带单位的计数/金额假阳率 <5% 才考虑拦（§7 第 5 条）。
- 出处汇总：phase75-step3.md §5（:83-87）、§7 第 5 条；phase75-assess §4:93；评测侧 7.5b §4 第 3 条（notes/phase75b-eval-assess.md）

## 3. 范围

**本次只解决**
- 脚本 + 单测 + 一份读数表（四类计数、两种口径差异、待标注清单）

**明确不做（Non-Goals）**
- 不改 `app/` 任何文件（A 组指纹不变）；不做拦截；不替 S 定口径；人工标注不在本节点（由评测侧做、S 抽查不少于 10%，见 I-06）

## 4. 输入

- 最近一次 202 题报告（内网回归产物，由 S 提供路径或文件）
- `report_adapter` 的 unverified 字段

## 5. 输出

- `scripts/eval/grounding_fp.py`
- 读数表（Markdown，贴 issue 评论，供 I-06 中评测侧标注）

## 6. 环境 / 前置条件

- 无需 Key、无需内网；报告文件需 S 提供
- scripts/ 与 tests/ 不进指纹扫描（DEVLOG [195] 指纹段）

## 7. 依赖

无前置、无兄弟 issue、不占内网，随时可开工（[Independent]）；产出解锁 I-06。

## 8. 实施步骤

- **节点 1**：四类分类器 + 双口径证据
  - 怎么验证：单测用构造报告覆盖四类与「问题原文含该数字」的口径差异
  - 通过标准：每类至少 2 个正例 1 个反例通过
- **节点 2**：在真实报告上跑出读数表
  - 怎么验证：脚本退出码 0；表头含题号、数字、结论原句、类别、两种口径是否核实
  - 通过标准：表中条目数 = 报告 unverified 条目总数（逐条不丢）
- **节点 3**：确认零产品改动
  - 怎么验证：`git diff --stat origin/master -- app/` 为空；重算 code_sha12
  - 通过标准：code_sha12 与 master 相同

## 9. 测试用例

- 新增 `tests/test_grounding_fp.py`：`test_classifies_four_kinds`（四类各有正反例）、`test_two_evidence_scopes_differ_when_question_contains_number`、`test_every_unverified_entry_is_listed`（条目数守恒）

## 10. 验收标准

- [ ] 新测试全绿；`app/` 零 diff；code_sha12 不变
- [ ] 读数表贴到本 issue
- [ ] 审查对比表无未解释偏离

## 11. 交付物

- 脚本与测试（独立 PR，S 同意后合并）
- 读数表
- DEVLOG 条目（合并时接号）
- 审查对比表
- 节点语义一致性审查表（只读审查 subagent 输出，贴本 issue 评论；格式见 master-plan §6）
