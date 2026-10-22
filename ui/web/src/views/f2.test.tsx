import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import pkg from "../../package.json";
import { Api } from "../api";
import { client } from "../client";
import { fakeBackend, sseStream } from "../fakeBackend";
import { MESSAGES } from "../turn";
import type { Message } from "../types";
import { Markdown } from "./Markdown";
import { SessionView } from "./SessionView";

const INJECT = '<img src=x onerror="window.__pwned=1">';
const SESSION = { id: "s1", dataset_id: "d1", agent: "workflow", title: "t", created_at: "t", updated_at: "t" };
const OK = { ok: true, answer: "总销量 **1685**", error: null, error_kind: null, warnings: ["步数用完后强制收尾"], charts: [] };
const user = (id: string, content: string): Message => ({ id, role: "user", content, status: "ok", created_at: "t" });

function mount(routes: Record<string, unknown>) {
  const be = fakeBackend(routes);
  render(<SessionView c={client(new Api("t", be.fetchImpl))} id="s1" datasetName="销量" onChanged={() => {}} onDeleted={() => {}} />);
  return be;
}

afterEach(() => {
  delete (window as unknown as { __pwned?: number }).__pwned;
});

test("提问：事件实时渲染（计划、折叠代码、执行），结论 markdown；结束后按库里的 status 收尾，出现 👍👎", async () => {
  const sse = sseStream("a1");
  let messages: Message[] = [];
  const be = mount({
    "GET /sessions/s1": () => ({ ...SESSION, messages }),
    "POST /sessions/s1/messages": () => sse.response(),
  });
  await screen.findByText("还没有消息");
  fireEvent.change(screen.getByLabelText("提问"), { target: { value: "总销量？" } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  const liveMsg = await screen.findByTestId("live-msg");
  await act(async () => sse.push("plan", { text: `计划 ${INJECT}` }));
  fireEvent.click(within(liveMsg).getByRole("button", { name: "查看过程" })); // V2a §2.3：过程默认折叠在步骤条里
  await within(liveMsg).findByText(`计划 ${INJECT}`);
  await act(async () => sse.push("code", { code: "result = df['units'].sum()", source: "codegen", attempt: 0 }));
  await act(async () => sse.push("exec", { ok: true, result_text: "1685", error: null, duration_s: 0.2, chart: null }));
  const code = await within(liveMsg).findByText("生成代码");
  expect(code.closest("details")?.open).toBe(false); // 代码默认折叠
  expect((screen.getByRole("button", { name: "停止" }) as HTMLButtonElement).disabled).toBe(false); // V2a §1.8：停止在输入区
  await act(async () => sse.push("answer", { text: OK.answer, forced: false }));
  messages = [user("u1", "总销量？"), { id: "a1", role: "assistant", content: "总销量 1685", status: "ok", created_at: "t",
    events: [], result: OK, feedback: null }];
  await act(async () => (sse.push("done", { result: OK }), sse.end()));
  const a = await screen.findByTestId("assistant-msg");
  expect(screen.queryByTestId("live-msg")).toBeNull();
  expect(within(a).getByText("1685", { selector: "strong" })).toBeTruthy(); // markdown
  expect(within(a).getByText("步数用完后强制收尾")).toBeTruthy();
  expect(within(a).getByRole("button", { name: "有用" })).toBeTruthy();
  expect(be.calls.find((c) => c.method === "POST")?.body).toEqual({ content: "总销量？" });
  expect(document.querySelector("img")).toBeNull();
});

test("停止：先等 cancel 返回、不断开流；流里收到过 answer 但库里是 cancelled → 已取消（未保存）；重放后不出现", async () => {
  const sse = sseStream("a1");
  const order: string[] = [];
  let messages: Message[] = [];
  const be = mount({
    "GET /sessions/s1": () => ({ ...SESSION, messages }),
    "POST /sessions/s1/messages": () => sse.response(),
    "POST /messages/a1/cancel": () => (order.push("cancel"), { id: "a1", status: "cancelled" }),
  });
  await screen.findByText("还没有消息");
  fireEvent.change(screen.getByLabelText("提问"), { target: { value: "q" } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  const liveMsg = await screen.findByTestId("live-msg");
  await act(async () => sse.push("plan", { text: "计划" }));
  await act(async () => sse.push("answer", { text: "结论原文", forced: false }));
  expect(liveMsg).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "停止" })); // V2a §1.8：停止在输入区
  await waitFor(() => expect(order).toEqual(["cancel"]));
  expect(screen.getByTestId("live-msg")).toBeTruthy(); // 没断开，流还在
  const cancelled: Message = { id: "a1", role: "assistant", content: MESSAGES.cancelled, status: "cancelled", created_at: "t",
    result: null, events: [{ type: "plan", seq: 0, data: { text: "计划" } }, { type: "answer", seq: 1, data: { text: "结论原文", forced: false } }] };
  messages = [user("u1", "q"), cancelled];
  await act(async () => {
    sse.push("error", { message: MESSAGES.cancelled, kind: "cancelled", fatal: true });
    sse.push("done", { result: { ...OK, ok: false, error: MESSAGES.cancelled, error_kind: "cancelled" } });
    sse.end();
  });
  const unsaved = await screen.findByTestId("unsaved-answer");
  expect(unsaved.textContent).toContain("已取消（未保存）");
  expect(unsaved.textContent).toContain("结论原文");
  expect(screen.queryByRole("button", { name: "有用" })).toBeNull();
  expect(be.calls.filter((c) => c.path.includes("/cancel"))).toHaveLength(1);
});

test("重放：cancelled 不显示结论；interrupted 给重试，重试发同一个问题；error 带失败类型，致命 error 不重复", async () => {
  const sse = sseStream("a9");
  const be = mount({
    "GET /sessions/s1": {
      ...SESSION,
      messages: [
        user("u1", "问一"),
        { id: "a1", role: "assistant", content: MESSAGES.cancelled, status: "cancelled", created_at: "t", result: null,
          events: [{ type: "answer", seq: 0, data: { text: "不该出现的结论", forced: false } }] },
        user("u2", "问二"),
        { id: "a2", role: "assistant", content: "数据集读取失败", status: "error", created_at: "t",
          result: { ...OK, ok: false, answer: "", error: "数据集读取失败", error_kind: "dataset", warnings: [] },
          events: [{ type: "error", seq: 0, data: { message: "数据集读取失败", kind: "dataset", fatal: true } }] },
        user("u3", "问三"),
        { id: "a3", role: "assistant", content: MESSAGES.interrupted, status: "interrupted", created_at: "t", result: null, events: [] },
      ],
    },
    "POST /sessions/s1/messages": () => sse.response(),
  });
  const msgs = await screen.findAllByTestId("assistant-msg");
  expect(screen.queryByText("不该出现的结论")).toBeNull();
  expect(within(msgs[0]).getByText(MESSAGES.cancelled, { selector: ".outcome" })).toBeTruthy();
  expect(within(msgs[1]).getAllByText(/数据集读取失败/)).toHaveLength(1); // 致命 error 事件不重复画，只在终止原因里出现一次
  // V2a §3.3：错误卡标题和详情分两行，不再是「数据集失败：…」一行
  expect(within(msgs[1]).getByRole("alert").querySelector(".errcard-title")?.textContent).toBe("数据读取失败");
  expect(within(msgs[1]).getByRole("alert").querySelector(".errcard-detail")?.textContent).toBe("数据集读取失败");
  expect(within(msgs[2]).getByRole("status").textContent).toContain(MESSAGES.interrupted);
  fireEvent.click(within(msgs[2]).getByRole("button", { name: "重新问一次" })); // V2a §3.4：中断的出口改名，行为不变
  await waitFor(() => expect(be.calls.find((c) => c.method === "POST")?.body).toEqual({ content: "问三" }));
  sse.end();
});

test("提问被拒（409）：显示错误，不留下实时气泡", async () => {
  mount({
    "GET /sessions/s1": { ...SESSION, messages: [] },
    "POST /sessions/s1/messages": () =>
      new Response(JSON.stringify({ detail: "这个会话还有一条消息在分析中" }), { status: 409 }),
  });
  await screen.findByText("还没有消息");
  fireEvent.change(screen.getByLabelText("提问"), { target: { value: "q" } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  expect((await screen.findByRole("alert")).textContent).toContain("409");
  expect(screen.queryByTestId("live-msg")).toBeNull();
});

test("👍👎：再点同一个取消（rating=null）；补充说明按文本渲染", async () => {
  const be = mount({
    "GET /sessions/s1": {
      ...SESSION,
      messages: [user("u1", "q"), { id: "a1", role: "assistant", content: "x", status: "ok", created_at: "t", result: OK, events: [],
        feedback: { rating: "down", note: INJECT } }],
    },
    "PUT /messages/a1/feedback": (b: unknown) => ({ message_id: "a1", ...(b as object) }),
  });
  const down = await screen.findByRole("button", { name: "没用" });
  expect(down.getAttribute("aria-pressed")).toBe("true");
  expect((screen.getByLabelText("补充说明") as HTMLInputElement).value).toBe(INJECT);
  fireEvent.click(screen.getByRole("button", { name: "有用" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "有用" }).getAttribute("aria-pressed")).toBe("true"));
  fireEvent.click(screen.getByRole("button", { name: "有用" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "有用" }).getAttribute("aria-pressed")).toBe("false"));
  expect(be.calls.filter((c) => c.method === "PUT").map((c) => c.body)).toEqual([
    { rating: "up", note: INJECT },
    { rating: null, note: INJECT },
  ]);
  expect(document.querySelector("img")).toBeNull();
});

test("markdown：版本钉住；不渲染 raw HTML；javascript: 链接被过滤；链接新标签页 + noreferrer noopener", () => {
  expect(pkg.dependencies["react-markdown"]).toBe("10.1.0");
  expect(pkg.dependencies["remark-gfm"]).toBe("4.0.1");
  render(<Markdown text={`${INJECT}\n\n[点我](javascript:window.__pwned=1) [官网](https://example.com)\n\n| a | b |\n|---|---|\n| 1 | 2 |`} />);
  expect(document.querySelector("img")).toBeNull();
  expect(screen.getByText(INJECT, { exact: false })).toBeTruthy();
  // 验收 P0-4：危险协议的链接只留文字，不再是 <a>（原来是去掉 href 的 <a>，样式上仍像链接）
  const bad = screen.getByText("点我");
  expect(bad.closest("a")).toBeNull();
  const good = screen.getByText("官网").closest("a")!;
  expect(good.getAttribute("href")).toBe("https://example.com");
  expect(good.getAttribute("target")).toBe("_blank");
  expect(good.getAttribute("rel")).toBe("noreferrer noopener");
  expect(document.querySelector("table")).not.toBeNull(); // remark-gfm
  fireEvent.click(bad);
  expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
});
