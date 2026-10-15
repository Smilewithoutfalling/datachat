import { expect, test, type Page } from "@playwright/test";
import { E2E_TOKEN } from "../playwright.config";

// 收集 CSP 违规：用 securitypolicyviolation 事件（比看 console 文本可靠）。init script 经 CDP 注入，不受页面 CSP 约束
async function watchCsp(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __csp: string[] };
    w.__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => w.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
  });
  return () => page.evaluate(() => (window as unknown as { __csp: string[] }).__csp);
}

test("fragment 带 token → 已连接，地址栏立即不含 token，无 CSP 违规", async ({ page }) => {
  const violations = await watchCsp(page);
  const res = await page.goto(`/#token=${E2E_TOKEN}`);
  expect(res?.headers()["content-security-policy"]).toContain("script-src 'self'");
  await expect(page.getByTestId("ready")).toBeVisible();
  expect(page.url()).not.toContain("token");
  expect(await violations()).toEqual([]);

  // 刷新：token 来自 sessionStorage，仍然可用
  await page.reload();
  await expect(page.getByTestId("ready")).toBeVisible();
});

test("错误 token → 会话已失效页", async ({ page }) => {
  await page.goto("/#token=wrong");
  await expect(page.getByRole("heading", { name: "会话已失效" })).toBeVisible();
  expect(page.url()).not.toContain("wrong");
});

test("没有 token（新标签页）→ 会话已失效页", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "会话已失效" })).toBeVisible();
});

test("静态资源不要 token，API 要", async ({ request }) => {
  expect((await request.get("/")).status()).toBe(200);
  expect((await request.get("/datasets")).status()).toBe(401);
});

test("对照：CSP 确实生效——页面里塞进的内联脚本被拦，且被记到", async ({ page }) => {
  const violations = await watchCsp(page);
  await page.goto(`/#token=${E2E_TOKEN}`);
  await expect(page.getByTestId("ready")).toBeVisible();
  const ran = await page.evaluate(() => {
    const w = window as unknown as { __pwned?: boolean };
    const s = document.createElement("script");
    s.textContent = "window.__pwned = true";
    document.body.appendChild(s);
    return w.__pwned === true;
  });
  expect(ran).toBe(false);
  await expect.poll(violations).toContainEqual(expect.stringContaining("script-src"));
});
