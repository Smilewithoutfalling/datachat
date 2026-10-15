/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 开发时（npm run dev）把 API 转给本机后端；生产由 FastAPI 同源托管 dist，不需要代理。
const API = ["/health", "/datasets", "/sessions", "/messages", "/charts", "/settings"];
const backend = process.env.DATACHAT_BACKEND ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  build: {
    // 只跑现代 WebView / Chrome，不需要 modulepreload polyfill；index.html 必须没有内联 <script>（CSP，见 scripts/check-dist.mjs）
    modulePreload: { polyfill: false },
    sourcemap: false,
  },
  server: {
    proxy: Object.fromEntries(API.map((p) => [p, { target: backend, changeOrigin: true }])),
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
