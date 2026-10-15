// 各接口的薄封装。全部经过 Api（统一 Bearer 与 401 处理）。
import type { Api } from "./api";
import type { Agent, Dataset, DatasetDetail, KeyStatus, Preview, Session, SessionDetail, Settings } from "./types";

const jsonBody = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const PREVIEW_ROWS = 20;

export function client(api: Api) {
  return {
    datasets: () => api.json<Dataset[]>("/datasets"),
    dataset: (id: string) => api.json<DatasetDetail>(`/datasets/${encodeURIComponent(id)}`),
    preview: (id: string, rows = PREVIEW_ROWS) =>
      api.json<Preview>(`/datasets/${encodeURIComponent(id)}/preview?rows=${rows}`),
    upload: (files: File[], name: string) => {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f, f.name));
      fd.append("name", name);
      return api.json<DatasetDetail>("/datasets", { method: "POST", body: fd });
    },
    deleteDataset: (id: string) => api.json(`/datasets/${encodeURIComponent(id)}`, { method: "DELETE" }),

    sessions: () => api.json<Session[]>("/sessions"),
    session: (id: string) => api.json<SessionDetail>(`/sessions/${encodeURIComponent(id)}`),
    createSession: (dataset_id: string, agent: Agent) =>
      api.json<Session>("/sessions", jsonBody("POST", { dataset_id, agent })),
    renameSession: (id: string, title: string) =>
      api.json<Session>(`/sessions/${encodeURIComponent(id)}`, jsonBody("PATCH", { title })),
    deleteSession: (id: string) => api.json(`/sessions/${encodeURIComponent(id)}`, { method: "DELETE" }),

    settings: () => api.json<Settings>("/settings"),
    saveSettings: (s: Partial<Settings>) => api.json<Settings>("/settings", jsonBody("PUT", s)),
    keyStatus: () => api.json<KeyStatus>("/settings/api-key"),
    setKey: (api_key: string) => api.json<KeyStatus>("/settings/api-key", jsonBody("PUT", { api_key })),
    deleteKey: () => api.json<KeyStatus>("/settings/api-key", { method: "DELETE" }),
  };
}
export type Client = ReturnType<typeof client>;

export function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function formatSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}
