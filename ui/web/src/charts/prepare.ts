// F3 prepare 管线：深拷贝 → normalize → changeKind → applyLayer1 → applySwitches → applyView → cleanup。
// - prepare(spec, ui, theme) 是纯函数（F3 第五步）：图型、开关、主题任何一个输入变了，EChart 都整体重算 + setOption(notMerge)。
//   主题进来是因为渐变色值由这里写死（取主题 color[i]），setTheme 换主题对象不会重算它。
// - normalize：把历史 spec 的几何归一到当前契约（chart_schema.json 的 geometry，后端 GEOMETRY 登记表导出）。
//   分界规则：后端契约改了、而重放路径又原样下发的键，一律在这里归一；后端以后改任何几何 / 外观键都必须在 GEOMETRY 登记
//   （tests/test_charts.py 双向比对登记表与 builder 产物）。在渲染期归一，不动库。
// - changeKind：从后端原始 option 换图型（switches.ts）；开关的兼容性按换完后的图型算，所以排在开关之前。
// - applyLayer1：F4 层 1 样式（layer1.ts）。applySwitches：前端开关，只写 FRONTEND_KEYS 里的值（switches.ts）。
// - applyView（F3 第六步）：交互态（缩放窗口、图例显隐，UiState.view）写回 option。排在开关之后：缩放只在 zoom 开关已经写出
//   dataZoom 时生效。导出（exportPng.ts）和屏幕走同一条管线，导出结果只由 (spec, ui, theme, size) 决定。
// - cleanup 永远最后：按 banned_keys.json 递归删被禁键 → 删顶层 color → 强制 tooltip.renderMode='richText'。放在最后，
//   前面任何一步（含层 1 / 开关）塞进来的被禁键或顶层 color 都会被删掉（charts.test.ts 用替身证明）。
// 纵深防御：第一道是后端 validate_spec（app/tools/charts.py），这里只在后端校验有漏洞时兜底；不是前端校验，也不回验。
// 用户字符串的渲染面规范化（{ } 换行）只在后端 _display_safe 做，这里不镜像一份。
// 顶层 color：配色归主题，后端第四步起不产出；这里删的是第四步之前存进库的 spec（重放路径原样下发、不过 validate_spec，
// tests/test_web_f2.py 钉住）。渐变写在 series 层（series[i].itemStyle / areaStyle.color），从不写顶层 color。
// 不修改输入。
import generated from "../generated/banned_keys.json";
import schema from "../generated/chart_schema.json";
import {
  applySwitchesTo, applyViewTo, asKind, asXKind, canChangeKind, changeKind as changeKindOf, DEFAULT_SWITCHES, type Kind, type Shape,
  type Switches, type View, type XKind,
} from "./switches";
import { DEFAULT_THEME, type ThemeName } from "./themes";
import { applyLayer1To, type Edit } from "./layer1";
import { applyCompactTo } from "./compact";

export const BANNED_KEYS: ReadonlySet<string> = new Set(generated.banned_keys);

export type Json = null | boolean | number | string | Json[] | { [k: string]: Json };
export type Option = { [k: string]: Json };
/** 前端 UI 状态：kind = 用户选的目标图型（null = 后端原图型），sw = 开关，view = 交互态（F3 第六步；不持久化，只有数值）。 */
export type UiState = { kind: Kind | null; sw: Switches; view?: View; edit?: Edit; compact?: boolean };
export const DEFAULT_UI: UiState = { kind: null, sw: DEFAULT_SWITCHES };
/** 进管线的图：spec.kind 是后端出的图型（后端真相，换图型不改它）；x_kind 历史 spec 可能没有。 */
export type ChartInput = { kind: string; x_kind?: string | null; option: Record<string, unknown> };
export type Ctx = { src: Kind | null; kind: Kind | null; xKind: XKind; ui: UiState; theme: ThemeName };
export type Step = (option: Option, ctx: Ctx) => Option;

function strip(node: Json): Json {
  if (Array.isArray(node)) return node.map(strip);
  if (node !== null && typeof node === "object") {
    const out: { [k: string]: Json } = {};
    for (const [k, v] of Object.entries(node)) if (!BANNED_KEYS.has(k)) out[k] = strip(v);
    return out;
  }
  return node;
}

const isObj = (v: Json | undefined): v is { [k: string]: Json } => v !== null && typeof v === "object" && !Array.isArray(v);
const GEOMETRY = schema.geometry as unknown as Record<string, { [k: string]: Json }>;

export const normalize: Step = (option) => {
  for (const [part, reg] of Object.entries(GEOMETRY)) {
    const target = option[part];
    if (!isObj(target)) continue; // 饼图没有 grid / 轴
    for (const [k, v] of Object.entries(reg)) target[k] = JSON.parse(JSON.stringify(v)) as Json;
  }
  return option;
};

export const changeKind: Step = (option, ctx) =>
  ctx.src && ctx.kind && ctx.kind !== ctx.src ? changeKindOf(option, ctx.src, ctx.kind, ctx.xKind) : option;

// F4：层 1 样式（layer1.ts）。排在开关之前：渐变开关以系列自己的 itemStyle.color（用户选的主题色）为底色。
export const applyLayer1: Step = (option, ctx) => applyLayer1To(option, ctx.kind, ctx.theme, ctx.ui.edit);

export const applySwitches: Step = (option, ctx) => {
  if (!ctx.kind) return option;
  const shape: Shape = { kind: ctx.kind, series: Array.isArray(option.series) ? option.series.length : 0, xKind: ctx.xKind };
  return applySwitchesTo(option, { shape, theme: ctx.theme, sw: ctx.ui.sw });
};

export const applyView: Step = (option, ctx) => applyViewTo(option, ctx.ui.view);

export function cleanup(option: Option): Option {
  const out = strip(option) as Option;
  delete out.color;
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

/** 目标图型能不能用：不能换就留在后端原图型（UI 已置灰，这里再兜一次）。 */
export function effectiveKind(spec: ChartInput, ui: UiState): Kind | null {
  const src = asKind(spec.kind);
  if (!src || !ui.kind || ui.kind === src) return src;
  const o = normalize(JSON.parse(JSON.stringify(spec.option)) as Option, {} as Ctx);
  return canChangeKind(o, src, ui.kind, asXKind(spec.x_kind)).ok ? ui.kind : src;
}

/** 管线本体：深拷贝 → steps 依次 → cleanup。导出给测试注入替身；产品只调 prepare。 */
export function runPipeline(spec: ChartInput, ui: UiState, theme: ThemeName, steps: readonly Step[]): Record<string, unknown> {
  // JSON 往返就是深拷贝：option 来自 JSON 响应，本来就只有 JSON 值
  let out = JSON.parse(JSON.stringify(spec.option)) as Option;
  const ctx: Ctx = { src: asKind(spec.kind), kind: effectiveKind(spec, ui), xKind: asXKind(spec.x_kind), ui, theme };
  for (const step of steps) out = step(out, ctx);
  return cleanup(out);
}

// issue #49：矮画布紧凑几何（compact.ts）。排最后：开关可能改 grid.bottom（图例），紧凑只在最终值上收紧。
export const applyCompact: Step = (option, ctx) => (ctx.ui.compact ? applyCompactTo(option) : option);

export const STEPS: readonly Step[] = [normalize, changeKind, applyLayer1, applySwitches, applyView, applyCompact];

export function prepare(spec: ChartInput, ui: UiState = DEFAULT_UI, theme: ThemeName = DEFAULT_THEME): Record<string, unknown> {
  return runPipeline(spec, ui, theme, STEPS);
}
