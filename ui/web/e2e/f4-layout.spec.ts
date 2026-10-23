import { expect, type Page, test } from "@playwright/test";
import { E2E_TOKEN } from "../playwright.config";

// V2a 验收的布局修正，钉住几何，免得下次动布局时静默回归（S 10-22 r2 §5⑤）：
// - P0-1：输入区是 flex 尾部、不占滚动区。打开会话 / 新一轮收尾后落在底部；滚到底时最后一条消息完整露在输入区之上。
// - P0-2：删除对话框有不透明的遮罩。
// - P0-5：··· 菜单夹在视口里（左右各 ≥ 8px）。
const auth = { Authorization: `Bearer ${E2E_TOKEN}` };
const SALES = "城市,销量,利润\n深圳,412,1.5\n上海,365,2.5\n北京,290,0.5\n广州,217,1.1\n";

async function geometry(page: Page) {
  return page.evaluate(() => {
    const sv = document.querySelector('[data-testid="session-view"]')!;
    const main = sv.querySelector(".main") as HTMLElement;
    const comp = sv.querySelector(".composer-wrap")!.getBoundingClientRect();
    const msgs = sv.querySelectorAll('[data-testid="assistant-msg"]');
    const last = msgs[msgs.length - 1].getBoundingClientRect();
    const m = main.getBoundingClientRect();
    return {
      atBottom: main.scrollHeight - main.scrollTop - main.clientHeight,
      overflow: main.scrollHeight > main.clientHeight,
      mainBottom: m.bottom, compTop: comp.top, lastBottom: last.bottom,
    };
  });
}

test("输入区不遮内容：1024×768 下两轮带图，落在底部，最后一张卡完整在输入区之上；重开会话也落在底部", async ({ page }) => {
  // 两轮带图在冷启动下会超过默认 30s（r3 那次 1 failed 就是这里：assistant-msg 0/1 时被 30s 测试超时截断）
  test.setTimeout(120_000);
  // 文件名带时间戳：--repeat-each 共用一个后端，同名数据集会让按名字点的定位器撞 strict mode
  const file = `layout-${Date.now()}.csv`;
  await page.setViewportSize({ width: 1024, height: 768 });
  expect((await page.request.put("/settings", { headers: auth, data: { model: "chart-bar" } })).ok()).toBe(true);
  await page.goto(`/#token=${E2E_TOKEN}`);
  await page.getByLabel("选择 CSV 文件").setInputFiles([{ name: file, mimeType: "text/csv", buffer: Buffer.from(SALES) }]);
  await page.getByRole("button", { name: "上传" }).click();
  await page.getByTestId("dataset-view").getByRole("button", { name: "新建会话" }).click();
  const sv = page.getByTestId("session-view");
  for (const [i, q] of ["画各城市销量柱状图", "再画一次"].entries()) {
    await sv.getByLabel("提问").fill(q);
    await sv.getByRole("button", { name: "发送" }).click();
    await expect(sv.getByTestId("assistant-msg")).toHaveCount(i + 1, { timeout: 60_000 }); // 这一轮收尾、换成库里的版本
  }
  await expect(sv.locator("canvas").first()).toBeVisible();
  // 条件式等待（PR #70 评审 §4）：不假设 400ms 内 ResizeObserver、滚动、字体都已就绪；
  // toPass 反复重算几何直到全部断言成立，10s 还不成立才红，红了说明真没落到底而不是"刚好没等够"
  // 前提在 toPass 外断言一次：内容确实比视口高，否则这条测不出东西；前提不成立应立刻红，而不是重试 10s 后报到别的断言上
  const check = async () => {
    expect((await geometry(page)).overflow).toBe(true);
    await expect(async () => {
      const g = await geometry(page);
      expect(g.atBottom).toBeLessThanOrEqual(2);
      expect(Math.abs(g.mainBottom - g.compTop)).toBeLessThanOrEqual(1); // 滚动区下沿就是输入区上沿，不重叠
      expect(g.lastBottom).toBeLessThanOrEqual(g.compTop); // 最后一张卡（含控件行、反馈栏）完整可见
    }).toPass({ timeout: 10_000 });
  };
  await check();
  // 去数据集页再回来：重新挂载，落在底部
  await page.getByRole("button", { name: "会话列表" }).click();
  await page.getByRole("button", { name: new RegExp(`^${file.replace(".", "\\.")}`) }).click();
  await page.getByTestId("dataset-view").waitFor();
  await page.getByRole("button", { name: "会话列表" }).click();
  await page.locator(".sess-row").first().click();
  await expect(sv.getByTestId("assistant-msg")).toHaveCount(2);
  await check();
});

test("删除对话框有遮罩；会话 ··· 菜单夹在视口里", async ({ page }) => {
  const file = `menu-${Date.now()}.csv`;
  // 首屏 GET /datasets 扣住到上传完成后才放：上传先完成、旧列表后到，新数据集不能被冲掉（r4 全量跑偶发 1 failed 的根因，Shell dsGen）
  let held = false;
  let release!: () => void;
  const late = new Promise<void>((r) => (release = r));
  await page.route(/\/datasets$/, async (route) => {
    if (route.request().method() !== "GET" || held) return route.continue();
    held = true;
    const res = await route.fetch();
    await late;
    await route.fulfill({ response: res });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/#token=${E2E_TOKEN}`);
  await page.getByLabel("选择 CSV 文件").setInputFiles([{ name: file, mimeType: "text/csv", buffer: Buffer.from(SALES) }]);
  await page.getByRole("button", { name: "上传" }).click();
  await page.getByTestId("dataset-view").getByRole("button", { name: "新建会话" }).click();
  await page.getByTestId("session-view").getByLabel("提问").waitFor();
  release();
  await expect(page.getByRole("navigation", { name: "数据集" }).getByRole("button", { name: new RegExp(`^${file.replace(".", "\\.")}`) })).toBeVisible();

  // 顶栏右上角的 ···：贴着视口右缘，原来菜单会被裁出去（P0-5）
  await page.getByTestId("session-view").getByRole("button", { name: "会话操作" }).click();
  const box = await page.getByRole("menu").evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { left: r.left, right: r.right, vw: window.innerWidth };
  });
  expect(box.left).toBeGreaterThanOrEqual(8);
  expect(box.right).toBeLessThanOrEqual(box.vw - 8);
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: new RegExp(`^${file.replace(".", "\\.")}`) }).click();
  await page.getByRole("button", { name: "数据集操作" }).click();
  await page.getByRole("menuitem", { name: "删除数据集" }).click();
  const bg = await page.locator("dialog.dialog[open]").evaluate((d) => getComputedStyle(d, "::backdrop").backgroundColor);
  const alpha = /rgba?\(([^)]+)\)/.exec(bg)![1].split(",").map((x) => Number(x.trim()));
  expect(alpha.length === 4 ? alpha[3] : 1).toBeGreaterThan(0.2); // 遮罩不透明度够，背景正文不会和对话框文字叠在一起
  expect(alpha.slice(0, 3).every((v) => v < 60)).toBe(true); // 是压暗，不是白雾
});

// 阶段 5 收尾 A（P2-21/22）：grid.left 从 '3%' 改成固定 12。改之前 25 屏（888 宽卡）卡左缘到 y 轴线 57px，设计 44；
// 验收要 1024 宽下 ≤ 46px。y 值轴默认不画轴线，"y 轴线"就是 plot 区左沿 = x 轴线的左端：读 canvas 像素找它，
// 不读 option（option 里是 12，量的是刻度文字 + 留白之后实际画出来的位置）。
test("1024 宽会话：图表卡左缘到 y 轴线 ≤ 46px（读 canvas 像素）；右侧留白不随宽度变", async ({ page }) => {
  test.setTimeout(120_000);
  const file = `axis-${Date.now()}.csv`;
  await page.setViewportSize({ width: 1024, height: 768 });
  expect((await page.request.put("/settings", { headers: auth, data: { model: "chart-bar" } })).ok()).toBe(true);
  await page.goto(`/#token=${E2E_TOKEN}`);
  await page.getByLabel("选择 CSV 文件").setInputFiles([{ name: file, mimeType: "text/csv", buffer: Buffer.from(SALES) }]);
  await page.getByRole("button", { name: "上传" }).click();
  await page.getByTestId("dataset-view").getByRole("button", { name: "新建会话" }).click();
  const sv = page.getByTestId("session-view");
  await sv.getByLabel("提问").fill("画各城市销量柱状图");
  await sv.getByRole("button", { name: "发送" }).click();
  await expect(sv.getByTestId("assistant-msg")).toHaveCount(1, { timeout: 60_000 });
  const wrap = sv.locator(".echart-wrap").first();
  await expect(wrap.locator("canvas").first()).toBeVisible();
  const measure = () => wrap.evaluate((w) => {
    const c = w.querySelector("canvas") as HTMLCanvasElement;
    const k = c.width / c.clientWidth;
    const d = c.getContext("2d")!.getImageData(0, 0, c.width, c.height).data;
    // x 轴线：从下往上找"连续灰色像素最长"的一行（轴线色 #6E7079 一类：r≈g≈b、比 200 暗）
    let best = { y: -1, x0: 0, x1: 0 };
    for (let y = c.height - 1; y >= c.height / 2; y--) {
      let run = 0, start = 0;
      for (let x = 0; x < c.width; x++) {
        const i = (y * c.width + x) * 4;
        const [r, g, b] = [d[i], d[i + 1], d[i + 2]];
        const gray = Math.max(r, g, b) - Math.min(r, g, b) < 24 && r < 200;
        if (gray) { if (!run) start = x; run++; } else run = 0;
        if (run > best.x1 - best.x0) best = { y, x0: start, x1: start + run };
      }
    }
    const cr = c.getBoundingClientRect(), wr = w.getBoundingClientRect();
    return { left: cr.left + best.x0 / k - wr.left, right: wr.right - (cr.left + best.x1 / k), len: (best.x1 - best.x0) / k, width: cr.width };
  });
  await expect(async () => {
    const m = await measure();
    expect(m.len).toBeGreaterThan(m.width * 0.6); // 找到的确实是横贯 plot 区的轴线
    expect(m.left).toBeLessThanOrEqual(46);
    expect(Math.abs(m.right - 17)).toBeLessThanOrEqual(2); // grid.right 16 + 卡边框 1
  }).toPass({ timeout: 10_000 });
});
