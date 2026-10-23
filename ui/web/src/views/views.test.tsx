import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { Api } from "../api";
import { client } from "../client";
import { fakeBackend } from "../fakeBackend";
import type { KeyStatus } from "../types";
import { Shell } from "./Shell";

const INJECT = '<img src=x onerror="window.__pwned=1">';
const DS = { id: "d1", name: "销量", created_at: "t", files: [{ filename: "sales.csv", size: 2048, sha256: "h" }] };
const PREVIEW = {
  rows: 20,
  dicts: ["sales.dict.csv"],
  tables: [
    {
      name: "sales",
      filename: "sales.csv",
      encoding: "gbk",
      total_rows: 100,
      total_columns: 3,
      columns: ["名称", INJECT, "数量"],
      dtypes: ["object", "object", "float64"],
      rows: [
        ["苹果", INJECT, null],
        ["null", "b", "3.0"],
      ],
      bidi_stripped: 2,
      truncated_cells: 1,
    },
  ],
};
const SESSION = { id: "s1", dataset_id: "d1", agent: "react", title: "旧标题", created_at: "t", updated_at: "t" };

function setup(extra: Record<string, unknown> = {}, key: KeyStatus = { configured: true, source: "keyring" }) {
  const be = fakeBackend({
    "GET /datasets": [DS],
    "GET /sessions": [SESSION],
    "GET /datasets/d1?rows=20": { ...DS, summary: "100 行 × 3 列，编码 gbk", tables: {}, preview: PREVIEW },
    "GET /sessions/s1": {
      ...SESSION,
      messages: [
        { id: "m1", role: "user", content: "问题", status: "ok", created_at: "t" },
        { id: "m2", role: "assistant", content: INJECT, status: "error", created_at: "t" },
      ],
    },
    "PATCH /sessions/s1": (b: unknown) => ({ ...SESSION, title: (b as { title: string }).title }),
    "GET /settings/api-key": key,
    "GET /settings": { model: "qwen", base_url: "https://x/v1", timeout: 60 },
    "PUT /settings": (b: unknown) => ({ model: "qwen", base_url: "https://x/v1", ...(b as object) }),
    "PUT /settings/api-key": { configured: true, source: "keyring" },
    ...extra,
  });
  render(<Shell c={client(new Api("t", be.fetchImpl))} initialKey={key} />);
  return be;
}

afterEach(() => {
  delete (window as unknown as { __pwned?: number }).__pwned;
});

test("预览：表头、单元格按文本渲染，注入串不变成元素；缺失值显示为'空'，与字符串 null 区分", async () => {
  setup();
  fireEvent.click(await screen.findByRole("button", { name: /^销量/ }));
  const view = await screen.findByTestId("dataset-view");
  expect(within(view).getByText("共 100 行 × 3 列，编码 gbk，显示前 2 行", { exact: false })).toBeTruthy();
  expect(within(view).getAllByText(INJECT)).toHaveLength(3); // 表头、单元格、右侧字段卡（V2a 新增）各一次，都是文本
  expect(view.querySelector("img")).toBeNull();
  expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
  expect(within(view).getByText("空").className).toBe("na");
  expect(within(view).getByText("null").className).toBe("");
  expect(within(view).getByText("字典文件：sales.dict.csv")).toBeTruthy();
  const hint = view.querySelector(".table-foot")?.textContent ?? ""; // 工具栏也有「共 100 行」（预览说明），取表格下的这一行
  expect(hint).toContain("1 个单元格超 200 字，已截断");
  expect(hint).toContain("2 处方向控制符已从预览中去掉");
});

test("详情与预览只发一个请求；上传后直接用响应里的预览，不再请求", async () => {
  const be = setup({
    "POST /datasets": { ...DS, id: "d2", name: "新上传", tables: {}, preview: PREVIEW },
  });
  fireEvent.click(await screen.findByRole("button", { name: /^销量/ }));
  await screen.findByTestId("dataset-view");
  expect(be.calls.filter((x) => x.path.startsWith("/datasets/d1")).map((x) => x.path)).toEqual(["/datasets/d1?rows=20"]);

  const file = new File(["a,b\n1,2\n"], "x.csv", { type: "text/csv" });
  fireEvent.change(screen.getByLabelText("选择 CSV 文件"), { target: { files: [file] } });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "上传" })));
  expect(await screen.findByRole("heading", { name: "新上传" })).toBeTruthy();
  expect(be.calls.some((x) => x.path.startsWith("/datasets/d2"))).toBe(false);
});

test("多表：tab 上带行列数与编码，读坏的表标出；顶层 error 提示分析会失败", async () => {
  setup({
    "GET /datasets/d1?rows=20": {
      ...DS,
      error: "users.csv：EmptyDataError",
      preview: {
        rows: 20,
        dicts: [],
        tables: [PREVIEW.tables[0], { name: "users", filename: "users.csv", error: "EmptyDataError" }],
      },
    },
  });
  fireEvent.click(await screen.findByRole("button", { name: /^销量/ }));
  const view = await screen.findByTestId("dataset-view");
  expect(within(view).getByRole("tab", { name: /sales\s*100×3 · gbk/ })).toBeTruthy();
  fireEvent.click(within(view).getByRole("tab", { name: /users\s*读取失败/ }));
  expect(within(view).getAllByRole("alert").map((x) => x.textContent)).toEqual([
    "有表读取失败，分析会失败：users.csv：EmptyDataError",
    "users.csv 读取失败：EmptyDataError",
  ]);
});

test("会话：消息按文本渲染；改名走 PATCH 并更新左栏", async () => {
  const be = setup();
  fireEvent.click(await screen.findByRole("button", { name: /^旧标题/ }));
  const view = await screen.findByTestId("session-view");
  // 失败轮次的后端原文在错误卡的「技术详情」里（验收 P1-2/3），展开后同样按文本渲染
  for (const b of within(view).queryAllByRole("button", { name: "技术详情" })) fireEvent.click(b);
  expect(within(view).getByText(INJECT)).toBeTruthy();
  expect(view.querySelector("img")).toBeNull();
  expect(within(view).getByText("失败")).toBeTruthy();
  const input = within(view).getByLabelText("会话标题");
  fireEvent.change(input, { target: { value: "新标题" } });
  await act(async () => fireEvent.blur(input));
  expect(be.calls.find((x) => x.method === "PATCH")?.body).toEqual({ title: "新标题" });
  expect(await screen.findByRole("button", { name: /^新标题/ })).toBeTruthy();
});

test("没设 Key → 直接进设置页；保存后输入框清空，Key 不出现在任何请求以外的地方", async () => {
  const be = setup({}, { configured: false, source: null });
  const view = await screen.findByTestId("settings-view");
  expect(within(view).getByTestId("key-status").textContent).toBe("未设置");
  const input = view.querySelector('input[type="password"]') as HTMLInputElement;
  fireEvent.change(input, { target: { value: "sk-secret" } });
  await act(async () => fireEvent.click(within(view).getByRole("button", { name: "保存 Key" })));
  expect(be.calls.find((x) => x.path === "/settings/api-key" && x.method === "PUT")?.body).toEqual({ api_key: "sk-secret" });
  expect(input.value).toBe("");
  expect(document.body.textContent).not.toContain("sk-secret");
  expect(within(view).getByTestId("key-status").textContent).toContain("系统凭据") // 验收 P1-15：界面不再用 macOS 的"钥匙串";
});

test("设置：超时越界前端拦下，不发请求；合法值以数字发出", async () => {
  const be = setup();
  fireEvent.click(await screen.findByRole("button", { name: "设置" }));
  const view = await screen.findByTestId("settings-view");
  const t = within(view).getByLabelText("单次请求超时（秒）");
  fireEvent.change(t, { target: { value: "1" } });
  await act(async () => fireEvent.click(within(view).getByRole("button", { name: "保存设置" })));
  expect(within(view).getByRole("alert").textContent).toContain("5–600");
  expect(be.calls.some((x) => x.method === "PUT" && x.path === "/settings")).toBe(false);
  fireEvent.change(t, { target: { value: "120" } });
  await act(async () => fireEvent.click(within(view).getByRole("button", { name: "保存设置" })));
  expect(be.calls.find((x) => x.method === "PUT" && x.path === "/settings")?.body).toEqual({
    model: "qwen",
    base_url: "https://x/v1",
    timeout: 120,
  });
});

test("删除数据集：输入名称才能确认，写明连带删除的会话数", async () => {
  // V2a §5.2：数据集是硬删并级联删会话（app.py:356），两次点击改成对话框 + 输入名称
  const be = setup({ "DELETE /datasets/d1": { ok: true } });
  fireEvent.click(await screen.findByRole("button", { name: /^销量/ }));
  const view = await screen.findByTestId("dataset-view");
  fireEvent.click(within(view).getByRole("button", { name: "数据集操作" }));
  fireEvent.click(within(view).getByRole("menuitem", { name: "删除数据集" }));
  const dlg = within(view).getByRole("dialog", { hidden: true });
  expect(dlg.textContent).toContain("1 个会话会一并删除");
  const confirm = within(dlg).getByRole("button", { name: "删除数据集", hidden: true }) as HTMLButtonElement;
  expect(confirm.disabled).toBe(true);
  fireEvent.change(within(dlg).getByLabelText("输入数据集名称以确认"), { target: { value: "销" } });
  expect(confirm.disabled).toBe(true);
  fireEvent.change(within(dlg).getByLabelText("输入数据集名称以确认"), { target: { value: "销量" } });
  expect(be.calls.some((x) => x.method === "DELETE")).toBe(false);
  await act(async () => fireEvent.click(confirm));
  expect(be.calls.some((x) => x.method === "DELETE" && x.path === "/datasets/d1")).toBe(true);
});

test("列表竞态：reload 在飞时新建会话，晚到的旧列表不能把新会话冲掉（PR #70 评审 §2，Shell listGen）", async () => {
  // 删数据集 d2 会触发 reload；把这次 GET /datasets 扣住，期间在 d1 上新建会话，再放行旧快照
  const D2 = { ...DS, id: "d2", name: "库存" };
  const NEW = { ...SESSION, id: "s9", title: "刚建的会话" };
  const be = fakeBackend({
    "GET /datasets": [DS, D2],
    "GET /sessions": [SESSION],
    "GET /datasets/d1?rows=20": { ...DS, summary: "", tables: {}, preview: PREVIEW },
    "GET /datasets/d2?rows=20": { ...D2, summary: "", tables: {}, preview: PREVIEW },
    "DELETE /datasets/d2": { ok: true },
    "POST /sessions": NEW,
    "GET /sessions/s9": { ...NEW, messages: [] },
    "GET /settings/api-key": { configured: true, source: "keyring" },
  });
  let n = 0;
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  const fetchImpl: typeof fetch = async (input, init) => {
    const u = new URL(String(input), "http://x");
    if ((init?.method ?? "GET") === "GET" && u.pathname === "/datasets" && ++n === 2) {
      const res = await be.fetchImpl(input, init); // 在门前取好：这是"删除后、新建前"的旧快照（只有 s1）
      await gate;
      return res;
    }
    return be.fetchImpl(input, init);
  };
  render(<Shell c={client(new Api("t", fetchImpl))} initialKey={{ configured: true, source: "keyring" }} />);
  const nav = await screen.findByRole("navigation", { name: "数据集" });
  fireEvent.click(await within(nav).findByRole("button", { name: /^库存/ }));
  let view = await screen.findByTestId("dataset-view");
  await within(view).findByText("库存", { exact: false });
  fireEvent.click(within(view).getByRole("button", { name: "数据集操作" }));
  fireEvent.click(within(view).getByRole("menuitem", { name: "删除数据集" }));
  const dlg = within(view).getByRole("dialog", { hidden: true });
  fireEvent.change(within(dlg).getByLabelText("输入数据集名称以确认"), { target: { value: "库存" } });
  await act(async () => fireEvent.click(within(dlg).getByRole("button", { name: "删除数据集", hidden: true })));
  expect(n).toBe(2); // reload 已发出、被扣住
  fireEvent.click(await within(nav).findByRole("button", { name: /^销量/ }));
  view = await screen.findByTestId("dataset-view");
  await act(async () => fireEvent.click(await within(view).findByRole("button", { name: "新建会话" })));
  await screen.findByRole("button", { name: /^刚建的会话/ });
  await act(async () => (release(), await new Promise((r) => setTimeout(r, 20))));
  expect(screen.getByRole("button", { name: /^刚建的会话/ })).toBeTruthy(); // 旧快照被整体丢弃
  expect(be.calls.filter((c) => c.method === "GET" && c.path === "/datasets")).toHaveLength(2);
});
