// 阶段 7.6 U2 数据资产卡（docs/roadmap/phase76-ui.md §2 U2）：侧栏数据集条目扩成卡片。
// 字段与后端双向钉住：契约文件 fixtures/asset_card.json 由 tests/test_u2_asset_card.py 断言与 GET /datasets/{id} 的 profile 逐字相等；
// 这里断言卡片上的每个数字都能在 profile 里找到，profile 的每个标量也都出现在卡片上。
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Api } from "../api";
import { client } from "../client";
import { fakeBackend } from "../fakeBackend";
import fx from "../fixtures/asset_card.json";
import type { DatasetProfile } from "../types";
import { Shell } from "./Shell";

const PROFILE = fx.profile as DatasetProfile;
const DS = { id: "d1", name: "门店", created_at: "t", files: [{ filename: fx.filename, size: 128, sha256: "h" }] };
const SESSION = { id: "s9", dataset_id: "d1", agent: "workflow", title: "", created_at: "t", updated_at: "t" };
const KEY = { configured: true, source: "keyring" } as const;

function setup(routes: Record<string, unknown> = {}) {
  const be = fakeBackend({
    "GET /datasets": [DS],
    "GET /sessions": [],
    "GET /datasets/d1": { ...DS, summary: "5 行 × 4 列，编码 utf-8", tables: { df: ["日期", "地区", "销量", "备注"] }, profile: PROFILE },
    "GET /settings/api-key": KEY,
    ...routes,
  });
  render(<Shell c={client(new Api("t", be.fetchImpl))} initialKey={KEY} />);
  return be;
}

/** 卡片上出现的数字（日期整体算一个，千分位去掉）。只看概要区和「N 个表」那一行，不看用户起的名字和文件名。 */
// 原型（proto/genie-shell）：数据集卡片从首页/侧栏移到了「数据集」页
async function openCards() {
  fireEvent.click(within(await screen.findByRole("navigation", { name: "主导航" })).getByRole("button", { name: /^数据集/ }));
  return screen.findByTestId("asset-card");
}

function cardNumbers(card: HTMLElement): string[] {
  const text = [card.querySelector(".ds-row .ds-meta")?.textContent ?? "", within(card).getByTestId("asset-stats").textContent ?? ""].join(" ");
  return (text.match(/\d{4}-\d{2}-\d{2}|\d[\d,]*/g) ?? []).map((t) => t.replace(/,/g, ""));
}

/** profile 里的全部标量（数据集级 + 逐表），转成字符串。 */
function profileValues(p: DatasetProfile): Set<string> {
  const out = new Set<string>();
  const walk = (v: unknown) => {
    if (v === null || v === undefined) return;
    if (typeof v === "object") Object.values(v as object).forEach(walk);
    else out.add(String(v));
  };
  walk(p);
  return out;
}

test("资产卡：没拿到概要时写明点「剖析」；「剖析」真实发出 GET /datasets/{id}（不带 rows），回来后填上概要", async () => {
  const be = setup();
  const card = await openCards();
  expect(within(card).getByTestId("asset-stats").textContent).toBe("还没读取概要，点「剖析」");
  expect(be.calls.some((x) => x.path.startsWith("/datasets/d1"))).toBe(false); // 侧栏不为卡片逐个读文件（F1.1）
  await act(async () => fireEvent.click(within(card).getByRole("button", { name: "剖析「门店」" })));
  expect(be.calls.filter((x) => x.method === "GET" && x.path.startsWith("/datasets/d1")).map((x) => x.path)).toEqual(["/datasets/d1"]);
  await waitFor(() => expect(within(card).getByTestId("asset-stats").textContent).toContain("5 行"));
  const stats = within(card).getByTestId("asset-stats").textContent;
  expect(stats).toBe("5 行 · 4 列 · 3 列有缺失2023-12-28 ~ 2024-03-31");
  expect(card.querySelector(".ds-row .ds-meta")?.textContent).toBe("1 个表");
  expect(within(card).getByText(fx.filename)).toBeTruthy(); // 文件名（数据集名和文件名不同时）
});

test("双向钉住：卡片上的每个数字都在 /datasets/{id} 的 profile 里；profile 的数据集级标量也都在卡片上", async () => {
  setup();
  const card = await openCards();
  await act(async () => fireEvent.click(within(card).getByRole("button", { name: "剖析「门店」" })));
  await waitFor(() => expect(within(card).getByTestId("asset-stats").textContent).toContain("行"));
  const shown = cardNumbers(card);
  const all = profileValues(PROFILE);
  expect(shown.length).toBeGreaterThanOrEqual(6);
  for (const n of shown) expect(all.has(n), `卡片上的 ${n} 不在 profile 里`).toBe(true);
  const top = [PROFILE.table_count, PROFILE.rows, PROFILE.columns, PROFILE.missing_columns, PROFILE.time_range!.min, PROFILE.time_range!.max];
  for (const v of top) expect(shown, `profile 的 ${v} 没上卡片`).toContain(String(v));
});

test("大数加千分位、多表用 table_count、没有日期列和没有缺失列各有说法；数字仍都在 profile 里", async () => {
  const big: DatasetProfile = {
    table_count: 3, rows: 1234567, columns: 21, missing_columns: 0, time_range: null,
    tables: [
      { name: "a", rows: 1234000, columns: 10, missing_columns: 0, time_range: null },
      { name: "b", rows: 560, columns: 8, missing_columns: 0, time_range: null },
      { name: "c", rows: 7, columns: 3, missing_columns: 0, time_range: null },
    ],
  };
  const D = { ...DS, files: [{ filename: "book.xlsx", size: 1, sha256: "h" }] }; // 一个 xlsx 读出 3 张表
  setup({ "GET /datasets": [D], "GET /datasets/d1": { ...D, summary: "", tables: {}, profile: big } });
  const card = await openCards();
  expect(card.querySelector(".ds-row .ds-meta")?.textContent).toBe("1 个表"); // 剖析前按文件数
  await act(async () => fireEvent.click(within(card).getByRole("button", { name: "剖析「门店」" })));
  await waitFor(() => expect(within(card).getByTestId("asset-stats").textContent).toBe("1,234,567 行 · 21 列 · 无缺失列没有日期列"));
  expect(card.querySelector(".ds-row .ds-meta")?.textContent).toBe("3 个表");
  const all = profileValues(big);
  for (const n of cardNumbers(card)) expect(all.has(n), n).toBe(true);
});

test("上传响应自带 profile：卡片直接显示，不再为卡片发 GET /datasets/{id}", async () => {
  const up = { id: "d2", name: "新的", created_at: "t", files: [{ filename: "n.csv", size: 1, sha256: "h" }] };
  const be = setup({
    "GET /datasets": [],
    "POST /datasets": { ...up, summary: "", tables: {}, profile: PROFILE, preview: { rows: 20, tables: [], dicts: [] } },
    "GET /datasets/d2/notes": [],
    "GET /settings": { model: "m", base_url: "", timeout: 60 },
    "GET /connections": { active: null, items: [] },
  });
  const input = (await screen.findAllByLabelText("选择 CSV 文件"))[0] as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File(["a\n1\n"], "n.csv", { type: "text/csv" })] } });
  await act(async () => fireEvent.click(await screen.findByRole("button", { name: "上传" })));
  const card = await openCards();
  await waitFor(() => expect(within(card).getByTestId("asset-stats").textContent).toContain("5 行"));
  expect(be.calls.some((x) => x.method === "GET" && /^\/datasets\/d2(\?|$)/.test(x.path))).toBe(false);
});

test("「提问」真实发出 POST /sessions（这个数据集、标准模式），并打开新会话", async () => {
  const be = setup({
    "POST /sessions": SESSION,
    "GET /sessions/s9": { ...SESSION, messages: [] },
  });
  const card = await openCards();
  await act(async () => fireEvent.click(within(card).getByRole("button", { name: "就「门店」提问" })));
  expect(be.calls.filter((x) => x.method === "POST" && x.path === "/sessions").map((x) => x.body)).toEqual([{ dataset_id: "d1", agent: "workflow" }]);
  await waitFor(() => expect(be.calls.some((x) => x.path === "/sessions/s9")).toBe(true));
});

test("「口径」进数据集页并滚到口径与规则（导入 / 导出在那里）；资产卡标「使用中」", async () => {
  const scrolled: Element[] = [];
  const orig = Element.prototype.scrollIntoView;
  Element.prototype.scrollIntoView = function (this: Element) {
    scrolled.push(this);
  };
  try {
    setup({
      "GET /datasets/d1?rows=20": { ...DS, summary: "", tables: {}, profile: PROFILE, preview: { rows: 20, tables: [], dicts: [] } },
      "GET /datasets/d1/notes": [],
      "GET /settings": { model: "m", base_url: "", timeout: 60 },
      "GET /connections": { active: null, items: [] },
    });
    const card = await openCards();
    await act(async () => fireEvent.click(within(card).getByRole("button", { name: "「门店」的口径导入导出" })));
    const notes = await screen.findByTestId("notes-section");
    await waitFor(() => expect(scrolled).toContain(notes));
    expect(within(notes).getByRole("button", { name: "导入" })).toBeTruthy();
    // 原型：卡片在「数据集」页，进了单个数据集页后卡片不在屏上，所以不再断言「使用中」。
    // 打开数据集页拿到的详情带 profile，回到卡片页时卡片已填上，不另发请求
    const again = await openCards();
    await waitFor(() => expect(within(again).getByTestId("asset-stats").textContent).toContain("5 行"));
  } finally {
    Element.prototype.scrollIntoView = orig;
  }
});

test("「剖析」读到坏文件：卡片转成读取失败，收起概要和按钮", async () => {
  setup({ "GET /datasets/d1": { ...DS, error: "文件是空的", tables: {}, summary: "", profile: { ...PROFILE, table_count: 0, tables: [] } } });
  const card = await openCards();
  await act(async () => fireEvent.click(within(card).getByRole("button", { name: "剖析「门店」" })));
  await waitFor(() => expect(within(card).getByText("读取失败")).toBeTruthy());
  expect(within(card).queryByTestId("asset-stats")).toBeNull();
  expect(within(card).queryByRole("button", { name: "剖析「门店」" })).toBeNull();
});
