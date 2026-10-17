import js from "@eslint/js";
import tseslint from "typescript-eslint";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "test-results", "playwright-report"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx,js,mjs}"],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    plugins: { react, "react-hooks": reactHooks },
    settings: { react: { version: "19" } },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // THREAT_MODEL T9：用户数据一律按文本渲染，禁止 dangerouslySetInnerHTML
      "react/no-danger": "error",
      // F3：ECharts 只从 echarts/core 按需引入（src/charts/register.ts），不 import 全量包
      "no-restricted-imports": ["error", { paths: [{ name: "echarts", message: "从 echarts/core 按需引入，见 src/charts/register.ts" }] }],
      "no-restricted-properties": ["error",
        { property: "innerHTML", message: "T9：不要写 innerHTML，按文本渲染" },
        { property: "outerHTML", message: "T9：不要写 outerHTML" }],
    },
  },
);
