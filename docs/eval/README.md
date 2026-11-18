# 评测系统入口（v7 稳态，2026-11-18 起）

> **v7 是冻结的尺子。** 题库、gold、判分口径的改动一律先进 `BACKLOG.md` 的「下一轮」，
> 攒够了一次性断代（新基线 + 说明）。不按单题断代，也不在日常跑批里改判据。
>
> **任何读数表必须同时标出 `agent=` 与 `memory_mode=`**（2026-11-17，P1）。缺一个就不许贴：
> react 与 workflow 是两条线，`off` 与 `state` 是两种呈现方式，横着比出来的"涨了/崩了"全是假的。

## 三层，日常只看这三层

| 层 | 什么时候跑 | 跑什么 | 红灯 |
|---|---|---|---|
| **PR** | 每次提交 / PR | `pytest`（`tests.yml`）+ `pr_oracle` 全量 oracle（**不调模型**） | oracle 判错、执行失败、题数不对 |
| **nightly** | **master 每次变更**（只改 `docs/` 或 `*.md` 除外；也可手动） | `agent=workflow` `memory_mode=state` 全量 **202 题，跑 1 次**，对 v7 基线 | ① 通过数比基线低 **6 题及以上**；② v7 三跑全对的题有 **2 题及以上**变错 |
| **canary-drift** | 周一 01:00 UTC（也可手动） | 十条固定探针，比冻结基线 | 算错 / usage 比例移动 >20%；`stale_baseline` = 该重立基线 |

三层之外还有 `release` / `inject` / `rerun` 三个**手动工具**，不在日常：release 归档、
inject 录注入基线、rerun 对历史报告定向复跑。五档对照（`off` / `full` / `react`）也不在日常，
只在断代或有人提问时手动跑。

### nightly 的两条红线是写死的

锚点是 `docs/eval/baseline_v7.json`：v7 的 workflow+state 三跑（194 / 192 / 192，取中位 **192**），
`pass^3` 名单 **188** 道，**模型 `Qwen3.5-397B-A17B` / temp 0**。
`scripts/eval/nightly_gate.py` 只判两件事：

1. 本次通过数 **≤ 186**（192 − 6）；
2. 188 道三跑全对的题里，有 **≥2 道**变错。

**模型名在 workflow 里写死，不从仓库变量读。** 变量指向 `GLM-5.2`（canary 跟的是它 ——
那是「网关默认模型有没有被换」的另一个问题），而 v7 是在 Qwen 上量的。回归门禁要固定仪器：
换模型 = 重立基线，不是改一行 YAML。

「不可比」不等于「红」，退 **2**，动作是修流水线或断代，不是查回归：

- `agent` / `memory_mode` / **`model`** 与基线不同（换了被测对象）；
- 题数不是 202（没跑完，或题集改过）；
- `evalset_sha12` / `judge_sha12` 与基线不同（**尺子动过**）；
- 报告里有 `infra_error`（网关熔断/超时，不是能力读数）。

> 按 v7 的数，规则 1 是规则 2 的超集：中位 192 与 pass^3 188 之间只有 4 题余量，
> 掉 6 题必然已经翻了 2 道稳定题。两条都留着是因为余量会随断代变化 ——
> **别因为规则 2 先响就把规则 1 删了。**

## 红了怎么看

**nightly 红**：看同一次运行的 artifact `eval-nightly-<run_id>` 里的 `nightly_brief.md`
（同时贴在 job summary）。简报固定给三样：

1. 触发了哪条规则、差多少；
2. **翻了的题**：id、分类、题面、gold、本次答案；
3. **提交区间**：上次绿的 nightly 到本次的所有提交（最多 20 条）。

处置：**不自动修，也不改尺子。** 由改产品的一侧回到提交区间里找改动，修完推 master，
nightly 自动重跑；绿了就不用管。同一故障连续失败只留一条 issue。

**PR 红**：oracle 判错只可能是判分链路/执行器坏了，不是模型不会 —— 修代码。
**canary 红**：`drift`（退出码 1）指向权重或网关回包；`stale_baseline`（2）是判分器/数据表
动过，该重立基线；`incomparable`（2）是题单变了。细节见 `CANARY.md`。

## 什么时候断代

只有这三样动过才断代：**题库（题面/增删题）**、**gold**、**判分口径**。

- 日常发现的问题先记 `BACKLOG.md`「下一轮」，**不单题改**；攒够一次（预计一个月至多一次）一起做。
- 断代 = 出新基线文件（`baseline_v7.json` → `baseline_v8.json`，把 `eval.yml` 的
  `--baseline` 指过去）+ 在 `CHANGES.md` 记一条 + 更新 `baselines.json` 与本文的读数表。
- **只有断代才写 `CHANGES.md` 与 `LEDGER.md`。** 日常 nightly 不进台账 —— 报告留在 Actions 工件里。
- 尺子一动，旧基线立刻不可比：nightly 会以退出码 2 明确报「先断代」，不会把差异算成回归。

## 当前读数（v7，2026-11-17，各 3 跑）

`code 996020ad8a04` / `evalset 672b52a3a6b0` / 模型 `Qwen3.5-397B-A17B`（temp 0）。
详细分解见 `v7.md` 与 `v7-report-20261117.md`。

| agent | memory_mode | n | 3 跑均值 | pass^3 | 备注 |
|---|---|---|---|---|---|
| **workflow** | **`state`** | **202** | **95.4%** | **93.1%** | 产品主线，nightly 的对象 |
| workflow | `off` | 195 | 85.1% | 83.6% | 对照：无状态块 |
| workflow | `full` | 202 | 95.7% | 94.6% | 对照：与 state 分不出高低 |
| react | `off` | 195 | 87.4% | 85.1% | 对照 |
| react | `state` | 202 | 93.1% | 90.6% | 对照：贵 2.7 倍 token |

**`FROZEN.md` 先读。** 这些百分比只能做「同一指纹下的回归对比」，不能当准确率对外说。
五条理由（n=1、网关缓存、自造数据、比较器放宽、题面会变）都在那个文件里。

**差多少才算降**：同题集、同一份代码（只差 recall 断言，不进单轮判定路径）跑两批，
`single_off` 94.4% → 92.5%，差 1.9pp。**1.9pp 以内的差当噪声**，这也是 nightly 把阈值定在
6 题（≈3pp）的依据。

**`off` 不等于"没记忆"**：`off` 把历史以对话消息回灌，`state` 折叠成结构化状态块。
85.1% vs 95.4% 量的是两种呈现方式，不是"有记忆 vs 没记忆"。

## 手动工具（不在日常三层）

| 工具 | 干什么 | 入口 |
|---|---|---|
| 25 题闸门 | 外部有效性（真实脏表），人工判定 `human_correct` | `scripts/gate/run_gate.py`、release 档 |
| 出境审计 | prompt 里不该出现的值 | `scripts/egress_audit.py` |
| 合并器 | 补跑后按 case id 覆盖主报告并重算 | `eval_merge.py` |
| 台账 | 全量 outputs → `LEDGER.md` + `runs/` | `eval_ledger.py` |
| 五档对照 | 断代或有疑问时重跑 off/full/react | `run_eval.py --agent X --memory Y --repeat 3` |

## 怎么验这套资产本身

评测代码有自己的单测，改判据 / 改台账 / 改题集之后要跑：

```bash
CODEBUDDY_SAFE_DELETE_BULK_THRESHOLD=100000 pytest tests/ -q   # 2000+ 项 / 约 48 分钟
```

**必须带这个阈值，否则进程会被杀。** 本机（Windows + WorkBuddy）注入了一层 safe-delete
（`cli/vendor/shim/sitecustomize.py`，经 `PYTHONPATH` 自动加载），它把 `shutil.rmtree` 换成
"送回收站"版本，并在**单次工具调用**内删除数超过 50 时 `raise SystemExit(1)`。
`SystemExit` 不是普通异常，pytest 的 teardown 保护（`onerror` / `ignore_errors`）拦不住它 ——
整个进程当场终止。表现是两种：全绿但 `exit=1`，或跑到一半突然没了（SIGTERM/无汇总行）。

实测现场：`count=647, threshold=50, scope="turn", targets=[garbage-*]` →
`SAFE_DELETE_BULK_CONFIRM_REQUIRED`。阈值调到 10 万后，同一次全量
`1907 passed / 0 failed / exit=0`，日志里 0 条 safe-delete（[165]）。

更省事的替代绕法：`env -u CODEBUDDY_TOOL_CALL_ID pytest ...` —— 守卫入口第一行是
`if not BULK_STATE_DIR or not TOOL_CALL_ID: return`，缺一个整段跳过，删除仍进回收站。

另外，同一份代码两次全量曾跑出 1 个 vs 11 个失败，失败项单独复跑全过 ——
**看到 `FAILED` 先单独复跑那一条，复跑过的才算回归**（详见 DEVLOG [164] 第六节）。

**别套 900 秒的 timeout。** `tests/test_eval_cases.py` 一个文件就要 **12 分钟**，其中
`test_oracle_pipeline_all_correct[react]` 350.9s、`[workflow]` 336.7s —— 各跑一遍 202 题的
完整 oracle 管线。套 900 秒去卡它几乎必然撞线，而且撞线时后面的文件还没开始跑，
看起来像"卡死"。只想验改动面时按范围挑：

| 改了什么 | 跑什么 | 规模 |
|---|---|---|
| `baselines.json` / `eval_ledger.py` | `test_ledger.py test_fingerprint.py test_replay.py test_report_adapter.py test_rescore_ledger.py test_tier_check.py` | 115 项 / 14s |
| `baseline_v7.json` / `nightly_gate.py` | `test_nightly_gate.py test_tier_check.py` | 28 项 / 6s |
| `app/eval/comparator.py` | `test_comparator.py` | — |
| 题集 `app/eval/cases*.py` | `test_eval_cases.py` + `test_multi_cases.py test_memory_cases.py` | 12 分钟起 |
| `app/eval/runner.py` | `test_eval_runner.py test_multi_cases.py test_memory_cases.py test_v2d.py` | 约 1 分钟 |

改台账之后**必须复核 `code_sha12` 没变**（`baselines.json` / `LEDGER.md` 不在结果指纹覆盖范围内，
但这一条要验，否则"修个字段"就把刚立的基线搞失效了）：

```bash
python -c "import sys;sys.path.insert(0,'.');from app.eval.fingerprint import code_fingerprint;print(code_fingerprint()['affects_results_sha256'])"
```

## 阶段 7 的留出集

`roadmap/phase7-accuracy.md` 的 H1（40 题新留出集）一件都没做。它的消费方是 A 系列改进，
A 系列没启动，建了也是摆着，而且冻结的题面会随时间失效。整体推迟，见那份文件顶部的状态。
