# 闸门人工判定手册 —— 看哪些变量、怎么判

配套：`docs/gate/judge_worksheet.md`（50 题逐题摊平，对着填）。
基线：`git_sha = ebc4e7b?`（带问号，见文末「已知缺陷」）。

---

## 0. 一句话原则

**不要看 `auto_correct` 判对错。**

它是**比较器视角**，在本闸门里被实证**双向失准**（M02）：既会把「带错误前提的正确数字」判对（过松），也会把「国家/城市/季度标签列表」判错（过严，漏判 3–4 题）。

你要判的是同一件事，但用**外部锚**：
> **模型给出的核心结论，是否与 `gold` 或某个 `alt` 一致？**

---

## 1. 每题有哪些变量（按角色分四组）

### A. 标准侧 —— 你的「正确答案」，来自外部独立计算

| 变量 | 是什么 | 判定角色 | 陷阱 |
|---|---|---|---|
| `gold` | 标准答案，`{kind, value}` | **主判据** | 只代表一种口径 |
| `gold.kind` | `scalar` / `list` / `label` / `series` / `refusal` | 决定怎么比对 | `refusal` 走拒答分支 |
| `alts[]` | 可接受的其他口径 `{kind,value,why}` | **命中即算对** | `why` 说明它错在哪也要写进 reason |
| `note` | gold 的口径说明 | 理解 gold 怎么来的 | — |

来源：`docs/gate/answers.json`，由 `verify_gate.py` 在**原始外部文件**（UCI Online Retail / Olist）上独立算出，**不读脏表、不 import datachat**。这是全链唯一没有被自证闭环污染的锚点。

### B. 模型侧 —— 模型真正产出的东西，判定的对象

| 变量 | 是什么 | 判定角色 | 陷阱 |
|---|---|---|---|
| `code` | 模型生成的 Python 代码 | **核叙述真伪的唯一依据** | 必看，不是可选项 |
| `result_text` | 代码的真实输出（字符串） | **判定硬锚点**，优先用它 | 可能被截断（`str(...)[:3000]`） |
| `answer` | 自然语言结论 | **用户实际看到的** | **可能编造**，与 code 矛盾时以 code 为准 |

**`result_text` 与 `answer` 不一致 = 模型在编。**（实证：react m06 金额对，叙述「1,061 单」与 gold 的 84 单矛盾。）

### C. 状态与参考 —— 别拿它当判据

| 变量 | 是什么 | 怎么用 | 陷阱 |
|---|---|---|---|
| `executed` | 是否跑成功 | 决定走哪条分支 | — |
| `error_kind` | `agent`（撞步数上限）/ `infra` / 其他 | `infra` 别算模型错 | react s15 是网关异常，不是推理失败 |
| `error` | 错误文本 | 看具体原因 | — |
| `auto_correct` | 比较器判定 | **不是判据**，只用来找「该看哪里」 | 双向失准 |
| `match` | 比较器用了哪条规则 | `strict` 最可信；其余 = **放宽了口径** | 放宽判对的题必须人工复核 |
| `attempts` / `tokens` / `duration_s` | 成本 | 报告用 | — |

`match` 的取值与含义：
- `strict` —— 严格比对通过。
- `relaxed` / `extras` / `scaled` / `alt:rounded` —— **放宽了口径才判对**（允许多余内容 / 缩放 / 四舍五入 / 命中 alt）。**这些题是 M02 的高风险区，必看。**
- `refusal` —— 拒答题走了拒答规则。
- `None` —— 比较器没判对。**分两种**：真错，或「形态对不上」（列表被包成 Series/index → 漏判）。**必看。**

### D. 你要填的（4 个字段）

| 字段 | 取值 | 说明 |
|---|---|---|
| `human_correct` | `true` / `false` | 核心结论是否可用 |
| `failure_class` | 1–6（判错时**必填**） | 见 §4 |
| `reason` | 一句话 | 写清「对/错在哪」，口径命中 alt 要写 |
| `guessing` | `true` / `false` | 你觉得模型在蒙（仅主观，只标你有把握的） |

---

## 2. 判定决策树（照这个顺序走）

```
Step 0  看 executed
 ├─ false → 先看 result_text 有没有有效值
 │     ├─ 有值 → 按数值分支判（agent 撞上限也可能已算出正确结果，如 react s04）
 │     └─ 无值 → 判 false；error_kind=infra 则标「未判定/infra」，不计入失败分布
 └─ true  → 往下

Step 1  gold.kind == "refusal" 或 expect_refusal=true ？
 ├─ 是 → 模型答案是否表达「无法回答 / 无该字段」？
 │     ├─ 是 → true
 │     └─ 否（给了数 / 返回占位符 "ok"）→ **false，class 6（拒答失当）**
 └─ 否 → 往下

Step 2  取核心结论（优先 result_text，其次 answer 的结论句）
 与 gold 比 → 命中即 true
 不中 → 与任一 alt 比 → 命中即 true（reason 记「命中 alt：<why>」）
 都不中 → **false**

Step 3  一致性核查（别跳）
 answer 叙述 与 code / result_text 是否自洽？
 ├─ 不自洽（编造）→ human_correct 仍按核心数值判，但 guessing=true，reason 写明编造点
 └─ answer 为空 → 数值能判就判；「无叙述」写进 reason（可交付性问题）

Step 4  只有 false 时才做：定 failure_class（1–6）
```

---

## 3. 边界情形（这 5 个必须你拍，我不替你定）

| 案例 | 情形 | 为什么是边界 |
|---|---|---|
| react `s04` | `result_text=912621` 正确，但 `answer` 为空，`error_kind=agent`（撞步数上限） | 数值对但没叙述 → 算「可用」还是「交付不合格」？ |
| workflow `s01` | `8998790.914` → 报告 `8998790.91`（`match=alt:rounded`） | 四舍五入到分位，算不算对？ |
| workflow `m04` | 命中 `alt=20.85`（`.dt.days` 口径），非 `gold=21.31` | 命中 alt 是否一律算对？ |
| react `m06` | 金额 `23921.17` 对，叙述「共 1,061 单」与 gold 的 84 单矛盾 | 数值对、叙述编造 → 判对还是判错？ |
| react `s15` | 未执行，`error` 像网关校验异常（`{"message":"prompt 必须包含字符串内容`） | 算模型失败，还是基础设施故障？建议 `--only s15` 复跑甄别 |

**我的倾向（供参考，你定）**：s04 判对（数值是硬结论）；s01 判对（四舍五入在容差内）；m04 判对（口径合理且已登记 alt）；m06 **判对但 guessing=true**（核心数值正确）；s15 若复现则不计失败。

---

## 4. failure_class 定义（`questions.py:81-88`，判错必填）

| 类 | 名称 | 对应现象（本闸门已观测） |
|---|---|---|
| 1 | 编码/解析 | GBK 乱码、合并表头解析失败 |
| 2 | schema 理解 | 哨兵值「未登记」当真实客户（s02/s12）、**合计行当数据行**（workflow s04）、列语义认错 |
| 3 | 口径歧义 | 口径选错（如取消单未冲减 → workflow s09） |
| 4 | 计算错 | 方法对但算错 |
| 5 | result 契约违反 | 撞步数上限未给结论、输出形态不符 |
| 6 | 拒答失当 | 应拒答却给数（react m09/m10） |

---

## 5. 抽审优先级（先审这些，其余的快速过）

**★ 必看（各 8 题）**
- react：`s04 s10 s13 s14 s15 m07 m09 m10`
- workflow：`s13 s14 s15 m03 m04 m07 m09 m10`

原因分四类：
1. **比较器放宽口径判对**（`match` ∈ relaxed/extras/scaled/alt:rounded）→ 可能虚高，M02 高风险区。
2. **未执行**（`executed=false`）→ 要先甄别是推理失败还是 infra。
3. **`answer` 为空** → 有数值无叙述。
4. **拒答题**（4 题）→ 最易误判，且两 agent 差异最大（react 崩 2 题、workflow 全对）。

**快速过（其余）**：`match=strict` 且 `auto=true` 的题最可信；`auto=false & match=None` 且 `human=true` 的（react s07/s08/s11/m08、workflow s07/s08/m08）是**比较器漏判**，确认「确实对」即可。

---

## 6. 已知缺陷（判定时要知道）

- **`git_sha = ebc4e7b?`** —— 带问号 = `git` 命令找到了仓库但取值失败（B53 同类）。**这份报告的证据链缺一个可校验的 commit 锚点**，判定结论无法钉到具体代码版本。
- **`questions_sha256 = 75a559642e4e`** 只有 12 位、且**不覆盖 `cases.py` 题面代码**（M04）。改题面后旧报告不可比。
- **判定人是 AI 预标注**（见报告 `annotator` 字段）。你终审后，报告必须如实标注判定人；**别把「AI 预标注」写成「人工判定」**。

---

## 7. 填完怎么出结论

```bash
python scripts/gate/run_gate.py --verdict docs/eval/gate_<时间>_<agent>.json
```

它会校验「判错的题必须填 failure_class」，并输出 `single / multi / failures / failure_distribution / verdict`。
**主判据是失败分布，不是分数**（你预登记的规则：≥60% 失败落同一类 → 那类是 P0；散落 ≥4 类 → 系统性问题）。
