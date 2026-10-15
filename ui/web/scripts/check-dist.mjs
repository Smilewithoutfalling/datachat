// 构建产物检查（npm run build 最后一步）：index.html 不能有内联 <script> 和内联事件处理器。
// 后端给 index.html 的 CSP 是 script-src 'self'，内联脚本会被浏览器拦下、页面白屏——在 CI 里先拦住。
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../dist/index.html", import.meta.url), "utf8");
const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)];
const inline = scripts.filter(([, attrs, body]) => !/\bsrc\s*=/.test(attrs) || body.trim() !== "");
const handlers = html.match(/\son[a-z]+\s*=/gi) ?? [];
if (inline.length || handlers.length) {
  console.error(`dist/index.html：内联 script ${inline.length} 个，内联事件处理器 ${handlers.length} 个（CSP 不允许）`);
  process.exit(1);
}
console.log(`dist/index.html 检查通过：${scripts.length} 个外链 script，0 个内联`);
