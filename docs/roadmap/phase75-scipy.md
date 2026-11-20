# 阶段 7.5 第 2 步（第三部分）：`scipy.stats` 方案

> 状态：草案，待 S 拍板 §4。依据 phase75-assess.md:40、:63。

## 1. 结论先行

**建议先不加，改为「等题驱动」。** 理由：

1. **题库里没有需要它的题。** 202 题中检索「p值 / 显著 / 检验 / 卡方 / 置信区间 / 正态 / 方差分析 / 回归系数」：`app/eval/cases*.py` 命中 1 处，而且是 `cases_multi.py:195` 的注释（讲 McNemar），不是题目。加库无法用评测证明收益，这和 phase75:63 对 sklearn/statsmodels 的门槛是同一条。
2. **体积代价大。** `import scipy.stats` 会连带加载 12 个子包，见 §2。现有 sidecar zip 89 MB（CI sidecar run 44660448032），粗估会增加三到五成，要等 CI 实测确认。
3. **相关、标准差、分位数这类需求，pandas/numpy 已经覆盖。** 题库里命中这类词的有 54 处，都不需要 scipy。

## 2. 实测（沙箱 aarch64，scipy 1.18.1，仅供参考，Windows 的数字以 CI 为准）

| 项 | 数值 |
|---|---|
| `import scipy.stats` 后加载的 scipy 模块 | 493 个 |
| 被连带的子包 | special、linalg、optimize、sparse、spatial、interpolate、integrate、fft、ndimage、constants、_lib、_external |
| scipy 包目录（未压缩） | 116.4 MB，另有 scipy.libs 31.8 MB |
| 其中 stats / optimize / sparse / special / linalg | 18.9 / 16.1 / 13.4 / 13.3 / 11.6 MB |
| 现有 sidecar zip | 89 MB |

## 3. 如果要加，按这个做（实现 PR 的已定规则）

- **白名单精确到子模块。** `sandbox_policy.py:17` 现在按顶层包名判断，直接把 `scipy` 加进 `allowed_imports` 会放开全部 scipy（包括 `scipy.io` 读写文件）。所以改为：`scipy` 只允许 `import scipy.stats` 和 `from scipy import stats`，`sandbox_caps.py` 增加一个 `allowed_submodules` 字段，评估契约 `codegen_imports` 也读这个字段。`tests/test_assess_contracts.py:98` 里 `from scipy import stats` 的期望会从 FAIL 变为 PASS；`from scipy import io` 仍是 FAIL。
- **导出也要同步。** `export_runtime.py` 的 import 白名单加上 `scipy.stats`；干净 venv 的导出测试补一条带 `scipy.stats` 的用例。
- **打包。** `build_sidecar.py` 加 `--hidden-import scipy.stats`，同时排除 `scipy.io`、`scipy.datasets`、`scipy.misc`、测试目录；selftest 加一项 `stats.ttest_ind` 冒烟。体积差贴在 PR 里，同 openpyxl。
- **prompt。** codegen 能力说明加一行「可用 scipy.stats 做检验」。按 phase75 §3 这属于全局 prompt，必须跑**评测全量 202 题**。
- **验收。** ① 现有闸门全绿；② sidecar 体积差和冷启动耗时差贴进 PR；③ 内网全量 202 题，按配对翻转判读（#111 B5），配对净退步不得 ≥6；④ 补 3 道检验题（t 检验、卡方、相关显著性），由评测侧入库后再算收益。
  - **补充（11-20，评测侧意见，S 同意）**：①不要直接进 `ALL_CASES`。202 题变成 205 题会改动 evalset 指纹，`nightly_gate` 会判定为「不可比」，v7 基线作废。先做成 probe 批（形式同 `probe_flip_1118`），单独跑这 3 题，用完就丢；只有决定真正加库时，才正式入库，并走断代流程、重新跑三次立基线。②codegen 没有加能力说明时，probe 测出来「模型不用检验」只能算下界，结论里必须注明。加不加能力说明属于 A 组 prompt 变更，需要全量回归，由 S 定。

## 4. 待 S 定

1. 先不加、等题驱动（推荐），还是按 §3 现在就加？
2. 如果加：sidecar 体积上限能接受多少？
3. 是否让评测侧先补检验类题目（§3 ④），用来判断值不值得加？
