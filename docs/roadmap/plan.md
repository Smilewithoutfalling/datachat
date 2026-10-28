# DataChat 产品化计划

> 2026-10-12 入库（此前只在仓库外，DEVLOG 里的引用是悬空的，M12）。按 M 系列审查（docs/roadmap/review-M-series*.md）修订：插入阶段 3.5，阶段 4/6 补交付物，外壳约束写明。

## 目标与前提
- 做成产品：先出 Windows 桌面客户端（用户自己填 API Key），Web 服务器版后续再上。
- 去掉 Streamlit，用 **React + TS 前端 + FastAPI 后端**。桌面端把后端作为本地 sidecar 进程，以后上服务器时同一套前后端直接复用。
- 威胁模型（桌面阶段）：单用户、本机数据、自带 Key。目标是防"别人给的恶意 CSV 通过提示注入偷 Key / 写文件"，**但这个目标在阶段 8（OS 级隔离）之前不成立**；阶段 6–7 的产品定位是"只分析自己的数据"。详见 docs/THREAT_MODEL.md。多租户问题留到 Web 阶段。
- 前端只通过 HTTP / SSE 调 FastAPI，**不使用 Tauri 的 invoke / IPC**：外壳（Tauri / Electron / 托盘）可替换，外壳 spike 失败不返工前端（M22）。

## 计划表
| 阶段 | 周期 | 交付物 | 验收标准 | 解决的问题 |
|---|---|---|---|---|
| 0 基线对齐 | 0.5 周 | 推送 2f67936；锁依赖版本；pytest 骨架；DEVLOG [1] | 远端 = 本地；`pytest` 能跑 | B03/B08 核对、B17 |
| 1 内核重构 | 1 周 | `core/` 包：统一的 `analyze()` 服务函数；结构化结果；LLM 显式超时/重试/token 统计；修评测口径与 comparator；编码检测 | 4 个旧入口全部改走 `analyze()`；评测出第一组可信基线数字 | B04 B06 B07 B10 B11 B12 B14 B15 B16 |
| 2 执行隔离 | 1 周 | 子进程沙箱：干净环境变量（不含 Key）、超时强杀、内存上限（Windows 用 Job Object）、工作目录隔离；结果通过 JSON/parquet + png 回传 | 三类逃逸用例写成测试，全部被挡；死循环 20 秒内被杀 | B01 B02 B03 |
| 3 评测基线 | 1–2 周 | 评测集 100–150 题，多张表，含歧义题、应拒答题；两个 Agent 同场比较准确率、耗时、token；GitHub Actions 跑单测 | 出一份带 SHA 的评测报告 | B13 |
| 3.5 外部验证闸门 | 3 天 | 非自造数据上的 25 题（单表 15：UCI Online Retail 改造的中文 GBK 脏表；多表 10：Olist 8 张表）；标准答案由独立脚本在原始数据上算出；最小多表支持（dfs）；报告逐题标判对层级、评测集指纹 | 按 docs/roadmap/gate-phase35.md 预登记的阈值与失败分布规则出结论 | M01 M02 M04 M05 M10(部分) M15 |
| 4 后端 API | 1–2 周 | 第一步：API Key 进系统钥匙串（keyring）；`analyze_stream()` 逐步产出事件，`analyze()` 包一层（M09）。FastAPI：数据集上传（一个数据集可含多个文件，M10）、会话、消息（SSE 流式推送每一步）、设置；SQLite + SQLAlchemy（表结构兼容 PG，预留 user_id）；logging + trace id（会话 / 消息 id），runs.jsonl 换成数据库（M08 M14）；接口返回 png + 图表数据（M13）。最后：PyInstaller sidecar + 沙箱 worker 在 Actions Windows runner 上的 spike（B35 / M06） | 用 curl 走完"上传 → 提问 → 流式结果 → 历史可查"；重启后会话还在；spike 打出的 exe 能在干净 runner 上执行一次沙箱代码 | B18 B35 |
| 5 前端 | 2–3 周 | 第一件事（M13，从阶段 4 顺延，含后端三步）：图表库定为 ECharts；定 option 格式与白名单、写 builder `chart(kind, df, x=, y=, series=, title=)`；worker 产出 chart_option（与 result 脱钩，B44）；接口加 chart_option；改绘图提示词并重跑闸门。之后：React + Vite + TS：数据集面板、对话流（展示计划、代码、执行步骤）、图表、可展开的代码、👍👎 反馈、Key 设置页，分步与验收见 docs/roadmap/phase5-frontend.md（F0–F5） | 不碰命令行就能完整用一遍 | — |
| 6 桌面打包 | 1–2 周 | Tauri 2 外壳（前提见上：前端只走 HTTP）+ PyInstaller 后端 sidecar；Windows 安装包；自动更新；首次启动引导填 Key；依赖许可证审计；pyarrow 已随 Streamlit 一起去掉（DEVLOG [67]） | 在一台干净的 Windows 上一键安装，可用；对外分发前代码签名，显示已验证的发布者（2024 年起任何证书都不能让 SmartScreen 立刻不拦，见 phase6-desktop.md §6，M19）；方案见 docs/roadmap/phase6-desktop.md；对外分发前满足 THREAT_MODEL.md 的 (b) 条件 | — |
| 6.5 模型接入 | 1 周 | 连接（用户命名，可多个）× 服务商预设（约 20 家）× 4 种协议（OpenAI Chat / OpenAI Responses / Azure / Anthropic）；每个连接一个 Key（存在系统钥匙串）；获取模型列表；测试连接时探测工具调用，不支持就把 ReAct 置灰；旧设置自动迁移。方案见 docs/roadmap/phase65-models.md | 见 phase65-models.md §6 | — |
| 6.6 记忆系统 | 批 1 约 4.5 天 | 先做批 1：保留与删除（删会话连带删图、删单条消息）、开关（settings 表，默认 off；off 时 prompt 逐字节不变）、按 token 的记忆预算、失败轮进历史、代码维护的工作状态、结构化回合快照。之后与评测侧合跑 history on/off 消融，看基线再定改写 / 口径库 / 压缩 / 门槛。方案见 docs/roadmap/memory-system.md 与 memory-system-spec.md（§14 是与评测 agent 的分工） | 见 memory-system-spec.md §5 批 1 DoD | — |
| 7 准确率 | 2–4 周 | 先做评测：留出集 H1（约 40 题，含陷阱和画图题）、过程验证器、pass^k；再做改进：列画像、结果合理性校验、枚举值召回；DuckDB / YAML 语义层视 H1 失败分布而定；反馈沉淀推迟。方案见 docs/roadmap/phase7-accuracy.md | 在留出集 H1 上：先测基线，再由 S 定目标「比基线高 X 个百分点」（M20）；闸门 25 题和自造集只作回归（2026-10-27 改：闸门已接近满分，而且已经被逐题分析过） | B05 B09 |
| 8 Web 上线（后续） | 另定 | PostgreSQL、登录、任务队列、Docker/E2B 沙箱、Langfuse、服务器部署与 ICP 备案 | 另定 | 多租户 |

阶段 1–7 原估合计约 10–15 周（一个人业余时间）。M18 认为实际可能 6–12 个月：**阶段 3.5 闸门结论出来后重估工期，必要时砍范围**。

## 进度与重估（2026-10-13，阶段 4 结束时；进度表 2026-10-23 补到阶段 5）
| 阶段 | 状态 | 实际 | 证据 |
|---|---|---|---|
| 0–3d | 完成 | 2026-10-09 → 10-10 | DEVLOG [1]–[9] |
| 3.5 / 3.6 | 完成，闸门中间区，P0 ⑤⑥ 已修 | 2026-10-12 | DEVLOG [10]–[13] |
| 4 | **完成**，三条验收都达到 | 2026-10-12 → 10-13 | DEVLOG [14]–[18]；curl 全流程与重启见 [16]，跨重启多轮见 [17]，干净 runner 上执行沙箱代码见 [18] |
| 5 | **完成**：F0–F4、V1 / V2a~V2d、F5 真 Key 走查通过（2026-10-26），Streamlit 已删 | 2026-10-13 → 10-26 | DEVLOG [19]–[67] |
| 6 | **自用范围完成**：D1 壳 + NSIS 安装包、D2 首次启动 + (a) 提示；D3 更新 / D4 许可证 / D5 签名推迟到对外分发前（S 10-26 定） | 2026-10-26 → 10-27 | DEVLOG [68]–[70]；CI 安装冒烟 desktop run 40295387628 |

**重估（M18）**：阶段 0–4 原估 5–7.5 周，实际 5 个日历日。原因是代码主要由 Hark 写、S 审，**不能**照这个速度外推后面的阶段：
- 阶段 0–4 几乎都能在 Linux 沙箱 + CI 里验证；阶段 5–6 的验收是"不碰命令行能用""干净 Windows 一键安装"，必须 S 在本机动手看，日历时间取决于 S 的可用时间，不取决于写代码的速度。
- 阶段 7 的节奏由真实模型评测决定（S 用自己的 Key 跑，每轮 25–130 题）。
- 外部依赖有交付周期：代码签名证书（阶段 6 对外分发前）通常要几天到几周的审核。

| 阶段 | 原估 | 重估（日历时间） | 主要不确定性 |
|---|---|---|---|
| 5 前端 | 2–3 周 | M13 后端三步已完成（[22]–[28]）；前端 F0–F5 另计 3–4.5 周（2026-10-15 改，见 docs/roadmap/phase5-frontend.md） | S 的 UI 验收轮数；M13 改提示词后的闸门回归 |
| 6 桌面打包 | 1–2 周 | 1–2 周，签名证书另计 | Tauri WebView2 / 自动更新 spike；证书审核 |
| 7 准确率 | 2–4 周 | 2–4 周（不变） | 需要新的留出评测集（闸门 25 题已只作回归）；评测轮数 |

阶段 6 结束时再按同样方法重估一次。

**重估（2026-10-27，阶段 6 自用范围结束）**：阶段 5 原估 2–3 周、实际 14 个日历日；阶段 6 自用部分原估 1–2 周、实际 2 天（D3~D5 没做）。剩下的工期不再取决于写代码的速度：
- 阶段 7：仍估 2–4 周。瓶颈是真实模型评测的轮数（每轮要 S 的 Key 和时间）以及留出集的建设，不是写代码。方案见 docs/roadmap/phase7-accuracy.md。
- 对外分发（D3~D5 + THREAT_MODEL 重新确认）：代码约 1 周，签名证书另计几天到几周的审核。
- 阶段 8：另定，不变。

## 开发日志（docs/DEVLOG.md）
- 每完成一个阶段或一次重要提交，追加一条记录，内容包括：
  - commit SHA 和当前技术栈；
  - **对照上一条的问题编号逐项写状态和证据**（文件:行、测试名或评测数字）；
  - 当前已知问题表、指标快照和下一步。
- 第 [0] 条已写好：基线 4e67c92，问题编号 B01–B18。

## 外部审计待办（2026-10-26：《AI Agent Book》第 7 章审计 + 全书 × 竞品综合稿，复核三定稿；报告不入库）
P0 三件（usage 拆分、单轮 token 预算、finish_reason=length）见 phase5-frontend.md「V2d」。其余按阶段归位：
- 阶段 6 第一步：M06 / B35 打包态沙箱 `sys.executable` 验证。
- 阶段 7：闸门加陷阱题组（错误前提 / 误导，判定手册 guessing 字段承接）；LLM-judge（必须换模型家族，防长度 / 位置 / 同源偏差）；过程验证器（AST 区分读取列与新建列再对 schema 校验，硬编码答案单独检测）；pass^k 报表（--repeat 受网关 temp0 缓存影响，需题序扰动独立化）；YAML 语义层（WrenAI / SuperSonic 为蓝本，条目带生效时间、声明"资料非指令"）；反馈沉淀管道（👍👎 / 失败轨迹 → 聚类 → 门槛入册 → 新题迁移验证）；判定记录补首错 step 序号。
- 产品 P2（阶段 7 之后另定）：分支会话（Data Formulator 的 Data Threads）、图型推荐、轻量用户记忆（口径偏好）。
- 条件先行 / 远期：ReAct 状态栏（单独 A/B，验证对 MARK 认证、闸门准确率和"提前放弃"的影响）；前缀重排（先真 Key 测 cached_tokens；用户自带 Key，服务商缓存能力不由项目定）；分节点 max_tokens 上限（V2d §1 有 reasoning 数据后再定）；ReAct 重复调用指纹熔断；图表 Vision 自查；runs.jsonl 跨会话并发写加锁；训练数据预埋。

## 已定 / 待定选择
- 外壳：暂定 Tauri 2，构建放在 GitHub Actions Windows runner（本机不装 Rust）。前提是前端只走 HTTP（M22）；阶段 6 前用 spike 判 WebView2 兼容与自动更新，不行就换 Electron，前端不受影响。真正的难点是 PyInstaller 把 pandas + matplotlib + langchain（+ duckdb）打成 sidecar，所以 spike 提前到阶段 4 末。
- 阶段 2 的内存上限：已用 ctypes Job Object 实现（app/tools/_winjob.py）。
