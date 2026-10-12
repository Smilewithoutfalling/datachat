# 阶段 3.5 外部验证闸门

方案与预登记规则：docs/roadmap/gate-phase35.md。

```
python scripts/gate/build_gate_data.py      # 下载外部数据、构造脏表（约 110 MB，到 data/gate/，不入库）
python scripts/gate/verify_gate.py          # 在原始数据上独立算标准答案 → docs/gate/answers.json（已入库，冻结）
python -m pytest tests/test_gate.py         # 自检：脏化只改呈现、题目分布、答案冻结、判定规则、25 题在脏表上可解
python scripts/gate/run_gate.py --agent react      # 跑模型 → docs/eval/gate_<时间>_react.json
#   人工逐题填 human_correct / failure_class / reason / guessing
python scripts/gate/run_gate.py --verdict docs/eval/gate_<时间>_react.json
```

数据来源与许可：
- UCI Online Retail（Chen 2015，CC BY 4.0），Online Retail.xlsx sha256 前 12 位 43465a06f2cc。
- Olist Brazilian E-Commerce（olist/work-at-olist-data @ d9e49802f3e92d09ee94ab9ccc5e457f207a8959；Kaggle 版本为 CC BY-NC-SA 4.0，仅用于非商业评测，不随产品分发）。
