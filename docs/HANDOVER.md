# 移交文档（给接手的 agent）

第二版，写于 2026-10-23，接 master `39c4741`（PR #70，F4 迭代 V2a 实现）之后，和「四屏视觉回归」（DEVLOG [59]）同一个 PR 合并。
第一版写于 2026-10-16（PR #37，`7ece7a2`），那一版里的进度已经过时，这一版整份替换它。
读完这一份，再按 §2 的顺序读文档，就能接着干。本文只写"不读代码、不翻历史就不知道"的东西；细节以仓库里的文档和代码为准，冲突时以代码为准，并顺手修正本文。

---

## 1. 这个项目是什么，做到哪了

**datachat**：用自然语言问 CSV，模型生成 pandas 代码，在子进程沙箱里执行，给出结论和图表。
2026-10-09 起目标从"作品"改为**产品**：先做桌面客户端（用户自带 API Key），以后再做 Web 服务端。

技术栈：
- `app/core`：分析核心（`analyze` / `analyze_stream`，两种 agent：工作流 `app/graph.py` + `app/nodes/*`，ReAct `app/react_agent.py`）。错误文案唯一出口 `app/core/errors.py` 的 `user_error`（T11）。
- `app/tools`：沙箱（`sandbox.py` + `sandbox_worker.py`，子进程 + 文件访问守卫）、图表（`charts.py`：ECharts option 生成、`_display_safe` 规范化、`BANNED_KEYS` 校验）。
- `app/server`：FastAPI 本地后端（sidecar），SQLite（写法兼容 PG），SSE 推事件，Bearer token，托管前端 dist 并带 CSP。启动契约见 `docs/sidecar-contract.md`（壳必须 `--port 0`）。
- `ui/web`：React 19 + TS 前端（Vite、vitest、Playwright），图表用 ECharts（按需引入）。**前端只通过 HTTP/SSE 和后端通信，不用 Tauri IPC**（S 定，2026-10-12）。
- 外壳：Tauri 2 + PyInstaller 打包的 sidecar，在 GitHub Actions 的 Windows runner 上构建（`packaging/`、`.github/workflows/sidecar.yml`）。
- Streamlit 旧界面已在 F5 验收后删除（DEVLOG [67]）。

进度：阶段 0–4 完成；**阶段 5（前端）收尾中**，方案是 `docs/roadmap/phase5-frontend.md`。
- F0–F2（#32–#35）、F3 ECharts 六步（#41–#53）、F4 层 1 面板（#57）、F4 迭代 V1（#67）、F4 迭代 V2a（#70，按 S 的设计稿整体重做界面）都已合并。
- 和 F 路径并行的：chart_errors 按执行记账（result.py:117，#55，已完成）、#49 矮画布紧凑几何（#58）、#44 sidecar 契约（#59）、T11 错误文案脱敏（#61）、A1 错题自动复跑（#63）、G1 闸门 oracle 上 CI（#65）、`llm_kind`（含在 #70 里）。
- F5：S 用真 Key 走完五条路径并通过（2026-10-26，走查记录在 DEVLOG [55]）；Streamlit 已删（DEVLOG [67]）。阶段 5 完成，下一步阶段 6。
- 最近一步：四屏视觉回归（`ui/web/e2e/f4-visual.spec.ts`，DEVLOG [59]）。

基线数字（39c4741 + [59]，Linux 沙箱）：pytest 837 passed（含闸门 25 条，需先下数据）、vitest 790、e2e 38、lint / tsc / build / `gen_ui_types --check` 全过。

## 2. 先读什么（按顺序）

1. `docs/roadmap/plan.md`：总计划、阶段表、已定 / 待定选择。
2. `docs/roadmap/phase5-frontend.md`：当前阶段的方案。每一步都有"已定"规则和验收；最近的是「F4 迭代 V2a」（0–10 节 + 「S 10-22 已定」）和「F5：S 验收走查」。
3. `docs/DEVLOG.md`：每一步做了什么、为什么、偏离了什么、没做什么。从 [36] 往后读能接上前端全程；时间紧就读 [53]–[59]。**[58] 很长，是 V2a 四轮验收的全部记录，改界面前必读**。
4. `docs/THREAT_MODEL.md`：安全边界（T9 用户数据一律按文本渲染、T10 CSP、T11 错误文案脱敏）。
5. 其余：`docs/roadmap/M13-图表方案.md`（option 产出规则，开关产出哪些键以 §12 为准）、`docs/gate/`（闸门阈值和 oracle）、`docs/eval/`、`docs/sidecar-contract.md`。

**不在仓库里、要向 S 要的东西**：V2a 的设计稿和交接包（S 定"不入库"，以其中 `07-落地范围.md` 为准；第一版交接包已作废），以及 S 每轮验收写的判定文件（`v2a-验收清单.md`、`-r2核对`、`-r3判定`、`-r4判定`、`v2a-pr70-评审.md`）。结论都已经写进 phase5 和 DEVLOG [58]，只在要对照原文时才需要。

## 3. 和 S 协作（最重要）

S 是仓库主人（GitHub `Smilewithoutfalling`），全程用中文，称呼 S。硬规则：

- **commit、push、开 PR、合并之前都先汇报，等 S 明确同意。** 一律 squash 合并，标题带 `(#N)`，合并后删分支。
- **方案先行**：新的一步先在 phase5 写"已定"规则和验收，S 评审通过再写代码；方案单独开 PR。（小修可以规则和实现同 PR，但要 S 同意，比如 #49。）
- **节奏**（S 10-20）：不要每改一小段就停下来提交或问；一个功能本地测过就接着做下一个，攒成一批再汇报。
- **不要假绿**：说"有覆盖"必须给出测试名；写了但没执行过的分支、默认分支吞掉错误、测的东西和产品无关，都算缺陷。**最后一次改动之后，所有闸门重跑一遍**再汇报。
- **判定表纪律**：改任何断言的期望值，都要写明"这个位置的行为为什么变了"；只是选择器变了的单独列出。探针要走完整产品路径。
- **偏离要带代码证据**（文件:行号、实测数字）。S 接受有证据的偏离，不接受凭感觉的。
- **装东西前先问装在哪**：S 本机是 Windows，磁盘很紧；超过约 1 GB 的东西放 CI。S 本人不在本地跑浏览器测试。真模型评测由 S 用自己的 Key 跑。
- **S 只能看到推上去的东西**（和你发给他的文件）。给 S 的压缩包文件名一律用英文（他的 Windows 会把中文名解成乱码），里面附一个带 BOM 的中文索引 txt。
- **汇报格式**：一句话结论 → 改了什么 → 偏离和理由（带代码证据）→ 实测数字（表格）→ 未做 → 待提交文件 → 问能否提交。

S 的评审风格：逐条评审，会对照代码和截图核实，按 P0（挡验收）/ P1 / P2 / P3 分级。他会强硬反驳；对的地方**精确地认**（认的是哪一条、为什么），他说错了（事实过时、截图状态不对）就**拿证据纠正**，不要含糊附和。例：r3 他量到失败卡偏 25px，实际是侧栏抽屉展开时的截图；r4 他认了 08 骨架色差是单点采样到 shimmer 不同相位。他定下的规则："跨元素比颜色要固定同一坐标；能读源码就不要猜像素"。

## 4. 已定的设计不变量（改之前先问 S）

- **status 是唯一真相**：消息的 `status` ∈ `MESSAGE_STATUSES`（`app/server/db.py`）。前端展示、重放都按 status / error_kind / llm_kind 分支，**不按文案匹配**（`turn.ts` 顶部注释）。
  - `cancelled` 只用于用户点了停止；后端重启扫尾、SSE 客户端断开 → `interrupted`；流异常结束且没有 done → `error` + `STREAM_ABORTED_MESSAGE`。只有 `except GeneratorExit`（真实断开）才落 interrupted。
  - 晚到的取消算取消：answer 可能已经推出，但 status=cancelled → 前端显示"已取消（未保存）"。
- **error_kind 只有一个写入方**（`app/core/service.py`），有 AST 测试守着；status 有多个写入方，另有 AST 测试扫描所有写 status 的字面量（`tests/test_web_f2.py`）。
- **llm_kind**（[57]）：error 事件和 done.result 都带。`Emitter.error(kind="llm")` **必须**传 `llm_kind`，非 llm 不许传，否则抛 `ValueError`。取值是 `events.LLM_KINDS`（classify_error 的 8 个值 + `no_key`）或 `http_NNN`。前端错误卡按它给出口（表在 phase5 V2a「S 10-22 已定」第 1 条）。
- **前后端共享常量靠生成**：`scripts/gen_ui_types.py` → `ui/web/src/generated/{events,banned_keys}.json`。改了后端常量要重新生成；CI 跑 `--check`。`generated/` 不要手改。
- **停止流程**：前端先 `await POST /messages/{id}/cancel`（CAS），**不主动断开流**，等流里的 error + done 自然结束。停止耗时分感知延迟（验收指标，< 500 ms）和后端延迟（只记录）。
- **图表**：option 在后端已经过规范化和 `BANNED_KEYS` 校验，前端经 `prepare()` 管线（深拷贝 → 层 1 改动 → 开关 → 递归清理 → 强制 `tooltip.renderMode='richText'`）交给 ECharts：不 eval、不执行 formatter 字符串。CSP 禁止外部图片，e2e 断言零外部请求。tooltip 会解析用户字符串里的 `}`（F3 第二步实测），所以规范化在后端做。
- **chart_fixtures 和导出 PNG 的字节是契约**：改了就是判定变更，要方案先行。V2a 全程没动它们（P2-19~22 因此放到 V2b）。
- **数值标签**（P2-18）：`StoredSwitches.label?: boolean`，undefined = 用户没碰过 → 设计默认（柱 / 线 / 面积开，饼 / 散点关；类目 > 30 降为关，可手动开）；"重置" = 清掉存储回到设计默认。
- **用户数据一律按文本渲染**（T9）。Markdown 用 react-markdown 10.1.0 + remark-gfm 4.0.1（锁精确版本），不开 raw HTML；只有 http(s) / mailto 渲染成链接，其余是 `span.md-link-blocked`。
- **假模型服务**（`tests/fake_llm.py`）：独立进程、OpenAI 兼容、**无状态**，产品代码只改 base_url。model 名决定场景（`ok`、`slow-Ns`、`hang-Ns`、`fail-CODE`、`chart-bar` 等，加 `@step`）。**认不出的一律 HTTP 400**，不要加"认不出就走默认"的分支。改了提示词，`tests/test_fake_llm.py` 会先红，同步 `MARK_*`。
- **V2a 视觉口径**（S 定）：只改 `styles.css` 原有 9 个变量的值，最多再补 6 个（已补满）；图标是 `views/icons.tsx` 的内联 SVG（超过 30 个再议 lucide）；字重只用 400 / 700；卡片不加阴影；暗色只作用于画布，不做整页暗色。
- **DEVLOG**：每步一条；新条目的 commit 写 `<待提交>`，**下一次提交时回填上一条的 squash SHA**；引用 CI 写 run id，不引用分支上的中间 commit（squash 后失效）。

## 5. 下一步做什么

1. **DEVLOG 回填**：[57][58] 回填 `39c4741`（[59] 所在 PR 已经做了的话就跳过）；[59] 在它合并后的下一个 PR 回填。
2. **视觉回归的基线要以 CI 为准**（见 §6「视觉回归」）。[59] 首次上 CI 时如果 f4-visual 红，按那里的步骤换基线。
3. 候选（S 定先后，[59] 时 S 还没定）：
   - **V2b**（先写方案）：P2-19 y 轴上限（`'dataMax'` 不能用，会顶到上沿；S 建议 `Math.ceil(max*1.08/50)*50`，必须和柱顶数值一起看）；P2-20 x 轴名和刻度太近（nameGap / grid.bottom）；P2-21 窄屏 grid.left 没缩（25 屏 y 轴区 90px，应约 44）；P2-22 图被压缩后右侧空 60px（ResizeObserver 后重算 grid）。这四条都改 chart_fixtures 和导出字节，属于判定变更。另有 phase5 V2a §8 列的 V2b 范围：标记卡视觉对齐、按列着色、标题输入、应用到同类、「完成」按钮。
   - 设置页「测试连接」：要后端新接口。
   - P1-17：图表警告文案（"x 列 '…' 不存在"暴露变量名）在后端 `chart_warnings`，前端改写就是匹配后端文案，要改就改后端。
   - P1-16：失效页"重新打开应用"浏览器里做不到，放阶段 6。
4. **F5**：已通过（2026-10-26），Streamlit 已删，pytest 基线 872 → 869（DEVLOG [67]）。
5. **阶段 6** Tauri 打包。代码签名证书要由有实名主体、能付款的一方办（S 没有），选型（大概率 OV 起步）在 phase5「F5」末尾的阶段 6 前置事项里。

## 6. 环境搭建与运行

S 的环境：Windows + PowerShell，Python 3.11（conda env `dc`），仓库在 `D:\Coding\claude\datachat`，Node v24（`D:\Coding\nodejs`），访问 github.com 常要代理。给 S 的命令要写 PowerShell 版本。CI 用 Node 24、Python 3.11 / 3.12。

后端（Linux 写法）：
```bash
python -m venv venv && . venv/bin/activate
pip install -r requirements-dev.txt
python scripts/gate/build_gate_data.py       # 闸门数据，约 90 MB，不入库；没下载则 test_gate 有 25 条 skip
python scripts/gen_eval_data.py --check
python scripts/gen_ui_types.py --check
python -m pytest -q                          # 约 8 分钟，837 passed；放后台跑
```
前端（`ui/web`）：
```bash
npm ci
npx playwright install chromium
npx playwright install-deps chromium         # 新 Linux / 沙箱必须，否则 libatk-1.0.so.0 缺失，e2e 全部 1ms 红
npm run lint && npx tsc --noEmit && npx vitest run && npm run build   # build 会检查 dist 里没有内联脚本
PATH=<venv>/bin:$PATH E2E_PORT=9900 npx playwright test              # 38 条；用端口 P、P+1、P+2
rm -rf test-results
```
- 跑任何 localhost 测试前先 `unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy`，否则 fake_llm 报 not found。
- Node 要 24（Node 22 不行）。
- e2e 前必须先 `npm run build`：后端托管的是 dist，不 build 测的是旧界面。
- 不在本机 build、改用 CI 的 `web-dist` 工件时：用普通权限（不要管理员）把压缩包里的内容直接解到 `ui\web\dist`，不要多套一层目录（`ui\web\web\web-dist` 这种未跟踪目录会让本机 eslint 报几千个错）。管理员解压出的 dist 普通进程删不掉，之后 `npm run build` 会 EPERM（V2c 记录）。

Playwright 结构（`playwright.config.ts`）：
- `nokey` project 匹配 `/f[012]\.spec\.ts/`（**不锚定**，`zz-f2.spec.ts` 这种名字也会被选中）；`fake` project 匹配 `/f[34].*\.spec\.ts/`，后端 base_url 指向假服务，每个测试用 `PUT /settings {model}` 选场景。
- `workers: 1`（model 是后端全局设置）；同一个 project 的所有文件共用一个后端，数据集、会话会累积。
- 临时脚本命名成 `f3-zz*.spec.ts` 放进 e2e/ 跑，**跑完删掉**（lint 会扫 e2e/）。

### 视觉回归（f4-visual，DEVLOG [59]）
- 四屏：08 分析中、11 标记浮层、24 窄屏失败页、25 窄屏会话。基线在 `e2e/f4-visual.spec.ts-snapshots/*-fake-linux.png`。
- 阈值 `threshold: 0.02, maxDiffPixels: 20`（偏离 S 提的 `maxDiffPixelRatio: 0.002`，变异实测见 [59] 和文件头注释）。
- **改了界面、预期就该变**：`npx playwright test e2e/f4-visual.spec.ts --update-snapshots`，提交时在 DEVLOG 写明哪屏为什么变（判定表纪律同样适用）。
- **基线以 CI 为准**：CI 是 ubuntu x64，沙箱可能是 arm64，字体抗锯齿可能不同。CI 红时：到失败 run 的 `playwright-results` 工件里取 `*-actual.png`，先看 `*-diff.png` 确认只是抗锯齿差异，再改名覆盖 `*-fake-linux.png` 提交。要是 diff 里有真的布局变化，那就是回归，修代码。
- 现有四张基线取自 CI（PR #71，run 39889413891）。在 arm64 沙箱本地跑，f4-visual 会因抗锯齿红 4 条，这是预期的：本地闸门可以加 `--grep-invert 视觉`，视觉结果以 CI 为准。改了界面要更新基线时，先推上去让 CI 出 actual 图，再按上一条换。
- 动态内容的处理：宽屏侧栏整块 mask（列表长度随别的用例变）；用时、副标题 mask；宽度随内容变的行内文字（trace 编号、同名数据集的「 · HH:MM」）截图前用 `freeze()` 换成定值，因为 mask 框会跟着变宽，框边本身就是像素差。

## 7. 提交 / PR / CI

- 本地 clone 起点：`git fetch && git reset --hard origin/master`。新文件先 `git add -A`。
- git 身份：`Smilewithoutfalling <91455578+Smilewithoutfalling@users.noreply.github.com>`。
- 分支 → PR → CI 里**被触发的** workflow 全绿 → S 同意 → squash 合并 → 删分支。
  - `tests`：pytest（ubuntu / windows × 3.11 / 3.12）+ gen 检查；`web` job（lint / vitest / build / Playwright）；`gate-oracle`（ubuntu / windows，闸门 25 条必跑，数据走 Actions cache，缺数据报红不降级）。
  - `sidecar`：Windows 打包冒烟，有 paths 过滤，只改前端或文档的 PR 不触发，这是正常的。
- 查 CI：`GET /repos/Smilewithoutfalling/datachat/actions/runs?branch=<br>`；job 日志可以匿名 `curl https://api.github.com/repos/Smilewithoutfalling/datachat/actions/jobs/<id>/logs`。
- PR 描述里有破坏性改动要单列一节（例：#70 写了 `Emitter.error(kind="llm")` 必须传 `llm_kind`）。

## 8. 踩过的坑

- **冷启动**：后端第一次分析要 import pandas / matplotlib / langchain 并建字体缓存，沙箱里 20 秒以上。会触发分析的 e2e 文件都要 `beforeAll` 预热（照 `f4-panel.spec.ts`），单独跑一个文件时尤其明显。
- **同名数据集**：同名上传时名字后面会追加「 · HH:MM」。`--repeat-each` 或多个用例共用一个后端时，按名字点的定位器会撞 strict mode，文件名带时间戳（照 `f4-layout.spec.ts`）。
- **`view-root` 是 `display: contents`**：`session-view` / `dataset-view` 的 testid 在它上面，不能对它做元素截图（"not visible"），也没有几何。
- **骨架 shimmer**：颜色是渐变动画，单点采样会采到不同相位。比颜色固定同一坐标，或读 CSS。
- **列表竞态**：Shell 的 6 个本地列表入口用 `listGen` 丢弃过时的 reload 结果（#70 修过一次真 bug：首屏 reload 晚于上传返回，把新数据集冲掉）。改 Shell 时保持这个模式。
- **`pkill -f <模式>` 会匹配到执行它的 shell 自己**。用 `pgrep -af ... | awk '{print $1}' | xargs kill`；模式里不要带 playwright 字样。
- Playwright 每次占 3 个端口；连跑两次要换 E2E_PORT，上次没退干净会 `Address already in use`（后端按契约不开 SO_REUSEADDR）。
- Playwright 里 import JSON 要写 `with { type: "json" }`。
- 上传对话框的名称输入框只有 placeholder，用 `getByPlaceholder("数据集名称（可选）")`。
- Windows CI：测试夹具写 CSV 要 `newline=""`，否则单元格里的 `\n` 被写成 `\r\n`（#46 红过一次）。
- `ui/web/tsconfig.tsbuildinfo` 是 tsc 的副产物，不要提交。

## 9. 关于"记忆"

我（上一任 agent，运行在 Hark 上）在仓库外还有工作笔记，你看不到。要点都已抄进本文 §3–§8；历史决定以 DEVLOG 和 phase5 为准。另外：
- S 的时区 Asia/Shanghai。
- **保持最新一条 DEVLOG 写明当前阶段和下一步**，这个习惯对任何接手者都有用。

---

## 10. 代码地图（细节）

### 10.1 后端 HTTP 接口（`app/server/app.py`）
除 `/health`、`/`、`/assets/*` 以外，全部要 `Authorization: Bearer <token>`。token 只经 URL fragment（`#token=`）交给前端，不进访问日志。

| 接口 | 作用 |
|---|---|
| `GET /health` | 存活检查 |
| `POST /datasets` | 上传（multipart `files`，可多表，可带 `.dict.csv` 数据字典）；拒绝只有 400 / 413；读取失败的数据集照样建，带 `error` |
| `GET /datasets`、`GET /datasets/{id}?rows=20`、`DELETE /datasets/{id}` | 列表（不带 error）；详情加预览；删除是硬删，级联删除会话 |
| `POST /sessions`、`GET /sessions`、`GET/PATCH/DELETE /sessions/{id}` | 会话 CRUD；PATCH 只改 title，不更新 `updated_at` |
| `POST /sessions/{id}/messages` | 提问，返回 SSE 流，响应头 `X-Message-Id`；同一会话已有分析在跑时 409 |
| `POST /messages/{id}/cancel` | 停止（CAS；已结束 409；对用户消息 400） |
| `PUT /messages/{id}/feedback` | 👍👎 加备注 |
| `GET /charts/{name}` | 图表文件（也要 token） |
| `GET/PUT /settings` | model、base_url、timeout；空串表示清除 |
| `GET/PUT/DELETE /settings/api-key` | Key 存在系统钥匙串，GET 只返回 `{configured, source}` |

SSE 事件类型以 `app/core/events.py` 为准：plan、code、exec、error（fatal 或可恢复，带 llm_kind）、answer、done（携带 result）。每个事件带 seq、trace_id、ts。

### 10.2 前端（`ui/web/src`）
- `api.ts`：fetch 封装、ApiError、XHR 上传（带进度；测试注入 fetch 时退回 fetch）。`client.ts`：所有 API 调用。`token.ts`：从 fragment 取 token。`sse.ts`：自写 SSE 解析器。
- `turn.ts`：唯一的 reducer。`replay()` / `settle()` / `outcome()`；V2a 加了 `steps()`（步骤条分段）、`partialSignals()`（黄条：warnings、unverified_numbers、字典读取失败）、`totalSeconds()`。
- `views/`：`Shell`（侧栏、窄屏图标条、上传对话框、拖放、`listGen`）、`DatasetView`（详情、失败卡）、`SessionView`（输入区、贴底滚动、停止）、`TurnView`（助手卡：状态标签、步骤条、错误卡、部分完成黄条）、`SettingsView`、`ui.tsx`（Topbar、Dialog、MoreMenu、relTime）、`icons.tsx`、`Markdown`、`FeedbackBar`、`ThemePicker`、`PreviewTable`。
- `charts/`：`EChart.tsx`（卡片、工具栏）、`MarksCard.tsx`（标记浮层，5 组）、`prepare.ts`、`switches.ts`、`layer1.ts`、`themes.ts`（四套 + Tableau 风）、`compact.ts`（#49）、`exportPng.ts`、`filename.ts`、`uiPrefs.ts`（localStorage，键 `datachat.chartEdit:<message_id>:<序号>`）、`register.ts`（按需注册组件）。
- `fakeBackend.ts`：vitest 用的内存假后端，和 `tests/fake_llm.py` 不是一回事。
- `styles.css`：一个文件。后半段是 V2a 各轮验收的覆盖规则，带"验收 rN"注释，改之前搜一下同一选择器有没有后面的覆盖。

### 10.3 测试地图
- 后端 web：`test_web.py`、`test_web_f1.py`、`test_web_f2.py`、`test_server.py`、`test_stream.py`、`test_llm_kind.py`、`test_sidecar_contract.py`。
- 核心：`test_core_analyze.py`、`test_workflow_mocked.py`、`test_react_loop.py`、`test_llm.py`、`test_sandbox.py`、`test_csv_io.py`、`test_multitable.py`、`test_dictionary.py`、`test_t11_errors.py`（T11）。
- 图表：`test_charts.py`、`test_chart_slot.py`、`test_chart_coverage.py`、`test_chart_fixtures.py`；`ui/web/src/generated/chart_fixtures.json`（gen_ui_types 生成）是契约。
- 评测和闸门：`test_comparator*.py`、`test_eval_cases.py`、`test_gate.py`、`test_phase36.py`。
- 假模型服务：`test_fake_llm.py`。进程内的 `ScriptedChatModel`（`app/core/testing.py`）给单测和 `run_eval.py --oracle` 用。
- 前端 vitest：`*.test.ts(x)`，V2a 的集中在 `views/v2a.test.tsx`。
- e2e：f0–f2（nokey）；f3-charts / errors / export / inject / stop / switches / themes；f4-panel（标记卡）、f4-layout（输入区几何、遮罩、菜单）、f4-visual（四屏像素）。

## 11. 路线图全貌
- 阶段 6 桌面打包：Tauri 2 外壳 + PyInstaller sidecar、Windows 安装包、自动更新、首次启动引导填 Key、依赖许可证审计；代码签名证书审核要几天到几周，要提前办。验收是"在干净的 Windows 上一键安装"，必须 S 在本机看。
- 阶段 7 准确率：DuckDB 统一 CSV / Excel / SQL、YAML 语义模型、枚举值召回、结果合理性校验、反馈沉淀为已验证问答对。需要新的留出评测集，闸门的 25 题只作回归用。
- 阶段 8 Web 上线：另定。
- 工期不能按阶段 0–4 的速度外推：阶段 5–6 的验收要 S 本人动手，日历时间取决于他。

## 12. 评测与闸门
- 评测集在 `docs/eval/`，`run_eval.py` 跑；`--rescore` 不调模型，按当前比较器重新打分；`--oracle` 不需要 Key。
- 阶段 3.5 外部验证闸门：25 题（UCI Online Retail 改造的中文 GBK 脏表 15 题，Olist 8 张表 10 题），标准答案由独立脚本在原始数据上算出。工具在 `scripts/gate/`，门槛在 `docs/gate/thresholds.json`（有哈希）。
- A1：错题自动复跑（m13r、`--rerun`、退出码 0/1/2/3、`--only` + `--reason` 留痕），细则在 phase5「A1」。
- 流程：S 用真实 Key 跑，把报告推上来 → agent 离线重新打分、对照门槛判定 → 写进 DEVLOG。

## 13. 这一段开发的经验
- **方案先行**，评审结论并进方案。S 的评审原文早期在 `docs/roadmap/review-*.md`，后来都是他直接发的文件。
- **每种终止原因单独一个 status**，文案都是常量并导出给前端，终止原因不靠匹配文案判断（F2 停止语义改了三轮的教训）。
- **每加一个分支就问"这条路径被执行过吗"**。新测试最好做一次"回退红"：把修复撤掉，确认测试真的会红（#70 的列表竞态、[59] 的变异实测都这么做）。
- **行为断言抓不到视觉回归**：V2a 验收里"改一处塌一处"出了三次（遮罩改完删除按钮变粉、居中改完失败卡宽度塌 49%、底注色只改了一半），当时的 e2e 全绿。所以有了 f4-visual。
- **测试隔离**：fake project 共用一个后端，任何依赖"列表里只有我"的断言都会在全量或 repeat 下挂。`--repeat-each=5` 是好的自检。
- 截图给 S 看：脚本放 `e2e/f3-zz-shots.spec.ts` 临时跑，输出到仓库外，打包发英文文件名的 zip。截图不入库。
