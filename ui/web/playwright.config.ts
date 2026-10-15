import { defineConfig, devices } from "@playwright/test";

// 只在 CI 跑（S 本机不装浏览器）：后端托管 npm run build 的产物，带真实 CSP 头，测的就是用户拿到的东西。
const PORT = Number(process.env.E2E_PORT ?? 8766);
export const E2E_TOKEN = "e2e-token-not-secret";

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${PORT}`, ...devices["Desktop Chrome"] },
  webServer: {
    command: `python -m app.server --port ${PORT} --token ${E2E_TOKEN} --home ui/web/test-results/home`,
    cwd: "../..",
    url: `http://127.0.0.1:${PORT}/health`,
    env: { DATACHAT_WEB_DIST: "ui/web/dist", DEEPSEEK_API_KEY: "", PYTHONUTF8: "1" },
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
