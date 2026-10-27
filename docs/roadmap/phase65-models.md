# 阶段 6.5：多服务商模型接入（方案）

> 2026-10-27。起因：S 希望模型接入尽量兼容市面上所有接口（参考 LangBot）。这一阶段排在阶段 7 评测之前；评测时仍然固定一个模型（phase7-accuracy.md §1 第 1 条），本阶段只拿闸门做回归。

## 0. 调研结论（2026-10-27，各仓库 master 浅克隆）

| 项目 | 协议层 | 服务商 | 能力 / 怪癖 |
|---|---|---|---|
| LangBot | LiteLLM（`requesters/litellmchat.py`，1905 行） | 44 个 yaml 预设，其中 31 个 `litellm_provider: openai` | 交给 LiteLLM；自己写了 `_LeasedHTTPHandler`，用来关掉 LiteLLM 隐藏的连接重试 |
| LobeChat | 自写 `openaiCompatibleFactory` + `anthropicCompatibleFactory` | 88 个，其中 69 个走工厂 | model-bank 给每个模型标 `functionCall` |
| Cherry Studio | Vercel AI SDK | 12 种协议类型（openai / openai-response / anthropic / gemini / azure-openai / vertexai / aws-bedrock / ollama …） | `ProviderApiOptions`：isNotSupportArrayContent / StreamOptions / EnableThinking … |
| Cline | Vercel AI SDK | 30 个 vendor | model-capabilities.ts、error-classification.ts |
| Pydantic AI | 自写；models（协议）和 providers（地址 + 鉴权）分开 | DeepSeek / Kimi / 阿里等继承 `_OpenAICompatibleProvider` | profiles 按模型家族区分（deepseek、qwen、zai …） |
| any-llm | 自写 | 约 55 个，其中 22 个继承 `BaseOpenAIProvider` | DeepSeek 单独做了推理内容回放 |
| Open WebUI | 只有 OpenAI 和 Ollama 两个 router，Anthropic 有个特判 | 其余靠用户填兼容地址 | — |
| Aider、PandasAI | LiteLLM（PandasAI 是可选扩展 pandasai-litellm） | — | — |

**共同结构**：协议只有少数几种，服务商是数据，真正费工夫的是怪癖和工具调用能力。

**不用 LiteLLM**：沙箱实测 litellm 1.106.4 安装后 152 MB，另外还带 boto3/botocore 28 MB、tokenizers 11 MB、huggingface_hub 7 MB；sidecar 工件现在是 85.7 MB（DEVLOG [67]）。我们自己的重试和错误分类（app/core/llm.py 的 `classify_error`、LLMClient）会和它的隐藏行为冲突，LangBot 就是因此重写了 HTTP handler。LiteLLM Proxy、OneAPI、NewAPI 这类网关，用户可以自己起，再按「自定义（OpenAI 兼容）」接进来。

## 1. 已定（S 10-27）

1. 每个服务商单独存 Key，不共用一个。
2. 引入「连接」：用户可以自己命名，同一个服务商可以建多个连接（比如「DeepSeek 个人」和「DeepSeek 公司」）。同一时间只有一个连接生效。
3. 要做「获取模型列表」。

## 2. 三层结构

### 2a 协议（4 种，都走 LangChain，共用现有的 LLMClient 重试、`classify_error` 和 UsageTracker）
| id | 实现 | 新依赖 |
|---|---|---|
| `openai_chat` | `ChatOpenAI`（现状） | 无 |
| `openai_responses` | `ChatOpenAI(use_responses_api=True)` | 无 |
| `azure` | `AzureChatOpenAI`（langchain-openai 自带） | 无 |
| `anthropic` | `ChatAnthropic` | langchain-anthropic + anthropic（安装后约 28 MB，sidecar 增量实测后写进 DEVLOG） |

Gemini、Ollama、LM Studio、Mistral、Groq 都先走它们的 OpenAI 兼容端点；实测不够用再加原生协议（Gemini 原生约 17 MB）。Bedrock 和 Vertex 的鉴权是云账号体系，推迟。

### 2b 服务商预设：`app/core/providers.json`（只放数据）
每条包括：`id`、显示名、分组（国内 / 国外 / 本地 / 自定义）、`protocol`、`base_url`、是否需要 Key、申请 Key 的链接、`models`（常用模型若干）、`quirks`（见 2c）。

第一批：DeepSeek、阿里云百炼、火山方舟（豆包）、Moonshot（Kimi）、智谱、硅基流动、MiniMax、腾讯混元、OpenAI、Anthropic、Google Gemini、Azure OpenAI、OpenRouter、Groq、Mistral、xAI、Ollama、LM Studio、NewAPI / OneAPI，以及「自定义」（协议可选 OpenAI 兼容 / Anthropic）。

默认 Base URL 和常用模型名，实现时逐家从官方文档核对，并在 PR 里列出出处。

### 2c 怪癖开关（只收实际碰到的；默认全关）
- `no_stream_options`：不发 `stream_options`
- `no_array_content`：content 只发字符串
- `reasoning_replay`：多轮工具调用时把推理内容带回去（DeepSeek 推理模型这一类）
- `thinking_param`：用 `enable_thinking` 或 `thinking` 参数控制思考（Qwen、GLM 这一类）

可以在预设里写，也可以在连接上手动覆盖。每个开关至少配一个单测。

### 2d 能力：靠探测，不维护模型表
「测试连接」分两步：
1. 连接：现在的 `ping`。
2. 工具调用：发一个只有一个工具的请求（`tool_choice` 必须调用），看返回里有没有 `tool_calls`。

结果按「连接 + 模型」存下来。工具调用结果是 ✗ 时，对话页把 ReAct 置灰（悬停说明原因），只能用 workflow；没测过的不拦。

## 3. 数据和接口

- 新表 `connections`，字段：`id`、`name`（唯一，用户命名）、`provider`、`protocol`、`base_url`、`model`、`extra`（JSON，放 Azure 的 deployment / api_version 和 quirks 覆盖）、`probe`（JSON：`{model, connect, tools, checked_at}`）、`created_at`、`updated_at`。
- `settings.active_connection` 记录当前生效的连接。超时仍然是全局设置。
- Key 存在钥匙串里，`SERVICE = "datachat"`、`ACCOUNT = "conn:<id>"`；删除连接时一起删掉。接口永远不返回 Key。
- 新接口（都要 Bearer）：
  - `GET /providers`：预设列表
  - `GET/POST /connections`、`PUT/DELETE /connections/{id}`
  - `PUT/DELETE /connections/{id}/api-key`
  - `POST /connections/{id}/activate`
  - `POST /connections/{id}/test`：连接 + 工具调用两步
  - `GET /connections/{id}/models`：读服务商的 `/models`（Anthropic 是 `/v1/models`），超时 10 秒，失败时返回预设里的模型和错误原因
- 旧接口 `/settings`、`/settings/api-key` 保留一个版本，作用到当前生效的连接上，免得前端和后端的版本对不上。
- 每条分析消息的 meta 记下 `connection_name` 和 `model`，历史里能看出当时用的是哪个连接。
- 环境变量 `DEEPSEEK_*`：只在没有任何连接时生效，作为一个只读的虚拟连接「环境变量」，浏览器模式和 CI 都靠它。

## 4. 迁移（第一次启动新版时自动执行，只执行一次）

旧的 `settings`（model / base_url）加上钥匙串里的 `llm_api_key`，生成一个连接：
- `base_url` 是 `api.deepseek.com`（或者为空）→ 服务商 DeepSeek，命名为「DeepSeek」。
- 其他地址 → 服务商「自定义」，命名为「我的连接」（比如 S 的 grgbanking 网关）。
- Key 复制到 `conn:<id>`。旧条目保留一个版本，下个阶段再删。
- 迁移后把它设为生效连接。迁移逻辑要有单测：空库、只有 Key、只有地址、地址和 Key 都有。

## 5. 前端（设置页「模型」一节重做）

- **连接列表**：每张卡片显示名称、服务商图标、模型，以及最近一次测试的 ✓/✗；生效的那张高亮。按钮有「新建连接」、设为生效、编辑、删除（删除要二次确认）。
- **编辑连接**：
  - 名称
  - 服务商（分组下拉，选好后自动填 Base URL，显示「去申请 Key」的链接）
  - 自定义时选协议
  - Key（不需要 Key 的服务商隐藏这一项）
  - Base URL（可以改，带「恢复默认」）
  - 模型（可以输入也可以下拉；下拉里放预设模型，加「获取模型列表」按钮）
  - 选 Azure 时显示部署名和 API 版本
  - 「高级」里放怪癖开关
- **测试连接**：显示两行结果（连接、工具调用），失败时带上游原文（沿用 T11 user_error，Key 打码）。
- 「当前生效」的来源提示保留，外加连接名。
- 首次启动引导（D2）改成直接新建第一个连接。
- 视觉基线 f4-visual 里的设置页那张要用 CI x64 的 actual 重取。

## 6. 验收

1. pytest：预设 JSON 的 schema 校验（每条字段齐全、协议合法、URL 是 https，本地服务商可以是 http://localhost）；4 种协议在 fake 传输下都能构建出模型并调通一次；4 个怪癖开关各有单测；迁移 4 种情况；connections CRUD、Key 不出现在任何响应里；`/models` 成功、失败、超时；探测在 tools ✓/✗ 两种响应下都判对。
2. vitest：连接列表、编辑表单（服务商切换联动、Azure 字段、不需要 Key 的服务商）、测试结果两行、ReAct 置灰。
3. e2e：新建连接 → 测试 → 设为生效 → 分析一题（fake LLM）。
4. 闸门回归：用 S 的连接（迁移后的「我的连接」）跑一轮，要达到闸门门槛（react 单表 14/15、多表 9/10，workflow 多表 10/10，见 phase7-accuracy.md §0）；没达到的要逐题解释。
5. 真连接只实测 S 的那个连接（就是第 4 条闸门用的那个）。其余服务商只做单测，用模拟响应；PR 里逐家标明「未实测」，并给出默认 Base URL 和模型名的官方文档出处。（S 10-27 定：不按 S 手上有哪些 Key 来安排实测。）
6. sidecar 体积增量写进 DEVLOG（加了 langchain-anthropic 之后）。

## 7. 不做

- LiteLLM、Bedrock、Vertex、Gemini 原生协议（理由见 §0 和 §2a）。
- 维护模型能力表（改为 §2d 探测）。
- 一个分析里自动切换或回退到其他连接。
- 图片、嵌入、重排模型。

## 8. 已定（S 10-27，第二批）

1. 实测范围：见 §6 第 5 条，不按 S 有哪些 Key 来安排。
2. 迁移后旧连接的默认名字定为「我的连接」。
