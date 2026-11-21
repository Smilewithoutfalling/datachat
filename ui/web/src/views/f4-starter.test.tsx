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

test("f4 U4 首页结构：问候 → 数据资产 → 三张提问卡，卡面文字和顺序照验收", async () => {
  setup();
  const home = await screen.findByTestId("starter-home");
  const hello = within(home).getByRole("heading", { level: 2 });
  const asset = within(home).getByTestId("starter-asset");
  const cards = within(home).getByRole("list", { name: "提问卡" });
  // DOM 顺序即视觉顺序
  expect(hello.compareDocumentPosition(asset) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(asset.compareDocumentPosition(cards) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(["早上好", "中午好", "下午好", "晚上好"]).toContain(hello.textContent);
  expect(within(cards).getAllByRole("button").map((b) => b.querySelector(".starter-card-title")?.textContent))
    .toEqual(["看看这份数据有什么", "找出异常值", "两期对比"]);
  expect(within(asset).getByTestId("starter-asset-name").textContent).toBe("门店"); // 列表按创建时间倒序，取最前面（刚上传的）那个
  await act(async () => fireEvent.click(within(asset).getByRole("button", { name: "打开数据集「门店」" })));
  expect(await screen.findByTestId("dataset-view")).toBeTruthy(); // 「打开」真实进数据集页
  expect(screen.queryByText("拖入文件到此处")).toBeNull(); // 有数据集时不再是上传大卡
});

test("f4 U4 没有数据集时首页照旧是上传大卡，不出提问卡", async () => {
  setup({ datasets: [] });
  expect(await screen.findByText("拖入文件到此处")).toBeTruthy();
  expect(screen.queryByTestId("starter-home")).toBeNull();
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

test("f4 U4 资产区：没有概要时写明并给「剖析」，「剖析」真实发出 GET /datasets/{id}，回来后数字都来自 profile", async () => {
  const { be } = setup();
  const asset = await screen.findByTestId("starter-asset");
  expect(within(asset).getByTestId("starter-asset-line").textContent).toBe("1 个表 · 还没读取概要");
  await act(async () => fireEvent.click(within(asset).getByRole("button", { name: "剖析" })));
  expect(be.calls.filter((x) => x.method === "GET" && x.path.startsWith("/datasets/d1")).map((x) => x.path)).toEqual(["/datasets/d1"]);
  await waitFor(() => expect(within(asset).getByTestId("starter-asset-line").textContent).toBe("1 个表 · 5 行 · 4 列 · 3 列有缺失"));
  expect(asset.textContent).toContain("2023-12-28 ~ 2024-03-31");
});

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
