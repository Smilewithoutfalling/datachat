# 服务商预设出处（阶段 6.5）

来源：app/core/providers.json。只记 Base URL、模型名和怪癖的依据。**除了 fake_llm，所有服务商都没有用真 Key 实测过**（方案 §6 第 5 条：只实测 S 自己那一个连接）。改预设时同步改这张表。

| id | 名称 | 协议 | Base URL | 模型 | 怪癖 | 出处 | 核实 |
|---|---|---|---|---|---|---|---|
| deepseek | DeepSeek | openai_chat | https://api.deepseek.com | deepseek-flash, deepseek-v4-pro | reasoning_replay=True | https://api-docs.deepseek.com | 已核实 |
| bailian | 阿里云百炼 | openai_chat | https://dashscope.aliyuncs.com/compatible-mode/v1 | qwen3.8-max, qwen3.7-plus | thinking_param=enable_thinking | https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope | 已核实；enable_thinking 怪癖未核实 |
| volcengine | 火山方舟（豆包） | openai_chat | https://ark.cn-beijing.volces.com/api/v3 | doubao-seed-2-1-pro-260915, doubao-seed-2-1-lite-260915 | thinking_param=thinking | ark.volcengine.com 兼容 OpenAI SDK 页 | base_url、pro 型号、thinking 已核实；lite 型号、Key 链接未核实 |
| moonshot | Moonshot（Kimi） | openai_chat | https://api.moonshot.cn/v1 | kimi-k3.1-pro, kimi-k3.1-pro-highspeed | reasoning_replay=True | https://platform.moonshot.cn/docs/api/chat ；https://platform.moonshot.cn/docs/guide/use-kimi-k2-thinking-model | 已核实（reasoning_replay 依据后者）；-highspeed 型号未核实 |
| zhipu | 智谱 | openai_chat | https://open.bigmodel.cn/api/paas/v4 | glm-5.3, glm-5.3-flash | thinking_param=thinking | https://docs.bigmodel.cn | 已核实 |
| siliconflow | 硅基流动 | openai_chat | https://api.siliconflow.cn/v1 | Pro/deepseek-ai/DeepSeek-R1 | — | https://docs.siliconflow.cn | 已核实 |
| minimax | MiniMax | openai_chat | https://api.minimax.cn/v1 | MiniMax-M3, MiniMax-M3.1-Flash | reasoning_replay=True | https://platform.minimaxi.com | 已核实；Key 链接末段未核实 |
| hunyuan | 腾讯混元 | openai_chat | https://api.hunyuan.cloud.tencent.com/v1 | hunyuan-turbos-latest | — | https://cloud.tencent.com/document/product/1729/111007 | 已核实 |
| openai | OpenAI | openai_responses | https://api.openai.com/v1 | gpt-6.1-sol, gpt-6-luna, gpt-6-astra | — | https://platform.openai.com/docs/models | 模型已核实；base_url、Key 链接未核实 |
| anthropic | Anthropic | anthropic | https://api.anthropic.com | claude-sonnet-5-5, claude-haiku-5-5, claude-opus-5-5 | — | https://docs.claude.com 模型总览 | 模型 ID 已核实 |
| gemini | Google Gemini | openai_chat | https://generativelanguage.googleapis.com/v1beta/openai/ | gemini-3.8-flash | — | https://ai.google.dev/gemini-api/docs/openai | 已核实 |
| azure | Azure OpenAI | azure | （用户填） | — | — | https://learn.microsoft.com/en-us/azure/ai-foundry/openai/api-version-lifecycle | v1 路径已核实（更新于 2026-05-13） |
| openrouter | OpenRouter | openai_chat | https://openrouter.ai/api/v1 | ~openai/gpt-sol-latest | — | https://openrouter.ai/docs/quickstart | base_url、模型已核实；Key 链接未核实 |
| groq | Groq | openai_chat | https://api.groq.com/openai/v1 | openai/gpt-oss-120b, openai/gpt-oss-20b | — | https://console.groq.com/docs/openai ；https://console.groq.com/docs/models | 已核实 |
| mistral | Mistral | openai_chat | https://api.mistral.ai/v1 | mistral-large-4, mistral-small-2603 | — | https://docs.mistral.ai/getting-started/models/models_overview/ | 模型名已核实；base_url 只和接口路径对照过 |
| xai | xAI（Grok） | openai_chat | https://api.x.ai/v1 | grok-4.7 | — | https://docs.x.ai | 已核实 |
| ollama | Ollama | openai_chat | http://localhost:11434/v1 | — | — | https://docs.ollama.com | 已核实 |
| lmstudio | LM Studio | openai_chat | http://localhost:1234/v1 | — | — | https://lmstudio.ai | 已核实 |
| newapi | NewAPI / OneAPI | openai_chat | http://localhost:3000/v1 | — | — | https://github.com/QuantumNous/new-api ；https://github.com/songquanpeng/one-api | 已核实 |
| custom | 自定义 | openai_chat | （用户填） | — | — | — | 用户自填 |
