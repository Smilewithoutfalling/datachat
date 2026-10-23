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

export type Settings = { model: string; base_url: string; timeout: number };
export type KeyStatus = { configured: boolean; source: string | null };
/** POST /settings/test（阶段 5 收尾 C）：用已保存的设置发一次最小请求。message 是 T11 user_error 的文案（带编号）。 */
export type SettingsTest =
  | { ok: true; latency_ms: number; model: string }
  | { ok: false; llm_kind: string; message: string; latency_ms: number };
