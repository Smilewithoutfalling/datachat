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

// ---------------------------------------------------------------- F4 迭代 V2a：步骤条与完成度（phase5 V2a §2.3、§3.2）
export type StepKey = "plan" | "code" | "exec" | "answer";
export type StepState = "done" | "running" | "pending" | "failed" | "stopped";
export type Step = { key: StepKey; name: string; state: StepState; count: number; seconds: number | null };
export const STEP_NAME: Record<StepKey, string> = { plan: "理解问题", code: "写代码", exec: "执行", answer: "总结" };
const ORDER: StepKey[] = ["plan", "code", "exec", "answer"];

const tsOf = (e: Ev): number | null => {
  const v = (e as unknown as { ts?: unknown }).ts;
  return typeof v === "number" && Number.isFinite(v) ? v : null;
};

/** 收到哪些事件 → 四段的状态。只看事件和 status，不猜进度。ReAct 没有 plan，就不出这一段。 */
export function steps(t: Turn, agent?: string): Step[] {
  const evs = t.events.filter((e) => e.type !== "error");
  const by = (k: StepKey) => evs.filter((e) => e.type === k);
  // 工作流一定先出计划；不知道 agent（旧调用）时看有没有收到 plan
  const hasPlan = agent === "workflow" || (agent === undefined && by("plan").length > 0);
  const keys = ORDER.filter((k) => k !== "plan" || hasPlan);
  const last = evs[evs.length - 1];
  // 下一段：最后收到的是 exec 且失败 → 回到写代码（修复重试）；否则顺延
  let next: StepKey | null = null;
  if (!last) next = keys[0];
  else if (last.type === "exec") next = last.data.ok ? "answer" : "code";
  else if (last.type === "answer") next = null;
  else next = ORDER[ORDER.indexOf(last.type as StepKey) + 1] ?? null;
  const o = outcome(t);
  const out: Step[] = keys.map((k) => {
    const mine = by(k);
    let seconds: number | null = null;
    if (k === "exec") seconds = mine.length ? mine.reduce((a, e) => a + Number((e.data as { duration_s?: number }).duration_s ?? 0), 0) : null;
    else if (mine.length) {
      const first = evs.indexOf(mine[0]);
      const prev = first > 0 ? tsOf(evs[first - 1]) : null;
      const end = tsOf(mine[mine.length - 1]);
      seconds = prev !== null && end !== null ? Math.max(0, end - prev) : null;
    }
    let state: StepState = mine.length ? "done" : "pending";
    if (o.kind === "running" && k === next) state = "running";
    if ((o.kind === "cancelled" || o.kind === "interrupted") && k === next) state = "stopped";
    if (o.kind === "error" && k === next) state = "failed";
    if (o.kind === "error" && t.result?.error_kind === "execution" && k === "exec" && mine.length) state = "failed";
    return { key: k, name: STEP_NAME[k], state, count: mine.length, seconds };
  });
  // 正常结束的轮次：没收到事件的段不画（比如按契约拒答，没有代码）。
  // 停下 / 出错的轮次保留后面没走到的段（灰），步骤条和运行中、停止中一样长（验收 r3 #4）
  return o.kind !== "ok" ? out : out.filter((s) => s.count > 0 || s.state !== "pending");
}

/** 部分完成（黄）：ok 且有 warnings 或 unverified_numbers（phase5 V2a §3.2）。返回要显示的提示条目。 */
export function partialSignals(t: Turn): string[] {
  if (t.status !== "ok" || !t.result) return [];
  // 可恢复的 dataset 错误只有"数据字典读取失败，已跳过"（service.py:186），S 10-22 定归黄；ReAct 的"重跑本轮"不算
  const dict = t.events.flatMap((e) => (e.type === "error" && !e.data.fatal && e.data.kind === "dataset" ? [e.data.message] : []));
  const out = [...dict, ...(t.result.warnings ?? [])];
  const nums = t.result.unverified_numbers ?? [];
  if (nums.length) out.push(`结论里这些数字在执行结果中没找到，请核对：${nums.join("、")}`);
  return out;
}

/** V2d §2e：整轮 token（done 里的 usage）。真数 + 估算；有估算时 estimated=true；一次调用都没有（reported 为 null）或没有 usage 时 null。 */
export function turnTokens(t: Turn): { n: number; estimated: boolean } | null {
  const u = t.result?.usage as
    | { total_tokens?: unknown; estimated_tokens?: unknown; estimated?: unknown; reported?: unknown; calls?: unknown }
    | undefined;
  if (!u || u.reported === null || u.reported === undefined || !Number(u.calls)) return null;
  const n = (Number(u.total_tokens) || 0) + (Number(u.estimated_tokens) || 0);
  return { n, estimated: u.estimated === true };
}

/** 整轮耗时（秒）：done 里的 timings.total；没有就用首末事件的 ts 差。 */
export function totalSeconds(t: Turn): number | null {
  const tm = t.result?.timings as { total?: unknown } | undefined;
  if (tm && typeof tm.total === "number") return tm.total;
  const ts = t.events.map(tsOf).filter((x): x is number => x !== null);
  return ts.length >= 2 ? ts[ts.length - 1] - ts[0] : null;
}
