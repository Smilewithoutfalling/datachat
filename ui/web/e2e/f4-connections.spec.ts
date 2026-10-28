import { expect, type Page, test } from "@playwright/test";
import { E2E_TOKEN } from "../playwright.config";

// 阶段 6.5 §6 第 3 条：新建连接 → 测试 → 设为生效 → 用假模型分析一题，全在后端托管的 dist 上走。
// fake 后端的钥匙串是 fail 后端（playwright.config），Key 存不进去，所以连接用「Ollama」（不需要 Key 的服务商），
// Base URL 改成假模型服务。先建一个 notools 连接（第一个连接自动生效，测出工具调用 ✗ → 数据集页「边想边做」置灰），
// 再建一个 ok 连接，测试两行都 ✓，设为生效后分析一题，回答卡上记着连接名和模型。
// 跑完删掉两个连接：这个 project 的后端是共用的，别的文件靠「环境变量」虚拟连接 + PUT /settings {model} 选场景。
const auth = { Authorization: `Bearer ${E2E_TOKEN}` };
const FAKE_LLM = `http://127.0.0.1:${Number(process.env.E2E_PORT) + 2}/v1`;
const CSV = "城市,销量\n北京,3\n上海,5\n";
const NAMES = ["e2e 不调工具", "e2e 假服务"];

async function cleanup(request: import("@playwright/test").APIRequestContext) {
  const l = await (await request.get("/connections", { headers: auth })).json();
  for (const x of l.items) if (NAMES.includes(x.name)) await request.delete(`/connections/${x.id}`, { headers: auth });
  expect((await (await request.get("/connections", { headers: auth })).json()).active).toBe("env");
}

test.beforeAll(async ({ request }) => {
  test.setTimeout(150_000);
  await cleanup(request);
  // 预热（照 f4-panel）：后端第一次分析要 import pandas / langchain，冷启动挪出用例的超时窗口
  expect((await request.put("/settings", { headers: auth, data: { model: "ok" } })).ok()).toBe(true);
  const ds = await (await request.post("/datasets", {
    headers: auth, multipart: { files: { name: "warm.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) } },
  })).json();
  const s = await (await request.post("/sessions", { headers: auth, data: { dataset_id: ds.id } })).json();
  const r = await request.post(`/sessions/${s.id}/messages`, { headers: auth, data: { content: "预热" }, timeout: 140_000 });
  expect(await r.text()).toContain("event: done");
});

test.afterAll(async ({ request }) => {
  await cleanup(request);
});

async function newConnection(page: Page, name: string, model: string) {
  const view = page.getByTestId("settings-view");
  await view.getByRole("button", { name: "新建连接" }).click();
  const f = view.getByTestId("conn-form");
  await f.getByLabel("服务商").selectOption("ollama");
  await expect(f.getByTestId("no-key-needed")).toBeVisible();          // 不需要 Key 的服务商不显示 Key 输入
  await expect(f.getByLabel("API Key")).toHaveCount(0);
  await f.getByLabel("连接名称").fill(name);
  await f.getByLabel("Base URL").fill(FAKE_LLM);
  await f.getByLabel("模型", { exact: true }).fill(model);
  await f.getByRole("button", { name: "新建并保存" }).click();
  await expect(view.getByTestId("conn-form")).toHaveCount(0);
  return view.getByTestId("conn-card").filter({ hasText: name });
}

test("新建连接 → 测试（两行）→ 设为生效 → 分析一题；工具调用 ✗ 时「边想边做」置灰", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto(`/#token=${E2E_TOKEN}`);
  await page.getByRole("button", { name: "设置" }).click();
  const view = page.getByTestId("settings-view");
  await expect(view.getByTestId("conn-card")).toHaveCount(1);           // 只有「环境变量」
  await expect(view.getByTestId("conn-card").first()).toContainText("环境变量");

  // 第一个连接：建好就生效（环境变量随之不再出现）；测试出工具调用 ✗
  const a = await newConnection(page, NAMES[0], "notools");
  await expect(view.getByTestId("conn-card")).toHaveCount(1);
  await expect(a.getByTestId("conn-active")).toBeVisible();
  await a.getByRole("button", { name: "测试连接" }).click();
  await expect(a.getByTestId("test-connect")).toContainText(/连接正常 · \d+\.\ds · notools/, { timeout: 20_000 });
  await expect(a.getByTestId("test-tools")).toContainText("不支持工具调用");
  await expect(a.getByTestId("conn-probe")).toHaveText("✓ 连接 · ✗ 工具调用");

  // 数据集页：生效连接不支持工具调用 → 「边想边做」不可选
  await page.getByLabel("选择 CSV 文件").setInputFiles([{ name: `conn-${Date.now()}.csv`, mimeType: "text/csv", buffer: Buffer.from(CSV) }]);
  await page.getByRole("button", { name: "上传" }).click();
  const dv = page.getByTestId("dataset-view");
  const react = dv.getByRole("option", { name: "边想边做（不可用）" });
  // Playwright 的 toBeDisabled 对 <select> 里的 <option> 判成 enabled（aria 快照却是 [disabled]），所以直接断言 disabled 属性
  await expect(react).toHaveAttribute("disabled", "");
  expect(await react.getAttribute("title")).toContain(`当前连接「${NAMES[0]}」的模型 notools 测试时没有调用工具`);

  // 第二个连接：测试两行都 ✓，设为生效
  await page.getByRole("button", { name: "设置" }).click();
  const b = await newConnection(page, NAMES[1], "ok");
  await expect(view.getByTestId("conn-card")).toHaveCount(2);
  await expect(b.getByTestId("conn-active")).toHaveCount(0);
  await b.getByRole("button", { name: "测试连接" }).click();
  await expect(b.getByTestId("test-connect")).toContainText(/连接正常 · \d+\.\ds · ok/, { timeout: 20_000 });
  await expect(b.getByTestId("test-tools")).toContainText(/支持 · \d+\.\ds/);
  await b.getByRole("button", { name: "设为生效" }).click();
  await expect(b.getByTestId("conn-active")).toBeVisible();
  await expect(a.getByTestId("conn-active")).toHaveCount(0);
  await expect(view.getByTestId("settings-sources")).toContainText(`当前生效：连接「${NAMES[1]}」，模型 ok`);
  const key = await (await page.request.get("/connections", { headers: auth })).json();
  expect(JSON.stringify(key)).not.toContain("fake-key-not-secret");

  // 分析一题（标准模式）：回答出来，卡头悬停写着连接名和模型；「边想边做」恢复可选
  await page.getByRole("navigation", { name: "数据集" }).getByRole("button", { name: /^conn-/ }).first().click();
  await expect(dv.getByRole("option", { name: "边想边做", exact: true })).not.toHaveAttribute("disabled");
  await dv.getByRole("button", { name: "新建会话" }).click();
  const sv = page.getByTestId("session-view");
  await sv.getByLabel("提问").fill("一共多少行？");
  await sv.getByRole("button", { name: "发送" }).click();
  const msg = sv.getByTestId("assistant-msg").last();
  await expect(msg).toContainText("（fake）结论：数据共有若干行。", { timeout: 60_000 });
  await expect(msg.locator(".acard-time")).toHaveAttribute("title", `连接：${NAMES[1]} · 模型：ok`);
});
