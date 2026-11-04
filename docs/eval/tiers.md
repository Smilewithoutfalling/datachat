# 评测三档：PR / nightly / release

三档回答三个不同的问题，不是同一件事跑三遍：

| 档 | 回答的问题 | 花不花钱 |
|---|---|---|
| PR | 改了这行代码，评测流水线还通不通？ | 不花（不调模型） |
| nightly | 模型与判分器有没有悄悄漂？ | 花（真模型，读 secret） |
| release | 这批数字能不能拿去对外说？ | 花，且要人工签字 |

## 一条贯穿三档的判断：小样本准确率不能当门禁

8 题里翻 1 题就是 12.5pp。EV-C2 算过 MDE：双侧精确 McNemar 要 **6:0 才显著**
（5:0 的 p 是 0.0625）。所以在 8 题这个量级上，任何准确率门槛（"≥7/8 才通过"）
拦住的都是噪声，不是退化。

结论：**三档的红灯只判「能不能跑完、报告结构完不完整」，不判「答对几题」。**
准确率写进报告与 artifact，归 `docs/eval/LEDGER.md` 的趋势和 drift 哨兵（EV-D5）。
这与 EV-C1「`flip_rate > 0.4` 的题不许进 `allowed_fail`」是同一条逻辑：
先证明这个数不是噪声，再拿它当判据。

## 8 题冒烟名单

PR 与 nightly 共用同一份名单。**改名单要改这里并写理由**，否则下一个人只看到 8 个 id。

| 类 | id | 为什么是它 |
|---|---|---|
| 聚合 | `agg_013` | canary 实证（6 跑 60 题次全对）：两级聚合，gold 标量 |
| 聚合 | `ord_007` | canary 实证：去重 + `groupby.size` + 计数，gold 标量 |
| 过滤 | `ord_012` | canary 实证。**避开 `ord_013`**：6 跑里掉过 1 次"算对没交卷"，进冒烟会制造假红 |
| 关联 | `emp_015` | canary 实证。**避开 `ord_017`**：同 `ord_013`，掉过 1 次 |
| 时序 | `ts_010` | canary 实证：`resample('ME')` + `pct_change`，gold 标量 |
| 拒答 | `ord_026` | canary 实证：问物流时长，数据里没有 |
| 歧义 | `ord_027` | 8 条 ambiguity 里 alt 最全的一条（不区分状态 / 折扣前 / 未去重三种都算对）—— 冒烟要验的是容错机制还在工作 |
| 多轮 | `mul_005` | 33 条里变量最少的一条：2 轮、只换 `dept` 一个筛选条件（`expect_turns: inherit:市场`） |

7 类各 1 条 = 7，第 8 条给最大的类（aggregation 43/183）。

**为什么歧义与多轮只给 1 条**：这两类的判定边界本来就在晃（ambiguity 靠 `alt_ground_truths`
容错，multi_turn 依赖记忆编排）。冒烟里放多了，红灯就分不清是 pipeline 坏了还是题自己在抖。

## 三档怎么跑

### PR：`pull_request`

```bash
python run_eval.py --oracle --agent react          # 全量 183 题，不调模型
```

- **红灯条件**：oracle 有任何一题判错或执行失败（`overall.correct < n`）。
- 产物：`outputs/eval_react_oracle_*.json` → 上传 artifact，不进仓库。
- 有 secret 时额外跑 8 题真模型，**只产出、不判红**（理由见上一节）。

### nightly：`schedule`，03:00

```bash
python scripts/gate/run_gate.py --agent react      # 25 闸门题，真模型
python run_eval.py --agent react --case <上面 8 个 id> --out ...
```

- **红灯条件**：闸门报告结构不完整（`n != 25`）、或 8 题报告缺字段。
  闸门的准确率也不判红——它是人工判定（`human_correct`）驱动的，CI 填不了。
- 失败时 `gh issue create`（用 `GITHUB_TOKEN`），标题带 commit 短 sha。
- 产物：两份报告 → artifact，不进仓库。

### release：`workflow_dispatch` + tag

```bash
python run_eval.py --oracle --agent react --case <8 题>      # 先自检判分链路
python run_eval.py --agent react                              # 183 题全量
python scripts/gate/run_gate.py --agent react                  # 25 闸门
python run_eval.py --agent react --canary --repeat 3           # pass^3(10)
```

- **人工确认**：`environment: release` 需要 reviewer 批准才会跑。**但这一步在 YAML 里做不到**——
  必须去仓库 Settings → Environments 建一个叫 `release` 的环境并配 Required reviewers，
  否则 `environment:` 只是给 job 挂个名字，点一下就跑。
- 产物归档到 `docs/eval/`（**只有这一档提交报告**）。job 里只上传 artifact，**不自动 commit**：
  自动 push 到 master 会绕过 PR 流程，与"一个 PR 只解决一个问题"的纪律冲突。要入库就人工挑文件提交。
- **不判红**：`pass^3` 的数字、闸门准确率。看数字的人自己判——这两项都没有可用的小样本门槛。

## 仓库要配的东西

| 类型 | 名字 | 用途 | 缺了会怎样 |
|---|---|---|---|
| Secret | `DATACHAT_LLM_KEY` | 真模型 | PR 档跳过冒烟（正常）；nightly / release **报错退出** |
| Variable | `DATACHAT_LLM_BASE_URL` | 网关 | 走代码里的默认值 |
| Variable | `DATACHAT_LLM_MODEL` | 模型名 | 走代码里的默认值 |
| Environment | `release` + Required reviewers | 人工确认 | release 档自动开跑，没有把关 |
| 权限 | Actions 允许 `issues: write` | nightly 失败开 issue | 开 issue 那步失败（job 本身已经红了） |

## 实测（2026-11-04，本机）

| 项 | 结果 |
|---|---|
| 全量 oracle（183 题，react） | **183/183 判对，183/183 执行成功**，351 秒 |
| 8 题名单 oracle | 8/8，27 秒（含启动） |
| 历史闸门报告走 `--kind gate --expect-n 25` | 通过；当成 eval 报告喂进去会被拒 |
| workflow 静态检查 | `eval.yml` / `drift.yml` / `tests.yml` 三份无 job 级 if 上下文误用、无悬空 step 引用 |

**没验的那一条**：`gh workflow run eval.yml -f tier=pr`。本机没有推仓库，GitHub 上也没建
secret / environment，所以"真的在 Actions 里跑一遍"这件事只有推到远端之后才能验。
`on:` 的四个触发条件、`environment:` 的审批、`gh issue create` 的权限都在这一条里。

## 跳过必须打印原因

GitHub 上 `if:` 跳过的 step 在 UI 里是灰色，和"跑绿了"只差一个眼色。所以每一个可能被跳过的
真模型 step 后面都跟一个反向 `if` 的 echo step，把原因写进日志：

```
::notice::跳过真模型：fork PR 拿不到 secret（GitHub 的安全设计，不绕）
```

## 已知代价

1. **8 题测不出小差异。** 4pp 以下的退化只能靠 canary 的周跑（drift 哨兵）与 release 全量发现。
2. **PR 上不拦模型退化。** 这是有意的：PR 的红灯必须 100% 指向代码问题，否则大家会学会忽略它。
3. **multi_turn 只有 1 条。** 记忆编排的回归在 PR/nightly 上基本看不见，`state` 与 `off` 的
   35pp 差距（LEDGER）只能靠全量发现。
4. **canary 十条里 `ord_013` / `ord_017` 各错过一轮**，release 的 `pass^3` 可能读到 8/10。
   那是真实读数，不是 bug——剔除掉题的两轮能得到漂亮的 10/10，但那是拿最好看的样本当锚点
   （DEVLOG [120] 已经踩过这个）。
