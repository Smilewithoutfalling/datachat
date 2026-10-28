import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { Api } from "../api";
import { client } from "../client";
import { fakeBackend } from "../fakeBackend";
import type { Connection, ConnectionTest, KeyStatus } from "../types";
import { conn, connRoutes, envConn } from "./connFixtures";
import { DatasetView } from "./DatasetView";
import { SettingsView } from "./SettingsView";
import { TurnView } from "./TurnView";

// 阶段 6.5 §6 第 2 条：连接列表、编辑表单（服务商切换联动、Azure 字段、不需要 Key 的服务商）、测试结果两行、ReAct 置灰。

function settings(items: Connection[], extra: Record<string, unknown> = {}) {
  const { routes, st } = connRoutes(items);
  const be = fakeBackend({ ...routes, ...extra });
  const keys: KeyStatus[] = [];
  render(<SettingsView c={client(new Api("t", be.fetchImpl))} onKeyChange={(k) => keys.push(k)} />);
  return { be, st, keys };
}

const cards = async () => {
  await screen.findByTestId("conn-list");
  return screen.getAllByTestId("conn-card");
};

describe("连接列表", () => {
  test("生效的那张高亮（aria-current + 「生效中」）；✓/✗ 按 probe；未测试写「未测试」", async () => {
    settings([
      conn({ id: "c1", name: "甲", probe: { model: "deepseek-flash", connect: true, tools: true, checked_at: "t" } }),
      conn({ id: "c2", name: "乙", active: false, probe: { model: "deepseek-flash", connect: true, tools: false, checked_at: "t" } }),
    ]);
    const [a, b] = await cards();
    expect(a.getAttribute("aria-current")).toBe("true");
    expect(within(a).getByTestId("conn-active").textContent).toBe("生效中");
    expect(within(a).getByTestId("conn-probe").textContent).toBe("✓ 连接 · ✓ 工具调用");
    expect(b.getAttribute("aria-current")).toBeNull();
    expect(within(b).queryByTestId("conn-active")).toBeNull();
    expect(within(b).getByTestId("conn-probe").textContent).toBe("✓ 连接 · ✗ 工具调用");
    expect(a.querySelector(".conn-sub")!.textContent).toBe("DeepSeek · deepseek-flash");
  });

  test("设为生效：POST activate，高亮换到那张，Shell 收到新连接的 Key 状态", async () => {
    const { be, keys } = settings([conn({ id: "c1", name: "甲" }), conn({ id: "c2", name: "乙", active: false, key: { needed: true, configured: false } })]);
    const [, b] = await cards();
    await act(async () => fireEvent.click(within(b).getByRole("button", { name: "设为生效" })));
    expect(be.calls.some((x) => x.method === "POST" && x.path === "/connections/c2/activate")).toBe(true);
    const [a2, b2] = screen.getAllByTestId("conn-card");
    expect(b2.getAttribute("aria-current")).toBe("true");
    expect(a2.getAttribute("aria-current")).toBeNull();
    expect(keys.at(-1)).toEqual({ configured: false, source: null }); // 乙没填 Key → 提问会被拦
    expect(within(b2).getByTestId("key-status").textContent).toBe("未填 API Key");
  });

  test("删除要二次确认；删完列表刷新", async () => {
    const { be } = settings([conn({ id: "c1", name: "甲" }), conn({ id: "c2", name: "乙", active: false })]);
    const [, b] = await cards();
    fireEvent.click(within(b).getByRole("button", { name: "删除" }));
    expect(be.calls.some((x) => x.method === "DELETE")).toBe(false);
    await act(async () => fireEvent.click(within(b).getByRole("button", { name: "确认删除（Key 一并删除）" })));
    expect(be.calls.some((x) => x.method === "DELETE" && x.path === "/connections/c2")).toBe(true);
    expect(screen.getAllByTestId("conn-card")).toHaveLength(1);
  });

  test("没有连接：只读的「环境变量」卡，没有编辑 / 删除 / 设为生效；Key 状态照旧显示", async () => {
    settings([], { "GET /connections": { active: "env", items: [envConn({ key: { needed: true, configured: true, source: "env" } })] } });
    const [e] = await cards();
    expect(within(e).getByText("环境变量")).toBeTruthy();
    expect(within(e).getByTestId("key-status").textContent).toContain("已设置（来源：环境变量 DEEPSEEK_API_KEY）");
    expect(within(e).queryByRole("button", { name: "编辑" })).toBeNull();
    expect(within(e).queryByRole("button", { name: "删除" })).toBeNull();
    expect(within(e).queryByRole("button", { name: "设为生效" })).toBeNull();
    expect(within(e).getByRole("button", { name: "测试连接" })).toBeTruthy();
    expect(screen.queryByTestId("conn-form")).toBeNull(); // 有 Key：不进引导
  });

  test("首次启动（D2）：没有连接也没有 Key → 引导横幅 + 直接打开新建连接；建好后它生效、Key 只出现在 api-key 请求里", async () => {
    const { be, keys } = settings([]);
    await screen.findByTestId("conn-list");
    expect(screen.getByTestId("onboarding").textContent).toContain("先填 API Key 并保存，再上传 CSV");
    const form = screen.getByTestId("conn-form");
    expect((within(form).getByLabelText("服务商") as HTMLSelectElement).value).toBe("deepseek");
    expect((within(form).getByLabelText("连接名称") as HTMLInputElement).value).toBe("DeepSeek");
    const key = within(form).getByLabelText("API Key") as HTMLInputElement;
    fireEvent.change(key, { target: { value: "sk-secret" } });
    await act(async () => fireEvent.click(within(form).getByRole("button", { name: "新建并保存" })));
    expect(be.calls.find((x) => x.method === "POST" && x.path === "/connections")?.body).toEqual({
      name: "DeepSeek", provider: "deepseek", model: "deepseek-flash", base_url: "https://api.deepseek.com",
      extra: { deployment: "", quirks: {} },
    });
    expect(be.calls.find((x) => x.method === "PUT" && x.path === "/connections/c101/api-key")?.body).toEqual({ api_key: "sk-secret" });
    expect(be.calls.filter((x) => JSON.stringify(x.body ?? "").includes("sk-secret"))).toHaveLength(1);
    expect(document.body.textContent).not.toContain("sk-secret");
    expect(screen.queryByTestId("conn-form")).toBeNull();
    expect(screen.queryByTestId("onboarding")).toBeNull();
    const [c1] = screen.getAllByTestId("conn-card");
    expect(c1.getAttribute("aria-current")).toBe("true");
    expect(keys.at(-1)).toEqual({ configured: true, source: "keyring" });
    expect(screen.getByRole("status").textContent).toContain("第一个连接已建好并生效");
  });
});

describe("编辑表单", () => {
  const openNew = async () => {
    settings([conn()]);
    await cards();
    fireEvent.click(screen.getByRole("button", { name: "新建连接" }));
    return screen.getByTestId("conn-form");
  };

  test("服务商切换联动：Base URL、「去申请 Key」、模型、名称（没手改过时）、预设怪癖；「恢复默认」", async () => {
    const f = await openNew();
    const sel = within(f).getByLabelText("服务商") as HTMLSelectElement;
    expect([...sel.querySelectorAll("optgroup")].map((g) => g.label)).toEqual(["国内", "国外", "本地", "自定义"]);
    fireEvent.change(sel, { target: { value: "zhipu" } });
    const url = within(f).getByLabelText("Base URL") as HTMLInputElement;
    expect(url.value).toBe("https://open.bigmodel.cn/api/paas/v4");
    expect(within(f).getByTestId("key-url").getAttribute("href")).toBe("https://bigmodel.cn/usercenter/proj-mgmt/apikeys");
    expect((within(f).getByLabelText("模型") as HTMLInputElement).value).toBe("glm-5.3");
    expect((within(f).getByLabelText("连接名称") as HTMLInputElement).value).toBe("智谱");
    expect((within(f).getByLabelText("思考参数") as HTMLSelectElement).value).toBe("thinking");
    const reset = within(f).getByRole("button", { name: "恢复默认" }) as HTMLButtonElement;
    expect(reset.disabled).toBe(true);
    fireEvent.change(url, { target: { value: "https://my-gw/v1" } });
    expect(reset.disabled).toBe(false);
    fireEvent.click(reset);
    expect(url.value).toBe("https://open.bigmodel.cn/api/paas/v4");
    // 手改过名称后再换服务商，名称不动；自己填的模型名也不动
    fireEvent.change(within(f).getByLabelText("连接名称"), { target: { value: "公司账号" } });
    fireEvent.change(within(f).getByLabelText("模型"), { target: { value: "my-model" } });
    fireEvent.change(sel, { target: { value: "anthropic" } });
    expect((within(f).getByLabelText("连接名称") as HTMLInputElement).value).toBe("公司账号");
    expect((within(f).getByLabelText("模型") as HTMLInputElement).value).toBe("my-model");
    expect(within(f).queryByLabelText("协议")).toBeNull(); // 只有自定义能选协议
  });

  test("自定义：可选协议（无 Azure），没有申请链接，Base URL 必填", async () => {
    const f = await openNew();
    fireEvent.change(within(f).getByLabelText("服务商"), { target: { value: "custom" } });
    const proto = within(f).getByLabelText("协议") as HTMLSelectElement;
    expect([...proto.options].map((o) => o.value)).toEqual(["openai_chat", "openai_responses", "anthropic"]);
    expect(within(f).queryByTestId("key-url")).toBeNull();
    fireEvent.change(within(f).getByLabelText("模型"), { target: { value: "m" } });
    await act(async () => fireEvent.click(within(f).getByRole("button", { name: "新建并保存" })));
    expect(within(f).getByRole("alert").textContent).toBe("需要填 Base URL");
    fireEvent.change(proto, { target: { value: "anthropic" } });
    fireEvent.change(within(f).getByLabelText("Base URL"), { target: { value: "https://gw.example" } });
    await act(async () => fireEvent.click(within(f).getByRole("button", { name: "新建并保存" })));
    expect(screen.queryByTestId("conn-form")).toBeNull();
  });

  // Azure 改走 v1 路径（不需要 api-version），表单不再有「API 版本」，extra 只带部署名。
  test("Azure：显示部署名、没有 API 版本，模型名可空（用部署名），发给后端的 extra 带部署名", async () => {
    const { be } = settings([conn()]);
    await cards();
    fireEvent.click(screen.getByRole("button", { name: "新建连接" }));
    const f = screen.getByTestId("conn-form");
    expect(within(f).queryByLabelText("部署名")).toBeNull();
    fireEvent.change(within(f).getByLabelText("服务商"), { target: { value: "azure" } });
    fireEvent.change(within(f).getByLabelText("Base URL"), { target: { value: "https://res.openai.azure.com" } });
    fireEvent.change(within(f).getByLabelText("部署名"), { target: { value: "gpt-dep" } });
    expect(within(f).queryByLabelText("API 版本")).toBeNull();
    expect(within(f).getByText("模型名（可选）")).toBeTruthy();
    await act(async () => fireEvent.click(within(f).getByRole("button", { name: "新建并保存" })));
    expect(be.calls.find((x) => x.method === "POST" && x.path === "/connections")?.body).toMatchObject({
      provider: "azure", model: "gpt-dep", base_url: "https://res.openai.azure.com",
      extra: { deployment: "gpt-dep" },
    });
  });

  test("不需要 Key 的服务商（Ollama）隐藏 Key 输入、不发 api-key 请求", async () => {
    const { be } = settings([conn()]);
    await cards();
    fireEvent.click(screen.getByRole("button", { name: "新建连接" }));
    const f = screen.getByTestId("conn-form");
    fireEvent.change(within(f).getByLabelText("服务商"), { target: { value: "ollama" } });
    expect(within(f).queryByLabelText("API Key")).toBeNull();
    expect(within(f).getByTestId("no-key-needed").textContent).toContain("不需要 API Key");
    expect((within(f).getByLabelText("Base URL") as HTMLInputElement).value).toBe("http://localhost:11434/v1");
    fireEvent.change(within(f).getByLabelText("模型"), { target: { value: "qwen3:8b" } });
    await act(async () => fireEvent.click(within(f).getByRole("button", { name: "新建并保存" })));
    expect(be.calls.some((x) => x.path.endsWith("/api-key"))).toBe(false);
  });

  test("编辑：怪癖只把和预设不同的项存成覆盖；已有 Key 显示「已保存」可更换；获取模型列表填进下拉", async () => {
    const { be } = settings([conn()], {
      "GET /connections/c1/models": { source: "remote", models: ["deepseek-flash", "deepseek-x"] },
    });
    const [a] = await cards();
    fireEvent.click(within(a).getByRole("button", { name: "编辑" }));
    const f = screen.getByTestId("conn-form");
    expect((within(f).getByLabelText("当前 Key") as HTMLInputElement).value).toBe("已保存在系统凭据中");
    await act(async () => fireEvent.click(within(f).getByRole("button", { name: "获取模型列表" })));
    expect(within(f).getByTestId("models-note").textContent).toBe("已获取 2 个模型");
    const opts = [...f.querySelectorAll("datalist option")].map((o) => (o as HTMLOptionElement).value);
    expect(opts).toEqual(["deepseek-flash", "deepseek-v4-pro", "deepseek-x"]);
    fireEvent.click(within(f).getByText("高级"));
    fireEvent.click(within(f).getByLabelText("消息内容只发字符串（有的网关不认分段内容）"));
    fireEvent.click(within(f).getByLabelText("多轮工具调用时回传推理内容（DeepSeek 推理模型一类）")); // 预设是开，关掉
    await act(async () => fireEvent.click(within(f).getByRole("button", { name: "保存" })));
    expect((be.calls.find((x) => x.method === "PUT" && x.path === "/connections/c1")?.body as { extra: unknown }).extra).toEqual({
      deployment: "", quirks: { no_array_content: true, reasoning_replay: false },
    });
    expect(be.calls.some((x) => x.path.endsWith("/api-key"))).toBe(false); // 没填新 Key 不发
  });

  test("获取模型列表失败：写明原因，下拉里仍是预设模型；新建（还没保存）时按钮不可点", async () => {
    settings([conn()], {
      "GET /connections/c1/models": { source: "preset", models: ["deepseek-flash"], reason: "请求超时（编号 1234abcd）" },
    });
    const [a] = await cards();
    fireEvent.click(within(a).getByRole("button", { name: "编辑" }));
    const f = screen.getByTestId("conn-form");
    await act(async () => fireEvent.click(within(f).getByRole("button", { name: "获取模型列表" })));
    expect(within(f).getByTestId("models-note").textContent).toBe("没取到，下拉里是预设模型：请求超时（编号 1234abcd）");
    fireEvent.click(within(f).getByRole("button", { name: "取消" }));
    fireEvent.click(screen.getByRole("button", { name: "新建连接" }));
    expect((within(screen.getByTestId("conn-form")).getByRole("button", { name: "获取模型列表" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("测试连接（两行）", () => {
  function pending() {
    let ctrl!: ReadableStreamDefaultController<Uint8Array>;
    const stream = new ReadableStream<Uint8Array>({ start: (c) => void (ctrl = c) });
    return {
      response: () => new Response(stream, { status: 200, headers: { "Content-Type": "application/json" } }),
      resolve: (v: unknown) => { ctrl.enqueue(new TextEncoder().encode(JSON.stringify(v))); ctrl.close(); },
    };
  }
  const OK: ConnectionTest = { ok: true, model: "deepseek-flash", connect: { ok: true, latency_ms: 812 }, tools: { ok: true, latency_ms: 430 },
    probe: { model: "deepseek-flash", connect: true, tools: true, checked_at: "t" } };

  test("三态：可点 → 测试中（不可点）→ 两行：连接正常 · 0.8s · 模型 / 支持 · 0.4s", async () => {
    const p = pending();
    const { be } = settings([conn()], { "POST /connections/c1/test": () => p.response() });
    const [a] = await cards();
    await act(async () => fireEvent.click(within(a).getByRole("button", { name: "测试连接" })));
    expect((within(a).getByRole("button", { name: "测试中…" }) as HTMLButtonElement).disabled).toBe(true);
    expect(be.calls.filter((x) => x.method === "POST" && x.path === "/connections/c1/test")).toHaveLength(1);
    await act(async () => p.resolve(OK));
    const card = screen.getAllByTestId("conn-card")[0];
    expect(within(card).getByTestId("test-connect").textContent).toBe("连接连接正常 · 0.8s · deepseek-flash");
    expect(within(card).getByTestId("test-tools").textContent).toBe("工具调用支持 · 0.4s");
  });

  test("工具调用 ✗：第二行写明「边想边做」不可用，原因收在技术详情", async () => {
    settings([conn()], { "POST /connections/c1/test": { ...OK, ok: false,
      tools: { ok: false, latency_ms: 300, message: "模型没有按要求调用工具：这个模型（或网关）可能不支持工具调用。" } } });
    const [a] = await cards();
    await act(async () => fireEvent.click(within(a).getByRole("button", { name: "测试连接" })));
    const t = within(screen.getAllByTestId("conn-card")[0]).getByTestId("test-tools");
    expect(t.querySelector(".test-fail-title")!.textContent).toBe("不支持工具调用");
    expect(t.querySelector(".test-fail-hint")!.textContent).toContain("只能选「标准」模式");
    expect((within(t).getByTestId("test-tech") as HTMLElement).hidden).toBe(true);
  });

  test("连接失败：第一行是标题 + 建议 + 编号（原文折叠），第二行「没有测」", async () => {
    const message = "鉴权失败，请检查 API Key：invalid key（编号 0123abcd）";
    settings([conn()], { "POST /connections/c1/test": { ok: false, model: "deepseek-flash",
      connect: { ok: false, llm_kind: "auth", message, latency_ms: 120 }, tools: null,
      probe: { model: "deepseek-flash", connect: false, tools: null, checked_at: "t" } } });
    const [a] = await cards();
    await act(async () => fireEvent.click(within(a).getByRole("button", { name: "测试连接" })));
    const card = screen.getAllByTestId("conn-card")[0];
    const r = within(card).getByTestId("test-connect");
    expect(r.querySelector(".test-fail-title")!.textContent).toBe("模型服务不认这个 API Key");
    expect(r.querySelector(".test-fail-hint")!.textContent).toBe("检查或更换上面的 Key。（编号 0123abcd）");
    const tech = within(r).getByTestId("test-tech");
    expect(tech.hidden).toBe(true);
    fireEvent.click(within(r).getByRole("button", { name: "技术详情" }));
    expect(tech.hidden).toBe(false);
    expect(tech.textContent).toBe(message);
    expect(within(card).getByTestId("test-tools").textContent).toBe("工具调用没有测（先要连得上）");
  });

  test("旧结果作废：测完再编辑保存（配置变了），结果不再显示", async () => {
    settings([conn()], { "POST /connections/c1/test": OK });
    const [a] = await cards();
    await act(async () => fireEvent.click(within(a).getByRole("button", { name: "测试连接" })));
    expect(within(screen.getAllByTestId("conn-card")[0]).getByTestId("test-result")).toBeTruthy();
    fireEvent.click(within(screen.getAllByTestId("conn-card")[0]).getByRole("button", { name: "编辑" }));
    fireEvent.change(screen.getByLabelText("模型"), { target: { value: "deepseek-v4-pro" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "保存" })));
    expect(within(screen.getAllByTestId("conn-card")[0]).queryByTestId("test-result")).toBeNull();
  });
});

describe("ReAct 置灰（probe.tools === false）", () => {
  const DS = { id: "d1", name: "销量", created_at: "t", files: [{ filename: "a.csv", size: 1, sha256: "h" }],
    summary: "", tables: {}, preview: { rows: 20, dicts: [], tables: [] } };
  const view = (items: Connection[] | null) => {
    const be = fakeBackend({
      "GET /datasets/d1?rows=20": DS,
      ...(items ? { "GET /connections": { active: items[0]?.id ?? "env", items } } : {}),
    });
    const made: string[] = [];
    render(<DatasetView c={client(new Api("t", be.fetchImpl))} id="d1" onDeleted={() => {}} onNewSession={(_, a) => made.push(a)} />);
    return made;
  };

  test("工具调用 ✗：「边想边做」不可选，悬停说明原因；新建会话只会是标准", async () => {
    const made = view([conn({ name: "网关", model: "m-x", probe: { model: "m-x", connect: true, tools: false, checked_at: "t" } })]);
    const sel = (await screen.findByLabelText("分析模式")) as HTMLSelectElement;
    const react = await screen.findByRole("option", { name: "边想边做（不可用）" }) as HTMLOptionElement;
    expect(react.disabled).toBe(true);
    expect(react.title).toContain("当前连接「网关」的模型 m-x 测试时没有调用工具");
    expect(sel.closest("label")!.title).toBe(react.title);
    fireEvent.change(sel, { target: { value: "react" } });
    fireEvent.click(screen.getByRole("button", { name: "新建会话" }));
    expect(made).toEqual(["workflow"]);
  });

  test.each([
    ["没测过（probe 为 null）", [conn()]],
    ["没测出来（tools 为 null）", [conn({ probe: { model: "deepseek-flash", connect: true, tools: null, checked_at: "t" } })]],
    ["读不到连接（旧后端 404）", null],
  ])("%s：不拦", async (_, items) => {
    const made = view(items as Connection[] | null);
    const sel = (await screen.findByLabelText("分析模式")) as HTMLSelectElement;
    await act(async () => new Promise((r) => setTimeout(r, 10)));
    const react = screen.getByRole("option", { name: "边想边做" }) as HTMLOptionElement;
    expect(react.disabled).toBe(false);
    fireEvent.change(sel, { target: { value: "react" } });
    fireEvent.click(screen.getByRole("button", { name: "新建会话" }));
    expect(made).toEqual(["react"]);
  });
});

test("每轮记下连接名和模型：卡头悬停可见，「查看过程」里写出来；旧消息没有 meta 不显示", async () => {
  const turn = { status: "ok", live: false, events: [{ type: "plan", seq: 0, ts: 0, data: { text: "计划" } },
    { type: "answer", seq: 1, ts: 1, data: { text: "好", forced: false } }],
    result: { ok: true, answer: "好", meta: { connection_name: "我的连接", model: "qwen3-32b" }, timings: { total: 1 } } };
  const { container, rerender } = render(<TurnView turn={turn as never} agent="workflow" chartSrc={(p) => p} />);
  expect(container.querySelector(".acard-time")!.getAttribute("title")).toBe("连接：我的连接 · 模型：qwen3-32b");
  fireEvent.click(screen.getByRole("button", { name: /查看过程/ }));
  expect(screen.getByTestId("turn-meta").textContent).toBe("连接：我的连接 · 模型：qwen3-32b");
  rerender(<TurnView turn={{ ...turn, result: { ok: true, answer: "好" } } as never} agent="workflow" chartSrc={(p) => p} />);
  expect(container.querySelector(".acard-time")!.getAttribute("title")).toBeNull();
});
