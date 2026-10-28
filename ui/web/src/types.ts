// 后端接口的形状（app/server/app.py）。事件类型、error_kind、消息状态、常量文案由 scripts/gen_ui_types.py 生成（src/generated/）。
export type FileInfo = { filename: string; size: number; sha256: string };
export type Dataset = { id: string; name: string; created_at: string; files: FileInfo[] };

export type PreviewCell = string | null;
export type PreviewTable =
  | {
      name: string;
      filename: string;
      encoding: string;
      total_rows: number;
      total_columns: number;
      columns: string[];
      dtypes: string[];
      rows: PreviewCell[][];
      bidi_stripped: number; // 去掉的方向控制符个数（只影响显示）
      truncated_cells: number; // 超长截断的单元格数
      error?: undefined;
    }
  | { name: string; filename: string; error: string };
export type Preview = { rows: number; tables: PreviewTable[]; dicts: string[] };
// GET /datasets/{id}?rows=N（F1.1：预览并入详情，每个文件只读一遍）；POST /datasets 的响应也带 preview
export type DatasetDetail = Dataset & {
  tables?: Record<string, string[]>;
  summary?: string;
  error?: string;
  preview?: Preview;
};

export type Agent = "workflow" | "react";
export type Session = { id: string; dataset_id: string; agent: Agent; title: string; created_at: string; updated_at: string };
export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: string; // MESSAGE_STATUSES（generated/events.json）
  created_at: string;
  events?: unknown[]; // 助手消息：done 以外的事件（重放用，见 turn.ts）
  result?: unknown | null; // 助手消息：done 里的 result；cancelled / interrupted / 流异常时为 null
  feedback?: Feedback | null;
};
export type Rating = "up" | "down" | null;
export type Feedback = { rating: Rating; note: string };
export type SessionDetail = Session & { messages: Message[] };

export type SettingSource = "settings" | "env" | "default" | "connection";
/** GET /settings：sources 是每项当前生效值的来源（阶段 6 收尾；旧后端没有这个字段）。
 *  阶段 6.5：有生效连接时 model / base_url 的来源是 connection；connection 是生效连接（没有连接时 id=env）。 */
export type Settings = {
  model: string;
  base_url: string;
  timeout: number;
  sources?: { model: SettingSource; base_url: SettingSource; timeout: SettingSource };
  connection?: { id: string; name: string };
};

// ---- 阶段 6.5：多服务商模型连接（app/server/connections.py、app/core/providers.json）
export type Protocol = "openai_chat" | "openai_responses" | "azure" | "anthropic";
export type ProviderGroup = "cn" | "global" | "local" | "custom";
export type ThinkingParam = "enable_thinking" | "thinking" | null;
export type Quirks = { no_stream_options: boolean; no_array_content: boolean; reasoning_replay: boolean; thinking_param: ThinkingParam };
export type Provider = {
  id: string;
  name: string;
  group: ProviderGroup;
  protocol: Protocol;
  base_url: string;
  needs_key: boolean;
  key_url: string | null;
  models: string[];
  quirks: Partial<Quirks>;
};
export type Catalog = { protocols: Protocol[]; custom_protocols: Protocol[]; groups: ProviderGroup[]; providers: Provider[] };
/** 最近一次测试（按「连接 + 模型」；model 对不上时后端给 null）。tools=null：没测出来（连不上、超时），不拦。 */
export type Probe = { model: string; connect: boolean; tools: boolean | null; checked_at: string };
export type ConnExtra = { deployment?: string; thinking?: boolean; quirks?: Partial<Quirks> };
export type Connection = {
  id: string;
  name: string;
  provider: string;
  protocol: Protocol;
  base_url: string;
  model: string;
  extra: ConnExtra;
  quirks: Quirks; // 预设 + 覆盖合并后的生效值
  probe: Probe | null;
  created_at: string | null;
  updated_at: string | null;
  active: boolean;
  readonly: boolean; // 「环境变量」虚拟连接（id=env）：只在没有任何连接时出现
  key: { needed: boolean; configured: boolean; source?: string | null };
};
export type Connections = { active: string | null; items: Connection[] };
export type ConnectionIn = { name: string; provider: string; protocol?: Protocol; base_url?: string; model: string; extra?: ConnExtra };
export type ConnKey = { needed: boolean; configured: boolean };
export type TestStep = { ok: true; latency_ms: number } | { ok: false; llm_kind: string; message: string; latency_ms: number };
export type ToolsStep = { ok: boolean | null; latency_ms: number; llm_kind?: string; message?: string };
/** POST /connections/{id}/test：连接 + 工具调用两步。连不上时 tools 为 null（没测）。 */
export type ConnectionTest = { ok: boolean; model: string; connect: TestStep; tools: ToolsStep | null; probe: Probe };
export type ModelList = { source: "remote" | "preset"; models: string[]; reason?: string; llm_kind?: string };
/** 每条分析消息的 result.meta（阶段 6.5）：当时用的连接和模型。旧消息没有。 */
export type ResultMeta = { connection_id?: string; connection_name: string; model: string };
export type KeyStatus = { configured: boolean; source: string | null };
/** POST /settings/test（阶段 5 收尾 C）：用已保存的设置发一次最小请求。message 是 T11 user_error 的文案（带编号）。 */
export type SettingsTest =
  | { ok: true; latency_ms: number; model: string }
  | { ok: false; llm_kind: string; message: string; latency_ms: number };
