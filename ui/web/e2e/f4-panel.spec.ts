import { expect, type Download, type Locator, type Page, test } from "@playwright/test";
import { readFileSync } from "node:fs";
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
  await sv.getByRole("button", { name: "提问" }).click();
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
  await ctl.getByRole("button", { name: "样式" }).click();
  const card = sv.getByTestId("marks-card").first();
  await expect(card).toBeVisible();

  await card.getByRole("tab", { name: /字号/ }).click();
  await card.getByRole("button", { name: "大 16" }).click();
  const big = await exportOf(ctl);
  expect(big.bytes.equals(base.bytes)).toBe(false);

  await card.getByRole("tab", { name: /轴范围/ }).click();
  await card.getByLabel("y 轴最大值").fill("20");
  const capped = await exportOf(ctl);
  expect(capped.bytes.equals(big.bytes)).toBe(false);
  await card.getByLabel("y 轴最小值").fill("30"); // min ≥ max：报错，不生效
  await expect(card.getByRole("alert")).toHaveText("最小值要小于最大值");
  expect((await exportOf(ctl)).bytes.equals(capped.bytes)).toBe(true);
  await card.getByLabel("y 轴最小值").fill("");

  await card.getByRole("tab", { name: /颜色/ }).click();
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

test("饼图 12 类：轴范围禁用；合并为'其他'改变导出；Tableau 风主题截图", async ({ page, baseURL }, info) => {
  test.setTimeout(150_000);
  await page.setViewportSize({ width: 1400, height: 900 });
  const w = watch(page, new URL(baseURL!).origin);
  await page.goto(`/#token=${E2E_TOKEN}`);
  const sv = await ask(page, PIE12, "pie12.csv", "chart-pie", "饼图面板");
  const ctl = sv.getByTestId("chart-controls").first();
  const base = await exportOf(ctl);
  await ctl.getByRole("button", { name: "样式" }).click();
  const card = sv.getByTestId("marks-card").first();
  await expect(card.getByRole("tab", { name: /轴范围/ })).toBeDisabled();
  await card.getByRole("tab", { name: /合并/ }).click();
  await card.getByRole("checkbox").check();
  const merged = await exportOf(ctl);
  expect(merged.bytes.equals(base.bytes)).toBe(false);

  await page.getByLabel("图表主题").selectOption({ label: "Tableau 风" });
  await card.getByRole("tab", { name: /颜色/ }).click();
  await page.waitForTimeout(300);
  await sv.getByTestId("assistant-msg").last().screenshot({ path: info.outputPath("f4-tableau-pie.png") });
  expect(w.external).toEqual([]);
  expect(w.bad).toEqual([]);
});
