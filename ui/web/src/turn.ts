// 一轮助手回答的状态（阶段 5 F2）。实时流和重放走同一个 reducer：重放时由前端合成 done（seq = max+1）。
// 规则见 docs/roadmap/phase5-frontend.md §1「停止的已定规则」：status 是最终真相源，流只作增量渲染。
import generated from "./generated/events.json";
import type { Message } from "./types";

export const EVENT_TYPES = generated.event_types as readonly string[];
export const ERROR_KINDS = generated.error_kinds as readonly string[];
export const MESSAGE_STATUSES = generated.message_statuses as readonly string[];
export const MESSAGES = generated.messages;

export type ChartItem = { png: string | null; option: Record<string, unknown> | null };
export type Result = {
  ok: boolean;
  answer: string;
  error: string | null;
  error_kind: string | null;
  llm_kind?: string | null; // error_kind=llm 时的子类（generated/events.json llm_kinds 或 http_NNN）；旧记录没有
  warnings: string[];
  unverified_numbers?: string[];
  charts: ChartItem[];
  result_text?: string;
  code?: string;
  [k: string]: unknown;
};
export type Ev =
  | { type: "plan"; seq: number; data: { text: string } }
  | { type: "code"; seq: number; data: { code: string; source: string; attempt: number; thought?: string } }
  | {
      type: "exec";
      seq: number;
      data: { ok: boolean; result_text: string; error: string | null; duration_s: number; stdout?: string; [k: string]: unknown };
    }
  | { type: "answer"; seq: number; data: { text: string; forced: boolean } }
  | { type: "error"; seq: number; data: { message: string; kind: string; fatal: boolean; llm_kind?: string | null } }
  | { type: "done"; seq: number; data: { result: Result } };

export type Turn = {
  events: Ev[]; // done 以外的事件，按 seq
  result: Result | null; // done 之后才有
  status: string; // 最终真相：running / ok / error / cancelled / interrupted
  live: boolean; // 本页实时收到的（不是重放）；只有实时轮次可能出现"已取消（未保存）"
};

export const emptyTurn = (live: boolean): Turn => ({ events: [], result: null, status: "running", live });

/** 唯一的 reducer。未知类型（后端新加、前端没重新生成）忽略而不是崩。 */
export function reduce(t: Turn, ev: Ev): Turn {
  if (!EVENT_TYPES.includes(ev.type)) return t;
  if (ev.type === "done") return { ...t, result: ev.data.result };
  if (t.events.some((e) => e.seq === ev.seq)) return t; // 去重（重连等）
  return { ...t, events: [...t.events, ev] };
}

/** status 不是 ok 且没有 result 时（cancelled / interrupted / 流异常 error）合成的 result：文案取 content（后端常量）。 */
export function synthResult(status: string, content: string): Result {
  const kind = status === "cancelled" || status === "interrupted" ? status : null;
  return { ok: false, answer: "", error: content, error_kind: kind, warnings: [], charts: [] };
}

/** 重放：历史事件 + 合成 done，走同一个 reducer。
 *  注意：status=cancelled 的轮次，库里可能存着 answer 事件（late-cancel）。它只作审计，不能展示——
 *  answerText 只在 ok 时出结论，outcome 的"未保存"只给实时轮次（live）。改这里的人别把它露出来。 */
export function replay(m: Message): Turn {
  let t = emptyTurn(false);
  const evs = (m.events ?? []) as Ev[];
  for (const ev of evs) t = reduce(t, ev);
  t = { ...t, status: m.status };
  if (m.status === "running") return t;
  const seq = evs.reduce((a, e) => Math.max(a, e.seq), -1) + 1;
  const result = (m.result as Result | null | undefined) ?? synthResult(m.status, m.content);
  return reduce(t, { type: "done", seq, data: { result } });
}

/** 以库里的最终 status 收尾一轮实时流（status 是真相源；流里的 done 只是增量）。 */
export function settle(t: Turn, m: Message): Turn {
  if (m.status === "ok" || m.status === "error") {
    const result = (m.result as Result | null | undefined) ?? t.result ?? synthResult(m.status, m.content);
    return { ...t, status: m.status, result };
  }
  // cancelled / interrupted：result 以库为准（没有 result_json），流里收到的 answer 留在 events 里供"未保存"展示
  return { ...t, status: m.status, result: synthResult(m.status, m.content) };
}

export type Outcome =
  | { kind: "running" }
  | { kind: "ok" }
  | { kind: "error"; errorKind: string | null; message: string }
  | { kind: "cancelled"; unsavedAnswer: string | null } // 实时轮次里流过 answer → "已取消（未保存）"
  | { kind: "interrupted"; message: string };

/** status → 终止原因。只按 status / error_kind 分支，不看文案。 */
export function outcome(t: Turn): Outcome {
  switch (t.status) {
    case "running":
      return { kind: "running" };
    case "ok":
      return { kind: "ok" };
    case "cancelled": {
      const ans = t.live ? t.events.find((e) => e.type === "answer") : undefined;
      return { kind: "cancelled", unsavedAnswer: ans && ans.type === "answer" ? ans.data.text : null };
    }
    case "interrupted":
      return { kind: "interrupted", message: t.result?.error ?? MESSAGES.interrupted };
    default:
      return { kind: "error", errorKind: t.result?.error_kind ?? null, message: t.result?.error ?? "" };
  }
}

/** 结论正文：只在 ok 时展示；cancelled 的未保存结论由 outcome 单独给。 */
export function answerText(t: Turn): string {
  if (t.status !== "ok") return "";
  return t.result?.answer || (t.events.find((e) => e.type === "answer") as Extract<Ev, { type: "answer" }> | undefined)?.data.text || "";
}
