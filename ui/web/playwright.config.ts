import { defineConfig, devices } from "@playwright/test";

// 后端托管 npm run build 的产物，带真实 CSP 头，测的就是用户拿到的东西。
// 两个后端、两个 project，前提互不污染：
//   nokey：没有 Key（f0/f1/f2），期望"模型调用失败"那条路径。
//   fake ：base_url 指向假模型服务（tests/fake_llm.py，独立进程、无状态），场景由 model 名决定（每个测试用
//          PUT /settings 设 model），F3 起的停止 / 图表 / 重试测试都走这里。
const PORT = Number(process.env.E2E_PORT ?? 8766);
const FAKE_BACKEND_PORT = PORT + 1;
const FAKE_LLM_PORT = PORT + 2;
export const E2E_TOKEN = "e2e-token-not-secret";

const backend = (port: number, home: string, env: Record<string, string>) => ({
  command: `python -m app.server --port ${port} --token ${E2E_TOKEN} --home ui/web/test-results/${home}`,
  cwd: "../..",
  url: `http://127.0.0.1:${port}/health`,
  // 钥匙串强制用 fail 后端：开发机钥匙串里存了 Key 也不读，Key 只来自下面的环境变量
  env: { DATACHAT_WEB_DIST: "ui/web/dist", PYTHON_KEYRING_BACKEND: "keyring.backends.fail.Keyring", PYTHONUTF8: "1", ...env },
  reuseExistingServer: false,
  timeout: 60_000,
});

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  retries: 0,
  workers: 1, // fake 后端的 model 是全局设置，同一后端上的测试不能并行
  reporter: [["list"]],
  use: { ...devices["Desktop Chrome"] },
  projects: [
    { name: "nokey", testMatch: /f[012]\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${PORT}` } },
    { name: "fake", testMatch: /f3.*\.spec\.ts/, use: { baseURL: `http://127.0.0.1:${FAKE_BACKEND_PORT}` } },
  ],
  webServer: [
    {
      command: `python -m tests.fake_llm --port ${FAKE_LLM_PORT}`,
      cwd: "../..",
      url: `http://127.0.0.1:${FAKE_LLM_PORT}/health`,
      env: { PYTHONUTF8: "1" },
      reuseExistingServer: false,
      timeout: 30_000,
    },
    // f2.spec 依赖"没有 Key"（期望"模型调用失败"），并在提问前断言 configured=false
    backend(PORT, "home", { DEEPSEEK_API_KEY: "" }),
    backend(FAKE_BACKEND_PORT, "home-fake", {
      DEEPSEEK_API_KEY: "fake-key-not-secret",
      DEEPSEEK_BASE_URL: `http://127.0.0.1:${FAKE_LLM_PORT}/v1`,
      DEEPSEEK_MODEL: "ok",
      DATACHAT_LLM_MAX_RETRIES: "0",
    }),
  ],
});
