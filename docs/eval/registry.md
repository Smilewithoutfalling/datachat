# 题集生命周期（EV-D3）

准确率的分母不能只涨不缩。题集一年后会有一半题"早就会了"，它们混在能力集里只会把
准确率抬到 95% 然后对任何改动都不再敏感——那时这个数字就失去诊断价值了。这份注册表
负责把"已经证明会做"的题从能力集移到回归集，把"根本测不出东西"的题退役。

真源是 [`registry.json`](registry.json)，本文件只写规则与理由。**未登记的题一律 active**。

## 状态机

```
candidate ──→ active ──→ graduated
    │            │            │
    └────────────┴────────────┴──→ retired
                                  └──→ active（误退可恢复）
```

| 状态 | 含义 | 计入能力准确率 | 仍跑 |
|---|---|---|---|
| `candidate` | 刚起草、尚未被读数验证的题 | 是 | 是 |
| `active` | 正常题（**默认**，未登记的题都是它） | 是 | 是 |
| `graduated` | 连续 3 个 release 全对，移到回归集 | **否** | 是 |
| `retired` | 测不出东西或长期不稳，退役 | 否 | 是（保留历史可比） |

规则来源：`docs/roadmap/eval-system-spec.md` §EV-D3。

- `graduated` 需要**连续 3 个 release 全对**（`GRADUATE_STREAK=3`）。
- `retired` 两条触发：**连续 2 个 release 都错**（`RETIRE_STREAK=2`），或同一配置
  重复跑的 **`flip_rate > 0.4`**（`FLIP_MAX`）。两条同时满足时**退役优先**——不稳定的题
  不该毕业。
- `candidate` 不能直接毕业：没当过 `active` 就没有连续读数可依据。
- `graduated` / `retired` 都可以退回 `active`（题面改过、误判、数据源修复），
  **必须写理由**，历史全部保留。

## 三条硬约束（`--check` 会拦）

1. 只能沿上面的边移动，每次移动必须有 `reason`，日期不早于上一次；
2. 登记了题库里不存在的 id = 幽灵条目（改名/删题时最容易漏）；
3. 每个非 `active` 的题**必须在本文件里写出理由**——`--check` 会检查它的 id 是否出现在
   本文中。规格要求"每次移动必须写 DEVLOG 与 registry.md 的理由"，DEVLOG 太自由没法机器
   校验，这里能。

## 用法

```bash
# 校验状态机；非法非 0 退出。输出各状态数量
python scripts/eval/registry.py --check

# 读若干份报告（按时间顺序），提议谁该毕业/退役。只打印，不写
python scripts/eval/registry.py --propose docs/eval/eval_react_20261105.json \
    docs/eval/eval_react_20261106.json docs/eval/eval_react_20261107.json

# 同一配置重复跑的稳定性：flip_rate > 0.4 的题提议退役。只打印，不写
python scripts/eval/registry.py --flip outputs/run1.json outputs/run2.json outputs/run3.json

# 人工确认（唯一的写入口）
python scripts/eval/registry.py --set emp_001=graduated --reason "连续 3 次 release 全对（11-05/06/07）"
```

**不要自动毕业。** 脚本只提议，`--set` 是人工动作。一次误判就把题从能力集里永久摘掉，
而分母变了没有任何地方会报错。

### release 怎么算（这条最容易搞错）

`--propose` 里的"release"不是"一份报告"，而是**一个配置版本**：

- 连续几份报告如果 `agent / memory_mode / rewrite / use_dictionary / code_sha12 /
  evalset_sha12` 全同，**折成一个 release**。同一天跑 3 次是 3 次重复测量，不是 3 个版本。
- 一个 release 内跑了多次时，**必须全对才算这轮对**（"release 全对"的字面意思）；
  错一次就是错。
- 折完不足 2 个 release 直接拒绝出提议；要测"同一配置下判定会不会自己翻"，用 `--flip`。
- 报告缺 `fingerprints.code_sha12`（2026-10 之前的老报告）→ **拒绝**。那种报告分不清
  "重复跑"和"换了代码"，折错方向就会把噪声当连续性。
- `agent` 或记忆档不同（例如 off/state/full 三份消融）→ **拒绝**。那是消融实验，
  跨档位的"连续全对"不构成毕业证据。

### ⚠️ 退役提议必须在**目标档位**上算（2026-11-09 实测）

同一个 `FLIP_MAX=0.4`，换档位结果差 8 倍：

| 档位 | 题数 | `flip_rate > 0.4` |
|---|---|---|
| `off` | 195 | **17 题** |
| `state` | 34 | **2 题**（`mul_026`、`mul_012`） |
| `full` | 34 | **2 题**（同上） |

`off` 档多出来的 15 题全是 `mul_*` —— 那一档的多轮题有**已知测量污染**：模型不执行代码、
凭上文口头作答（`executed=False`），判定自然在翻。用它算 flip，等于把「测量方式坏了」
记成「题不稳」，然后退役一批其实能测的题。

**规则**：要退役哪一档的题，就用哪一档的三跑去算，不要跨档位混合。
本仓库的能力读数以 `state` / `full` 为准（`off` 只作记忆消融的下界），退役提议同理。

### 提议出来的这两题，复核后**都不该退役**

`state` / `full` 两档都提议 `mul_012` / `mul_026`。逐跑查了现场：

| 题 | 翻转形态 | 结论 |
|---|---|---|
| `mul_012`<br>2024-03 各品类订单笔数占比 | run1 用 `drop_duplicates()` 全列、不按 status 过滤 → 对；run2/3 用 `subset=['order_id']` **并加了 status 过滤** → 错 | **C-001 的残留**：过滤倾向从 22 次降到偶尔，没清零。这是真实行为不稳，不是题的问题 |
| `mul_026`<br>平均月薪最高部门里绩效 A 几人 | run1/3 先算部门均值→取最高→数 A，答「研发 13 人」→ 对；run2 **跳过第一步**，直接给「各部门 A 人数」表（研发 13 排第一） | **答非所问**：信息在答案里，但用户问的是一个数，它给了一张表。判错合理 |

两题都在暴露**真实的模型行为**（口径漂移 / 不按问句收敛结论），退役等于把症状藏起来。
`--flip` 只提议，判断要人做 —— 这和「不要自动毕业」是同一条纪律的另一半。

配置回滚（a→b→a）算三个 release：中间那版代码是真实发生过的一段。

## 报告里怎么体现

`EvalReport.summary()` 的 `lifecycle` 块：

```json
{"registry_sha12": "...", "counts": {"candidate": 0, "active": 199, "graduated": 2, "retired": 0},
 "uniform": false,
 "capability": {"n": 199, "correct": 141, "correctness_rate": 70.85},
 "regression": {"n": 2, "correct": 2, "correctness_rate": 100.0},
 "retired": {"n": 0, "correct": 0, "correctness_rate": null}}
```

- `overall.correctness_rate` 的分母**永远是跑了的全部题**，不随状态变；要看能力集口径就
  用 `lifecycle.capability.correctness_rate`。
- `uniform=false` 表示这轮的分母与"全量题库"不同 → **不能和历史读数直接比**，
  即使 `fingerprints` 判定可比（注册表不改题面，`evalset_sha12` 不会变；
  `registry_sha12` 只记录、不进 `GATE_KEYS`）。
- `retired` 的题仍在报告里出现（历史可比），只是两份准确率都不算它。

## 当前状态

不在这里写数字（会腐烂）。跑 `python scripts/eval/registry.py --check` 看实时计数。

已毕业/已退役的题及其理由：

<!-- 每加一条状态，在这里补一行：`- id：state —— 理由（日期）`。--check 会校验 id 出现在本文中。 -->
_（暂无）_
