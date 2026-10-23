import { expect, type Page, test } from "@playwright/test";
import { E2E_TOKEN } from "../playwright.config";
import events from "../src/generated/events.json" with { type: "json" };

const MESSAGES = events.messages as Record<string, string>;

// F3：停止的端到端，跑在 fake 后端上（base_url → tests/fake_llm.py）。
// 场景 hang-8s@codegen：plan 正常返回（事件已推到前端），codegen 那次模型调用挂 8 秒。
// 两个数分开记（phase5-frontend.md 验收第 5 条）：
//   感知延迟：点"停止" → 按钮变"停止中"。验收指标。
//   后端延迟：POST /cancel 返回 200 → 界面出现"已取消"（流里 error+done 到达 + settle 读库）。只记录：
//            检查点在每个事件之前，上界 ≈ 当前那次模型调用的剩余时间，这里约等于 8 秒减去点停止前已挂的时间。
const CSV = "城市,销量\n北京,3\n上海,5\n";
const auth = { Authorization: `Bearer ${E2E_TOKEN}` };

async function useScenario(page: Page, model: string) {
  const r = await page.request.put("/settings", { headers: auth, data: { model } });
  expect((await r.json()).model).toBe(model);
}

// 预热：后端进程的第一次分析要 import pandas / matplotlib / langchain、建字体缓存，沙箱里能到 20 秒以上。
// 停止测的是稳态下的延迟，所以先用 ok 场景完整跑一轮（只走 API），把冷启动挪出被测窗口。
test.beforeAll(async ({ request }) => {
  test.setTimeout(150_000);
  expect((await request.put("/settings", { headers: auth, data: { model: "ok" } })).ok()).toBe(true);
  const ds = await (await request.post("/datasets", {
    headers: auth, multipart: { files: { name: "warm.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) } },
  })).json();
  const s = await (await request.post("/sessions", { headers: auth, data: { dataset_id: ds.id } })).json();
  const r = await request.post(`/sessions/${s.id}/messages`, { headers: auth, data: { content: "预热" }, timeout: 140_000 });
  expect(await r.text()).toContain("event: done");
});

test("停止：感知延迟 / 后端延迟分开测；落 cancelled；立刻重问不撞 409", async ({ page }) => {
  test.setTimeout(60_000);
  await useScenario(page, "hang-8s@codegen");
  await page.addInitScript(() => {
    const w = window as unknown as { __t: Record<string, number> };
    w.__t = {};
    const orig = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const res = await orig(input, init);
      if (String(input instanceof Request ? input.url : input).match(/\/messages\/[^/]+\/cancel$/)) w.__t.cancelOk = performance.now();
      return res;
    };
    document.addEventListener("click", (e) => {
      if ((e.target as HTMLElement).closest("button.stop")) w.__t.click = performance.now();
    }, true);
    new MutationObserver(() => {
      const b = document.querySelector("button.stop");
      if (w.__t.click && !w.__t.stopping && b?.textContent === "停止中") w.__t.stopping = performance.now();
      const done = [...document.querySelectorAll('[data-testid="assistant-msg"] .badge.cancelled')];
      if (w.__t.click && !w.__t.cancelled && done.length) w.__t.cancelled = performance.now();
    }).observe(document, { subtree: true, childList: true, characterData: true });
  });

  await page.goto(`/#token=${E2E_TOKEN}`);
  await page.getByLabel("选择 CSV 文件").setInputFiles([{ name: "sales.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) }]);
  await page.getByRole("button", { name: "上传" }).click();
  await page.getByTestId("dataset-view").getByRole("button", { name: "新建会话" }).click();
  const sv = page.getByTestId("session-view");
  await sv.getByLabel("提问").fill("一共几行？");
  await sv.getByRole("button", { name: "发送" }).click();

  const live = sv.getByTestId("live-msg");
  // plan 已到，codegen 正挂着。V2a：过程默认折叠，改看步骤条的状态
  await expect(live.locator('[data-step="plan"][data-state="done"]')).toBeVisible({ timeout: 15_000 });
  await expect(live.locator('[data-step="code"][data-state="running"]')).toBeVisible();
  await sv.getByRole("button", { name: "停止" }).click(); // V2a §1.8：停止在输入区
  const msg = sv.getByTestId("assistant-msg");
  await expect(msg.locator(".badge.cancelled")).toHaveText("已取消", { timeout: 15_000 });
  await expect(live).toHaveCount(0);

  const t = await page.evaluate(() => (window as unknown as { __t: Record<string, number> }).__t);
  const perceived = t.stopping - t.click;
  const backend = t.cancelled - t.cancelOk;
  test.info().annotations.push(
    { type: "感知延迟 ms（点停止 → 停止中）", description: perceived.toFixed(0) },
    { type: "后端延迟 ms（POST /cancel 200 → 已取消）", description: backend.toFixed(0) },
    { type: "点停止 → POST /cancel 返回 ms", description: (t.cancelOk - t.click).toFixed(0) },
  );
  console.log(`[F3 stop] perceived=${perceived.toFixed(0)}ms cancelOk=${(t.cancelOk - t.click).toFixed(0)}ms backend=${backend.toFixed(0)}ms`);
  expect(perceived).toBeLessThan(500);          // 乐观 UI：同一次渲染，留足 CI 余量
  expect(backend).toBeGreaterThan(0);
  expect(backend).toBeLessThan(10_000);         // 上界 = codegen 剩余挂起时间（≤ 8s）+ 收尾余量
  await expect(msg.getByTestId("unsaved-answer")).toHaveCount(0); // answer 从没产出过，不该有"未保存"
  await expect(msg.locator(".outcome.cancelled")).toHaveText(MESSAGES.cancelled); // 不是"失败"，没有 alert
  await expect(msg.getByRole("alert")).toHaveCount(0);

  // 立刻重问：不撞 409，正常走完
  await useScenario(page, "ok");
  await sv.getByLabel("提问").fill("再问一次");
  await sv.getByRole("button", { name: "发送" }).click();
  await expect(sv.getByTestId("assistant-msg").nth(1)).toContainText("（fake）结论：数据共有若干行。");

  // 刷新：库里是 cancelled，重放一致
  await page.reload();
  await page.getByRole("navigation", { name: "会话" }).getByRole("button", { name: /一共几行/ }).click();
  const again = page.getByTestId("session-view").getByTestId("assistant-msg");
  await expect(again.nth(0).locator(".badge.cancelled")).toHaveText("已取消");
  await expect(again.nth(1)).toContainText("（fake）结论");
});
