// F4 迭代 V2a（phase5 §10 验收）：状态标签、步骤条、部分完成、错误卡分级、未配置 Key 拦截、重名数据集、上传拦截。
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { Api } from "../api";
import { client } from "../client";
import { fakeBackend } from "../fakeBackend";
import { type Ev, partialSignals, steps, type Turn } from "../turn";
import type { Message } from "../types";
import { SessionView } from "./SessionView";
import { Shell } from "./Shell";
import { TurnView } from "./TurnView";

const ev = (type: string, seq: number, data: Record<string, unknown>, ts = 100 + seq): Ev =>
  ({ type, seq, ts, data }) as unknown as Ev;
const OK = { ok: true, answer: "结论", error: null, error_kind: null, warnings: [], charts: [] };
const turn = (status: string, events: Ev[], result: Record<string, unknown> | null = null, live = false): Turn =>
  ({ status, events, result, live }) as unknown as Turn;
const badge = () => screen.getByTestId("turn-badge");

describe("状态标签 6 态（只按 outcome 分支）", () => {
  const cases: [string, Turn, string, string][] = [
    ["running", turn("running", []), "running", "分析中"],
    ["ok", turn("ok", [], OK), "ok", "已完成"],
    ["partial", turn("ok", [], { ...OK, warnings: ["图表未生成"] }), "partial", "部分完成"],
    ["error", turn("error", [], { ...OK, ok: false, error: "x", error_kind: "agent" }), "error", "失败"],
    ["cancelled", turn("cancelled", [], { ...OK, ok: false, error_kind: "cancelled" }), "cancelled", "已取消"],
    ["interrupted", turn("interrupted", [], { ...OK, ok: false, error_kind: "interrupted" }), "interrupted", "已中断"],
  ];
  test.each(cases)("%s", (_, t, cls, text) => {
    render(<TurnView turn={t} />);
    expect(badge().className).toBe(`badge ${cls}`);
    expect(badge().textContent).toBe(text);
  });
  test("running + stopping → 停止中，说明当前这一步结束后生效（不承诺秒数）", () => {
    render(<TurnView turn={turn("running", [])} stopping />);
    expect(badge().textContent).toBe("停止中");
    expect(screen.getByText("已发送停止，当前这一步结束后生效。")).toBeTruthy();
  });
});

describe("步骤条分段", () => {
  const states = (t: Turn, agent?: string) => steps(t, agent).map((s) => `${s.key}:${s.state}${s.count > 1 ? `x${s.count}` : ""}`);
  test("工作流：一个事件都没收到时理解问题在跑", () => {
    expect(states(turn("running", []), "workflow")).toEqual(["plan:running", "code:pending", "exec:pending", "answer:pending"]);
  });
  test("工作流：修复重试 → 写代码 ×2、执行 ×2；执行失败后回到写代码", () => {
    const evs = [ev("plan", 0, { text: "p" }), ev("code", 1, { code: "a" }), ev("exec", 2, { ok: false, duration_s: 0.1 })];
    expect(states(turn("running", evs), "workflow")).toEqual(["plan:done", "code:running", "exec:done", "answer:pending"]);
    const more = [...evs, ev("code", 3, { code: "b" }), ev("exec", 4, { ok: true, duration_s: 0.2 }), ev("answer", 5, { text: "x" })];
    expect(states(turn("ok", more, OK), "workflow")).toEqual(["plan:done", "code:donex2", "exec:donex2", "answer:done"]);
    const exec = steps(turn("ok", more, OK), "workflow").find((s) => s.key === "exec")!;
    expect(exec.seconds).toBeCloseTo(0.3); // 执行段用 duration_s 之和
  });
  test("ReAct 没有计划：不出理解问题这一段", () => {
    const evs = [ev("code", 0, { code: "a" }), ev("exec", 1, { ok: true, duration_s: 0.1 })];
    expect(states(turn("running", evs), "react")).toEqual(["code:done", "exec:done", "answer:running"]);
  });
  test("出错：下一段标失败；代码执行失败标在执行段", () => {
    expect(states(turn("error", [], { ...OK, error_kind: "llm" }), "workflow")).toEqual(["plan:failed", "code:pending", "exec:pending", "answer:pending"]); // 验收 r3 #4：没走到的段保留（灰），步骤条长度一致
    const evs = [ev("plan", 0, {}), ev("code", 1, {}), ev("exec", 2, { ok: false })];
    expect(states(turn("error", evs, { ...OK, error_kind: "execution" }), "workflow")).toEqual(["plan:done", "code:failed", "exec:failed", "answer:pending"]);
  });
  test("停止：停在哪一段，那一段标已中断", () => {
    const evs = [ev("plan", 0, {})];
    expect(states(turn("cancelled", evs, { ...OK, error_kind: "cancelled" }), "workflow")).toEqual(["plan:done", "code:stopped", "exec:pending", "answer:pending"]);
  });
});

describe("部分完成的信号", () => {
  test("warnings、unverified_numbers、字典读取失败各算一条；ReAct 的重跑提示不算", () => {
    const t = turn("ok", [
      ev("error", 0, { message: "数据字典读取失败，已跳过", kind: "dataset", fatal: false }),
      ev("error", 1, { message: "重跑本轮：…", kind: "llm", fatal: false, llm_kind: "gateway_error" }),
    ], { ...OK, warnings: ["图表未生成"], unverified_numbers: ["42"] });
    expect(partialSignals(t)).toEqual(["数据字典读取失败，已跳过", "图表未生成", "结论里这些数字在执行结果中没找到，请核对：42"]);
  });
  test("都没有时不出黄条", () => {
    render(<TurnView turn={turn("ok", [], OK)} />);
    expect(document.querySelector(".wbar")).toBeNull();
  });
  test("多条时第一条做标题，其余收在「还有 N 条」里", () => {
    render(<TurnView turn={turn("ok", [], { ...OK, warnings: ["一", "二", "三"] })} />);
    expect(document.querySelector(".wbar-title")?.textContent).toBe("一");
    expect(screen.queryByText("二")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "还有 2 条" }));
    expect(screen.getByText("二")).toBeTruthy();
  });
});

describe("错误卡：error_kind 4 类，llm 再按 llm_kind 分出口", () => {
  const err = (error_kind: string, llm_kind: string | null = null) =>
    turn("error", [], { ...OK, ok: false, error: "详情", error_kind, llm_kind });
  // 出口按钮（不含「技术详情」这个折叠开关）
  const names = () => within(screen.getByRole("alert")).queryAllByRole("button").map((b) => b.textContent).filter((t) => t !== "技术详情");
  test("正文只放建议和编号，后端原文收进「技术详情」（验收 P1-2/3）", () => {
    const t = turn("error", [], { ...OK, ok: false, error: "请求太频繁，被限流，共尝试 1 次：[fake_llm] 按场景返回 429（编号 abcdef12）",
      error_kind: "llm", llm_kind: "server" });
    render(<TurnView turn={t} messageId="abcdef1234567890" {...act} />);
    expect(document.querySelector(".errcard-detail")?.textContent).toBe("通常是临时的，可以重试。（编号 abcdef12）");
    expect(document.querySelector(".errcard-detail")?.textContent).not.toContain("fake_llm");
    expect((document.querySelector(".errcard .tech-body") as HTMLElement).hidden).toBe(true); // 默认收起
    fireEvent.click(screen.getByRole("button", { name: "技术详情" }));
    expect((document.querySelector(".errcard .tech-body") as HTMLElement).hidden).toBe(false);
    expect(document.querySelector(".errcard .tech-body")?.textContent).toContain("[fake_llm]");
  });
  const act = { onRetry: () => {}, onRephrase: () => {}, onGoSettings: () => {} };
  test.each([
    ["llm", "server", "模型服务出错了", ["重试"]],
    ["llm", "http_502", "模型服务出错了", ["重试"]],
    ["llm", "timeout", "模型服务响应超时", ["重试"]],
    ["llm", "connection", "连不上模型服务", ["重试"]],
    ["llm", "auth", "模型服务不认这个 API Key", ["去设置"]],
    ["llm", "no_key", "还没有配置 API Key", ["去设置"]],
    ["llm", "bad_request", "模型服务拒绝了这次请求", ["重试", "换个问法"]],
    ["llm", "http_409", "模型服务拒绝了这次请求", ["重试", "换个问法"]],
    ["llm", "gateway_error", "模型调用失败", ["重试"]],
    ["llm", null, "模型调用失败", ["重试"]], // 旧记录没有 llm_kind
    ["execution", null, "代码没跑通", ["重试", "换个问法"]],
    ["dataset", null, "数据读取失败", ["重试"]],
    ["agent", null, "分析流程出错", ["重试"]],
  ] as const)("%s / %s", (kind, lk, title, buttons) => {
    render(<TurnView turn={err(kind, lk)} {...act} />);
    expect(document.querySelector(".errcard-title")?.textContent).toBe(title);
    expect(names()).toEqual(buttons);
  });
  test("rate_limit：按钮先置灰倒计时，结束后可点", () => {
    vi.useFakeTimers();
    try {
      render(<TurnView turn={err("llm", "rate_limit")} {...act} />);
      const b = within(screen.getByRole("alert")).getByRole("button", { name: /重试/ }) as HTMLButtonElement;
      expect(b.disabled).toBe(true);
      expect(b.textContent).toBe("10 秒后可重试");
      for (let i = 0; i < 10; i++) act_(() => vi.advanceTimersByTime(1000));
      expect(b.disabled).toBe(false);
      expect(b.textContent).toBe("稍后再试");
    } finally {
      vi.useRealTimers();
    }
  });
});
const act_ = (fn: () => void) => act(fn);

const SESSION = { id: "s1", dataset_id: "d1", agent: "workflow", title: "t", created_at: "t", updated_at: "t" };
test("未配置 Key：横幅常显；点发送前端拦下，不发请求", async () => {
  const be = fakeBackend({ "GET /sessions/s1": { ...SESSION, messages: [] as Message[] } });
  render(<SessionView c={client(new Api("t", be.fetchImpl))} id="s1" datasetName="销量" keyConfigured={false} onGoSettings={() => {}}
    onChanged={() => {}} onDeleted={() => {}} />);
  await screen.findByText("还没有消息");
  expect(screen.getByTestId("key-banner").textContent).toContain("未配置模型凭证");
  fireEvent.change(screen.getByLabelText("提问"), { target: { value: "q" } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(screen.getByTestId("key-banner").textContent).toContain("这次提问没有发出");
  expect(be.calls.some((c) => c.method === "POST")).toBe(false);
});

const shell = (datasets: unknown[]) => {
  const be = fakeBackend({ "GET /datasets": datasets, "GET /sessions": [], "GET /settings/api-key": { configured: true, source: "keyring" } });
  render(<Shell c={client(new Api("t", be.fetchImpl))} initialKey={{ configured: true, source: "keyring" }} />);
  return be;
};

test("重名数据集：名称后追加创建时间，只改显示", async () => {
  const today = new Date();
  today.setHours(10, 42, 0, 0);
  const f = [{ filename: "sales.csv", size: 10, sha256: "h" }];
  shell([
    { id: "a", name: "sales.csv", created_at: today.toISOString(), files: f },
    { id: "b", name: "sales.csv", created_at: "2026-10-01T02:00:00Z", files: f },
    { id: "c", name: "warm.csv", created_at: today.toISOString(), files: f },
  ]);
  const nav = await screen.findByRole("navigation", { name: "数据集" });
  await within(nav).findByText("sales.csv · 10:42");
  expect(within(nav).getByText(/^sales\.csv · 10月1日$/)).toBeTruthy();
  expect(within(nav).getByText("warm.csv")).toBeTruthy();
});

test("上传区：非 .csv 前端拦下，不发请求", async () => {
  const be = shell([]);
  const file = new File(["x"], "a.xlsx");
  fireEvent.change(await screen.findByLabelText("选择 CSV 文件"), { target: { files: [file] } });
  expect(screen.getByRole("alert").textContent).toBe("只支持 .csv；a.xlsx 不支持");
  expect(screen.queryByRole("button", { name: "上传" })).toBeNull();
  expect(be.calls.some((c) => c.method === "POST")).toBe(false);
});
