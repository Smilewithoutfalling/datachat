// F3 prepare 管线（第三步起是骨架）：深拷贝 → applyLayer1 → applySwitches → cleanup。
// - applyLayer1 / applySwitches：本步恒等，第五步填层 1 样式与前端开关。
// - cleanup 永远最后：按 banned_keys.json 递归删被禁键 → 强制 tooltip.renderMode='richText'。放在最后，前面任何一步
//   （包括将来的层 1 / 开关）塞进来的被禁键都会被删掉（charts.test.ts 用替身证明）。
// 纵深防御：第一道是后端 validate_spec（app/tools/charts.py），这里只在后端校验有漏洞时兜底；不是前端校验，也不回验。
// 用户字符串的渲染面规范化（{ } 换行）只在后端 _display_safe 做，这里不镜像一份，避免两处规则漂移（方案第三步第 4 条）。
// 不修改输入。renderMode 本身也在禁用键里（后端不许决定它），删完之后由这里统一写成 richText（THREAT_MODEL §2.3）。
import generated from "../generated/banned_keys.json";

export const BANNED_KEYS: ReadonlySet<string> = new Set(generated.banned_keys);

export type Json = null | boolean | number | string | Json[] | { [k: string]: Json };
export type Option = { [k: string]: Json };
/** 前端 UI 状态（开关等）。第三步是空类型，第五步填。 */
export type UiState = Record<string, never>;
export type Step = (option: Option, ui: UiState) => Option;

function strip(node: Json): Json {
  if (Array.isArray(node)) return node.map(strip);
  if (node !== null && typeof node === "object") {
    const out: { [k: string]: Json } = {};
    for (const [k, v] of Object.entries(node)) if (!BANNED_KEYS.has(k)) out[k] = strip(v);
    return out;
  }
  return node;
}

// 恒等步骤不声明 ui 形参：TS 允许少参数的函数赋给 Step；写 _ui 虽过 tsc（noUnusedParameters 放过下划线），
// 但 ESLint 的 no-unused-vars 不放过。第五步真正用到 ui 时再加形参。
export const applyLayer1: Step = (option) => option;
export const applySwitches: Step = (option) => option;

export function cleanup(option: Option): Option {
  const out = strip(option) as Option;
  const t = out.tooltip;
  if (Array.isArray(t)) {
    out.tooltip = t.map((x) => (x !== null && typeof x === "object" && !Array.isArray(x) ? { ...x, renderMode: "richText" } : { renderMode: "richText" }));
  } else if (t !== null && typeof t === "object") {
    out.tooltip = { ...t, renderMode: "richText" };
  } else {
    out.tooltip = { renderMode: "richText" };
  }
  return out;
}

/** 管线本体：深拷贝 → steps 依次 → cleanup。导出给测试注入替身；产品只调 prepare。 */
export function runPipeline(option: Record<string, unknown>, ui: UiState, steps: readonly Step[]): Record<string, unknown> {
  // JSON 往返就是深拷贝：option 来自 JSON 响应，本来就只有 JSON 值
  let out = JSON.parse(JSON.stringify(option)) as Option;
  for (const step of steps) out = step(out, ui);
  return cleanup(out);
}

export function prepare(option: Record<string, unknown>, ui: UiState): Record<string, unknown> {
  return runPipeline(option, ui, [applyLayer1, applySwitches]);
}
