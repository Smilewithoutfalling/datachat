import { expect, type Page, test } from "@playwright/test";
import { E2E_TOKEN } from "../playwright.config";

// 阶段 7.6 U3 结果卡（docs/roadmap/phase76-ui.md §2 U3 验收）：在后端托管的 dist 上真机跑（fake project）。
// 1. 徽章的 N 必须等于 unverified_numbers 的条数，且黄条不再重复列出这些数字——用桩数据断言：真跑一轮 ok 场景，
//    再把 GET /sessions/{id} 响应里第一条助手消息的 result 换上桩（warnings、unverified_numbers），前端收尾 / 重放都读这份。
// 2. 底部三个动作各自真实发出一条请求：换个口径 / 补一张图 = POST /sessions/{id}/messages（真跑，fake 模型照常答），
//    导出 = POST /messages/{id}/export/code、/export/result（#110）。导出请求在网络层截下、回桩，不往 CI 机器的下载文件夹写文件。
const auth = { Authorization: `Bearer ${E2E_TOKEN}` };
const SALES = "月份,城市,销量\n2024-01,深圳,412\n2024-01,上海,365\n2024-02,深圳,290\n2024-02,上海,9999\n";
const WARNING = "结果只显示了前 20 行";
const UNVERIFIED = ["1,061", "82.2 万", "37.5%"];
// 与 src/turn.ts FOLLOW_UPS 一字不差（e2e 不 import 应用源码里带 JSON 生成物的模块，照 f4-starter 的做法写死）
const FOLLOW_METRIC = "换个口径再算一次：先说明上一轮结论用的口径（统计范围、指标定义、时间粒度），再换一种合理的口径重新计算，并对比两种口径的结果差异。";
const FOLLOW_CHART = "给上一轮的结论补一张图：选最能说明这个结论的图型，用上一轮的结果画出来。";

/** GET /sessions/{id}：第一条 ok 的助手消息换上桩数据（只改 result 的这几个字段，别的照后端原样）。 */
async function stubFirstResult(page: Page, extra: Record<string, unknown> = {}) {
  await page.route(/\/sessions\/[^/?]+(\?.*)?$/, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const res = await route.fetch();
    const body = await res.json();
    const m = (body.messages ?? []).find((x: { role: string; status: string }) => x.role === "assistant" && x.status === "ok");
    if (m?.result) {
      m.result = { ...m.result, executed: true, code: m.result.code || "result = df['销量'].sum()",
        warnings: [WARNING], unverified_numbers: UNVERIFIED, ...extra };
    }
    await route.fulfill({ response: res, json: body });
  });
}

function watchPosts(page: Page) {
  const posts: { path: string; body: unknown }[] = [];
  page.on("request", (r) => {
    if (r.method() !== "POST") return;
    const u = new URL(r.url());
    if (/^\/sessions\/[^/]+\/messages$/.test(u.pathname) || /^\/messages\/[^/]+\/export\//.test(u.pathname)) {
      posts.push({ path: u.pathname + u.search, body: u.pathname.includes("/export/") ? null : r.postDataJSON() });
    }
  });
  return posts;
}

async function firstTurn(page: Page, file: string) {
  expect((await page.request.put("/settings", { headers: auth, data: { model: "ok" } })).ok()).toBe(true);
  await page.goto(`/#token=${E2E_TOKEN}`);
  await page.getByLabel("选择 CSV 文件").setInputFiles([{ name: file, mimeType: "text/csv", buffer: Buffer.from(SALES) }]);
  await page.getByRole("button", { name: "上传" }).click();
  await page.getByTestId("dataset-view").getByRole("button", { name: "新建会话" }).click();
  const sv = page.getByTestId("session-view");
  await sv.getByLabel("提问").fill("各城市销量");
  await sv.getByRole("button", { name: "发送" }).click();
  await expect(sv.getByTestId("assistant-msg")).toHaveCount(1, { timeout: 60_000 });
  return sv;
}

// 预热（照 f4-visual / f4-starter）：冷后端第一次分析要 20 秒以上，挪出用例的超时窗口
test.beforeAll(async ({ request }) => {
  test.setTimeout(150_000);
  expect((await request.put("/settings", { headers: auth, data: { model: "ok" } })).ok()).toBe(true);
  const ds = await (await request.post("/datasets", {
    headers: auth, multipart: { files: { name: "result-warm.csv", mimeType: "text/csv", buffer: Buffer.from(SALES) } },
  })).json();
  const s = await (await request.post("/sessions", { headers: auth, data: { dataset_id: ds.id } })).json();
  const r = await request.post(`/sessions/${s.id}/messages`, { headers: auth, data: { content: "预热" }, timeout: 140_000 });
  expect(await r.text()).toContain("event: done");
});

test("U3 结果卡：徽章 N 等于 unverified_numbers 条数，点开列出这几个；黄条不重复列这些数字", async ({ page }) => {
  test.setTimeout(90_000);
  await stubFirstResult(page);
  const sv = await firstTurn(page, `u3-badge-${Date.now()}.csv`);
  const card = sv.getByTestId("assistant-msg").first();

  const badge = card.getByTestId("verify-badge");
  await expect(badge).toHaveText(`△ ${UNVERIFIED.length} 个数字未核实`);
  await expect(card.getByTestId("verify-list")).toHaveCount(0);
  await badge.click();
  await expect(card.getByTestId("verify-list").getByRole("listitem")).toHaveText(UNVERIFIED);

  // 黄条只剩 warnings：桩里那条在，未核实的数字一个都不在
  const wbar = card.locator(".wbar");
  await expect(wbar).toHaveCount(1);
  await expect(wbar).toContainText(WARNING);
  const text = await wbar.innerText();
  for (const n of UNVERIFIED) expect(text).not.toContain(n);
  expect(text).not.toContain("没找到");
  await expect(card.getByTestId("turn-badge")).toHaveText("部分完成");
});

test("U3 结果卡：换个口径、补一张图、导出各发出一条请求", async ({ page }) => {
  test.setTimeout(150_000);
  await stubFirstResult(page);
  const exports: string[] = [];
  await page.route(/\/messages\/[^/]+\/export\/(code|result)/, async (route) => {
    const u = new URL(route.request().url());
    exports.push(u.pathname + u.search);
    const name = u.pathname.endsWith("/code") ? "u3.py" : "u3.csv";
    await route.fulfill({ json: { path: `/tmp/e2e/${name}`, filename: name, rows: 2, columns: 2, matches_original: true } });
  });
  const sv = await firstTurn(page, `u3-actions-${Date.now()}.csv`);
  const posts = watchPosts(page);
  const card = sv.getByTestId("assistant-msg").first();
  const actions = card.getByTestId("result-actions");
  const sid = /\/sessions\/([^/]+)\/messages/;

  await actions.getByRole("button", { name: "换个口径" }).click();
  await expect(sv.getByTestId("assistant-msg")).toHaveCount(2, { timeout: 60_000 });
  expect(posts.map((p) => p.path.replace(sid, "/sessions/:id/messages"))).toEqual(["/sessions/:id/messages"]);
  expect(posts[0].body).toEqual({ content: FOLLOW_METRIC });
  await expect(sv.locator(".msg.user .bubble").nth(1)).toHaveText(FOLLOW_METRIC);

  await expect(actions.getByRole("button", { name: "补一张图" })).toBeEnabled();
  await actions.getByRole("button", { name: "补一张图" }).click();
  await expect(sv.getByTestId("assistant-msg")).toHaveCount(3, { timeout: 60_000 });
  expect(posts).toHaveLength(2);
  expect(posts[1].body).toEqual({ content: FOLLOW_CHART });

  // 第一轮助手消息的 id：从这个会话的详情里取（会话 id 来自刚才那次提问的路径）
  const sessionId = sid.exec(posts[0].path)![1];
  const detail = await (await page.request.get(`/sessions/${sessionId}`, { headers: auth })).json();
  const messageId: string = detail.messages.find((m: { role: string }) => m.role === "assistant").id;

  await actions.getByRole("button", { name: "导出" }).click();
  await page.getByRole("menuitem", { name: "分析代码（.py）" }).click();
  await expect(actions.getByTestId("export-result")).toHaveText("已保存到 /tmp/e2e/u3.py");
  await actions.getByRole("button", { name: "导出" }).click();
  await page.getByRole("menuitem", { name: "结果表（CSV）" }).click();
  await expect(actions.getByTestId("export-result")).toHaveText("已保存到 /tmp/e2e/u3.csv");
  expect(exports).toEqual([`/messages/${messageId}/export/code`, `/messages/${messageId}/export/result?format=csv`]);
  expect(posts.slice(2).map((p) => p.path)).toEqual(exports);
});

// 阶段 7.6 U3 收尾（docs/roadmap/phase76-u3u5.md §1.3 e2e）：桩上 answer、key_numbers（K3 的真实形状，label 带「 · 」）、
// unverified_numbers：① 关键数字是桩里未核实之外的前 3 个；② 卡头那句结论在正文 .answer .md 里不出现；③ 刷新页面重放后照样成立。
const KN_ANSWER = "深圳销量最高，共 1,061 单。\n\n上海次之，82.2 万元，占比 37.5%；深圳 1 月 412 单。";
const KN_LEAD = "深圳销量最高，共 1,061 单。";
const KN_STUB = {
  answer: KN_ANSWER,
  unverified_numbers: ["82.2 万"],
  key_numbers: [
    { value: "1,061", label: "深圳 · 销量" }, { value: "82.2 万", label: "上海 · 销量" },
    { value: "37.5%", label: "上海 · 占比" }, { value: "412", label: "2024-01 · 深圳" }, { value: "290", label: "第五个" },
  ],
};

test("U3 收尾：关键数字取未核实之外的前 3 个；卡头结论在正文里不重复；刷新重放后照样成立", async ({ page }) => {
  test.setTimeout(90_000);
  await stubFirstResult(page, KN_STUB);
  const file = `u3-kn-${Date.now()}.csv`;
  const sv = await firstTurn(page, file);
  const check = async () => {
    const card = sv.getByTestId("assistant-msg").first();
    await expect(card.getByTestId("key-numbers").locator(".kn-value")).toHaveText(["1,061", "37.5%", "412"]);
    await expect(card.getByTestId("key-numbers").locator(".kn-label")).toHaveText(["深圳 · 销量", "上海 · 占比", "2024-01 · 深圳"]);
    await expect(card.getByTestId("result-lead")).toHaveText(KN_LEAD);
    const md = await card.locator(".answer .md").innerText();
    expect(md.split(KN_LEAD).length - 1).toBe(0);
    expect(md).toContain("上海次之");
  };
  await check();
  await page.reload();
  // 刷新落在首页：从侧栏按数据集名（= 文件名，在会话行的副标题里）点回这个会话，走 GET /sessions/{id} 重放
  await page.getByRole("navigation", { name: "会话" }).getByRole("button", { name: new RegExp(file.replace(/\./g, "\\.")) }).click();
  await expect(sv.getByTestId("assistant-msg")).toHaveCount(1, { timeout: 30_000 });
  await check();
});
