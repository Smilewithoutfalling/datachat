import { expect, type Locator, type Page, test } from "@playwright/test";
import { E2E_TOKEN } from "../playwright.config";

// F3 第五步：开关 / 换图型 / 缩放 / 渐变切主题，在后端托管的 dist 上真机跑（canvas）。
// 判据只用像素（toDataURL 等待画面稳定后比较）和 DOM 状态，不读 echarts 内部。
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
  return askAgain(page, q, 1);
}
async function askAgain(page: Page, q: string, n: number) {
  const sv = page.getByTestId("session-view");
  await sv.getByLabel("提问").fill(q);
  await sv.getByRole("button", { name: "提问" }).click();
  await expect(sv.getByTestId("assistant-msg")).toHaveCount(n, { timeout: 60_000 });
  await expect(sv.getByTestId("assistant-msg").last()).toContainText("（fake）结论", { timeout: 60_000 });
  return sv;
}
/** 画面稳定（连续两次相同，跨过入场 / 过渡动画）后的 canvas 内容 */
async function snap(chart: Locator): Promise<string> {
  const read = () => chart.locator("canvas").first().evaluate((c: HTMLCanvasElement) => c.toDataURL());
  let prev = await read();
  for (let i = 0; i < 20; i++) {
    await chart.page().waitForTimeout(300);
    const cur = await read();
    if (cur === prev) return cur;
    prev = cur;
  }
  throw new Error("画面 6 秒内没有稳定");
}
function watch(page: Page) {
  const posts: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && /\/sessions\/[^/]+\/messages$/.test(new URL(r.url()).pathname)) posts.push(r.url());
  });
  const bad: string[] = [];
  page.on("console", (m) => {
    if (m.text().includes("willReadFrequently")) return;
    if (m.type() === "error" || m.type() === "warning" || m.text().startsWith("[ECharts]")) bad.push(`${m.type()}: ${m.text()}`);
  });
  page.on("pageerror", (e) => bad.push(`pageerror: ${e.message}`));
  return { posts, bad };
}
const CSV = "类目,值\n" + Array.from({ length: 30 }, (_, i) => `k${String(i).padStart(2, "0")},${(i * 37) % 101 + 5}`).join("\n") + "\n";

test("开关：逐个打开像素有变化、不发新的分析请求；不兼容的 disabled；刷新后偏好保持；同图型的新图继承", async ({ page }) => {
  test.setTimeout(150_000);
  await page.setViewportSize({ width: 1400, height: 900 });
  const { posts, bad } = watch(page);
  await page.goto(`/#token=${E2E_TOKEN}`);
  const sv = await ask(page, CSV, "sw.csv", "chart-bar", "开关柱图");
  const chart = sv.getByTestId("echart").first();
  const ctl = sv.getByTestId("chart-controls").first();
  const instance = await chart.getAttribute("data-instance");
  const base = await snap(chart);

  for (const name of ["数值标签", "渐变", "圆角", "平均线和极值"]) {
    const box = ctl.getByRole("checkbox", { name });
    await box.check();
    expect([name, (await snap(chart)) !== base]).toEqual([name, true]);
    await box.uncheck();
    expect([name, (await snap(chart)) === base]).toEqual([name, true]);
  }
  await ctl.getByLabel("排序").selectOption("desc");
  expect((await snap(chart)) !== base).toBe(true);
  await ctl.getByLabel("排序").selectOption("off");
  // 单系列柱图：堆叠 / 平滑 / 图例位置不兼容
  for (const name of ["堆叠", "平滑"]) await expect(ctl.getByRole("checkbox", { name })).toBeDisabled();
  await expect(ctl.getByLabel("图例位置")).toBeDisabled();
  expect(posts).toHaveLength(1);
  await expect(chart).toHaveAttribute("data-instance", instance!);

  // 偏好按图型存：刷新后保持；同一会话再出一张柱图，直接继承
  await ctl.getByRole("checkbox", { name: "数值标签" }).check();
  await page.reload();
  await page.getByRole("navigation", { name: "会话" }).getByRole("button", { name: /开关柱图/ }).first().click();
  const sv2 = page.getByTestId("session-view");
  await expect(sv2.getByTestId("chart-controls").first().getByRole("checkbox", { name: "数值标签" })).toBeChecked();
  await askAgain(page, "再来一张", 2);
  await expect(sv2.getByTestId("chart-controls")).toHaveCount(2);
  await expect(sv2.getByTestId("chart-controls").nth(1).getByRole("checkbox", { name: "数值标签" })).toBeChecked();
  expect(JSON.parse((await page.evaluate(() => localStorage.getItem("datachat.chartUi:bar")))!).label).toBe(true);
  expect(bad).toEqual([]);
});

test("换图型：柱 → 饼 → 柱，回来后画面与初始相同；刷新回到后端图型", async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1400, height: 900 });
  const { posts, bad } = watch(page);
  await page.goto(`/#token=${E2E_TOKEN}`);
  const csv = "城市,销量\n北京,3\n上海,5\n广州,2\n深圳,8\n杭州,6\n";
  const sv = await ask(page, csv, "kind.csv", "chart-bar", "换图型");
  const chart = sv.getByTestId("echart").first();
  const kind = sv.getByTestId("chart-controls").first().getByLabel("图型");
  const base = await snap(chart);
  expect(await kind.locator('option[value="scatter"]').evaluate((o: HTMLOptionElement) => [o.disabled, o.title]))
    .toEqual([true, "散点图不能和其他图型互换"]);
  await kind.selectOption("pie");
  await expect(chart).toHaveAttribute("data-shown-kind", "pie");
  await expect(chart).toHaveAttribute("data-kind", "bar"); // spec.kind 是后端真相，不变
  expect((await snap(chart)) !== base).toBe(true);
  await kind.selectOption("bar");
  await expect(chart).toHaveAttribute("data-shown-kind", "bar");
  expect((await snap(chart)) === base).toBe(true);
  await kind.selectOption("line");
  await page.reload();
  await page.getByRole("navigation", { name: "会话" }).getByRole("button", { name: /换图型/ }).first().click();
  await expect(page.getByTestId("session-view").getByTestId("echart").first()).toHaveAttribute("data-shown-kind", "bar");
  expect(posts).toHaveLength(1);
  expect(bad).toEqual([]);
});

test("缩放：普通滚轮滚页面、图不动；Shift + 滚轮缩放；双击空白处还原", async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1400, height: 600 }); // 矮视口：.main 一定能滚
  const { bad } = watch(page);
  await page.goto(`/#token=${E2E_TOKEN}`);
  const sv = await ask(page, CSV, "zoom.csv", "chart-bar", "缩放柱图");
  const chart = sv.getByTestId("echart").first();
  await sv.getByTestId("chart-controls").first().getByRole("checkbox", { name: "缩放" }).check();
  await expect(sv.getByText("Shift + 滚轮缩放，拖动平移，双击空白处还原")).toBeVisible();
  const main = page.locator(".main");
  await main.evaluate((m) => (m.scrollTop = 0));
  await chart.scrollIntoViewIfNeeded();
  // 悬停会画 tooltip / axisPointer，每次取画面前把指针移出图（侧栏左上角）
  const still = async () => { await page.mouse.move(5, 5); return snap(chart); };
  const full = await still();
  const center = async () => { const b = (await chart.boundingBox())!; return [b.x + b.width / 2, b.y + b.height / 2] as const; };

  // 这条才是重点：证明没劫持页面滚动（inside 唯一的失败模式）
  // 指针放在 plot 区中心：echarts 的 RoamController 只在 grid 内吞事件（见 EChart.tsx 的注释），边缘测不出问题。
  // 方向取还能滚的那一边（图在页面底部时 .main 已经滚到底）
  const top0 = await main.evaluate((m) => m.scrollTop);
  const dir = top0 > 0 ? -1 : 1;
  await page.mouse.move(...(await center()));
  await page.mouse.wheel(0, 120 * dir);
  await expect.poll(async () => ((await main.evaluate((m) => m.scrollTop)) - top0) * dir).toBeGreaterThan(0);
  expect((await still()) === full).toBe(true);

  await page.mouse.move(...(await center()));
  await page.keyboard.down("Shift");
  for (let i = 0; i < 5; i++) await page.mouse.wheel(0, -120);
  await page.keyboard.up("Shift");
  const zoomed = await still();
  expect(zoomed !== full).toBe(true);

  // 双击空白：画布右上角（标题在中间、单系列没有图例）
  const b = (await chart.boundingBox())!;
  await page.mouse.dblclick(b.x + b.width - 8, b.y + 8);
  expect((await still()) === full).toBe(true);
  expect(bad).toEqual([]);
});

test("渐变开着切主题：实例不重建、不发分析请求，画面跟着变；主题配色差异不只在角上（第四步评审五）", async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1400, height: 900 });
  const { posts, bad } = watch(page);
  await page.goto(`/#token=${E2E_TOKEN}`);
  const csv = "城市,销量\n北京,3\n上海,5\n广州,2\n深圳,8\n杭州,6\n";
  const sv = await ask(page, csv, "grad.csv", "chart-bar", "渐变主题");
  const chart = sv.getByTestId("echart").first();
  const picker = sv.getByLabel("图表主题");
  const instance = await chart.getAttribute("data-instance");

  // 渐变关：classic 与 soft 的像素差异必须出现在左上角 10×10 以外（不只是背景角）
  const pixels = () => chart.locator("canvas").first().evaluate((c: HTMLCanvasElement) => Array.from(c.getContext("2d")!.getImageData(0, 0, c.width, c.height).data));
  await snap(chart);
  const classic = await pixels();
  await picker.selectOption("soft");
  await snap(chart);
  const soft = await pixels();
  const width = await chart.locator("canvas").first().evaluate((c: HTMLCanvasElement) => c.width);
  const dpr = await page.evaluate(() => window.devicePixelRatio || 1);
  let diffOutside = 0;
  for (let i = 0; i < classic.length; i += 4) {
    const p = i / 4, x = p % width, y = Math.floor(p / width);
    if (x < 10 * dpr && y < 10 * dpr) continue;
    if (classic[i] !== soft[i] || classic[i + 1] !== soft[i + 1] || classic[i + 2] !== soft[i + 2]) diffOutside++;
  }
  expect(diffOutside).toBeGreaterThan(100);

  await sv.getByTestId("chart-controls").first().getByRole("checkbox", { name: "渐变" }).check();
  const softGrad = await snap(chart);
  await picker.selectOption("business");
  const businessGrad = await snap(chart);
  expect(businessGrad !== softGrad).toBe(true);
  await expect(chart).toHaveAttribute("data-instance", instance!);
  expect(posts).toHaveLength(1);
  await picker.selectOption("classic");
  expect(bad).toEqual([]);
});
