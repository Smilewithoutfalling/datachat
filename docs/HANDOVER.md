# 移交文档（给接手的 agent）

写于 2026-10-16，紧接 master `7aed8e8`（PR #36）之后，随移交文档 PR 一起合并。读完这一份，再按 §2 的顺序读四份文档，就能接着干。
本文只写"不读代码 / 不翻历史就不知道"的东西；细节以仓库里的文档和代码为准，冲突时以代码为准并修正本文。

---

## 1. 这个项目是什么，做到哪了

**datachat**：用自然语言问 CSV，模型生成 pandas 代码，在子进程沙箱里执行，给出结论和图表。
2026-10-09 起目标从"作品"改为**产品**：先做桌面客户端（用户自带 API Key），以后再做 Web 服务端。

技术栈：
- `app/core`：分析核心（`analyze` / `analyze_stream`，两种 agent：工作流 `app/graph.py` + `app/nodes/*`，ReAct `app/react_agent.py`）。
- `app/tools`：沙箱（`sandbox.py` + `sandbox_worker.py`，子进程 + 文件访问守卫）、图表（`charts.py`：ECharts option 生成与 `BANNED_KEYS` 校验）。
- `app/server`：FastAPI 本地后端（sidecar），SQLite（写法兼容 PG），SSE 推事件，Bearer token，托管前端 dist 并带 CSP。
- `ui/web`：React + TS 前端（Vite、vitest、Playwright）。**前端只通过 HTTP/SSE 和后端通信，不用 Tauri IPC**（S 定的规则，2026-10-12）。
- 外壳：Tauri 2 + PyInstaller 打包的 sidecar，在 GitHub Actions 的 Windows runner 上构建（`packaging/`、`.github/workflows/sidecar.yml`）。
- Streamlit 旧界面（`ui/streamlit_app.py`、`ui/chat_app.py`）还在，F5 验收后删除。

进度：阶段 0–4 完成；**阶段 5（前端）进行中**，方案是 `docs/roadmap/phase5-frontend.md`（v2.1，F0–F5）。
- F0 托管 / auth / CSP（PR #32）、F1 数据集 / 会话 / 设置（#33、#34）、F2 SSE / 事件渲染 / 停止 / 👍👎（#35）已合并。
- **F3 进行中**：第一步（假模型服务 + 停止的端到端）已合并（#36，DEVLOG [35]）。**下一步是 ECharts 渲染**。

## 2. 先读什么（按顺序）

1. `docs/roadmap/plan.md`：总计划、阶段表、已定 / 待定选择。
2. `docs/roadmap/phase5-frontend.md`：当前阶段的方案。§1 有"停止的已定规则"，§3 是图表，§6 有 "F3 已定"。
3. `docs/DEVLOG.md`：每一步做了什么、为什么、没做什么。从 [31] 往后读就够接上前端。
4. `docs/THREAT_MODEL.md`：安全边界（T9 用户数据一律按文本渲染、T10 CSP、T11 错误文案脱敏）。
5. 其余：`docs/roadmap/M13-图表方案.md`（图表 option 的产出规则，开关产出哪些键以它的 §12 为准）、`docs/gate/`（评测闸门阈值）、`docs/eval/`。

## 3. 和 S 协作（最重要）

S 是仓库主人（GitHub `Smilewithoutfalling`），用中文交流。下面这些是硬规则：

- **每次 commit / push 之前先告诉 S、等他同意。** 合并 PR 也要他点头（"可以合并"）。
- **装任何东西到 S 的机器上之前，先问装在哪个目录。** S 本机（Windows）磁盘非常紧：超过约 1 GB 的东西放远端（Actions / Codespaces），不要让他本地装。
- **S 本人不在本地跑浏览器测试**；Playwright 只在 CI 和 agent 的沙箱里跑。

工作方式：
- S 会逐条评审，而且会对照代码核实。他看重**事先登记的标准**（先写验收条件，再做）和**基线锚点**（数字要有对照）。
- 他会强硬地反驳。对的地方**精确地认**（说清楚认的是哪一条、为什么）；他说错了（比如事实已经过时）就**拿证据纠正**，不要含糊附和。2026-10-16 就有一例：他提议"认不出返回 500"、"stream-20tps"，我用代码证据改成 400 和 slow-Ns，他认了。
- 最在意"**假绿**"：写了但没被执行过的分支、默认分支吞掉错误、测试测的东西和产品无关，都算缺陷。新增任何测试设施，都要说明它的每个分支有没有被测到；没测到就在 DEVLOG 里明写"尚无覆盖"。
- 改代码的节奏：在本地 clone 里改 → 跑全套验证 → 给 S 一个总结（改了什么、偏离了他哪句原话以及理由、实测数字、还没做什么）→ 他同意 → 开 PR → CI 绿 → 他说合并再合并。
- 回复用中文，先给结论，数字要准。

## 4. 已定的设计不变量（改之前先问 S）

- **status 是唯一真相**：消息的 `status` ∈ `MESSAGE_STATUSES`（`app/server/db.py`）。前端展示、重放都按 status 分支，不按文案匹配。
  - `cancelled` 只用于用户点了停止；后端重启扫尾、SSE 客户端断开 → `interrupted`；流异常结束且没有 done → `error` + `STREAM_ABORTED_MESSAGE`（不带异常原文）。
  - 只有 `except GeneratorExit`（真实断开）才落 interrupted。
  - 晚到的取消算取消：answer 可能已经推出，但 status=cancelled → 前端显示"已取消（未保存）"，刷新后消失。cancelled 轮次里存下的 answer 事件只作审计。
- **error_kind 只有一个写入方**（`app/core/service.py`），有 AST 测试守着；**status 有多个写入方**，所以用另一种 AST 测试：扫描 `app/` 里所有写 status 的字面量，必须在 `MESSAGE_STATUSES` 里（`tests/test_web_f2.py`）。
- **前后端共享常量靠生成**：`scripts/gen_ui_types.py` → `ui/web/src/generated/{events,banned_keys}.json`（事件类型、error_kinds、message_statuses、各种文案、`BANNED_KEYS`）。改了后端常量要重新生成；CI 跑 `--check`。
- **停止流程**：前端先 `await POST /messages/{id}/cancel`（CAS：running→cancelled；已结束 409），**不主动断开流**，等流里的 error + done 自然结束。顺序反了会落成 interrupted。
- **停止耗时是两个指标**：感知延迟（点击 → "正在停止…"，验收指标，< 500 ms）；后端延迟（cancel 200 → cancelled，只记录，上界约等于当前那次模型调用的剩余时间，属于架构粒度，不是可优化项）。实测：1–2 ms / ~8050 ms（DEVLOG [35]）。
- **图表**：option 在后端已经过 `BANNED_KEYS` 校验，前端**原样**交给 ECharts：不 eval、不执行 formatter 字符串、不动态二次拼装。CSP `img-src 'self' data: blob:`，禁止外部图片。
- **用户数据一律按文本渲染**（T9）：预览单元格、错误、警告、结论、反馈备注。Markdown 用 react-markdown 10.1.0 + remark-gfm 4.0.1（锁精确版本），不开 raw HTML。
- **假模型服务**（`tests/fake_llm.py`）是 F3/F4/T11 所有异步测试的公共设施：独立进程，OpenAI 兼容，**无状态**，产品代码只改 base_url，不 monkeypatch。
  - model 名 `<ok|hang-Ns|fail-CODE|slow-Ns>[@plan|codegen|fix|answer|act|final]`。不写 @step 时作用于第一次调用。
  - **认不出的一律 HTTP 400**（不可重试，第一跳就失败）：未知或拼错的场景、跨链路的 @step、认不出当前步骤（提示词变了）、stream=true。不要加"认不出就走默认"的分支。
  - 按提示词里的 `MARK_*` 片段识别步骤。改了 `app/nodes/*` 或 `react_agent.py` 的提示词，`tests/test_fake_llm.py` 的真链路测试会先红，同步更新 `MARK_*` 即可。
  - 边界：ReAct 的 act/final 只看最后一条消息是不是 tool，多轮工具调用分不出第几轮。真要测时按 tool 消息的个数分，仍然无状态。
- **DEVLOG 引用 CI run id，不引用分支上的中间 commit**（squash 合并后中间 SHA 全部失效，而且不会报错）。每条 DEVLOG 写自己时 SHA 填 `<待提交>`，**下一次提交时回填上一条的 squash SHA**。

## 5. 下一步做什么

1. **下一次提交时，把 DEVLOG [36]（本文所在的提交）的 `<待提交>` 回填为它的 squash SHA**（在 master 的 git log 里找 "handover"），然后新开一条 [37]。
2. **F3 剩余**（方案 §3、§6 "F3 已定"）：
   - ECharts 原样渲染（按需引入组件）。先最小一步：渲染 + **覆盖后端可能产出的全部图表类型**（类型清单从后端导出，可以用 gen_ui_types；参考 `scripts/chart_coverage.py`），Playwright 断言**零外部请求**（不能只靠 CSP）。
   - `prepare(option, ui)` 纯函数：深拷贝 → 层 1 改动 → 开关 → 最后按 `BANNED_KEYS` 递归清理（renderMode 例外）→ 强制 `tooltip.renderMode='richText'`，并配递归单测。
   - 4 套自研主题；开关（数值标签、图例位置、堆叠、平滑、渐变、圆角、排序、平均线和极值、dataZoom；产出的键以 M13 §12 为准；不兼容的置灰）；换图型（同步 boundaryGap，换完重算开关兼容性）；导出（离屏实例 `getDataURL({pixelRatio:2})`，文件名清洗）。
   - 注入实测：用假服务产出带注入串的图，按方案 §4 的表分工（vitest + ECharts SSR SVG / testing-library / Playwright），并更新 THREAT_MODEL。
   - 增量渲染测试用 `slow-Ns`。图表场景可能要给假服务加一个产出 `chart()` 代码的剧本，加的时候也要遵守 fail loud。
3. F4 层 1 面板；F5 S 验收、删除 Streamlit。
4. 与 F 路径并行的两个**独立 PR**：
   - **T11 错误文案脱敏**：已做（DEVLOG [48]）。新增的错误文案一律经 `app/core/errors.py` 的 `user_error` 生成，不要再拼 `{type(e).__name__}: {e}`。
   - **A1 自动复跑 ×2 的闸门规则**：赶在下一次跑闸门之前做。方案在 phase5「A1 错题自动复跑」，DEVLOG [49]。
5. 已知未做（DEVLOG [34] 有记）：messages 表没有 error_kind 列，几种失败落库后都塌成 status=error；late-cancel 没有端到端测试，假服务造不出这个时序。

## 6. 环境搭建与运行

S 的环境：Windows + PowerShell，Python 3.11（conda env `dc`），仓库在 `D:\Coding\claude\datachat`，Node v24.14.0（`D:\Coding\nodejs`），访问 github.com 常要代理。CI 用 Node 24。

后端（Linux 沙箱写法；Windows 对应改一下）：
```bash
python -m venv venv && . venv/bin/activate
pip install -r requirements-dev.txt          # 包含 requirements.txt
python scripts/gen_eval_data.py --check
python scripts/gen_ui_types.py --check
python -m pytest -q                          # 约 8 分钟，654 passed（前提：已下载闸门数据，见下）；建议后台跑
python -m app.server --port 8765             # 第一行打印 {"port","token","home"}；API 要 Bearer token。桌面壳必须用 --port 0，见 docs/sidecar-contract.md
```
闸门数据（`data/gate/`，不入库）：先跑 `python scripts/gate/build_gate_data.py`。没下载的话，`tests/test_gate.py` 里会有 25 条跳过（629 passed, 25 skipped）。这 25 条是"闸门题在原始脏数据上能解出来"的 oracle 守卫，改内核时一定要在本地跑。CI 不生成这份数据，所以在 CI 上它们一直是跳过的。
前端（`ui/web`）：
```bash
npm ci
npx tsc --noEmit && npm run lint && npx vitest run && npm run build   # build 会检查 dist 里没有内联脚本
npx playwright install chromium && sudo npx playwright install-deps chromium   # 新机器一次
PATH=<venv>/bin:$PATH E2E_PORT=8840 npx playwright test              # 8 个；用端口 P、P+1、P+2
rm -rf test-results
```
Playwright 的结构（`playwright.config.ts`）：
- `nokey` project：f0–f2，没有 Key，用 `DEEPSEEK_API_KEY=""` + `PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring` 固定。
- `fake` project：f3*，后端 base_url 指向假服务，`DATACHAT_LLM_MAX_RETRIES=0`，每个测试用 `PUT /settings {model}` 选场景。
- `workers: 1`，因为 model 是后端的全局设置。

真模型：S 用自己的 Key（公司网关，Qwen3.5-397B-A17B）跑真实评测，报告由他自己推上来；agent 负责离线重新打分（`run_eval.py --rescore`）。`run_eval.py --oracle` 不需要 Key。

## 7. 提交 / PR / CI

- 分支 → PR → CI 里**被触发的** workflow 全绿（`tests`：pytest + gen 检查 + 前端 lint/test/build + Playwright；`sidecar`：Windows 打包冒烟，配了 paths 过滤，只改文档的 PR 不会触发它，这是正常的） → S 同意 → **squash 合并**，标题带 `(#N)` → 删除分支 → 本地 `git fetch && git reset --hard origin/master`。
- 查 CI：`GET /repos/Smilewithoutfalling/datachat/actions/runs?branch=<br>`。
- 我原来所在的沙箱 `git push` 会 403，所以用 GitHub Contents API 逐个文件 `PUT` 到新分支再开 PR（只能新增或修改，不能删文件）。你那边能正常 push 就直接 push。

## 8. 踩过的坑

- **冷启动**：后端进程第一次分析要 import pandas / matplotlib / langchain 并建字体缓存，沙箱里要 20 多秒。测耗时的 e2e 必须先预热（`f3-stop.spec.ts` 的 beforeAll）。CI 的新 runner 也是冷的。
- **代理**：沙箱里有 HTTP(S)_PROXY，连 localhost 的测试要 `env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY ...`。
- **`pkill -f <模式>` 会匹配到执行它的 shell 自己**，命令行里含同一字符串时会把自己杀掉。用 `pgrep -af ... | awk '{print $1}' | xargs kill`，单独一条命令执行。
- Playwright 每个配置占 3 个端口；连跑两次要隔开（8840、8850），上次没退干净的进程会导致 `Address already in use`。
- Playwright 里 import JSON 要写 `with { type: "json" }`。
- pytest 全量约 8 分钟，放后台跑，别在前台超时。
- S 本机的 Node / Python 路径和沙箱不一样；给 S 的命令要写 PowerShell 版本。

## 9. 关于"记忆"

我（上一任 agent）在仓库外还保存了这些东西，你可能看不到，这里把要点抄过来：
- S 的偏好就是 §3 那些。另外：S 叫 Smile，称呼 S；时区 Asia/Shanghai。
- 历史状态（阶段 0–4 的过程、各轮评审）已归档在 DEVLOG 和 `docs/roadmap/review-*.md`。
- 有一个 Home 面板每天从 `docs/DEVLOG.md` 生成任务清单（Hark 特有，换平台后不可用）。**保持最新一条 DEVLOG 写明"当前阶段"**，这个习惯对任何接手者都有用。
- 不相关的旁线：S 曾考虑给开源项目（OpenShell、crewAI）提 PR，已搁置，与本仓库无关。

---

## 10. 代码地图（细节）

### 10.1 后端 HTTP 接口（`app/server/app.py`）
除 `/health`、`/`、`/assets/*` 以外，全部要 `Authorization: Bearer <token>`。token 只经 URL fragment（`#token=`）交给前端，不进访问日志。`/charts/*` 也要 token，因为图里是用户数据。

| 接口 | 作用 |
|---|---|
| `GET /health` | 存活检查 |
| `POST /datasets` | 上传（multipart `files`，可多表，可带 `.dict.csv` 数据字典），返回值里带预览 |
| `GET /datasets`、`GET /datasets/{id}?rows=20`、`DELETE /datasets/{id}` | 列表；详情加预览（rows 1–100，越界 422；单元格是 str 或 null，长度超过 200 截断；去掉方向控制符；每张表的错误相互隔离）；删除 |
| `POST /sessions`、`GET /sessions`（按最近分析时间排序）、`GET/PATCH/DELETE /sessions/{id}` | 会话 CRUD；PATCH 只改 title，不会更新 `updated_at` |
| `POST /sessions/{id}/messages` | 提问，返回 SSE 流，响应头 `X-Message-Id`；同一会话已有分析在跑时返回 409 |
| `POST /messages/{id}/cancel` | 停止（CAS；已结束 409；对用户消息 400） |
| `PUT /messages/{id}/feedback` | 👍👎 加备注（feedback 单独建表，备注限长并清理控制字符） |
| `GET /charts/{name}` | 图表文件 |
| `GET/PUT /settings` | model、base_url、timeout（5–600）；空串表示清除，回到环境变量或默认值 |
| `GET/PUT/DELETE /settings/api-key` | Key 存在系统钥匙串，GET 只返回 `{configured, source}` |

SSE 事件类型以 `app/core/events.py` 为准：plan、code、exec、error（fatal 或可恢复）、answer、done。每个事件带 seq 和 trace_id，done 携带 result。

### 10.2 前端（`ui/web/src`）
- `client.ts`：所有 API 调用（ask / cancel / feedback 等）。`api.ts`：fetch 封装和 ApiError。`token.ts`：从 fragment 取 token，先 setItem（放在 try/catch 里），总是 replaceState 清掉地址栏，返回内存里的 token。
- `sse.ts`：自己写的 SSE 解析器（fetch + ReadableStream，能带 Authorization；处理 CRLF / LF / CR、注释、多行 data、BOM，未收尾的块丢弃）。
- `turn.ts`：唯一的 reducer（按 seq 去重，未知类型忽略）。`replay()` 重放时合成 done，`settle()` 按库里的 status 收尾，`outcome()` 决定终止原因怎么显示。
- `views/`：`Shell`（左栏数据集和会话）、`DatasetView` 和 `PreviewTable`、`SessionView`（提问、实时气泡、停止、重试）、`TurnView`（一轮回答）、`Markdown`、`FeedbackBar`、`SettingsView`、`ConfirmButton`（点两次才删除）。
- `fakeBackend.ts`：vitest 用的内存假后端，和 `tests/fake_llm.py` 不是一回事。
- `generated/`：由 gen_ui_types 生成，**不要手改**。

### 10.3 测试地图
- 后端 web：`test_web.py`（F0）、`test_web_f1.py`、`test_web_f2.py`（取消、CAS、断开、AST 约束、真实 TCP 断开）、`test_server.py`、`test_stream.py`。
- 核心：`test_core_analyze.py`、`test_workflow_mocked.py`、`test_react_loop.py`、`test_llm.py`（重试和错误分类）、`test_sandbox.py`、`test_csv_io.py`、`test_multitable.py`、`test_dictionary.py`。
- 图表：`test_charts.py`、`test_chart_slot.py`、`test_chart_coverage.py`。
- 评测和闸门：`test_comparator*.py`、`test_eval_cases.py`、`test_gate.py`、`test_phase36.py`。
- 假模型服务：`test_fake_llm.py`。进程内的脚本化假模型是 `app/core/testing.py` 的 `ScriptedChatModel`，单测和 `run_eval.py --oracle` 用它；e2e 用 HTTP 假服务。
- 前端：`*.test.ts(x)`（vitest），`e2e/*.spec.ts`（Playwright）。

## 11. 路线图全貌
- 阶段 6 桌面打包：Tauri 2 外壳 + PyInstaller sidecar、Windows 安装包、自动更新、首次启动引导填 Key、依赖许可证审计；代码签名证书审核要几天到几周，要提前办。验收是"在干净的 Windows 上一键安装"，必须 S 在本机看。
- 阶段 7 准确率：DuckDB 统一 CSV / Excel / SQL、YAML 语义模型、枚举值召回、结果合理性校验、反馈沉淀为已验证问答对。需要新的留出评测集，闸门的 25 题已经只作回归用。
- 阶段 8 Web 上线：另定。
- 工期：阶段 0–4 实际只用了 5 个日历日，但**不能照这个速度外推**。阶段 5–6 的验收要 S 本人动手，日历时间取决于他。详见 plan.md 的"进度与重估"。

## 12. 评测与闸门
- 评测集在 `docs/eval/`，`run_eval.py` 跑；`--rescore` 不调模型，按当前比较器重新打分。
- 阶段 3.5 外部验证闸门：25 题，都不是自造数据（单表 15 题，用 UCI Online Retail 改造成中文 GBK 脏表；多表 10 题，用 Olist 的 8 张表）。标准答案由独立脚本在原始数据上算出。工具在 `scripts/gate/`，门槛在 `docs/gate/thresholds.json`（有哈希，防止事后改门槛）。
- 流程：S 用真实 Key 跑，把报告推上来 → agent 离线重新打分、对照门槛判定 → 写进 DEVLOG。
- 待做 A1：错题自动复跑 ×2 的规则，作为一个单独的闸门 PR，在下一次跑闸门之前完成。

## 13. 这一段开发的经验（我的工作记忆）
- **方案先行**：每一步先在 phase5-frontend.md 写"已定"规则和验收，S 评审通过再动代码。评审原文在 `docs/roadmap/review-*.md`，结论都并进了方案。
- **F2 的停止语义改了三轮**：第 1 轮加了 CANCELLED_MESSAGE 常量和 answer 检查点；第 2 轮把重启扫尾改成 interrupted，并加了 STREAM_ABORTED；第 3 轮客户端断开也算 interrupted，status 加上 AST 约束，补了真实 TCP 断开的测试。教训是：**每种终止原因单独一个 status，不要合并成一个**；所有文案都是常量并导出给前端；终止原因不靠匹配文案来判断。
- **每加一个分支就问"这条路径被执行过吗"**。S 会逐个 scenario 检查覆盖。
- **提出偏离要带代码证据**。比如：500 会进 LLMClient 的重试集合；ChatOpenAI 是非流式调用。S 接受有证据的偏离，不接受凭感觉的偏离。
- 汇报格式：一句话结论，加一张卡片，依次写改了什么、偏离和理由、实测数字（表格）、未做、待提交文件，最后问能否提交。
- 本地 clone 的起点：`git fetch && git reset --hard origin/master`。改完给 S 看，**不要自己提交**。
