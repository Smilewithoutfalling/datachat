# 阶段 5 前端方案 v1 评审（锐，2026-10-15）

- 核验基线：`HEAD = 513f6e1`（DEVLOG [29]/[30]，B70 已合并）；M13 第 1–3 步已完成（[22]–[28]，`063f242` / `be5cfa8`）。
- 结论：**骨架可用，没有要推翻的地方**。但有 **8 处会让你在 F0/F2/F3 直接卡住**、**6 处遗漏**、**4 处与既有文档不一致**。估时要改。
- 本文只列**可核实的差异与风险**；已核对属实、方案写得对的地方不再复述。

---

## 1. 会炸的（按会撞上的顺序）

### 1.1 F0 — 静态资源挂 auth 会白屏（`app/server/app.py:100`）

现有 `auth` 是**路由级依赖**（每个 API 都写 `dependencies=[Depends(auth)]`）。新增 dist 托管时必须分开：

| 路径 | auth | 理由 |
|---|---|---|
| `GET /` | **不要** | 首次打开时前端还没有 token（token 在 fragment 里，由前端读出） |
| `GET /assets/*.js|.css` | **不要** | 子资源请求带不了自定义头，挂了就是 401 → 白屏 |
| `GET /charts/*` | 要（`?token=` 分支，`:104-107`） | 已有 |
| 其余 API | 要 | 已有 |

方案 §1 只写了"FastAPI 直接托管 `ui/web/dist`"，没写这条边界。**这是 F0 第一个会炸的点，且症状是白屏而不是报错，排查会绕远。**

### 1.2 F0 — CSP 可能挡住 Vite 生产产物里的内联脚本

`script-src 'self'` 不允许内联 `<script>`。Vite 默认不内联，但**必须在 F0 实测构建产物的 `index.html`**：只要有内联 `<script type="module">`（module preload polyfill 的旧形态、或日后误加 singlefile 插件），页面直接白屏，且浏览器只在 console 报 CSP 违规。

**F0 验证项**：`grep -c '<script[^>]*>[^<]' dist/index.html` 应为 0；不为 0 就改用 `hash`/`nonce`。
另外建议补三个便宜的头：`base-uri 'none'`（防 `<base>` 劫持）、`form-action 'none'`、`frame-ancestors 'none'`（纵深；TrustedHost 已挡 T5，但这是零成本的一道）。

### 1.3 F0 — `messages` 加两列没有迁移路径，与验收条件直接冲突

`app/server/db.py:105` 只有：

```python
Base.metadata.create_all(engine)
```

`create_all` **只建缺的表，不改已存在的表**。所以 `feedback` / `feedback_note` 两列在**任何已存在的库上都不会生效** → `PUT /messages/{id}/feedback` 直接 `OperationalError: no such column`。

而验收条件里有"**重启后会话还在**" → 不能靠删库重建来加列。

**要补**：一个幂等迁移（`PRAGMA table_info(messages)` 查缺哪列 → `ALTER TABLE messages ADD COLUMN ...`），在 `create_all` 之后跑。SQLite 支持 `ADD COLUMN`，够用。方案 §5 只写了"messages 表加两列"。

### 1.4 F0 — token 失效没有降级路径

方案 §1 的 token 流转（fragment → sessionStorage → `replaceState` 抹掉）本身是对的。缺的是**失效后的行为**：

- **后端重启 → token 换新**（`app/server/__main__.py` 每次启动随机生成）→ 前端 sessionStorage 里的旧 token 全部 401。**必须有一个"token 失效"页**，指引回命令行重开 URL，而不是让每个请求静默 401。
- **新标签页 / 复制 URL 打开** → 没有 token（`replaceState` 已抹掉）→ 同上。
- **`replaceState` 必须在读出 token 后同步执行**，早于任何 `await`；否则前端在初始化阶段抛异常时 fragment 会留在地址栏。

### 1.5 F2 — 「停止」按 AbortController 有三个问题（方案自己标了"待实测"，实测结果不会乐观）

后端现在是这样（`app/server/app.py:301-325`，`def stream()` 起于 `:301`、`status` 初值在 `:302`、`finally` 在 `:319`）：

```python
def stream():
    status, content, result_json = "cancelled", "已取消", None
    try:
        for ev in analyze_stream(target, body.content, **kwargs):
            ...
            yield f"id: {ev.seq}\nevent: {ev.type}\n..."
    finally:
        # 写回 status / content / result_json
```

① **断开 ≠ 立即停**。生成器的关闭点在下一次 `yield`。而两次 yield 之间可能夹着**一次完整的 LLM 调用**（ReAct 一次工具调用 = 一次模型推理）→ 用户按停之后，**还要烧掉一次调用的 token 才算停住**。这在 ReAct 上最明显（20+ 步）。T6 那张表里"烧 Key 的额度"是明确的威胁项。

② **真错误会被伪装成"用户取消"**。`finally` 里 `status` 的初值是 `"cancelled"` / `"已取消"`，而 `try` **没有 except**。`analyze_stream` 抛非 `GeneratorExit` 异常时，`StreamingResponse` 报错、finally 照写 → 用户看到"已取消"，实际是崩了。这条是既有代码的问题，但阶段 5 的"停止"按钮把它变成了**用户可见路径**。

③ **409 竞态**。`post_message` 有并发保护（`:279`：同会话有 `status == "running"` 的消息就 409）。用户按停后**立刻重问**，若后端还没到 yield 点（status 仍是 running）→ 新请求 409。方案 §2 的"停止"没写这个 UX。

**建议把"不够用再加 cancel 接口"前移**。最小实现：`POST /messages/{id}/cancel` 落一个标记，`analyze_stream` 每轮检查并提前 break——停止粒度从"一次 LLM 调用"缩到"一轮"。代价是给 `analyze_stream` 传一个 cancel 回调。**同时把 finally 的初值改成 `"error"` / 空串**，只在捕获到 `GeneratorExit` 时才写 `"cancelled"`。

> 已确认处理得对、不用动：`turn_history`（`:179-186`）只收 `status == "ok"` 的轮次，取消 / 失败的轮次不进 ReAct 上下文。

### 1.6 F2 — 重放路径没有 `done` 事件

`message_out`（`:167-173`）返回的 `events` 来自 `EventRow` 表，而**`done` 事件不写表**（`db.py:77` 注释已说明："done 除外：完整结果在 messages.result_json"）。所以：

- **流式路径**：`[...events, done]`
- **重放路径**：`[...events]` + `message.result`

方案 §2 说"历史消息从 events 重放，和流式渲染共用同一套组件"——**两条路径的事件序列不同**。reducer 必须支持"用 result 兜底"，或者前端在重放时**合成一个 done**（`{type:'done', seq: max(seq)+1, data:{result: message.result}}`）。漏了这条的症状是"**刷新页面后图表消失**"，且只在这一条路径上出现。

### 1.7 F3 — `prepare()` 的"最后强制清理"列表要补，且它才是真正的守门人

方案 §3 写的是"最后强制 `tooltip.renderMode='richText'`、删 `dataView`、关 `aria`、删 `graphic` / `title.link` / `sublink`"。

顺序对（清理放在层 1 改动之后，才能覆盖掉任何来源的 `renderMode`）。**但它漏了 `formatter` 系**（`tooltip.formatter` / `series[].label.formatter` / `legend.formatter`）。

`richText` 模式下 `formatter` 不产生 DOM（canvas 绘制），所以**不是必须删**——但既然方案自己写了"不回验白名单（THREAT_MODEL §2.3）"，就意味着**白名单在后端，前端这层没有第二道**。那前端就该把**全部 DOM 通道**一次清干净，而不是逐个列举记忆：

- 必删：`toolbox.feature.dataView`、`aria`、`graphic`、`title.link` / `title.sublink`、`series[].renderItem`
- 必强制：`tooltip.renderMode = 'richText'`、`aria.enabled = false`
- 建议一并删：`tooltip.formatter`、`series[].label.formatter`、`legend.formatter`

**并且把清理列表做成常量 + 单测断言"清理后的 option 不含这些键"**——这等于在前端重新表达一遍白名单，成本低、收益是把"将来有人加了个新通道"变成测试失败。

### 1.8 F3 — 10 个开关里，6 个要往 option 里加白名单没有的键

对照 `app/tools/charts.py:331-345` 的 `_ALLOWED`：

| 开关 | 需要的键 | 在白名单里？ |
|---|---|---|
| 图例位置 | `legend.top` / `orient` | ✅ |
| 排序 | 前端对 data 排序，不改 option 结构 | ✅ |
| 数值标签 | `series[].label` | ❌ `[23]` 时删掉了 |
| 堆叠 | `series[].stack` | ❌ `[23]` 时删掉了 |
| 平滑 | `series[].smooth` | ❌ `[23]` 时删掉了 |
| 圆角 | `series[].itemStyle.borderRadius` | ❌ `_ALLOWED` 里没有 `itemStyle` |
| 渐变 | `series[].itemStyle.color` | ❌ 同上（且 `color` 只允许 `#RRGGBB` 字符串） |
| 平均线与极值 | `series[].markLine` / `markPoint` | ❌ |
| dataZoom | `dataZoom` | ❌ |
| 横 / 竖 | `yAxis.type` / `xAxis.type` | ❌ 枚举只允许 `yAxis.type == "value"`（见 1.9） |

**这不违反 v1 的安全模型**（白名单只校验 builder 输出，前端产物永不回验——`charts.py:347-349` 注释和 THREAT_MODEL §2.3 都写明了）。**但它决定了 v2 层 2 patch 白名单的"最小必需集"**：如果 v1 前端用了 `markLine` / `label` / `stack` / `smooth` / `itemStyle.borderRadius`，那 v2 想表达"加个平均线"时，**后端白名单必须能容纳这些键**，否则"一句话改样式"根本没法表达 v1 已经能做的事。

方案 §3 完全没提这层耦合。**建议在 F3 开工前，把"前端开关 × 产出键"列成一张表，钉进 `docs/roadmap/M13-图表方案.md`**——它是 v2 白名单的输入。（已在 `[30]` 落地：该文档新增 §12 就是这张表。）

顺带一个实现细节：**渐变必须用普通对象形式** `{type:'linear', x:0,y:0,x2:0,y2:1, colorStops:[...]}`，不能用 `new echarts.graphic.LinearGradient()`（后者不是合法 JSON，将来回灌 / 导出会炸）。

### 1.9 F3 — 「横 / 竖」在 v1 的 option 结构下不可达

`_ENUMS[("yAxis","type")] = {"value"}`（`charts.py:352-359`；`("xAxis","type")` 允许 `category`/`value`，但 `yAxis` 锁死 `value`），builder 产出的 `xAxis.type` 固定是 `"category"`。横向柱状图要求 `yAxis.type="category"` + `xAxis.type="value"`——**交换两个轴的类型**。

这不是"改样式"，是**改数据层结构**（`xAxis.data` 的语义从类目变成数值）。跟 M13 §3.1「data 层由 builder 独占产出」直接冲突。

**建议**：v1 把这个开关**删掉**，或者明确改成"前端重排"（前端自己交换轴 + 交换数据，标示为"重绘"而非"样式开关"）。不要让它留在"只对兼容的图型显示"的列表里——它**对任何图型都不兼容**。

---

## 2. 该补的

### 2.1 依赖漏了两个

- **`remark-gfm`**：`react-markdown` 渲染 GFM 表格需要它。方案 §1 用"结论里有 markdown 表格"当选型理由，但依赖列表里没有 → **不装则表格渲染成纯文本**。
- **`jsdom`（或 `happy-dom`）**：`@testing-library/react` 需要 DOM 环境，vitest 要配 `environment`。方案依赖列表里没有。

### 2.2 markdown 渲染要处理链接与图片

不开 `rehype-raw` 挡住了原始 HTML ✅，但：

- **链接**：`[点我](https://evil)` 会渲染成真实 `<a href>`。点击 → Referer 泄露"本机在用 datachat"。**建议在 `components` 里覆写 `a`**：`rel="noreferrer noopener"` + `target="_blank"`，或直接禁用链接。
- **图片**：`![](https://evil/x)` 会被 CSP `img-src 'self' data: blob:` 挡住 ✅ **这是免费的兜底**，但要在 THREAT_MODEL 里记一笔（否则将来有人放宽 `img-src` 就无声失守）。
- `react-markdown` v9+ 默认 `urlTransform` 过滤 `javascript:` ✅，但要**显式确认版本并在测试里钉住**（结论文本是非可信输入）。

### 2.3 导出 PNG 的两个细节

- **"导出用浅色"不要动用户看到的实例**：用离屏实例（`echarts.init(detachedDiv)` → `setOption` → `getDataURL` → `dispose`）。动现役实例会有闪烁 + 主题状态同步问题。
- **导出的文件名**来自标题 / 会话标题 → **可能含用户数据**（列名里可能有 `/`、控制字符）→ 必须清洗后再进 `a[download]`。

### 2.4 换图型要同步的两个东西

M13 §6.3 的条件表**可判定**（`xAxis.type === 'value'` 就判散点，多 series 就禁饼图），但实现时要一起处理：

- **`xAxis.boundaryGap`**：bar 是 `true`、line 是 `false`。换图型不同步改它，柱子会贴边。这个键在白名单里 ✅，但 §6.3 没提。
- **换完图型后要重算开关兼容性**：`prepare` 是纯函数，开关状态是 UI 状态。换了 pie 之后"堆叠"就不该再亮着——**要定义"开关状态保留还是重置"**。方案没写。

### 2.5 events 的 TS 类型会漂移

`Event.data` 有 6 种形状（`app/core/events.py:5-12` 那张表），前端手写 TS 类型**一定会和后端漂移**。建议二选一：

- 从 `GET /openapi.json` 生成（`openapi-typescript`）——但 SSE 的事件体不在 OpenAPI 里，覆盖不到；
- **写一份 TS 的 `EVENT_TYPES` 常量 + 一个测试断言它与 `app/core/events.py` 的 `EVENT_TYPES` 一致**（从 Python 侧或 CI 里读）。

这条的教训 M13 已经吃过一次（"白名单只留 builder 产出的键"）。

### 2.6 数据集预览应该做，不该"待定"

验收条件是"上传单表 / 多表"——**用户上传后必须能确认数据读对了**（编码、列名、分隔符、脏表结构）。没有预览，只能用"问一个问题看答案对不对"反推。

而且这个接口是 **T9 的一个入口**（数据里的字符串直出），方案自己已经想到"按 T9 原样返回，由前端转义" ✅。**建议 F1 就做**，别留"待定"——`GET /datasets/{id}` 已有 summary / 列名（`:239`），加 `preview?rows=20` 是小活。

---

## 3. 与既有文档的不一致

### 3.1 注入实测清单多测了（与 THREAT_MODEL §2.3 冲突）

M13 §4.3 的原清单是 10 个字段（`title.link` / `sublink` / `label.formatter` / `legend.formatter` / `tooltip.formatter` / `aria.label` 等）。但 **THREAT_MODEL §2.3（`[24]` 定稿）已经把这个清单按 v1/v2 拆开了**：

> v1 可达的字段：`title.text`、`series[].name`、`xAxis.data[]`、`yAxis.name` / `xAxis.name`，以及错误消息、警告里的列名。
> 只在 v2 才可达、v1 测的是不可达路径的字段（放到层 2 时再测）：`title.link` / `sublink`、`series[].label.formatter`、`legend.formatter`、`tooltip.formatter`、`aria.label` / `description`。

方案 §3 说"vitest 用 ECharts SSR SVG 渲染器**逐字段**打注入串"——照 M13 §4.3 的原清单逐字段做，会**花力气测 6 个 v1 不可达的路径**。**应按 THREAT_MODEL §2.3 的拆分做**：v1 测那 5 个可达字段 + 三个文本面（tooltip / 错误消息 / 结论），v2 字段留到层 2。

### 3.2 SSR SVG 测不了 tooltip（方案的两条要分工明确）

ECharts SSR + SVG 渲染器能测**标题、轴标签、类目、图例**（进 SVG）。但 **tooltip 在 SSR 下根本不渲染**（它是交互时创建的 DOM/canvas 层）。所以：

- vitest + SSR SVG → 测"字段进了 option 后，渲染出的 SVG 里没有可执行元素"
- Playwright 真机悬停 → **只有这条能测 tooltip**

方案把两条都列了 ✅，但要把**各自能覆盖什么**写死，避免后来人以为 SSR 那条覆盖了 tooltip。

### 3.3 Playwright 必须跑"后端托管 dist"，不能跑 vite dev / preview

CSP 是"后端返回 index.html 时设置"的（方案 §3 自己写的）。`vite dev` 和 `vite preview` 都**不带这个头**。所以 e2e 必须：`python -m app.server --open`（或不起 `--open`，直接 curl）→ 访问 `127.0.0.1:端口` → 悬停 tooltip。**否则测的是"没有 CSP 的配置"**，注入实测的结论无效。

顺带：CI 里**只在一个 Linux job 装 Playwright**（Windows runner 装浏览器慢且 flaky），并把 Python 测试和前端 build 放同一个 job（e2e 需要两者同时在场）。

### 3.4 `M13-图表方案建议.md` 三处仍写"多表 ≥ 8/10"

> **[已处理 · [30]]** 文档已随 `[30]` 进仓库并改名 `docs/roadmap/M13-图表方案.md`：文首加了 `[v4]` 注解，`:261`/`:300`/`:334` 三处已同步成 `9/10`，并新增 §12（开关 × 产出键表）。以下为评审时的原始记录。

`[25]` 已把 react 多表门槛修正为 **9/10**（`docs/gate/thresholds.json` 的 `m13.agents.react.multi.allowed_fail=["m10"]`），但 M13 方案文档**三处**还写着 `8/10`：`:261`（§8.2 结论行）、`:300`（§9 第 4 条）、`:334`（风险表"回归误判"行）。这份文档目前是 **untracked**（未提交），留着会误导下一次改门槛的人。

---

## 4. 验收条件修订

方案 §0 的验收有一处会**必然踩空**、三处**漏了**：

| 原文 | 问题 | 建议 |
|---|---|---|
| "重启后会话还在" | 后端重启**必然换 token** → 必须重新从命令行打开 URL。写成这样会被当成 bug | 改成"重启后端 → **重新打开 URL** → 历史会话仍在" |
| — | 注入实测结果没进验收 | 加："注入实测结论写进 THREAT_MODEL §2.3，且 DOM 断言在**托管 dist** 的路径上跑通" |
| — | "停止"没进验收 | 加："按停后 ① 后端在有限时间内停止（记录实际耗时）② `status` 落 `cancelled` ③ 立刻重问不撞 409" |
| "换主题和开关" | 无可观测断言 | 加："导出 PNG 返回非空 data URL，且文件名已清洗" |

---

## 5. 估时

方案合计 **2.5–4 周**，`plan.md:41` 写的阶段 5 是 **1.5–3 周**。方案自己承认"高于 plan.md 里阶段 5 剩下的估计"，但没写要改 `plan.md`。**DEVLOG 惯例是估时变化要记录 —— 更新 `plan.md` 的表格，理由：新增整个前端（原估只算 M13 后端三步 + 少量前端）。**

F0 的实际工作量比估的大：脚手架 + 托管 + token + CSP + **迁移** + CI job（含 Playwright）——2 天够，但要一次做对 1.1–1.4 四条。

---

## 6. 建议的 F0 顺序（一次做对，别返工）

1. 迁移函数（`ALTER TABLE ADD COLUMN`，幂等）→ 先跑通，否则后面所有涉及 feedback 的验证都跑不了
2. dist 托管 + **静态资源绕过 auth** + `--open`（fragment URL）
3. token 流转（读出 → sessionStorage → **同步** `replaceState`）+ 401 降级页
4. CSP 头 + **实测构建产物无内联 script**
5. CI job（lint / test / build / 上传 dist；Playwright 单 Linux job）
6. `sidecar.yml` 冒烟加 `GET /` + **断言 CSP 头存在**

F1 开始前把 1.7（prepare 清理列表）、1.8（开关 × 产出键表）、1.9（横竖开关去留）三条定下来——它们决定了前端与服务端白名单的接缝。

---

## 7. 一句话

**方向不用改，把 1.1–1.9 这九条按 F0/F2/F3 归位补上，估时改成 3–4.5 周，验收条件按 §4 改写。** 最该提前的不是 UI，是 1.3（迁移）和 1.5（停止语义）——前者决定"会话还在不在"，后者决定"按停是真停还是继续烧钱"。

---

## 附录 A — 核验闸门时发现的事实（不属于 F0–F5，但影响阶段 5 的验收可信度）

核这份评审时把闸门的两份新基线也核了一遍（`HEAD=513f6e1`），发现五条**与前端无关、但会挡在阶段 5 前面**的问题。除 A5 外，其余四条都有可复现的实测证据。

### A1. 新基线已提交，但参照基线自己被判成"有回归"

`docs/eval/gate_20261014_162428_react.json`、`gate_20261014_163133_workflow.json`（都在 `063f242` 上跑，`[28]` 已提交）的 `verdict` 段：

| | single | multi | 名单外错题 | 意外答对 | `regression_verdict` |
|---|---|---|---|---|---|
| react | 14/15 | 9/10 | `m09` | `m10` | **有回归** |
| workflow | 10/15 | 10/10 | `s06` | — | **有回归** |

问题不在"错了"，在于 `m13` 门槛（`allowed_fail`）是照 `cdaf0f6`/`9430354` 的**旧观察**预先登记的：react 多表写死"只允许 `m10` 错"，而这次是 `m09` 错、`m10` 对 —— 一进一出，`allowed_fail` 一条没命中，于是**参照基线自己被判成回归**。

这不是噪声问题，是**门槛标定问题**：`m09`/`m10` 这类"拒答失当 / 不调工具"的题在 temperature 0 下也会翻（`[28]` 说"复跑记波动"就是承认了这点）。**用一个逐题名单去卡一个会翻的 agent，每次跑都会随机触发一次假告警。**

建议把 `allowed_fail` 放宽到"该组可错题集合"（react 多表 → `{m09, m10}`；workflow 单表 → `{s02, s04, s06, s09, s12}`），或把判据从"逐题"改成"组内 ≥ min 且错题所属类别落在已知类别里"。

### A2. "复跑记波动"的证据没进仓库

`[28]` 的结论（"S 复跑 `m09`、`s06` 均通过 → 记为波动，第 3 步不回退提示词"）依赖 4 次单题复跑，证据是工作区里这 4 份 **untracked** 报告（实测：即 m09/s06 各两次、均答对）：

```
gate_20261014_165504_react.json     m09 → 无法回答：数据中没有客户年龄…   ✅
gate_20261014_165536_react.json     m09 → 无法回答：数据中没有客户年龄…   ✅
gate_20261014_165312_workflow.json  s06 → 1036 条                       ✅
gate_20261014_165603_workflow.json  s06 → 1036 条                       ✅
```

结论目前**不可从仓库独立复核**。要么提交这 4 份，要么在 `[28]` 里把复跑结果记成表格（题号 / 是否答对 / 时间）。

### A3. `labels_final: false` 与 `labeled_by: "…S 终审通过"` 自相矛盾

两份新基线的 `labeled_by` 都是 `"Hark 预标注（…）；S 终审通过（2026-10-15）"`，但 `labels_final` 仍是 `false`。根因在 `run_gate.py:160-161`：

```python
if "待 S 终审" in out["labeled_by"]:
    out["labels_final"] = False      # 只有 if，没有 else
```

**这个字段永远只会被写成 `false`，无法表达"已终审"**——正如方案 `[25]` 要求的那样"终审后重跑 `--verdict`"，键本应**消失**。实测（把 `labeled_by` 改成"S 终审通过"后重跑 `verdict()`）：`labels_final` 键**根本不出现**。所以两份基线里的 `false` 是**上一轮 `verdict()` 留下的陈旧值**——`labeled_by` 被改过，但没有重跑 `--verdict`。

二选一：① 补 `else: out["labels_final"] = True`，让字段能表达终态；② 保持"终态不写键"，那就必须**重跑 `--verdict`** 让键真正消失。当前"键在、值假"是第三种状态，最坏。

### A4. `thresholds_sha256` 在本机不可复现（行尾符）

`run_gate.py:37` 直接读原始字节算哈希：

```python
raw = open(THRESHOLDS, "rb").read()
... hashlib.sha256(raw).hexdigest()[:12]
```

而同一目录的 `verify_gate.py:162` 是**规范化过**的：

```python
data = open(...questions.py, "rb").read().replace(b"\r\n", b"\n")
```

本仓库 `core.autocrlf=true`，而 `.gitattributes` 只给 `data/eval/*.csv` 定了 `eol=lf`，`docs/gate/*.json` 没有例外 → 工作区签出为 **CRLF**。实测：

```
工作区原样(CRLF) sha256[:12] = 8703d010bbe3     ← 本机 --verdict 实际写出的
规范化 LF        sha256[:12] = 4992a4016355     ← 两份新基线里记的 / git 对象内容
```

**同一份 `thresholds.json`，本机跑出来的哈希和基线记录的不一样。** 哈希的用途（证明"这次用的是哪一版门槛"）当场失效——阶段 5 之后在本机跑 `--verdict`，会写 `8703d010bbe3`，看起来像门槛被人改过。

修法（任一）：`load_profile` 也做 `.replace(b"\r\n", b"\n")`；或 `.gitattributes` 加 `docs/gate/*.json text eol=lf`；或改用 `git hash-object` 口径。

### A5. `[29]` 的 commit 字段没回填

`DEVLOG [29]` 标题仍是 `commit <待提交>`，实际已提交为 `513f6e1`（PR #30，B70）。`[22]`–`[24]`/`[28]` 都填了。DEVLOG 规范要求每条记 commit SHA。

---

**这五条里 A1 和 A4 会直接影响阶段 5 的验收结论**：A1 让"改动前后对比"每次都报假回归，A4 让"用的哪版门槛"无法追溯。建议在 F0 之前先处理 A1 / A3 / A4 —— 都不大，但拖着会让阶段 5 之后的闸门数据不可比。
