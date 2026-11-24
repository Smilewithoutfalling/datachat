import generated from "./generated/events.json";
import {
  answerText, emptyTurn, type Ev, isReplan, MESSAGE_STATUSES, MESSAGES, outcome, planLabel, plans, reduce, replay, settle, steps,
} from "./turn";
import type { Message } from "./types";

const plan: Ev = { type: "plan", seq: 0, data: { text: "计划" } };
const answer: Ev = { type: "answer", seq: 1, data: { text: "总销量 1685", forced: false } };
const fatalCancel: Ev = { type: "error", seq: 2, data: { message: MESSAGES.cancelled, kind: "cancelled", fatal: true } };
const okResult = { ok: true, answer: "总销量 1685", error: null, error_kind: null, warnings: [], charts: [] };
const msg = (over: Partial<Message>): Message => ({
  id: "a1", role: "assistant", content: "", status: "ok", created_at: "t", events: [plan, answer], result: okResult, ...over,
});

test("生成文件与前端约定一致：kind / status / 文案都来自后端", () => {
  expect(generated.error_kinds).toEqual(expect.arrayContaining(["cancelled", "interrupted"]));
  expect(MESSAGE_STATUSES).toEqual(["running", "ok", "error", "cancelled", "interrupted"]);
  expect(MESSAGES.cancelled).toBe("已取消");
});

test("reducer：按 seq 去重，未知类型忽略，done 只设 result", () => {
  let t = emptyTurn(true);
  t = reduce(t, plan);
  t = reduce(t, plan);
  t = reduce(t, { type: "mystery", seq: 9, data: {} } as unknown as Ev);
  expect(t.events).toEqual([plan]);
  t = reduce(t, { type: "done", seq: 3, data: { result: okResult } });
  expect(t.result).toEqual(okResult);
  expect(t.events).toEqual([plan]);
});

test("重放 ok：合成 done 取库里的 result，seq = max+1，结论来自 result", () => {
  const t = replay(msg({}));
  expect(outcome(t)).toEqual({ kind: "ok" });
  expect(answerText(t)).toBe("总销量 1685");
});

test("重放 cancelled：库里有 answer 事件也不出现（刷新后不出现），只显示已取消", () => {
  const t = replay(msg({ status: "cancelled", content: MESSAGES.cancelled, result: null, events: [plan, answer, fatalCancel] }));
  expect(outcome(t)).toEqual({ kind: "cancelled", unsavedAnswer: null });
  expect(answerText(t)).toBe("");
  expect(t.result?.error_kind).toBe("cancelled");
});

test("实时 cancelled：流里收到过 answer → 已取消（未保存）；status 以库为准，流里的 done 是 ok 也不算", () => {
  let t = emptyTurn(true);
  for (const ev of [plan, answer]) t = reduce(t, ev);
  t = reduce(t, { type: "done", seq: 2, data: { result: okResult } }); // late-cancel：流里是成功
  t = settle(t, msg({ status: "cancelled", content: MESSAGES.cancelled, result: null }));
  expect(outcome(t)).toEqual({ kind: "cancelled", unsavedAnswer: "总销量 1685" });
  expect(answerText(t)).toBe("");
  expect(t.result?.ok).toBe(false);
});

test("interrupted（重启、断开）：独立的终止原因，文案取库里的常量", () => {
  for (const content of [MESSAGES.interrupted, MESSAGES.disconnected]) {
    const t = replay(msg({ status: "interrupted", content, result: null, events: [plan] }));
    expect(outcome(t)).toEqual({ kind: "interrupted", message: content });
  }
});

test("error 没有 result（流异常 stream_aborted）：只显示 content；有 result 时带 error_kind", () => {
  expect(outcome(replay(msg({ status: "error", content: MESSAGES.stream_aborted, result: null })))).toEqual({
    kind: "error", errorKind: null, message: MESSAGES.stream_aborted,
  });
  const r = { ...okResult, ok: false, answer: "", error: "模型调用失败", error_kind: "llm" };
  expect(outcome(replay(msg({ status: "error", content: "模型调用失败", result: r })))).toEqual({
    kind: "error", errorKind: "llm", message: "模型调用失败",
  });
});

test("每个消息状态都有明确的终止原因分支（不落进默认分支）", () => {
  const kinds = MESSAGE_STATUSES.map((s) => outcome(replay(msg({ status: s, result: s === "ok" ? okResult : null }))).kind);
  expect(kinds).toEqual(["running", "ok", "error", "cancelled", "interrupted"]);
});

// ---------------------------------------------------------------- 阶段 7.5 第 3 步：replan 两版计划
describe("replan：第二个 plan 事件（source=replan）", () => {
  const replanEv: Ev = { type: "plan", seq: 5, data: { text: "换一种思路", source: "replan" } };
  const code = (seq: number, source = "codegen", attempt = 0): Ev => ({ type: "code", seq, data: { code: "x", source, attempt } });
  const exec = (seq: number, ok: boolean): Ev =>
    ({ type: "exec", seq, data: { ok, result_text: "", error: ok ? null : "KeyError", duration_s: 0.1 } }) as Ev;
  const events: Ev[] = [plan, code(1), exec(2, false), code(3, "reviewer", 1), exec(4, false), replanEv, code(6), exec(7, true)];

  test("plans() 按顺序给出两版，第二版标「重新规划」", () => {
    let t = emptyTurn(true);
    for (const e of events) t = reduce(t, e);
    expect(plans(t)).toEqual([
      { text: "计划", label: "分析计划", replan: false },
      { text: "换一种思路", label: "重新规划", replan: true },
    ]);
    expect(isReplan(replanEv)).toBe(true);
    expect(isReplan(plan)).toBe(false);
    expect(planLabel(plan)).toBe("分析计划");
    expect(planLabel(replanEv)).toBe("重新规划");
  });

  test("步骤条：「理解问题」计数 2，replan 之后顺延到写代码（不新增段）", () => {
    let t = emptyTurn(true);
    for (const e of events.slice(0, 6)) t = reduce(t, e);
    const s = steps(t, "workflow");
    expect(s.map((x) => x.key)).toEqual(["plan", "code", "exec", "answer"]);
    expect(s.find((x) => x.key === "plan")?.count).toBe(2);
    expect(s.find((x) => x.key === "code")?.state).toBe("running");
  });

  test("没有 replan 的轮次：一版计划，标题不变", () => {
    let t = emptyTurn(true);
    t = reduce(t, plan);
    expect(plans(t)).toEqual([{ text: "计划", label: "分析计划", replan: false }]);
  });
});
