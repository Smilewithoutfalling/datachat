# M 系列审查的回复与决定（2026-10-12）

对应 docs/roadmap/review-M-series.md。清单核验基线是 16d51c3，本回复对照 master ec9ac0f。两轮讨论后的最终决定如下。

## 采纳
| 编号 | 决定 | 落到哪 |
|---|---|---|
| M01 / M15 | 插入阶段 3.5 外部验证闸门，放在阶段 4 之前；阈值由 S 预登记（docs/roadmap/gate-phase35.md） | 阶段 3.5 |
| M02 | 不用关键词黑名单（换个说法就绕过）。报告逐题记录判对靠的层级（strict / rounded / scaled / extras / relaxed / refusal，备选答案加 alt:），重评输出 needs_audit 清单，非 strict 判对的题人工抽审 | 阶段 3.5，已做 |
| M03 / M16 | keyring 作为阶段 4 第一项；威胁模型写明"偷 Key 目标在阶段 8 前不成立"，阶段 6–7 选 (a) 只分析自己的数据 | docs/THREAT_MODEL.md，已写 |
| M04 | 评测集指纹覆盖题面代码（cases.py / cases_extra.py / case_model.py）、数据生成脚本、数据与字典文件 | 阶段 3.5，已做 |
| M05 | n=1、网关缓存、不得单独引用为准确率 → docs/eval/FROZEN.md | 已写 |
| M06 | PyInstaller sidecar + 沙箱 worker 的 spike 提前到阶段 4 末 | 阶段 4 |
| M07 | 本来就在阶段 4（B18） | 阶段 4 |
| M08 / M14 | logging + trace id，runs.jsonl 换数据库 | 阶段 4 |
| M09 | 阶段 4 第一步 analyze_stream()；内部本来就在 stream，不算返工内核 | 阶段 4 |
| M10 | 最小多表支持（目录 / 路径列表 → dfs，不提示 join key）已做，闸门要用；表结构允许一个数据集多文件 | 阶段 3.5（最小）、阶段 4（表结构） |
| M11 | .gitignore 加 .venv/、.pytest_cache/ | 已做 |
| M12 | 评测 JSON 直接并进 master（分支会删，SHA 会成孤儿）；plan.md 入库 | 已做 |
| M13 | 接口返回 png + 图表数据 | 阶段 4 |
| M18 / M20 | 闸门结论出来后重估工期、在闸门数据上定阶段 7 目标 | 阶段 3.5 之后 |
| M19 | 阶段 6 验收加代码签名 / SmartScreen；依赖许可证审计 | 阶段 6 |

## 修正后采纳
- **M21**：两条独立线，互补并行。DuckDB 是引擎能力；M10 是应用层（多文件注册成表、join key 从哪来、多表 schema 怎么进 prompt），DuckDB 一个都不做。
- **M22**：保留 Tauri，前提是前端只走 HTTP / SSE，不用 Tauri invoke / IPC，外壳可换；真正的难点是 PyInstaller sidecar。
- **合规（标尺第 7 项）**：依赖许可证审计放阶段 6；AI 生成标识与备案针对面向公众的服务，留到 Web 阶段。

## 附：判对层级的第一次统计（阶段 3 报告离线重评）
| 报告 | 判对 | strict | rounded | alt:strict | refusal | 其余（需抽审） |
|---|---|---|---|---|---|---|
| react 有字典（phase3c） | 128/130 | 72 | 0 | 3 | 9 | 44（relaxed 36、extras 5、scaled 2、alt:rounded 1） |
| workflow 有字典（phase3） | 128/130 | 81 | 0 | 5 | 9 | 33（relaxed 32、scaled 1） |

约三分之一的"判对"靠放宽规则，正是 M02 担心的量级。抽审清单由 `python run_eval.py --rescore <报告>` 的 needs_audit 给出。
