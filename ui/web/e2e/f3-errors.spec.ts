import { expect, type Page, test } from "@playwright/test";
import { E2E_TOKEN } from "../playwright.config";

// T11：上游错误 message 回显用户问题时，界面（助手消息、刷新后的重放）看不到问题原文，只看到剥离后的上游信息和编号。
// 走完整产品路径：fake_llm 的 fail-echo / fail-echocut 场景 → LLMClient → service.py user_error → SSE → 落库 → 重放。
const CSV = "城市,销量\n北京,3\n上海,5\n";
const Q = "请按城市统计二零二五年每个季度的销量并画出柱状图";
const auth = { Authorization: `Bearer ${E2E_TOKEN}` };

async function useScenario(page: Page, model: string) {
  const r = await page.request.put("/settings", { headers: auth, data: { model } });
  expect((await r.json()).model).toBe(model);
}

for (const echo of ["echo", "echocut"]) {
  test(`上游回显问题（${echo}）：助手消息里没有问题原文，有编号`, async ({ page }) => {
    test.setTimeout(90_000);
    await useScenario(page, `fail-${echo}-400`);
    await page.goto(`/#token=${E2E_TOKEN}`);
    await page.getByLabel("选择 CSV 文件").setInputFiles([{ name: "sales.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) }]);
    await page.getByRole("button", { name: "上传" }).click();
    await page.getByTestId("dataset-view").getByRole("button", { name: "新建会话" }).click();
    const sv = page.getByTestId("session-view");
    await sv.getByLabel("提问").fill(Q);
    await sv.getByRole("button", { name: "提问" }).click();

    const check = async () => {
      const msg = page.getByTestId("session-view").getByTestId("assistant-msg");
      await expect(msg).toContainText("[fake_llm] 按场景返回 400", { timeout: 60_000 });
      const text = (await msg.textContent()) ?? "";
      expect(text).toMatch(/（编号 [0-9a-f]{8}）/);
      expect(text).not.toContain(Q.slice(0, 12));
      expect(text).not.toMatch(/Error|Exception|Traceback/);
    };
    await check();
    await page.reload();
    await page.getByRole("navigation", { name: "会话" }).getByRole("button", { name: /请按城市/ }).first().click();
    await check();
    await useScenario(page, "ok");
  });
}
