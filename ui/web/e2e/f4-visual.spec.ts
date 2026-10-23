import { expect, type Page, test } from "@playwright/test";
import { E2E_TOKEN } from "../playwright.config";

// 视觉回归（S 10-22 r4 §六、PR #70 评审结论）：V2a 验收里"改一处塌一处"三次（遮罩→删除钮变粉、居中→失败卡宽度塌 49%、
// 底注只改一半），4 条行为 e2e 全绿却一条没抓到，因为没有一条看像素。这里给四屏钉基线：
//   08 分析中（骨架 + 控件行占位）· 11 标记浮层 · 24 窄屏失败页 · 25 窄屏会话
// 约定：
// - 截整页（view-root 是 display: contents，不能按元素截）；不可复现的部分 mask 掉（见 DYNAMIC）。
// - 动画由 toHaveScreenshot 默认的 animations: "disabled" 停在首帧。
// - 阈值：threshold 0.02（逐像素色差）+ maxDiffPixels 20。偏离 S 定的 maxDiffPixelRatio 0.002，理由是变异实测（DEVLOG [59]）：
//   整页 1440×900 的 0.002 是 2592 像素，默认 threshold 0.2 下底注 #6B6B70→#A0A0A5 只差 82 像素、骨架圆角 12→6 差 0，都抓不到；
//   threshold 0.02 下分别是 609 / 36 像素，标记浮层透明度 .58→.75 是 16134。不变时 --repeat-each=4 共 16 次为 0 像素。
// - 基线按平台分（*-fake-linux.png）。CI 是 ubuntu x64，沙箱是 arm64，抗锯齿可能不同，以 CI 产出的为准：
//   CI 红时从 playwright-results 工件取 *-actual.png 覆盖基线（步骤见 HANDOVER §6）。
// - 改了 UI、预期就该变：npx playwright test f4-visual --update-snapshots，提交时在 DEVLOG 写明哪屏为什么变。
const auth = { Authorization: `Bearer ${E2E_TOKEN}` };
const SALES = "城市,销量,利润\n深圳,412,1.5\n上海,365,2.5\n北京,290,0.5\n广州,217,1.1\n";
const SHOT = { threshold: 0.02, maxDiffPixels: 20 } as const;

const model = async (page: Page, m: string) =>
  expect((await page.request.put("/settings", { headers: auth, data: { model: m } })).ok()).toBe(true);

async function upload(page: Page, name: string, body: string) {
  await page.getByLabel("选择 CSV 文件").setInputFiles([{ name, mimeType: "text/csv", buffer: Buffer.from(body) }]);
  await page.getByRole("button", { name: "上传" }).click();
  await page.getByTestId("dataset-view").waitFor();
}

async function newSession(page: Page) {
  await page.getByTestId("dataset-view").getByRole("button", { name: "新建会话" }).click();
  const sv = page.getByTestId("session-view");
  await sv.getByLabel("提问").waitFor();
  return sv;
}

// 预热（照 f4-panel.spec.ts）：冷后端第一次分析要 20 秒以上，挪出每条用例的超时窗口。
test.beforeAll(async ({ request }) => {
  test.setTimeout(150_000);
  expect((await request.put("/settings", { headers: auth, data: { model: "ok" } })).ok()).toBe(true);
  const ds = await (await request.post("/datasets", {
    headers: auth, multipart: { files: { name: "vr-warm.csv", mimeType: "text/csv", buffer: Buffer.from(SALES) } },
  })).json();
  const s = await (await request.post("/sessions", { headers: auth, data: { dataset_id: ds.id } })).json();
  const r = await request.post(`/sessions/${s.id}/messages`, { headers: auth, data: { content: "预热" }, timeout: 140_000 });
  expect(await r.text()).toContain("event: done");
});

// 宽屏侧栏整块 mask：列表长度随共享后端里别的用例变化，会把「会话」一节整体推下去（--repeat-each=2 实测 9% 像素差）。
// 窄屏是图标轨，不含列表，照比。
// 宽度随内容变的行内文字不能 mask（mask 框跟着变宽，框边本身就是像素差），改成截图前把文字换成定值，样式照比：
//   失败卡原因行的随机编号（trace id 前 8 位）；同名重复上传时数据集名后带的「 · HH:MM」（顶栏标题、输入区胶囊）。
async function freeze(page: Page) {
  await page.evaluate(() => {
    for (const el of document.querySelectorAll(".failcard .reason")) el.textContent = (el.textContent ?? "").replace(/编号 [0-9a-f]+/, "编号 00000000");
    for (const el of document.querySelectorAll(".ctx-pill span")) el.textContent = "vr.csv";
    for (const el of document.querySelectorAll(".topbar-title")) el.textContent = (el.textContent ?? "").replace(/ · \d\d:\d\d$/, "");
  });
}
// 已结束轮次的步骤条带每步用时（< 0.05s 时不显示，宽度也会变），整条 mask；步骤条的样式由 08（分析中，无用时）钉住。
const DYNAMIC = [".acard-time", ".topbar-sub", ".sidebar"];
const masks = (page: Page, finished = false) => [...DYNAMIC, ...(finished ? [".stepbar"] : [])].map((s) => page.locator(s));

test("视觉 08：分析中——骨架图块与控件行同色、同圆角", async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await model(page, "slow-2s");
  await page.goto(`/#token=${E2E_TOKEN}`);
  await upload(page, "vr-running.csv", SALES);
  const sv = await newSession(page);
  await sv.getByLabel("提问").fill("各城市的销量占比是多少？");
  await sv.getByRole("button", { name: "发送" }).click();
  await expect(sv.locator(".skeleton")).toBeVisible();
  await freeze(page);
  await expect(page).toHaveScreenshot("08-running.png", { ...SHOT, mask: masks(page) });
  await expect(sv.getByTestId("assistant-msg")).toHaveCount(1, { timeout: 30_000 }); // 收尾，免得拖到下一条
});

test("视觉 11：标记浮层压在柱图上，色板区半透明", async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await model(page, "chart-bar");
  await page.goto(`/#token=${E2E_TOKEN}`);
  await upload(page, "vr-marks.csv", SALES);
  const sv = await newSession(page);
  await sv.getByLabel("提问").fill("画各城市销量柱状图");
  await sv.getByRole("button", { name: "发送" }).click();
  await expect(sv.getByTestId("assistant-msg")).toHaveCount(1, { timeout: 30_000 });
  await expect(sv.locator("canvas").first()).toBeVisible();
  await sv.getByTestId("assistant-msg").getByRole("button", { name: "标记" }).click();
  await expect(page.locator(".marks-item").first()).toBeVisible();
  await freeze(page);
  await expect(page).toHaveScreenshot("11-marks-card.png", { ...SHOT, mask: masks(page, true) });
});

test("视觉 24：1024 窄屏失败页——卡片宽 min(620px, 100% - 48px)，底注 #6B6B70", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto(`/#token=${E2E_TOKEN}`);
  await upload(page, "vr-empty.csv", "");
  const dv = page.getByTestId("dataset-view");
  await expect(dv.locator(".failcard")).toBeVisible();
  await freeze(page);
  await expect(page).toHaveScreenshot("24-narrow-dataset-failed.png", { ...SHOT, mask: masks(page) });
});

test("视觉 25：1024 窄屏会话——落在最新一轮，输入区不压卡片", async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1024, height: 768 });
  await model(page, "chart-bar");
  await page.goto(`/#token=${E2E_TOKEN}`);
  await upload(page, "vr-narrow.csv", SALES);
  const sv = await newSession(page);
  await sv.getByLabel("提问").fill("画各城市销量柱状图");
  await sv.getByRole("button", { name: "发送" }).click();
  await expect(sv.getByTestId("assistant-msg")).toHaveCount(1, { timeout: 30_000 });
  await expect(sv.locator("canvas").first()).toBeVisible();
  await freeze(page);
  await expect(page).toHaveScreenshot("25-narrow-session.png", { ...SHOT, mask: masks(page, true) });
});
