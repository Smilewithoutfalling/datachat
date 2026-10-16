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
| Playwright（单个 Linux job） | **跑在后端托管的 dist 上（带 CSP）**：用 `chat_model_factory` 起假模型服务，产出带注入串的图，真机悬停 tooltip，断言不产生 DOM 节点 | — |

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

## 7. 与前端并行，不在 F 路径上
- 错误文案脱敏（THREAT_MODEL T10）：单独一个 PR，F2 之后做；先定规则再改阶段 3/4 的代码。
- A1 自动复跑规则：单独一个闸门 PR，赶在下一次跑闸门之前做（比如验证 B70 时）。
- [30] 的 SHA（4497d2b）随 F0 一起回填（已做，见 DEVLOG [31]）。
