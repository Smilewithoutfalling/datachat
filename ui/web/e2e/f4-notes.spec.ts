import { expect, test } from "@playwright/test";
import { E2E_TOKEN } from "../playwright.config";

// 批 4b M2 / M10（docs/roadmap/memory-batch4.md §3.4.1）：数据集页「口径与规则」在后端托管的 dist 上走一遍（fake project）。
// 加一条口径 → 列表里出现 → 新建会话 → 提问 → 请求成功（结论出来）。不测模型行为（fake_llm 不看口径）。
// 三档（off / state / full）都会跑这个文件：off 下口径区写明不生效，其余两档不写；提问都要成功。
const CSV = "城市,销量,单价\n北京,3,10\n上海,5,12\n";
const auth = { Authorization: `Bearer ${E2E_TOKEN}` };

test("口径：添加 → 列表 → 导出可用 → 新建会话提问成功；停用后从列表消失", async ({ page }) => {
  test.setTimeout(90_000);
  expect((await page.request.put("/settings", { headers: auth, data: { model: "ok" } })).ok()).toBe(true);
  await page.goto(`/#token=${E2E_TOKEN}`);
  await page.getByLabel("选择 CSV 文件").setInputFiles([{ name: "notes.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) }]);
  await page.getByRole("button", { name: "上传" }).click();
  const view = page.getByTestId("dataset-view");
  const sec = view.getByTestId("notes-section");
  await expect(sec.getByTestId("notes-empty")).toBeVisible();
  const mode = (await (await page.request.get("/settings", { headers: auth })).json()).memory.mode;
  await expect(sec.getByTestId("notes-off")).toHaveCount(mode === "off" ? 1 : 0);

  await sec.getByRole("button", { name: "添加口径" }).click();
  await sec.getByLabel("口径名称").fill("销售额");
  await sec.getByLabel("公式或规则").fill("销量 * 单价");
  await sec.getByLabel("单位").fill("元");
  await sec.getByLabel("别名").fill("营收，收入");
  await sec.getByRole("button", { name: "保存口径" }).click();
  const row = sec.getByTestId("note-row");
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("销量 * 单价");
  await expect(row).toContainText("营收、收入");
  await expect(sec.getByRole("button", { name: "导出 CSV" })).toBeEnabled();
  // 数据集页原有的「删除数据集」入口仍唯一（按钮不重名）
  await expect(view.getByRole("button", { name: /删除/ })).toHaveCount(0);

  await view.getByRole("button", { name: "新建会话" }).click();
  const sv = page.getByTestId("session-view");
  await sv.getByLabel("提问").fill("各城市销售额");
  await sv.getByRole("button", { name: "发送" }).click();
  await expect(sv.getByTestId("assistant-msg")).toContainText("（fake）结论", { timeout: 60_000 });

  // 回到数据集页停用
  const ds = (await (await page.request.get("/datasets", { headers: auth })).json())[0];
  const notes = await (await page.request.get(`/datasets/${ds.id}/notes`, { headers: auth })).json();
  expect(notes.map((n: { name: string }) => n.name)).toEqual(["销售额"]);
  const del = await page.request.delete(`/datasets/${ds.id}/notes/${notes[0].id}`, { headers: auth });
  expect(del.status()).toBe(204);
  expect(await (await page.request.get(`/datasets/${ds.id}/notes`, { headers: auth })).json()).toEqual([]);
});
