import { expect, type Page, test } from "@playwright/test";
import { E2E_TOKEN } from "../playwright.config";

// 阶段 7.6 U4 空态卡（docs/roadmap/phase76-ui.md §2 U4 验收：点任一张卡都会产生一轮对话）。在后端托管的 dist 上真机跑（fake project）。
// 首页上传 → 回首页：问候 → 数据资产 → 三张提问卡；点卡 = POST /sessions + POST /sessions/{id}/messages（E1 复用现有链路），
// 会话页里出现用户那句话和一轮完成的助手回答（fake_llm 的 ok 场景出「（fake）结论」）。三张卡各跑一遍。
const auth = { Authorization: `Bearer ${E2E_TOKEN}` };
const SALES = "月份,城市,销量\n2024-01,深圳,412\n2024-01,上海,365\n2024-02,深圳,290\n2024-02,上海,9999\n";
const CARDS = [
  { id: "overview", title: "看看这份数据有什么" },
  { id: "outliers", title: "找出异常值" },
  { id: "compare", title: "两期对比" },
] as const;

function watchPosts(page: Page) {
  const posts: { path: string; body: unknown }[] = [];
  page.on("request", (r) => {
    if (r.method() !== "POST") return;
    const path = new URL(r.url()).pathname;
    if (path === "/sessions" || /^\/sessions\/[^/]+\/messages$/.test(path)) posts.push({ path, body: r.postDataJSON() });
  });
  return posts;
}

// 预热（照 f4-visual）：冷后端第一次分析要 20 秒以上，挪出用例的超时窗口
test.beforeAll(async ({ request }) => {
  test.setTimeout(150_000);
  expect((await request.put("/settings", { headers: auth, data: { model: "ok" } })).ok()).toBe(true);
  const ds = await (await request.post("/datasets", {
    headers: auth, multipart: { files: { name: "starter-warm.csv", mimeType: "text/csv", buffer: Buffer.from(SALES) } },
  })).json();
  const s = await (await request.post("/sessions", { headers: auth, data: { dataset_id: ds.id } })).json();
  const r = await request.post(`/sessions/${s.id}/messages`, { headers: auth, data: { content: "预热" }, timeout: 140_000 });
  expect(await r.text()).toContain("event: done");
});

for (const card of CARDS) {
  test(`U4 空态卡：首页上传后点「${card.title}」产生一轮对话`, async ({ page }) => {
    test.setTimeout(90_000);
    expect((await page.request.put("/settings", { headers: auth, data: { model: "ok" } })).ok()).toBe(true);
    const posts = watchPosts(page);
    await page.goto(`/#token=${E2E_TOKEN}`);
    const name = `starter-${card.id}.csv`;
    await page.getByLabel("选择 CSV 文件").setInputFiles([{ name, mimeType: "text/csv", buffer: Buffer.from(SALES) }]);
    await page.getByRole("button", { name: "上传" }).click();
    await page.getByTestId("dataset-view").waitFor();
    await page.getByRole("button", { name: "返回", exact: true }).click();

    // 结构：问候 → 数据资产（刚上传的这个，数字来自上传响应的 profile）→ 三张提问卡
    const home = page.getByTestId("starter-home");
    await expect(home.getByRole("heading", { level: 2 })).toHaveText(/^(早上好|中午好|下午好|晚上好)$/);
    const asset = home.getByTestId("starter-asset");
    await expect(asset.getByTestId("starter-asset-name")).toHaveText(new RegExp(`^${name.replace(".", "\\.")}( · \\d\\d:\\d\\d)?$`)); // 没填名称时数据集名就是文件名；重名时带创建时间
    await expect(asset.getByTestId("starter-asset-line")).toHaveText("1 个表 · 4 行 · 3 列 · 无缺失列");
    await expect(home.locator(".starter-card-title")).toHaveText(CARDS.map((c) => c.title));
    const order = await home.evaluate((el) =>
      [el.querySelector("h2"), el.querySelector("[data-testid=starter-asset]"), el.querySelector(".starter-cards")]
        .map((x) => (x as HTMLElement).getBoundingClientRect().top));
    expect(order[0]).toBeLessThan(order[1]);
    expect(order[1]).toBeLessThan(order[2]);

    const question = await home.getByTestId(`starter-${card.id}`).getAttribute("title");
    expect(question).toBeTruthy();
    await home.getByTestId(`starter-${card.id}`).click();

    // 一轮对话：用户气泡是卡片那句话，助手回答完成并落库
    const sv = page.getByTestId("session-view");
    await expect(sv.locator(".msg.user .bubble").first()).toHaveText(question!);
    await expect(sv.getByTestId("assistant-msg")).toHaveCount(1, { timeout: 60_000 });
    await expect(sv.getByTestId("assistant-msg")).toContainText("（fake）结论");

    // 真实请求：先建会话（这个数据集），再发这句提问，各一次
    expect(posts.map((p) => p.path.replace(/\/sessions\/[^/]+\//, "/sessions/:id/"))).toEqual(["/sessions", "/sessions/:id/messages"]);
    expect(posts[1].body).toEqual({ content: question });
    const ds = (await (await page.request.get("/datasets", { headers: auth })).json()).find((d: { name: string }) => d.name === name);
    expect((posts[0].body as { dataset_id: string }).dataset_id).toBe(ds.id);
    // 库里也是一问一答
    const sid = posts[1].path.split("/")[2];
    const detail = await (await page.request.get(`/sessions/${sid}`, { headers: auth })).json();
    expect(detail.messages.map((m: { role: string }) => m.role)).toEqual(["user", "assistant"]);
    expect(detail.messages[0].content).toBe(question);
  });
}
