import { expect, type Page, test } from "@playwright/test";
import { E2E_TOKEN } from "../playwright.config";

// 阶段 5 收尾 C：设置页「测试连接」在后端托管的 dist 上走假模型服务（fake project）。测的是已保存的配置：
// 先用 API 存 model（= 假服务的场景名），再打开设置页点按钮。ok → 连接正常 · 耗时 · 模型名；fail-401 → 鉴权失败的文案 + 编号。
// 阶段 6.5：期望变了——这个后端没有连接，生效的是「环境变量」虚拟连接；按钮在它的卡片上，测试改成两步（连接 + 工具调用），
// 结果分两行。所以断言从整块 test-result 改到第一行 test-connect（文字带「连接」行标签），ok 时另断言第二行工具调用 ✓，
// fail-401 时第二行是「没有测」。PUT /settings {model} 没有连接时仍写旧 settings 行，作用于环境变量虚拟连接（行为不变）。
const auth = { Authorization: `Bearer ${E2E_TOKEN}` };
const model = async (page: Page, m: string) =>
  expect((await page.request.put("/settings", { headers: auth, data: { model: m } })).ok()).toBe(true);
async function openSettings(page: Page) {
  await page.goto(`/#token=${E2E_TOKEN}`);
  await page.getByRole("button", { name: "设置" }).click();
  return page.getByTestId("settings-view");
}

test.afterAll(async ({ request }) => {
  await request.put("/settings", { headers: auth, data: { model: "ok" } });
});

test("测试连接（ok）：连接正常 · 耗时 · 模型名；工具调用支持", async ({ page }) => {
  await model(page, "ok");
  const view = await openSettings(page);
  await view.getByRole("button", { name: "测试连接" }).click();
  await expect(view.getByTestId("test-connect")).toHaveText(/^连接连接正常 · \d+\.\ds · ok$/, { timeout: 20_000 });
  await expect(view.getByTestId("test-tools")).toHaveText(/^工具调用支持 · \d+\.\ds$/);
});

test("测试连接（fail-401）：显示鉴权失败的文案和编号，不带 Key", async ({ page }) => {
  await model(page, "fail-401");
  const view = await openSettings(page);
  await view.getByRole("button", { name: "测试连接" }).click();
  const r = view.getByTestId("test-connect");
  await expect(r).toContainText("鉴权失败，请检查 API Key", { timeout: 20_000 });
  await expect(r).toContainText(/（编号 [0-9a-f]{8}）$/);
  await expect(view.getByTestId("test-result")).not.toContainText("fake-key-not-secret");
  await expect(view.getByTestId("test-tools")).toHaveText("工具调用没有测（先要连得上）");
});
