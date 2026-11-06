import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Api } from "../api";
import { client } from "../client";
import { fakeBackend } from "../fakeBackend";
import type { DatasetNote, NoteIn } from "../types";
import { DatasetView } from "./DatasetView";
import { validateNote } from "./NotesSection";
import { Shell } from "./Shell";
import { conn, connRoutes } from "./connFixtures";

// 批 4b M2 / M10：数据集页「口径与规则」（docs/roadmap/memory-batch4.md §3.4.1）
const INJECT = '<img src=x onerror="window.__pwned=1">';
const TABLE = {
  name: "sales", filename: "sales.csv", encoding: "utf-8", total_rows: 2, total_columns: 1, columns: ["units"], dtypes: ["int"],
  rows: [["1"], ["2"]], bidi_stripped: 0, truncated_cells: 0,
};
const DS = { id: "d1", name: "销量", created_at: "t", files: [{ filename: "sales.csv", size: 10, sha256: "h" }], summary: "", tables: {},
  preview: { rows: 20, dicts: [], tables: [TABLE] } };
const note = (over: Partial<DatasetNote> = {}): DatasetNote => ({
  id: "n1", dataset_id: "d1", kind: "metric", name: "利润", body: "units * price - cost", unit: "元", synonyms: "净利,净利润",
  sha: "abc123abc123", source: "explicit_user", supersedes: null, retired_at: null, created_at: "t", ...over,
});

function view(routes: Record<string, unknown> = {}, ds: unknown = DS) {
  const be = fakeBackend({ "GET /datasets/d1?rows=20": ds, "GET /settings": { model: "m", base_url: "u", timeout: 60,
    memory: { mode: "state", setting: "state", env: null } }, ...routes });
  render(<DatasetView c={client(new Api("t", be.fetchImpl))} id="d1" onDeleted={() => {}} onNewSession={() => {}} />);
  return be;
}

afterEach(() => {
  delete (window as unknown as { __pwned?: number }).__pwned;
});

test("列表：名称 / 类型 / 公式 / 单位 / 别名按文本渲染，注入串不变成元素；没有「删除」按钮", async () => {
  view({ "GET /datasets/d1/notes": [note(), note({ id: "n2", kind: "rule", name: "退款不计", body: INJECT, unit: "", synonyms: "" })] });
  const sec = await screen.findByTestId("notes-section");
  const rows = await within(sec).findAllByTestId("note-row");
  expect(rows).toHaveLength(2);
  expect(within(rows[0]).getByText("units * price - cost")).toBeTruthy();
  expect(within(rows[0]).getByText("净利、净利润")).toBeTruthy();
  expect(within(rows[1]).getByText("规则")).toBeTruthy();
  expect(within(rows[1]).getByText(INJECT)).toBeTruthy();
  expect(sec.querySelector("img")).toBeNull();
  expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
  expect(within(sec).queryByRole("button", { name: /删除/ })).toBeNull();
  expect(within(sec).getByText("2 条")).toBeTruthy();
  expect(within(sec).queryByTestId("notes-off")).toBeNull();
});

test("表单校验：名称、公式为空或超长时不发请求，写明原因", async () => {
  const be = view({ "GET /datasets/d1/notes": [] });
  const sec = await screen.findByTestId("notes-section");
  await within(sec).findByTestId("notes-empty");
  fireEvent.click(within(sec).getByRole("button", { name: "添加口径" }));
  await act(async () => fireEvent.click(within(sec).getByRole("button", { name: "保存口径" })));
  expect(within(sec).getByTestId("note-form-error").textContent).toBe("名称不能为空");
  fireEvent.change(within(sec).getByLabelText("口径名称"), { target: { value: "利润" } });
  await act(async () => fireEvent.click(within(sec).getByRole("button", { name: "保存口径" })));
  expect(within(sec).getByTestId("note-form-error").textContent).toBe("公式不能为空");
  expect(be.calls.some((x) => x.method === "POST")).toBe(false);
  const base: NoteIn = { kind: "metric", name: "a", body: "b", unit: "", synonyms: "" };
  expect(validateNote({ ...base, name: "x".repeat(65) })).toBe("名称不能超过 64 字");
  expect(validateNote({ ...base, kind: "rule", body: "b".repeat(2001) })).toBe("规则不能超过 2000 字");
  expect(validateNote({ ...base, unit: "u".repeat(17) })).toBe("单位不能超过 16 字");
  expect(validateNote({ ...base, synonyms: "s".repeat(201) })).toBe("别名不能超过 200 字");
  expect(validateNote(base)).toBe("");
});

test("添加：发 POST，成功后列表刷新；409 时提示改用编辑", async () => {
  let list: DatasetNote[] = [];
  let conflict = false;
  const be = view({
    "GET /datasets/d1/notes": () => list,
    "POST /datasets/d1/notes": (b: unknown) => {
      if (conflict) return new Response(JSON.stringify({ detail: "已经有一条在用的「利润」，请改用编辑" }), { status: 409 });
      list = [note({ ...(b as NoteIn) })];
      return list[0];
    },
  });
  const sec = await screen.findByTestId("notes-section");
  await within(sec).findByTestId("notes-empty");
  fireEvent.click(within(sec).getByRole("button", { name: "添加口径" }));
  fireEvent.change(within(sec).getByLabelText("口径名称"), { target: { value: " 利润 " } });
  fireEvent.change(within(sec).getByLabelText("公式或规则"), { target: { value: "units * price - cost" } });
  fireEvent.change(within(sec).getByLabelText("单位"), { target: { value: "元" } });
  fireEvent.change(within(sec).getByLabelText("别名"), { target: { value: "净利，净利润" } });
  await act(async () => fireEvent.click(within(sec).getByRole("button", { name: "保存口径" })));
  expect(be.calls.find((x) => x.method === "POST")?.body).toEqual(
    { kind: "metric", name: " 利润 ", body: "units * price - cost", unit: "元", synonyms: "净利，净利润" });
  expect(await within(sec).findAllByTestId("note-row")).toHaveLength(1);
  expect(within(sec).getByRole("status").textContent).toBe("口径已添加。");

  conflict = true;
  fireEvent.click(within(sec).getByRole("button", { name: "添加口径" }));
  fireEvent.change(within(sec).getByLabelText("口径名称"), { target: { value: "利润" } });
  fireEvent.change(within(sec).getByLabelText("公式或规则"), { target: { value: "别的" } });
  await act(async () => fireEvent.click(within(sec).getByRole("button", { name: "保存口径" })));
  expect((await within(sec).findByTestId("note-form-error")).textContent).toBe("已经有一条在用的「利润」，请在列表里点它的「编辑」。");
});

test("编辑发 PUT（新版本），停用两次点击确认，停用后从列表消失", async () => {
  let list = [note()];
  const be = view({
    "GET /datasets/d1/notes": () => list,
    "PUT /datasets/d1/notes/n1": (b: unknown) => (list = [note({ ...(b as NoteIn), id: "n9", supersedes: "n1" })])[0],
    "DELETE /datasets/d1/notes/n9": () => ((list = []), new Response(null, { status: 204 })),
  });
  const sec = await screen.findByTestId("notes-section");
  fireEvent.click(await within(sec).findByRole("button", { name: "编辑「利润」" }));
  expect((within(sec).getByLabelText("公式或规则") as HTMLTextAreaElement).value).toBe("units * price - cost");
  fireEvent.change(within(sec).getByLabelText("公式或规则"), { target: { value: "units * price - cost - tax" } });
  await act(async () => fireEvent.click(within(sec).getByRole("button", { name: "保存修改" })));
  expect(be.calls.find((x) => x.method === "PUT")?.body).toMatchObject({ name: "利润", body: "units * price - cost - tax" });
  await waitFor(() => expect(within(sec).getByText("units * price - cost - tax")).toBeTruthy());
  fireEvent.click(within(sec).getByRole("button", { name: "停用" }));
  expect(be.calls.some((x) => x.method === "DELETE")).toBe(false); // 第一次点只是武装
  await act(async () => fireEvent.click(within(sec).getByRole("button", { name: "确认停用" })));
  await within(sec).findByTestId("notes-empty");
  expect(be.calls.filter((x) => x.method === "DELETE").map((x) => x.path)).toEqual(["/datasets/d1/notes/n9"]);
  expect(within(sec).getByRole("status").textContent).toBe("已停用「利润」。");
});

test("导入：文件内容原样作请求体，按扩展名定 Content-Type；整批被拒时显示后端原因", async () => {
  let reject = false;
  const be = view({
    "GET /datasets/d1/notes": [],
    "POST /datasets/d1/notes/import": () => reject
      ? new Response(JSON.stringify({ detail: "导入失败，没有写入任何一条：第 3 行：名称不能为空" }), { status: 400 })
      : { added: 2, updated: 1, unchanged: 0, errors: [] },
  });
  const sec = await screen.findByTestId("notes-section");
  await within(sec).findByTestId("notes-empty");
  const input = within(sec).getByLabelText("选择口径文件");
  const csv = new File(["kind,name,body\n"], "口径.csv", { type: "text/csv" });
  await act(async () => fireEvent.change(input, { target: { files: [csv] } }));
  const call = be.calls.find((x) => x.path === "/datasets/d1/notes/import")!;
  expect(call.body).toBe(csv);
  expect(within(sec).getByRole("status").textContent).toBe("导入完成：新增 2 条，更新 1 条，未变 0 条。");
  reject = true;
  await act(async () => fireEvent.change(input, { target: { files: [new File(["[]"], "x.json")] } }));
  expect(within(sec).getByRole("alert").textContent).toBe("导入失败，没有写入任何一条：第 3 行：名称不能为空");
});

test("会话记忆关闭时写明口径不生效；读取失败的数据集不显示口径区", async () => {
  view({ "GET /datasets/d1/notes": [], "GET /settings": { model: "m", base_url: "u", timeout: 60, memory: { mode: "off", setting: "off", env: null } } });
  expect((await screen.findByTestId("notes-off")).textContent).toContain("会话记忆关闭时口径不生效");
});

test("读取失败的数据集（allFailed）：不显示口径区，也不请求口径", async () => {
  const failed = { ...DS, error: "sales.csv：EmptyDataError", preview: { rows: 20, dicts: [], tables: [{ name: "sales", filename: "sales.csv", error: "EmptyDataError" }] } };
  const be = view({ "GET /datasets/d1/notes": [] }, failed);
  await screen.findByText(/读取失败/, { selector: "h2" });
  expect(screen.queryByTestId("notes-section")).toBeNull();
  expect(be.calls.some((x) => x.path.includes("/notes"))).toBe(false);
});

// 批 4b：设置页三选一 + 改写复选框（batch4 §2.2）
test("设置：记忆三选一含「开启（完整）」，改写复选框随保存发 memory_rewrite；被 DATACHAT_REWRITE 覆盖时写明", async () => {
  const saved: unknown[] = [];
  const be = fakeBackend({
    ...connRoutes([conn({ name: "qwen 网关", provider: "custom", model: "qwen", base_url: "https://x/v1" })]).routes,
    "GET /datasets": [], "GET /sessions": [], "GET /settings/api-key": { configured: true, source: "keyring" },
    "GET /settings": { model: "qwen", base_url: "https://x/v1", timeout: 60,
      memory: { mode: "state", setting: "state", env: null, rewrite: false, rewrite_setting: false, rewrite_env: null } },
    "PUT /settings": (b: unknown) => (saved.push(b), { model: "qwen", base_url: "https://x/v1", timeout: 60,
      memory: { mode: "full", setting: "full", env: null, rewrite: false, rewrite_setting: true, rewrite_env: false } }),
  });
  render(<Shell c={client(new Api("t", be.fetchImpl))} initialKey={{ configured: true, source: "keyring" }} />);
  fireEvent.click(await screen.findByRole("button", { name: "设置" }));
  const v = await screen.findByTestId("settings-view");
  const sel = (await within(v).findByLabelText("会话记忆")) as HTMLSelectElement;
  await waitFor(() => expect(sel.value).toBe("state"));
  expect([...sel.options].map((o) => o.value)).toEqual(["off", "state", "full"]);
  expect(within(v).getByRole("option", { name: "开启（完整）：再压缩较长的历史，并参考你点过赞的写法" })).toBeTruthy();
  const box = within(v).getByLabelText("追问前先改写问题") as HTMLInputElement;
  expect(box.checked).toBe(false);
  fireEvent.change(sel, { target: { value: "full" } });
  fireEvent.click(box);
  await act(async () => fireEvent.click(within(v).getByRole("button", { name: "保存记忆设置" })));
  expect(saved).toEqual([{ memory_mode: "full", memory_rewrite: true }]);
  expect((within(v).getByLabelText("追问前先改写问题") as HTMLInputElement).checked).toBe(true);
  expect(within(v).getByTestId("rewrite-hint").textContent).toContain("DATACHAT_REWRITE=0 覆盖");
  fireEvent.change(sel, { target: { value: "off" } });
  expect(within(v).getByTestId("rewrite-hint").textContent).toContain("会话记忆关闭时不改写");
});
