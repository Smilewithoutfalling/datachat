// 后端接口的形状（app/server/app.py）。F2 起事件类型改由 gen_ui_types 生成。
export type FileInfo = { filename: string; size: number; sha256: string };
export type Dataset = { id: string; name: string; created_at: string; files: FileInfo[] };
export type DatasetDetail = Dataset & { tables?: Record<string, string[]>; summary?: string; error?: string };

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
      error?: undefined;
    }
  | { name: string; filename: string; error: string };
export type Preview = { dataset_id: string; rows: number; tables: PreviewTable[]; dicts: string[] };

export type Agent = "workflow" | "react";
export type Session = { id: string; dataset_id: string; agent: Agent; title: string; created_at: string; updated_at: string };
export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: string;
  created_at: string;
  feedback?: { rating: "up" | "down" | null; note: string } | null;
};
export type SessionDetail = Session & { messages: Message[] };

export type Settings = { model: string; base_url: string; timeout: number };
export type KeyStatus = { configured: boolean; source: string | null };
