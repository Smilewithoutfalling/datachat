# 扰动评测（EV-B6）：同一份逻辑数据换形态

目标不是加 20 道新题，是测**鲁棒性**：真实世界的 csv 长着合并表头、合计行、千分位、
紧凑日期，评测语料的四张表全是干净的 —— 干净表上的高分测不出"换个导出格式就崩"。

## 9 种变体（`variant_kind`）

| kind | 变换 | 期望 |
|---|---|---|
| `merged_header` | 首行是横跨全表的标题行 | 表头识别 |
| `two_row_header` | 第 1 行大类、第 2 行子列，第 3 行起数据 | 表头识别 |
| `total_row` | 末尾插一行「合计」 | 剔除汇总行 |
| `thousand_sep` | 数值列加千分位字符串（带引号写 csv） | 类型转换 |
| `percent_str` | 数值列写成 `12.3%` | 类型转换 |
| `date_compact` | `2024-01-05` → `20240105` | 日期解析 |
| `dup_columns` | 两列同名（pandas 自动加 `.1`） | 列名消歧 |
| `empty_col` | 插一列全空 | 空列处理 |
| `footer_note` | 末尾两行备注（含逗号） | 尾部噪声 |

## 生成

```bash
python scripts/perturb.py --case agg_001 --kind total_row --out outputs/perturb/
# 产出 agg_001.total_row.dirty.csv（agent 看）+ .clean.csv（gold 算），
# stdout 打一条 EvalCase 片段
```

约束：

- **clean 与 dirty 必须语义等价**。`total_row` 的 clean 就是去掉合计行的原表 ——
  期望值变了就不是测扰动，是测新题。
- **千分位 / 备注行带引号写 csv**，否则逗号破坏结构或被 pandas 读成数字，测不到。
- **多表题不支持**（biz 目录）：表头语义属于表本身，换形态会破坏 `dfs['表名']` 契约。
- 变换器只吃纯文本（csv 模块），**不用 pandas 读回写** —— pandas 会自作主张改类型。

## 衰减曲线

```bash
python scripts/eval/decay.py docs/eval/<报告>.json [...]
```

`variant_kind` 非空的行按 kind 分组算 pass_rate，基线取同报告里被指向的 `variant_of`
原题，输出 `decay_pp`。规格的完整实验是 **20 条基线题 × 4 种最相关变体
（total_row / thousand_sep / date_compact / two_row_header）= 80 次真模型运行**；
80 次成本不低，先 5 条冒烟再放量。

## 进题库的题

`cases_extra.py::PERTURB_CASES`（目前 1 条 `pert_001`，total_row 变体的 agg_001）。
fixture 在 `tests/fixtures/perturb/`，**进仓库**（CI 的 PR 档 oracle 没有预生成文件也能跑）。

三条纪律：

1. **不自动写进 cases.py** —— perturb.py 只打印片段，id 与指纹变更由人显式过一次
   （改 `test_case_count_and_ids_unique` 的写死题数）。
2. **别手改 fixture 的 csv**。这些路径不在 `DATASETS` 里，evalset 指纹**不会**因为
   csv 内容变化而变 —— 手改后两份报告会被判"可比"，这是已知盲点，靠 git review 兜底。
3. `dataset`（脏表）与 `gold_dataset`（干净表）必须同时给；runner 的 gold 走
   `gold_dataset`（`_gold_source`），agent 走 `dataset`。没声明 gold_dataset 的题
   行为与旧版逐字节一致。

## 已知边界

- 变换器对"全空数值列"的表会跳过该列；`percent_str`/`date_compact` 找不到目标列时
  直接报错退出 —— 宁可不生成，不生成语义错位的"扰动"。
- 空单元格（如未支付订单的 `pay_amount`）在 total_row 里按 0 计入合计，千分位/百分比
  变换保持空。这与"业务系统导出"的真实行为一致。
