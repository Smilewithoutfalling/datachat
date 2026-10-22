import { expect, test } from "@playwright/test";
import { E2E_TOKEN } from "../playwright.config";

// F2：在后端托管的 dist（带 CSP）上走一次真实 SSE。E2E 后端没有 Key，分析在第一步就以 llm 失败结束。
// V2a 起前端在没有 Key 时直接拦下提问，所以 SSE 改由 API 发起，页面覆盖：拦截 → 重放失败原因 → 👍👎 → 刷新后一致。
// 流式渲染本身由 fake 项目的 f3 系列覆盖。
// 停止的端到端（需要能挂住的假模型）随 F3 的假模型服务一起做。
const CSV = "城市,销量\n北京,3\n上海,5\n";

test("没 Key 拦截 → SSE 失败原因 → 👍 → 刷新重放一致", async ({ page }) => {
  await page.addInitScript(() => {
    const w = window as unknown as { __csp: string[] };
    w.__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => w.__csp.push(e.violatedDirective));
  });
  // 前提：后端没有 Key（playwright.config 固定）。哪天 CI 配了 Key，这里先红，而不是下面的期望静默变味
  const key = await page.request.get("/settings/api-key", { headers: { Authorization: `Bearer ${E2E_TOKEN}` } });
  expect(await key.json()).toEqual({ configured: false, source: null });
  await page.goto(`/#token=${E2E_TOKEN}`);
  await page.getByLabel("选择 CSV 文件").setInputFiles([{ name: "sales.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) }]);
  await page.getByRole("button", { name: "上传" }).click();
  const view = page.getByTestId("dataset-view");
  await view.getByRole("button", { name: "新建会话" }).click();

  const sv = page.getByTestId("session-view");
  // V2a §1.9：没有 Key 时前端拦下提问，横幅提示，不发请求
  await expect(sv.getByTestId("key-banner")).toContainText("未配置模型凭证");
  await sv.getByLabel("提问").fill("哪个城市销量最高？");
  await sv.getByRole("button", { name: "发送" }).click();
  await expect(sv.getByTestId("key-banner")).toContainText("这次提问没有发出");
  await expect(sv.getByTestId("assistant-msg")).toHaveCount(0);
  // 后端的 no_key 路径仍要走通（Key 在别处被删、状态过期）：同一个会话直接调 API 提问，走真实 SSE
  const sid = await page.evaluate(async (t) => {
    const r = await fetch("/sessions", { headers: { Authorization: `Bearer ${t}` } });
    return (await r.json())[0].id as string;
  }, E2E_TOKEN);
  const r = await page.request.post(`/sessions/${sid}/messages`, { headers: { Authorization: `Bearer ${E2E_TOKEN}` },
    data: { content: "哪个城市销量最高？" } });
  expect(await r.text()).toContain("event: done");
  await page.reload();
  await page.getByRole("navigation", { name: "会话" }).getByRole("button", { name: /哪个城市/ }).click();
  const msg = page.getByTestId("session-view").getByTestId("assistant-msg");
  await expect(msg.getByRole("alert").locator(".errcard-title")).toHaveText("还没有配置 API Key"); // 验收 P1-2：按 llm_kind=no_key 给标题
  await expect(msg.getByRole("alert")).toContainText("未配置 API Key");
  await expect(msg.getByRole("alert").getByRole("button", { name: "去设置" })).toBeVisible(); // llm_kind=no_key 的出口
  await msg.getByRole("button", { name: "有用" }).click();
  await expect(msg.getByRole("button", { name: "有用" })).toHaveAttribute("aria-pressed", "true");

  await page.reload();
  await page.getByRole("navigation", { name: "会话" }).getByRole("button", { name: /哪个城市/ }).click();
  const again = page.getByTestId("session-view").getByTestId("assistant-msg");
  await expect(again.getByRole("alert")).toContainText("未配置 API Key");
  await expect(again.getByRole("button", { name: "有用" })).toHaveAttribute("aria-pressed", "true");

  expect(await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp)).toEqual([]);
});
