# holdout：发布前的独立题集

这个目录**只放脚本和说明，不放数据、不放题面**。

理由：130 题的 `app/eval/cases*.py` 在仓库里，任何一个改评测的人都能看到题面和标准答案。
这不是安全问题（单机产品，没有攻击者），是**过拟合问题**——写实现的人会不自觉地照着自己
看过的题调 prompt。holdout 用来回答"换一批没见过的题，还成立吗"。

## 规则

1. **holdout 题面与数据不进 git**：不放进 `app/eval/`，不放进 `data/`，不放这个目录。
   本机路径写在 `.holdout_path`（已 gitignore），由跑的人自己维护。
2. **不进 CI**：workflow 里不出现 holdout 路径。CI 只跑 130 题 + 闸门 25 题。
3. **只在发布前人工跑**：跑法、阈值、判定写进发布清单；结果只记"通过/不通过 + 失败题号"，
   不把 holdout 题面贴进 PR、issue 或报告。
4. **失败题的处置**：只允许"改实现"或"删题并说明为什么这题不成立"。**不许**把 holdout 题
   挪进 `app/eval/` 当普通题——那等于把它变成训练集，同时也破坏了"这批题从未见过"的前提。
5. **换题节奏**：每次发布前若 holdout 全部通过，从下一批新题里换掉一半，避免长期重复使用
   同一批题形成事实上的记忆。

## 现状

本目录当前没有脚本：holdout 的流程还没到需要自动化的程度（一次发布跑一次，手工指路径就够）。
等它变成每月都要做的事，再把选样与汇总写成脚本。

不要为了实现一个"完整的 holdout 体系"先在空目录里搭框架——`run_eval.py` 已经支持换数据表，
缺的只是数据本身。

### 但"换数据表"只对单表成立（2026-11-02 核对）

E0 的 H1 要 40 题：单表 18、多表 12、画图 5、陷阱 5（`docs/roadmap/phase7-accuracy.md` §2）。
两种题型的入口不是一回事：

| 题型 | 换数据的办法 | 需要动产品代码吗 |
|---|---|---|
| 单表 18 题 | `--data <csv>` | 不用 |
| 多表 12 题 | **没有 CLI 入口** | 不用，但得自己写 runner |

依据：

- `run_eval.py:97` 的 `--data` help 写的是"替换 **sales** 表的数据文件"，消费点 `run_eval.py:178`
  把它传成 `EvalRunner(args.data)`，而 `app/eval/runner.py:77-78` 只做一件事：
  `self.datasets["sales"] = df_path`。**其它表的路径它碰不到。**
- `DATASETS`（`app/eval/cases.py:357`）是模块级硬编码 dict，`--data` 改不了它。
- 闸门能跑 Olist 8 张表，是因为它**根本不走 `run_eval.py`**：`scripts/gate/run_gate.py:160`
  把题库里的 `q["dataset"]`（一个相对路径，指向目录）直接传给 `analyze()`，
  而 `analyze(dataset, ...)` 的第一个参数本来就是路径（`app/core/service.py:46-47`）。

所以多表留出集有两条路，**选成本低的第二条**：

1. 给 `run_eval.py` 加一个传整个 `datasets` dict 的参数。`EvalRunner.__init__` 已经有
   `datasets: dict | None = None`（`runner.py:72`），技术上只差一个 CLI 参数。
   **但这是新增 CLI 入口，属于产品行为**，按仓库规矩要先开 issue —— 只为跑一次留出集不值得。
2. 照闸门的形状写一个 holdout runner（`scripts/holdout/run_holdout.py`），`q["dataset"]`
   存相对路径，直接传给 `analyze()`。不改 `run_eval.py`、不改 `app/`，A 组指纹零变动。
   等 holdout 真要每月跑一次、或者多表题确认要长期保留，再考虑走第 1 条。
