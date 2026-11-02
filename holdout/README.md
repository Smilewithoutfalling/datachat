# holdout：H1 留出集题库

这是 DataChat 发布前用的**独立题集**——40 道题、两份外部数据、一套"先算答案再跑模型"的流程。
目的是回答一个问题：**换一批没见过的数据，这套实现还成立吗。**

与 `app/eval/cases*.py` 里的 130 道自造题分开：那 130 道在仓库里、谁都能改；这一批刻意独立，
避免写实现的人照着题调 prompt。

## 目录

| 文件 | 内容 |
|---|---|
| `questions.json` | 40 道题面，不含标准答案 |
| `answers_spec.json` | 题号 → 参考解法（`code` 跑脏化表、`raw_code` 跑原始表） |
| `answers.json` | 由 `verify_holdout.py --write` 生成，含 `questions_sha256` 冻结哈希 |

数据不在仓库里（约 98 MB）。两种拿法：

1. **下载 Release 附件** `holdout-data.zip`，解压到本目录，得到 `data/`；
2. **自己构建**（需要能访问 UCI 和 Inside Airbnb）：

       python scripts/holdout/build_holdout_data.py --out <本目录>
       python scripts/holdout/build_holdout_multi.py --out <本目录>

   两个脚本会把原始包缓存到 `data/_cache/` —— `verify_holdout.py` 的 `raw_code` 核对要用它。

## 数据

| 数据集 | 逻辑名 | 规模 | 来源与许可 |
|---|---|---|---|
| 北京多站点空气质量 | `air` | 420,768 行 × 15 列，12 站 × 2013-03 ~ 2017-02 | UCI ML Repo 501，**CC BY 4.0** |
| 空气质量（报表导出变体） | `air_report` | 同上，两级表头 + 末行合计 | 由 `build_holdout_data.py` 派生 |
| Inside Airbnb 四表 | `rental` | 房源 500 / 可订日历 182,500 / 评论 30,251 / 社区 15 | Inside Airbnb，**CC BY 4.0 + CC0** |

脏化只改呈现、不改数值：中文列名、GB18030 编码、CRLF、缺失写成 `未登记`、价格带 `$` 和千分位。
原始数据在 `data/_cache/` 里原样保留，这是双表核对的基准。

## 环境

- Python 3.11+（实测 3.11.17）
- pandas（实测 3.0.6；**pandas 2.x 的部分行为不同，见文末"坑"**）

## 跑

    # 1. 算标准答案（不写文件，只核对）
    python scripts/holdout/verify_holdout.py --dir holdout

    # 2. 核对通过后写出 answers.json
    python scripts/holdout/verify_holdout.py --dir holdout --write

    # 3. 离线自检：用标准答案代替模型输出，验证流水线与数据可解
    python scripts/holdout/run_holdout.py --dir holdout --oracle

    # 4. 正式跑（要 API Key）
    python scripts/holdout/run_holdout.py --dir holdout --agent react --repeat 3

## 出下一批题：照这个顺序做

**先摸数据，再定题。** 反过来做会出出"看着在考聚合、其实答案退化"的题——比如问"某表评论数和评论表条数差多少"，
两边本来就恒等，差永远是 0。本库第一版就废过一道这样的题。

1. **数据画像**：每列的 `nunique` / 缺失数 / 分布、时间覆盖是否完整、两张表的外键有没有孤儿。
2. **挑题**：一题一个口径。写下来之后先问自己"如果我用最直白的 `groupby().mean()` 会得到什么"——
   如果那个答案也是"对的"，这题就没有区分度，换掉。
3. **写 `questions.json`**：`id` 接着编（`h1_19` 起 / `c06` 起 / `t06` 起），字段照现有条目抄：
   `group`（single/multi/chart/trap）、`category`、`dataset`、`gold_kind`、`question`，
   需要时加 `ordered` / `percent_equiv` / `expect_refusal` / `has_chart`。
4. **写 `answers_spec.json`**：每题三段
   - `code`：在**脏化表**上算，`result = ...`
   - `raw_code`：同一件事在**原始表**上再算一遍（列名不同，逼你分别写）
   - `note`：口径说明，跑完会自动把算出的值追加进去
   - 可选 `expect`：你预期的答案，对不上会当场报错
5. **核对**：`verify_holdout.py`。`code` 与 `raw_code` 不一致就拒绝写 `answers.json`——
   这道关救过一次"报表合计行让均值正好翻倍"的错答案。
6. **自检**：`run_holdout.py --oracle` 必须全过。

## 硬规则

- **不改已有的 40 题。** 冻结后改题 = 换了一套卷子，历史基线全部不可比。题出错就作废那一题、记进 DEVLOG，不在原题上改。
- **答案必须唯一。** 有第二种合理解释，就把口径写进题面（"占**有数值的**记录"、"只算完整年份"），
  或者把它做成 `expect_refusal` / 用 `alt_ground_truths` 收编。
- **一题只考一个口径。** 两个坑叠在一起，判错时说不清是哪一个。
- **每道新题都要有 `raw_code`。** 只算脏化表那一遍，脏化本身改错了数值也发现不了。
- **脏化不许改变答案口径。** 例如把 NaN 变成 `未登记` 会让 `value_counts()` 多出一项——
  要么题面写"不含缺失记录"，要么别用会受影响的写法。

## 已经踩过的坑

| 坑 | 表现 | 正确做法 |
|---|---|---|
| 缺失不是 NaN | `isna()` 返回 0，`mean()` 报 `Cannot perform reduction with string dtype` | `pd.to_numeric(..., errors='coerce')` |
| pandas 3 的时间解析 | `pd.to_datetime('2013/3/1 0')` 直接 `DateParseError` | 显式 `format='%Y/%m/%d %H'` |
| 字符串排序 | `df['监测时间'].max()` 给 `'2017/2/9 9'`，真值是 `2017-02-28 23:00` | 先转 datetime 再取 |
| 报表合计行 | 不剔除末行合计，均值算出来正好翻倍 | 按 `序号 == '合计'` 剔掉 |
| 两级表头 | 默认 `header=0` 得到 `Unnamed: 3` 这样的列名 | 第一行做列名 + `iloc[1:]` |
| 样本不完整 | 2017 只有 59 天却年均最高，`idxmax()` 会选它 | 先判覆盖（完整年 = 有 365/366 天）再比 |
| `--oracle` 下的画图题 | 5 道 `has_chart` 一定报缺图 | 伪失败：标准答案只算数不画图，真出图率要 `--agent` 跑 |

## 现有 40 题

| 组 | 题号 | 说明 |
|---|---|---|
| 单表 18 | `h1_01`–`h1_18` | 空气质量；聚合/过滤/时序/关联/排序各若干，含 1 道应拒答 |
| 多表 12 | `m01`–`m12` | 民宿四表；含跨表 join、集合差、日期解析、1 道应拒答 |
| 画图 5 | `c01`–`c05` | `has_chart=true`，判分仍比 `result`，出图另由报告检查 |
| 陷阱 5 | `t01`–`t05` | 未登记、字符串 max、两级表头+合计行、完整年、双列同时缺失 |

冻结哈希：`questions_sha256 = a98a43b75968`（2026-11-02）。

## 下一批（待出）

- **数量**：≥ 20 题，够轮换掉一半。
- **题面不得与上表 40 题重复**——重复题不计入新批次，也不该靠改几个字绕过。
- **优先换数据源**。目前 40 题只用了两套数据：单表全是空气质量、多表全是民宿。
  在同一批数据上再出一套题，测出来的还是"对这两套数据的熟悉度"。新数据源要许可证干净
  （CC BY / CC0 / 公有领域），并在 PR 或说明里核对清楚。
- 沿用现有 4 个 `group` 的配比（单表 : 多表 : 画图 : 陷阱 ≈ 18 : 12 : 5 : 5），
  但不必逐组凑满。
- 新题只写进 `questions.json` / `answers_spec.json`，**不要改已有 40 题**。

## 公开的代价：这批题不再是盲测题

题面和参考解法进了公开仓库，任何模型都可能见过。所以：

- 这 40 题从此只当**格式样板 + 基线对照**，不再算"没见过的题"。
- 新出的题**不要提交到这个仓库**。本地存一份，冻结哈希记进 DEVLOG 就够了。
- 如果确实需要公开新题（比如做外部协作），就得承认那一批也失去了盲测属性，
  另外再留一批不公开的。

