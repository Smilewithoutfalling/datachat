// 各接口的薄封装。全部经过 Api（统一 Bearer 与 401 处理）。
import type { Api } from "./api";
import { parseSse } from "./sse";
import type { Ev } from "./turn";
import type { Agent, Dataset, DatasetDetail, KeyStatus, Rating, Session, SessionDetail, Settings } from "./types";

const jsonBody = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const PREVIEW_ROWS = 20;

export function client(api: Api) {
  return {
    datasets: () => api.json<Dataset[]>("/datasets"),
    dataset: (id: string, rows = PREVIEW_ROWS) =>
      api.json<DatasetDetail>(`/datasets/${encodeURIComponent(id)}?rows=${rows}`),
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

    /** 提问：POST 后读 SSE。messageId 在响应头里，拿到就能点停止。 */
    ask: async (sessionId: string, content: string, signal?: AbortSignal) => {
      const res = await api.request(`/sessions/${encodeURIComponent(sessionId)}/messages`, {
        ...jsonBody("POST", { content }),
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        signal,
      });
      const messageId = res.headers.get("X-Message-Id") ?? "";
      const body = res.body;
      async function* events(): AsyncGenerator<Ev> {
        if (!body) return;
        for await (const m of parseSse(body)) {
          let ev: Ev;
          try {
            ev = { type: m.event, ...JSON.parse(m.data) } as Ev;
          } catch {
            continue; // 坏块跳过；最终以库里的 status 为准
          }
          yield ev;
        }
      }
      return { messageId, events: events() };
    },
    /** 停止：CAS 落库 cancelled。409 = 已经结束。前端必须等它返回再断开流（否则库里会落 interrupted）。 */
    cancel: (messageId: string) =>
      api.json<{ id: string; status: string }>(`/messages/${encodeURIComponent(messageId)}/cancel`, { method: "POST" }),
    feedback: (messageId: string, rating: Rating, note = "") =>
      api.json<{ message_id: string; rating: Rating; note: string }>(
        `/messages/${encodeURIComponent(messageId)}/feedback`,
        jsonBody("PUT", { rating, note }),
      ),

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
