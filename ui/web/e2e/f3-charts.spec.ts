import { expect, type Page, test } from "@playwright/test";
import { E2E_TOKEN } from "../playwright.config";
import schema from "../src/generated/chart_schema.json" with { type: "json" };

// F3-ECharts 第一步：五种 kind 各问一轮（假服务 chart-<kind>），后端托管 dist、带 CSP。
// 断言：出现 canvas、图数 = result.charts 的结构化图数；刷新后走重放仍在；全程零外部请求、零 CSP 违规。
const CSV = "城市,销量,利润\n北京,3,1.5\n上海,5,2.5\n广州,2,0.5\n";
const auth = { Authorization: `Bearer ${E2E_TOKEN}` };

async function setScenario(page: Page, model: string) {
  const r = await page.request.put("/settings", { headers: auth, data: { model } });
  expect((await r.json()).model).toBe(model);
}

test.beforeAll(async ({ request }) => {
  test.setTimeout(150_000); // 冷启动预热，同 f3-stop.spec
  expect((await request.put("/settings", { headers: auth, data: { model: "ok" } })).ok()).toBe(true);
  const ds = await (await request.post("/datasets", {
    headers: auth, multipart: { files: { name: "warm.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) } },
  })).json();
  const s = await (await request.post("/sessions", { headers: auth, data: { dataset_id: ds.id } })).json();
  const r = await request.post(`/sessions/${s.id}/messages`, { headers: auth, data: { content: "预热" }, timeout: 140_000 });
  expect(await r.text()).toContain("event: done");
});

test("五种图型：canvas 渲染、图数一致、刷新重放仍在；零外部请求、零 CSP 违规", async ({ page, baseURL }) => {
  test.setTimeout(120_000);
  const origin = new URL(baseURL!).origin;
  const external: string[] = [];
  const sameOriginAssets: string[] = [];
  page.on("request", (req) => {
    const u = new URL(req.url());
    if (u.protocol === "data:" || u.protocol === "blob:") return;
    if (u.origin !== origin) external.push(req.url());
    else if (u.pathname.startsWith("/assets/")) sameOriginAssets.push(u.pathname);
  });
  await page.addInitScript(() => {
    const w = window as unknown as { __csp: string[] };
    w.__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => w.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
  });

  await page.goto(`/#token=${E2E_TOKEN}`);
  await page.getByLabel("选择 CSV 文件").setInputFiles([{ name: "charts.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) }]);
  await page.getByRole("button", { name: "上传" }).click();
  await page.getByTestId("dataset-view").getByRole("button", { name: "新建会话" }).click();
  const sv = page.getByTestId("session-view");

  const kinds = schema.kinds;
  for (const [i, kind] of kinds.entries()) {
    await setScenario(page, `chart-${kind}`);
    await sv.getByLabel("提问").fill(`画 ${kind}`);
    await sv.getByRole("button", { name: "发送" }).click();
    const msg = sv.getByTestId("assistant-msg").nth(i);
    await expect(msg).toContainText("（fake）结论", { timeout: 30_000 });
    await expect(msg.getByTestId("echart")).toHaveCount(1);
    await expect(msg.getByTestId("echart")).toHaveAttribute("data-kind", kind);
    await expect(msg.getByTestId("echart").locator("canvas")).not.toHaveCount(0);
  }

  // 图数 = 库里 result.charts 的结构化图数（每轮 1 张，kind 对得上）
  const sid = await page.evaluate(async (token) => {
    const r = await fetch("/sessions", { headers: { Authorization: `Bearer ${token}` } });
    const list = (await r.json()) as { id: string; title: string }[];
    return list.find((s) => s.title.startsWith("画 "))?.id ?? list[0].id;
  }, E2E_TOKEN);
  const detail = await (await page.request.get(`/sessions/${sid}`, { headers: auth })).json();
  const stored = (detail.messages as { role: string; result?: { charts: { option: { kind: string } | null }[] } }[])
    .filter((m) => m.role === "assistant")
    .map((m) => (m.result?.charts ?? []).filter((c) => c.option).map((c) => c.option!.kind));
  expect(stored).toEqual(kinds.map((k) => [k]));

  // 刷新：重放路径，图仍在
  await page.reload();
  await page.getByRole("navigation", { name: "会话" }).getByRole("button", { name: /画 / }).first().click();
  const again = page.getByTestId("session-view").getByTestId("echart");
  await expect(again).toHaveCount(kinds.length);
  for (const [i, kind] of kinds.entries()) {
    await expect(again.nth(i)).toHaveAttribute("data-kind", kind);
    await expect(again.nth(i).locator("canvas")).not.toHaveCount(0);
  }

  const csp = await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp);
  expect(external).toEqual([]);
  expect(csp).toEqual([]);
  expect(sameOriginAssets.length).toBeGreaterThan(0); // 对照：监听器确实收到了同源 /assets/* 请求
});

// 边界绘制走 canvas（S 10-16 评审）：vitest 里的边界夹具只用 SSR SVG 渲染过，这里补上 canvas 路径。
// 5000 个类目 × 1 个系列 = MAX_POINTS，正好不截断。断言：画出 canvas，尺寸非 0；没有 console error / warning，
// 也没有 [ECharts] log；没有页面异常；没有截断提示；库里存的 option 正好 5000 点。
test("边界：bar 5000 点在 canvas 上画出，console 干净", async ({ page }) => {
  test.setTimeout(120_000);
  const big = "类目,值\n" + Array.from({ length: 5000 }, (_, i) => `c${String(i).padStart(4, "0")},${i % 97}`).join("\n") + "\n";
  const bad: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning" || m.text().startsWith("[ECharts]")) bad.push(`${m.type()}: ${m.text()}`);
  });
  page.on("pageerror", (e) => bad.push(`pageerror: ${e.message}`));

  await setScenario(page, "chart-bar");
  await page.goto(`/#token=${E2E_TOKEN}`);
  await page.getByLabel("选择 CSV 文件").setInputFiles([{ name: "bar5000.csv", mimeType: "text/csv", buffer: Buffer.from(big) }]);
  await page.getByRole("button", { name: "上传" }).click();
  await page.getByTestId("dataset-view").getByRole("button", { name: "新建会话" }).click();
  const sv = page.getByTestId("session-view");
  await sv.getByLabel("提问").fill("画 5000 点");
  await sv.getByRole("button", { name: "发送" }).click();
  const msg = sv.getByTestId("assistant-msg").last();
  await expect(msg).toContainText("（fake）结论", { timeout: 60_000 });
  const chart = msg.getByTestId("echart");
  await expect(chart).toHaveCount(1);
  await expect(chart).toHaveAttribute("data-kind", "bar");
  const canvas = chart.locator("canvas").first();
  await expect(canvas).toBeVisible();
  const box = await canvas.boundingBox();
  expect(box!.width).toBeGreaterThan(0);
  expect(box!.height).toBeGreaterThan(0);
  await expect(msg.locator(".warnings")).toHaveCount(0);

  const sessions = (await (await page.request.get("/sessions", { headers: auth })).json()) as { id: string; title: string }[];
  const sid = sessions.find((s) => s.title.startsWith("画 5000"))!.id;
  const detail = await (await page.request.get(`/sessions/${sid}`, { headers: auth })).json();
  const spec = (detail.messages as { role: string; result?: { charts: { option: { truncated: boolean; option: { series: { data: unknown[] }[] } } | null }[] } }[])
    .filter((m) => m.role === "assistant").at(-1)!.result!.charts[0].option!;
  expect(spec.truncated).toBe(false);
  expect(spec.option.series[0].data).toHaveLength(5000);

  await page.waitForTimeout(500); // 给 ResizeObserver 回调和后续帧留一点时间，再看 console
  expect(bad).toEqual([]);
});
