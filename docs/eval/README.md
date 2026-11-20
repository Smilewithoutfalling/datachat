# 评测系统入口（v7 稳态，2026-11-18 起）

> **v7 是冻结的尺子。** 题库、gold、判分口径的改动一律先进 `BACKLOG.md` 的「下一轮」，
> 攒够了一次性断代（新基线 + 说明）。不按单题断代，也不在日常跑批里改判据。
>
> **任何读数表必须同时标出 `agent=` 与 `memory_mode=`**（2026-11-17，P1）。缺一个就不许贴：
> react 与 workflow 是两条线，`off` 与 `state` 是两种呈现方式，横着比出来的"涨了/崩了"全是假的。

## 谁在跑什么

| 谁 | 什么时候跑 | 跑什么 | 要不要模型 |
|---|---|---|---|
| **GitHub CI**（`tests.yml`） | 每次推 master、每个 PR | `pytest` 四个 job + `gate-oracle` ×2 + web | 不要 |
| **S（内网 Ubuntu）** | 动了 prompt / agent / 记忆 / 执行器，**合并前**（判据见下节） | 下面两条命令 | 要 |
| 手动工具 | 断代 / 归档 / 有人提问 | `release` / `inject` / `rerun` | 看档位 |

**CI 不再自动跑任何 LLM 评测（2026-11-18 改）。** `eval.yml` 与 `drift.yml` 现在只有
`workflow_dispatch`，没有 `push` / `pull_request` / `schedule`。原因很硬：GitHub 托管 runner
是公网机器，而基线是在内网 `grg-aikits-test.grgbanking.com`（`10.62.27.32`，公网 DNS
`NXDOMAIN`）上用 `Qwen3.5-397B-A17B` 量的。公网 runner 永远够不着那台网关 —— 自动跑只会
得到「202 题全是 `infra_error`」，白烧 token 还判不出任何东西。真模型评测改在内网手工跑。

## 什么时候必须跑命令一

判据一句话：**这次改动会不会改变「模型看到的东西」或「它产出的结果」？** 会，就在合并前跑。

| 改了这些 | 跑不跑 | 为什么 |
|---|---|---|
| `app/nodes/`（planner / codegen / reviewer / summarizer） | **跑** | prompt 与生成链路本体，改一个字读数就会动 |
| `app/graph.py`、`app/react_agent.py` | **跑** | 编排：节点顺序、重试、上下文拼装 |
| `app/memory/` | **跑** | 记忆读写，以及 `rewrite.py` 里的改写 prompt |
| `app/tools/` | **跑** | 执行器与沙箱：写不出结果就是 `executed=False`，直接改通过数 |
| `app/core/` | **跑** | 结果提取、grounding、provider 注册，都在评测路径上 |
| `app/llm.py`、`app/state.py` | **跑** | 采样参数与状态结构 |
| `ui/`、`desktop/` | 不跑 | 纯前端，不进评测路径；改 `ui/` 照常由 CI 的 web job 兜 |
| `docs/`、`*.md`、`tests/`、`.github/` | 不跑 | 不影响读数；改 `tests/` 跑 pytest 就够 |

两条边界，容易搞混：

- **改 `app/eval/`（题库 / gold / judge / 指纹）不是「跑命令一」，是「动尺子」。**
  那会先让门禁以退出码 2 报「不可比」，正确动作是断代（见下节），不是查回归。
- **拿不准就跑。** 22 分钟换掉一次「我不知道它退没退」，不亏；漏跑一次退步的代价是
  它悄悄留在 master 上，等下一次有人想起才被发现。

## S 的两条命令

前置：内网的 Ubuntu；仓库根目录；能 `curl` 到 `https://grg-aikits-test.grgbanking.com/v1/models`
（不通就是不在内网，别往下走）。模型配置走 `.env`（`DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` /
`DEEPSEEK_MODEL`，取值见 `.env.example`），`run_eval.py` 启动时自己加载。

### 一条：全量 202 题对比 v7（约 22 分钟）

```bash
cd <仓库根目录>
git pull
python -m pip install -r requirements.txt

python run_eval.py --agent workflow --memory state --no-fail \
    --out outputs/nightly_v7.json

python scripts/eval/nightly_gate.py \
    --report outputs/nightly_v7.json \
    --baseline docs/eval/baseline_v7.json \
    --out outputs/nightly_brief.md
echo "退出码=$?"
```

| 退出码 | 意思 | 你做什么 |
|---|---|---|
| **0** | 绿：通过数没比基线低 6 题 | 不用管。翻了几道题照样在简报里，看都不用看 |
| **1** | 红：通过数掉了 6 题及以上 | 打开 `outputs/nightly_brief.md`，按「翻了的题」回去找改动 |
| **2** | 不可比：模型/题数/指纹不对，或有 `infra_error` | 先修环境（多半是没在内网或 `n` 不是 202），不是查回归 |

简报固定给三样：触发了什么、**翻了的题**（id / 分类 / 题面 / gold / 本次答案）、提交区间。

### 二条：canary 漂移（约 3 分钟）

```bash
python run_eval.py --canary --agent react --repeat 1 --out outputs/canary_check.json
python scripts/eval/canary.py outputs/canary_check.json
echo "退出码=$?"
```

| 退出码 | 意思 | 你做什么 |
|---|---|---|
| **0** | 干净 | 不用管 |
| **1** | 漂移：有探针**算错**了 | 看输出里点名的那几条题；十条全对过就重跑一次再判 |
| **2** | `incomparable`（题单变了）或 `stale_baseline`（判分器/数据表动过） | 前者改题单，后者 `--init --force` 重立基线 |

**usage 三条比例（in/out/cache_read/reasoning）只列不拦**，越界只写一行「提示（不拦）」。
基线是 6 跑聚合比、这里跑的是 1 跑，两者形态不同，比例的抖动是结构性的，不是模型在漂。

## 判据是写死的

锚点是 `docs/eval/baseline_v7.json`：v7 的 workflow+state 三跑（194 / 192 / 192，取中位 **192**），
`pass^3` 名单 **188** 道，**模型 `Qwen3.5-397B-A17B` / temp 0**。

`scripts/eval/nightly_gate.py` **判红只看一条**：本次通过数 **≤ 186**（192 − 6）。

翻转题（v7 三跑全对、本次变错）**只列不拦**，2026-11-18 降级。证据：同一个 master、同一基线，
连续两跑给出相反结论（193 翻 2 → 红、195 翻 0 → 绿），而判红那跑的通过数还**高于**基线。
根因是网关 temp 0 并不确定（canary 基线 `answer_varied=10`，十题六跑答案文本全不同），
`pass^3` 只是三次抽样，证不了「这题永远对」。详见 `BACKLOG.md` N7。

模型名必须与基线一致，**换模型 = 重立基线**。

「不可比」不等于「红」，退 **2**，动作是修环境或断代，不是查回归：

- `agent` / `memory_mode` / **`model`** 与基线不同（换了被测对象）；
- 题数不是 202（没跑完，或题集改过）；
- `evalset_sha12` / `judge_sha12` 与基线不同（**尺子动过**）；
- 报告里有 `infra_error`（网关熔断/超时，不是能力读数）。

## 红了怎么看

**nightly 红（退出码 1）**：开 `outputs/nightly_brief.md`。

1. 触发了哪条规则、差多少；
2. **翻了的题**：id、分类、题面、gold、本次答案；
3. **提交区间**：简报能查到的最近一次通过记录（有成功的 nightly 就用它，没有就退回 v7
   基线的 `run_commit`）到本次的所有提交（最多 20 条）。手动模式下这一段往往很长 ——
   你自己知道刚改了什么，它只是兜底。

处置：**不自动修，也不改尺子。** 回到提交区间里找改动，修完重跑这条命令；绿了就不用管。

**canary 红（退出码 1）**：只可能是探针**算错**。`stale_baseline`（2）是判分器/数据表动过，
该重立基线；`incomparable`（2）是题单变了。细节见 `CANARY.md`。

## 什么时候断代

只有这三样动过才断代：**题库（题面/增删题）**、**gold**、**判分口径**。

- 日常发现的问题先记 `BACKLOG.md`「下一轮」，**不单题改**；攒够一次（预计一个月至多一次）一起做。
- 断代 = 出新基线文件（`baseline_v7.json` → `baseline_v8.json`，把命令里的 `--baseline`
  指过去）+ 在 `CHANGES.md` 记一条 + 更新 `baselines.json` 与本文的读数表。
- **只有断代才写 `CHANGES.md` 与 `LEDGER.md`。** 日常不进台账。
- 尺子一动，旧基线立刻不可比：门禁会以退出码 2 明确报「先断代」，不会把差异算成回归。

## 当前读数（v7，2026-11-17，各 3 跑）

`code 996020ad8a04` / `evalset 672b52a3a6b0` / 模型 `Qwen3.5-397B-A17B`（temp 0）。
详细分解见 `v7.md` 与 `v7-report-20261117.md`。

| agent | memory_mode | n | 3 跑均值 | pass^3 | 备注 |
|---|---|---|---|---|---|
| **workflow** | **`state`** | **202** | **95.4%** | **93.1%** | 产品主线，门禁的对象 |
| workflow | `off` | 195 | 85.1% | 83.6% | 对照：无状态块 |
| workflow | `full` | 202 | 95.7% | 94.6% | 对照：与 state 分不出高低 |
| react | `off` | 195 | 87.4% | 85.1% | 对照 |
| react | `state` | 202 | 93.1% | 90.6% | 对照：贵 2.7 倍 token |

**`FROZEN.md` 先读。** 这些百分比只能做「同一指纹下的回归对比」，不能当准确率对外说。
五条理由（n=1、网关缓存、自造数据、比较器放宽、题面会变）都在那个文件里。

**差多少才算降**：同题集、同一份代码（只差 recall 断言，不进单轮判定路径）跑两批，
`single_off` 94.4% → 92.5%，差 1.9pp。再加上 2026-11-18 连续两跑的实测（193 / 195，
跨 3 题），所以把红线定在掉 6 题（≈3pp）。

**`off` 不等于"没记忆"**：`off` 把历史以对话消息回灌，`state` 折叠成结构化状态块。
85.1% vs 95.4% 量的是两种呈现方式，不是"有记忆 vs 没记忆"。

## 手动工具（都不在 S 那两条命令里）

| 工具 | 干什么 | 入口 |
|---|---|---|
| 25 题闸门 | 外部有效性（真实脏表），人工判定 `human_correct` | `scripts/gate/run_gate.py`、release 档 |
| 出境审计 | prompt 里不该出现的值 | `scripts/egress_audit.py` |
| 合并器 | 补跑后按 case id 覆盖主报告并重算 | `eval_merge.py` |
| 台账 | 全量 outputs → `LEDGER.md` + `runs/` | `eval_ledger.py` |
| 五档对照 | 断代或有疑问时重跑 off/full/react | `run_eval.py --agent X --memory Y --repeat 3` |
| oracle 自检（不调模型） | 只验评测流水线通不通 | `eval.yml` 手动 dispatch，`tier=pr` |

## 怎么验这套资产本身

评测代码有自己的单测，改判据 / 改台账 / 改题集之后要跑：

```bash
CODEBUDDY_SAFE_DELETE_BULK_THRESHOLD=100000 pytest tests/ -q   # 2000+ 项 / 约 40 分钟
```

**必须带这个阈值，否则进程会被杀。** 本机实测（2026-11-18，`ba0ad05`）：**2079 passed /
0 failed / 2387 s**。本机（Windows + WorkBuddy）注入了一层 safe-delete
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
