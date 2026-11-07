# 失败归因表（EV-D2）

**这张表与 `app/eval/failure_classes.py` 的码集合必须逐字相等**，`tests/test_failure_map.py` 钉住。
改一边忘另一边 -> 测试红。

## 为什么要归因到模块

闸门报告里判错的题只写一句人话（"schema 理解错"），评测报告里只有机器码
（`ANSWER_RESULT_MISMATCH`）。两者都不告诉你**该去动哪个文件**。没有映射时，
每轮复盘都要人肉重新推一遍——推错一次就改错模块。

本表给每个码配三样东西：**落点模块**、**首个修复方向**、**历史案例**。
`scripts/eval/triage.py` 把任意报告翻成这三样。

## 两类码，别混

| 类别 | 来源 | 形态 | 谁填 |
|---|---|---|---|
| `F*` | 闸门报告（`scripts/gate/`） | 整数 1–6，或自由文本 | 人工标注 |
| `A*` | 评测报告（`run_eval.py`） | 大写常量 | 机器（一致性/图表/扰动断言） |

**infra 错误不在此表**：`llm` / `cancelled` / `interrupted` / `dataset` 类失败由报告里的
`error` 字段与 tier 区分，triage 单独归到 `infra` 桶。把它们算成模型错会污染失败率。

## 表

| code | 标签 | 闸门编号 | 触发关键词 | 模块 | 首个修复方向 | 历史案例 |
|---|---|---|---|---|---|---|
| `F01_PARSE` | 编码/解析 | 1 | 编码、解析、乱码、分隔符、parse、encoding | `app/tools/csv_io.py` | 看解码链：编码猜测顺序、分隔符嗅探、千分位清洗 | s07 千分位未清洗导致静默拼接 |
| `F02_SCHEMA` | schema 理解 | 2 | schema、列名、字段、理解、表头、类型 | `app/tools/schema.py` | 改 schema 渲染（采样行/类型名/统计行标注），不改提示词 | m03 把 leave_date 为空当别的口径 |
| `F03_CALIBER` | 口径歧义 | 3 | 口径、歧义、定义、含不含、净额 | `app/tools/dictionary.py` | 补数据字典条目；检索命中率进报告 | s03 净额是否含取消单没说清 |
| `F04_COMPUTE` | 计算错 | 4 | 计算、算错、聚合、去重、排序 | `app/tools/sandbox.py` | 先看聚合层级 / 去重 / 取前 N；能进扰动题就进 | m04 跨表 Top5 用了错表的行数 |
| `F05_CONTRACT` | result 契约违反 | 5 | 契约、result、未赋值、输出格式 | `app/core/result.py` | 看执行器收尾与 format_result 兜底 | s02 只打印没赋值 result |
| `F06_REFUSAL` | 拒答失当 | 6 | 拒答、澄清、反问、impossible、refusal | `app/core/service.py` | 看负向题集（neg_*）与 expect_kind 判定路径 | m09 缺列却硬算 |
| `A01_ANSWER_RESULT_MISMATCH` | 答案数字与 result 不一致 | — | answer_result_mismatch、结果不一致 | `app/core/service.py` | 总结层数字注入与换算规则（0.2493↔24.93） | B4 断言 1 首批命中 |
| `A02_CHART_RESULT_MISMATCH` | 图表与 result 不一致 | — | chart_result_mismatch、图表 | `app/core/chart_check.py` | 图从哪个 df 生成（漏过滤/漏同聚合） | B3 落地首轮，"和匹配"救拆解图误报 |
| `A03_TIME_FILTER_MISMATCH` | 时间词与代码不一致 | — | time_filter_mismatch、时间过滤 | `app/core/service.py` | today 注入与相对时间解析 | mul_031 追问"上个月"沿用首轮区间 |
| `A04_TOTAL_ROW_COUNTED` | 尾部统计行被当明细 | — | total_row、合计行、统计行、汇总行 | `app/tools/schema.py` | 已加尾部统计行标注；仍复现就看注解有没有被挤掉 | 扰动 20 题 5 败：204 在职(真值 203)、61 条(真值 60) |

## 用法

```bash
# 单份
python scripts/eval/triage.py docs/eval/gate_20261012_104407_react.json
# 多份合并，机器可读
python scripts/eval/triage.py outputs/mul_state.json outputs/mem_full.json --json
```

退出码：**有未映射条目 -> 1**。CI/nightly 里可以直接当门禁用。

## 已知边界

- **自由文本归因只能做到关键词级**。同一条"② 缺失哨兵"既可能属于 `F02_SCHEMA` 也可能属于
  `F06_REFUSAL`，关键词匹配取**最长命中**；判不准时它会被算成未映射，逼人补关键词而不是猜。
- **一个错可能有多因**。本表只记首个修复方向，不建因果图；同一题有多个码时 triage 会各报一次。
