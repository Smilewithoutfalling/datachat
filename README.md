# 对话式数据分析 Agent（DataChat）

给一个 CSV，用自然语言提问，Agent 自动**规划 → 写 pandas 代码 → 沙箱执行 → 反思纠错 → 出结论 + 汇报级图表**。

项目实现了**两种 Agent 架构**，可直接对比：

| 版本 | 入口 | 控制流 | 特点 |
|------|------|--------|------|
| **工作流版** | `run.py` | 固定状态图（StateGraph） | 流程写死、可控、易调试；带 Executor↔Reviewer 反思纠错闭环 |
| **ReAct 版** | `run_react.py` | 模型自主决定调哪个工具、何时停 | 自主性高，控制权在模型；用 `create_react_agent` + 工具调用 |

图表统一走 `app/tools/plotting.py` 的样式：**中文字体 + 汇报级美化 + 高清输出**，出来的图可直接拖进 PPT。

## 工作流版架构（run.py）

```
用户问题
   │
[planner]    读表结构 + 理解问题 → 出分析步骤
   │
[codegen]    生成 pandas 代码
   │
[executor]   受限沙箱 + 超时执行 ──报错──┐
   │成功                                │ 条件边回流（最多 max_attempts 次）
[summarizer] 结果/图表 → 自然语言结论     │
   │                                    │
  END                            [reviewer] 读异常信息修代码
```

## ReAct 版架构（run_react.py）

模型在循环中自主行动：**思考 → 调用 `run_python_on_data` 工具执行代码 → 观察结果/报错 → 决定继续或收尾**。
控制流不再由固定的图决定，而由模型的工具调用驱动。`run_react.py` 会打印完整的"思考-调用-观察"轨迹。

## 文件导读

- `app/graph.py`     —— 工作流版状态图与条件边（先读这个，理解整体流程）
- `app/react_agent.py` —— ReAct 版（自主工具调用），对比着读最能体会两种架构差异
- `app/state.py`     —— 工作流版在节点间流转的 State 定义
- `app/nodes/`       —— 五个节点：planner / codegen / executor / reviewer / summarizer
- `app/config.py`    —— 项目根路径锚定，产物统一落到 `outputs/`（不随启动目录漂移）
- `app/tools/persist.py`  —— 图表唯一命名 + 运行记录 `runs.jsonl`
- `app/tools/dictionary.py` —— 数据字典 BM25 检索（jieba 分词），把字段说明注入提问
- `app/tools/sandbox.py`  —— 受限命名空间 + 超时的代码执行（安全相关）
- `app/tools/plotting.py` —— 中文字体 + 汇报级图表样式（解决中文乱码、美化）
- `app/tools/schema.py`   —— CSV 表结构描述
- `app/llm.py`       —— DeepSeek（OpenAI 兼容）模型封装
- `ui/streamlit_app.py` —— 单轮网页界面（工作流版）
- `ui/chat_app.py`   —— 多轮对话界面（ReAct 版 + 记忆，支持追问）

## 运行

```bash
# 1. 安装依赖（建议在你的 conda 环境里）
pip install -r requirements.txt

# 2. 配置 DeepSeek API Key
cp .env.example .env      # 然后编辑 .env 填入 DEEPSEEK_API_KEY

# 2b. 跑测试（不需要 API Key）
pip install -r requirements-dev.txt
python -m pytest -q

# 3a. 工作流版（固定状态图）
python run.py
python run.py data/sample.csv "各产品的平均单价是多少？画柱状图。"

# 3b. ReAct 版（模型自主调用工具）
python run_react.py
python run_react.py data/sample.csv "各地区各产品的销量分布，画图说明。"

# 3c. 单轮网页界面（工作流版）
streamlit run ui/streamlit_app.py

# 3d. 多轮对话界面（ReAct 版，支持记忆与追问）
streamlit run ui/chat_app.py
```

生成的图表保存在 `outputs/charts/`（每次唯一命名，不覆盖历史）；
每次运行追加一行记录到 `outputs/runs.jsonl`（问了什么、答了什么、生成了哪些图）。

## 三个进阶能力

- **数据字典 RAG（BM25 词法检索）**：在 CSV 旁放一个同名 `*.dict.csv`（两列 `field,description`），
  提问前用 BM25 + jieba 检索最相关的字段说明并注入 prompt，帮模型把口语化问法对应到真实列名。
  DeepSeek 无 embedding 接口，BM25 纯词法、零网络依赖、几毫秒返回，对短字段文本足够好。
  无 `.dict.csv` 时自动跳过，不影响运行。
- **多轮对话与追问**：`ui/chat_app.py` 基于 ReAct 智能体 + LangGraph `MemorySaver`，
  同一 `thread_id` 下模型记得前几轮的结论，可自然追问（"那华北呢？""它的销量呢？"）。
- **结果持久化**：路径锚定项目根，图表唯一命名落到 `outputs/charts/`；sandbox 重定向 `plt.savefig`，
  无论模型用什么文件名，图都强制存到正确位置，工作目录不再散落临时图片。

## 可扩展方向

- **更强 RAG**：当前是词法检索；若接入带 embedding 的服务，可换向量检索提升语义匹配。
- **更强沙箱**：当前用线程超时 + 受限 builtins，生产环境可换 subprocess / Docker 隔离。
- **支持 SQLite/多表**：扩展 schema.py 与 executor，把 pandas 换成 SQL 执行。

## 安全说明

`sandbox.py` 通过受限 `__builtins__` 白名单屏蔽了 `open / __import__ / eval` 等高危能力，
并用线程 join 超时防止死循环。注意：线程超时**无法真正杀死**失控线程，且并非完整隔离，
仅作演示级防护；真要对外提供服务，应改用子进程或容器沙箱。
