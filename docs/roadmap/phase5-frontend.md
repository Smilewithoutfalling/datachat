# 阶段 5 前端方案（v2.1，2026-10-15）

> 来历：v1（工作区草稿，未入库）→ S 评审 `review-phase5-frontend-v1.md` → v2 → S 复核三处技术问题（aria 与删键自相矛盾、toolbox.dataView 冗余、cancel 的两个洞）→ v2.1，即本文。S 10-15 确认后随 F0 入库。
> 下文 [v2] / [v2.1] 标的是相对 v1 / v2 的改动。

基线 master 4497d2b。在 v1 的基础上吸收了评审 `docs/roadmap/review-phase5-frontend-v1.md` 和 S 10-15 的三个决定。标 **[v2]** 的是相对 v1 的改动。

## 0. 范围与验收
- 做：React + Vite + TS 的数据集面板、对话流、图表（M13 第 5 步）、可展开代码、👍👎、设置页。不做：层 2、Tauri 外壳、多用户。
- 验收：`python -m app.server --open` 一条命令启动，此后全程鼠标操作：
  1. 填 Key → 上传单表 / 多表 → **看预览确认数据读对了** [v2]
  2. 两种 agent 各问一次 → 看步骤、代码、图 → 换主题和开关
  3. **导出 PNG 得到非空 data URL，文件名已清洗** [v2] → 👍👎
  4. **重启后端 → 重新打开 URL → 历史会话还在，图表还在（走重放路径）** [v2]
  5. **按停后：后端在有限时间内停下（记录实测耗时），status 落为 cancelled，立刻重问不撞 409** [v2]
     - 耗时分两个数，分开记，不混成一个 [F3 前定，S 10-16]：
       - **感知延迟**（验收指标）：点"停止"→ 按钮变"正在停止…"（乐观 UI，同一帧）；最终态"已取消 / 已取消（未保存）"只来自 settle() 读到的库里 status。
       - **后端延迟**（只记录，不设门槛）：`POST /cancel` 返回 200 → 流里出现 error(kind=cancelled) + done / 库里 status=cancelled。检查点在"每产出一个事件之前"，所以上界 ≈ 当前这次模型调用的剩余时间（秒级到几十秒），这是架构选定的粒度，不是 bug；"< 1s"之类的门槛架构上达不到，不写。用假模型服务挂住 N 秒实测，记进 DEVLOG。
  6. **用 v1 的库启动一次：feedback 表出现，旧表行数不变**（写成测试）[v2]
  7. **注入实测结论写进 THREAT_MODEL §2.3，DOM 断言在后端托管的 dist 上跑通** [v2]

## 1. 架构
| 项 | 决定 |
|---|---|
| 托管 | FastAPI 托管 `ui/web/dist`。**`/` 和 `/assets/*` 不走 auth；`/charts/*` 仍接受 `?token=`；其余 API 都要 Bearer。** 加测试：不带 token 访问 assets 返回 200，访问 API 返回 401 [v2] |
| token | `--open` 打开 `127.0.0.1:端口/#token=…`，前端读出后存 sessionStorage，**在任何 await 之前同步 `replaceState`**。**遇到 401 统一进"会话已失效"页**，引导用户回到命令行重新打开（后端重启、新标签页都会走到这里）[v2] |
| CSP | 返回 index.html 时设置：`default-src 'self'; img-src 'self' data: blob:; script-src 'self'; style-src 'self' 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`。**F0 检查构建产物里没有内联 script**（CI 断言 grep 为 0）。实测 Vite 8.3.4 默认把 modulepreload polyfill 打进入口 chunk、index.html 无内联 script；仍设 `build.modulePreload.polyfill=false`（只跑现代 WebView/Chrome）。若将来非 0，找出来源去掉，不用 hash [v2.1] |
| SSE | fetch + ReadableStream 自写解析器（带 Authorization 头） |
| 停止 [v2.1] | **新增 `POST /messages/{id}/cancel`**：<br>• CAS 写库：`UPDATE … SET status='cancelled' WHERE id=? AND status='running'`，命中 0 行 → 409（已结束，不改已完成的轮次）；命中则置位该消息的 `threading.Event`<br>• `analyze_stream(cancel=…)` 每产出一个事件前检查一次，置位就提前收尾，产出 done（error_kind=cancelled）<br>• `stream()` 分流：`status = "cancelled" if r.error_kind == "cancelled" else ("ok" if r.ok else "error")`<br>• `stream()` 的 finally 也改 CAS：只在当前 status 仍为 running 时写 status/content/result_json；被 cancel 的轮次 result_json 留空，重放时前端按 status=cancelled 合成"已取消"的 done<br>• 维护 `done_seen`：没收到 done 又不是 GeneratorExit → 记为 error<br>• 粒度：正在进行的那次 LLM 调用或 exec 会跑完，和断开连接一样；接口价值在于**状态确定、不撞 409**<br>• 旧分析可能与新问题短暂并行，turn_history 只取 ok 轮次（app.py:184），不受影响 |
| 依赖 | react、echarts（echarts/core 按需引入）、react-markdown（不开 raw）、**remark-gfm**；开发依赖：vite、typescript、vitest、**jsdom**、@testing-library/react、eslint（react/no-danger）、prettier [v2] |
| Node [v2] | **本机和 CI 统一用 Node 24**（S 本机已有 v24.14.0，D:\Coding\nodejs）。`node_modules` 放在 `D:\Coding\claude\datachat\ui\web`；Playwright 浏览器只在 CI 上装 |
| 事件类型 [v2] | `scripts/gen_ui_types.py` 从 `app/core/events.py` 生成 `ui/web/src/generated/events.json`（EVENT_TYPES）和 `banned_keys.json`（BANNED_KEYS），CI 跑 `--check`，和 gen_eval_data 一样的做法 |

**停止的已定规则 [F2，S 10-16 确认]**
- 取消照常产出 fatal error + done（保留"done 之前有且只有一个终结事件"的不变式）；`error.message`、`AnalysisResult.error`、`messages.content` 在 cancelled 时一律是常量 `CANCELLED_MESSAGE`（"已取消"），不带内部异常或堆栈。前端只按 `kind` / `status` 分支，不匹配文案。
- **"已取消"只用于用户动作。** 非用户动作的终止一律 `status=interrupted`（`ERROR_KINDS` 含它；analyze_stream 不产出，前端重放按 status 合成 done(error_kind=interrupted)），前端给重试入口：后端重启清理遗留 running → `INTERRUPTED_MESSAGE`；SSE 客户端断开（关标签页、网络抖动）→ `DISCONNECTED_MESSAGE`。流中途抛异常、没收到 done → `status=error`、`STREAM_ABORTED_MESSAGE`，异常详情只进日志。
- **真 TCP 断开**（关标签页、进程被杀、断网）：分析跑在 SSE 生成器里，断开后在下一个事件 yield 时停下（最多晚一次模型调用），finally 落 `interrupted` + `DISCONNECTED_MESSAGE`。判据是显式的：只在 `except GeneratorExit` 里落 interrupted；默认兜底是 error + `STREAM_ABORTED_MESSAGE`（没预料到的结局是后端问题，不能把排查方向指向网络）。不留 running：分析已经停了，留 running 会让会话 409 到重启。真 uvicorn + 真 socket 的测试钉住。若以后要"断开后分析继续跑"，前提是分析挪出请求生命周期（后台 worker），那是另一个设计。
- **events 表里 cancelled 轮次的 answer 事件只作审计**：库里照存（events 是发生过什么的记录），但重放 / 展示一律以 status 为准，status=cancelled 时不展示任何 answer。以后做"重放全部事件"类功能必须保留这条过滤（turn.ts 的 replay / answerText 有测试）。
- **前端点停止的顺序**：先 `POST /messages/{id}/cancel` 并等它返回，再断开 fetch（或者不断开，等流里的 error + done）。反过来先断开，库里会落 interrupted。
- **status → 终止原因映射（前端用）**：ok → 正常；cancelled → "已取消"；interrupted → 已中断 + 重试；error → 失败，原因看流里 / result 里的 error_kind，重放时没有 result（stream_aborted）就只显示 content。messages 表没有 error_kind 列（技术债，见 DEVLOG [34] 未做）。
- `events.json` 带 `event_types`、`error_kinds`、`message_statuses` 和全部常量文案，`--check` 覆盖它们的漂移；测试另钉三条：service.py 写的 kind 恰为 `ERROR_KINDS` 去掉 interrupted；整个 app/ 只有 service.py 写 error_kind（评测记录自己的 `ground_truth` 以 (文件, kind) 列白名单）；app/ 里写进 status 的字面量都在 `MESSAGE_STATUSES` 里且每个都有人写。
- 检查点：`analyze_stream` 在每个事件产出前检查（answer 也是检查点），内部跑完、done 之前再查一次。late-cancel 窗口只剩 answer 发出之后到 done 之前的收尾记账（没有模型调用）。
- 晚到的取消算取消。**已知取舍**：answer 事件可能已经发出，但 status=cancelled、result_json 为空，这个组合会传到前端；写进 PR 描述和 DEVLOG。
- **前端：status 是最终真相源，流只作增量渲染。** 流里收到过 answer、但最终 status=cancelled → 当场保留气泡，标"已取消（未保存）"；刷新/重放后不出现（重放按 status=cancelled 合成"已取消"的 done）。不把 answer 补写回库。

## 2. 页面
1. 左栏：数据集、会话。**数据集详情含前 20 行预览**（F1 做）[v2]
2. 对话流按事件渲染：plan、code（折叠）、exec（折叠）、error（黄 / 红）、answer（markdown）、done（图、警告）。**重放时由前端合成 done**：`{type:'done', seq: max+1, data:{result}}`，reducer 只走一条路径 [v2]
3. markdown 的安全处理 [v2]：
   - `a` 覆写为 `rel="noreferrer noopener" target="_blank"`
   - 在测试里钉住 react-markdown 版本和 `javascript:` 过滤
   - `img` 依赖 CSP 的 `img-src` 兜底，这一条写进 THREAT_MODEL
4. 设置页：Key 从不回显；另有 base_url、model、超时。
5. 👍👎：`PUT /messages/{id}/feedback {rating: up|down|null, note?}`

## 3. 图表
- `prepare(option, ui)` 是纯函数，步骤：深拷贝 → 层 1 改动 → 开关（按图型过滤）→ **最后清理**：
  - **按后端 `BANNED_KEYS`（从生成的 json 读）逐层递归删除，除 renderMode 外**（与 charts.py `_walk` 同为递归匹配；toolbox、aria 均在表内，删掉即等价于 dataView 关闭、aria 默认 false）
  - 再强制 `tooltip.renderMode='richText'`
  - 单测：递归遍历清理后的 option，任何层级都不含被禁键（renderMode 只允许出现在 tooltip 下且值为 richText）[v2.1]
- 主题：自研 4 套。
- 开关 [v2]：
  - **去掉横 / 竖**
  - 保留数值标签、图例位置、堆叠、平滑、渐变（用普通对象写法）、圆角、排序（仅用户）、平均线和极值、dataZoom，产出键以 **M13 §12** 为准
  - 开关状态保留，不兼容的开关置灰且不生效
- 换图型：按 §6.3 的条件，**同步 boundaryGap**，换完重算开关兼容性 [v2]
- 层 1 面板：只能改 §3.2 的样式键，加 yAxis.min/max 和排序；改动存在 localStorage。
- 导出 [v2]：
  - **离屏实例**（init → setOption → `getDataURL({pixelRatio:2})` → dispose），可选"导出用浅色"
  - **文件名清洗**：去掉路径符和控制字符，限长

## 4. 安全测试分工 [v2]
| 手段 | 覆盖 | 不覆盖 |
|---|---|---|
| vitest + ECharts SSR SVG | 按 THREAT_MODEL §2.3，只测 v1 可达的字段：title.text、series[].name、xAxis.data[]、xAxis/yAxis.name | tooltip（SSR 不渲染） |
| vitest + testing-library | 错误、警告、结论、预览单元格、feedback note 都按文本渲染 | — |
| Playwright（单个 Linux job） | **跑在后端托管的 dist 上（带 CSP）**：用假模型服务（`tests/fake_llm.py`，独立进程的 OpenAI 兼容 HTTP 服务，后端只改 base_url，不是进程内对象），产出带注入串的图，真机悬停 tooltip，断言不产生 DOM 节点 | — |

v2 才可达的字段（link、formatter、aria 等）留到层 2 再测。

## 5. 后端改动
1. 静态托管（auth 边界）、`--open`、CSP。
2. feedback **单独建表**：message_id 做主键，外键级联删除；rating 为 NULL 时保留这一行；有意不保留改赞的历史；note 限长、清除控制字符，加进 THREAT_MODEL T9 的表面列表。
3. `GET /datasets/{id}/preview?rows=20`：所有值转成字符串，按 T9 原样返回。
4. cancel 接口和 `done_seen`（F2）。
5. `gen_ui_types.py --check`。
6. Streamlit 的文件等 S 验收之后再删。

## 6. 分步与估时（3–4.5 周；在 F0 的 PR 里同步改 plan.md）
| 步 | 内容 | 估时 |
|---|---|---|
| F0 | ① feedback 表 + v1 库测试 ② 托管、auth 边界、`--open` ③ token 流转 + 401 页 ④ CSP + 内联检查 ⑤ CI job（Node 24：lint/test/build/上传 dist；Playwright 用单个 Linux job，和 pytest 同 job）⑥ sidecar 冒烟：`GET /` + 断言 CSP 头存在 | 2–3 天 |
| F1 | 数据集（含预览）、会话、设置 | 2–3 天 |
| F2 | SSE、事件渲染、重放合成 done、cancel、👍👎、gen_ui_types（**完成，DEVLOG [34]**） | 3–5 天 |
| F3 | ECharts、prepare、主题、开关、换图型、导出、注入实测 + THREAT_MODEL | 4–5 天 |
| F4 | 层 1 面板 | 2–3 天 |
| F5 | S 验收轮次、删 Streamlit | 3–5 天 |

**F3 已定 [S 10-16]**
- **假模型服务**是 F3/F4/T11 所有异步测试的公共设施：独立进程的 HTTP 服务，接口形状同真模型（OpenAI 兼容 chat/completions，产品代码只改 base_url 指过去，不 monkeypatch）。行为由请求控制、无副作用状态：按 model 名分派场景（如挂住 N 秒、可控失败、控制流式速率）。至少支持：挂住指定时长、可控失败（HTTP 5xx / 超时 / 坏响应）、控制 token 流速率。F3 停止测试、T11 错误文案测试、F4 重试测试都复用它，不另写。
- **ECharts 原样渲染**：option 在后端已过 BANNED_KEYS（app/tools/charts.py），前端不做二次解释——不 eval、不执行 formatter 字符串、不动态拼 option，只"原样交给 ECharts"。
- 测试：按需引入的 ECharts 组件覆盖**后端可能产出的全部图表类型**（从后端导出的类型清单比对，不是只测当前用例用到的几种）；渲染时不产生外部资源请求（Playwright 断言零外部请求，不只靠 CSP）。
- T11 单独 PR，不跟 F3 合。

**F3-ECharts 第一步：原样渲染 + 图型覆盖 + 零外部请求（S 10-16 定稿）**

范围：只做"后端出的 option 原样画出来"。`prepare()` 只做最小一层（BANNED_KEYS 递归清理 + 强制 `tooltip.renderMode='richText'`）。主题、开关、换图型、导出、注入实测放到后面几步。

已定：
1. **依赖**：`echarts` 锁精确版本 `6.1.0`（写 package.json 时不带 ^；Apache-2.0）。只从 `echarts/core` 按需引入，不 import `echarts` 全量包；ESLint `no-restricted-imports` 禁止 `import … from "echarts"`。lockfile 用 Node 24 生成。
2. **renderer 用 canvas**（`CanvasRenderer`），产品里不注册 SVGRenderer。理由：
   - 主要理由：SVG renderer 会把类目名、数据标签这些来自用户数据的字符串作为 `<text>` 节点插进 DOM。这样 THREAT_MODEL §2.3 的"用户字符串不进 DOM"就从结构上的事实，降成了"依赖 ECharts SVG renderer 自己的转义实现"：要去核实它内部用的是 textContent 还是拼 innerHTML，要为它写测试，ECharts 每升一次级都要重新验。canvas 把文本画成像素，DOM 里根本没有文本节点，这一面在结构上就不存在。
   - 规模：5000 点的夹具在 SVG 下会生成约 5000 个 DOM 节点，产品里会慢，而且慢的程度正好随边界夹具一起涨；canvas 一次绘制就完成。
   - 导出 PNG：canvas 的 `getDataURL({type:'png', pixelRatio:2})` 直接可用。矢量导出这一步不做；以后真要做，单独走一条 SVG renderer 的导出路径，到时再评估一次 §2.3。
   - CSP：canvas 不需要额外放开什么，`img-src 'self' data: blob:` 够用。
   - vitest 里用 SSR SVG（`init(null, null, {renderer:'svg', ssr:true})`）只作断言工具（§4 的分工），只在测试文件里注册 SVGRenderer。
3. **图型清单的来源是后端白名单，不是只看 KINDS**：`gen_ui_types` 新增 `chart_schema.json`，内容是 `KINDS`、`_KIND_SERIES_TYPE`、`_ENUMS`（`series.type` ∈ {bar,line,pie,scatter}、`xAxis.type` ∈ {category,value}、`yAxis.type` ∈ {value}、`legend.type` ∈ {plain,scroll}）以及 `_ALLOWED` 的顶层键（color/title/tooltip/legend/grid/xAxis/yAxis/series）。
   - 前端 `charts/register.ts` 维护一张"白名单项 → ECharts 组件"的显式映射表（BarChart、LineChart、PieChart、ScatterChart、TitleComponent、TooltipComponent、LegendComponent（含 plain 和 scroll）、GridComponent、CanvasRenderer）。
   - `tooltip.trigger`、`legend.orient` 这类不需要额外组件的枚举，也在映射表里显式写成"无需组件"，保证后端新增任何枚举值时都必须有人在这里确认过。（已核对：echarts 6.1.0 的 `LegendComponent` 的 install 同时装了 plain 和 scroll。）
   - vitest 防漂移：生成清单里的每个顶层键和每个枚举值都必须在映射表里有一项，少一项就红；映射表里多出的项也要红（无人产出的组件不预留，和 `_ALLOWED` 的规则一致）。
   - 说明：后端**没有** ECharts 的 time 轴。时间列走 `xAxis.type='category'`，类目是 ISO 字符串，再加 `axisLabel.hideOverlap`（charts.py:256、261）。所以不注册 time 轴，夹具里的"时间列"例子测的是这条路径。
4. **夹具由后端真实产出，不手写**：`gen_ui_types` 用 `build_option` 在固定的合成 DataFrame 上生成 `chart_fixtures.json`，CI 跑 `--check` 防止漂移。每个例子带 id，至少包括：
   - 五种 kind 各一个正常例；
   - 时间列作 x（line、area）；
   - 缺失类目（显示为「（缺失）」）和缺失数值（null）；
   - 长表 series：恰好 `MAX_SERIES`=20 个系列；
   - 饼图：恰好 `MAX_PIE_SLICES`=50 个扇区；
   - 点数边界：cartesian 恰好 `MAX_POINTS`=5000（truncated=false）和 5001（truncated=true，截到 5000）；scatter 同样做 5000 和 5001。
     - 5001 的期望写死：输入 5001 行时，`build_option` **接受并截断**，产出 5000 点、truncated=true，并且通过 `validate_spec`（实测，见下）。这是一个能渲染的成功例，不是失败例。
     - "已经产出的 spec 超过 5000 点 → `validate_spec` 拒绝"属于另一类期望，留在后端 `tests/test_charts.py::test_too_many_points_rejected`，**不进 chart_fixtures.json**。夹具文件里只放成功例。
   - 多 y 宽表；带标题和不带标题各一个。
   - 体积：全部存成实际产出的 option，不存生成参数。只存参数就要前端自己展开数据，又多出一个"前端生成器 vs `build_option`"需要对齐的面，夹具本来就是为了消掉这个面。系列 20 和点数 5000 是两个独立的边界，不做组合。
   - 格式：用缩进 JSON（`json.dumps(…, ensure_ascii=False, indent=1)`），`--check` 按字节比对。这样 `build_option` 一改，从 diff 就能看出改了哪个值；紧凑 JSON 只有一行，每次 diff 都是整份重写。实测（2026-10-16，固定 seed）：bar 5000 点紧凑约 71 KB，indent=1 约 126 KB；scatter 5000 点紧凑约 84 KB，indent=1 约 214 KB，因为每个 [x, y] 都被拆成 3 行。整份文件估计约 0.75 MB，生成后实测写进 DEVLOG。
   - 不写自定义序列化器（S 10-16）。indent=1 已经做到行粒度，改一个点只动几行。自定义序列化器能省一些体积（scatter 从 214 KB 降到约 114 KB），diff 也稍微紧凑一点，但数据形状每变一次都得重新检查它，`json.dumps` 没有这个负担。将来 diff 真的太吵，就把大数据夹具拆到单独的文件，这样改小夹具时不会碰到大文件；不换序列化器。
   - 将来某个图型（比如热力图）大到不适合全存：改用后端固定 seed 的确定性生成器产出，测试只做轻量断言（渲染不报错、图数正确），不逐点比对。仍然不在前端生成数据。
5. **渲染组件** `EChart({option})`：一张图一个实例。
   - 挂载：`init(div, null, {renderer:'canvas'})` → `setOption(prepare(option), {notMerge:true})`。
   - 尺寸：每个实例自己挂一个 `ResizeObserver` → `instance.resize()`。
   - 卸载：先 `observer.disconnect()`，再 `instance.dispose()`。
   - **截断必须让用户看到**：truncated=true 的图如果不提示，会让人以为看到的就是全部数据。这条通道已经有了，本步不新建：后端 `result.chart_warnings`（app/core/result.py:110）在截断时产出"图表「名」数据点超过 5000，只显示了前面的部分"（tests/test_chart_slot.py:75），由 `app/core/service.py`（:257 工作流，:524 ReAct）并入 `result.warnings`，F2 的 TurnView 把它和其他警告一起显示（TurnView.tsx:87）。前端不再根据 spec.truncated 自己拼一条提示，保持单一来源，不会重复显示。本步补两条测试：vitest 里用 5001 的夹具，断言图和截断警告同时出现；后端断言两条链路上 truncated=true 时 `result.warnings` 里都有这条警告（目前只测到 chart_slot 层）。
   - 一轮最多 4 张结构化图（`MAX_CHARTS`）+ 1 张 PNG。TurnView 按 `result.charts` 的顺序渲染：option 项用 `EChart`，png 项用 `<img src="/charts/<name>?token=">`（同源，`img-src 'self'` 允许）。
   - option 变化时整体重设（notMerge），不做增量合并。
6. **prepare v0**：深拷贝 → 按 `banned_keys.json` 递归删除（renderMode 除外）→ 强制 `tooltip.renderMode='richText'`。这是**纵深防御**：第一道仍是后端的 `validate_spec`（charts.py），前端这一层只在后端校验有漏洞时兜底，不能当成前端校验，也不回验。

验收：
- vitest：
  - 每个夹具 × 按产品映射表注册的组件，用 SSR SVG 渲染，断言 ECharts 没有打印任何 warn/error（缺组件时 ECharts 会报 "Unknown series" 之类，以 console spy 断言为 0），且产物里有对应 series 的图元。
  - 第 3 条的防漂移测试双向都测。
  - prepare：递归遍历清理后的 option，任何层级都不含被禁键；renderMode 只出现在 tooltip 下，值为 richText；不修改输入（深拷贝）。另外加一个人为塞了被禁键的对照例，证明清理确实执行过。
  - EChart 组件：挂载、卸载 4 张图后 init 和 dispose 次数相等，`getInstanceByDom` 为空；resize 由 observer 触发。
- Playwright（fake project，后端托管 dist，带 CSP）：
  - 假服务新增 scenario `chart-<kind>`：codegen（工作流）和 act（ReAct）回一段调用 `chart('<kind>', df, …)` 的代码，列由 e2e 固定 CSV 决定。kind 不在 KINDS 里时返回 400；和 @step 组合也返回 400（fail loud）。
  - 新 scenario 都要有单测，不能"写了没验证"。`tests/test_fake_llm.py` 补：解析的合法和非法例（含未知 kind、带 @step），以及真链路下五种 kind 各一条，断言 `result.charts` 的 kind 正确、spec 通过 `validate_spec`。
  - 已有 scenario 的覆盖顺手补齐。现状：`fail-CODE` 在 handler 层（`test_targets_first_call_by_default_and_named_step_otherwise`）和真链路（`test_real_chain_fail_code_goes_through_product_classification`，500 重试和 401 不重试）都有测；`slow-Ns` 只在 handler 层断言了睡眠次数，没有真链路测试。本步补一条 `slow-1s` 真链路测试，断言分析成功，且总耗时 ≥ 调用次数 × 1 s。
  - 五种 kind 各问一轮，断言出现 canvas、图数和 `result.charts` 一致；刷新后走重放路径，图仍在。
  - **零外部请求**：`page.on('request')` 记录所有非同源 URL，断言为空；同时断言无 CSP 违规（`securitypolicyviolation` 为 0）。两条合起来才能说明 ECharts 没尝试加载外部资源：CSP 拦下的请求不会进入网络，单看 request 事件不够。对照例：断言监听器确实收到了同源的 `/assets/*` 请求，证明监听器在工作。
- 性能数（只记录，不设闸门）：build 后的 chunk 增量（按需引入前后对比）；`prepare` 在 5000 点夹具上的耗时（深拷贝加全量递归遍历，每次 option 变化都会跑）。超过几十毫秒的话，在 DEVLOG 里标出来，和 S 讨论要不要优化。

不做（后续步骤）：主题、开关、换图型、导出、注入实测和 THREAT_MODEL 更新、层 1 面板。

第一步已完成：PR #41（acaa8bf），DEVLOG [37]。

**F3 后续拆分（草案，待 S 评审）**

| 步 | 内容 | 为什么排在这里 | 估时 |
|---|---|---|---|
| 第二步 | 注入实测 + THREAT_MODEL §2.3 结论（§0 验收 7） | **顺序上必须**：P4、P5 的结论直接决定第三步 prepare 的设计范围（见下文第二步第 1 条）。另外，第二步只加测试、不动产品 UI；之后每一步改 option，都要重跑这条注入回归 | 1–1.5 天 |
| 第三步 | prepare 完整版的管线骨架（深拷贝 → 层 1 → 开关 → 清理）+ 后端 `containLabel` 改 `outerBounds`，然后从注册表里去掉 LegacyGridContainLabel；如果第二步判定 `{}` 会被解析，再加上对用户来源字符串的转义 | option 处理层，靠自动化测试判绿。两项改的是同一条 option 路径，合起来正好消掉唯一一条跨端隐式契约 | 1 天 |
| 第四步 | 自研 4 套主题 | 视觉层，靠人眼验收。和第三步分开（S 10-17）：验收方式不同的东西放进同一个 PR，测试绿了主题还在来回调，已经能用的那一半也会被拖住 | 1 天 |
| 第五步 | 开关 + 换图型（兼容性一起算）+ 回填 M13 §12 第三列 | 两者都要用到"当前图型能用哪些开关"，拆开做就得写两遍 | 2 天 |
| 第六步 | 导出 PNG（离屏实例、文件名清洗、可选浅色）（§0 验收 3） | 导出的应该是用户最终看到的样子，所以依赖主题和开关 | 0.5–1 天 |

每一步开工前，先在本文写好"已定"规则和验收标准，由 S 评审。下面只展开第二步。

**F3 第二步：注入实测（S 10-17 评审通过；已实现，DEVLOG [38]）**

实测结论：tooltip（richText）会解析用户字符串里的 `}`，其余位置都不解析，模板占位符哪里都不替换。所以第三步 prepare **必须**处理进 tooltip 的 `{` `}`。详见 THREAT_MODEL §2.3。实现时的两处偏离见 DEVLOG [38]：chart_error 改成单独一个 `inject-error` 场景；第二张图的标题用 P4+P5。

目标：§0 验收第 7 条，"注入实测结论写进 THREAT_MODEL §2.3，DOM 断言在后端托管的 dist 上跑通"。本步只测 v1 可达的字段；v2（层 2）才可达的字段写明"未测"，到层 2 再测。

覆盖现状（逐条给测试名，不凭印象）：
- 已有，vitest：`views.test.tsx`「预览：表头、单元格按文本渲染，注入串不变成元素…」；`f2.test.tsx`「markdown：版本钉住；不渲染 raw HTML；javascript: 链接被过滤…」，同文件「提问：事件实时渲染（计划、折叠代码、执行）…」只给 plan 文本带了注入串（:37），代码面和执行面没有；「👍👎：…补充说明按文本渲染」覆盖 note。
- 已有，托管 dist：`e2e/f1.spec.ts` 只覆盖预览面。
- **缺**：图表（标题、系列名、类目、轴名、图例、tooltip）在任何层级都没有注入测试；错误或警告文案、结论、代码面板在托管 dist 上没有测试（`grep -n "INJECT\|onerror" ui/web/e2e/*.ts` 只命中 f1.spec.ts）。

已定（待评审）：
1. **载荷常量**放在 `tests/fake_llm.py` 的 `INJECT_PAYLOADS`，由 `gen_ui_types` 导出给前端。前端不自己再写一份，避免两边漂移。每条都短于 `NAME_MAX`=100，这样不会被截断，攻击串能完整到达：
   - P1 `<img src=x onerror="window.__pwned=1">`
   - P2 `"><svg onload="window.__pwned=2">`
   - P3 `javascript:window.__pwned=3`
   - P4 `{a}{b}{c}`：ECharts 的模板占位符。观察默认 tooltip 会不会把它替换掉，只记录现象。
   - P5 `{x|富文本}`：rich 语法（`rich` 已在 BANNED_KEYS 里）。观察它是原样显示，还是被当成样式标记。
   P4、P5 不是代码执行面，但会造成**视觉欺骗或数据篡改**（S 10-17），所以不能只"记录现象"，必须对每个渲染位置给出明确的是或否：
   - P5：在 richText 模式下（canvas tooltip 必须用这个模式），用户数据里的 `{x|…}` 会不会被当成富文本解析？如果会，攻击者就能改显示样式：把某个数染灰、缩小、藏起来，图看起来说的是一个数，实际数据是另一个。
   - P4：类目名或系列名里的 `{a}{b}{c}` 会不会被某个模板替换成系列数据？如果会，图上显示的数字就不是真实数据。
   - 结论直接决定第三步：任一位置答"是"，第三步 prepare 完整版就**必须**对用户来源的字符串做 `{}` 处理。ECharts 的 rich 语法没有转义符，具体做法（比如换成全角字符、加零宽字符，或者改由前端提供 formatter 函数自己拼 tooltip）在第三步方案里定。全部答"否"，就在 THREAT_MODEL 里记一条"已确认不解析（echarts 6.1.0）"，关掉这个面；以后升级 echarts，靠第二步的回归测试重新判定。
   - 判定方法：见第 4 条的 `fillText` 记录。
2. **假服务新增 scenario `inject-<kind>`**，kind 取 KINDS。行为同 `chart-<kind>`，但有三处不同：
   - `title=` 传 P1；
   - 写代码的那一步多调一次 `chart()`，传一个不存在的列名（取 P1），让 `chart_error` 带着载荷进 `result.warnings`；
   - 结论文本里拼上 P1–P3。
   CSV：列名用 P2、P3，类目值用 P1–P5，另有一个系列列，取值也是 P1–P5。这样系列名、轴名、类目、图例、饼图扇区名都由真 builder 产出，不走捷径。
   - **series.name / legend 的来源**（已对照 charts.py 确认）：宽表的 series.name 是列名（`_wide`，`_clean_str(c, NAME_MAX)`）；长表（`series=`）的 series.name 是**系列列里的单元格值**（`_cat` 之后再 `_clean_str`），这是列名之外的另一个来源；饼图的扇区名是类目值（`_cat`）。加工只有三种：控制字符换成空格、去掉首尾空白、超长截断并加"…"，不拼后缀。builder 不设 `legend.data`，图例由 ECharts 从 series.name（饼图从扇区名）推出来，所以这一个字符串会出现在**图例和 tooltip 的系列名两个位置**。cartesian 和 scatter 的图例只在多系列时显示。所以写代码那一步对 cartesian 和 scatter 调两次 `chart()`：一次宽表多 y（列名进图例），一次长表 `series=系列列`（单元格值进图例）。饼图只调一次（单 y）。再加上 chart_error 那一次，一轮最多 3 张图，在 MAX_CHARTS=4 以内。
   - **CSV 用标准库写**：由 `gen_ui_types` 用 `csv.writer` 生成，和载荷一起导出到 `inject.json`（`{payloads, csv}`）；e2e 直接上传这份 CSV，不在 TS 里手拼。载荷里有 `<`、`"`、`{`、`|`，手拼的话会把 CSV 结构撑坏，测试红了看起来像注入有问题，其实是夹具自己坏了。另加一条后端单测：pandas 把这份 CSV 读回来，列名和单元格值逐个等于载荷。解析规则同 chart：未知 kind → 400；带 @step → 400。`tests/test_fake_llm.py` 补单测：解析的正例和反例；两种 agent 各跑一次真链路，断言 `result.charts` 里有图，warnings 含载荷，结论含载荷。
3. **夹具**：`chart_fixtures.json` 增加 bar、pie 两个注入例（由 `build_option` 用载荷列名、类目和标题产出）。vitest 用 SSR SVG 渲染，断言：
   - SVG 串里载荷只以转义形式出现（`&lt;img`），没有原样的 `<img`、`onload=`、`onerror=`；
   - 产物里有对应 series 的图元（证明载荷确实到了渲染器，这是攻击能成立的前提）。
   注意 SVG 只是断言工具，产品用 canvas，结论要按 canvas 写（见第 5 条）。
4. **托管 dist 上的 e2e**（`e2e/f3-inject.spec.ts`，fake project，带 CSP）：
   - `addInitScript` 挂一个 MutationObserver，记录全页新增元素的 tagName 和属性名，同时 `page.on('dialog')` 一触发就判失败。
   - bar、pie 各问一轮，然后展开代码面板（代码里有载荷字面量，这也是一个面）。
   - `addInitScript` 再包一层 `CanvasRenderingContext2D.prototype.fillText`（以及 `strokeText`），记录每次画出的字符串，原样转调，不改行为。
   - **tooltip 真机悬停**：在柱子或扇区的位置 hover，再加两道对照，证明 tooltip 真的画出来了；否则"零新增元素"可能只是因为根本没 hover 到：
     - fillText 记录：hover 之后出现了新的绘制字符串，内容包含被 hover 的类目或系列名。这条是确定性的，不受动画时序影响；
     - 像素：hover 前后各截一次 canvas，结果不同。**截图前要先等画面稳定**：连续两次截图逐字节相同才算稳定，有上限次数，超过就判失败并输出截图。ECharts 的入场动画和 tooltip 的过渡都会让单次截图的时机不确定。不改产品的 `animation` 或 `transitionDuration` 来迁就测试，那会让测试走的路径和产品不一样。
   - **P4、P5 的判定**：在 fillText 记录里，按位置（标题、轴标签、图例、tooltip）检查载荷字面量 `{a}{b}{c}`、`{x|富文本}` 是否原样画出。原样出现就是"不解析"；只出现"富文本"而没有 `{x|`，或者 `{a}` 被替换成了数值，就是"解析"。每个位置的结论写进 THREAT_MODEL。
   - 断言：
     - `window.__pwned` 为 undefined；没有触发 dialog；
     - 新增元素里没有 `on*` 属性；没有 `href` 或 `src` 以 `javascript:` 开头的元素；没有新增 img、svg、script、iframe、object、embed；
     - 每个 `.echart` 容器的 `textContent` 为空，后代只有 div 和 canvas（文本全画成了像素）；
     - 警告、结论、代码面板里载荷按文本出现（`toContainText`），且这些区域没有新增上述标签；
     - 零 CSP 违规，零外部请求（复用 f3-charts 的监听器和同源对照）。
5. **THREAT_MODEL §2.3** 的"验证（第 5 步）"一段改写为结论：
   - 每个面怎么测、哪个文件里测，结果是什么；
   - P4、P5 的实际现象；
   - 未测字段写明"v2 才可达，层 2 时测"：title.link / sublink、label.formatter、legend.formatter、tooltip.formatter、aria.*；
   - prepare 的纵深防御只在 vitest 层测过（人为塞入被禁键的对照例），托管 dist 上不可达，因为后端 `validate_spec` 先拒了。

验收：上面第 2–4 条的测试全绿；THREAT_MODEL 已改；DEVLOG 写一条。

不做：v2 字段的注入；prepare 完整版；任何产品 UI 改动。如果实测发现 P4、P5 显示错乱，只记录现象，修不修和 S 讨论。

## 7. 与前端并行，不在 F 路径上
- 错误文案脱敏（THREAT_MODEL T11）：单独一个 PR，F2 之后做；先定规则再改阶段 3/4 的代码。
- A1 自动复跑规则：单独一个闸门 PR，赶在下一次跑闸门之前做（比如验证 B70 时）。
- [30] 的 SHA（4497d2b）随 F0 一起回填（已做，见 DEVLOG [31]）。
