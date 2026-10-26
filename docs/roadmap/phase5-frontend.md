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
  - 开关状态保留，不兼容的开关不渲染且不生效（F4 迭代 V1 起；之前是置灰）
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

**F3 第三步：用户字符串规范化 + outerBounds + prepare 管线骨架（S 10-17 评审通过，含评审补充）**

输入：第二步实测（THREAT_MODEL §2.3、DEVLOG [38]）和 S 10-17 的三轮评审。要处理三件事：
- tooltip 的 richText 会解析用户字符串里的 `{` `}`（借样式时可以在数值列伪造数字）；
- `\n` 会参与排版（真值配上假标签）；
- `grid.containLabel` 要求前端注册 LegacyGridContainLabel，这是唯一一条跨端隐式契约。

覆盖现状（grep 结果）：
- `grep -o "_clean_str(" app/tools/charts.py` 共 19 处（含定义，`app/` 其他文件 0 处）。除了构造 option 的那些，**还有 5 处在拼消息**：`charts.py:77`、`:140-141`（ChartError："列 … 不存在；可用列：…"）、`:542`（internal）、`:584`（`_msgs`）、`:613`（截断警告里的标题）。
- 其中 ChartError 会进 ReAct 的工具回执（`react_agent.py:210-211`，"chart() 未出图：…"），模型会照着"可用列"重新传列名。

已定（待评审）：
1. **规范化放在 option 构造完成之后的一处，不放在 `_clean_str` 里**。这一条和 S 上一轮的设想不同，理由是上面那 5 处消息出口：
   - 如果在 `_clean_str` 里把 `{` 换成 `｛`，"可用列：｛a｝…"就会回到模型那里，模型照抄全角列名再调 `chart()`，结果是"列不存在"的死循环。这是功能 bug，不只是显示失真。
   - 所以新增 `_display_safe(option)`：在 `build_option` 返回之前递归遍历整个 option，**每一个 string 值**都做 `{`→`｛`（U+FF5B）、`}`→`｝`（U+FF5D）、`\n`→空格（`\r` 已经在 `_CTRL` 里）。`\t` 不处理，第二步实测它不参与排版。
   - 一处就能覆盖 v1 的全部字符串，以后新增字段也会自动覆盖，因为它遍历的是产物，不是登记表。消息、数据表、结论文本都不经过这里，保持原文。
   - 结构上的理由（S）：`_clean_str` 负责"字符串怎么变成模型看得到的文本"，`_display_safe` 负责"字符串怎么变成画布像素"，两条消费路径。渲染面的规则（花括号、换行，以后可能还有零宽字符）只属于后者。
   - **顺序写死**：`build_option` → `_display_safe` → `validate_spec`。闸门会拒绝任何 `{`，如果规范化放在校验之后，每张图都会被拒，而且是全量红。
   - `\t` 不处理，依据（第二步实测不参与排版）写进代码注释，因为 `_CTRL` 本身就放过了它。
   - 代价：名字里带花括号或换行时，标题、轴标签、图例、扇区标签也会跟着变成全角或空格。这样的名字很少，全角在视觉上几乎看不出差别。
2. **`validate_spec` 加闸门 `_check_strings`**：
   - 和 `_walk` 分开，单独递归遍历整个 option，**不看规则表**。任何 string 值（以及 dict 的键）含 ASCII `{`、`}`、`\n` 就报问题，整图拒绝。
   - 单测里给 `_ALLOWED` 临时加一个新字段，证明闸门照样能拦下（防"只覆盖枚举到的部分"，S 10-17）。
   - **字符集只定义一份**：模块常量 `DISPLAY_UNSAFE = {"{": "｛", "}": "｝", "\n": " "}`，`_display_safe` 和 `_check_strings` 都从它读。漂移测试：任取含有全部不安全字符的字符串，经过 `_display_safe` 后必须通过闸门；再给常量临时加一个字符，两侧必须同时生效。
   - **拒绝路径单独测**：对 builder 的产物来说，规范化之后闸门永远不会触发，所以要手工构造含 `{` 和 `\n` 的 spec（绕过 builder），断言 `validate_spec` 拒绝。这和"给 `_ALLOWED` 加字段"不是一回事：后者测的是遍历覆盖，前者测的是拒绝本身。
   - 职责划分：规范化负责把字符串变干净，闸门负责保证结果干净。builder 漏掉一处时，闸门变红，变红的原因记作 `ChartBugError`。
3. **outerBounds 替换 containLabel（后端 + 前端，同一个 PR）**：
   - `_cartesian` 和 `_scatter` 的 grid 改成 `outerBoundsMode: "same", outerBoundsContain: "axisLabel"`。依据是 echarts 6.1.0 官方注释，原文称两者等价（`types/dist/shared.d.ts`：「`grid.containLabel` is equivalent to `{outerBoundsMode: 'same', outerBoundsContain: 'axisLabel'}`」）。但同一处注释也写了 `'axisLabel'` "differs slightly from the previous option `containLabel` but more precise"，所以方案和 DEVLOG 都写成**官方称等价、更精确、和旧行为略有差异**，不写成"等价写法"。
   - **下限差异**：`outerBoundsClampWidth/Height` 默认是 `['25%', '25%']`（`GridModel.js:56` 的 `OUTER_BOUNDS_CLAMP_DEFAULT`），为了容纳标签，grid 最多只能缩到原尺寸的 25%。legacy 的 containLabel 没有这个下限。新增夹具 `long-labels-bar`：bar 图，3 个类目，每个约 120 字（类目少，不会被 hideOverlap 隐藏）。断言轴标签都在画布内。如果真的溢出，就在 DEVLOG 记成已知差异并写明是 clamp 导致的，**不调** `outerBoundsClampWidth`。调成 100% 等于绕开官方下限，只是把"图被压扁"换成"图看不清"。
   - 选等价写法而不是 `'all'`（`'all'` 会把轴名也算进去）：本步只做机械替换，靠自动化测试判绿。要不要把轴名也包进去属于视觉决策，放到第四步主题里由人眼定。
   - `_ALLOWED.grid`（`charts.py:336`）删掉 `containLabel`，加上这两个键，让"option 里不可能再出现 containLabel"成为闸门保证的事实，前端摘掉组件才有依据。另加一条断言：全部夹具的产物里都不含 `containLabel`；`_ENUMS` 加 `("grid","outerBoundsMode"): {"same"}`、`("grid","outerBoundsContain"): {"axisLabel"}`。重新生成 `chart_schema.json`。
   - `register.ts`：`ENUMS` 加对应的两项（都是 `NONE`）；`grid` 去掉 `LegacyGridContainLabel`，同时删掉那段"跨端隐式契约"注释。双向比对测试会强制两边对齐。
   - 回归：`charts.test.ts` 现有的"零 `[ECharts]` log"断言继续保留。新增 SSR 断言：每个直角坐标系夹具里，每个轴标签 `<text>` 的锚点都在画布内。**布局差异做自动断言**：从 SSR 产物里取第一根柱子的 x 和 width，替换前后各取一次（替换前的值作为常量写进测试，并注明来源 commit），要求差异小于 5%。SSR 和 canvas 用的是同一套布局引擎。
   - 零 `[ECharts]` log 断言留在 **vitest**，不挪到 e2e。生产构建里 `__DEV__` 分支被去掉，那条 log 根本不存在，放到 e2e 就成了空断言，会出现和 fail-CODE 一样的假绿。
4. **prepare 管线骨架**：签名改成 `prepare(option, ui)`，`ui` 本步只有空类型 `UiState = {}`。步骤固定为深拷贝 → `applyLayer1` → `applySwitches` → `cleanup`（删被禁键 + 强制 richText）。前两步本步是恒等函数，导出给测试用；形参写成 `_ui`（tsconfig 开了 `noUnusedParameters`）。单测：
   - 两个恒等步骤的输出和输入 `JSON.stringify` 后逐字节相同，`prepare` 的整体输出和改动前的 v0 逐字节相同；
   - 输入不被修改；
   - 往 `applyLayer1` 的测试替身里塞一个被禁键，最终产物里没有（证明清理在最后）；
   - 现有的递归不含被禁键断言保持不变。
   - prepare 耗时：vitest 对 5000 点夹具跑 20 次，取中位数打到日志并写进 DEVLOG，不设阈值（方案已定"要记录"，原来没做）。
   - 前端**不**镜像 `{}` 规范化：v1 没有外部 option 输入；v2 层 2 的 patch 要重新走 builder 和 `validate_spec`，闸门覆盖。前端如果再做一遍，就等于两处规则，以后会漂移。
5. **注入回归**：
   - `INJECT_PAYLOADS` 新增 P6 `x}{__EC_aUTo_4|999`（借样式）和 P7 `上\n下`（换行），加进类目。类目顺序要重新验证：标签隔一个画一个，必须保证 P4–P7 都在被画出来的位置上。悬停点加上 P6、P7。
   - `inject.json` 增加 `display`：由后端 `_display_safe` 算出每个载荷的期望显示串，前端不另写一份。
   - **判定表改判据，不改期望值的形状**：`note()` 改成用 `includes(display[P])` 判 raw，不写成"不含原串、也不含 `{a`"这种多重否定。tooltip 那两格从 `PARSED` 变成 `R`。commit 里写清原因："后端 `_display_safe` 把 `{}` 规范化为全角，richText 包装不再能被提前闭合"。
   - P6 另加断言：tooltip 里出现了 `display[P6]`（证明悬停确实命中），并且没有任何 `900` 字重的绘制串等于 `999`。P7：tooltip 里 `上 下` 是一次绘制，不拆行，真值和它在同一个 y。
   - `chart_fixtures.json` 的注入例重新生成（`--check` 会提醒）。
6. **THREAT_MODEL §2.3**：换行、借样式两条改成"已修（第三步，后端规范化 + 闸门）"，保留实测记录。"对第三步的要求"一段改成实际做法和测试名。

验收：
- pytest：`_display_safe` 的正例和反例；**消息出口保持原文**要有测试（ChartError 的"可用列"、`_msgs` 里 `{a}` 和 `\n` 原样保留），这是防止以后有人图省事把规范化挪进 `_clean_str` 的唯一屏障；字符集漂移测试；手工非法 spec 的拒绝路径；闸门遍历和"新增字段也拦"；`containLabel` 不在白名单，也不在任何产物里；
- vitest：管线骨架（恒等步骤逐字节）；outerBounds 的 SSR 断言（标签在画布内，含 `long-labels-bar`；第一根柱子差异小于 5%）；零 `[ECharts]` log；注册表双向比对；
- e2e：f3-inject 新判定表全绿，P6、P7 的断言通过；
- 全部闸门在最后一次改动之后重跑；DEVLOG [39]，并回填 [38] 的 706e9b8。

不做：主题和轴名是否包进 outerBounds（第四步）；开关和层 1 的实际内容（第五步）；result.py:117 有图时 chart_error 被丢弃的问题（未定，单独讨论）；#44。

**F3 第四步：4 套主题 + 轴名纳入外边界（S 10-19 两轮评审已并入；S 10-19 定：阈值 20、换 #CD7D28、暗色 bg ≤ #1B1F24）**

输入：第三步遗留的"轴名是否包进 outerBounds"；M13 §6.1（`registerTheme`，切换即重绘、不重跑代码）；HANDOVER §0 验收 2"换主题"。

实测和源码依据（echarts 6.1.0；探针走 `build_option` 产物 + SSR，不入库）：
- **后端 `option.color` 会压过主题配色。** `Global.js` 的 `mergeTheme` 里有 `name === 'color' && option.color` 就 `return`。实测 bar 夹具配红色主题：保留 `color` 时柱子是 `#1F6FB2`，删掉后才是 `#ff0000`。`charts.py:37` 的注释"前端主题可整体覆盖"是错的，要删。
- **`setTheme(theme, opts?)` 是公开实例方法**，内部走 `_resetOption('recreate')` → `initBase`，第一行就是 `ecModel.option = {}`。所以切换主题不用重建实例，也不会残留旧主题的键：新主题没写的键会先清空，再由 globalDefault 补回。
- **轴名出画布，根因是名字太长，不是 clamp。** 用 3 档画布宽 × 轴名 2/20/100 字测（估算宽度按中文 12px/字）：
  - 2 字：`axisLabel` 下 x 轴名在 640 宽时是 [629,653]，出画布；改成 `all` 后三档宽度都在画布内。
  - 20 字：`all` 在 320 宽时是 [171,411]，把 clamp 调到 10% 也只到 [141,381]，仍然出画布。
  - 100 字：x 轴名本身约 1200px，比 320 和 640 的画布都宽，任何 clamp 都包不住。
  - 加上 `nameTruncate: {maxWidth: 120, ellipsis: "…"}` 后，三档宽度 × 三种长度全部在画布内（x 轴名最右到 304 / 611 / 1149）。

已定（待评审）：
1. **主题载体：`registerTheme` + `setTheme`，不进 prepare。**
   - 主题是 echarts 的"默认值层"：后端 option 管内容，主题管外观。
   - `EChart` 用 `init(el, theme)` 创建，切换时调 `setTheme`。`prepare(option, ui)` 签名不变。
   - 第六步离屏导出时，用同一个主题名 `init`，走同一个 `prepare`。
2. **配色归主题，后端摘掉 `color`（S 10-19 同意）。**
   - `build_option` 删掉 `option["color"]`。死代码和死测试同一次清掉：`_HEX`（`:46`）、`:474` 的 `#RRGGBB` 检查、`_ALLOWED["color"]`、`test_charts.py:180` 的格式用例。
   - 删掉 `charts.py:37` 那句错误注释。
   - `PALETTE` 由 `gen_ui_types.py` 写进 `chart_schema.json` 的 `palette`，默认主题从这里读。新增 `charts.PALETTE == plotting.PALETTE` 测试，两份字面量从此有测试钉住。
   - **历史兼容**：重放路径是 `app.py:252` 的 `public_result` → `public_chart`，原样下发 `option`，不过 `validate_spec`，所以老会话的 spec 里还带着 `color`。所有渲染路径共用的 `prepare` 的 `cleanup` 会删掉顶层 `color`，第六步导出也走它。
   - **把"重放不过 validate_spec"这个前提用测试钉住**：手工写一条 `result_json` 含 `color`（以及一个现在白名单外的键）的消息，经 `GET` 会话接口取回，断言 `option` 原样回来；同时 monkeypatch `validate_spec` 断言它没被调用。以后谁在重放路径上加校验，这条先红，不会出现老会话的图静默消失。
3. **对比度拆成两条，各自写明适用范围**：
   - **文字**（轴标签、轴名、标题、图例、tooltip 文字）对背景 ≥ 4.5（WCAG 1.4.3）。echarts 默认轴标签灰 `#6E7079` 在白底上是 4.93，可以过；在深底 `#15181C` 上只有 3.61，所以暗色主题必须显式改色。
   - **系列色**对背景 ≥ 3.0（WCAG 1.4.11 非文本），并且相邻两色的 CIEDE2000 ≥ 20。
     - 现 PALETTE 对白底的对比度：5.28 / 3.48 / **2.76** / 5.44 / 5.21 / 5.00；相邻 ΔE00：31.0 / 46.6 / 24.5 / 38.2 / 46.9 / 43.5。
     - **阈值 20 按外部标准定（S 10-19）**：JND 约 2.3，5–10 是"能看出不同"，20 是"不同色系"。它和本仓库调色板无关，不是现状的快照；常量旁边要写明这一点，以免以后有人当快照去改。
     - **余量规则**：新引入的颜色必须 ≥ 阈值 × 1.1，即 ≥ 22，用来吸收实现差异（kL 参数、换库、色域处理）。
     - **`#E2843B` 换成 `#CD7D28`，两份 PALETTE 同改**，不记成取舍，因为 matplotlib 的 PNG 也有同样的问题。`#CD7D28` 的数据：对白底 3.20，对 `#C0392B` 的 ΔE00 是 25.0，对青色 43.9，和旧橙相差 5.6（人眼看仍是同一个橙）。最弱的一项是对白底的 3.20。在这一色带里，"白底 3:1"和"离红 ≥24"几乎互斥，25 左右就是上限，要写进测试注释。曾考虑过 `#D2701F`，它的 ΔE00 是 20.6，余量只有 3%，所以出局。
     - **ΔE00 断言对每套主题自己的 `color` 数组都跑**，不只测默认主题。
     - **暗色画布的数值约束**：PALETTE 中最弱的 `#C0392B` 在 `#15181C` 上是 3.27，在 `#1B1F24` 上是 3.05，在 `#20242A` 上是 2.87。所以暗色 bg 不能亮于 `#1B1F24`，否则这套主题就得单独配一套提亮的 palette。断言写成"该主题的每个系列色对它的 bg ≥ 3.0"，bg 被调亮时自动变红。
     - **文字同理**：echarts 默认轴标签灰 `#6E7079` 在 `#15181C` 上只有 3.61。这就是暗色画布要逐键改文字色的理由，写在 `themes.ts` 的注释里。
   - 两条都是纯计算断言，覆盖 4 套主题，不悄悄删掉。
4. **轴名：`outerBoundsContain: "all"` + `nameTruncate`，clamp 显式写成 `"25%"`。**
   - 后端 `_cartesian` 和 `_scatter` 的 x、y 轴都加 `nameTruncate: {maxWidth: 120, ellipsis: "…"}`。120 要注释说明：12px 字体下约等于 10 个汉字，或约 18 个 ASCII 字符（每字约 6.5–7px）。
   - grid 显式加 `outerBoundsClampWidth/Height: "25%"`，不靠默认值。`_ALLOWED` 和 `_ENUMS` 同步更新，然后重新生成 schema。
   - clamp 调到 10% 对 20 字以上的轴名无效（见上面的实测），所以不放弃官方默认值。
   - **代价**：超过约 10 个汉字或约 18 个 ASCII 字符的轴名会被截断。y 轴名在 tooltip 的系列名里还能看到全文，x 轴名看不到。这是已知取舍，可以接受，理由是省略号会自己说明截断（S 10-19）：用户看到"…"就知道名字被截了。这和当初 truncated 静默截断不是一类问题，那次是图在说假话，这次是图在说"我截了"。
   - 第三步"第一根柱子偏差 < 5%"的常量要更新，测试旁边写明原因：轴名纳入外边界后 grid 缩小了（判定表纪律③）。
   - 新增三个夹具：
     - `long-axis-name-bar`：中文轴名，长度为 `NAME_MAX`（100）。
     - `long-ascii-axis-name-bar`：ASCII 轴名，长度 100。CSV 列名以 ASCII 为主，这才是主流场景。
     - `long-y-axis-name-bar`：只有 y 轴名长，配矮画布（高 200 档）。截断是按轴分别生效的，这个夹具覆盖 y 方向。
5. **4 套主题，只在配色和背景一个维度上区分**（排版、线宽、网格不作为区分维度，免得几套主题看起来像同一套的不同深浅）：
   - **经典**（默认）：白底，`palette`。
   - **柔和**：白底，低饱和配色。
   - **商务蓝**：白底，蓝色系色阶。
   - **暗色画布**：深底。改名的理由：应用本身没有暗色模式，名字要直说"只有图是暗的"。
   - 每套主题逐键写出，不留给"看起来还行"：
     - `color`、`backgroundColor`（**4 套都显式设**；不设时画布透明，暗色主题会透出白页面）、`textStyle.color`；
     - `title.textStyle.color`、`legend.textStyle.color`、`legend.pageTextStyle.color`；
     - `tooltip.backgroundColor` / `borderColor` / `textStyle.color`；
     - `categoryAxis`、`valueAxis`、`timeAxis` 各自的 `axisLine.lineStyle.color`、`axisTick.lineStyle.color`、`axisLabel.color`、`splitLine.lineStyle.color`、`nameTextStyle.color`。
   - 测试断言每套主题都包含上面每一个键，缺一个就红。
   - **不设 `rich`、`formatter`、`renderMode`，不设任何 `BANNED_KEYS`**，所以注入判定表不受主题影响。
6. **切换和持久化**：对话区顶栏放一个全局选择器，值存 `localStorage` 的 `datachat.chartTheme`。
   - 读出来先查 `THEMES`，**不认识的名字（改名、删除、手改）回退到默认主题**，再调 `setTheme`。否则 echarts 查不到主题会静默保持旧主题。
   - 不做单图主题。

验收：
- **pytest**：
  - 产物不含 `color`；`palette` 已导出；`charts.PALETTE == plotting.PALETTE`；
  - 重放路径原样回传含 `color` 的 spec，且 `validate_spec` 未被调用；
  - 枚举和白名单已更新；死用例已删。
- **vitest**：
  - 主题对象是纯 JSON，不含 `BANNED_KEYS`、`rich`、`formatter`；必需键齐全；
  - 默认主题的 `color` 等于 `palette`；
  - 文字对比度 ≥ 4.5；系列色对比度 ≥ 3.0，相邻 ΔE00 ≥ 20；
  - 每套主题 × 全部夹具：零 `[ECharts]` log，第一个系列的填充色等于该主题的 `color[0]`；
  - 未知主题名回退默认；`prepare` 删掉历史 `color`；
  - **轴名在画布内**：宽度 [320, 640, 1200] × 全部直角坐标夹具（含上面三个长名夹具）。SSR 按锚点和估算宽度判定（中文 12px/字，ASCII 7px/字）；改动前的写法下应当是红的，作为对照。**同一个测试里断言 plot 区宽度 ≥ 画布的 50%**，防止"把图压废了，轴名照样在画布内"也被判为通过。
- **e2e**：
  - 用 fillText 记录（同时记 textAlign 和 measureText 宽度），在 320、640、1200 三档视口下检查：长轴名画出来的宽度 ≤ 120+ε，末尾是"…"，并且在画布内。只断言"在画布内"可能是碰巧过的；
  - 切换主题后像素有变化，刷新后主题保持，零 CSP 违规；
  - f3-inject 在经典和暗色画布两套主题下各跑一遍，判定表不变。
- **人眼**：4 套主题 × 5 种图型的截图（不入库）交给 S 定稿；调色只改 `themes.ts`。
- **注入 e2e 防假绿（S 10-19）**：轴名纳入外边界后 grid 变窄，`hideOverlap` 隐藏的类目集合跟着变；而且这个集合还取决于运行宽度。所以每个载荷先断言它的标签确实有 fillText 记录，再断言没有被解析。前一条不过，说明测试失效，不能算"不解析"的结论。不靠重新排类目顺序来规避。
- **人眼清单里加一张 matplotlib 图**：`plotting.py:101` 的 `prop_cycle` 会让所有新出的 PNG 换色。仓库里没有 matplotlib 金图（chart_path 都是 tmp_path 加存在性断言），所以这是唯一没人看的输出。
- 全部闸门在最后一次改动之后重跑；DEVLOG [40]，并回填 [39] 的 10e76ff（已核对是 #46 的合并 SHA）。

不做：导出用浅色（第六步）；开关和层 1（第五步）；应用整体暗色模式；单图主题；内置主题；`result.py:117`；#44。

估时：1–1.5 天，人眼来回调色不计在内。

**F3 第五步：开关 + 换图型（S 10-19 评审：A 同意、B 选 (a)、C 同意、D 改按图型存，另加三个结构点；第三轮五条随实现并入；已实现，DEVLOG [41]）**

输入：§3「开关」「换图型」；M13 §6.2、§6.3、§12；PR #48 评审里第四、五、六条（S 10-19 定：随第五步做）；issue #49（不在本步，见"不做"）。

实测和源码依据（echarts 6.1.0；探针走 `build_option` 夹具 → `prepare` → SSR，探针不入库）：
- **slider 型 dataZoom 不进 outerBounds，会压住 x 轴名。** `bar` 夹具 640×360 加 `dataZoom:[{type:'slider'}]`：plot 区仍是 y 87–285（和不加时一样），slider 落在 y 308–338，x 轴名"城市"在 y 313–325，两者重叠；`long-axis-name-bar`、`line-wide` 也一样。
- **inside 型的默认值会劫持页面滚动**：`InsideZoomModel.js:58–60` 的默认值是 `zoomOnMouseWheel: true`、`moveOnMouseMove: true`、`moveOnMouseWheel: false`；`InsideZoomView.js:424` 写明取值可以是 `true / false / 'shift' / 'ctrl' / 'alt'`。
- **`chart.on('dblclick')` 在空白处不触发**：`echarts.js:843–870` 只在命中带 `dataIndex` 或 `eventData` 的元素时才派发；双击 plot 区的空白处，`params` 为空，不会派发。所以双击重置必须挂在 `chart.getZr().on('dblclick')` 上。
- **图例改到顶部不会撞标题**：图例在 y 6–18，标题从 y 20 开始，plot 区不变（`grid.top: 60` 本来就留了空间）。左右放置会盖住 plot 区：竖排图例不在 outerBounds 的计算范围内。
- **渐变必须写死颜色值**：`colorStops[].color` 只接受具体颜色，不能引用"主题第 i 色"。

已定：
1. **管线：`prepare(option, ui, theme)` 是纯函数，顺序为深拷贝 → `normalize` → `changeKind` → `applyLayer1` → `applySwitches` → `cleanup`。**
   - `normalize`（第四步评审第四条）：把历史 spec 的几何归一到当前契约，理由和删 `color` 一样，在渲染时归一，不动库。
     - 覆盖的键：`grid.outerBounds*`，以及 x/y 轴的 `nameLocation` / `nameGap` / `nameTextStyle.align` / `nameTruncate`。
     - 值由 `gen_ui_types.py` 导出到 `chart_schema.json` 的 `geometry`，前端不写第二份字面量。
     - **分界规则**写进 prepare.ts 头注释：后端契约改了、而重放路径原样下发的键，一律在 `normalize` 归一。后端以后改任何几何或外观键，必须在 `geometry` 里登记；pytest 双向比对登记表和 `_cartesian` / `_scatter` 的产物，漏登记就红。
   - `color` 的删除留在 `cleanup`，它同时防止前面任何一步写回顶层 color。
   - `changeKind` 放在开关之前，开关的兼容性按换完后的图型算。
   - `cleanup` 仍然最后执行。
2. **架构变更（PR 描述里单列）：第四步的 setTheme 路径被"整体重算"取代。**
   - 渐变的色值是 `prepare` 写死的，`setTheme` 换主题对象时不会重算它。所以 `EChart` 持有后端原始 option，**图型、开关、主题任何一个输入变化，都整体重算 `prepare` 并 `setOption(…, {notMerge: true})`**。主题变化时还要先 `setTheme`（主题的默认值层，例如背景、轴色，仍然由主题对象提供）。
   - 这和第四步不冲突：第四步 e2e 断言的是"切主题不重建实例"，重跑 `prepare` 同样不重建实例。第四步第 1 条管的是顶层 `color`，本步碰的是 series 层，那一条不用改写。
3. **UiState**：`{ kind: 目标图型 | null, sw: { label, legend, stack, smooth, gradient, radius, sort, marks, zoom } }`。
   - **开关偏好按图型存（S 10-19，D）**：键为 `datachat.chartUi:<kind>`，最多 5 个键，和 COMPAT 的维度一致。语义是"饼图看百分比、柱图看原始值"这一类图型偏好：新出的图直接继承，删会话也不会留下残留。（S 的原文写的是 `datachart.`，按仓库现有前缀 `datachat.` 统一。）
     - 键名取 `changeKind` 之后的图型，也就是用户眼前看到的图型。
     - 读取时逐字段校验，不认识的字段或值丢弃并回退默认；**读写都包在 try/catch 里**（F2 token.ts 的教训：隐私模式或配额满时会抛错）。写失败只是不持久化，不影响渲染。
   - **"换成什么图型"不持久化**，只存在组件状态里，刷新后回到后端出的图型。它是对某一张图的操作，按 messageId 存会重新带回 D 否掉的三个问题。
   - 开关状态在换图型时保留；不兼容的开关不渲染且不生效（§3；F4 迭代 V1 起，之前是置灰），换回来后恢复。
4. **兼容表**（"多系列"指 ≥ 2 个 series；"时间轴"见第 7 条的 `x_kind`）：

| 开关 | bar | line | area | pie | scatter | 写入的键 |
|---|---|---|---|---|---|---|
| 数值标签 | ✅ | ✅ | ✅ | ✅ | ❌（点多时满屏） | `series[].label.show`、`.position`（bar/line/area 写 `top`，堆叠时写 `inside`；pie 写 `outside`） |
| 图例位置 | 多系列 | 多系列 | 多系列 | ❌（竖排在左，见实测） | 多系列 | `legend.top`：只能是 `top` 或 `bottom` |
| 堆叠 | 多系列 | 多系列 | 多系列 | ❌ | ❌ | `series[].stack = "total"` |
| 平滑 | ❌ | ✅ | ✅ | ❌ | ❌ | `series[].smooth = true` |
| 渐变 | ✅ | ❌（无填充） | ✅ | ❌ | ❌ | bar 写 `series[i].itemStyle.color`，area 写 `series[i].areaStyle.color`（见第 6 条） |
| 圆角 | ✅ | ❌ | ❌ | ❌ | ❌ | `series[].itemStyle.borderRadius = [4,4,0,0]`；堆叠时只写最上面那个系列 |
| 排序 | 单系列、非时间轴 | ❌ | ❌ | ✅ | ❌ | 不写新键：`xAxis.data` 和 `series[0].data` 一起重排（pie 只重排 `data`）。三态：关 / 降序 / 升序；null 排最后 |
| 平均线和极值 | ✅ | ✅ | ✅ | ❌ | ❌ | `series[].markLine.data=[{type:'average'}]`、`series[].markPoint.data=[{type:'max'},{type:'min'}]` |
| dataZoom | ✅ | ✅ | ✅ | ❌ | ❌ | 见第 5 条 |

   - 兼容表在代码里是常量 `COMPAT`。UI 是否渲染（F4 迭代 V1 起；之前是置灰）和 `applySwitches` 的过滤都读这一张表。
5. **dataZoom 只用 inside（S 10-19，A），并补两件事，否则不成立：**
   - **不劫持页面滚动**：写 `dataZoom: [{type: "inside", zoomOnMouseWheel: "shift", moveOnMouseWheel: false, moveOnMouseMove: true}]`。对话流里图占的屏幕面积不小，用默认值的话，用户在图上滚一下，缩放的是图，页面不动。开关旁边的提示改成"Shift + 滚轮缩放，拖动平移，双击还原"。
     **实现时实测推翻了"只靠 option 就不劫持"（DEVLOG [41] 偏离第 1 条）**：上面的 `'shift'` / `false` 只决定"缩不缩"，不决定"吞不吞"。roams.js:175-181 给 RoamController 的是统一配置（zoomOnMouseWheel / moveOnMouseWheel 都是 true），每个 dataZoom 的取值要到监听器里才判（roams.js:107）；RoamController 在触发监听器之前，只要指针在 grid 内就先 `eventTool.stop(e.event)`（RoamController.js:316-322）。探针：plot 区中心滚轮，window 上的监听器一次都没收到，`.main` 的 scrollTop 150 → 150；grid 外边缘则正常滚。所以 `EChart` 在容器上加 capture 阶段的 wheel 监听：不按 Shift 就 `stopPropagation`，事件到不了 zrender，默认动作（滚页面）照常；按 Shift 的放行。option 仍按本条写（Shift 时由它决定缩放）。
   - **恢复入口**：`toolbox.feature.restore` 用不了，因为 `toolbox` 在 BANNED_KEYS 里。所以 `EChart` 自己接双击：`chart.getZr().on("dblclick", (e) => { if (e.target) return; chart.dispatchAction({type: "dataZoom", start: 0, end: 100}) })`。挂在 zr 上，不挂 `chart.on`，理由见上面的源码依据。**`e.target` 有值就不重置**（S 10-19 第三轮）：命中元素 = ECharts 自己的交互（图例双击切显隐也走 zr 层），空白才是我们的手势；缩到一个点时周围全是空白，总能点到。只在 zoom 开着时注册，关掉或 dispose 时解绑。
   - 不用 slider（理由见实测），代价是没有可见的缩放条。
6. **渐变写在 series 层，不写顶层 `color`（S 10-19，B 选 (a)）。** 写顶层 color 会被 `mergeTheme` 整条跳过，等于把第四步修掉的问题带回来。写法：
   - `{type:"linear", x:0, y:0, x2:0, y2:1, colorStops:[{offset:0, color: theme.color[i % n]}, {offset:1, color: rgba(theme.color[i % n], 0)}]}`
   - 第二端用同一个颜色、透明度为 0，所以色值只依赖 `color[i]`，不用给每套主题再定义第二色。
   - 主题色由 `theme` 参数传入 `prepare`，`rgba()` 只接受 `#RRGGBB`（主题色的格式已由第四步的测试钉住），格式不对就抛错，不静默降级。
7. **`x_kind` 放在 spec 层，和 `option` 并列，不放进 option（S 10-19 结构点②）。**
   - option 是交给 ECharts 的东西，"能不能换成饼图"所需的信息不属于它。
   - spec 结构从 `{v, kind, truncated, option}` 变成 `{v, kind, truncated, x_kind, option}`，`x_kind ∈ {category, time, value}`。builder 总是产出它，`validate_spec` 的结构检查同步修改；`SPEC_VERSION` 不变，新字段只用于判断能否换图型，不影响渲染。
   - 历史 spec 没有 `x_kind`（重放路径不过 validate_spec）。前端按"未知"保守处理：**只有"不可换饼图"一条**（悬停原因"旧图缺少类型信息，不能换成饼图"）；排序的条件是"单系列且不是时间轴"，未知不拦（S 10-19 第三轮：别把没做的事写进降级规则）。不从 `axisLabel.hideOverlap` 反推。
   - **两个同名真相**（S 10-19 第三轮）：`spec.kind` 是后端出的图型，`option.series[].type` 是当前显示的；换图型后两者有意不一致，这是"刷新回到后端图型"的实现基础。测试 `spec_kind_is_backend_truth` 钉住，防后来的人去"修"。
   - **SPEC_VERSION 升版规则**（写在常量旁）：加字段不升（向后兼容）；改字段语义或删字段才升。判据是"老前端读到新 spec 会不会误判"。
8. **换图型（S 10-19，C 同意放宽）**：一律从后端原始 option 出发，不链式转换，所以来回切换无损。
   - **bar ↔ line ↔ area**：条件是 category 轴，系列数不限。放宽 §6.3 的"单个数值 series"：柱换折线不丢信息，M13 那条是按饼图的口径写的。
   - **bar / line / area → pie**：单系列、`x_kind` 为 category、全部值非 null 且 ≥ 0、类目数 ≤ `MAX_PIE_SLICES`（导出）。
   - **pie → bar / line / area**：总是可以换。
   - **scatter**：不参与互换。
   - **跨端契约测试**：`gen_ui_types.py` 用同一份数据分别以 bar / line / area / pie 调 `build_option`，生成换图型夹具。vitest 断言 `changeKind(A, B)` 等于 builder 直接出的 B，**只允许下表列出的差异**，表外任何差异都红：

| 差异位置 | 什么时候出现 | 为什么允许 |
|---|---|---|
| `xAxis.name` 为空 | pie → bar / line / area | pie 的 option 里没有 x 列名；和 builder 在 `xs.name is None` 时的行为一致 |

   `boundaryGap`（bar 为 true，line/area 为 false）、`areaStyle`（area 有，line 没有）、`showSymbol`（类目数 ≤ 60，阈值导出）**不在差异表里**：`changeKind` 必须产出和 builder 相同的值，否则断言就是红的，而这个红正是我们要的（S 10-19 指出初稿漏了前两项）。
   - 换不了时选项置灰，悬停显示固定文案（例如"有空值，不能换成饼图"），不拼接任何数据。
9. **白名单外的产出要有机制约束，不只是约定（S 10-19 结构点①）。**
   - 现状：`charts.py` 白名单上方的注释写明，前端加了 `renderMode` 后，最终产物必然不过白名单，这是有意的，最终产物永不回验。之前唯一的例外是一个被测试钉住的键。第五步把例外扩成一整层：`dataZoom`、`markLine`、`markPoint`、`label`、`stack`、`smooth`、`itemStyle`、`areaStyle.color`。这些都在 `_ALLOWED` 外，`_check_strings` 的 `{`、`}`、`\n` 闸门也管不到它们。
   - **`FRONTEND_KEYS` 是一张常量表**：路径模式 → 允许的值集合。值只能是字面量、字面量对象，或者特定标记 `THEME_GRADIENT`（结构固定为第 6 条的写法，颜色从主题 `color` 取）。`applySwitches` 写值时**只从这张表取**，代码里不出现第二处字面量。
   - **测试**：全部夹具 × 4 套主题 × 开关组合（每个开关单开 + 全开），对 `prepare` 的产物和 `normalize → changeKind` 的产物求差：新增或改动的路径必须 ⊆ `FRONTEND_KEYS`，每个值必须属于该路径的值集合（`THEME_GRADIENT` 按结构比对，颜色 ∈ 该主题的 `color` 或其透明版本）。基线取 `normalize → changeKind`，因为它已经由第 8 条的契约测试钉成等于 builder 的产物（在白名单内）。
   - 例外层不含任何字符串型的用户数据，所以 `_check_strings` 管不到也没关系。这一点由"值集合里只有字面量"保证，测试注释和 THREAT_MODEL §2.3 都要写明。
   - 同步改 `charts.py` 白名单上方那段注释：例外从 `renderMode` 一个键扩成 `FRONTEND_KEYS` 这一层，并指向这条测试。
10. **注册**：新增 `MarkLineComponent`、`MarkPointComponent`、`DataZoomInsideComponent`。register.ts 加 `FRONTEND_REG`（`FRONTEND_KEYS` 的路径 → 组件），和 `FRONTEND_KEYS` 双向比对。
11. **M13 §12 第三列回填**：用 `FRONTEND_KEYS` 的路径集合。vitest 读 M13 §12 的 markdown，断言集合里的每个路径都在表里、表里写出的每个前端路径也都在集合里（M13 §12「两条实现约定」第 2 条）。
12. **第四步评审遗留**：
    - 四：见第 1 条。加一个"第三步形状"的历史夹具（`outerBoundsContain:"axisLabel"`、带 `color`、没有 nameLocation / nameTruncate / x_kind；手写，注释写明它对应第三步的 build_option）。断言 prepare 后的几何键等于当前 builder 的产出。
    - 五：主题 e2e 加配色断言：classic 和 soft 各截一张，左上角 10×10 以外的像素必须有差异。
    - 六：themes.test.ts 的 LEGACY 余量豁免改成按 `(theme, hex)` 二元组，只豁免 classic 现有的 5 色。

验收：
- **pytest**：schema 导出 `geometry`、`pie_max_slices`、`show_symbol_max`；`geometry` 登记表和 builder 产物双向一致；spec 带 `x_kind`，取值正确（category / time / value 各一例），`validate_spec` 的结构检查同步；换图型夹具由 `build_option` 生成，`--check` 覆盖。
- **vitest**：
  - **COMPAT 45 格都测"生效"（S 10-19 结构点③）**：每格挑一个满足条件的夹具（缺的补上，例如多系列 scatter）。
    - ✅ 格：开关打开后，产物里该开关的键在、值对；关闭时该键不在。
    - ❌ 格：开和关的产物相同。比较前**递归排序键再 stringify**（S 10-19 第三轮）：开关全关时对象可能被重建、键序变化，产品行为不变；排序后比较还能顺带发现重复键。
    - 条件格（多系列、单系列、非时间轴）：两边各一个夹具。
    - 用 `test.each` 展开，测试名带"开关 × 图型"，45 格一格不少（用一条计数断言钉住）。
  - 第 9 条的例外层机制测试；`FRONTEND_KEYS` = `FRONTEND_REG` = M13 §12 第三列；任何开关组合下 prepare 产物都不含被禁键。
  - 换图型契约（第 8 条的差异表），以及 A → B → A 和原始 A 完全一致。
  - 渐变：只写 series 层，产物顶层没有 `color`；换主题后 colorStops 跟着变。
  - 4 套主题 × 全部夹具 × 全开：零 `[ECharts]` log。
  - 排序：类目和值一起移动，null 排最后。
  - UiState：按图型读写；不合法时回退；`localStorage` 抛错时渲染不受影响。
  - 历史夹具经 normalize 后几何正确；没有 `x_kind` 时不可换饼图、不可排序；LEGACY 二元组。
  - 注入夹具全开时，SSR 判定表与关闭时相同。
- **e2e**：
  - 开关逐个打开，像素有变化，不发新的分析请求；刷新后偏好保持；同一图型的新图继承偏好；不兼容的开关是 disabled。
  - dataZoom：在图上普通滚轮滚动，页面会滚、图不缩放；Shift + 滚轮会缩放；双击空白处还原（还原前后的 fillText 类目集合对比）。
  - 换图型：bar → pie → bar 后 fillText 记录与初始相同；刷新后回到后端图型。
  - 渐变开着切主题：实例不重建，柱子颜色跟着变。
  - 主题配色差异（第 12 条之五）；历史 spec 的 x 轴名在画布内。
  - f3-inject 加一轮"全开关"，判定表不变。
- **人眼**：5 种图型 × 开关全开的截图，给 S。
- PR 描述单列第 2 条的架构变更。DEVLOG [41]，回填 [40] 的 2373f24（S 已核对）。全部闸门在最后一次改动之后重跑。

不做：层 1 面板（F4）；dataZoom slider；横 / 竖（v1 已删）；scatter 换图型；图例放左右；时间轴排序；"换成什么图型"的持久化；#49 的高度问题和矮画布刻度丢失；导出（第六步）。

估时：2.5 天（加了例外层机制测试和 45 格生效测试）。S 10-19 提醒偏乐观：机制测试比 UI 本身重；真超了不吞，可拆"开关"和"换图型"两个 PR（只共享 COMPAT 一张表）。

实现时的偏离（DEVLOG [41] 有代码证据）：
- `prepare` 的签名是 `prepare(spec, ui, theme)`，第一参数是 spec 不是 option：`changeKind` 要 `spec.kind`（源图型）和 `spec.x_kind`，从 option 反推图型和 x_kind 正是本步否掉的做法。
- dataZoom 那一行在 M13 §12 里加了"前端实际写出"一列（没有覆盖原第三列"v1 `_ALLOWED`"），测试读这一列。

**F3 第六步：导出 PNG（S 10-19 评审已并入：交互态选 (b)）**

输入：§0 验收 3"导出 PNG 得到非空 data URL，文件名已清洗"；§3"导出 [v2]"（离屏实例、文件名清洗、可选浅色）；第四步第 1 条"离屏导出用同一个主题名 init、走同一个 prepare"；拆分表"导出的应该是用户最终看到的样子"。

实测（echarts 6.1.0，后端托管的 dist + 真实 CSP，Playwright Chromium；探针把 `init` / `prepare` 临时挂到 window 上，走 `prepare(spec, ui, theme)` 完整路径，夹具是 `build_option` 产出的 `bar`，不入库）：
- **离屏实例不用挂进 DOM。** `init(document.createElement("div"), theme, {renderer: "canvas", width: 800, height: 450})` → `setOption` → `getDataURL({type: "png", pixelRatio: 2})`，得到 1600×900 的 PNG，每张约 22 ms。
- **入场动画会被拍成半成品。** 同一张图，`setOption` 后立刻 `getDataURL`：保留动画时非背景像素 21,921，`animation: false` 时 365,183，相差约 17 倍（柱子还在从 0 长高）。所以离屏 option 必须关动画。
- **背景来自主题，`getDataURL` 的 `backgroundColor` 参数不起作用。** 暗色画布导出的左上角是 `#15181C`（21,24,28），不透明；传 `backgroundColor: "#FFFFFF"` 后仍是 `#15181C`。所以"导出用浅色"只能换主题重画一遍，不能靠这个参数。
- **下载：data URL 和 blob URL 的 `<a download>` 在 CSP 下都能触发下载。** Chromium 会自己把 `a/b\c:d*?.png` 改成 `a_b_c_d__.png`，但这是浏览器的行为，Tauri 的 WebView2 / WKWebView 不一定一样，所以不依赖它。
- **`fetch(dataURL)` 被 CSP 拦下**（`connect-src 'self'`，console 报错）。所以 data URL 不能用 fetch 转成 blob；如果要转，用 `atob` 手动转。
- **下载的字节拿得到。** Playwright 的 `waitForEvent("download")` + `download.path()`：data URL 和 blob URL 两种都能拿到文件（52,446 字节，PNG 签名 `89504e470d0a1a0a`，IHDR 宽高 1600×900，`failure()` 为 null）。所以 e2e 可以建在真下载上（S 10-19 要求先验证）。Chromium 在 Linux 上**不会**改写 `CON.png`，保留名完全靠我们自己清洗。
- **darkCanvas 的系列色放到白底上不达标**：对 `#FFFFFF` 的对比度分别是 2.96 / 3.27 / 2.25 / 2.32 / 2.94 / 2.51，6 个里有 5 个低于第四步的 3.0（WCAG 1.4.11）。"同一套配色只把背景换白"会违反第四步的对比度契约。
- **后端的 `_clean_str` 不清 bidi 控制符**：`_CTRL`（`charts.py:56`）只覆盖 C0、DEL、U+2028/2029，不含 U+202A–202E、U+2066–2069，也不含 C1。另外，重放路径不过 `validate_spec`（第四步已用测试钉住）。所以文件名只能由前端自己清洗，不能假设后端已经清过。仓库里已经有两套控制字符集：`charts.py:56` 的 `_CTRL`，以及 `app/server/app.py:66` 的 `_CONTROL_CHARS`（含 C1 和 bidi）。文件名是第三套需求，**独立定义、表驱动测试，不复用其中任何一套**（S 10-19）：否则将来有人"统一一下"，RLO 防线的依据就混了。

已定：
1. **离屏导出，和屏幕走同一条管线。** `exportPng(spec, ui, theme, size)` 是纯 DOM 函数，放在 `charts/exportPng.ts`。导出的结果只由这四个参数决定，屏幕上也是同一套 `prepare`：
   - 创建不挂 DOM 的 div；`init(el, theme, {renderer: "canvas", width, height})`；
   - `opt = prepare(spec, ui, theme)`，然后写 `opt.animation = false`；
   - `setOption(opt, {notMerge: true})`；`getDataURL({type: "png", pixelRatio: 2})`；
   - `dispose` 放在 `finally` 里，抛错也要释放。
   - `animation` 只在导出路径写，不进 `prepare`，所以屏幕上的图不受影响。它也不是开关的产物，不进 FRONTEND_KEYS。
   - 尺寸取屏幕上这张图容器当前的 `clientWidth × clientHeight`：布局（nameTruncate、图例换行、刻度密度）依赖尺寸，换个尺寸就不是同一张图了。
2. **交互态进 UiState，在事件发生时写入，导出时不从实例里取（S 10-19 选 (b)，并定了实现形状）。**
   - 不走 `chart.getOption()`：它返回的是渲染后的完整 option，带全部 series data。它是渲染产物，spec 才是后端的真相，拿它再 prepare 就等于把数据重算一遍。也不走 `getModel()`：那是内部 API，升级就会挂。
   - `UiState` 加 `view: { zoom: {start, end} | null, hidden: number[] }`：
     - 监听 `datazoom`，存 `{start, end}`：0–100 的有限数，start ≤ end；
     - 监听 `legendselectchanged`，存被隐藏系列的 **seriesIndex** 集合。
   - **系列显隐用 index，不用名字**：`legend.selected` 的键是系列名，而系列名来自 CSV 列名，这是整个产物里唯一一条"用户字符串作为对象键进 option"的路径。现在它经过了 `_display_safe`，所以不危险；但只要将来有人把 option 回传后端，它就是一条新的用户字符串通道。事件给的是名字，在事件处理里按当前 option 的 `series[i].name` 换成 index 再存，名字不进 UiState。
   - `prepare` 新增一步 `applyView`，放在 `applySwitches` 之后、`cleanup` 之前：
     - `zoom` 写进开关已经产出的 `dataZoom[*].start/end`。zoom 开关关着、或当前图型不兼容时忽略；
     - `hidden` 用 index 生成 `legend.selected`：键取 `series[i].name`，这个名字来自 option 本身，不来自 UiState。index 越界的直接丢掉。
     - 换图型时（target 变化）、spec 变化时，`view` 清空。系列数和类目轴都可能变，旧的 index 和区间没有意义。
     - `view` 不持久化，刷新后回到全量、全显，和"目标图型"一致。
   - 屏幕路径：`view` 变化也走整体 `setOption(notMerge)`。`datazoom` 是 ECharts 自己先画好的，写回 UiState 之后重设一遍结果相同；要防止回环，比较值相同就不 set。
   - FRONTEND_KEYS 补两条：`dataZoom[*].start/end`（数值）、`legend.selected`（键必须等于某个 `series[i].name`，值是布尔）。例外层的机制测试同样覆盖它们。
   - tooltip 和 hover 高亮不进 UiState，导出时也不带。
3. **文件名清洗**，放在 `charts/filename.ts`，纯函数 `safeFilename(title, kind)`。字符集在本文件里独立定义（见实测最后一条）。按下面的顺序执行，**trim 放在限长之后**（S 10-19 指出初稿的顺序会重新造出非法的尾部）：
   1. 来源：`option.title.text`（normalize 之后）；没有标题时用 `KIND_LABEL[kind]`（"柱状图"等）；
   2. NFC 规范化；
   3. 删除 C0、DEL、C1（U+0080–009F）、U+2028/2029、bidi 控制符（U+200E/200F、U+061C、U+202A–202E、U+2066–2069）。RLO 能让 `gnp.exe` 显示成 `exe.png`；
   4. 把 `\ / : * ? " < > |` 换成 `_`；连续空白合并成一个空格；
   5. 按码点限长 60（`Array.from`，不切断代理对）；
   6. **限长之后**再去掉首尾的空格和点（Windows 会拒绝或静默去掉尾随的空格和点；前导点在类 Unix 上是隐藏文件）；
   7. 清完为空时回退到 `图表`；
   8. 保留名判"第一个点之前的那一段"：`name.split(".")[0].trimEnd().toUpperCase()` 属于 {CON, PRN, AUX, NUL, COM1–9, LPT1–9} 时，整个名字前面加 `_`。所以 `CON`、`con.txt`、`CON.png`、`Nul.tar.gz` 都会加；
   9. 加 `.png`，不加时间戳，重名由浏览器自己编号。
   - 第 8 步加 `_` 后最多 61 个码点，加上 `.png` 是 65，远低于 255，不需要再限长。
4. **"导出为浅色（经典配色）"，文案写死（S 10-19 要求二选一，选这个）。**
   - 只在当前主题是 darkCanvas 时，在导出按钮旁边显示这个勾选框。勾上后用 classic 重新 `prepare` 再 `init`（渐变的色值由 prepare 按主题写死，所以必须重新 prepare），系列配色也会一起变成经典配色，文案就照这个写。
   - 不做"darkCanvas 的浅色变体"：实测 darkCanvas 的系列色有 5 个在白底上低于 3.0，同色系白底的方案过不了第四步的对比度契约。真要做，就是第五套配色加一整套对比度和 ΔE00 测试，不在这一步做。
   - 勾选不持久化。
5. **下载用 data URL 加 `<a download>`**：`a.href = dataURL; a.download = safeFilename(...); a.click()`，不挂进 DOM。`img-src` 已经允许 `data:`，不用改 CSP。不走 fetch 转 blob（会被 CSP 拦，见实测）。Tauri 壳里的下载行为到壳那一步再验证。
6. **UI**：
   - 控件面板加"导出 PNG"按钮；darkCanvas 下旁边多一个"导出为浅色（经典配色）"。导出失败（抛错）时在按钮旁显示"导出失败"，不弹窗，不影响屏幕上的图。
   - matplotlib 的 png 项不加导出按钮，但在图下方标注"静态图（由 matplotlib 生成），可右键另存为"。这样同一页上两种图一个有按钮一个没有时，用户知道是为什么，不会以为按钮坏了（S 10-19）。

验收：
- **vitest**：
  - `safeFilename` 表驱动，逐条写期望值，不只断言"不含某字符"。覆盖：
    - INJECT_PAYLOADS P1–P7 全部；
    - RLO 构造的 `U+202E + "gnp.exe"`；
    - `CON`、`con.txt`、`CON.png`、`Nul.tar.gz`、`CONSOLE`（不是保留名，不加 `_`）；
    - `..`、`  . `、全是控制字符（回退到 `图表`）；
    - 120 字符、第 60 个码点是空格（截断后不能有尾随空格）；第 60 个码点是 `.` 同理；
    - 65 个 emoji（限长不切断代理对）；
    - 正常中文标题原样保留；无标题时回退到图型名。
  - 另加一条：文件名字符集与 `_CTRL`、`_CONTROL_CHARS` 互相独立，不 import 任何一方。
  - `exportPng`：mock `init`，断言传入的主题名和 width/height、`setOption` 收到的 option 等于 `prepare(spec, ui, theme)` 加上 `animation: false`、`getDataURL` 的参数、`dispose` 被调用；`getDataURL` 抛错时 `dispose` 仍被调用。
  - `applyView`：
    - zoom 写进 dataZoom；zoom 开关关着或图型不兼容时忽略；
    - hidden 按 index 生成 `legend.selected`，键等于 `series[i].name`；
    - 越界 index、NaN、start > end、超出 0–100 都丢掉；
    - 换图型或 spec 变化后 view 清空；
    - `view` 里只有数值，没有任何字符串。
  - 4 套主题 × 全部夹具 × 开关全开 × 带 view，导出 option 都过 cleanup：不含被禁键，`tooltip.renderMode` 是 richText；例外层机制测试包含 view 产物。
- **e2e**（后端托管的 dist；下载的字节已实测拿得到，见实测）：
  - 点"导出 PNG"后用 `waitForEvent("download")` + `path()` 拿到文件：前 8 字节是 PNG 签名，IHDR 宽高等于容器尺寸 × 2，非背景像素数 > 0。`suggestedFilename` 等于 `safeFilename` 的期望值，用 inject 夹具的标题（P1）来测。
  - 不发新的分析请求，零外部请求，console 干净。
  - **开关全开和全关的导出不同，限定在单系列、类目轴的 bar 上，并且只比较对这个形状 ✅ 的开关**。COMPAT 里没有哪种图型九格全是 ✅：单系列类目 bar 上 ✅ 的是 label、gradient、radius、sort、marks、zoom 六个，legend、stack 要求多系列，smooth 不支持 bar。选到 ❌ 格时，全开就等于全关，断言恒真（S 10-19）。所以测试先用 `compat()` 算出这个形状的 ✅ 集合，断言它正好是这六个；再逐个打开，断言每一个的导出都和全关不同，最后断言全开也和全关不同。
  - Shift + 滚轮缩放后导出的图和缩放前不同；在图例上点掉一个系列后导出的图和点掉前不同；刷新后 view 清空，导出的图和初始相同。
  - darkCanvas 勾"导出为浅色（经典配色）"后左上角是 `#FFFFFF`，不勾是 `#15181C`。
  - matplotlib 的 png 项有"静态图"标注，没有导出按钮。
- **人眼**：4 套主题各导出一张，加一张 darkCanvas 的浅色导出、一张缩放加点掉系列后的导出，给 S 看。
- THREAT_MODEL §2.3 加两行：导出文件名是用户串离开画布的唯一出口，前端清洗，规则见本条第 3 点；系列显隐按 index 存，用户串不作为 UiState 的键或值。DEVLOG [42]，[41] 回填 d589d61。全部闸门在最后一次改动之后重跑。

实现时的偏离（DEVLOG [42]，S 10-19 第二轮评审后）：
- 第 2 条"view 变化也走整体 setOption"改为：view 变化**不**触发 setOption（S 认可：datazoom 每个 mousemove 一次，notMerge 每次重建 dataZoom，手势当场断）。
- **屏幕是真相源，view 是镜像（S 10-19 第二轮，取代"只在事件里写、从不读实例"）**：每次重算 setOption 之后从实例回读一次 view（`viewFromRendered(chart.getOption(), shown)`，只读 `dataZoom[0].start/end` 和 `legend[0].selected` 两处，名字当场换成 index）。开关关掉 dataZoom → 回读不到区间 → zoom 清空；图例项变了 → 只剩现存项。不维护"哪些变化要清空 view"的列表。换图型 / 换 spec 仍先清空再算。事件写入照旧（拖动途中不重算）。
- 验收"逐个打开，每一个的导出都和全关不同"在 zoom 上不成立（inside 不画东西）。e2e 对 zoom 单开断言"相同"并写明原因；开关本身由对照钉住：**关着时 Shift + 滚轮后导出与初始相同，开着时不同**；关掉再打开后导出回到全量。
- FRONTEND_KEYS 的值集合加两种：range（`dataZoom[].start/end`，0–100）、legendItems（`legend.selected`，键必须是 option 里已有的图例项名）。饼图的图例项是扇区，hidden 存 `series[0].data` 的 index。**存 index、按名字应用是有意的**：legend.selected 只认名字，同名项在 ECharts 里本来就一起显隐；index 换来的只是 UiState 里没有用户串（注释写在 switches.ts）。
- e2e 要一张 matplotlib 图，fake 模型加了 `chart-matplotlib` 场景（tests/fake_llm.py，pytest 走真链路覆盖）。

约束（补进第 1 条）：
- **主题必须模块级注册**（`register.ts` 的 `registerCharts`，幂等），不能挂在组件生命周期里。离屏实例不经过任何组件，`init(div, name)` 遇到没注册的主题名会静默回退默认主题，导出配色全错且不报错。`exportPng` 在 init 之前自己调 `registerCharts`（exportPng.test「init 之前已注册」）。
- **尺寸为 0（容器 display:none）抛错**，不回退默认尺寸、不让 getDataURL 产出坏图；UI 显示"导出失败"。
- e2e 文件自带 beforeAll 预热（照 f3-stop），单独跑也不卡冷启动。

不做：SVG / 矢量导出（第一步已说明这一步不做）；复制到剪贴板；批量导出；导出时改尺寸或分辨率；matplotlib png 的导出按钮；darkCanvas 的浅色变体（第 4 点）；view 持久化；Tauri 壳里的下载行为（到壳那一步再做）；#49。

估时：1–1.25 天（含 view 进 UiState 和 applyView）。

### F4：层 1 面板（已定，S 10-20 评审通过，PR #56）

范围依据 M13 §3.2 的层 1 列。已经做掉的不重复：图例、堆叠、平滑、渐变、圆角、排序都是 F3 第五步的开关。F4 只做剩下的四项，再加上饼图 >6 色的问题。

已定（待 S 评审）：
1. **入口与生效**：每张图工具栏加一个「样式」按钮，点开是一个小面板（不是弹窗），有「重置」。改动写进 `UiState.edit`，进 `prepare` 的 `applyLayer1`（prepare.ts:8 现在是恒等）。和开关一样，任何改动都整体重算并 setOption(notMerge)；`view` 照旧回读（第六步的 viewFromRendered）。导出走同一条 prepare，所见即所得。
2. **轴范围 yAxis.min / max（仅用户）**：两个数字框，空着表示自动。校验：必须是有限数，同时填时 min < max，不合法的框标红、不生效。适用 bar / line / area / scatter；饼图置灰，理由写「饼图没有 y 轴」。bar 填了 min > 0 时不拦，面板里常显一行提示「柱图 y 轴不从 0 开始会夸大差异」。堆叠时按堆叠后的总量判断，echarts 本身就是这么算的，不另处理。
3. **系列色（series[i].itemStyle.color）**：每个系列一个色块，只能从**当前主题调色板**里选。存的是调色板 index，不存 hex，所以换主题后色跟着主题走，对比度检查也照旧成立。饼图按扇区 index 存（data[i].itemStyle.color），和第六步 hidden 存 index 的口径一致。
4. **字号（textStyle.fontSize）**：三档，小 12 / 中 14（默认，不写键）/ 大 16。只改全局 textStyle。轴名截断宽度 AXIS_NAME_MAX_PX 不跟着变，长名照旧截断。
5. **分段 visualMap.pieces：F4 不做。** 它要用户自己定区间和颜色，面板复杂度会翻倍，现在也没有需求。留到 F5 验收之后，看 S 是否需要。
6. **饼图 >6 类目（S 10-19 定归 F4）**：
   - (a) 每套主题的调色板从 6 色扩到 10 色。约束：前 6 色不动；新加的 4 色每一个对背景 ≥3.0；循环顺序上相邻的两色 ΔE00 ≥20（第 10 色和第 1 色也算相邻）。四套主题都要逐对测。
   - (b) 超过 10 个类目：颜色照旧循环，面板里给「合并为'其他'」开关（仅用户，默认关），Top-N 默认 9 个加 1 个「其他」。打开后标题旁常显「已合并 N 项为'其他'」。合并只在前端做，spec 不改，导出时也带着这行标注。
   - matplotlib 的 PALETTE 要不要一起扩：扩，两份继续由一致性测试钉住相等。
7. **存储**：键是 `datachat.chartEdit:<message_id>:<图序号>`，读写都包 try/catch，按合法取值逐字段校验，不合法的字段丢掉。重放历史会话时读回来。删除会话时不清理（localStorage 小，留个技术债记一笔）。
8. **安全**：面板的输入只有有限数、调色板 index、枚举三类，没有一个用户字符串会进 option。新写的键（yAxis.min / max、itemStyle.color、textStyle.fontSize、legend 不动）加进 FRONTEND_KEYS，复用第五步的机制测试：写出的值只能是数字、主题色或枚举。（实现偏离：单独登记在 layer1.ts 的 LAYER1_KEYS，因为 FRONTEND_KEYS 要和 M13 §12 逐字比对，见 DEVLOG [44]。）

9. **界面风格借鉴 Tableau 的「标记」卡（S 10-20 提）**：面板做成一张竖排卡片，一排小方块按钮（F4 迭代 V1 起为 5 组：颜色 / 标签 / 形状 / 轴 / 文字，见「F4 迭代 V1」第 3 条），点一下展开它自己的小浮层；配色用浅灰底、细边框、低饱和的强调色，这些都是 Tableau 的风格。只借外观和点选交互。Tableau 那种把字段拖到行、列、颜色架上「拼接」出图的玩法**不借**：那是在改数据映射，换列、换聚合都属于层 2 或重新分析，按 M13 §3.2 只能走模型和后端。我们的面板只改样式键。
   - Tableau 10 调色板不能直接搬：在白底上实测对比度 ≥3.0 的只有 6 色（#4E79A7 4.55、#9C755F 4.10、#E15759 3.68、#B07AA1 3.42、#59A14F 3.16 等），#EDC948 只有 1.61、#76B7B2 只有 2.29。S 10-20 定：新增第五套主题「Tableau 风」，保留 Tableau 10 的色相，加深到对白底 ≥3.0，并通过相邻 ΔE00 ≥20 的检查；S 也说现有主题偏单调，这套主题要更有层次（浅灰网格、细轴线、柔和底色）。S 还要求先尽快出一版能跑的，自己跑过再提修改意见。

验收：
- vitest：applyLayer1 对 5 种图型 × 4 项逐格测（生效、置灰、不合法输入不生效）；调色板 index 换主题后解析成新主题的同一位置；10 色的对比度和相邻 ΔE00 四套主题逐对测；合并「其他」的求和不变、Top-N 顺序；存储逐字段校验，坏值丢弃。
- e2e：改 y 轴范围后屏幕和导出一致（复用第六步的导出比对）；刷新页面后改动还在；重置后回到后端原样；8 类目饼图第 7、8 扇区颜色和第 1、2 扇区不同。
- 人眼：四套主题 × 10 色饼图截图，加一张改了范围、配色、字号的 bar。

估时 2–3 天。超出就拆成两个 PR：(1) 面板 + 轴范围 + 系列色 + 字号；(2) 10 色 + 合并「其他」。

### F4 迭代 V1：图表工具栏和标记卡的视觉（S 10-21 第二轮评审后改定；DEVLOG [53]）

起因：S 10-20 看过 F4 MVP（#57，05e2e1d），评价是"很不好看"，没有给具体意见。本节依据 10-21 在 1400×900 下的实拍截图（柱图 8 类、饼图 12 类，经典主题），先改最显眼的几处；S 跑过之后再定下一轮。

实拍问题（S 10-21 已在代码里逐条核对）：
- P1 工具栏 12 个控件（EChart.tsx:176-225）：图型 select、9 个开关（其中图例位置、排序是 select）、样式、导出 PNG。饼图上有 7 个置灰（COMPAT 里 pie 只有 label、sort 是 yes，switches.ts:40-50）。
- P2 样式入口分两处：F3 开关在工具栏，F4 标记卡在"样式"里。
- P3 标记卡在文档流里，打开后把反馈按钮和输入框往下推。
- P4 色块 14px，系列名一栏 64px（styles.css:143-145）。
- P5 5 套主题各 10 色，12 类饼图里第 11、12 扇区和第 1、2 扇区同色。

已定（待 S 评审）：
1. **工具栏**：只放图型、排序、样式、导出 PNG 四个**控件**。zoomOn 时的 chart-hint（"Shift + 滚轮缩放…"，f3-switches:129 断言可见）照旧留在这一行，它是提示文字，不是控件。所以"这一行"在 zoomOn 时有 5 个元素。
2. **一条纪律：不适用就隐藏**。§3 和 F3 第二步原来的规则是"不兼容的开关置灰且不生效"，现在改为"不渲染，且不生效"。排序留在工具栏，也走同一条纪律，不设例外：COMPAT.sort 为 no（line、area、scatter），或者 single-nontime 不成立（多系列、时间轴）时，工具栏不渲染排序，只剩三个控件。理由有两条：一是 disabled 控件的 title 在 Chrome 里悬停不显示，置灰之后理由其实看不见，只剩噪音；二是 COMPAT 过滤照旧，隐藏不改变生效规则。换图型时开关状态照旧保留，换回来后照旧恢复（只是重新显示出来）。图型 select 里换不了的选项照旧置灰（§6.3 第 447 行），不在本步范围内。
3. **标记卡里共 12 项，分 5 组**：8 项是从工具栏挪进来的 F3 开关，4 项是 F4 原有的（系列色、轴范围、字号、合并为"其他"）。
   | 组 | 项（按组内顺序） | 控件形态 |
   |---|---|---|
   | 颜色 | 系列色、渐变、合并为"其他" | 色块行；checkbox；checkbox（仅饼图出现） |
   | 标签 | 数值标签、图例位置 | checkbox；两段按钮 下 / 上（legend 只有 bottom 和 top 两个值，不是布尔） |
   | 形状 | 堆叠、平滑、圆角 | checkbox ×3 |
   | 轴 | y 轴范围、缩放、平均线和极值 | 一行两个数字框（各 72px，"最小 ～ 最大"）；checkbox；checkbox |
   | 文字 | 字号 | 三段按钮 小 / 中 / 大 |
   每项一行，统一用 grid：左边标签一栏 88px，gap 8，右边放控件。88 和第 7 条色块行的名称一栏是同一个值，全卡只有这一种标签列宽。轴范围那一行 = 88 + 8 + 72 + 「～」16 + 72 = 256，在可用的 342 以内。组内不适用的项按第 2 条不渲染。合并为"其他"沿用原条件：只在饼图出现。
4. **组 tile 的可用性和理由**：一组里所有项都不适用时，这个 tile 不可用。用 `aria-disabled="true"`，**不用 `disabled` 属性**，这样它还能拿到焦点，点击时什么都不做。理由用**静态组文案**，不从组内各项拼接，因为组内各项的 compat 理由各不相同。理由渲染成 tile 行下面常显的灰字 `.marks-why`，用 aria-describedby 指向它，不挂在 title 上。排法定为**一行**：多条用「 · 」连接，每条前面带组名。例如饼图：「形状：饼图没有可调的形状 · 轴：饼图没有 y 轴」，12px 下约 312px，放得进 342。`.marks-why` 始终占一行高（min-height 一行），没有理由时内容为空，所以卡头高度不随图型跳。按现有 COMPAT，所有能走到的不可用情形只有三种，逐一列出：
   - 形状：pie、scatter 不可用（scatter 的堆叠是 no；pie 三项全是 no），文案是「{图型}没有可调的形状」；bar、line、area 至少有一项可用（bar 有圆角，line、area 有平滑）。
   - 轴：只有 pie 不可用，文案沿用「饼图没有 y 轴」。
   - 标签：只有单系列的 scatter 不可用（数值标签是 no，图例要求 multi），文案是「散点图不显示数值标签，单系列也没有图例」。
   - 颜色、文字：任何图型都可用。所以"样式"按钮没有不可用态。
   {图型} 取 KIND_LABEL 里的枚举值，不进任何用户串。vitest 对 5 种图型 × 系列数 1/2 × xKind 有无时间轴逐格枚举，断言 tile 的可用性和文案正好是上面这张表；以后 COMPAT 一改，这张表必须跟着改。
5. **ARIA 和展开方式**：**组可以多开**，每个 tile 独立开合。
   - tile 行用 `role="group"`（aria-label "样式分组"）。
   - 每个 tile 是独立的 toggle button：aria-pressed 表示自己这组是否展开，aria-controls 指向自己的展开区。不再用 role="tab"，原来的写法缺 tabpanel，本身就是错的。
   - 每个展开区是 `role="region"`，aria-labelledby 指向自己的 tile；展开区按 tile 的顺序从上往下排。
   - 卡打开时，各组默认都收起。
   - 选多开、不用 radiogroup 的理由：aria-pressed 本来就是"各自独立"的语义；12 项可以同时看见，用起来更顺手；卡太高时按第 6 条在卡内滚动。
6. **浮层定位（写死）**：
   - `.chart-controls` 加 `position: relative`，浮层用 `position: absolute; right: 0; bottom: calc(100% + 4px)`，**向上展开**，盖在图上。right: 0 是有意的：浮层右缘对齐工具栏右缘，不对齐"样式"按钮右边。因为 chart-export 有 margin-left: auto，导出按钮在样式按钮右边约 120px，所以浮层会和触发按钮错开。好处是浮层位置不随导出按钮的宽度飘。`.echart-wrap` 本身没有定位，不能拿它做锚点。
   - `z-index: 20`，压住 .ask 输入区和 echarts 画布。
   - 打开时（以及 .main 滚动、resize 时）量一次可用高度：avail = 工具栏顶部 − .main 可视区顶部 − 8。`max-height = min(420, avail)`，超出部分在卡内滚动。如果 avail < 160（工具栏已经快滚到顶），改成向下展开，用 `top: calc(100% + 4px)`，可用高度按 .main 可视区底部算。.main 是 overflow:auto 的滚动容器，这样算出来的浮层不会被它裁掉。
   - 关闭方式：Esc、点浮层外、再点"样式"。整页同一时间只开一张卡：打开另一张图的卡时，先关掉当前这张。卡内的组按第 5 条可以多开。导出只取 echarts 实例，浮层不进导出。
7. **卡宽和色块（按 S 的账算）**：选 **色块 16px、名称一栏 88px、卡宽 380**，不选 20px / 410 宽。账：380 − 边框 2 − .marks-pop 左右 margin 20 − 内边距 16 = 可用 342；一行 = 名称 88 + gap 8 + 色块组（"自动" ≈30 + 10 × 16 + 10 个间隔 × 4 = 230）= 326，余 16。间隔取 4，是因为选中外环 2px + offset 1px 要占 3px。选这档的理由：16px 加外环和 ✓ 已经能看出选中了哪个；20px 的卡要宽到 410 以上，向上展开时会盖住更多图面。选中的色块是 2px 外环加白色 ✓，aria-pressed；键盘焦点用 :focus-visible 画焦点环。系列名超出时截断，悬停显示全名。行高 `--row-h: 24px`（色块 16 + 行距 8）。色块列表 `max-height: calc(8 * var(--row-h))` = 192px，第 9 个条目起开始滚动，8 个以内不滚。
8. **饼图类目多于色数时的提示**：类目数 > 当前主题调色板长度（现在 5 套主题都是 10）时，颜色 tile 上显示一个小点。打开颜色组后，第一行写「N 类，多于 M 色，颜色会重复」，下一行就是"合并为'其他'"。阈值和合并的阈值同界（PIE_TOP_N=9，len ≤ 10 不合并，layer1.ts:83），所以合并打开后提示消失。合并默认照旧关（S 10-20 定）。
9. **视觉 token**：工具栏和卡共用一组 CSS 变量：--ctl-bg #f7f7f8、--ctl-line #dcdde0、--ctl-accent 取 var(--accent)、圆角 6、控件高 28。tile 改成横排，图标在左、文字在右，高 32。
10. **文档三处统一**：本节合入后，§3 第 65 行、F3 第二步第 404 和 419 行的"置灰"改成"不渲染"，并注明"F4 迭代 V1 起"。F4 第 9 条里的 tile 列表（"颜色 / 标签 / 文字 / 轴"）改成指向本节的 5 组。这些都和实现放在同一个 PR 里改。

不做：主界面其余部分的视觉（上传控件的 "Choose Files"、侧栏、消息卡），另开一步；饼图图例和扇区标签去重（要动 legend 的默认策略）；图型 select 的置灰选项；暗色主题下浮层只保证对比度 ≥4.5；Tableau 风主题的色值不动。

验收（**导出字节的期望值不变；选择器和禁用断言按分组重写**）：
- 判定表，下面每处都要在 DEVLOG 写明"这个位置的行为为什么变了"：
  - f3-switches.spec.ts:65：开关的定位作用域从 chart-controls 改成卡（先点"样式"、再点所在组）。
  - :72、:74：排序仍在工具栏，选择器不变。
  - :76-77：堆叠、平滑、图例位置的 `toBeDisabled()` 改成 `card.getByRole(...)` 下的 `toHaveCount(0)`。**作用域必须是卡，并且要先打开卡和形状、标签两组**。如果照旧写 `ctl.getByRole`，开关搬家后那里永远是 0 个，这条断言会无条件绿。这个夹具是单系列柱图：堆叠和图例因为单系列不渲染，平滑因为 bar 是 no 不渲染。同时加一条正向对照：同一张卡里圆角 `toHaveCount(1)`，证明作用域和展开状态都对；另外断言形状 tile 没有 aria-disabled。
  - :82-89：刷新后先点"样式"、再点"标签"，然后查数值标签。
  - :129：chart-hint 可见，不变。
  - f4-panel.spec.ts 本来就是先点"样式"（:106、:145），只需要改里面的选择器。共 4 处，role 都从 tab 改成 button：
    - :109 `tab /字号/` 改成 `button /^文字/`（tile 改名了）；
    - :117 `tab /轴范围/` 改成 `button /^轴/`；
    - :118 `tab /合并/`：合并已经不是独立的 tile，改成先点 `button /^颜色/`，再在颜色组里找"合并为'其他'"的 checkbox；
    - :120 `tab /颜色/` 改成 `button /^颜色/`。
  - EChart.test.tsx：helper :366 `tile = (n) => screen.getByRole("tab", …)` 改成 `getByRole("button", { name: new RegExp("^" + n) })`。用到它的 4 个 test：
    - :372 `tile("字号")` 改成 `tile("文字")`；
    - :380 `tile("轴范围")` 改成 `tile("轴")`；
    - :391 原题「饼图：轴范围按钮禁用，合并按钮可用」改成「饼图：形状、轴 tile aria-disabled，理由行是『形状：饼图没有可调的形状 · 轴：饼图没有 y 轴』；展开颜色组后有合并 checkbox」。原来的 `.disabled` 断言改成断言 aria-disabled；
    - :397 `tile("颜色")` 名字不变，只换 role。
- vitest 新增：
  - 工具栏控件集合：5 种图型 × 单/多系列，排序按 COMPAT 出现或不出现。
  - 第 4 条的组可用性逐格枚举。
  - 12 项各在其组，不适用的不渲染。
  - 隐藏不改变生效规则：对同一组 sw 状态，applySwitches 的输出和改之前逐字节相同（快照）。
  - 三种关闭方式。
  - 色块的 aria-pressed 和 ✓。
  - 组多开：先后点颜色、轴，两个 region 都在，两个 tile 都是 aria-pressed=true；再点一次颜色，只收起颜色组。
  - 色块列表：8 个条目时 scrollHeight ≤ clientHeight，9 个条目时 >。
  - .marks-why：饼图上是一行、两条，用「 · 」连接；柱图上为空，但高度和饼图相同。
  - 提示的阈值：10 类不出现，11 类出现，合并后消失。
- e2e 新增：
  - 打开浮层前后，提问输入框的 boundingBox 不变（不推开文档流）。
  - 浮层中心点用 elementFromPoint 取到的是浮层自身（z-index 压住了）。
  - 向下展开分支：1400×900 下，把**工具栏**滚到贴着 .main 可视区的顶部（这时图已经滚出上方，avail ≈ 0 < 160），再打开卡，断言浮层用的是 top 定位，并且整体落在 .main 可视区内（向下约有 864 的空间）。只把图滚到顶部触发不了：图高 360，工具栏会在顶部下方约 400 处，avail ≈ 392。另加一条：在正常位置打开时，断言走的是向上展开分支。
  - 5 套主题下，颜色组每一行 scrollWidth ≤ clientWidth（卡宽账的实测）。
  - 饼图 12 类在经典主题下出现提示，打开合并后提示消失。
- 人眼：三张截图（柱图默认、柱图开卡、饼图 12 类开卡）改前改后各一套，再加 Tableau 风主题下各一张。

估时 1.5 天，一个 PR。

### F5：S 验收走查（已定，S 10-21 评审通过；DEVLOG [55]）

F5 不是回归清单，而是一次真 Key 的手动走查加观感判断，预计一小时内跑完。32 条 e2e 已经覆盖的内容这里不重抄，只列"看什么、什么算过、截图留哪"。启动命令：`python -m app.server --open`。

**截图不入库**（仓库策略，S 10-21 定）：S 本机自存，文件名用 `<条号>-<要点>.png`。验收证据是 DEVLOG [55] 走查记录里的文字结论；只有暴露问题的截图才贴到对应的 PR 或 issue 上。理由：每轮迭代往 docs/ 里堆 PNG，仓库只增不减；e2e 截图照旧走 test-results/（gitignore）。所有发现记在 DEVLOG [55] 的"走查记录"里：观感问题单列，不在 F5 里当场修。

**五条操作路径（S 动手）**

| # | §0 | 谁 | 看什么 | 什么算过 | 截图 |
|---|---|---|---|---|---|
| 1 | ① | S | 填真 Key → 上传单表（GBK）和多表 → 看预览 | 列名、中文、行数和数据源对得上；预览按文本渲染，没有乱码；**多表时每个文件各一份预览（F1 按 dataset_files 逐文件预览），每份都要对，不能只看第一份** | 1-preview-single.png、1-preview-multi.png |
| 2 | ② | S（agent 先用假模型过一遍 UI） | workflow、ReAct 各问一题，题目要能出图 → 展开步骤和代码 → 换主题、开关、开标记卡 | 两种 agent 都给出结论和图；步骤和代码可展开；5 套主题和开关观感可接受（观感结论单列） | 2-workflow.png、2-react.png、2-themes.png |
| 3 | ③ | S，只验真机手感 | 导出 PNG → 去下载目录找文件 → 双击打开 → 👍👎 | 文件真落在下载目录，文件名已清洗，能正常打开且非空；👍👎 刷新后还在 | 3-export.png |
| 4 | ④ | S，只验真机手感 | 关掉后端进程 → 重新 `--open` → 打开原会话 | 历史会话和图都在（走重放）；关掉前正在跑的那轮显示"已中断"，不是"已取消" | 4-replay.png |
| 5 | ⑤ | S | 真模型提问 → 中途按停 → 立刻重问 | 按钮同一帧变成"正在停止…"；最终是"已取消"；重问不撞 409；后端延迟从程序里取数，不用秒表（见下），只记录，不设门槛 | 5-stop.png |

①的输入限制：上传框是 `accept=".csv" multiple`（views/Shell.tsx:157），xlsx / xls 传不进来。验 GBK 要用 Excel「另存为 CSV」导出的文件。解码顺序是 BOM → utf-8 严格 → gb18030 严格（csv_io.py），GBK 没问题。**已知局限**：Big5（繁体）会被 gb18030 静默读成错字，不报错。手上有繁体表的话顺便验一下，并在走查记录里定要不要处理（处理就单独立项，不在 F5 里修）。

⑤的后端延迟取法：不用秒表，因为秒表会把人的反应时间和网络往返都算进去。
- 库里的 ts 是字符串。来源是 `round(time.time(), 3)`（events.py:65），入库时用 `str(ev.ts)`（app.py:450），所以它是 **epoch 秒、带 3 位小数的墙钟时间**，比较前要先转成数字。
- cancel 本身不是一个事件，也不落库：POST /cancel 只置位，没有记时间。所以单靠 `GET /sessions/{id}` 拿不到两条 ts 来相减，库里只有 error(kind=cancelled) 这一条 ts。
- 主路径：在 DevTools Network 的 Timing 面板里取 `POST /messages/{id}/cancel` 收到响应的时刻，换算成 epoch 秒，再和 `GET /sessions/{id}` 返回的 events 里 error(kind=cancelled) 的 ts 相减。
- 辅助：EventStream 面板里 error 行的到达时刻。这个面板是否给出每个事件的时间戳要看 Chrome 版本，所以不能当作唯一路径。
- 走查记录里写明用的是哪条路径，以及换算的方法。

已有的技术覆盖（③④ 只验真机，不重复这些断言）：
- ③：f3-export「导出 PNG：真下载拿到 PNG…文件名清洗…」、f2「提问 → SSE → 失败原因 → 👍 → 刷新重放一致」。Playwright 的下载是模拟的，真实下载目录和双击打开只有 S 能验。
- ④：pytest `test_full_flow_workflow_and_restart`（test_server.py:49）、`test_restart_marks_interrupted_not_cancelled`（test_web_f2.py:265）、`test_replay_returns_stored_chart_option_verbatim_without_validation`（test_web_f2.py:427）；e2e f3-charts「五种图型…刷新重放仍在」。注意 e2e 只刷新页面，没有重启后端；重启后端由 pytest 覆盖。
- ⑤：f3-stop「停止：感知延迟 / 后端延迟分开测；落 cancelled；立刻重问不撞 409」，用的是假模型挂住 3 秒。真模型下的感知延迟只有 S 能验。

**两条已闭环（⑥ 不用复核，⑦ 只确认文档）**

| # | §0 | 证据 | S 复核 |
|---|---|---|---|
| 6 | ⑥ v1 库迁移 | `test_v1_database_gains_feedback_table_without_touching_old_tables`（tests/test_web.py:149）：drop feedback 还原成 v1 后重启，6 张旧表的 count(*) 和 pragma table_info 前后相等，旧消息能直接评价 | 不用复核，测试本身就是证明（S 10-21） |
| 7 | ⑦ 注入结论 | THREAT_MODEL §2.3（命中率、落点、_display_safe、7 个后端测试 + f3-inject 的 P6/P7）；f3-inject 在后端托管的 dist 上跑 | 确认 §2.3 已写全 |

**通过与收尾**
- 1–5 全过，6、7 复核无异议 → F5 通过。随后单独开一个 PR 删除 Streamlit，HANDOVER 和 plan.md 里标阶段 5 完成。删除时至少涉及以下几处（S 10-21 扫出，删 PR 里逐条勾掉）：
  - `ui/streamlit_app.py`、`ui/chat_app.py`
  - `requirements.txt:10` 的 `streamlit==1.65.0`（漏删的话，打包会继续装 Streamlit）
  - `tests/test_ui_smoke.py`（2 个 test，其中一个按两个页面参数化）。删掉后 pytest 基线从 814 变成 811，这不是回归，DEVLOG 要写明新基线（漏删的话 CI 会红）
  - `packaging/build_sidecar.py:31` 的 `--exclude-module streamlit`。DEVLOG 第 771 行记着 pyarrow 是 streamlit 的传递依赖，删完要重新确认 pandas 3.0 的字符串后端是否还需要它
  - `README.md:54` 对 Streamlit 界面的介绍
  - `docs/HANDOVER.md:19`，以及 DEVLOG 第 42 行 B14 的状态"随 Streamlit 下线"
- 观感问题不阻断 F5，记成"F4 迭代 V2"的输入，进阶段 6 之前处理完：进了 Tauri 壳再改，要重打包、重签名、重发版。
- 代码签名证书挪到**阶段 6 前置事项**。它需要实名主体、付款和 CA 审核，agent 和评审都办不了，要由有主体的人申请；周期长，而且不依赖 F5 的结论，主体一旦确定就可以启动。目标是「Windows 一键安装不弹 SmartScreen 黄条」，所以大概率要 OV 起步。选型：
  - DV / 个人验证：最快，但 SmartScreen 信誉要靠下载量慢慢攒。
  - OV：需要营业执照和电话回访，签名后信誉建立比 DV 快。
  - EV：私钥放在硬件 token 或云 HSM 上，对 SmartScreen 立刻生效。
  材料清单在阶段 6 方案里给出。

**F5 覆盖不到的：#49 矮画布紧凑几何**。在产品里不可达：`.echart` 固定 `height: 360px`（styles.css:110），EChart.tsx 用 `isCompact(el.clientHeight)`，而 COMPACT_BELOW = 300，所以 isCompact(360) 恒为 false，COMPACT_KEYS 在真实用户路径上从来不会下发。窗口变矮只会出现滚动条，图本身不会变矮。f3-themes 里 #49 的用例能绿，是因为 measure() 人为把 style.height 设成了 220px，**测试绿不等于产品生效**。要人工验只能在 devtools 里改 style.height。#49 的状态是：契约、单测、e2e 都已完成，产品行为不变。

### F4 迭代 V2a：按 S 设计稿改版（已定，S 10-22 评审通过；DEVLOG [56]）

起因：10-21 假模型走查（截图 41 张，不入库）列出 3 个 P1、6 个 P2。S 据此出了设计稿，10-22 交来交接包（14 屏 PNG、tokens、规范、组件、状态机、07-落地范围），两轮讨论后定下口径。设计稿和交接包都不入库，S 本机保存；本节是唯一的规则来源，和交接包冲突时以本节为准。

范围：V2a 是纯前端的换皮和结构调整，**不改后端（唯一例外是 llm_kind 的小 PR，见文末），不改 SSE 契约、不改 chart_schema / chart_fixtures / 导出字节**。标记卡的视觉对齐和 3 项新功能放 V2b，另出方案。

#### 0. 纪律
1. **只改现有 9 个 CSS 变量的值**（styles.css:3-11），不引入 tokens.css 的 60 个变量，避免出现 `--bg` 和 `--bg-canvas` 两套语义。改值以后最多再补 6 个变量：`--line-muted`、`--accent-bg`、`--radius-card`、`--radius-pill`、`--h-control`、`--h-topbar`。超出这 6 个要回到方案里改。
   | 变量 | 原值 | 新值 |
   |---|---|---|
   | --bg | #fafafa | #FAFAFC |
   | --panel | #fff | #FFFFFF |
   | --fg | #1f2328 | #1D1D1F |
   | --muted | #6a737d | #7A7A7A |
   | --line | #e1e4e8 | #E8E8EA |
   | --accent | #2f6feb | #0066CC |
   | --warn-bg | #fff8e1 | #FFFAEE |
   | --warn | #8a5a00 | #B25000 |
   | --danger | #c62828 | #D70015 |
2. **颜色只表语义**：--accent 只用于可点的主操作和链接；--danger 只用于不可逆操作（删除按钮）；出错提示用 `#E5484D`，写成局部常量，不另起变量；黄（--warn）表示「能用但不完整」。图表色板只给图表用。
3. **字重只用 400 和 700**。微软雅黑没有 500/600，会合成或掉档；设计稿里的 500/600 一律落成 700 或 400。字体沿用现有 font-family，不打包 Noto Sans SC。
4. **图标用内联 SVG**：新文件 `ui/web/src/views/icons.tsx`，`stroke="currentColor"`、stroke-width 1.5、viewBox 统一 16。预计约 18 个。超过 30 个再讨论是否换 lucide-react。不新增任何 npm 依赖。
5. **判定表纪律照旧**：结构一变，e2e 和 vitest 的选择器必然要改。每改一处断言，在 DEVLOG 里写明「这个位置的行为为什么变了」，或者写明「只是选择器变了，行为没变」。

#### 1. 壳：侧栏、顶栏、输入区
1. **侧栏**宽 248，底色 --bg。从上到下：品牌行；「数据源 · N」分组（上传区 + 数据集行）；分割线；「会话 · N」分组；弹性留白；设置行。去掉设计稿里的「H 的工作区」（占位符，产品没有用户概念）。
2. **上传区**改成可点击、可拖放的卡片（高 62，图标 + 两行文案「拖入文件或点击上传 / 仅 CSV，单个文件不超过 1 GB」）。内部仍然是原来的 `<input type=file accept=".csv" multiple>`，视觉上隐藏，aria-label「选择 CSV 文件」不变。数据集名称输入框保留在卡片下方，选好文件后才出现。原生控件「Choose Files / No file chosen」不再可见（P2-4）。
3. **数据集行**：名称 + 右侧「使用中」（当前会话所用的数据集）。多表数据集在名称下面挂每个 CSV 的胶囊，胶囊顺序和数据集详情里的 tab 顺序一致，都以 `detail.files` 的顺序为准（P1-2 后半）。
4. **数据集重名（P1-2 前半）**：后端在没填名称时用第一个文件名作数据集名（app.py:323），所以两个数据集可能同名。前端在列表里检测重名，重名的行在名称后追加创建时间（`· 10:42`，同一天以外写 `· 10月21日`）。只改显示，不改后端名称。
5. **会话行**：标题 + 元信息「{数据集名} · {相对时间}」。悬停（或键盘聚焦）时右侧出现 `···` 按钮，菜单里是「重命名」「删除」。顶栏里常驻的红色「删除会话」去掉。
6. **顶栏**高 60：左边是标题和副标题两行（会话页的副标题是「{数据集名} · {工作流 / ReAct} · {N} 轮」），右边是图表主题选择和 `···`。
7. **会话标题统一（P1-3）**：侧栏、顶栏、浏览器标题都显示同一个值 `session.title || "未命名会话"`。现在主区显示「未命名会话」而侧栏显示首问，原因是：首问时后端把标题设成问题的前 60 字（app.py:407）；一轮结束后，SessionView.tsx:76 只执行了 setS(d)，没有同步标题输入框的 state（`title`，:25 初始化、:38 只在加载时赋值），所以输入框一直是空，显示的是 placeholder。修法是在这里同时 setTitle(d.title)；如果用户正在编辑标题，则不覆盖。改名在顶栏标题上原地编辑：点击变输入框，回车或失焦保存，Esc 取消，不弹窗。
8. **输入区（composer）**：圆角卡片，上面是文本框，下面一行是「数据集胶囊」（只展示，不带 ▾，因为会话和数据集在创建时绑定，不能中途切换）、快捷键提示、发送按钮。三态：
   - ready：「问一个关于这份数据的问题…」，蓝底发送按钮；
   - running：「分析进行中…」，按钮变成白底描边的「停止」；
   - disabled：没有数据集时（首屏空状态），占位改为「上传数据集后即可提问…」，按钮置灰。
9. **未设置 Key**：会话页顶栏下方显示黄色横幅「未配置模型凭证 · 去设置 →」。此时发送按钮可点，但点击后**前端直接拦下、不发请求**，在横幅上加一次强调。判据是 `KeyStatus.configured === false`。

#### 2. 助手卡
1. **固定结构，顺序不可改**：头（头像、datachat、状态标签、右侧耗时）→ 步骤条 → 警示条（仅黄、红态）→ 结论 → 图表卡 → 尾（👍👎换成线性图标、重新生成）。结论永远在图之前（P1-1）。
2. **状态标签 6 态**，只按 `outcome().kind` 分支，不看文案：
   | kind | 标签 | 色 |
   |---|---|---|
   | running | 分析中（带旋转环） | 蓝底 |
   | ok | 已完成 | 蓝底 |
   | ok + 有不完整信号（见 §3.2） | 部分完成 | 黄底 |
   | error | 失败 | 红底（#E5484D 系） |
   | cancelled | 已取消 | 灰底 |
   | interrupted | 已中断 | 灰底 |
   取消/停止相关的控件不再用「看起来像禁用」的灰（P2-7），标签和恢复按钮都是正常可读的颜色。
3. **步骤条**：默认折叠成一行（高 38），右侧「查看过程 ›」展开；展开后就是现在的事件流（计划全文、代码、执行结果），各项默认收起。分段和事件的对应：
   | 段 | 事件 | 说明 |
   |---|---|---|
   | 理解问题 | plan | ReAct 没有 plan，这一段不出现 |
   | 写代码 | code | 多次（修复重试、ReAct 多轮）时写「写代码 ×N」 |
   | 执行 | exec | 同上，「执行 ×N」；有一次失败、后来成功的，图标仍是完成 |
   | 总结 | answer | |
   每段的耗时：exec 用 `data.duration_s`，其余用相邻事件的 ts 差。running 时当前段蓝色加旋转环，后面的段灰色空心。段的状态只由收到了哪些事件决定，不猜进度。
4. **running 态**：不定式进度条（往复动画）+ 结论位置的三点脉冲。没有真实进度，也没有流式结论，不做确定式进度条和打字机效果。
5. **重新生成**：ok / error 两态的尾部有「重新生成」，行为和现在 interrupted 的「重试」相同，即用原问题重新提问（SessionView.tsx:125 的 `ask(q)`）。running 时不显示。

#### 3. 异常路径（三屏降级 + 错误卡）
1. **上传失败分两类，分开呈现**：
   - **上传时被拒**（不建数据集）：400（文件名重复、只有字典文件没有数据表）、413（单个文件超过 1 GB）、非 .csv。错误显示在上传区卡片里（红边 + 一行原因 + 「重新选择」），不进数据集列表。
   - **数据集已建、读取失败**（`detail.error` 非空：编码解不开、空文件、pandas 读不了）：侧栏这一行变成红卡（底 #FEF6F6，红名 + 「读取失败」），点进去是主区的失败卡：标题「{文件名} 读取失败」+ 原因原文 + 两个出口「删除这个数据集」「重新上传」，外加一行固定提示「Excel 里另存为 CSV（UTF-8）通常能解决编码问题」。不做设计稿里的「用 GBK 重新解析 / 跳过乱码行」，这两项需要后端新功能。
   - Big5 会被 gb18030 读成错字而不报错（csv_io.py 文档的已知局限），前端捕捉不到，所以不设单独的失败态；数据集详情的预览上方常显一行灰字：「预览里出现乱码时，多半是编码问题，请另存为 UTF-8 后重新上传」。
2. **部分完成（黄）**：ok 且下面任一信号成立：`result.warnings` 非空（包括 chart_errors 产生的那一条）；`result.unverified_numbers` 非空。呈现为结论上方的黄色警示条，标题写第一条信号的原文，多条时「还有 N 条」可展开；图表卡右上角不加徽章（没有「剔除 N 行」这个数）。不做设计稿里的 skippedRows / 分母，后端没有这个数据。现在 TurnView.tsx:95-104 底部的 warnings 列表和 unverified 小字挪进这个警示条，不再重复显示。
3. **错误卡（红）**：替代现在的一行红字。图标 + 标题 + 原文详情 + 出口按钮。按 `error_kind` 的 4 类分级（TurnView.tsx:10）：
   | error_kind | 标题 | 出口 |
   |---|---|---|
   | llm | 模型调用失败 | 按 llm_kind 区分，见文末「S 10-22 已定」第 1 条 |
   | execution | 代码执行失败 | 重新生成、换个问法 |
   | dataset | 数据集读取失败 | 打开数据集 |
   | agent / 其他 | 分析流程出错 | 重新生成 |
   「换个问法」= 把原问题填回输入框并聚焦。llm 类按子类给出口（S 10-22）。
4. **取消 / 中断**：
   - stopping：标签「正在停止」，停止按钮置为「正在停止…」并不可再点，下方说明「已发送停止，当前这一步结束后生效」。**不写「最多 3 秒」**：取消在模型调用的边界生效，可能晚一整次调用。
   - cancelled：说明「已在 {耗时} 时停止，没有生成结论」+ 三个出口「重新问一次」（= 重新生成）、「换个问法」、「查看已生成的代码」（有 code 事件时才显示，点击展开步骤条）。实时轮次里已经流过 answer 的（unsavedAnswer）保留现在的「已取消（未保存）」+ 原文。
   - interrupted：同 cancelled 的样式，说明用现有文案（MESSAGES.interrupted），出口同上。
   - 取消的一轮不进入后续追问的上下文，这是现有行为（app.py:265 只取 status=ok），不用改。

#### 4. 图表卡
1. 卡片：圆角 12、1px 边，头部是标题和副标题（{图型} · {N} 个类目），中间是画布，底部一行是工具栏。
2. **工具栏胶囊组**：图型、排序、样式三个高 28 的胶囊，导出 PNG 放在右侧，样式独立（白底描边）。控件集合和显隐规则不变（F4 迭代 V1 第 1、2 条），只改样式。
3. **图型 select 当前项发灰（P2-5）**：现在当前图型的 option 是 disabled 样式（canChangeKind(当前→当前) 不 ok）。改成当前项不走 disabled 判定，换不了的其他选项仍然置灰。只改显示，可换判定不变。
4. **暗色画布（P2-6）**：画布外包一圈和画布同色的卡片内衬（卡片头、工具栏随主题变暗），不再是浅色页面里的黑色矩形。导出照旧，不改导出字节。
5. 饼图保持饼图，不改环形图。环形图会改动 chart_fixtures 和导出字节，属于判定表变更，留给 V2b 或不做。

#### 5. 管理面
1. **设置页**：单列居中、最大宽 640（P3：现在只占左半）。API Key 卡三态：env（只读，显示「来自环境变量 DEEPSEEK_API_KEY」，更换按钮不可用，并写明原因）、keyring（显示「已保存在系统钥匙串」，可更换、可删除）、未设置（黄色提示 + 输入框）。模型、Base URL、超时三项照旧。
2. **删除数据集**：后端是硬删，并且会级联删除它的所有会话（app.py:356-361，sessions.dataset_id ondelete CASCADE）。所以改成对话框：标题「删除数据集「{名称}」？」，说明「会一起删除 N 个会话，删除后无法恢复」（N 由前端从会话列表里数出来），要求输入数据集名称才能点红色确认。对话框用原生 `<dialog>` 的 showModal（自带焦点圈和 Esc），不用 window.confirm。
3. **删除会话**：从 `···` 菜单进入，保留现在的两次点击确认（ConfirmButton），不要求输入。
4. **会话失效页**：保留现有文案，命令 `python -m app.server --open` 放进可复制的代码块（带「复制」按钮），加「重新连接」按钮（重新读取地址栏里的 token 并重试 /settings），并写明「数据都还在本地，没有丢失」。

#### 6. 窄屏、拖放、上传进度
1. **窄屏**：视口宽度小于 1080 时侧栏收成 56 宽的图标条（新建、数据集、会话、设置），点开以浮层形式展开完整侧栏。顶栏副标题必须带上数据集名。纯 CSS 加一个开合状态。
2. **拖放**：拖进窗口时上传区高亮，松手等同于选择了文件。非 .csv 的文件在前端直接拦下，按 §3.1 第一类显示。
3. **上传进度**：上传改用 XMLHttpRequest（fetch 拿不到上传进度），只改 api.ts 的上传这一个函数。上传区显示「上传中 37%」和进度条；上传结束、等待后端响应时显示「处理中…」。

#### 7. 首屏空状态
没有数据集时，主区居中一张卡：「先上传一份 CSV」+ 一个蓝色主按钮（等同于点击上传区）+ 一行说明（可多选；加上 *.dict.csv 作数据字典）。首页空白过多（P3）由这张卡解决。输入区按 §1.8 处于 disabled 态。

#### 8. 不做
- 需要后端的：上传修复选项（GBK 重解析、跳过乱码行、只读前 N 行）、部分完成的分母、断点续跑、流式结论 / 真实进度、XLSX。
- 产品取舍：继续追问建议（多一次模型调用）、整页暗色（和「暗色只作用于画布」冲突）、复制结果（复制格式待定）、图表全屏、自动选图、「H 的工作区」、环形图。
- V2b 范围：标记卡视觉对齐、按列着色、标题输入、应用到同类、「完成」按钮。

#### 9. 实现分段和提交
一个分支 `feat/f4-v2a`，三段依次做，每段本地闸门全绿后再做下一段，三段做完一起推、开一个 PR（S 10-22 定）：
- ① 变量、壳、助手卡、图表卡（§0、§1、§2、§4、§7）；
- ② 异常路径和管理面（§3、§5）；
- ③ 窄屏、拖放、上传进度（§6）。
DEVLOG 每段一条（[57]–[59]）。

#### 10. 验收
- 闸门：pytest 814、vitest、e2e、lint、tsc、gen --check、build 全绿。vitest、e2e 的条数变化写进 DEVLOG，删掉或改写的断言逐条写理由（§0.5）。
- 不变量：chart_fixtures、导出 PNG 的字节、SSE 事件、后端代码，相对 llm_kind PR 合并后的 master 都没有 diff。PR 里贴 `git diff --stat master -- app/ tests/ ui/web/src/generated/` 的结果，应该为空。
- 新增测试（vitest）：状态标签 6 态 × outcome；步骤条分段（工作流、修复重试 ×2、ReAct 无 plan）；部分完成的两个信号各一条、两者都没有时不出黄条；错误卡 4 类；未设置 Key 时点发送不发请求；数据集重名追加时间；删除数据集对话框里的 N 和输入校验；上传区非 .csv 拦截。
- 新增 e2e（fake）：结论在图前、步骤条默认折叠可展开；停止后出现三个出口且「换个问法」把原问题填回；fail-500 出错误卡；1024 宽度下侧栏为图标条；拖放上传一份 CSV。
- 截图：按 10-21 走查的 41 个状态在 1400×900 重拍一遍，S 本机对照设计稿核对，截图不入库。

#### S 10-22 已定
1. **llm 类错误按子类分出口**（S 10-22，先回"不分"，随后改为"分开"）。turn.ts:90 规定前端只按 status / error_kind 分支，不看文案，所以要分子类就得让后端在 error 事件的 data 里多给一个 `llm_kind`。它取 classify_error 已经算出的枚举值（timeout / connection / rate_limit / auth / bad_request / server / gateway_error / unknown / http_NNN），非 llm 类的错误这个字段为 null，并写进 generated/events.json 契约。这一步**单独开一个小 PR**（规则和实现放在同一个 PR 里，DEVLOG 另起一条），在 V2a 实现之前合并。V2a 不改后端的原则，只为这一处破例。出口：
   | llm_kind | 出口 |
   |---|---|
   | rate_limit、http_429 | 「稍后再试」：按钮先置灰 10 秒，倒计时结束后可点，点了等于重新生成 |
   | timeout、connection、server、gateway_error、http_5xx | 重新生成 |
   | auth、no_key（没配 Key，没发请求；[57] 补）、http_401、http_403 | 去设置 |
   | bad_request、http_4xx（上面没列出的） | 换个问法、重新生成 |
   | unknown、null | 重新生成 |
   classify_error 已把 401/403 归为 auth、429 归为 rate_limit、5xx 归为 server（llm.py:163），所以 http_NNN 实际只会出现上面没单列的 4xx；表里写 http_401 等只为兜底。
   错误卡的标题仍然是「模型调用失败」，详情照旧显示现有文案（文案里已经包含子类的中文，例如 LLM_KIND_TEXT）。

2. **"数据字典读取失败，已跳过"也归黄色**（部分完成）。这是我的建议，S 回复"可以提交"时没有单独提出异议。

### 阶段 5 收尾：V2b、设置页「测试连接」、P1-17（方案，待 S 评审；DEVLOG [60]）

S 10-23 定：阶段 5 剩下的三项**方案合一个 PR**（本节），评审通过后**实现合一个 PR**（三项一起做、最后统一跑全量闸门），F5 走查后删 Streamlit 单独一个 PR。依据：S 10-23 交来的设计包第二版（handoff2，英文文件名版，不入库；标记卡以 `screens/marks-card-edit.png` 为准，范围以 `07-scope.md`（07-落地范围）为准），以及本节里逐条列的代码和实测。

范围：
- **V2b**：A 组是图表几何（P2-19~22），B 组是标记卡（视觉对齐 + 3 项新功能 + 「完成」）。
- **测试连接**：后端新接口 + 设置页按钮。
- **P1-17**：图表警告文案不再暴露模型的参数和变量名（后端）。

判定变更预告（实现 PR 里逐条写理由）：chart_fixtures 24 条里 21 条会变（所有带 grid 的直角坐标夹具；nameGap 和 grid.left/right 是公共几何），只有 pie、pie-50、inject-pie 不动。gen_ui_types --check 会红，**同一个 PR 里重生成并提交 chart_fixtures.json**；导出 PNG 字节会变（A1–A3）；f4-visual 的 11、25 两屏基线会变（A 组 + B 组），08、24 不变；M13 §12「数值标签」一行的"前端实际写出"多 `yAxis.max`、`yAxis.interval`（A1）；chart_schema.json 多一个 `display` 对象（B3）。

#### A. 图表几何（P2-19~22）

现状实测（两个来源；SSR 的文字宽度是 zrender 估算值，只用来比较相对变化，像素以 CI 截图为准）：

| 项 | 证据 | 数 |
|---|---|---|
| y 轴上限 | SSR，夹具 `bar`（最大值 8） | ECharts 自动取的上限 = 8 = 数据最大值，最高的柱顶贴着上沿，柱顶数值（P2-18 起柱图默认开）画到网格外 |
| | 25 屏基线（412） | 自动上限 500，留白够；所以问题只在"最大值正好落在整刻度上"时出现，412 这个夹具看不出来 |
| x 轴名间距 | SSR，宽 1174 / 880 / 640 | x 轴刻度文字下沿到轴名上沿都是 8px（nameGap 28 是从轴线量的，刻度文字占掉约 20） |
| 左侧 | 25 屏基线（卡宽 888） | 卡左缘到 y 轴线 57px（`grid.left: '3%'` = 27px + 刻度文字），设计 44 |
| 右侧 | SSR | `grid.right: '4%'`：宽 1174 时 47px，880 时 35px，640 时 26px；随宽度变 |
| x 轴名下方 | 25 屏基线 | 轴名下面还空约 35px（`grid.bottom: 30`，单系列没有图例也照留） |

1. **P2-19 y 轴留顶（前端，随数值标签走）**
   - 触发：数值标签解析为**开**、图型是柱 / 线 / 面积、值轴、且层 1 之后 `yAxis.min`、`yAxis.max` 都未设置（用户填了上限或下限就整条不做，以用户为准；下限不从 0 起时刻度对不齐）。`dmax` 是所有系列的最大值；堆叠开时取每个类目的堆叠和的最大值。`dmax ≤ 0` 不写（全负的图标签在下面，不顶上沿）。
   - 判据（写死）：`t = dmax × 1.08`（留 8% 给柱顶数值；步长按 **t** 选，不按 dmax）。候选步长升序 `[1, 2, 2.5, 5] × 10^k`，k 从 `floor(log10(t / 6))` 起往上；取**第一个**使 `n = ceil(t / step) ≤ N` 的 step，写 `yAxis.max = n × step` **和** `yAxis.interval = step`。N 非紧凑 6、紧凑（compact.ts，画布 < 300 高）3。
   - 为什么必须同时写 interval（SSR 实测，min 0）：只写 max 时 ECharts 按自己的 splitNumber 选间隔，不一定整除上限。非紧凑 splitNumber 5 下 max 10 / 120 / 500 / 15 刻度整齐，但 max 12.5 出 `0, 3, 6, 9, 12, 12.5`；紧凑 splitNumber 3 下更糟，max 10 出 `0, 3, 6, 9, 10`、120 出 `0, 50, 100, 120`。写 interval = step 后刻度就是 `0, step, …, n × step`。紧凑用 N = 3 是为了不把 issue #49 收掉的刻度密度又加回去（例：8 在紧凑下 → step 5，max 10，刻度 0 / 5 / 10）。
   - 位置：单独一步 `applyHeadroom`，排在 applySwitches 之后、applyCompact 之前，读 ctx.ui.compact；写出的键 `yAxis.max`、`yAxis.interval` 登记为 `HEADROOM_KEYS`。只在数值标签开时触发，"全关 = 后端原样"不受影响。
   - 例：8 → t 8.64：step 1 要 9 格（超），step 2 要 5 格 → **10**；97 → t 104.76：step 10 要 11 格，step 20 要 6 格 → **120**；412 → t 444.96：step 100 要 5 格 → **500**（和现在一样）；11.4 → t 12.31：step 2 要 7 格，step 2.5 要 5 格 → **12.5**。
   - 2.5 不是死候选：它只在 12 < t ≤ 15（× 10^k）时被选中，其中 12 < t ≤ 12.5 给出 12.5；删掉它这一段会跳到 step 5 → 15，多留约 20%。(12.5, 15] 段有没有它结果都是 15。测试用例要包含 11.4 → 12.5 这一条（interval 2.5，刻度 0 / 2.5 / … / 12.5），钉住它。
   - 浮点：`ceil(t / step)` 先减 1e-12 再取整（12 / 2 这种整除不能因为浮点误差多出一格），step 用 `b × 10^k` 现算，最后的上限按 step 的小数位数 round 一次（0.3 → 0.4，不出 0.40000000000000002）。
   - **偏离 S 的建议** `Math.ceil(max*1.08/50)*50`：50 是写死的步长，最大值 8 会被抬到 50，图只剩 1/6 高。步长要跟数据量级走。
   - 为什么放前端、不放后端：顶上沿只在数值标签开着时才是问题，而数值标签的默认值是前端的（P2-18，`switches.ts` 的 `DESIGN_LABEL`）。写在开关这一步里，"全关 = 后端原样"的契约不变，chart_fixtures 也不变；重放的旧图同样生效（后端改的话，旧图要靠 normalize，而这不是常量几何，登记不进 GEOMETRY）。
   - M13 §12「数值标签」一行的"前端实际写出"补上 `yAxis.max`、`yAxis.interval`（由 applyHeadroom 写，注明随标签开触发）。

2. **P2-20 x 轴名间距（后端几何契约）**：`_X_NAME.nameGap` 28 → **32**。设计稿没给这个数（04 §6 只给了 `grid`，含义是 containLabel 式的外框，不含轴名）。判据：**最大字号下刻度文字到轴名仍留现在默认字号下的 8px**。层 1 字号「大」把刻度文字从 12 放到 16，多占 4px，所以 28 + 4 = 32；默认字号下变成 12px。nameGap 在 GEOMETRY 登记表里，`normalize` 会把重放的旧图一并归一。紧凑几何 `COMPACT.nameGap` 22 不变，和非紧凑差 10px（原来差 6）；紧凑切换时 grid.top 本来就一次收 24px（60 → 36），10px 不是最大的跳变，不另调。

3. **P2-21 / P2-22 左右留白改成固定像素（后端几何契约）**：`grid.left: '3%'` → `12`，`grid.right: '4%'` → `16`（设计 04-component-spec §6 是 `left 44`（含刻度文字）/ `right 16`）。两个键从 `_CART_GRID` 挪进 GEOMETRY 的 grid（三个直角坐标图都用同一个值），旧图走 normalize。效果：25 屏卡左缘到 y 轴线 57 → 约 42；右侧在任何宽度都是 16（1174 宽时少 31px）。
   - 初稿引用的「y 轴区 90px」「右侧空 60px」来源查不到（S 10-23 确认没给过这两个数），以实测为准：当前 master 25 屏基线卡左缘到 y 轴线 57px（3% 的 26.6 + 刻度文字约 30），右侧 36px（888 × 4% = 35.5）。两处都是百分比留白随宽度涨，改固定像素。

4. **单系列 `grid.bottom` 30 不动**（初稿想降到 16，撤回）：`COMPACT.bottomMin` 是 14、`bottomCut` 是 16，非紧凑降到 16 后紧凑态只收 2px，compact 在底边这一项就失去意义；要动得连 compact 一起重定，不值得为 14px 空白开这个口子。

A 组净效果（25 屏 360 高）：plot 区高度 −4px（nameGap 多占 4），宽度 +约 30px（左少 15、右在 888 宽时少 20）。

#### B. 标记卡（视觉对齐 + 3 项新功能 + 「完成」）

保留 V1 的浮层结构和无障碍语义（07 §5、04 §8 都要求不改固定面板）：组可多开、每组一个 toggle button（aria-pressed + aria-controls）对应一个 role=region、整组不可用用 aria-disabled、默认展开颜色组、上下翻转（`placeCard`）、整页只开一张卡、Esc / 点外面关闭。

**B1 视觉对齐（照 marks-card-edit.png）**
1. **卡头**：「标记」13/700 + 「N 个图形元素」10.5 灰（N = 颜色组列出的项数：系列数，饼图和按类目着色时是类目数）+ 右侧「重置」。字重按 V2a 纪律只用 400/700。
2. **组从一排 tile 改成竖排的组头**：每组一行 h40，左边图标 + 组名，跟着「当前值」（灰，10.5），右边下 / 右箭头；展开的内容紧跟在自己的组头下面。当前值：颜色「自动 / 按{x 轴名} / 已改 N 项」，标签「显示数值 / 不显示」，形状「默认 / 已改」（堆叠、平滑、圆角任一开），轴「自动 / {min}～{max}」，文字「{标题或"默认标题"} · {字号}」。
3. **整组不可用**：组头仍在（不跳行），aria-disabled，当前值的位置写理由（原 `.marks-why` 的静态组文案，照用 `groupReason`），aria-describedby 指向这个理由。`.marks-why` 那一行删掉。→ 判定变更：f4-panel「浮层…marks-why 柱图饼图同高」和 EChart.test 里读 `marks-why` 的断言改成读组头理由；理由文案本身不变。
4. **开关形态**：checkbox 外观改成拨动开关（CSS，`input type=checkbox` + `role="switch"`），可访问名不变，测试用的 `getByRole("checkbox"…)` 改成 `switch`（只是选择器变）。
5. **底部固定区**：灰字「改动只作用于这张图，不改动原始数据。」+「应用到所有{图型}」（h32 白底描边）+「完成」（h32 蓝底）。「完成」= 关卡，和 Esc 同一个出口。
6. **宽度不跟设计的 300–316，保持 380**：设计的颜色组是"4 个色板"，我们的颜色组是"每个系列一行 × 自动 + 10 色"（F4 层 1 的模型，[53] 算过一行 326px）。316 宽里放不下，换成 4 色板就是换功能。底色、边框、圆角 14、组头和间距按设计。

**B2 按列着色（新）**
- **只做"按类目着色"**：颜色组顶上一个下拉「按列着色」，选项「不按列（每个系列一色）」和「{x 轴名}」（即按类目，每根柱子一色）。选后者写 `series[].colorBy = 'data'`；颜色行随之换成按类目列（和饼图一样，改 `series[0].data[i].itemStyle.color`，数值点就地包成 `{value}`）。
- 只对**单系列柱图**开放（多系列已经是按系列着色；线 / 面积按点着色没意义；饼图本来就按类目）。类目多于色数时照饼图的提示「N 类，多于 10 色，颜色会重复」。
- **偏离设计**：设计的下拉列的是数据集的列（04 §8 `columns: string[]`）。换成别的列着色是在改数据映射，F4 第 9 条和 M13 §3.2 明确不借（属于层 2 / 重新分析）。这里只用图上已经有的 x 轴，不进任何新列。
- 存储：`Edit.colorBy: "series" | "data"`（默认 series），parseEdit 逐字段校验。写出的键登记进 `LAYER1_KEYS`（`series[].colorBy`、`series[].data[].value`）。

**B3 标题输入（新）**
- 「文字」组加一行「标题」输入框，占位符是当前标题（后端的 title.text）；留空 = 用后端标题。写 `title.text`。
- **这是"UiState 只存编号、数值、枚举，用户串不进 option"（switches.ts 头注释，S 10-19）的第一处例外，写成规则：**
  1. 例外只有一个：`Edit.title`。别的字段仍然只许编号 / 数值 / 枚举；以后再加字符串字段要另立方案。
  2. 进 option 只写 `title.text` 一处，写之前过 `sanitizeTitle`；屏幕和导出走同一条 prepare，所以两边是同一个串。
  3. `sanitizeTitle` 规则：C0 / C1 控制字符和 DEL（`\u0000-\u001f`、`\u007f-\u009f`）、`\u2028` `\u2029`、Bidi 控制符（`\u061c` `\u200e` `\u200f` `\u202a-\u202e` `\u2066-\u2069`）一律换成空格；`DISPLAY_UNSAFE` 里的 `{` `}` 换全角、`\n` 换空格；首尾去空白；限长 **100** 个字符（= 后端 `TITLE_MAX`，charts.py:41，后端标题也是 `_clean_str(title, TITLE_MAX)`），超出截断加「…」，和 `_clean_str` 同一种截法。清完是空串 = 没设置。
     后端 `_CTRL`（charts.py:57）不含 Bidi，这里比后端严：标题会进导出文件名，Bidi 能让文件名显示成别的扩展名；后端那边加 Bidi 会改 chart_fixtures 和注入判定表（app/core/text.py:7 的说明），不在本次范围。
  4. **导出路径（新增）**：gen_ui_types 往 chart_schema.json 加一个 `display` 对象：`{"unsafe": DISPLAY_UNSAFE, "title_max": TITLE_MAX}`。Bidi 表是前端独有的，写在前端，不导出。chart_schema.json 本来就在 `gen_ui_types --check` 的比对清单里，后端改了这两个值、前端没重生成，--check 就红；tests/test_charts.py 加一条比对 `display` 与 charts.py 常量。
  5. localStorage 校验：`parseEdit` 给 title 单独一条：必须是 string、长度 ≤ 100、且 `sanitizeTitle(v) === v`（存进去的永远是清过的串，不等就是被手改过），不满足就丢掉这个字段（只丢 title，别的字段照常），和数值字段坏值丢弃同一个口径。
  6. canvas 渲染，不进 DOM。标记卡组头的「当前值」会显示标题，那是 React 文本节点（自动转义），不用 innerHTML、不进 `title=` 属性。不碰 `document.title`。导出文件名本来就取标题，仍经 `safeFilename`。
  7. THREAT_MODEL §2.3 表面列表加一行；prepare.ts 头注释「用户字符串的规范化只在后端做」改成「后端出的串在后端做；用户在本机输入的标题在前端 sanitizeTitle 做，规则表由生成共享」。
  8. vitest：注入串（含 `{a|x}`、换行、Bidi、`<img onerror>`、101 字）当标题，SSR 渲染不产生 DOM 节点、title.text 等于清洗结果、导出文件名不含 Bidi；parseEdit 读到未清洗 / 超长 / 非字符串的 title 时丢弃。
- 存储：`Edit.title: string | null`。标题**不**随「应用到同类」带走（每张图的标题是它自己的）。

**B4 应用到所有同类图表（新）**
- 先说清楚现状：**开关本来就按图型存**（`uiPrefs.ts` 的 `datachat.chartUi:<kind>`，EChart.tsx `getPrefs(prefKind)`），改一张柱图的数值标签，所有柱图都跟着变。所以这个按钮只管层 1 的改动。
- 按钮把这张图的**可迁移字段**存成该图型的默认：`colors`、`colorBy`、`font`、`other`（饼图）。**不迁移**：`yMin / yMax`（跟数据量级绑定）、`title`。新键 `datachat.chartEditKind:<kind>`。
- 生效：一张图的层 1 = 图型默认 ← 这张图自己改过的字段覆盖。自己改过某个字段的图，这个字段保持自己的；没改过的跟着图型默认走（历史图、以后的新图都算）。按钮旁的提示写「已单独改过的图保持不变」。
- 「重置」只清这张图自己的改动，回到图型默认 + 开关设计默认，不动图型默认。有图型默认时，卡头「重置」旁多一个「清除{图型}默认」，清掉后所有没单独改过的同类图回到原样。
- 实现上 Edit 要能区分"没设置"和"设成默认值"：存储改成只存设置过的字段（parseEdit 读老数据照旧，老数据里有的字段都视为"这张图自己设过"）。

**B5 不做**：设计稿里的形状选择（圆 / 方 / 菱形）、轴组「显示网格」开关、标签「位置」下拉、「复制结果」、图表全屏、卡头 badge。前三项是新的开关，不在 07 §5 的范围里；要做再单列。

#### C. 设置页「测试连接」

1. **接口**：`POST /settings/test`（要 Bearer）。用**已保存**的设置（model、base_url、timeout，Key 走 `resolve_api_key`）发一次最小请求：一条固定的 user 消息（"ping"），`max_tokens=1`，不重试（`max_retries=0`），超时取 `min(timeout, 15)` 秒。
2. **返回** 200：`{"ok": true, "latency_ms": N, "model": "…"}` 或 `{"ok": false, "llm_kind": "…", "message": "…", "latency_ms": N}`。`llm_kind` 取 `classify_error` 的值（含 `http_NNN`）；没 Key 时不发请求，直接 `no_key`。`message` 走 T11 的 `user_error`（同 llm 错误卡的文案，不带上游原文和 Key）。不落库、不写 events。
3. 同一时间只允许一个测试在跑，第二个返回 409。
4. **前端**：凭证卡和模型三项下面一个「测试连接」按钮。表单有未保存的改动时按钮不可点，旁边写「先保存再测试」（测的是保存后的配置，避免"测的和用的不是一份"）。结果：成功「连接正常 · 0.8s · deepseek-chat」（绿）；失败显示 message，llm_kind 是 auth / no_key 时把焦点移到 Key 输入框。
5. **假模型服务**：`tests/fake_llm.py` 加一个 ping 场景标记 `MARK_PING`（现在认不出的请求一律 400，测试连接的固定消息会被判成 400），`fail-401`、`hang-Ns` 等原有场景照常用。
6. **测试**：pytest 每种结果一条（ok、no_key、auth、rate_limit、timeout、server、409 并发、返回里没有 Key 串）；vitest 按钮三态 + 未保存时不可点；e2e（fake）ok 和 fail-401 各一条。

#### D. P1-17 图表警告文案（后端）

1. 现状：`chart_warnings`（result.py:112）把 ChartError 原文直接拼进用户看的警告，「图表未生成：x 列 'region_name' 不存在；可用列：…」，这句话是写给模型看的（charts.py:165，要带列名让模型自己改），用户看到的是变量名和参数名。
2. **改法**：ChartError 原文**照旧**回到模型（chart_errors 不动，模型自我修正要靠它）；`chart_warnings` 里给用户的两条改成固定文案，不带原文：
   - 一张都没画出来：「图没画出来：模型给的画图参数和结果数据对不上。结论不受影响，可以重新生成。」
   - 画出了一部分：「另有 N 张图没画出来：画图参数和结果数据对不上。」
   **用户界面上从此看不到原文**（S 10-23 核过：TurnView.tsx 的 exec 折叠区只渲染 stdout / result_text / error，前端没有任何地方读 chart_errors）。原文只回到模型（chart_errors），模型下一轮能自己改。这是有意的取舍：不为这条加新 UI；用户来问"图为什么没出来"，答案就是固定文案里的"重新生成"。以后要在执行详情里列 chart_errors，另立方案。
3. 不按错误类型分文案：对用户来说出口都是"重新生成 / 换个问法"，分成 22 种只是把模型的话翻译一遍，还得维护映射。前端也不匹配这些文案（黄条照旧显示第一条信号原文）。
4. 判定变更：tests/test_chart_slot.py :141 / :227 / :235 / :261、tests/test_fake_llm.py :284 / :294 的前缀和 `"nope" in w[0]` 断言改成新文案、并改断言"警告里**不含**原文"（行为变化：原文不再进警告）。`ui/web/src/views/v2a.test.tsx` 里的 `"图表未生成"` 是夹具字符串，不依赖后端文案，不用改。

#### 验收（实现 PR）
- 闸门：pytest、vitest、e2e、lint、tsc、gen --check（同 PR 重生成 chart_fixtures.json / chart_schema.json）、build 全绿（f4-visual 以 CI 为准，11、25 两屏按 HANDOVER §6 换基线，DEVLOG 写明每屏为什么变）。条数变化逐条写理由。
- A 组：vitest 纯函数表驱动 8 → 10 / 97 → 120 / 412 → 500 / 11.4 → 12.5 / 0.3 → 0.4，紧凑 8 → 10（interval 5）；SSR 断言 `bar`（最大值 8）开标签时刻度是 0 / 2 / … / 10、关标签时不写；用户填了上限或下限时不写；堆叠时按堆叠和；全负不写。x 轴刻度文字到轴名默认字号 ≥ 12px、字号「大」≥ 8px（SSR 估算）；`grid.left/right` 在 640 和 1174 两个宽度下等于 12 / 16（不随宽度变）。e2e：25 屏 1024 宽下 y 轴线到卡左缘 ≤ 46px（读 canvas 像素找轴线）。
- B 组：vitest 组头当前值 5 组、整组不可用的理由在组头、「完成」关卡、按类目着色（单系列柱图才出现、写 colorBy、颜色行换成类目）、标题（空串回到后端标题、注入串 SSR 不产生 DOM、限长 100）、应用到同类（迁移字段 / 不迁移字段、自己改过的不被覆盖、清除图型默认）。e2e：f4-panel 加「应用到所有柱状图」跨两张图生效。
- C 组、D 组：见上面各自的测试条目。

### F4 迭代 V2c：F5 第一批发现（已定，S 10-25 评审通过，PR #75；实现 PR #76；DEVLOG [63][64]）

来源：S 10-23 本机走查（Windows + Firefox，缩放 90%）第一批 8 条，加测试 agent 10-24~25 的基线报告（假模型 F5 ①~⑥ 全过，pytest 852 / vitest 848 / e2e 非视觉 35/35；不入库）。白屏已由 #74 修掉（squash 0c777a1），不在本节。S 的真 Key 五条路径还没走完，走完的新发现**补进本节**，再一起评审；实现合一个 PR、最后统一跑闸门。

按 F5 的约定，观感问题（3~8）是 V2 的输入，在阶段 6 之前做完；1、2 是功能问题。

#### 1. 测试连接：保存后旧结果又显示出来（bug）
- 证据：`SettingsView.tsx:173-182` 只用 `!unsaved` 判断显示与否。测完 → 改 Base URL（unsaved，结果隐藏）→ 保存（unsaved 变回 false）→ 刚才那次针对**旧配置**的结果重新出现。
- 规则：结果绑在"测的那一份已保存配置"上。任何字段 onChange、填新 Key、保存成功，都 `setTest(null)`。`unsaved` 只管按钮禁用和「先保存再测试」提示，不再参与结果显示。
- 验收（vitest）：成功 → 改字段 → 改回原值，结果不出现；成功 → 改字段 → 保存，结果不出现；失败的结果同理。

#### 2. 测试连接失败：正文不放上游英文原文（S 10-25 定：原文折叠保留）
- 证据：失败时 `message = user_error("llm", e)`（app.py:590），格式是「中文原因，共尝试 n 次：上游 message（编号）」（errors.py:145 起）。分析的错误卡已经把上游原文收进「技术详情」（TurnView.tsx:238，验收 P1-2/3），设置页还是整串直出。
- 规则：和错误卡一致。把 ErrorCard 里按 llm_kind 给标题、建议的那段映射抽成一个函数，两处共用；设置页失败显示「标题 + 建议（编号）」，`message` 原文放进默认折叠的「技术详情」。后端接口不变（已返回 `llm_kind`）。
- 为什么不直接去掉原文：模型名写错、Base URL 少 `/v1` 这类配置问题，上游原文是最直接的线索；设置页正是用户排查配置的地方，所以留着，只是折叠。

#### 3. 设置页、数据集页没有返回入口
- 证据：视图是 Shell 里的一个 state（`Shell.tsx:20` `useState<View>`），不进浏览器历史；浏览器后退会直接离开应用，页面上也没有返回按钮，只能靠侧栏。
- 规则：Shell 记住上一个视图 `prev`（进设置 / 数据集时记下，删除会话 / 数据集后把指向它的 prev 清掉）。设置页、数据集页 topbar 标题左侧加「← 返回」，回到 prev，没有 prev 就回首页。首次启动没配 Key 时自动进的设置页不显示返回（那时没有可回的地方）。
- 不做：接浏览器历史（pushState）。Tauri 里没有后退键，收益只在 Web 版，等阶段 7 再说。

#### 4. 字号整体偏小
- 证据：根 `font-size: 13px`（styles.css:20），但 styles.css 里 133 处 `font-size` 全部写死 px，只改根字号什么都不会变。
- 规则，分两步，同一个 PR、两个 commit 便于评审：
  - a. 机械换算：所有 px 字号改成 rem（÷13，保留 4 位小数），根字号不动。**验收：f4-visual 四屏基线零变化**，证明这一步没改观感。
  - b. 根字号 13 → **14**（S 10-25 定；整体 +7.7%）。S 浏览器 90% 下约等于现在的 100%。四屏基线全部重取（CI actual）。
- 不随之变：ECharts 画布里的字（由主题和层 1 字号控制）、行高和控件高度的 px（44px 行高等）。

#### 5. 结论正文排版生硬
- 证据：`.md` 只定了 p、table、pre（styles.css:225-231）；h1~h4、ul/ol/li 没有规则，吃浏览器默认值（h1 是 2em，列表上下 1em 外边距），模型一出标题和列表就显得忽大忽散。
- 规则（数字以根 14px 计）：`.answer` 15px / 1.7；`.md h1,h2` 17px 700、上 18 下 8；`h3,h4` 15px 700、上 14 下 6；第一个子元素去掉上边距；`p` 下 10；`ul,ol` 左缩进 1.4em、下 10；`li + li` 上 4；`table` 上下 10、表头 600。
- 验收：加一个 Markdown 渲染的 vitest（标题 + 列表 + 表格）只验结构；观感以 S 看 25 屏新基线为准。

#### 6. 会话删除入口找不到
- 证据：删除在「⋯」菜单里（Shell.tsx:254-256），`.sess-more` 平时 `opacity: 0`，只在 hover 时出现（styles.css:131-132）。
- 规则：当前会话那一行的「⋯」常显；其他行仍 hover 显示；`@media (hover: none)` 下全部常显（触屏没有 hover）。
- 不做：删除按钮外露。误删代价高，保留菜单 + 二次确认。

#### 7. 数据集预览的滚动条
- 证据：`.table-scroll { overflow: auto; max-height: 60vh }`（styles.css:296）。默认预览 20 行 × 44px 行高 + 表头，常见屏幕高度下超过 60vh，于是表格里出现第二根竖条；Windows 11 的 Firefox 用浮层滚动条，横条盖在最后一行上。
- 规则：去掉 `max-height`，表格按行数撑开，竖向跟页面一起滚（这也就是 S 要的"能放大"）；`.table-scroll` 底部留 12px，横条不再压行。表头 sticky 只在表格自己有竖向滚动时生效，撑开后不再吸顶，接受。
- 验收：08 屏（数据集预览）基线重取。

#### 8. API Key 占位文字用了等宽字体
- 证据：`.settings .key-field input` 整体是等宽（styles.css:339），占位「已保存在系统凭据中」也跟着等宽。
- 规则：`::placeholder` 和只读态改回界面字体；用户输入的 Key 本身仍等宽（便于核对字符）。

#### 9. f3-inject 在 Windows 本机红 3 条（测试可移植性）
- 证据：`f3-inject.spec.ts:236` 的前提要求 P4~P7 全部画成 x 轴标签；P5 是 `{x|富文本}`（tests/fake_llm.py:93），Windows 字体下更宽，被 hideOverlap 丢掉，前提先红，注入判定没执行到。CI（linux）绿。
- 规则：这一条前提只在 linux 上断言，其他平台 `test.skip` 并写明"类目标签集合依赖字体度量，以 CI 为准"，和视觉基线以 CI 为准（HANDOVER §6）一个口径。不放宽 linux 上的断言。
- 不做：改夹具关掉 hideOverlap。那会改 chart_fixtures，而注入测试要测的就是产品真实配置。

#### 记录不改
- 测试 agent O1：curl 用 GBK 字节传的 multipart 文件名存成乱码；浏览器上传走 UTF-8，不受影响。
- 测试 agent O2：停止要等当前模型调用返回才收尾，符合"不主动断流"的设计；真模型下的手感留给 S 的 F5 ⑤。
- S 本机环境：`ui\web\dist` 因管理员身份解压而删不掉；`ui\web\web\web-dist` 是多解压了一层的未跟踪目录，会打爆本机 eslint。HANDOVER 里给 web-dist 解压步骤补一句"普通权限、直接解到 `ui\web\dist`"，不改 eslint 配置。

#### 判定变更预告
- f4-visual 四屏（08、11、24、25）基线全部重取（4b、5、7）；4a 那个 commit 必须零变化。
- vitest、e2e 里写死字号或用 `opacity: 0` 判断「⋯」可见性的断言如有，逐条写理由改。
- pytest、chart_fixtures 不变（本节没有后端改动）。

### V2d：token 观测与单轮预算（方案，待 S 评审；DEVLOG [65]）

来源：测试 agent 10-25~26 对照《AI Agent Book》第 7 章的审计（复核三定稿）和全书 × 竞品综合稿（都不入库）。两稿的 P0 三件在这里落成规则；P1~P3 记进 plan.md「外部审计待办」。三件**都不改提示词**，fake_llm 的 MARK 认证和闸门准确率不受影响，ScriptedChatModel / fake_llm 在 CI 里就能测，不需要真 Key。

实测基线（docs/eval/gate_*.json，每题 `tokens` = total_tokens，`runner.py:99` 只在 reported 时写）：

| 架构 | 题数 | p50 | p95 | 最高 |
|---|---|---|---|---|
| ReAct（25 题全量 ×5 份） | 125 | 8,975 | 28,846 | 63,817 |
| 工作流（25 题全量 ×3 份） | 75 | 2,343 | 8,411 | 12,996 |

#### 1. usage 拆分
- 证据：`TokenUsage`（app/core/llm.py:60-67）只有 calls / input / output / total / retries / reported；`UsageTracker.add_message`（llm.py:76-88）只读 `usage_metadata` 的 input、output、total。评测报告每题只导 total（runner.py:99）。零调用就失败时 `reported` 停在默认值 True（dataclass 默认），报告里看起来像"上报了 0"。
- 规则：
  - TokenUsage 增加 `cache_read_tokens`、`reasoning_tokens`，从 `usage_metadata.input_token_details.cache_read`、`output_token_details.reasoning` 读（langchain-openai 把 OpenAI 兼容口的 `prompt_tokens_details.cached_tokens` / `completion_tokens_details.reasoning_tokens` 映射到这两处）；服务商不给就记 None（不是 0），表示"没上报"而不是"没用"。
  - 增加 `estimated: bool`：任何一次调用缺 usage 时，这次调用按字符数估算（见 §2a）并置 True；`reported` 语义不变（每次都拿到真 usage 才为 True）。
  - `reported` 初值改为"calls == 0 时为 None"：零调用时报告写 null，不写 True。
  - 评测 / 闸门报告每题导出 `tokens_in`、`tokens_out`、`tokens_cache_read`、`tokens_reasoning`、`tokens_reported`、`tokens_estimated`；原 `tokens`（total）保留，旧报告可比。
- 验收（pytest）：ScriptedChatModel 返回带 input/output_token_details 的 usage → 四个字段都累加；不带 details → 两个新字段 None；不带 usage → estimated=True、reported=False；零调用失败 → reported 为 None；runner 导出新字段且 `tokens` 与原口径一致。

#### 2. 单轮 token 预算
- 证据：没有任何 token 上限，只有 ReAct 的 `recursion_limit=25`（service.py:51；图步数，模型调用和工具调用各算一步，约 12 次模型调用）和工作流的 `max_attempts=3`。ReAct 每次模型调用都重发系统提示 + 全部历史（react_agent.py:102-104），花的是用户自己的 Key。
- 规则：
  - 单轮预算 `DATACHAT_TOKEN_BUDGET`，默认 **130,000**（ReAct 实测最高 63,817 的约 2 倍；工作流最高 12,996，正常碰不到）。设成 0 关闭。只在后端，不进设置页。
  - a. 计数口径：每次调用后累加 total；缺 usage 的调用按「输入字符数 + 输出字符数」÷ 2 估算（中文约 1 字 1 token、英文约 4 字符 1 token 的折中，宁可多算），同一个预算线，置 `estimated`。
  - b. 判定时机：每次模型调用**之前**检查"已用 + 预留 ≥ 预算"，预留 = 强制收尾那次调用的量（取最近一次调用的输入量，没有就 0）。这样超限后收尾那一笔也在预算内。
  - c. ReAct 超限：停在当前步，走步数到顶的强制收尾通道（service.py:480-500）——用已有执行结果出结论，warning 写「本轮 token 用量达到上限（N），已根据已有执行结果收尾」；收尾也失败时与步数到顶相同，`error_kind=agent`。
  - d. 工作流超限：executor 之后的条件边（graph.py:11-15 `_route_after_exec`）加预算条件，超限即使还有重试次数也不进 reviewer，直接走 summarizer——与重试用尽是同一条路径，warning 同上。planner / codegen 之前超限（只可能在预算设得很小时）直接以 `error_kind=agent` 结束。
  - e. 前端：每轮卡片底部现有耗时（turn.ts:175 `timings.total`）旁加「约 N tokens」；`estimated` 时数字前加「≈」并在 title 写"服务商未返回用量，按字数估算"；`reported` 为 None（零调用）时不显示。
- 验收：
  - pytest：ReAct 用 ScriptedChatModel 每次报大 usage → 第 k 次调用前停、出 forced_answer、warning 文案；工作流第一次 exec 失败且已超限 → 不调 reviewer、走 summarizer；缺 usage 时按估算触发；预算 0 → 不触发；收尾预留：预算恰好卡在"再调一次就超"时先收尾。
  - vitest：卡片显示 tokens；estimated 显示「≈」；零调用不显示。
  - e2e：fake_llm 加一个场景按调用返回大 usage（现在固定 10/5，tests/fake_llm.py:301），断言卡片出现预算 warning 和结论。

#### 3. finish_reason=length 作为明确错误
- 证据：除测试连接（max_tokens=1）外，所有调用都不传 max_tokens（llm.py:198-205）。模型输出被服务商默认上限截断时，codegen 拿到半截代码 → 语法错误 → 进 reviewer 重试，用户看到的是"代码执行出错"，原因被掩盖。
- 规则：节点调用和 ReAct agent 调用检查 `response_metadata.finish_reason == "length"`：codegen / reviewer 截断不执行半截代码，记一次失败、error 写「模型输出被截断（达到输出长度上限）」，照常进重试；summarizer / ReAct 结论截断时保留已有文字，加 warning「结论可能不完整（模型输出达到长度上限）」。
- **本节不设 max_tokens 上限。** 理由：思考 token 是否计入 max_tokens 因服务商而异，当前看不见；等 §1 上线后用真 Key 跑一遍闸门，拿各节点 output / reasoning 分布，再定一个可配置的上限（取实测最高值的若干倍）。
- 验收（pytest）：ScriptedChatModel 返回 finish_reason=length 的 codegen → 不进 executor、attempts+1；summarizer → 有 warning、answer 保留。

#### 判定变更预告
- pytest：新增上述用例；旧的 usage 断言里 `reported` 在零调用路径从 True 变 None，逐条写理由。
- 闸门 / 评测报告结构加 6 个字段，旧报告不重写；FROZEN.md 的可比性规则不变（只比 total）。
- vitest / e2e：卡片底部多一段 token 文字，f4-visual 的 11、25 屏基线大概率要重取。
- 提示词、chart_fixtures 不变。

#### 不做（记在 plan.md）
- 前缀重排（P3，先用真 Key 测 cached_tokens）、ReAct 状态栏（P1，单独 A/B）、分节点紧 max_tokens（撤回）、陷阱题组 / LLM-judge / 过程验证器（阶段 7）、M06 打包沙箱（阶段 6 第一步）。

## 7. 与前端并行，不在 F 路径上
- 错误文案脱敏（THREAT_MODEL T11）：单独一个 PR，F2 之后做；先定规则再改阶段 3/4 的代码。
- A1 自动复跑规则：单独一个闸门 PR，赶在下一次跑闸门之前做（比如验证 B70 时）。方案见下文「A1 错题自动复跑」。
- [30] 的 SHA（4497d2b）随 F0 一起回填（已做，见 DEVLOG [31]）。
- 饼图类目 >6 时颜色循环（调色板 6 色，第 7 项与第 1 项同色；F3 第六步截图发现，非第六步引入）：S 10-19 定归 F4，写 F4 方案时给出规则（扩色 / 合并"其他" / 二者结合）和验收。
- chart_errors 按执行记账（result.py:117，单独一个 PR）。方案见下。

### chart_errors 按执行记账（result.py:117）

现状（代码证据）：
- `_tally_charts`（service.py:265）把每次执行的 `chart_errors` 累加进 `res.chart_errors`，失败的执行也算。
- `chart_warnings`（result.py:117）只在 `not has_option` 时报"图表未生成"。这个条件同时干了两件事：挡掉失败那次执行留下的旧错误（对），也吞掉了成功那次执行里"一张成功、一张失败"的错误（错，违反 [23]/[24] 不静默丢弃）。
- chart() 参数错误不让执行失败（test_react_chart_error_reaches_model_and_warnings：res.ok 且 result==1），所以"展示的那次执行里有 chart_error"是常见情况，不是边角。
- 展示哪些图：workflow 是最后一次 executor 的 state（只有失败才重试，所以就是唯一成功那次）；ReAct 是所有成功执行的图之和（react_agent.py:202 在成功时 extend sink["charts"]）。

已实现（#55 / ff7b8dc，DEVLOG [43]；本段状态 10-21 更正）：
1. 新字段 `res.chart_errors_shown`：只收"图被展示的执行"自己的 chart_errors，即 error 为空的执行。workflow 取最后一次成功 executor；ReAct 取所有成功 exec。`res.chart_errors` 保留原语义（全部累加，评测计数用，chart_smoke 不动）。
2. `chart_warnings` 只看 `chart_errors_shown`：
   - 没有展示的 option 且有错 → 「图表未生成：<最后一条>」（文案不变）。
   - 有展示的 option 且有错 → 「另有 N 张图未生成：<最后一条>」，N = len(chart_errors_shown)。
   - 错误只出现在失败的执行里 → 不报（那次的图已由"已丢弃"警告覆盖）。
3. 判定表纪律：test_react_chart_error_reaches_model_and_warnings、test_real_chain_inject_error_reaches_warnings 期望不变（错误都在成功执行里，无图）。若有现存测试依赖"失败执行的旧错误被报出"，改期望并写明原因：那次的图已丢弃，旧错误对用户不再成立。
4. 事件不变：exec 事件里的 chart_errors 本来就是单次执行的（_chart_event_fields），前端不用改。

验收：
- workflow、ReAct 各一条：同一次成功执行里两次 chart()，一次成功一次列名错 → 1 张图 + 警告「另有 1 张图未生成：…」。
- workflow、ReAct 各一条：第一次执行 chart() 列名错 + 代码报错，重试成功并出图 → 只有"已丢弃"警告，没有"未生成"。
- ReAct：两次成功执行，第一次 chart 错、第二次出图 → 警告「另有 1 张图未生成」（两次的图都展示，第一次的错误仍成立）。
- fake 模型复用现有场景，必要时加一个 chart-partial 场景（同一段代码一对一错）；真链路 workflow/react 参数化各一条。

### issue #49：矮画布紧凑几何（已定，S 10-20 让直接修；规则与实现同 PR，DEVLOG [45]）

1. 触发：容器高 < 300px（默认卡片 360 不触发）。由 EChart 的 ResizeObserver 量出来，写进 UiState.compact；导出用同一个 ui。
2. 收紧：grid.top 有标题 36 / 无标题 16；grid.bottom −16（下限 14）；x 轴 nameGap 22；y 值轴 splitNumber 3、showMinLabel / showMaxLabel。只收紧不放宽，饼图不动。键登记在 COMPACT_KEYS。
3. 验收：1200×220 长轴名夹具 plot 区 ≥ 40%，值轴首末刻度（0 和 3）都画出来；长轴名那条 e2e 的全部断言在 220 高下照旧成立；360 高时产物和修之前逐字节相同。

### T11 错误文案脱敏（已定，S 10-20 第二轮；THREAT_MODEL §2.4）

> 实现：DEVLOG [48]。偏离见 [48]。S 10-20 第三轮补充（实现时落地，覆盖下文对应条目）：
> - **文案只写详情，种类由 error_kind 承担**：界面渲染为「{KIND}失败：{文案}」（TurnView.tsx KIND），所以文案里不写「LLM 调用失败」「分析流程」「数据集读取失败」这类前缀。classify_error 的内部枚举经 `LLM_KIND_TEXT` 映射成中文，unknown 省略。常量相应改为：agent →「内部错误」，dataset 兜底 →「无法读取文件」，解析 →「CSV 第 N 行无法解析」。
> - **机械约束**：user_error 返回 `UserText(str)`，F2 常量也是 UserText；`Emitter.error` 断言 message 是 UserText，只有 kind=execution（exec 原文）例外。
> - **dataset_message 判定顺序**：精确类在前，宽类（ValueError）兜底在后。每一类用只属于它的异常构造测试。
> - **数据集预览**：日志行带 dataset id 和文件名。
> - **keystore 纳入，改源头**：keystore.py 的 :40、:49、:86/:97、:90 不再拼类型名或后端全限定名，细节进日志；app.py 只负责转成 400。CLI status 仍显示后端全名（本地终端，不进界面）。
> - **charts._CTRL 不并**：它和 text.py 里的集合用途不同，原因写在 text.py 的注释里。

**纳入原则：按生成点算，不按字段算**。凡是经 `user_error` 生成的串都已脱敏，不管它最后落在 `res.error`、`Step.error`，还是非致命 error 事件里。exec 原文一律不经过 `user_error`。所以：
- `service.py:176` 的 `Step("load", error=res.error)` 是 res.error 的拷贝，要脱敏。
- `service.py:290` 的 `s.error = upd.get("error")` 是沙箱 exec 原文，按 T9 只当文本渲染，**不脱敏**。代码面板 / observation 里的 traceback 同理。
- keystore 的 CLI 输出不在渲染面上，不纳入。

**规则**：
1. **唯一出口**：新增 `app/core/errors.py` 的 `user_error(kind, exc_or_text, *, trace_id, question=None)`，所有到界面的错误串都由它生成。原始的 `{type(e).__name__}: {e}` 和堆栈只按 trace_id 写进 server.log。
2. **编号统一追加、不设例外**：由 `user_error` 在文案末尾追加`（编号 xxxxxxxx）`，取 trace_id 的前 8 位，并写进 messages.content。content 是跨会话唯一保留下来的载体，也是用户唯一会复制、截图的东西；如果由前端渲染 message.id[:8]，用户复制不到。可查性：`app.py:412` 里 trace_id=msg_id，`__main__.py:47` 把日志落盘到 home/server.log，编号能和日志里的 trace= 对上。各处常量文案**不要**自己写编号。
3. **dataset：已知异常转成常量**，不带路径和类型名。
   - 文件不存在 →「数据文件不见了，请重新上传」
   - 编码 →「无法识别文件编码」，保留试过的编码列表
   - pandas ParserError →「CSV 解析失败」，可以保留"第 N 行"（正则只取行号）
   - EmptyDataError →「文件是空的」
   - 我们自己抛的中文校验文案原样保留
   - 其他一律 →「数据集读取失败」
   - 多表数据集：`dataset.py:63-66` 的 `load_data` 要逐表捕获，把**文件名**（只带文件名，不带路径）带进异常，常量文案前面加「表 x.csv：」。否则多表时"文件不存在"定位不到是哪一张。
4. **上游原文（llm / gateway）：保留，并做固定的四步处理**。这是用户自救的依据，比如余额、模型名、context 超限。
   - (a) 只取 `error.message`，不要异常 repr，也不要 `{type}:` 前缀。
   - (b) **只剥用户问题**：问题整串在上游文本里出现就换成 `…`（问题 ≥ 4 字才判）；另外兜一条截断回显：问题的最长前缀（≥ 12 字）出现在上游文本里也换掉，网关截断 body 时只会剩半句。**不剥**列名、代码、数据字典：它们在表头、轴标签、图例、代码面板里本来就按设计显示，剥掉不会减少任何泄漏面，还会和 ChartError「可用列」必须保持原文那条规则冲突（短列名被剥成 … 后，「列 price 不存在」会变成「列 … 不存在」）。
   - (c) 打码：`sk-` 加 ≥ 8 位的 Key、带 query 的 URL、文件路径（盘符或 / 开头）。
   - (d) 洗控制符：复用**同一份**字符集（`app/server/app.py:66` 的 `_CONTROL_CHARS`，含 C1 和 bidi）。core 不能反向依赖 server，所以把它挪到 `app/core/text.py`，app.py 改成 import，仓库里不新增第三份；`charts._CTRL` 维持现状不动。然后截到 200 字。
   - **剥离放在 service.py 做，不放 llm.py**：LLMClient 手里只有拼好的 prompt，分不出哪段是问题。`LLMError` 新增 `upstream: str | None`，放上游 message 的原文；`service.py:244` 的 `str(e)` 改成 `user_error("llm", e, question=...)`。kind 和尝试次数由我们自己生成，保留。
5. **agent / 未知异常 → 常量**：「分析流程内部出错」。
6. **必须一起改的生成点**（第一轮漏掉了下面四处）：
   - `service.py:175`、`246`、`412`、`414`
   - `llm.py:237`（只改它的 message 结构，用户串由 service.py 生成）
   - `app.py:213`、`222`（数据集预览）
   - `service.py:184`（字典非致命）
   - `service.py:464`：「接口返回错误内容：{bad}」。bad 是上游原文，最常见的失败路径（B45 / B62），走第 4 条。
   - `service.py:431`：非致命 error 事件用的 why 里含有 `api_error_text(final)`，走第 4 条。
   - `service.py:525`：「结论：{res.answer[:100]!r}」把模型答案的 repr 塞进了错误文案。改成常量「模型没有执行代码也没有按契约拒答」，答案本身只进日志。

**验收：断言跑出来的串，不扫源码**。grep `type(e).__name__` 扫不到 f-string、`str(e)`、`.format` 拼出来的串，和 AST 扫描器只能扫字面量是同一类问题。
- 场景表驱动：dataset（文件不存在、编码、解析、空文件、多表缺一张）、llm（fake_llm `fail-<code>`、超时、gateway 错误内容）、agent（注入异常）、字典非致命、数据集预览、`service.py:431` 和 `525` 两条路径。每个场景都跑完，取**所有界面文案**（error 事件、done、messages.content、Step.error 里经 user_error 生成的部分、预览 error），断言：
  - 不含 `Error`、`Exception`、`Traceback`、盘符或绝对路径、`sk-`、C0 / C1 / bidi 控制符；
  - 末尾正好有一个`（编号 xxxxxxxx）`，并且等于 trace_id 的前 8 位；
  - 用户问题不出现（另有一条载荷是问题前缀被截断的回显）；
  - 长度 ≤ 200 + 编号。
- 对照：沙箱 exec 报错的场景里，Step.error **仍然**是 traceback 原文（钉住"exec 原文不脱敏"）。
- 列名保留：上游 message 里带列名时，列名原样保留。
- fake_llm 加场景 `fail-echo-<code>`：上游 message 回显请求里的用户问题（整句一种、截断半句一种），e2e 走完整路径验证界面上看不到。
- 判定表：`tests/test_fake_llm.py` 里的 `"[fake_llm]" in r.error` 保留（上游 message 照常透出），另外断言不再带 `APIStatusError:` 前缀，并且有编号。F2 的常量文案（cancelled / interrupted / stream_aborted）保持不变：它们不经 user_error，也不加编号。

### A1 错题自动复跑（S 10-20 第二、三轮评审改定；DEVLOG [49]；实现 [50]，PR #63）

**问题**（代码证据）：
- m13 的 `allowed_fail` 是逐题登记的（thresholds.json），`_verdict_regression`（run_gate.py:205）把 `failed - allowed` 直接列为回归。
- m09 / m10 这类在 temperature 0 下也会翻的题，因此每次跑闸门都会随机报一次假回归（review-v1 A1：两份参照基线 162428 / 163133 都被判成"有回归"）。
- [28] 那次是手工单题复跑，证据是事后补进仓库的（[30]）。

**S 10-15 定（[30]）**：
- 名单外错题复跑，全对记为波动，有一次错记为回归，取代 [28] 的 ≥4/5。
- 复跑存原始 answer / result_text，并且人工签字（B68）。
- 上游 / 生命周期类失败算无效复跑，可以补跑，不算答错。
- verdict 写明假阴性率。

**已定**：
1. **新增 profile `m13r`，m13 不动**：thresholds.json 的规矩是"改门槛只能新增 profile"。m13r 复制 m13 的 `agents`（allowed_fail 和 why），另加 `"rerun": {"times": 3, "max_makeup": 1, …}`。phase35 不接复跑。
   - 复制会产生两份来源，所以加一条断言 `m13r["agents"] == m13["agents"]` 钉住副本（S 第二轮 一）。
2. **复跑次数 3（S 第二轮 四）**：p² ≤ 25% 只在 p ≤ 0.5 时成立；p=0.7 时两次都对的概率是 49%。改为 3 次后，p=0.5 时假阴性率 12.5%，p=0.7 时 34%。代价是每道错题多 1 次调用。verdict 里写明这张表的前提，不再只写一个"25%"。
   - 另外每题记 `observed_pass_rate`：主报告那次加上有效复跑，一共答对几次 / 共几次。
3. **"对"由谁判（S 第二轮 二，第三轮 一、二、五改定）**：flaky 和回归**都要人工签字才能定论**，比较器在两个方向上都没有定论权。
   - **match 是三态，两种 None 分开处理**：

     | 复跑行 | 含义 | 处理 |
     |---|---|---|
     | executed=False（execution / agent 失败，`match=None`，run_gate.py:100） | 这次确实没答出来 | 有效观测，**记为答错**，和主报告 `auto_correct = match is not None` 的口径一致 |
     | executed=True，`match=None`（auto_judge 自己崩了，:76-77） | 答案在，但比较器判不了 | **无效观测**，补跑，不算回归 |
     | match=True / False | 比较器的参考判断 | 有效观测，只用来排人工先看哪几行 |

     因此 valid 由两部分决定：error_kind 在 RERUN_VALID_KINDS 里，并且不是"executed=True 但 match=None"这种情况。
   - **match 只决定人工先看哪几行**：`--rerun` 跑完后，每道复跑题都进 `{g}_pending_review`，并按"有 match=false 或 executed=False 的题在前"排序，供人工优先查看。match 不会直接把任何一题写成 flaky 或回归。上一版"match=false 直接定回归"已删除：它在判错方向给了比较器定论权，B66 / B68 那类"模型答对、比较器判错"的情况会被直接固定成回归。
   - **签字签在 reruns 行的 `human_correct` 上**（第三轮 五）：
     - 主报告的 cases 行不动，它们在 `--rerun` 之前就已经全部判定。
     - 一道题的有效复跑行全部填了 human_correct 才算结案：全部是 true → `{g}_flaky`；有一行 false → `{g}_regressions`，这一行还要填 failure_class，和主报告的 :149 同规则。
     - 有效行里还有 human_correct 为 None 的，这道题留在 pending_review。
     - 无效行不需要签字。
     - 这条完整性检查是新写的：现在的 :144 只看 cases，复跑行不在它的检查范围内。
   - 工作量：约 5 道错题 × 3 行，每行看 result_text 的前几十个字。
4. **有效性用白名单（S 第二轮 三）**：
   - `RERUN_VALID_KINDS = (None, "execution", "agent")`：题目本身的结果，交给人判对错。
   - `RERUN_INVALID_KINDS = ("llm", "cancelled", "interrupted", "dataset")`：上游、生命周期或环境问题，不是题目错。
   - 断言：`set(ERROR_KINDS) | {None}` 必须恰好等于两者的并集，而且两者不相交。将来新增 kind 时不登记，这条测试就会红。
   - **偏离 S 的草案**：dataset 也放进无效。理由和第 5 条一致：闸门数据是冻结的本地文件，读取失败属于环境抖动，跟模型无关。
   - 每题跑满 3 次，其中有无效的就补跑 1 次，所以每题最多 4 次。
5. **flaky 分原因（S 第二轮 五）**：每道 flaky 题记 `flaky_cause`。主报告那次的 error_kind 在 RERUN_INVALID_KINDS 里时记 `env`（比如主报告是 dataset 失败、复跑成功），否则记 `model`。统计模型稳定性时只看 `model`。
6. **退出码四档（S 第二轮 ②，第三轮 三）**：

   | 码 | 含义 |
   |---|---|
   | 0 | 通过：已复跑的题全部签成 flaky，措辞是「已复跑的 N 题里没有回归」，并附 flaky 名单和原因 |
   | 1 | 有回归：有题签成 regressions |
   | 2 | 无法判定：有 rerun_invalid（补跑后有效次数仍不足 3 次），或有 pending_review 还没签字，或 m13r 还没复跑（待复跑） |
   | 3 | 前提不满足：主报告没判完（:146）、缺 failure_class（:149）、profile 未知（:45）、agent 不在门槛里（:212）、没给 --profile（:237），以及新增的复跑前提比对失败 |

   - 现在这些前提失败用的是 `sys.exit(str)`，退出码是 1，会和"1 = 有回归"撞上。所以 run_gate.py 里所有前提失败统一改成先打印到 stderr 再 `sys.exit(3)`；这对 m13 / phase35 也生效，因为它们的前提失败本来也不该用 1。
   - **m13 / phase35 的成功路径有意不改**：它们有回归时，退出码现在是 0，以后仍是 0（verdict() 返回 out，:183）。A1 只给 m13r 加 0 / 1 / 2，不改既有闸门的 CI 行为。所以 **m13 / phase35 的 0 只表示"跑完了"，不表示"通过"**，结论看报告里的 regression_verdict。这句也写进 docs/gate/README.md。
   - 「没有 Key / 上游 429」和「代码有回归」是两件事，所以 rerun_invalid 不压成 1。这和 interrupted 不并进 cancelled 是同一条原则。
7. **sha 带 `?`（S 第二轮 ③）**：沿用 run()（:118）的先例，默认警告并继续，报告的复跑段写 `sha_verified: false`。需要严格复现时显式加 `--require-sha`，带 `?` 就退出。
8. **复跑的前提**：复跑前逐项比对，有一项不一致就拒绝。比对项是主报告的 `git_sha`、`agent`、`use_dictionary`，以及 run_metadata 的 `model`、`temperature`、`base_url_host`、`python`、`pandas`（S 第二轮：pandas 版本会改 result_text 的浮点格式和排序稳定性）。
   - 已知前提比看上去弱：run() 没有把 data_path 传给 run_metadata，报告里没有 data_sha256，只能靠 answers.json 的 sources 间接判断（那是生成 answers 时的哈希，不是这次实际读的文件）。A1 不修，记在这里。
9. **复跑写在同一份报告里**：报告加一个 `reruns: [...]` 数组，每行和 cases 行同构（answer / result_text / code / error_kind / match / duration_s 都在），另加 `attempt`（每题内从 1 开始）和 `valid`。人工字段 human_correct / failure_class / reason 留空。不用 `time` 这个字段名（顶层 `time` 是报告时间戳）。复跑段的元数据（`rerun_meta`：时间、sha_verified、profile）放在顶层。
10. **一条命令、一个顺序（S 第二轮 结构洞）**：
    - `--rerun REPORT --profile m13r [--only s02 m10] [--require-sha]`：先要求主报告的 human_correct 全部填完，再选出名单外的错题，加上 `--only` 指定的题（比较器漏判的那类，B66 / B68），逐题复跑，追加写进 reruns，最后**直接算出 verdict 写回**（此时通常全部在 pending_review，退出码 2）。
    - 人工在复跑行上签完字后，跑 `--verdict REPORT --profile m13r`，只重算结论，不重复跑模型，按第 3 条结案。
    - m13r 但报告里还没有 reruns：结论写「待复跑」并给出命令，退出码 2。
    - m13 / phase35 下的 `--verdict`：路径一字不动（前提失败的退出码按第 6 条从 1 改成 3，这是唯一的改动）。
11. **防抽签，但给声明过的重跑留口（S 第三轮 四）**：
    - 默认路径：`--rerun` 不带 `--only` 时，如果选出的题里已有 reruns，就拒绝（退出码 3），并提示用 `--only` 显式重跑。防的是不声明的重复抽样。
    - `--only s02`：允许，**替换**该题已有的 reruns 行，并在顶层 `rerun_history` 追加一条 `{time, git_sha, id, replaced_attempts, reason}`，reason 由 `--reason` 必填。被替换的旧行原样搬进这条记录，不丢证据。
    - 这样跑到一半被中断（Key 用完、进程被 kill），或 rerun_invalid 是环境原因造成的（充值后想重跑），都能用 `--only` 加理由继续，不会永远卡在「无法判定」。
    - 中断时写到一半的问题：每跑完一行就落盘一次（写临时文件再原子替换），所以中断后报告里是完整的若干行，不会是半行。

**选题用什么（S 第二轮 ①）**：用人工判定（B），也就是主报告的 human_correct 必须先填完。比较器漏判的题用 `--only` 补进来。两个入口共用同一套复跑和结论逻辑。不做"跑完立刻按比较器复跑"：那样选题只能靠 match，等于把比较器当成真相源。

**验收**（tests/test_gate.py，全部用合成报告，analyze 打桩，不需要数据和 Key，CI 上会跑）：
- 选题：只复跑名单外的错题，加上 `--only` 指定的题；allowed_fail 里的错题和意外答对的题都不复跑。
- 防抽签：不带 `--only` 时，已有 reruns 的题被拒绝（退出码 3）；`--only` 不带 `--reason` 时被拒绝；`--only s02 --reason …` 会替换 s02 的行，rerun_history 多一条，旧行完整保留；中断后（打桩在第 2 行抛 KeyboardInterrupt）报告里有 1 个完整行，可以用 `--only` 续跑。
- 次数：3 次都有效时不补跑；有 1 次无效时补跑 1 次；补跑后仍无效时停在 4 次，结论是 rerun_invalid，退出码 2。
- 三态 match：executed=False 算有效且记为答错；executed=True 且 match=None（auto_judge 打桩抛异常）算无效并触发补跑；两条各一个用例。
- 判定（全部要签字）：
  - 刚复跑完、没签字：全部在 pending_review，退出码 2；有 match=false 或 executed=False 的题排在前面。
  - 签字全部是 true：flaky，退出码 0。
  - 签字里有 false：regressions，退出码 1；这一行没填 failure_class 时退出码 3。
  - match=false 但人工签 true：flaky（B66 / B68 情形）。
  - 只签了一部分：仍在 pending_review，退出码 2。
  - 无效行不签字也能结案。
  - `flaky_cause` 两种取值各一个用例；`observed_pass_rate` 的分子分母正确。
- 退出码：0 / 1 / 2 / 3 各一个用例；m13 下有回归时仍是 0（钉住"有意不改"）；m13 的 `--verdict` 遇到前提失败时是 3。
- 前提：git_sha、agent、use_dictionary、model、temperature、base_url_host、python、pandas 逐项改一个，都会被拒绝（退出码 3）；sha 带 ? 时默认警告并写 `sha_verified: false`，加 `--require-sha` 时退出码 3；主报告有未判定的题时，退出码 3。
- 白名单：`set(ERROR_KINDS) | {None} == VALID | INVALID`，并且两者不相交。
- 顺序：`--rerun` 跑完就写好 verdict；m13r 下 `--verdict` 没有 reruns 时出「待复跑」，退出码 2。
- 回归保护：两份参照基线用 m13 重跑 verdict，除 `thresholds_sha256` 外逐字节相同；`m13r["agents"] == m13["agents"]`；`test_phase35_profile_reproduces_final_verdict` 不变。
- 不做：真模型复跑（S 跑）；把 [28] 的 4 份复跑报告迁到新格式；补 data_sha256；改 m13 / phase35 成功路径的退出码。

估时：大半天。

### G1 闸门 25 条 oracle 上 CI（S 10-21 第三轮评审改定；DEVLOG [51]，PR #64；实现 [52]）

**问题**（代码证据）：
- `tests/test_gate.py:234` 的 `HAVE_DATA` 在 data/gate/ 不存在时，`:302` 的 skipif 会把 25 条 `test_oracle_solvable_on_dirty_data` 全部跳过。
- CI 不生成这份数据，所以这 25 条在 CI 上一直是跳过（HANDOVER §3）。它们守的是"闸门题在 datachat 读到的脏数据上可解、比较器认得出正确答案"。改 csv_io / 沙箱 / 比较器时，如果本地没下数据，就没有任何东西拦得住。
- 方案先行的 PR 里，验证数字一直写成"含本地闸门数据 25 条"，S 只能信我，没法核实。

**实测（本地，10-21）**：
- data/gate/ 一共 173 MB，下载量约 90 MB（UCI zip 加 8 张 Olist 表）。
- 25 条 oracle 用时 65 s，其中 36 s 是 fixture 读表。
- `verify_gate.py` 重算标准答案用时 36 s，写出的 answers.json 和库里的**逐字节相同**（git status 干净，pandas 3.0.6）。

**已定（S 10-21 第一至三轮评审改定）**：
1. **单独开一个 job：`gate-oracle`**，放在 tests.yml 里，不进现有的 pytest 矩阵。
   - 矩阵只有 `ubuntu-latest`、`windows-latest` × Python 3.12。S 本机是 Windows，GB18030 解码、中文路径、PYTHONUTF8 在 Windows 上的行为差异，都要在 Windows 上跑过才算数。3.11 和 3.12 的差异已经由主矩阵覆盖。
   - 主矩阵不动，那 25 条在主矩阵里照旧 skip。所以 CI 里会同时出现两个 25：**主矩阵 25 skipped，gate-oracle 25 passed**。HANDOVER §3 照这个写，避免有人看到主矩阵的 skip 就以为 G1 没落地。
   - 放在 tests.yml 里，自动进入"触发的 workflow 全绿才合并"的条件。不加 paths 过滤：oracle 守的是内核，内核的改动可能出现在任何路径下。
2. **缺数据要报红，并且报错要说人话（S 第一轮 四）**。skipif 在函数体之前生效，所以开关必须让 skipif 自己知道：
   ```python
   REQUIRE_DATA = os.environ.get("DATACHAT_REQUIRE_GATE_DATA") == "1"
   @pytest.mark.skipif(not HAVE_DATA and not REQUIRE_DATA, reason=...)   # 只在不要求数据时 skip
   def test_oracle_solvable_on_dirty_data(...):
       if not HAVE_DATA:
           pytest.fail("闸门数据缺失：data/gate/ 下缺 …（DATACHAT_REQUIRE_GATE_DATA=1）")
   ```
   缺数据时直接报"数据缺失"，并列出缺了哪几个路径，不再靠末尾断言的"数量不对"间接暴露。
   - gate_data 是返回闭包的惰性 fixture，不碰磁盘，所以函数第一行的 fail 一定先于任何 load_data 执行（S 第二轮已核）。
   - **数据根统一由一个 helper 给出（第二轮 小 3）**：`_gate_path(rel)` 读 `DATACHAT_GATE_DATA_ROOT`（默认是仓库根）。HAVE_DATA（:234）和 gate_data 里的 `os.path.join(ROOT, path)`（:297）都改用它。如果只改 HAVE_DATA，子进程单测会读到本机的真实数据，等于白测。
3. **数量断言用 junitxml，不解析人类可读的输出（S 第一轮 三）**：
   - Windows runner 的默认 shell 是 pwsh，没有 grep；pytest 的文字输出格式也会随版本变化。
   - pytest 用精确的 node id 选中这 25 条：`tests/test_gate.py::test_oracle_solvable_on_dirty_data`，不用 `-k oracle`。`-k` 是子串匹配，今天只选中这一个测试是巧合，不是约束。
   - 加 `--junitxml=gate.xml`，下一步由 `scripts/gate/check_junit.py` 解析 testsuite。
   - **import 形状（第三轮 二）**：`scripts/` 和 `scripts/gate/` 都不是包（没有 `__init__.py`），`from scripts.gate import questions` 会抛 ModuleNotFoundError。改为用 `python scripts/gate/check_junit.py` 运行，此时 `sys.path[0]` 就是 scripts/gate，直接 `import questions`，和 run_gate.py:135 的写法一致。单测里按 test_gate.py 现有的 `spec_from_file_location` + `sys.path.insert(GATE)` 方式导入。不依赖 shell，两个 OS 用同一条命令。
   - **期望数不硬编码 25（第二轮 四）**：`expect = len(questions.QUESTIONS)`，断言 `{tests: expect, failures: 0, errors: 0, skipped: 0}`，失败时把 expect 和实际值都打出来。parametrize 和期望值取自同一个来源，这样抓的是"collection 掉了 params"，而不是"题目数变了"；以后加一题不用改 CI。
4. **缓存覆盖整个 data/gate/，命中时完全跳过 build（S 第一轮 二）**：
   - `build_retail()`（:128-136）每次都会无条件 read_excel 再重写两份 CSV，而 to_csv 的输出会随 pandas 版本变化。如果缓存命中也照跑 build，pandas 一升级指纹就不符，CI 会红，但原因是依赖变了，不是代码坏了。
   - 因此 job 写成 `if: steps.restore.outputs.cache-hit != 'true'` 时才运行 `build_gate_data.py`。命中时不下载、不 read_excel、不重写。173 MB 在仓库 10 GB 的缓存额度内。
   - **key 带上依赖和指纹（第二轮 二）**：`gate-data-v2-${{ runner.os }}-${{ hashFiles('scripts/gate/build_gate_data.py', 'scripts/gate/fingerprints.py', 'requirements.txt', 'requirements-dev.txt') }}`。
     - 加 requirements：bump pandas 或 openpyxl 的那个 PR 会当场 miss、重跑 build，产物如果变了就红在这个 PR 上。作者在同一个 PR 里重登指纹，并在 DEVLOG 写明原因。如果不加，风险会一直藏着，直到某次缓存淘汰后，红在一个跟依赖无关的 PR 上。
     - 加 fingerprints.py：重登指纹后缓存一定失效，不会出现旧产物去撞新常量的情况。
     - 代价是每次依赖变动多下一次 90 MB、多跑一次 read_excel，是一次性的。
   - **只用精确 key，不设 restore-keys（第二轮 小 1）**：部分命中时 cache-hit 是 false，build 照样会跑并重写产物，等于拿一套可能对不上的输入去撞指纹。
   - **restore 和 save 拆开（第二轮 小 2）**：`actions/cache/restore` 和 `actions/cache/save` 分成两步。save 的条件是 `if: steps.restore.outputs.cache-hit != 'true' && steps.build.outcome == 'success' && steps.check.outcome == 'success'`，只看数据，不看 oracle 的结果。否则一个把 oracle 判红的 PR 每次 push 都要重下 90 MB。save 只在 --check 通过后才写，坏数据不会被冻进缓存。
   - 按 OS 分开缓存，不用 enableCrossOsArchive。
5. **独立的校验入口：`build_gate_data.py --check`（S 第一轮 一）**：
   - actions/cache 不可变，同一个 key 写入后不能覆盖。key 只能保证生成脚本没变，**不能保证缓存里的内容是对的**。
   - `--check` 只读 data/gate/ 下已有的文件，和期望指纹逐个比对：不下载、不写文件、不读 Excel（只对 xlsx 算哈希）。缺文件或指纹不符就 exit 1，并列出每个文件的期望值和实际值。
   - 缓存命中和未命中两条路径**都要**跑 `--check`：命中时校验现场；未命中时 build 之后再校验一次，顺带发现生成逻辑的漂移。上面那条"pandas 2.1 生成的旧 CSV 被命中"的路径，就是靠它拦下的。
   - **集合相等，不是"包含"（第二轮 三）**：中断的 run 留下的残余文件会被冻进缓存，而且永远不会被发现。所以 `--check` 要求 `data/gate/olist/` 的文件集合恰好等于 8 张 Olist 表，`retail/` 和 `retail_report/` 各恰好 1 个文件，`data/gate/` 顶层恰好是登记过的那几项（UCI xlsx 和三个子目录）。多出来的文件逐个列出，并 exit 1。
   - 常量放进 `scripts/gate/fingerprints.py`（它也进 cache key）。分两组：`SOURCE_SHA12`（源文件：UCI xlsx 加 8 张 Olist 表，即现有的 `UCI_XLSX_SHA256` / `OLIST_FILES`，原样保留）和 `PRODUCT_SHA12`（产物：零售明细.csv、零售报表.csv，新登记，取值来自本地 pandas 3.0.6 生成的文件）。`build` 写完产物后也按 `PRODUCT_SHA12` 比对；pandas 升级导致产物变化时会在这里红，处理办法是重登指纹并在 DEVLOG 写明原因。
   - **单份 PRODUCT_SHA12 同时服务两个 OS，这一点要实测（第二轮 一）**：
     - 已经钉住的：`write_csv` 写死了 `lineterminator="\r\n"` 和 `encoding="gb18030"`，表头和合计行也是手拼的 `\r\n`；requirements 锁定 pandas 3.0.6、numpy 2.4.6、openpyxl 3.1.5（S 第二轮已核）。
     - 唯一的隐式前提是 Excel 引擎：read_excel 没指定 engine，现在能跑只是因为碰巧没装 calamine。**两处都写死 `engine="openpyxl"`（第三轮 四）**：`build_gate_data.py:129`（产物）和 `verify_gate.py:56`（标准答案）。产物和答案必须用同一个引擎；指纹检查只看产物，如果只改一处，引擎有差异的那天会出现产物对、答案错的情况，而且发现不了。
     - 首次运行两个 OS 时，把 `--check` 打印的实际值原样记进 DEVLOG 比对。如果两边不等，立刻把常量改成按 OS 分两份 `{"Linux": …, "Windows": …}`，**不去调参数让两边相等**。
   - **--check 放在 pytest 之前（第二轮 小 4）**：缓存坏了只出一条人话，不用去 25 条失败里找原因。它和 REQUIRE 是两层：--check 管"数据对不对"，REQUIRE 管"pytest 自己不要降级成 skip"。
6. **答案冻结检查（只在 ubuntu 上跑）**：先 `python scripts/gate/verify_gate.py`，再 `git diff --exit-code docs/gate/answers.json`。Windows 不跑，因为 autocrlf 签出会带来行尾噪声，而答案本身和平台无关。
   - **本 PR 的合法变更（第三轮 一，选 A）**：`verify_gate.py:175-176` 会把脚本自身的哈希写进 answers.json 的 `verify_script_sha256`。本步要给 verify_gate.py 加 engine 参数，这个字段一定会变；如果不处理，冻结检查在本 PR 自己身上就会红，而且看起来和"标准答案被改了"一模一样。
   - 做法：同一个 PR 里重新生成 answers.json 并提交，**只允许 `verify_script_sha256` 这一个字段变化**。PR 描述里贴出这一行的 diff，本地用 `git diff --word-diff docs/gate/answers.json` 确认只有这一处改动。其余字段（answers、sources、pandas、questions_sha256）必须逐字节不变。
   - 不选 B（剔掉这个字段再比对），因为那样"重跑一遍就能过"会变成默认路径，等于给掩盖改动开了口子。
   - 已有的覆盖：answers.json 本身就记录了 `pandas` 版本和 `sources`（9 个源文件的指纹，olist 由 os.listdir 枚举），所以源文件身份和 pandas 版本已经被 ubuntu 上的冻结检查间接管住，不需要再加机制。
7. **上游不可达时直接红**：缓存未命中且 UCI 或 GitHub raw 不可达时，job 红在下载这一步，错误信息写明 URL。不重试成绿，也不降级成 skip，由 S 手动 re-run。
8. **缓存预热和淘汰（S 第一轮 五）**：
   - 作用域：PR 的 run 能读 master 的缓存；PR 自己写的缓存只给该 PR 后续的 run 用，不会污染 master；7 天没访问就自动淘汰。
   - 操作：G1 实现合并后，**先在 master 上用 workflow_dispatch 跑一次预热**，在日志里确认 "Cache saved"，run id 记进 DEVLOG。
   - 预期表现，写进 docs/gate/README.md：master 冷了一周以上，下一个 PR 的 gate-oracle 会重新下载，首次大约 5–8 分钟（Windows 更慢）；如果这时 UCI 挂了，这个 job 会红。看到这种红，先看是不是下载步骤，不用去查代码。
9. **许可**：Olist 是 CC BY-NC-SA 4.0，UCI 是 CC BY 4.0。数据只在 runner 上用于评测：不入库、不上传 artifact（失败时也不传 data/gate/）、不放 LFS 或 Release。actions cache 只对本仓库的 workflow 可见。边界：**如果 datachat 将来有商业用途，NC 条款要重新审**。这几条写进 docs/gate/README.md。
10. **超时 25 分钟（第三轮 六，和主 job 一致）**：Windows 冷路径要依次跑 pip install -r requirements-dev.txt（matplotlib、numpy、cryptography 的 wheel）、下载 90 MB（UCI 在境外）、read_excel 读 54 万行、oracle、抄表，估计 10–14 分钟，UCI 不稳时会顶格。超时设大只是晚 5 分钟报警，设小了会随机变红。
    - `--check` **只放在 gate-oracle job 里**，不进主矩阵。主矩阵没有 data/gate，加进去 4 个 job 会全红。主矩阵保持"25 skipped"是设计，不是缺陷。
11. **concurrency 的预期成本（第三轮 七，不改，只写明）**：tests.yml 开了 `cancel-in-progress: true`（:11-13），feebcb7 那次 run 就是这样被取消的。
    - 同一分支连续 push 时，中间那次的 gate-oracle 结果拿不到，只看最后一次。
    - 被取消的 run 不会执行 save，所以频繁 push 的分支可能一直存不下缓存。PR 的缓存本来也不给 master 用，所以损失只是"这个分支下次再下 90 MB"。
12. **顺手修**：.gitignore 里 data/gate 的注释"约 110 MB"改为实测的 173 MB（本 PR 已改）。

**job 草图**：
```yaml
gate-oracle:
  strategy: {fail-fast: false, matrix: {os: [ubuntu-latest, windows-latest]}}
  runs-on: ${{ matrix.os }}
  timeout-minutes: 25
  env: {PYTHONUTF8: "1", DATACHAT_REQUIRE_GATE_DATA: "1"}
  steps:
    - checkout / setup-python 3.12 / pip install -r requirements-dev.txt
    - id: restore
      uses: actions/cache/restore@v4
      with:
        path: data/gate
        key: gate-data-v2-${{ runner.os }}-${{ hashFiles('scripts/gate/build_gate_data.py', 'scripts/gate/fingerprints.py', 'requirements.txt', 'requirements-dev.txt') }}
        # 不设 restore-keys
    - id: build
      if: steps.restore.outputs.cache-hit != 'true'
      run: python scripts/gate/build_gate_data.py
    - id: check
      run: python scripts/gate/build_gate_data.py --check
    - name: 命中时必须跳过 build
      if: steps.restore.outputs.cache-hit == 'true'
      shell: bash
      run: test "${{ steps.build.outcome }}" = "skipped"
    - if: steps.restore.outputs.cache-hit != 'true' && steps.build.outcome == 'success' && steps.check.outcome == 'success'
      uses: actions/cache/save@v4
      with: {path: data/gate, key: ${{ steps.restore.outputs.cache-primary-key }}}
    - run: python -m pytest tests/test_gate.py::test_oracle_solvable_on_dirty_data -q -p no:cacheprovider --junitxml=gate.xml
    - run: python scripts/gate/check_junit.py gate.xml      # 期望数 = len(QUESTIONS)
    - if: runner.os == 'Linux'
      run: python scripts/gate/verify_gate.py && git diff --exit-code docs/gate/answers.json
```

**命中断言（第三轮 五）**："命中时没跑 build"要由机器断言，不靠人看日志。上面那步 `test steps.build.outcome = skipped` 显式写了 `shell: bash`，这样 Windows runner 上也能跑（默认 shell 是 pwsh）。如果将来 if 写错、build 又跑了一遍，重写出的产物和缓存里一致，`--check` 照样绿，只有这一步能发现缓存其实没起作用。

**验收**：
- 单测（tests/test_gate.py，CI 主矩阵上跑）：
  - 子进程 pytest，`DATACHAT_GATE_DATA_ROOT` 指向空目录（本机有真实数据时也必须报缺失，证明 helper 覆盖了 HAVE_DATA 和 fixture 两处）：
    - 设了 `REQUIRE`：返回码非 0，输出含"闸门数据缺失"，junit 里 failures=25、skipped=0。
    - 不设：skipped=25，返回码 0。
  - `--check`：
    - 用合成小目录，登记一组假指纹（指纹常量可以注入）：
      - 全部吻合时退出 0。
      - 缺一个文件、改一个字节，都退出 1，并且输出里有期望值和实际值。
      - 在 olist/、retail/ 或顶层多放一个文件，都退出 1，并且输出里点名那个多余的文件。
    - `--check` 不写文件（目录 mtime 和内容前后一致），不调用 fetch（打桩成抛异常）。
  - junit 断言脚本：expect/0/0/0 时退出 0；skipped=expect、tests=expect-1、failures=1 时都退出 1，并且输出里有 expect 和实际值。期望值来自 `len(QUESTIONS)`，当前是 25。
- CI 实测（本 PR 触发）：
  - gate-oracle 两个 OS 都是 25/0/0/0，ubuntu 上 answers.json 无 diff。
  - **每个 OS：两次 run 或三次 run（第二、三轮 五/三）**。`PRODUCT_SHA12` 先按本机登记，而 save 的条件是"未命中、build 成功、--check 成功"，--check 失败时后面的步骤默认跳过。所以分两种情况：
    | 情况 | run 1 | run 2 | run 3 |
    |---|---|---|---|
    | 本机登记的值和 runner 字节一致 | 未命中，绿，存缓存 | **命中**，绿 | — |
    | 不一致 | 未命中，`--check` 红，不存缓存。**这次红是采样，不算失败** | 按 run 1 的输出重登，或拆成按 OS 两份（会改 fingerprints.py，key 跟着变），然后未命中，绿，存缓存 | **命中**，绿 |
    - 每一跑都记 run id 和耗时。把两个 OS 上 `--check` 打印的产物实际哈希原样记进 DEVLOG 比对。
    - 最后一跑必须 `cache-hit == 'true'`，并且"命中时必须跳过 build"这一步是绿的。
    - Windows 命中路径要专门验：`零售明细.csv` 这类非 ASCII 文件名经过一次 tar/zstd 往返后仍能被 `--check` 找到并对上指纹。如果解出来是乱码目录名，这里会红成"缺文件"加"多余文件"，一眼就能认出来。
    - 命中那一跑可以是 PR 上的 re-run，也可以是合并后 master 上的预热 run，两种都记。
- 反向演示（只在 PR 分支上做，不合入）：
  - 临时改坏一个 oracle，确认 gate-oracle 变红，记下 run id 后 revert。
  - 临时改一个 `PRODUCT_SHA12`，确认 `--check` 变红，记下 run id 后 revert。
- 合并后：在 master 上用 workflow_dispatch 预热，第一次未命中并写入缓存，再 dispatch 一次确认命中，run id 都记下。PR 上已经把指纹定好了，正常是两次；如果 master 的第一次也红了（采样），就按上表走到第三次。
- answers.json：本 PR 的 diff 只能是 `verify_script_sha256` 一行，PR 描述贴出这一行，ubuntu 上的冻结检查要绿。
- `check_junit.py` 用 `python scripts/gate/check_junit.py` 实际跑一次，exit 0（证明裸 import 可用）。
- HANDOVER §3 改为"主矩阵 skip、gate-oracle 必跑"。

**不做**：闸门真模型评测上 CI（要 Key，由 S 跑）；把数据放进 Release 或 LFS；用 3.11 跑 oracle；补 data_sha256（另立）。

估时：大半天，大头是 CI 实测（冷、热各一次）和两次反向演示。
