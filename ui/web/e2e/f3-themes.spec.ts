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
  await sv.getByRole("button", { name: "发送" }).click();
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

// 长轴名：真实字体下（vitest 的 SSR 只有估算字宽）用 fillText + measureText 判。
// bbox 按变换矩阵算：记下 getTransform() 的 a..f 和 measureText 的 actualBoundingBox*（相对锚点，已含 textAlign / textBaseline），
// 把局部四角都变换到设备坐标后取 min/max——旋转过的文本也成立，不再假定不旋转。
// 旋转角取画布上的世界变换（a, b）：y 轴名的元素自身 rotation 是 3π/2，但它先挂在 rotation=π/2 的 transformGroup 下
// 再 decomposeTransform 到 group（echarts 6.1.0 lib/component/axis/AxisBuilder.js:566-585），世界角 = 2π ≡ 0，所以横排。
// 帧：每次 echart 画布 clearRect 记一帧；只判"最后一次画 y 轴名"的那一帧（resize 过渡里会有旧布局的帧）。
type Box = { l: number; t: number; r: number; b: number };
type Draw = { text: string; box: Box; a: number; b: number; rot: number; align: string; w: number; cw: number; ch: number; gen: number; frame: number };
const NUM = /^-?\d+(\.\d+)?$/;
const hit = (p: Box, q: Box) => p.l < q.r && q.l < p.r && p.t < q.b && q.t < p.b;
const mid = (b: Box) => (b.t + b.b) / 2;
const xName = ("x_total_revenue_by_region_".repeat(10)).slice(0, 100);
const yName = ("y_total_revenue_by_region_".repeat(10)).slice(0, 100);
const isName = (d: Draw, full: string) => d.text.length > 3 && full.startsWith(d.text.slice(0, -1));

async function longAxisChart(page: Page) {
  await page.setViewportSize({ width: 1600, height: 900 });
  await page.addInitScript(() => {
    const w = window as unknown as { __draws: Draw[]; __gen: number; __frame: number };
    w.__draws = [];
    w.__gen = 0;
    w.__frame = 0;
    const clear = CanvasRenderingContext2D.prototype.clearRect;
    CanvasRenderingContext2D.prototype.clearRect = function (this: CanvasRenderingContext2D, ...a: [number, number, number, number]) {
      if (this.canvas.closest(".echart")) w.__frame += 1;
      return clear.apply(this, a);
    };
    const orig = CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText = function (this: CanvasRenderingContext2D, text: string, x: number, y: number, mw?: number) {
      if (this.canvas.closest(".echart")) {
        const dpr = window.devicePixelRatio || 1;
        const m = this.measureText(String(text));
        const tf = this.getTransform();
        const pts = [[x - m.actualBoundingBoxLeft, y - m.actualBoundingBoxAscent], [x + m.actualBoundingBoxRight, y - m.actualBoundingBoxAscent],
          [x - m.actualBoundingBoxLeft, y + m.actualBoundingBoxDescent], [x + m.actualBoundingBoxRight, y + m.actualBoundingBoxDescent]]
          .map(([px, py]) => tf.transformPoint(new DOMPoint(px, py)));
        const xs = pts.map((p) => p.x / dpr), ys = pts.map((p) => p.y / dpr);
        w.__draws.push({ text: String(text), box: { l: Math.min(...xs), t: Math.min(...ys), r: Math.max(...xs), b: Math.max(...ys) },
          a: tf.a / dpr, b: tf.b / dpr, rot: Math.round((Math.atan2(tf.b, tf.a) * 180) / Math.PI), align: this.textAlign, w: m.width,
          cw: this.canvas.width / dpr, ch: this.canvas.height / dpr, gen: w.__gen, frame: w.__frame });
      }
      return mw === undefined ? orig.call(this, text, x, y) : orig.call(this, text, x, y, mw);
    };
  });
  await page.goto(`/#token=${E2E_TOKEN}`);
  const sv = await ask(page, `${xName},${yName}\na,3\nb,1\nc,2\n`, "long.csv", "chart-bar", "长轴名");
  return sv.getByTestId("echart").first();
}
// 把画布设成 width×height，返回最后一帧里两个轴名、y 刻度、类目标签，以及 plot 区占比
async function measure(page: Page, chart: Locator, width: number, height: number) {
  const gen = await page.evaluate(([wd, ht]) => {
    const w = window as unknown as { __gen: number };
    w.__gen += 1;
    document.querySelectorAll<HTMLElement>(".echart").forEach((el) => { el.style.width = `${wd}px`; el.style.height = `${ht}px`; });
    return w.__gen;
  }, [width, height]);
  await expect.poll(async () => { const b = (await chart.boundingBox())!; return [b.width, b.height]; }).toEqual([width, height]);
  await expect.poll(() => page.evaluate((g) => (window as unknown as { __draws: Draw[] }).__draws.filter((d) => d.gen === g && d.text.endsWith("\u2026")).length, gen))
    .toBeGreaterThanOrEqual(2);
  await page.waitForTimeout(800);
  const draws = await page.evaluate((g) => (window as unknown as { __draws: Draw[] }).__draws.filter((d) => d.gen === g), gen);
  const lastY = draws.filter((d) => isName(d, yName)).at(-1);
  const frame = lastY ? draws.filter((d) => d.frame === lastY.frame) : [];
  const ticks = frame.filter((d) => NUM.test(d.text) && d.align === "right");
  // plot 区上下沿：数据是 a,3 b,1 c,2，值轴是 [0, 3]。矮画布下 0 和 3 两个刻度会被 hideOverlap 藏掉，
  // 所以不取"画出来的最高 / 最低刻度"，而用画出来的刻度做线性映射，换算 v=3 和 v=0 的像素位置
  const pts = ticks.map((t) => [Number(t.text), mid(t.box)] as const).sort((p, q) => p[0] - q[0]);
  const [v0, y0] = pts[0] ?? [0, NaN], [v1, y1] = pts.at(-1) ?? [1, NaN];
  const at = (v: number) => y0 + ((y1 - y0) / (v1 - v0)) * (v - v0);
  // 阶段 5 收尾 A（P2-19）：柱图数值标签默认开，y 轴按数据量级留顶（applyHeadroom 写 max / interval），轴顶不再是数据最大值 3，
  // 而是画出来的最高刻度（360 高 max 4 interval 1；220 紧凑 max 4 interval 2，首末刻度必画）。没有留顶时 v1 ≤ 3，取 3 与原来相同。
  const plotTop = at(Math.max(3, v1)), plotBottom = at(0);
  return { draws, frame, ticks, plotTop, plotBottom, tickTexts: ticks.map((t) => t.text), plotRatio: (plotBottom - plotTop) / height,
    xn: frame.filter((d) => isName(d, xName)).at(-1), yn: lastY, cats: frame.filter((d) => ["a", "b", "c"].includes(d.text)) };
}
const SIZES = [[320, 360], [640, 360], [1200, 360], [1200, 220]] as const;

test("长轴名：320 / 640 / 1200 宽与 1200×220 矮画布下截断为 …，绘制宽度 ≤ 120+ε，旋转 bbox 在画布内、不压 y 刻度和 plot 区，x 轴名与类目行隔 ≥ 8", async ({ page }) => {
  test.setTimeout(120_000);
  const chart = await longAxisChart(page);
  const eps = 1;
  for (const [width, height] of SIZES) {
    const tag = `${width}x${height}`;
    const m = await measure(page, chart, width, height);
    writeFileSync(test.info().outputPath(`long-axis-${tag}.json`), JSON.stringify({ xn: m.xn, yn: m.yn, ticks: m.ticks, cats: m.cats, plotTop: m.plotTop, plotBottom: m.plotBottom }));
    writeFileSync(test.info().outputPath(`long-axis-${tag}.png`), await chart.screenshot());
    expect(m.draws.filter((d) => d.text === xName || d.text === yName)).toEqual([]); // 没有未截断的全名
    // 前提：这一帧里两个轴名、≥2 个 y 刻度、3 个类目标签都画了（没画就谈不上"在画布内 / 不相交"）
    expect([tag, !!m.yn, !!m.xn, m.ticks.length >= 2, m.cats.length]).toEqual([tag, true, true, true, 3]);
    expect([tag, m.frame[0].ch]).toEqual([tag, height]);
    for (const d of [m.xn!, m.yn!]) {
      expect([tag, d.text.endsWith("\u2026")]).toEqual([tag, true]);
      expect(d.w).toBeLessThanOrEqual(schema.axis_name_max_px + eps);
      const b = d.box;
      expect([tag, d.text, d.rot, b.l >= -eps && b.t >= -eps && b.r <= d.cw + eps && b.b <= d.ch + eps]).toEqual([tag, d.text, d.rot, true]);
    }
    // y 轴名：不压 y 刻度数字，也不进 plot 区（plot 顶 = 最高刻度的中线）
    expect([tag, m.ticks.filter((t) => hit(t.box, m.yn!.box)).map((t) => t.text)]).toEqual([tag, []]);
    expect([tag, m.yn!.box.b <= m.plotTop + eps]).toEqual([tag, true]);
    // x 轴名行与类目行至少隔 8px（nameGap 28 吃掉的余量；主题加 axisLabel.fontSize 时先红在这里）
    expect([tag, mid(m.xn!.box) - Math.max(...m.cats.map((c) => mid(c.box))) >= 8]).toEqual([tag, true]);
    expect([tag, Number.isFinite(m.plotRatio) && m.plotRatio > 0]).toEqual([tag, true]); // 占比可算，下面 test.fail 那条只吞一个数
  }
});

// issue #49（原 test.fail，DEVLOG [40]）：矮画布紧凑几何（compact.ts）。修之前 top 60 + bottom 30 + nameGap 28 = 118px（220 的 54%），
// plot 58px ≈ 26%，且值轴 0 和 3 两个刻度被 hideOverlap 吞掉。判定表：这条从 test.fail 翻成 test，期望值不变（plot ≥ 40%），
// 另加刻度完整：数据范围 [0, 3] 的两端刻度都画出来。360 高不触发紧凑（上一条的 1200×360 / 640×360 照旧）。
test("#49：1200×220 下 plot 区高 ≥ 画布 40%，值轴首末刻度 0 和 4（留顶后的上限）都在", async ({ page }) => {
  test.setTimeout(120_000);
  const chart = await longAxisChart(page);
  const m = await measure(page, chart, 1200, 220);
  writeFileSync(test.info().outputPath("issue49-1200x220.png"), await chart.screenshot());
  expect(m.plotRatio).toBeGreaterThanOrEqual(0.4);
  // 判定表改动（阶段 5 收尾 P2-19）：轴的首末刻度从 0 / 3（数据范围）变成 0 / 4（留顶后的上限，紧凑 N = 3 → step 2）
  expect(m.tickTexts).toContain("0");
  expect(m.tickTexts).toContain("4");
  expect(m.tickTexts).not.toContain("3");
});
