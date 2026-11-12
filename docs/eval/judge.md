# LLM Judge（EV-B8 / phase7 E4）

> 用途：给"结论对不对"提供第二把尺子，判**结论文字与数值是否一致**；数值对错仍以比较器 + 人工判定为准。
> 状态：**已校准达标，可启用**（2026-11-12）。校准读数见 §3。

## 1. 契约（预登记，来自 spec EV-B8）

- 只判二元（pass / 不 pass），**不打分**——0-100 分不可校准。
- `confidence=low` 或 `abstain=true` 的样本**不计入一致率分母**，校准时单列。
- 调用失败抛 `JudgeError`，**绝不返回 pass=false**——基础设施故障不算模型错。
- rubric 只来自题面与 gold，**不许把被评答案喂回去让它"解释"**。
- 防偏差：gold 与 answer 呈现顺序一半 `gold_first` / 一半 `answer_first`（固定 seed 可复现）；
  prompt 明写"长度、文风不作依据"。
- judge 模型与被评模型**不同家族**。当前：judge = `Qwen3.5-397B-A17B`，主评测模型 = `GLM-5.2`（CI）。
- judge **不进 CI 门禁**（要 Key、有成本、有随机性），只服务离线校准与报告复核。

## 2. 文件

| 文件 | 职责 |
|---|---|
| `app/eval/judge.py` | `judge()` 单次判定 + `judge_model()`（`DATACHAT_JUDGE_MODEL/API_KEY/BASE_URL` 配置，缺省回退 `DEEPSEEK_*`） |
| `scripts/eval/judge_calibrate.py` | 跑校准集，算一致率 / Cohen's κ / 混淆矩阵 / 弃权数；退出码 0=达标 1=未达标 2=有效样本不足 |
| `scripts/eval/build_judge_gold.py` | 从历史报告构建校准集（带 match 阶梯过滤与 alt 纳入，见 §4） |
| `docs/eval/judge_gold.jsonl` | 校准集：35 条（20 对 / 15 错），跨 16 个类别，顺序 20/15 平衡 |
| `tests/test_judge.py` | 13 条契约测试（二元/弃权/重试/异常/temperature 锁死/κ 手算对照） |

## 3. 校准读数（2026-11-12，judge=`Qwen3.5-397B-A17B`，temp=0.0）

```
样本 35：有效 34   弃权/低置信 1   调用失败 0
混淆矩阵（judge, label）：TP=19  FP=0  FN=0  TN=15
一致率 100.0%   Cohen's κ 1.000
判据：κ ≥ 0.7 且 一致率 ≥ 90% → 达标，可启用
```

弃权 1 条（mem_007）：模型回答只引用前轮结果没给数值，judge 按契约 abstain——这是**正确行为**。

**解读纪律**：这个 100% 是三轮修正**校准集标签**后的读数，judge prompt 从第一版起一字未改。
三轮修正的全是标签侧问题（见 §4）——结论是 judge 本体稳定，但 35 条样本量下 100% 仍有
过拟合校准集的可能；后续跑批累积新错样本时应扩到 40+ 复核。

## 4. 校准集构建规则（第一轮 82% → 第三轮 100% 的教训）

第一轮校准一致率只有 82.1%（κ 0.640），7 条错分**全部是校准集标签问题**，judge 本体零误伤：

| 问题 | 实测案例 | 修法 |
|---|---|---|
| expected 字符串被报告截断（~520 字符） | agg_005：25 行表只剩 20 行，judge 把截掉的行判成"标准答案缺失" | series 一律用 `expected_obj`（结构化完整）构造 |
| 旧报告（10 月初）无 match 字段，判分口径过期 | ord_027：answer 858,290.45 vs gold 850854.16 差 0.9% 却标 True | True 侧要求 match ∈ {strict, rounded, refusal, impossible} 及其 alt: 前缀；False 侧要求人工背书或 match 非 None |
| alt 答案没进 gold_summary | emp_025：模型答 18580（登记的全员口径变体），judge 只见主 gold 18631.53 | `match=alt:*` 的样本从用例定义现算全部 alt 值列进标准答案 |
| 拒答题契约没表达 | emp_022：answer 拒答后又输出大段替代分析，judge 只看"结论=拒答"就放行 | rubric 对"无法回答"类 gold 写明：拒答后续答算错 |

**样本量偏离说明**：规格写"20 对 / 20 错"，实际 20 对 / **15** 错——仓库内判分语义清晰的
错样本就 15 条（match=None 且无人背书的旧报告 False 不可信，实测有标签反转）。凑够 20 只能
放宽过滤灌噪声，不凑。跑批累积新错样本（human=False 或 match 阶梯明确的 False）到 20 后改回。

## 5. 用法

```bash
# 重建校准集（历史报告变化后）
python scripts/eval/build_judge_gold.py

# 校准（验收命令，与 spec EV-B8 一致）
python scripts/eval/judge_calibrate.py --gold docs/eval/judge_gold.jsonl
python scripts/eval/judge_calibrate.py --gold docs/eval/judge_gold.jsonl --limit 5   # 冒烟
python scripts/eval/judge_calibrate.py --gold ... --out outputs/judge_cal.json       # 存明细

# 单次判定
from app.eval.judge import judge, judge_model
r = judge(question, answer, gold_summary, rubric, model=judge_model(), order="gold_first")
```

## 6. 启用条件与边界

- **已满足**：κ 1.000 ≥ 0.7，一致率 100% ≥ 90%（预登记判据）。
- judge 只复核"结论文字与数值是否一致、有无过度推断"；**数值对错的最终裁定仍是比较器 + 人工**。
- judge 结果进报告只作参考列，不参与 auto_correct，不进门禁。
- 换 judge 模型必须重新校准并落新的读数到本文件。
