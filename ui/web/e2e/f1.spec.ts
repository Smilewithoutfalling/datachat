import { expect, test } from "@playwright/test";
import { E2E_TOKEN } from "../playwright.config";

// F1 验收路径的前半段（不调模型）：设置 → 上传 → 看预览 → 建会话 → 改名 → 刷新后还在。跑在后端托管的 dist（带 CSP）上。
const INJECT = '<img src=x onerror="window.__pwned=1">';
const CSV = `名称,备注,数量\n苹果,"${INJECT.replace(/"/g, '""')}",\n梨,普通,3\n`;

test("设置超时 → 上传 → 预览按文本渲染 → 建会话改名 → 刷新仍在", async ({ page }) => {
  const violations: string[] = [];
  await page.addInitScript(() => {
    const w = window as unknown as { __csp: string[] };
    w.__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => w.__csp.push(e.violatedDirective));
  });
  await page.goto(`/#token=${E2E_TOKEN}`);

  // 没有 Key → 先进设置页
  await expect(page.getByTestId("settings-view")).toBeVisible();
  await expect(page.getByTestId("key-status")).toHaveText("未设置");
  await page.getByLabel("单次请求超时（秒）").fill("90");
  await page.getByRole("button", { name: "保存设置" }).click();
  await expect(page.getByText("设置已保存。")).toBeVisible();

  // 上传（含注入串的 CSV + 字典）
  await page.getByLabel("选择 CSV 文件").setInputFiles([
    { name: "fruit.csv", mimeType: "text/csv", buffer: Buffer.from(CSV, "utf-8") },
    { name: "fruit.dict.csv", mimeType: "text/csv", buffer: Buffer.from("列,含义\n数量,箱数\n", "utf-8") },
  ]);
  await page.getByPlaceholder("数据集名称（可选）").fill("水果");
  await page.getByRole("button", { name: "上传" }).click();

  const view = page.getByTestId("dataset-view");
  await expect(view.getByRole("heading", { name: "水果" })).toBeVisible();
  await expect(view.getByText("共 2 行 × 3 列", { exact: false })).toBeVisible();
  await expect(view.getByText(INJECT)).toBeVisible();
  await expect(view.locator("tbody img")).toHaveCount(0);
  await expect(view.locator("td .na")).toHaveText("空");
  await expect(view.getByText("字典文件：fruit.dict.csv")).toBeVisible();

  // 建会话 → 改名
  await view.getByLabel("分析方式").selectOption("react");
  await view.getByRole("button", { name: "新建会话" }).click();
  const sv = page.getByTestId("session-view");
  await expect(sv.getByText("数据集：水果 · ReAct")).toBeVisible();
  await sv.getByLabel("会话标题").fill("看看水果");
  await sv.getByLabel("会话标题").press("Enter");
  await expect(page.getByRole("navigation", { name: "会话" }).getByRole("button", { name: /看看水果/ })).toBeVisible();

  // 刷新：token 走 sessionStorage；数据集、会话名、超时都在
  await page.reload();
  await page.getByRole("navigation", { name: "会话" }).getByRole("button", { name: /看看水果/ }).click();
  await expect(page.getByTestId("session-view").getByLabel("会话标题")).toHaveValue("看看水果");
  await page.getByRole("button", { name: /^设置/ }).click();
  await expect(page.getByLabel("单次请求超时（秒）")).toHaveValue("90");

  violations.push(...(await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp)));
  expect(violations).toEqual([]);
  expect(await page.evaluate(() => (window as unknown as { __pwned?: number }).__pwned)).toBeUndefined();
});
