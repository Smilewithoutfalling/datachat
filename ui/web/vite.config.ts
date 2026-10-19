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
    // 默认只许读 ui/web 内的文件；switches.test.ts 用 ?raw 读 docs/roadmap/M13-图表方案.md 的 §12 表比对 FRONTEND_KEYS（F3 第五步）。
    // 只放开这一个文档目录；产品代码不 import 它（build 产物检查见 scripts/check-dist.mjs）。
    fs: { allow: [".", "../../docs/roadmap"] },
    proxy: Object.fromEntries(API.map((p) => [p, { target: backend, changeOrigin: true }])),
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
