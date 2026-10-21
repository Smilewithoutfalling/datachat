# 阶段 3.5 外部验证闸门

方案与预登记规则：docs/roadmap/gate-phase35.md。

```
python scripts/gate/build_gate_data.py      # 下载外部数据、构造脏表（约 110 MB，到 data/gate/，不入库）
python scripts/gate/verify_gate.py          # 在原始数据上独立算标准答案 → docs/gate/answers.json（已入库，冻结）
python -m pytest tests/test_gate.py         # 自检：脏化只改呈现、题目分布、答案冻结、判定规则、25 题在脏表上可解
python scripts/gate/run_gate.py --agent react      # 跑模型 → docs/eval/gate_<时间>_react.json
#   人工逐题填 human_correct / failure_class / reason / guessing
python scripts/gate/run_gate.py --verdict docs/eval/gate_<时间>_react.json --profile m13
#   门槛在 docs/gate/thresholds.json：phase35 = 阶段 3.5 原判，m13 = 阶段 5 改 CHART_GUIDE 后的回归（DEVLOG [25]）

# A1 错题复跑（profile m13r，DEVLOG [49]/[50]；需要 API Key，与主报告同一 commit、同一模型环境）
python scripts/gate/run_gate.py --rerun docs/eval/gate_<时间>_react.json --profile m13r
#   名单外错题各复跑 3 次（无效的补 1 次，最多 4 次），写进同一报告的 reruns，并直接写回 verdict（一般全在 pending_review）
#   人工在 reruns 的有效行上签 human_correct（判错再填 failure_class），然后：
python scripts/gate/run_gate.py --verdict docs/eval/gate_<时间>_react.json --profile m13r
#   补题 / 中断续跑 / 环境原因重跑：--rerun ... --only s02 --reason "<理由>"（旧行进 rerun_history）
#   workflow 报告加 --agent workflow；要求 commit 干净：--require-sha
```

退出码：0 通过 / 1 有回归 / 2 无法判定（待复跑、待签字、有效复跑不足）/ 3 前提不满足（没判完、profile 不存在、复跑环境不一致等）。

**注意**：m13 / phase35 的成功路径有意不改，有回归时退出码仍是 0。它们的 0 只表示"跑完了"，不表示"通过"，结论看报告 verdict 里的 regression_verdict。只有 m13r 的 0 表示通过。

数据来源与许可：
- UCI Online Retail（Chen 2015，CC BY 4.0），Online Retail.xlsx sha256 前 12 位 43465a06f2cc。
- Olist Brazilian E-Commerce（olist/work-at-olist-data @ d9e49802f3e92d09ee94ab9ccc5e457f207a8959；Kaggle 版本为 CC BY-NC-SA 4.0，仅用于非商业评测，不随产品分发）。
