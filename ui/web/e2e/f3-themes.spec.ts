import { expect, type Locator, type Page, test } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { E2E_TOKEN } from "../playwright.config";
import schema from "../src/generated/chart_schema.json" with { type: "json" };

// F3 第四步：主题切换（setTheme，不重跑分析、不重建实例）、持久化、未知名回退；长轴名在真实字体下截断并留在画布内。
// 人眼验收截图写到 test-results（theme-*.png），不做像素比对。
const auth = { Authorization: `Bearer ${E2E_TOKEN}` };
const THEMES = { classic: { label: "经典", bg: [255, 255, 255] }, soft: { label: "柔和", bg: [255, 255, 255] },
  business: { label: "商务蓝", bg: [255, 255, 255] }, darkCanvas: { label: "暗色画布", bg: [0x15, 0x18, 0x1c] } } as const;

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
  await expect(sv.getByTestId("assistant-msg").last()).toContainText("（fake）结论", { timeout: 60_000 });
  return sv;
}
// 画布左上角 (2,2) 的像素：画布背景就是主题 backgroundColor（option 不设背景，留给主题）
const cornerPixel = (chart: Locator) =>
  chart.locator("canvas").first().evaluate((c: HTMLCanvasElement) => [...c.getContext("2d")!.getImageData(2, 2, 1, 1).data.slice(0, 3)]);

test("主题：四套逐个切换不重跑分析，背景与配色跟着变；刷新保持；未知名回退经典", async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1400, height: 900 });
  const posts: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && /\/sessions\/[^/]+\/messages$/.test(new URL(r.url()).pathname)) posts.push(r.url());
  });
  const bad: string[] = [];
  page.on("console", (m) => {
    // 测试自己的 getImageData 读像素会触发 Chrome 的 willReadFrequently 提示，不是产品的告警
    if (m.text().includes("willReadFrequently")) return;
    if (m.type() === "error" || m.type() === "warning" || m.text().startsWith("[ECharts]")) bad.push(`${m.type()}: ${m.text()}`);
  });
  page.on("pageerror", (e) => bad.push(`pageerror: ${e.message}`));
  await page.goto(`/#token=${E2E_TOKEN}`);
  // 饼图 6 个扇区：一张图里看全一套 palette
  const csv = "类别,值\n" + ["甲", "乙", "丙", "丁", "戊", "己"].map((c, i) => `${c},${[30, 24, 18, 12, 9, 7][i]}`).join("\n") + "\n";
  const sv = await ask(page, csv, "theme.csv", "chart-pie", "主题饼图");
  const chart = sv.getByTestId("echart").first();
  const picker = sv.getByLabel("图表主题");
  await expect(picker).toHaveValue("classic"); // 默认经典
  expect(posts).toHaveLength(1);

  for (const [name, t] of Object.entries(THEMES)) {
    await picker.selectOption(name);
    await expect(chart).toHaveAttribute("data-theme", name);
    await expect.poll(() => cornerPixel(chart)).toEqual([...t.bg]);
    await page.waitForTimeout(1200); // 等 setTheme 之后的入场动画结束，截图给人眼验收
    writeFileSync(test.info().outputPath(`theme-${name}.png`), await chart.screenshot());
  }
  expect(posts).toHaveLength(1); // 切了四次主题，没有新的分析请求

  // 刷新：从 localStorage 读回（最后选的是暗色画布）
  await page.reload();
  await page.getByRole("navigation", { name: "会话" }).getByRole("button", { name: /主题饼图/ }).first().click();
  const again = page.getByTestId("session-view").getByTestId("echart").first();
  await expect(page.getByTestId("session-view").getByLabel("图表主题")).toHaveValue("darkCanvas");
  await expect(again).toHaveAttribute("data-theme", "darkCanvas");
  await expect.poll(() => cornerPixel(again)).toEqual([...THEMES.darkCanvas.bg]);

  // 未知主题名（改名 / 删主题 / 手改）：回退经典，不是保持上一个，也不是透明画布
  await page.evaluate(() => localStorage.setItem("datachat.chartTheme", "macarons"));
  await page.reload();
  await page.getByRole("navigation", { name: "会话" }).getByRole("button", { name: /主题饼图/ }).first().click();
  const fallback = page.getByTestId("session-view").getByTestId("echart").first();
  await expect(fallback).toHaveAttribute("data-theme", "classic");
  await expect.poll(() => cornerPixel(fallback)).toEqual([...THEMES.classic.bg]);
  expect(bad).toEqual([]);
});

// 长轴名：真实字体下（vitest 的 SSR 只有估算字宽）用 fillText + measureText 判。三档画布宽度。
type Draw = { text: string; x: number; y: number; w: number; align: string; cw: number; ch: number; gen: number };
test("长轴名：320 / 640 / 1200 三档宽度下截断为 …，实际绘制宽度 ≤ 120+ε，且在画布内", async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1600, height: 900 });
  await page.addInitScript(() => {
    const w = window as unknown as { __draws: Draw[]; __gen: number };
    w.__draws = [];
    w.__gen = 0;
    const orig = CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText = function (this: CanvasRenderingContext2D, text: string, x: number, y: number, mw?: number) {
      if (this.canvas.closest(".echart")) {
        const dpr = window.devicePixelRatio || 1;
        const p = this.getTransform().transformPoint(new DOMPoint(x, y));
        w.__draws.push({ text: String(text), x: p.x / dpr, y: p.y / dpr, w: this.measureText(String(text)).width, align: this.textAlign,
          cw: this.canvas.width / dpr, ch: this.canvas.height / dpr, gen: w.__gen });
      }
      return mw === undefined ? orig.call(this, text, x, y) : orig.call(this, text, x, y, mw);
    };
  });
  await page.goto(`/#token=${E2E_TOKEN}`);
  const xName = ("x_total_revenue_by_region_".repeat(10)).slice(0, 100);
  const yName = ("y_total_revenue_by_region_".repeat(10)).slice(0, 100);
  const sv = await ask(page, `${xName},${yName}\na,3\nb,1\nc,2\n`, "long.csv", "chart-bar", "长轴名");
  const chart = sv.getByTestId("echart").first();
  const eps = 1;
  for (const width of [320, 640, 1200]) {
    const gen = await page.evaluate((wd) => {
      const w = window as unknown as { __gen: number };
      w.__gen += 1;
      document.querySelectorAll<HTMLElement>(".echart").forEach((el) => (el.style.width = `${wd}px`));
      return w.__gen;
    }, width);
    await expect.poll(async () => (await chart.boundingBox())!.width).toBe(width);
    await expect.poll(() => page.evaluate((g) => (window as unknown as { __draws: Draw[] }).__draws.filter((d) => d.gen === g && d.text.endsWith("\u2026")).length, gen))
      .toBeGreaterThanOrEqual(2);
    await page.waitForTimeout(800);
    const draws = await page.evaluate((g) => (window as unknown as { __draws: Draw[] }).__draws.filter((d) => d.gen === g), gen);
    // 轴名：以完整名的前缀开头。前提：两个轴名都画了（没画就谈不上"在画布内"）
    const all = draws.filter((d) => d.text.length > 3 && (xName.startsWith(d.text.slice(0, -1)) || yName.startsWith(d.text.slice(0, -1))));
    // 只判最后一帧：resize 过渡里会有旧布局的帧（实测 320 宽时还画过一次 x=595 的轴名），按轴取最后一次绘制
    const names = ["x", "y"].map((k) => all.filter((d) => d.text[0] === k).at(-1)).filter((d): d is Draw => !!d);
    expect([width, names.length]).toEqual([width, 2]);
    expect(draws.filter((d) => d.text === xName || d.text === yName)).toEqual([]); // 没有未截断的全名
    for (const d of names) {
      expect([width, d.text.endsWith("\u2026")]).toEqual([width, true]);
      expect(d.w).toBeLessThanOrEqual(schema.axis_name_max_px + eps);
      const left = d.align === "center" ? d.x - d.w / 2 : d.align === "right" || d.align === "end" ? d.x - d.w : d.x;
      expect([width, d.text, left >= -eps && left + d.w <= d.cw + eps]).toEqual([width, d.text, true]);
    }
    writeFileSync(test.info().outputPath(`long-axis-${width}.png`), await chart.screenshot());
  }
});
