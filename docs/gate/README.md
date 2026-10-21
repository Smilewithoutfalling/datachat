# 阶段 3.5 外部验证闸门

方案与预登记规则：docs/roadmap/gate-phase35.md。

```
python scripts/gate/build_gate_data.py      # 下载外部数据（约 90 MB）、构造脏表（data/gate/ 约 173 MB，不入库），结束时自动 --check
python scripts/gate/build_gate_data.py --check   # 只校验现场：文件集合恰好相等 + 指纹（scripts/gate/fingerprints.py），不下载不写
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

## CI：gate-oracle job（G1，DEVLOG [51]/[52]）

- tests.yml 里独立的 `gate-oracle` job（ubuntu + windows × 3.12）必跑这 25 条；**主矩阵里它们照旧 25 skipped，是设计不是缺陷**。
- 数据走 Actions cache，key = OS + `build_gate_data.py`、`fingerprints.py`、`requirements*.txt` 的哈希；只用精确 key。命中就完全跳过 build（并有一步机器断言 build 为 skipped）；无论命中与否都跑 `--check`，然后才跑 pytest。
- `DATACHAT_REQUIRE_GATE_DATA=1`：缺数据直接判红并报"闸门数据缺失"，不降级成 skip。数量由 `scripts/gate/check_junit.py` 按 junitxml 断言为 `len(QUESTIONS)` 条、0 失败 0 跳过。
- ubuntu 上再跑 `verify_gate.py` + `git diff --exit-code docs/gate/answers.json`（答案冻结）。改 verify_gate.py 会让 `verify_script_sha256` 变，同 PR 重生成 answers.json，diff 只允许这一行。
- **怎么读红**：
  - 红在"生成闸门数据"的下载上 → 上游（UCI / GitHub raw）不可达，看日志里的 URL，手动 re-run；不是代码问题。
  - 红在 `--check` 的"指纹不符：retail…" → 产物变了（多半是 bump 了 pandas/openpyxl），在同一个 PR 里改 `fingerprints.py` 的 `PRODUCT_SHA12` 并在 DEVLOG 写原因；源文件指纹不符则查上游，别重登。
  - "多余：…" → 缓存里混进了残留文件（不会被保存进缓存，因为 save 只在 --check 通过后执行）。
- 缓存作用域：PR 能读 master 的缓存，PR 自己存的只给本 PR 后续 run；7 天没访问自动淘汰。仓库冷一周后，下一个 PR 的 gate-oracle 会重下 90 MB，首次约 5–8 分钟（Windows 更慢），此时 UCI 挂了它就会红。
- tests.yml 是 `cancel-in-progress: true`：同一分支连续 push，中间那次的结果拿不到；被取消的 run 不保存缓存。
- 许可边界：数据只在 runner 上用于评测，不入库、不上 artifact、不进 LFS/Release；cache 只对本仓库 workflow 可见。datachat 将来若有商业用途，Olist 的 NC 条款要重审。

数据来源与许可：
- UCI Online Retail（Chen 2015，CC BY 4.0），Online Retail.xlsx sha256 前 12 位 43465a06f2cc。
- Olist Brazilian E-Commerce（olist/work-at-olist-data @ d9e49802f3e92d09ee94ab9ccc5e457f207a8959；Kaggle 版本为 CC BY-NC-SA 4.0，仅用于非商业评测，不随产品分发）。
