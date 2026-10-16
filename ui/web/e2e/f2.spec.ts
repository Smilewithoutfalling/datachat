import { expect, test } from "@playwright/test";
import { E2E_TOKEN } from "../playwright.config";

// F2：在后端托管的 dist（带 CSP）上走一次真实 SSE。E2E 后端没有 Key，分析在第一步就以 llm 失败结束——
// 正好覆盖：提问 → 流式事件 → 致命 error + done → 按库里 status 收尾 → 👍👎 → 刷新后重放一致。
// 停止的端到端（需要能挂住的假模型）随 F3 的假模型服务一起做。
const CSV = "城市,销量\n北京,3\n上海,5\n";

test("提问 → SSE → 失败原因 → 👍 → 刷新重放一致", async ({ page }) => {
  await page.addInitScript(() => {
    const w = window as unknown as { __csp: string[] };
    w.__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => w.__csp.push(e.violatedDirective));
  });
  await page.goto(`/#token=${E2E_TOKEN}`);
  await page.getByLabel("选择 CSV 文件").setInputFiles([{ name: "sales.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) }]);
  await page.getByRole("button", { name: "上传" }).click();
  const view = page.getByTestId("dataset-view");
  await view.getByRole("button", { name: "新建会话" }).click();

  const sv = page.getByTestId("session-view");
  await sv.getByLabel("提问").fill("哪个城市销量最高？");
  await sv.getByRole("button", { name: "提问" }).click();
  const msg = sv.getByTestId("assistant-msg");
  await expect(msg.getByRole("alert")).toContainText("模型调用失败：");
  await expect(msg.getByRole("alert")).toContainText("未配置 API Key");
  await expect(sv.getByTestId("live-msg")).toHaveCount(0);
  await expect(sv.getByRole("button", { name: "提问" })).toBeDisabled(); // 输入框已清空
  await msg.getByRole("button", { name: "有用" }).click();
  await expect(msg.getByRole("button", { name: "有用" })).toHaveAttribute("aria-pressed", "true");

  await page.reload();
  await page.getByRole("navigation", { name: "会话" }).getByRole("button", { name: /哪个城市/ }).click();
  const again = page.getByTestId("session-view").getByTestId("assistant-msg");
  await expect(again.getByRole("alert")).toContainText("未配置 API Key");
  await expect(again.getByRole("button", { name: "有用" })).toHaveAttribute("aria-pressed", "true");

  expect(await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp)).toEqual([]);
});
