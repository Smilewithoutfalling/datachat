import { expect, type Download, type Locator, type Page, test } from "@playwright/test";
import { readFileSync } from "node:fs";

// 验收 P0-3：标记卡打开时默认展开颜色组；颜色 tile 只在收起时再点（点已展开的会收起）
async function openColors(scope: import("@playwright/test").Locator) {
  const t = scope.getByRole("button", { name: /^颜色/ });
  if ((await t.getAttribute("aria-pressed")) !== "true") await t.click();
}
import { E2E_TOKEN } from "../playwright.config";

// F4 层 1 面板（标记卡）：在后端托管的 dist 上真机跑。改动是否落到图上，用真导出（导出和屏幕走同一个 prepare）比字节；
// 存储键按 <message_id>:<图序号>；Tableau 风主题顺带出截图给 S 人眼看（test-results/f4-*.png）。
const auth = { Authorization: `Bearer ${E2E_TOKEN}` };

async function setScenario(page: Page, model: string) {
  const r = await page.request.put("/settings", { headers: auth, data: { model } });
  expect((await r.json()).model).toBe(model);
}
async function ask(page: Page, csv: string, name: string, model: string, q: string) {
  await setScenario(page, model);
  await page.getByLabel("选择 CSV 文件").setInputFiles([{ name, mimeType: "text/csv", buffer: Buffer.from(csv) }]);
  await page.getByRole("button", { name: "上传" }).click();
  await page.getByTestId("dataset-view").getByRole("button", { name: "新建会话" }).click();
  const sv = page.getByTestId("session-view");
  await sv.getByLabel("提问").fill(q);
  await sv.getByRole("button", { name: "发送" }).click();
  await expect(sv.getByTestId("assistant-msg").last()).toContainText("结论", { timeout: 60_000 });
  return sv;
}
function watch(page: Page, origin: string) {
  const posts: string[] = [];
  const external: string[] = [];
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (u.protocol === "data:" || u.protocol === "blob:") return;
    if (u.origin !== origin) external.push(r.url());
    if (r.method() === "POST" && /\/sessions\/[^/]+\/messages$/.test(u.pathname)) posts.push(r.url());
  });
  const bad: string[] = [];
  page.on("console", (m) => {
    if (m.text().includes("willReadFrequently")) return;
    if (m.type() === "error" || m.type() === "warning" || m.text().startsWith("[ECharts]")) bad.push(`${m.type()}: ${m.text()}`);
  });
  page.on("pageerror", (e) => bad.push(`pageerror: ${e.message}`));
  return { posts, external, bad };
}

type Png = { name: string; bytes: Buffer; width: number; height: number };
/** 点导出，拿到真下载的文件：PNG 签名、IHDR 宽高。 */
async function exportOf(ctl: Locator): Promise<Png> {
  const page = ctl.page();
  const [dl] = await Promise.all([page.waitForEvent("download"), ctl.getByRole("button", { name: "导出 PNG" }).click()]);
  return read(dl);
}
async function read(dl: Download): Promise<Png> {
  expect(await dl.failure()).toBeNull();
  const bytes = readFileSync((await dl.path())!);
  expect(bytes.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
  return { name: dl.suggestedFilename(), bytes, width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}
const CSV = "城市,销量\n北京,3\n上海,5\n广州,2\n深圳,8\n杭州,6\n成都,4\n武汉,7\n西安,1\n";

// 预热（照 f3-stop.spec.ts）：后端进程第一次分析要 import pandas / matplotlib / langchain、建字体缓存，沙箱里 20 秒以上。
// 单独跑这个文件时第一条曾卡在 60 秒的等待上；放在全套里能过，只是因为前面的文件已经把后端热好了（workers: 1、共用一个后端）。
// 只走 API，用 ok 场景完整跑一轮，把冷启动挪出每条用例的超时窗口。
test.beforeAll(async ({ request }) => {
  test.setTimeout(150_000);
  expect((await request.put("/settings", { headers: auth, data: { model: "ok" } })).ok()).toBe(true);
  const ds = await (await request.post("/datasets", {
    headers: auth, multipart: { files: { name: "warm.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) } },
  })).json();
  const s = await (await request.post("/sessions", { headers: auth, data: { dataset_id: ds.id } })).json();
  const r = await request.post(`/sessions/${s.id}/messages`, { headers: auth, data: { content: "预热" }, timeout: 140_000 });
  expect(await r.text()).toContain("event: done");
});


const PIE12 = "品类,销量\n" + Array.from({ length: 12 }, (_, i) => `品类${i + 1},${(i + 1) * 3}`).join("\n") + "\n";

test("柱图：字号 / y 轴上限 / 系列色各自改变导出；存进 datachat.chartEdit:<message_id>:0；重置回到原图；console 干净", async ({ page, baseURL }) => {
  test.setTimeout(150_000);
  await page.setViewportSize({ width: 1400, height: 900 });
  const w = watch(page, new URL(baseURL!).origin);
  await page.goto(`/#token=${E2E_TOKEN}`);
  const sv = await ask(page, CSV, "f4.csv", "chart-bar", "面板");
  const ctl = sv.getByTestId("chart-controls").first();
  const base = await exportOf(ctl);
  await ctl.getByRole("button", { name: "标记" }).click();
  const card = sv.getByTestId("marks-card").first();
  await expect(card).toBeVisible();

  await card.getByRole("button", { name: /^文字/ }).click(); // F4 迭代 V1：tile 改名、role 从 tab 改成 toggle button
  await card.getByRole("button", { name: "大 16" }).click();
  const big = await exportOf(ctl);
  expect(big.bytes.equals(base.bytes)).toBe(false);

  await card.getByRole("button", { name: /^轴/ }).click();
  await card.getByLabel("y 轴最大值").fill("20");
  const capped = await exportOf(ctl);
  expect(capped.bytes.equals(big.bytes)).toBe(false);
  await card.getByLabel("y 轴最小值").fill("30"); // min ≥ max：报错，不生效
  await expect(card.getByRole("alert")).toHaveText("最小值要小于最大值");
  expect((await exportOf(ctl)).bytes.equals(capped.bytes)).toBe(true);
  await card.getByLabel("y 轴最小值").fill("");

  await openColors(card);
  await card.getByRole("button", { name: /颜色 5$/ }).first().click();
  expect((await exportOf(ctl)).bytes.equals(capped.bytes)).toBe(false);

  const keys = await page.evaluate(() => Object.keys(localStorage).filter((k) => k.startsWith("datachat.chartEdit:")));
  expect(keys).toHaveLength(1);
  expect(keys[0]).toMatch(/^datachat\.chartEdit:[^:]+:0$/);
  expect(JSON.parse((await page.evaluate((k) => localStorage.getItem(k), keys[0]))!)).toEqual(
    { yMin: null, yMax: 20, colors: { 0: 4 }, font: "l", other: false });

  await card.getByRole("button", { name: "重置" }).click();
  expect((await exportOf(ctl)).bytes.equals(base.bytes)).toBe(true);
  expect(await page.evaluate(() => Object.keys(localStorage).filter((k) => k.startsWith("datachat.chartEdit:")))).toEqual([]);
  expect(w.external).toEqual([]);
  expect(w.bad).toEqual([]);
});

test("饼图 12 类：轴组 aria-disabled；重复色提示，合并为'其他'改变导出且提示消失；Tableau 风主题截图", async ({ page, baseURL }, info) => {
  test.setTimeout(150_000);
  await page.setViewportSize({ width: 1400, height: 900 });
  const w = watch(page, new URL(baseURL!).origin);
  await page.goto(`/#token=${E2E_TOKEN}`);
  const sv = await ask(page, PIE12, "pie12.csv", "chart-pie", "饼图面板");
  const ctl = sv.getByTestId("chart-controls").first();
  const base = await exportOf(ctl);
  await ctl.getByRole("button", { name: "标记" }).click();
  const card = sv.getByTestId("marks-card").first();
  await expect(card.getByRole("button", { name: /^轴/ })).toHaveAttribute("aria-disabled", "true");
  // 合并已不是独立 tile：在颜色组里（F4 迭代 V1 第 3 条）
  await openColors(card);
  await expect(card.getByTestId("marks-repeat")).toHaveText("12 类，多于 10 色，颜色会重复");
  await card.getByRole("checkbox", { name: "合并为'其他'" }).check();
  await expect(card.getByTestId("marks-repeat")).toHaveCount(0);
  const merged = await exportOf(ctl);
  expect(merged.bytes.equals(base.bytes)).toBe(false);

  await page.getByLabel("图表主题").selectOption({ label: "Tableau 风" });
  // selectOption 不一定派发 mousedown，卡可能还开着：只在关着时再点"样式"，颜色组只在收起时再点
  const btn = ctl.getByRole("button", { name: "标记" });
  if ((await btn.getAttribute("aria-expanded")) !== "true") await btn.click();
  const colors = card.getByRole("button", { name: /^颜色/ });
  if ((await colors.getAttribute("aria-pressed")) !== "true") await colors.click();
  await page.waitForTimeout(300);
  await sv.getByTestId("assistant-msg").last().screenshot({ path: info.outputPath("f4-tableau-pie.png") });
  expect(w.external).toEqual([]);
  expect(w.bad).toEqual([]);
});

// ---- F4 迭代 V1：浮层（phase5「F4 迭代 V1」第 5–8 条）-----------------------------------------------------------------
const PIE = (n: number) => "品类,销量\n" + Array.from({ length: n }, (_, i) => `品类${i + 1},${(i + 1) * 3}`).join("\n") + "\n";

test("浮层：不推开文档流、压在最上层、正常位置向上展开；组多开；理由行一行且柱图饼图同高；5 套主题色块行不溢出", async ({ page }, info) => {
  test.setTimeout(150_000);
  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto(`/#token=${E2E_TOKEN}`);
  const sv = await ask(page, CSV, "pop.csv", "chart-bar", "浮层");
  const ctl = sv.getByTestId("chart-controls").first();
  await sv.getByTestId("echart").first().scrollIntoViewIfNeeded();
  const input = sv.getByLabel("提问");
  const before = await input.boundingBox();
  await page.screenshot({ path: info.outputPath("v1-bar-default.png") });
  await ctl.getByRole("button", { name: "标记" }).click();
  const card = ctl.getByTestId("marks-card");
  await expect(card).toHaveAttribute("data-dir", "up");
  expect(await input.boundingBox()).toEqual(before);
  const top = await card.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return el.contains(document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2));
  });
  expect(top).toBe(true);
  // 组多开（颜色组默认已展开）
  await expect(card.getByRole("button", { name: /^颜色/ })).toHaveAttribute("aria-pressed", "true");
  await card.getByRole("button", { name: /^轴/ }).click();
  await expect(card.getByRole("region")).toHaveCount(2);
  await card.getByRole("button", { name: /^颜色/ }).click();
  await expect(card.getByRole("region")).toHaveCount(1);
  await card.getByRole("button", { name: /^颜色/ }).click();
  await page.screenshot({ path: info.outputPath("v1-bar-card.png") });
  // 理由行：柱图为空，但占一行高
  const why = card.getByTestId("marks-why");
  await expect(why).toHaveText("");
  const barWhyH = (await why.boundingBox())!.height;
  // 色块行不溢出（卡宽账的实测）
  for (const t of ["classic", "soft", "business", "darkCanvas", "tableau"]) {
    await page.getByLabel("图表主题").selectOption(t);
    if ((await ctl.getByRole("button", { name: "标记" }).getAttribute("aria-expanded")) !== "true") await ctl.getByRole("button", { name: "标记" }).click();
    const colors = card.getByRole("button", { name: /^颜色/ });
    if ((await colors.getAttribute("aria-pressed")) !== "true") await colors.click();
    const over = await card.locator(".marks-swatch-list .marks-item").evaluateAll((rows) => rows.filter((r) => r.scrollWidth > r.clientWidth).length);
    expect([t, over]).toEqual([t, 0]);
  }
  await page.getByLabel("图表主题").selectOption("classic");

  const sv2 = await ask(page, PIE12, "pop-pie.csv", "chart-pie", "浮层饼图");
  const ctl2 = sv2.getByTestId("chart-controls").first();
  await sv2.getByTestId("echart").first().scrollIntoViewIfNeeded();
  await ctl2.getByRole("button", { name: "标记" }).click();
  const why2 = ctl2.getByTestId("marks-why");
  await expect(why2).toHaveText("形状：饼图没有可调的形状 · 轴：饼图没有 y 轴");
  const h2 = (await why2.boundingBox())!.height;
  expect(h2).toBe(barWhyH);
  expect(await why2.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true); // 一行放得下，没有被截断
  await openColors(ctl2);
  await page.screenshot({ path: info.outputPath("v1-pie12-card.png") });
});

test("浮层：工具栏滚到 .main 顶部时改向下展开，整体落在 .main 可视区内", async ({ page }) => {
  test.setTimeout(150_000);
  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto(`/#token=${E2E_TOKEN}`);
  const sv = await ask(page, CSV, "down.csv", "chart-bar", "向下");
  const ctl = sv.getByTestId("chart-controls").first();
  // 撑出可滚动的余量后，把工具栏滚到贴着 .main 可视区顶部
  await page.locator(".main").evaluate((m, sel) => {
    const pad = document.createElement("div");
    pad.style.height = "1200px";
    m.appendChild(pad);
    const c = m.querySelector(sel)!;
    m.scrollTop += c.getBoundingClientRect().top - m.getBoundingClientRect().top;
  }, '[data-testid="chart-controls"]');
  await ctl.getByRole("button", { name: "标记" }).click();
  const card = ctl.getByTestId("marks-card");
  await expect(card).toHaveAttribute("data-dir", "down");
  const [c, m] = await Promise.all([card.boundingBox(), page.locator(".main").boundingBox()]);
  expect(c!.y).toBeGreaterThanOrEqual(m!.y);
  expect(c!.y + c!.height).toBeLessThanOrEqual(m!.y + m!.height);
});

test("色块列表：8 个条目不滚动，9 个起滚动", async ({ page }) => {
  test.setTimeout(150_000);
  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto(`/#token=${E2E_TOKEN}`);
  for (const [n, scroll] of [[8, false], [9, true]] as const) {
    const sv = await ask(page, PIE(n), `sw${n}.csv`, "chart-pie", `色块${n}`);
    const ctl = sv.getByTestId("chart-controls").last();
    await sv.getByTestId("echart").last().scrollIntoViewIfNeeded();
    await ctl.getByRole("button", { name: "标记" }).click();
    await openColors(ctl);
    const list = ctl.locator(".marks-swatch-list");
    await expect(list.locator(".marks-item")).toHaveCount(n);
    expect([n, await list.evaluate((el) => el.scrollHeight > el.clientHeight)]).toEqual([n, scroll]);
    await page.keyboard.press("Escape");
  }
});
