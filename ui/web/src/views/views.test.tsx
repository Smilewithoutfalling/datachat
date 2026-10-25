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

// V2c §3：设置页、数据集页的「← 返回」回到最近一次停留的首页或会话
test("返回：会话 → 设置 → 数据集 → 返回，回到会话（设置 ↔ 数据集之间不改锚点）", async () => {
  setup();
  fireEvent.click(await screen.findByRole("button", { name: /^旧标题/ }));
  await screen.findByTestId("session-view");
  fireEvent.click(screen.getByRole("button", { name: "设置" }));
  await screen.findByTestId("settings-view");
  expect(screen.getByRole("button", { name: "返回" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /^销量/ }));
  await screen.findByTestId("dataset-view");
  fireEvent.click(screen.getByRole("button", { name: "返回" }));
  expect(await screen.findByTestId("session-view")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "返回" })).toBeNull(); // 会话页本身不带返回
});

test("返回：首次启动没 Key 自动进设置页，不显示返回", async () => {
  setup({}, { configured: false, source: null });
  await screen.findByTestId("settings-view");
  expect(screen.queryByRole("button", { name: "返回" })).toBeNull();
});

// ---- 阶段 5 收尾 C：设置页「测试连接」——测的是已保存的配置 -------------------------------------------------------
describe("测试连接", () => {
  /** 可控的 JSON 响应：body 流先不关，调用方 resolve 时才写入并关闭（按钮的"测试中"态要能看到）。 */
  function pending() {
    let ctrl!: ReadableStreamDefaultController<Uint8Array>;
    const stream = new ReadableStream<Uint8Array>({ start: (c) => void (ctrl = c) });
    return {
      response: () => new Response(stream, { status: 200, headers: { "Content-Type": "application/json" } }),
      resolve: (v: unknown) => { ctrl.enqueue(new TextEncoder().encode(JSON.stringify(v))); ctrl.close(); },
    };
  }
  const open = async () => {
    fireEvent.click(await screen.findByRole("button", { name: "设置" }));
    return screen.findByTestId("settings-view");
  };

  test("三态：可点 → 测试中（不可点）→ 连接正常 · 0.8s · 模型名；请求是 POST /settings/test", async () => {
    const p = pending();
    const be = setup({ "POST /settings/test": () => p.response() });
    const view = await open();
    const btn = within(view).getByRole("button", { name: "测试连接" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
    await act(async () => fireEvent.click(btn));
    expect((within(view).getByRole("button", { name: "测试中…" }) as HTMLButtonElement).disabled).toBe(true);
    expect(be.calls.filter((x) => x.method === "POST" && x.path === "/settings/test")).toHaveLength(1);
    await act(async () => p.resolve({ ok: true, latency_ms: 812, model: "deepseek-chat" }));
    expect(within(view).getByTestId("test-result").textContent).toBe("连接正常 · 0.8s · deepseek-chat");
    expect((within(view).getByRole("button", { name: "测试连接" }) as HTMLButtonElement).disabled).toBe(false);
  });

  // V2c §2（S 10-25 定）：失败和错误卡一个口径——正文是标题 + 建议 + 编号，后端原文收进默认折叠的「技术详情」。
  // 期望变了：原来断言正文就是整串 message（含上游英文 "invalid key"），现在正文不含原文，原文只在展开后的技术详情里。
  test("失败：正文是标题 + 建议 + 编号，上游原文折叠在「技术详情」；auth 时焦点移到 Key 输入框", async () => {
    const message = "鉴权失败，请检查 API Key，共尝试 1 次：invalid key（编号 0123abcd）";
    setup({ "POST /settings/test": { ok: false, llm_kind: "auth", message, latency_ms: 120 } });
    const view = await open();
    await act(async () => fireEvent.click(within(view).getByRole("button", { name: "测试连接" })));
    const r = within(view).getByTestId("test-result");
    expect(r.querySelector(".test-fail-title")!.textContent).toBe("模型服务不认这个 API Key");
    expect(r.querySelector(".test-fail-hint")!.textContent).toBe("检查或更换上面的 Key。（编号 0123abcd）");
    const tech = within(view).getByTestId("test-tech");
    expect(tech.hidden).toBe(true);
    expect(tech.textContent).toBe(message);
    const toggle = within(r).getByRole("button", { name: "技术详情" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(tech.hidden).toBe(false);
  });

  test("失败（auth）：焦点移到 Key 输入框", async () => {
    setup({ "POST /settings/test": { ok: false, llm_kind: "auth", message: "x（编号 0123abcd）", latency_ms: 1 } });
    const view = await open();
    await act(async () => fireEvent.click(within(view).getByRole("button", { name: "测试连接" })));
    expect(document.activeElement).toBe(within(view).getByLabelText("当前 Key"));
  });

  test("失败（server）：标题、设置页口径的建议；message 不带编号时不拼编号；焦点不动", async () => {
    setup({ "POST /settings/test": { ok: false, llm_kind: "server", message: "模型服务出错", latency_ms: 5 } });
    const view = await open();
    const btn = within(view).getByRole("button", { name: "测试连接" });
    btn.focus();
    await act(async () => fireEvent.click(btn));
    const r = within(view).getByTestId("test-result");
    expect(r.querySelector(".test-fail-title")!.textContent).toBe("模型服务出错了");
    expect(r.querySelector(".test-fail-hint")!.textContent).toBe("通常是临时的，稍后再测。");
    expect(document.activeElement).toBe(btn);
  });

  // V2c §1：结果只对测的那一份已保存配置有效
  test("旧结果作废：改字段再改回、改字段再保存、填新 Key、在飞时改字段，结果都不再出现", async () => {
    const p = pending();
    let n = 0;
    setup({ "POST /settings/test": () => (n++ === 2 ? p.response() : Response.json({ ok: true, latency_ms: 812, model: "deepseek-chat" })) });
    const view = await open();
    const btn = () => within(view).getByRole("button", { name: "测试连接" });
    const model = () => within(view).getByLabelText("模型名");
    // 改字段再改回原值：unsaved 回到 false，但结果已作废
    await act(async () => fireEvent.click(btn()));
    expect(within(view).getByTestId("test-result")).toBeTruthy();
    fireEvent.change(model(), { target: { value: "m2" } });
    fireEvent.change(model(), { target: { value: "qwen" } }); // 回到已保存的原值
    expect(within(view).queryByTestId("test-result")).toBeNull();
    // 改字段再保存（原来的 bug：保存后旧结果重新出现）
    await act(async () => fireEvent.click(btn()));
    expect(within(view).getByTestId("test-result")).toBeTruthy();
    fireEvent.change(model(), { target: { value: "m3" } });
    await act(async () => fireEvent.click(within(view).getByRole("button", { name: "保存设置" })));
    expect(within(view).queryByTestId("test-unsaved")).toBeNull();
    expect(within(view).queryByTestId("test-result")).toBeNull();
    // 在飞时改字段：回来的是旧配置的结果，丢弃
    await act(async () => fireEvent.click(btn()));
    fireEvent.change(model(), { target: { value: "m4" } });
    await act(async () => p.resolve({ ok: true, latency_ms: 1, model: "m3" }));
    fireEvent.change(model(), { target: { value: "m3" } });
    expect(within(view).queryByTestId("test-result")).toBeNull();
    expect(within(view).getByRole("button", { name: "测试连接" })).toBeTruthy();
  });

  test("有未保存的改动时不可点，旁边写「先保存再测试」；保存后可点；填了新 Key 没保存也算未保存", async () => {
    const be = setup({ "POST /settings/test": { ok: true, latency_ms: 1, model: "m2" } });
    const view = await open();
    const btn = () => within(view).getByRole("button", { name: "测试连接" }) as HTMLButtonElement;
    expect(within(view).queryByTestId("test-unsaved")).toBeNull();
    fireEvent.change(within(view).getByLabelText("模型名"), { target: { value: "m2" } });
    expect(btn().disabled).toBe(true);
    expect(within(view).getByTestId("test-unsaved").textContent).toBe("先保存再测试");
    fireEvent.click(btn());
    expect(be.calls.some((x) => x.path === "/settings/test")).toBe(false);
    await act(async () => fireEvent.click(within(view).getByRole("button", { name: "保存设置" })));
    expect(btn().disabled).toBe(false);
    expect(within(view).queryByTestId("test-unsaved")).toBeNull();
    fireEvent.click(within(view).getByRole("button", { name: "更换" }));
    fireEvent.change(within(view).getByLabelText("替换为新的 Key"), { target: { value: "sk-new" } });
    expect(btn().disabled).toBe(true);
  });
});

// V2c §5：结论排版的样式挂在 .md 下的 h1~h4、ul/ol/li、table 上——钉住渲染结构（观感以 25 屏基线为准）
test("结论 Markdown：标题、列表、表格都渲染在 .md 下，第一个子元素是标题", async () => {
  const { Markdown } = await import("./Markdown");
  const { container } = render(<Markdown text={"## 结论\n\n- 第一条\n- 第二条\n\n| 列 | 值 |\n|---|---|\n| a | 1 |\n\n### 细节\n\n正文"} />);
  const md = container.querySelector(".md")!;
  expect(md.firstElementChild?.tagName).toBe("H2");
  expect(md.querySelectorAll(":scope > ul > li")).toHaveLength(2);
  expect(md.querySelector(":scope > table th")?.textContent).toBe("列");
  expect(md.querySelector(":scope > h3")?.textContent).toBe("细节");
});
