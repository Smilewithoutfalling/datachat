# 多轮评测（EV-B5）怎么加一条题

题库在 `app/eval/cases_multi.py`（`MULTI_CASES`，截至 2026-11-04 共 **34 条**，规格下限 8 条）。
记忆系统 M11 要扩题就改**同一个文件**，不另建 —— 两处清单迟早漂移。

## 一条多轮题长什么样

```python
EvalCase(id="mul_035", category="multi_turn", dataset="orders", gold_kind="scalar",
         turns=["只看已完成的订单，这样的订单有多少笔？",     # 第 1 轮
                "其中 APP 渠道的有多少笔？"],                 # 第 2 轮（= question，判分只看它）
         question="其中 APP 渠道的有多少笔？",
         ground_truth=_D + "d = d[d['status'] == '已完成']; result = int((d['channel'] == 'APP').sum())",
         no_history_truth="result = int((df['channel'] == 'APP').sum())",
         keywords=["status", "channel", "APP"],
         expect_turns=["exec", "inherit:已完成"]),
```

字段约定（`EvalCase` 定义在 `case_model.py`，校验在 `validate.py`，改字段先过那两关）：

| 字段 | 必填 | 说明 |
|---|---|---|
| `turns` | ✓ | 按时间顺序的全部问题；非空时 `question` 必须等于 `turns[-1]` |
| `expect_turns` | ✓ | 每轮一个约束，长度必须等于 `len(turns)`。取值见下 |
| `ground_truth` | ✓ | **只算最后一轮**，且是独立的完整表达式（gold 执行时没有前几轮的结果） |
| `no_history_truth` | 二选一 | 把末轮当独立单轮题时的"直白答案"；用于机械验证"这题真的需要历史" |
| `recall_turn` | 可选 | 跨轮数字断言，见下 |
| `gold_dataset` | 可选 | 脏数据题（EV-B6）用：gold 在干净表上跑 |

`expect_turns` 的取值：

- `exec` —— 该轮必须执行代码
- `refusal` —— 该轮必须按契约拒答
- `any` —— 不约束（纯指令轮，不计入报告的约束满足分母）
- `inherit:<regex>` —— 该轮**最终代码**必须匹配 regex。匹配代码不匹配答案：匹配答案等于测措辞。

## 加题的硬规则

1. **末轮必须不能单独作答。** 判据：把 `turns[-1]` 单独发给一个没看过历史的模型，它无法确定要算什么。
   "那 S02 呢""这些记录里"这种指代要敢写 —— 单轮题不敢写的是歧义，多轮题必须写。
2. **`no_history_truth` 与豁免表二选一。** 没写对照的题必须在
   `tests/test_multi_cases.py::_NOT_ABOUT_REMEMBERING` 里登记理由，否则测试红。
   两边都写也红。这不是文书负担：mul_014/mul_030 初稿的"记忆题"在两种口径下答案恰好相同，
   一分记忆都没测出来 —— 这道闸就是防它的。
3. **`no_history_truth` 必须与 gold 不同**（`test_no_history_truth_actually_differs_from_gold`）。
   相同 = 不带历史也能对 = 零信息量。
4. **gold 不跨轮传值。** 每轮是独立的 analyze 调用，历史里只有问答文本（+ off 路径的可信代码快照）。
   末轮想要什么条件就写什么条件 —— 这正是 `inherit:` 能断言"约束被带下来"的原因。
5. **前几轮失败不重试。** 历史变脏是真实行为，重试会掩盖 D4（失败恢复）要测的东西。
6. **轮数克制。** 多轮题成本是 `turns ×`；规格的 8 条里最长 3 轮，别把新题都写成 5 轮。
7. **id 走 `mul_` 前缀**，`^[a-z]{2,6}_\d{3}$`；加题必须同步改
   `tests/test_eval_cases.py::test_case_count_and_ids_unique` 里写死的题数 —— 那行故意写死，
   加题会让 evalset 指纹变、历史数字失去可比性，必须显式过一次。

## 跨轮数字断言（`recall_turn`，规格 mt_007 的附加项）

`recall_turn: int = 0`。0 = 不启用；设为 n（1 起头，必须 < `len(turns)`）后，
**最后一轮 answer 里的"有分量"数字必须全部能在前面各轮的 `result_text` 里找到**
（`grounding.unverified_numbers` 的抽取与容差：千分位 / % / 万 / 亿 / 比例↔百分数都认，年份自动豁免）。

- 为什么需要它：gold 是独立重算的，模型把第 1 轮的数**记错**、末轮逻辑对，result 层照样判对 ——
  只有这条路能抓"长会话后复述错旧数字"。
- 与规格字面的偏差：规格写"∈ 第 1 轮 result_text"，实现取**末轮之前全部轮次**的 result_text。
  原因：最终答案常常同时复述几个轮次的数（"合计 X，其中 6 月 Y"），只认第 1 轮会把第 2 轮的
  合法数字误判成编造；而幻觉了旧数字的失败，两种口径都抓得到。
- 失败时 `correct=False`，原因写进报告行的 `recall_why`，汇总在
  `summary.multi_turn.recall`。当前只有 mul_034 启用。
- 校验：`validate.py` 规则 2c —— 只对多轮题有效、不许指向末轮（指向末轮等于拿自己当证据）。

## 现有 34 条的分组（写新题前先看有没有重复劳动）

| 组 | 题 | 测什么 |
|---|---|---|
| A 约束继承 | mul_001–003 | 末轮省略筛选条件，"这些记录"指上一轮那批 |
| B 纠正覆盖 | mul_004–005 | 第 2 轮推翻第 1 轮的前提 |
| C 粒度/口径切换 | mul_006–010 | 按地区→按城市→回地区、换表、换指标 |
| D 失败恢复 | mul_011、mul_029 | 拒答/报错后追问 |
| E 防过度继承 | mul_025、mul_033 | 该丢的约束要丢掉（跨表、选择性撤销） |
| F 指代计算结果 | mul_016、mul_026–027、mul_032 | "那个部门""这 3 个地区""它" |
| V 回头引用 | mul_034 | 长会话后复述第 1 轮的数字（`recall_turn`） |

## 验收命令

```bash
python run_eval.py --oracle --agent react --case mul_001 --verbose
python -c "from app.eval.cases import ALL_CASES; print(sum(1 for c in ALL_CASES if c.turns))"
python -m pytest tests/test_multi_cases.py -q
```
