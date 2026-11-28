// 阶段 7.6 U4 空态卡（docs/roadmap/phase76-ui.md §2 U4、§2.1）：有数据集时首页是「问候 → 数据资产 → 三张提问卡」；
// 三张卡点了都真实发出一句提问：POST /sessions 建会话，再走现有的 POST /sessions/{id}/messages（E1）。
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Api } from "../api";
import { client } from "../client";
import { fakeBackend, sseStream } from "../fakeBackend";
import fx from "../fixtures/asset_card.json";
import type { DatasetProfile, KeyStatus } from "../types";
import { SessionView } from "./SessionView";
import { Shell } from "./Shell";
import { assetLine, greeting, STARTERS } from "./StarterCards";

const PROFILE = fx.profile as DatasetProfile;
const DS = { id: "d1", name: "门店", created_at: "t", files: [{ filename: fx.filename, size: 128, sha256: "h" }] };
const OLD = { id: "d0", name: "旧表", created_at: "t0", files: [{ filename: "old.csv", size: 1, sha256: "o" }] };
const SESSION = { id: "s9", dataset_id: "d1", agent: "workflow", title: "", created_at: "t", updated_at: "t" };
const KEY: KeyStatus = { configured: true, source: "keyring" } as KeyStatus;

type Wrap = (f: typeof fetch) => typeof fetch;
function setup({ key = KEY, datasets = [DS, OLD], routes = {}, wrap = (f) => f }: { key?: KeyStatus; datasets?: unknown[]; routes?: Record<string, unknown>; wrap?: Wrap } = {}) {
  const sse = sseStream("m1");
  const be = fakeBackend({
    "GET /datasets": datasets,
    "GET /sessions": [],
    "GET /datasets/d1": { ...DS, summary: "5 行 × 4 列", tables: { df: ["日期", "地区", "销量", "备注"] }, profile: PROFILE },
    "GET /settings/api-key": key,
    "POST /sessions": SESSION,
    "GET /sessions/s9": { ...SESSION, messages: [] },
    "POST /sessions/s9/messages": () => sse.response(),
    ...routes,
  });
  render(<Shell c={client(new Api("t", wrap(be.fetchImpl)))} initialKey={key} desktop={false} />);
  return { be, sse };
}

test("首页结构（原型 GenieHome）：问候 → 提问框 → 推荐问题三张卡 → 最近对话 / 数据集，卡面文字和顺序照 STARTERS", async () => {
  setup();
  const home = await screen.findByTestId("genie-home");
  const hello = within(home).getByRole("heading", { level: 2 });
  const box = within(home).getByLabelText("提问");
  const cards = within(home).getByRole("region", { name: "推荐问题" });
  expect(hello.compareDocumentPosition(box) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(box.compareDocumentPosition(cards) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(hello.textContent).toMatch(/^(早上好|中午好|下午好|晚上好)，今天想分析什么？$/);
  expect(within(cards).getAllByRole("button").map((b) => b.querySelector(".g-card-title")?.textContent))
    .toEqual(STARTERS.map((x) => x.title));
  // 框内选数据集：默认最新（列表按创建时间倒序，取最前面）
  expect((within(home).getByRole("combobox", { name: "数据集" }) as HTMLSelectElement).value).toBe("d1");
  const dsSec = within(home).getByRole("region", { name: "数据集" });
  await act(async () => fireEvent.click(within(dsSec).getByRole("button", { name: /门店/ })));
  expect(await screen.findByTestId("dataset-view")).toBeTruthy(); // 真实进数据集页
  expect(screen.queryByText("拖入文件到此处")).toBeNull();
});

test("f4 U4 没有数据集时首页照旧是上传大卡，不出提问卡", async () => {
  setup({ datasets: [] });
  expect(await screen.findByText("拖入文件到此处")).toBeTruthy();
  expect(screen.queryByRole("region", { name: "推荐问题" })).toBeNull();
});

for (const [i, s] of STARTERS.entries()) {
  test(`f4 U4 点「${s.title}」：POST /sessions（这个数据集、标准模式）后真实发出这句提问，进入会话、出现一轮对话`, async () => {
    const { be, sse } = setup();
    const card = await screen.findByTestId(`starter-${s.id}`);
    await act(async () => fireEvent.click(card));
    const sv = await screen.findByTestId("session-view");
    await waitFor(() => expect(be.calls.some((x) => x.method === "POST" && x.path === "/sessions/s9/messages")).toBe(true));
    const posts = be.calls.filter((x) => x.method === "POST");
    expect(posts.map((x) => x.path)).toEqual(["/sessions", "/sessions/s9/messages"]);
    expect(posts[0].body).toEqual({ dataset_id: "d1", agent: "workflow" });
    expect(posts[1].body).toEqual({ content: STARTERS[i].question });
    // 这一轮已经在页面上：用户气泡是这句话，助手位是实时那一条
    expect(within(sv).getByText(s.question)).toBeTruthy();
    expect(within(sv).getByTestId("live-msg")).toBeTruthy();
    await act(async () => sse.end());
  });
}

test("f4 U4 三句提问互不相同，且都点名了卡面的事", () => {
  expect(new Set(STARTERS.map((s) => s.question)).size).toBe(3);
  expect(STARTERS[0].question).toContain("有什么");
  expect(STARTERS[1].question).toContain("异常值");
  expect(STARTERS[2].question).toContain("两期对比");
});

test("f4 U4 只发一次：回到首页再进同一个会话，不会重复提问", async () => {
  const { be, sse } = setup();
  const card = await screen.findByTestId("starter-outliers");
  await act(async () => fireEvent.click(card));
  await waitFor(() => expect(be.calls.filter((x) => x.path === "/sessions/s9/messages").length).toBe(1));
  await act(async () => sse.end());
  // 侧栏的会话行重新打开它
  const row = await screen.findByRole("button", { name: /未命名会话|找出这份数据/ });
  await act(async () => fireEvent.click(row));
  await screen.findByTestId("session-view");
  await new Promise((r) => setTimeout(r, 20));
  expect(be.calls.filter((x) => x.path === "/sessions/s9/messages").length).toBe(1);
});

test("f4 U4 没配凭证：SessionView 不发 messages 请求，问题放进输入框并提示（与手动发送同一规矩）", async () => {
  const be = fakeBackend({ "GET /sessions/s9": { ...SESSION, messages: [] } });
  const asked = vi.fn();
  render(<SessionView c={client(new Api("t", be.fetchImpl))} id="s9" datasetName="门店" keyConfigured={false}
    initialQuestion={STARTERS[1].question} onInitialAsked={asked} onChanged={() => {}} onDeleted={() => {}} />);
  const sv = await screen.findByTestId("session-view");
  await waitFor(() => expect((within(sv).getByLabelText("提问") as HTMLTextAreaElement).value).toBe(STARTERS[1].question));
  expect(asked).toHaveBeenCalledTimes(1);
  expect(within(sv).getByTestId("key-banner")).toBeTruthy();
  expect(be.calls.some((x) => x.method === "POST")).toBe(false);
});

// 原型：「剖析」从首页资产区移到了「数据集」页的卡片上，由 u2-asset-card.test.tsx 覆盖。

test("f4 U4 建会话中三张卡一起禁用，连点只建一个会话", async () => {
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  // POST /sessions 先压住不回（fakeBackend 的路由是同步的，这里在外面包一层）
  let creates = 0;
  const wrap: Wrap = (f) => (async (input, init) => {
    if (init?.method === "POST" && String(input).endsWith("/sessions")) {
      creates++;
      await gate;
    }
    return f(input, init);
  }) as typeof fetch;
  setup({ wrap });
  const a = await screen.findByTestId("starter-overview");
  await act(async () => fireEvent.click(a));
  for (const s of STARTERS) expect((screen.getByTestId(`starter-${s.id}`) as HTMLButtonElement).disabled).toBe(true);
  await act(async () => fireEvent.click(screen.getByTestId("starter-compare")));
  expect(creates).toBe(1);
  await act(async () => (release(), gate));
  await screen.findByTestId("session-view");
});

test("f4 U4 greeting 按本地时段；assetLine 千分位、无缺失列", () => {
  const at = (h: number) => new Date(2026, 10, 21, h, 0, 0);
  expect([2, 6, 11, 14, 19].map((h) => greeting(at(h)))).toEqual(["晚上好", "早上好", "中午好", "下午好", "晚上好"]);
  expect(assetLine({ table_count: 3, rows: 1234567, columns: 21, missing_columns: 0, time_range: null, tables: [] }))
    .toBe(`3 个表 · ${(1234567).toLocaleString()} 行 · 21 列 · 无缺失列`);
});
