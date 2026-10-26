import { expect, type Page, test } from "@playwright/test";
import { E2E_TOKEN } from "../playwright.config";

// V2d §2：单轮 token 预算。fake_llm 的 tokens-70000 场景每次调用报 prompt_tokens=70000：ReAct 第一次调用后
// 已用 70,005、预留 70,000，第二次调用前即达默认预算 130,000 → 走强制收尾（MARK_FINALIZE 认作 final）→ 有结论 + 预算 warning。
// 卡片头部显示本轮 token（act + 收尾两次调用 × 70,005 = 140,010）。
const CSV = "城市,销量\n北京,3\n上海,5\n";
const auth = { Authorization: `Bearer ${E2E_TOKEN}` };

async function useScenario(page: Page, model: string) {
  const r = await page.request.put("/settings", { headers: auth, data: { model } });
  expect((await r.json()).model).toBe(model);
}

test("超预算：ReAct 按已有执行结果收尾，卡片部分完成、写明 token 上限，头部显示本轮 tokens", async ({ page }) => {
  test.setTimeout(90_000);
  await useScenario(page, "tokens-70000");
  try {
    await page.goto(`/#token=${E2E_TOKEN}`);
    await page.getByLabel("选择 CSV 文件").setInputFiles([{ name: "budget.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) }]);
    await page.getByRole("button", { name: "上传" }).click();
    const view = page.getByTestId("dataset-view");
    await view.getByLabel("分析模式").selectOption("react");
    await view.getByRole("button", { name: "新建会话" }).click();
    const sv = page.getByTestId("session-view");
    await sv.getByLabel("提问").fill("一共几行");
    await sv.getByRole("button", { name: "发送" }).click();

    const msg = sv.getByTestId("assistant-msg");
    await expect(msg).toContainText("（fake）结论", { timeout: 60_000 });
    await expect(msg).toContainText("本轮 token 用量达到上限（130000），已根据已有执行结果收尾");
    await expect(sv.getByTestId("turn-badge")).toHaveText("部分完成");
    await expect(sv.getByTestId("turn-tokens")).toContainText("140,010 tokens");
    await expect(sv.getByTestId("turn-tokens")).not.toHaveAttribute("title", /.+/);
  } finally {
    await useScenario(page, "ok");
  }
});
