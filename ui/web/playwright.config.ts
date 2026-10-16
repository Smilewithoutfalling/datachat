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
    // 显式固定"没有 Key"：环境变量置空 + 钥匙串强制用 fail 后端（开发机钥匙串里存了 Key 也不读）。
    // f2.spec 依赖这个前提（期望"模型调用失败"），并在提问前断言 configured=false。
    env: { DATACHAT_WEB_DIST: "ui/web/dist", DEEPSEEK_API_KEY: "", PYTHON_KEYRING_BACKEND: "keyring.backends.fail.Keyring", PYTHONUTF8: "1" },
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
