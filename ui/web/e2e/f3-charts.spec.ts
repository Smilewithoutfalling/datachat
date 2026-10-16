import { expect, type Page, test } from "@playwright/test";
import { E2E_TOKEN } from "../playwright.config";
import schema from "../src/generated/chart_schema.json" with { type: "json" };

// F3-ECharts 第一步：五种 kind 各问一轮（假服务 chart-<kind>），后端托管 dist、带 CSP。
// 断言：出现 canvas、图数 = result.charts 的结构化图数；刷新后走重放仍在；全程零外部请求、零 CSP 违规。
const CSV = "城市,销量,利润\n北京,3,1.5\n上海,5,2.5\n广州,2,0.5\n";
const auth = { Authorization: `Bearer ${E2E_TOKEN}` };

async function useScenario(page: Page, model: string) {
  const r = await page.request.put("/settings", { headers: auth, data: { model } });
  expect((await r.json()).model).toBe(model);
}

test.beforeAll(async ({ request }) => {
  test.setTimeout(150_000); // 冷启动预热，同 f3-stop.spec
  expect((await request.put("/settings", { headers: auth, data: { model: "ok" } })).ok()).toBe(true);
  const ds = await (await request.post("/datasets", {
    headers: auth, multipart: { files: { name: "warm.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) } },
  })).json();
  const s = await (await request.post("/sessions", { headers: auth, data: { dataset_id: ds.id } })).json();
  const r = await request.post(`/sessions/${s.id}/messages`, { headers: auth, data: { content: "预热" }, timeout: 140_000 });
  expect(await r.text()).toContain("event: done");
});

test("五种图型：canvas 渲染、图数一致、刷新重放仍在；零外部请求、零 CSP 违规", async ({ page, baseURL }) => {
  test.setTimeout(120_000);
  const origin = new URL(baseURL!).origin;
  const external: string[] = [];
  const sameOriginAssets: string[] = [];
  page.on("request", (req) => {
    const u = new URL(req.url());
    if (u.protocol === "data:" || u.protocol === "blob:") return;
    if (u.origin !== origin) external.push(req.url());
    else if (u.pathname.startsWith("/assets/")) sameOriginAssets.push(u.pathname);
  });
  await page.addInitScript(() => {
    const w = window as unknown as { __csp: string[] };
    w.__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => w.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
  });

  await page.goto(`/#token=${E2E_TOKEN}`);
  await page.getByLabel("选择 CSV 文件").setInputFiles([{ name: "charts.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) }]);
  await page.getByRole("button", { name: "上传" }).click();
  await page.getByTestId("dataset-view").getByRole("button", { name: "新建会话" }).click();
  const sv = page.getByTestId("session-view");

  const kinds = schema.kinds;
  for (const [i, kind] of kinds.entries()) {
    await useScenario(page, `chart-${kind}`);
    await sv.getByLabel("提问").fill(`画 ${kind}`);
    await sv.getByRole("button", { name: "提问" }).click();
    const msg = sv.getByTestId("assistant-msg").nth(i);
    await expect(msg).toContainText("（fake）结论", { timeout: 30_000 });
    await expect(msg.getByTestId("echart")).toHaveCount(1);
    await expect(msg.getByTestId("echart")).toHaveAttribute("data-kind", kind);
    await expect(msg.getByTestId("echart").locator("canvas")).not.toHaveCount(0);
  }

  // 图数 = 库里 result.charts 的结构化图数（每轮 1 张，kind 对得上）
  const sid = await page.evaluate(async (token) => {
    const r = await fetch("/sessions", { headers: { Authorization: `Bearer ${token}` } });
    const list = (await r.json()) as { id: string; title: string }[];
    return list.find((s) => s.title.startsWith("画 "))?.id ?? list[0].id;
  }, E2E_TOKEN);
  const detail = await (await page.request.get(`/sessions/${sid}`, { headers: auth })).json();
  const stored = (detail.messages as { role: string; result?: { charts: { option: { kind: string } | null }[] } }[])
    .filter((m) => m.role === "assistant")
    .map((m) => (m.result?.charts ?? []).filter((c) => c.option).map((c) => c.option!.kind));
  expect(stored).toEqual(kinds.map((k) => [k]));

  // 刷新：重放路径，图仍在
  await page.reload();
  await page.getByRole("navigation", { name: "会话" }).getByRole("button", { name: /画 / }).first().click();
  const again = page.getByTestId("session-view").getByTestId("echart");
  await expect(again).toHaveCount(kinds.length);
  for (const [i, kind] of kinds.entries()) {
    await expect(again.nth(i)).toHaveAttribute("data-kind", kind);
    await expect(again.nth(i).locator("canvas")).not.toHaveCount(0);
  }

  const csp = await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp);
  expect(external).toEqual([]);
  expect(csp).toEqual([]);
  expect(sameOriginAssets.length).toBeGreaterThan(0); // 对照：监听器确实收到了同源 /assets/* 请求
});
