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

/** 黄条（提示条）的条目：ok 时的可恢复字典错误 + warnings（phase5 V2a §3.2）。
 *  阶段 7.6 U3：unverified_numbers 不再进黄条，改由结果卡的校验徽章单独承载（verifyState），黄条不重复列这些数字。 */
export function partialSignals(t: Turn): string[] {
  if (t.status !== "ok" || !t.result) return [];
  // 可恢复的 dataset 错误只有"数据字典读取失败，已跳过"（service.py:186），S 10-22 定归黄；ReAct 的"重跑本轮"不算
  const dict = t.events.flatMap((e) => (e.type === "error" && !e.data.fatal && e.data.kind === "dataset" ? [e.data.message] : []));
  return [...dict, ...(t.result.warnings ?? [])];
}

/** 部分完成（卡头黄标签）：黄条有条目，或有未核实数字（V2a §3.2 的口径不变，只是数字挪到了徽章里）。 */
export function isPartial(t: Turn): boolean {
  return partialSignals(t).length > 0 || unverifiedOf(t).length > 0;
}

const unverifiedOf = (t: Turn): string[] =>
  t.status === "ok" && Array.isArray(t.result?.unverified_numbers)
    ? t.result.unverified_numbers.filter((x): x is string => typeof x === "string")
    : [];

// ---------------------------------------------------------------- 阶段 7.6 U3：结果卡（docs/roadmap/phase76-ui.md §2 U3）
/** 校验徽章：只在真的核过时出（ok、执行成功拿到了结果、不是反问）。
 *  app/core/grounding.py：证据为空时 unverified_numbers 返回 [] 但什么都没核，所以没执行成功（executed 不为 true）时不出「全部可溯源」。
 *  numbers 原样取 result.unverified_numbers，徽章里的 N 就是它的条数。 */
export type Verify = { kind: "ok" } | { kind: "unverified"; numbers: string[] };
export function verifyState(t: Turn): Verify | null {
  const r = t.result;
  if (t.status !== "ok" || !r || r.executed !== true || r.clarify === true) return null;
  const numbers = unverifiedOf(t);
  return numbers.length ? { kind: "unverified", numbers } : { kind: "ok" };
}

/** 一句话结论：结论正文第一段的第一句，逐字摘取，只去掉 Markdown 记号，不改写、不补字。
 *  取不到（第一块是表格 / 代码 / 分隔线，或第一句超过 LEAD_MAX 字、短于 4 字）时 lead 为 null，卡片就不出这一行。
 *  后端没有单独的 summary 字段（app/core/result.py AnalysisResult 只有 answer），所以只能从 answer 摘。
 *
 *  阶段 7.6 U3-1（docs/roadmap/phase76-u3u5.md §1.1 做法 A）：同时返回 body，即正文里隐去已摘出那一句之后剩下的部分，
 *  卡头和正文不再重复同一句。规则：
 *  1. body = 原文去掉 lead 在原始 Markdown 里对应的那段（从第一段内容的起点——列表记号之后——到这一句的句末），其余字符不动；
 *  2. 被去掉的原文里 `**`、`__`、`` ` `` 必须成对、链接 [..](..) 必须完整，否则视为隐不干净：lead = null，body = 原文（退回 U3 之前）；
 *     对不上（原文里找不到去掉记号后等于 lead 的前缀）同样退回；
 *  3. 去掉后这一行只剩空白（或只剩列表记号）时整行删除；它前面的小标题保留；
 *  4. 只改显示：消息 content、result.answer、导出、会话记忆读到的仍是完整原文。 */
export const LEAD_MAX = 120;
export type Conclusion = { lead: string | null; body: string };

const plainOf = (s: string): string =>
  s
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/(\*\*|__|`)/g, "")
    .replace(/(^|[^*])\*([^*]+)\*/g, "$1$2")
    .trim();

/** 被去掉的原文前缀能不能干净地去掉：强调 / 代码记号成对，链接完整。 */
function cleanCut(raw: string): boolean {
  const even = (re: RegExp) => (raw.match(re)?.length ?? 0) % 2 === 0;
  if (!even(/\*\*/g) || !even(/__/g) || !even(/`/g)) return false;
  const rest = raw.replace(/!?\[[^\]]*\]\([^)]*\)/g, "");
  return !/\[[^\]]*\]\(/.test(rest) && !/\[[^\]]*$/.test(rest);
}

function leadOf(first: string): string | null {
  const plain = plainOf(first);
  const m = /^.*?[。！？!?；;]/u.exec(plain);
  const lead = (m ? m[0] : plain).trim();
  if (Array.from(lead).length < 4 || Array.from(lead).length > LEAD_MAX) return null;
  return lead;
}

export function conclusionOf(answer: string): Conclusion {
  const text = answer ?? "";
  const none: Conclusion = { lead: null, body: text };
  const lines = text.split(/(?<=\n)/); // 保留换行符，拼回去逐字不变
  let offset = 0;
  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i];
    const line = rawLine.trim();
    if (!line) { offset += rawLine.length; continue; }
    if (/^#{1,6}\s/.test(line)) { offset += rawLine.length; continue; } // 小标题（「### 结论」）跳过，看下一行
    if (/^(```|~~~|\||[-*_]{3,}$|>)/.test(line)) return none; // 代码块、表格、分隔线、引用打头：不是一句话
    const lineBody = rawLine.replace(/\r?\n$/, "");
    const marker = /^\s*(?:(?:[-*+]|\d+[.)、])\s+)?/.exec(lineBody)![0];
    const content = lineBody.slice(marker.length);
    const lead = leadOf(content);
    if (!lead) return none;
    // 在原始 Markdown 里找这一句的句末：句末标点之后、或行尾，去掉记号后正好等于 lead 的最短前缀
    const cuts: number[] = [];
    for (let k = 0; k < content.length; k++) if ("。！？!?；;".includes(content[k])) cuts.push(k + 1);
    cuts.push(content.length);
    const k = cuts.find((c) => plainOf(content.slice(0, c)) === lead);
    if (k === undefined || !cleanCut(content.slice(0, k))) return none;
    const restOfLine = content.slice(k);
    const start = offset + (restOfLine.trim() ? marker.length : 0);
    const end = restOfLine.trim() ? offset + marker.length + k : offset + rawLine.length;
    return { lead, body: text.slice(0, start) + text.slice(end) };
  }
  return none;
}

/** 关键数字（最多 3 个）：只认结构化字段 result.key_numbers = [{value, label}]。
 *  后端在 server 层确定性产出（app/server/key_numbers.py，phase76-u3u5.md §1.2）：数取自 result 原对象、并且和结论里的数字对得上，
 *  value 用结论里的原文写法，label 取自 result 的结构；前端仍不从结论正文里猜数字、猜口径。
 *  未核实的数字（unverified_numbers 里有的）不放大显示。 */
export type KeyNumber = { value: string; label: string };
export const KEY_NUMBERS_MAX = 3;
export function keyNumbers(t: Turn): KeyNumber[] {
  const raw = t.status === "ok" ? t.result?.key_numbers : undefined;
  if (!Array.isArray(raw)) return [];
  const bad = new Set(unverifiedOf(t));
  return raw
    .filter((x): x is KeyNumber => !!x && typeof x === "object"
      && typeof (x as KeyNumber).value === "string" && (x as KeyNumber).value.trim() !== ""
      && typeof (x as KeyNumber).label === "string" && (x as KeyNumber).label.trim() !== "")
    .filter((x) => !bad.has(x.value.trim()))
    .slice(0, KEY_NUMBERS_MAX)
    .map((x) => ({ value: x.value.trim(), label: x.label.trim() }));
}

/** 结果卡底部「换个口径」「补一张图」发出的追问：走现有提问链路（POST /sessions/{id}/messages），会话记忆把上一轮带上。 */
export const FOLLOW_UPS = {
  metric: "换个口径再算一次：先说明上一轮结论用的口径（统计范围、指标定义、时间粒度），再换一种合理的口径重新计算，并对比两种口径的结果差异。",
  chart: "给上一轮的结论补一张图：选最能说明这个结论的图型，用上一轮的结果画出来。",
} as const;

/** 能不能导出（POST /messages/{id}/export/*）：后端只收执行成功、带代码的助手消息（app.py export_source），前端照同一条件给按钮。 */
export function canExport(t: Turn): boolean {
  const r = t.result;
  return t.status === "ok" && !!r && r.executed === true && typeof r.code === "string" && r.code.trim() !== "";
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

/** 阶段 6.5：done 里 result.meta 记着这一轮用的连接名和模型；旧消息、取消 / 中断（没有 result）时 null。 */
export function turnMeta(t: Turn): { connection_name: string; model: string } | null {
  const m = (t.result as { meta?: unknown } | null | undefined)?.meta as { connection_name?: unknown; model?: unknown } | undefined;
  if (!m || typeof m.connection_name !== "string" || typeof m.model !== "string") return null;
  return { connection_name: m.connection_name, model: m.model };
}

/** 整轮耗时（秒）：done 里的 timings.total；没有就用首末事件的 ts 差。 */
export function totalSeconds(t: Turn): number | null {
  const tm = t.result?.timings as { total?: unknown } | undefined;
  if (tm && typeof tm.total === "number") return tm.total;
  const ts = t.events.map(tsOf).filter((x): x is number => x !== null);
  return ts.length >= 2 ? ts[ts.length - 1] - ts[0] : null;
}
