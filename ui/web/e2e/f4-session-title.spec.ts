import { expect, test } from "@playwright/test";
import { E2E_TOKEN } from "../playwright.config";

// 阶段 7.6 U5 会话标题（docs/roadmap/phase76-u3u5.md §2.5 e2e）：上传、首问「各地区销售额是多少」后，
// 顶栏标题框和侧栏当前会话的名字都是后端本地规则生成的「地区销售额」（app/server/titles.py），不是问题原话。
// 每次上传都是新数据集，重名去重只在同一数据集内，所以共享后端里别的用例留下的同名会话不影响这里。
const auth = { Authorization: `Bearer ${E2E_TOKEN}` };
const SALES = "月份,地区,销售额\n2024-01,华东,412\n2024-01,华南,365\n2024-02,华东,290\n";

test("U5：首问后顶栏和侧栏的会话名是「地区销售额」；刷新后照样", async ({ page }) => {
  test.setTimeout(90_000);
  expect((await page.request.put("/settings", { headers: auth, data: { model: "ok" } })).ok()).toBe(true);
  await page.goto(`/#token=${E2E_TOKEN}`);
  const file = `u5-${Date.now()}.csv`;
  await page.getByLabel("选择 CSV 文件").setInputFiles([{ name: file, mimeType: "text/csv", buffer: Buffer.from(SALES) }]);
  await page.getByRole("button", { name: "上传", exact: true }).click();
  await page.getByTestId("dataset-view").getByRole("button", { name: "新建会话" }).click();
  const sv = page.getByTestId("session-view");
  await sv.getByLabel("提问").fill("各地区销售额是多少");
  await sv.getByRole("button", { name: "发送" }).click();
  // 响应头 X-Session-Title 一到，顶栏就跟上（不等这一轮结束）
  await expect(sv.getByLabel("会话标题")).toHaveValue("地区销售额", { timeout: 30_000 });
  await expect(sv.getByTestId("assistant-msg")).toHaveCount(1, { timeout: 60_000 });
  const row = page.locator('.sess-row[aria-current="page"] .sess-title');
  await expect(row).toHaveText("地区销售额");
  await page.reload();
  // 刷新落在首页：侧栏里这个数据集（会话行副标题 = 文件名）的会话名照样是「地区销售额」，点回去顶栏也是
  const again = page.getByRole("navigation", { name: "会话" }).getByRole("button", { name: new RegExp(file.replace(/\./g, "\\.")) });
  await expect(again.locator(".sess-title")).toHaveText("地区销售额", { timeout: 30_000 });
  await again.click();
  await expect(page.getByTestId("session-view").getByLabel("会话标题")).toHaveValue("地区销售额");
});
