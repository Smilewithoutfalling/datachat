import { expect, type Download, type Locator, type Page, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import inject from "../src/generated/inject.json" with { type: "json" };
import { E2E_TOKEN } from "../playwright.config";

// F3 第六步：导出 PNG，在后端托管的 dist 上真机跑（canvas、真实 CSP）。建在真下载上：方案阶段已实测
// waitForEvent("download") + path() 对 data URL 拿得到字节（S 10-19 要求先验证）。
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
// F4 迭代 V1：开关在标记卡的组里。打开卡（已开不重复点）、展开组（已展开不重复点），返回卡。卡和样式按钮都在 chart-controls 里。
async function group(ctl: Locator, name: string): Promise<Locator> {
  const btn = ctl.getByRole("button", { name: "样式" });
  if ((await btn.getAttribute("aria-expanded")) !== "true") await btn.click();
  const card = ctl.getByTestId("marks-card");
  const t = card.getByRole("button", { name: new RegExp("^" + name) });
  if ((await t.getAttribute("aria-pressed")) !== "true") await t.click();
  return card;
}
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
/** 在页面里解码（img-src 允许 data:）：左上角 (2,2) 的颜色、和左上角颜色不同的像素数。 */
async function pixels(page: Page, png: Png): Promise<{ corner: string; nonBg: number }> {
  return page.evaluate(async (b64) => {
    const img = new Image();
    img.src = `data:image/png;base64,${b64}`;
    await img.decode();
    const c = document.createElement("canvas");
    c.width = img.width;
    c.height = img.height;
    const g = c.getContext("2d")!;
    g.drawImage(img, 0, 0);
    const d = g.getImageData(0, 0, c.width, c.height).data;
    const at = (2 * c.width + 2) * 4;
    const corner = "#" + [d[at], d[at + 1], d[at + 2]].map((v) => v.toString(16).padStart(2, "0")).join("").toUpperCase();
    let nonBg = 0;
    for (let i = 0; i < d.length; i += 4) if (Math.abs(d[i] - d[at]) + Math.abs(d[i + 1] - d[at + 1]) + Math.abs(d[i + 2] - d[at + 2]) > 30) nonBg++;
    return { corner, nonBg };
  }, png.bytes.toString("base64"));
}
async function sizeOf(chart: Locator) {
  return chart.evaluate((el) => ({ w: el.clientWidth, h: el.clientHeight }));
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

async function shiftWheel(page: Page, chart: Locator) {
  await chart.scrollIntoViewIfNeeded();
  const b = (await chart.boundingBox())!;
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
  await page.keyboard.down("Shift");
  for (let i = 0; i < 5; i++) await page.mouse.wheel(0, -120);
  await page.keyboard.up("Shift");
  await page.mouse.move(5, 5);
}

test("导出 PNG：真下载拿到 PNG，宽高是容器的 2 倍、非空；文件名清洗；不发分析请求、零外部请求、console 干净", async ({ page, baseURL }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1400, height: 900 });
  const w = watch(page, new URL(baseURL!).origin);
  await page.goto(`/#token=${E2E_TOKEN}`);
  const sv = await ask(page, inject.csv, "inject.csv", "inject-bar", "注入导出");
  const chart = sv.getByTestId("echart").first();
  const png = await exportOf(sv.getByTestId("chart-controls").first());
  const { w: cw, h: ch } = await sizeOf(chart);
  expect([png.width, png.height]).toEqual([cw * 2, ch * 2]);
  expect((await pixels(page, png)).nonBg).toBeGreaterThan(1000);
  expect(png.name).toBe("_img src=x onerror=_window.__pwned=1__.png"); // 标题是 P1
  expect(await page.evaluate(() => (window as unknown as { __pwned?: number }).__pwned)).toBeUndefined();
  expect(w.posts).toHaveLength(1);
  expect(w.external).toEqual([]);
  expect(w.bad).toEqual([]);
});

test("单系列类目 bar：先确认 ✅ 集合正好六个，再逐个打开与全关的导出不同，全开也不同", async ({ page, baseURL }) => {
  test.setTimeout(150_000);
  await page.setViewportSize({ width: 1400, height: 900 });
  const w = watch(page, new URL(baseURL!).origin);
  await page.goto(`/#token=${E2E_TOKEN}`);
  const sv = await ask(page, CSV, "sw.csv", "chart-bar", "开关导出");
  const ctl = sv.getByTestId("chart-controls").first();
  // ✅ 集合由 compat() 决定，UI 上就是 enabled；❌ 格的全开 == 全关，断言恒真，所以先把集合钉死（S 10-19）
  // F4 迭代 V1 起不兼容的不渲染：集合 = 卡里（五组全展开）渲染出来的开关 + 工具栏上的排序
  for (const g of ["颜色", "标签", "形状", "轴"]) await group(ctl, g);
  const card = ctl.getByTestId("marks-card");
  const boxes = ["数值标签", "堆叠", "平滑", "渐变", "圆角", "平均线和极值", "缩放"];
  const enabled: string[] = [];
  for (const name of boxes) if ((await card.getByRole("checkbox", { name }).count()) === 1) enabled.push(name);
  if ((await card.getByRole("group", { name: "图例位置" }).count()) === 1) enabled.push("图例位置");
  if ((await ctl.getByLabel("排序").count()) === 1) enabled.push("排序");
  expect(enabled.sort()).toEqual(["数值标签", "渐变", "圆角", "平均线和极值", "缩放", "排序"].sort());

  const off = await exportOf(ctl);
  for (const name of ["数值标签", "渐变", "圆角", "平均线和极值", "缩放"]) {
    const box = card.getByRole("checkbox", { name });
    await box.check();
    const on = await exportOf(ctl);
    await box.uncheck();
    // 缩放开着、窗口是全量时画面与全关相同（inside 不画任何东西），这一格的"不同"要等下面缩过之后才成立
    if (name === "缩放") expect(on.bytes.equals(off.bytes)).toBe(true);
    else expect([name, on.bytes.equals(off.bytes)]).toEqual([name, false]);
  }
  await ctl.getByLabel("排序").selectOption("desc");
  expect((await exportOf(ctl)).bytes.equals(off.bytes)).toBe(false);
  for (const name of ["数值标签", "渐变", "圆角", "平均线和极值", "缩放"]) await card.getByRole("checkbox", { name }).check();
  expect((await exportOf(ctl)).bytes.equals(off.bytes)).toBe(false);
  expect(w.posts).toHaveLength(1);
  expect(w.bad).toEqual([]);
});

test("交互态：缩放开关关着时 Shift + 滚轮后导出与初始相同、开着时不同（钉住开关本身）；图例点掉一个系列后导出不同；刷新后 view 清空、导出回到初始", async ({ page, baseURL }) => {
  test.setTimeout(150_000);
  await page.setViewportSize({ width: 1400, height: 900 });
  const w = watch(page, new URL(baseURL!).origin);
  await page.goto(`/#token=${E2E_TOKEN}`);

  // 缩放：单系列柱图
  const sv = await ask(page, CSV, "zoom.csv", "chart-bar", "缩放导出");
  const chart = sv.getByTestId("echart").first();
  const ctl = sv.getByTestId("chart-controls").first();
  // 对照（S 10-19 第二轮）：下面"缩过之后导出不同"的前提是开关真的开着；开关写坏成恒开 / 恒关时，只有这组对照会红
  const initial = await exportOf(ctl);
  await shiftWheel(page, chart);
  expect((await exportOf(ctl)).bytes.equals(initial.bytes)).toBe(true);
  const zoom = (await group(ctl, "轴")).getByRole("checkbox", { name: "缩放" });
  await zoom.check();
  await page.keyboard.press("Escape"); // 卡盖在图上，滚轮前关掉
  const full = await exportOf(ctl);
  expect(full.bytes.equals(initial.bytes)).toBe(true); // inside 不画东西：全量窗口时与关着相同
  await shiftWheel(page, chart);
  const zoomed = await exportOf(ctl);
  expect(zoomed.bytes.equals(full.bytes)).toBe(false);
  // 关掉再打开：屏幕是真相源，回读不到区间，窗口回到全量，不跳回刚才缩的位置（S 10-19 第二轮第一节）
  await (await group(ctl, "轴")).getByRole("checkbox", { name: "缩放" }).uncheck();
  await (await group(ctl, "轴")).getByRole("checkbox", { name: "缩放" }).check();
  await page.keyboard.press("Escape");
  expect((await exportOf(ctl)).bytes.equals(full.bytes)).toBe(true);

  // 图例：多系列（注入场景的第一张是宽表，两个以上系列、图例在底部）。图例项的位置不读内部状态：沿底边扫，
  // 点一下、移开指针，画面变了就是点中了一项（点空白不变）
  const sv2 = await ask(page, inject.csv, "legend.csv", "inject-bar", "图例导出");
  const chart2 = sv2.getByTestId("echart").first();
  const ctl2 = sv2.getByTestId("chart-controls").first();
  const before = await exportOf(ctl2);
  await chart2.scrollIntoViewIfNeeded();
  const b2 = (await chart2.boundingBox())!;
  const canvasShot = () => chart2.locator("canvas").first().evaluate((c: HTMLCanvasElement) => c.toDataURL());
  await page.mouse.move(5, 5);
  await page.waitForTimeout(600);
  const still = await canvasShot();
  let toggled = false;
  for (let x = b2.x + b2.width * 0.25; x < b2.x + b2.width * 0.75 && !toggled; x += 12) {
    await page.mouse.click(x, b2.y + b2.height - 14);
    await page.mouse.move(5, 5);
    await page.waitForTimeout(600);
    toggled = (await canvasShot()) !== still;
  }
  expect(toggled).toBe(true);
  const hidden = await exportOf(ctl2);
  expect(hidden.bytes.equals(before.bytes)).toBe(false);

  // 刷新：view 不持久化，回到全量、全显
  await page.reload();
  await page.getByRole("navigation", { name: "会话" }).getByRole("button", { name: /图例导出/ }).first().click();
  const again = await exportOf(page.getByTestId("session-view").getByTestId("chart-controls").first());
  expect(again.bytes.equals(before.bytes)).toBe(true);
  expect(w.posts).toHaveLength(2);
  expect(w.bad).toEqual([]);
});

test("暗色画布：勾「导出为浅色（经典配色）」后左上角 #FFFFFF，不勾是 #15181C；经典主题下没有这个勾选", async ({ page, baseURL }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1400, height: 900 });
  const w = watch(page, new URL(baseURL!).origin);
  await page.goto(`/#token=${E2E_TOKEN}`);
  const sv = await ask(page, CSV, "dark.csv", "chart-bar", "暗色导出");
  const ctl = sv.getByTestId("chart-controls").first();
  const light = ctl.getByRole("checkbox", { name: "导出为浅色（经典配色）" });
  await expect(light).toHaveCount(0);
  await sv.getByLabel("图表主题").selectOption("darkCanvas");
  expect((await pixels(page, await exportOf(ctl))).corner).toBe("#15181C");
  await light.check();
  expect((await pixels(page, await exportOf(ctl))).corner).toBe("#FFFFFF");
  await sv.getByLabel("图表主题").selectOption("classic");
  expect(w.bad).toEqual([]);
});

test("matplotlib 的静态图：有「静态图」标注，没有导出按钮", async ({ page, baseURL }) => {
  test.setTimeout(120_000);
  const w = watch(page, new URL(baseURL!).origin);
  await page.goto(`/#token=${E2E_TOKEN}`);
  const sv = await ask(page, CSV, "mpl.csv", "chart-matplotlib", "静态图");
  const fig = sv.getByTestId("chart-static");
  await expect(fig).toHaveCount(1);
  await expect(fig).toContainText("静态图（由 matplotlib 生成），可右键另存为");
  await expect(fig.locator("img")).toHaveJSProperty("complete", true);
  await expect(sv.getByRole("button", { name: "导出 PNG" })).toHaveCount(0);
  expect(w.bad).toEqual([]);
});
