// F3 第五步：前端开关 + 换图型（docs/roadmap/phase5-frontend.md「F3 第五步」）。
// - COMPAT 是唯一一张"开关 × 图型"兼容表：UI 置灰和 applySwitches 的过滤都读它，不各写一份。
// - FRONTEND_KEYS 是白名单外的例外层：路径 → 值集合。applySwitches 写值时只经 put() 从这张表取，代码里没有第二处字面量；
//   switches.test.ts 的例外层测试对 prepare 产物相对"builder 等价产物"求差，新增 / 改动必须 ⊆ 这张表、值必须在值集合里。
//   值只有字面量、主题色（渐变）和排列（排序），不含任何字符串型用户数据，所以后端 _check_strings 管不到也没关系（THREAT_MODEL §2.3）。
// - changeKind 一律从后端原始 option 出发（不链式转换），造出和 build_option 直接出的 B 一样的 option（换图型契约测试钉住，
//   只允许 KIND_DIFF 列出的差异）。框架值和阈值都从 chart_schema.json 读，不写第二份。
// - spec.kind 是后端出的图型（后端真相），换图型只改 option，spec.kind 不动：两者有意不一致，
//   switches.test.ts 的 spec_kind_is_backend_truth 钉住，别"修"。
import schema from "../generated/chart_schema.json";
import type { Json, Option } from "./prepare";
import { THEMES, type ThemeName } from "./themes";

export const KINDS = ["bar", "line", "area", "pie", "scatter"] as const;
export type Kind = (typeof KINDS)[number];
export const KIND_LABEL: Record<Kind, string> = { bar: "柱状图", line: "折线图", area: "面积图", pie: "饼图", scatter: "散点图" };
export type XKind = "category" | "time" | "value" | null; // null = 历史 spec 没有 x_kind（第五步之前存进库的）

export const SWITCHES = ["label", "legend", "stack", "smooth", "gradient", "radius", "sort", "marks", "zoom"] as const;
export type SwitchName = (typeof SWITCHES)[number];
export type Switches = {
  label: boolean; legend: "bottom" | "top"; stack: boolean; smooth: boolean; gradient: boolean;
  radius: boolean; sort: "off" | "desc" | "asc"; marks: boolean; zoom: boolean;
};
/** 每个开关的合法取值，第一个是默认（"关"）。读 localStorage 时逐字段按它校验。 */
export const SWITCH_VALUES: { readonly [K in SwitchName]: readonly Switches[K][] } = {
  label: [false, true], legend: ["bottom", "top"], stack: [false, true], smooth: [false, true], gradient: [false, true],
  radius: [false, true], sort: ["off", "desc", "asc"], marks: [false, true], zoom: [false, true],
};
export const DEFAULT_SWITCHES: Switches = Object.fromEntries(SWITCHES.map((s) => [s, SWITCH_VALUES[s][0]])) as Switches;
export const SWITCH_LABEL: Record<SwitchName, string> = {
  label: "数值标签", legend: "图例位置", stack: "堆叠", smooth: "平滑", gradient: "渐变",
  radius: "圆角", sort: "排序", marks: "平均线和极值", zoom: "缩放",
};

// ---- 兼容表 ----------------------------------------------------------------------------------
// yes：总能用；no：这种图型不支持；multi：≥2 个系列；single-nontime：单系列且不是时间轴（历史 spec 没有 x_kind 时不拦，
// 降级规则只有"不可换饼图"一条，S 10-19）。
export type Cond = "yes" | "no" | "multi" | "single-nontime";
export const COMPAT: Record<SwitchName, Record<Kind, Cond>> = {
  label:    { bar: "yes", line: "yes", area: "yes", pie: "yes", scatter: "no" },     // scatter 点多时满屏
  legend:   { bar: "multi", line: "multi", area: "multi", pie: "no", scatter: "multi" }, // 饼图图例竖排在左，不挪
  stack:    { bar: "multi", line: "multi", area: "multi", pie: "no", scatter: "no" },
  smooth:   { bar: "no", line: "yes", area: "yes", pie: "no", scatter: "no" },
  gradient: { bar: "yes", line: "no", area: "yes", pie: "no", scatter: "no" },      // 折线没有填充
  radius:   { bar: "yes", line: "no", area: "no", pie: "no", scatter: "no" },
  sort:     { bar: "single-nontime", line: "no", area: "no", pie: "yes", scatter: "no" },
  marks:    { bar: "yes", line: "yes", area: "yes", pie: "no", scatter: "no" },
  zoom:     { bar: "yes", line: "yes", area: "yes", pie: "no", scatter: "no" },
};

export type Shape = { kind: Kind; series: number; xKind: XKind };
export type Verdict = { ok: true } | { ok: false; reason: string };
const OK: Verdict = { ok: true };
const no = (reason: string): Verdict => ({ ok: false, reason });

export function compat(sw: SwitchName, s: Shape): Verdict {
  switch (COMPAT[sw][s.kind]) {
    case "yes": return OK;
    case "no": return no(`${KIND_LABEL[s.kind]}不支持${SWITCH_LABEL[sw]}`);
    case "multi": return s.series >= 2 ? OK : no("只有一个系列");
    case "single-nontime":
      if (s.series !== 1) return no("多系列不能排序");
      return s.xKind === "time" ? no("时间轴不排序") : OK;
  }
}

// ---- 例外层：路径 → 值集合 ---------------------------------------------------------------------
// 路径里数组下标写成 []。值集合三种：lit（字面量，按 JSON 比对）、gradient（第 6 条的固定结构，颜色取当前主题 color）、
// perm（排序：只许是原数组的一个排列）。
// F3 第六步加两种：range（有限数、落在区间内；dataZoom 的 start / end）、legendItems（legend.selected：键必须是 option 里
// 已有的图例项名——直角坐标是 series[i].name，饼图是 series[0].data[i].name——值是布尔）。legend.selected 的键是用户串
// （列名 / 类目），但它取自 option 本身、不来自 UiState：UiState.view 只存 index（S 10-19）。
export type ValueSet = { lit: readonly Json[] } | { gradient: true } | { perm: true } | { range: readonly [number, number] } | { legendItems: true };
export const DATA_ZOOM: Json = [{ type: "inside", zoomOnMouseWheel: "shift", moveOnMouseWheel: false, moveOnMouseMove: true }];
export const FRONTEND_KEYS: Readonly<Record<string, ValueSet>> = {
  "legend.top": { lit: ["top"] },
  "series[].label.show": { lit: [true] },
  "series[].label.position": { lit: ["top", "inside", "outside"] },
  "series[].stack": { lit: ["total"] },
  "series[].smooth": { lit: [true] },
  "series[].itemStyle.color": { gradient: true },
  "series[].areaStyle.color": { gradient: true },
  "series[].itemStyle.borderRadius": { lit: [[4, 4, 0, 0]] },
  "series[].markLine.data": { lit: [[{ type: "average" }]] },
  "series[].markPoint.data": { lit: [[{ type: "max" }, { type: "min" }]] },
  // inside：不用 slider（slider 不进 outerBounds，压住 x 轴名）；Shift + 滚轮才缩放，普通滚轮滚页面（S 10-19）
  dataZoom: { lit: [DATA_ZOOM] },
  // F3 第六步：交互态（UiState.view）写回的缩放窗口和图例显隐。dataZoom 本身仍是上面那条字面量，start / end 是它的子键
  "dataZoom[].start": { range: [0, 100] },
  "dataZoom[].end": { range: [0, 100] },
  "legend.selected": { legendItems: true },
  "xAxis.data": { perm: true },
  "series[].data": { perm: true },
};

const same = (a: Json, b: Json) => JSON.stringify(a) === JSON.stringify(b);

/** 取 FRONTEND_KEYS[path] 里等于 value 的那个字面量（深拷贝）；不在值集合里就抛错——开关代码写不出表外的值。 */
function lit(path: string, value: Json): Json {
  const set = FRONTEND_KEYS[path];
  if (!set || !("lit" in set)) throw new Error(`FRONTEND_KEYS 没有字面量路径 ${path}`);
  const hit = set.lit.find((v) => same(v, value));
  if (hit === undefined) throw new Error(`${path} 的值不在 FRONTEND_KEYS 里：${JSON.stringify(value)}`);
  return JSON.parse(JSON.stringify(hit)) as Json;
}

/** 取 FRONTEND_KEYS[path] 的区间值：不是有限数或出了区间就抛错（调用方先校验，这里是第二道）。 */
function inRange(path: string, v: number): number {
  const set = FRONTEND_KEYS[path];
  if (!set || !("range" in set)) throw new Error(`FRONTEND_KEYS 没有区间路径 ${path}`);
  if (!Number.isFinite(v) || v < set.range[0] || v > set.range[1]) throw new Error(`${path} 越界：${v}`);
  return v;
}

/** 渐变第二端：同一颜色、透明度 0。主题色格式已由 themes.test.ts 钉成 #RRGGBB，格式不对就抛错，不静默降级。 */
export function rgba0(hex: string): string {
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  if (!m) throw new Error(`主题色不是 #RRGGBB：${hex}`);
  return `rgba(${parseInt(m[1], 16)}, ${parseInt(m[2], 16)}, ${parseInt(m[3], 16)}, 0)`;
}
export function gradient(color: string): Json {
  return { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color }, { offset: 1, color: rgba0(color) }] };
}

type Obj = { [k: string]: Json };
const isObj = (v: Json | undefined): v is Obj => v !== null && typeof v === "object" && !Array.isArray(v);
const sub = (o: Obj, k: string): Obj => (isObj(o[k]) ? (o[k] as Obj) : (o[k] = {}));
const seriesOf = (o: Option): Obj[] => (Array.isArray(o.series) ? (o.series.filter(isObj) as Obj[]) : []);

export type SwitchCtx = { shape: Shape; theme: ThemeName; sw: Switches };

/** 按开关改 option（就地改，调用方传的是 prepare 里的深拷贝）。不兼容的开关不生效。 */
export function applySwitchesTo(o: Option, { shape, theme, sw }: SwitchCtx): Option {
  const on = (s: SwitchName) => sw[s] !== SWITCH_VALUES[s][0] && compat(s, shape).ok;
  const series = seriesOf(o);
  const stacked = on("stack");
  if (on("legend") && isObj(o.legend)) o.legend.top = lit("legend.top", sw.legend);
  if (stacked) for (const s of series) s.stack = lit("series[].stack", "total");
  if (on("smooth")) for (const s of series) s.smooth = lit("series[].smooth", true);
  if (on("label")) {
    const pos = shape.kind === "pie" ? "outside" : stacked ? "inside" : "top";
    for (const s of series) {
      const l = sub(s, "label");
      l.show = lit("series[].label.show", true);
      l.position = lit("series[].label.position", pos);
    }
  }
  if (on("gradient")) {
    const palette = THEMES[theme].theme.color;
    series.forEach((s, i) => {
      const g = gradient(palette[i % palette.length]);
      if (shape.kind === "area") sub(s, "areaStyle").color = g;
      else sub(s, "itemStyle").color = g;
    });
  }
  if (on("radius")) {
    // 堆叠时只有最上面的系列圆角，否则每一段都圆，堆起来像一串珠子
    for (const s of stacked ? series.slice(-1) : series) sub(s, "itemStyle").borderRadius = lit("series[].itemStyle.borderRadius", [4, 4, 0, 0]);
  }
  if (on("marks")) {
    for (const s of series) {
      sub(s, "markLine").data = lit("series[].markLine.data", [{ type: "average" }]);
      sub(s, "markPoint").data = lit("series[].markPoint.data", [{ type: "max" }, { type: "min" }]);
    }
  }
  if (on("zoom")) o.dataZoom = lit("dataZoom", DATA_ZOOM);
  if (on("sort")) sortInPlace(o, shape.kind, sw.sort === "asc" ? 1 : -1);
  return o;
}

const valueOf = (v: Json): number | null => (typeof v === "number" ? v : isObj(v) && typeof v.value === "number" ? v.value : null);
/** 稳定排序，null 永远排最后（不随升降序翻转）。 */
function order(vals: (number | null)[], dir: 1 | -1): number[] {
  return vals.map((v, i) => [v, i] as const).sort(([a, i], [b, j]) => {
    if (a === null || b === null) return a === null && b === null ? i - j : a === null ? 1 : -1;
    return a === b ? i - j : (a - b) * dir;
  }).map(([, i]) => i);
}
function sortInPlace(o: Option, kind: Kind, dir: 1 | -1) {
  const s = seriesOf(o)[0];
  if (!s || !Array.isArray(s.data)) return;
  const data = s.data;
  const idx = order(data.map(valueOf), dir);
  s.data = idx.map((i) => data[i]);
  if (kind !== "pie" && isObj(o.xAxis) && Array.isArray(o.xAxis.data)) {
    const cats = o.xAxis.data; // 类目和值一起移动
    o.xAxis.data = idx.map((i) => cats[i]);
  }
}

// ---- 换图型 -----------------------------------------------------------------------------------
const CARTESIAN: readonly Kind[] = ["bar", "line", "area"];
const isCart = (k: Kind) => CARTESIAN.includes(k);

export function asKind(k: unknown): Kind | null {
  return typeof k === "string" && (KINDS as readonly string[]).includes(k) ? (k as Kind) : null;
}
export function asXKind(k: unknown): XKind {
  return typeof k === "string" && (schema.x_kinds as string[]).includes(k) ? (k as XKind) : null;
}

/** from → to 能不能换（§6.3 落成条件，S 10-19 放宽：直角坐标三种之间系列数不限）。原因是固定文案，不拼接数据。 */
export function canChangeKind(o: Option, from: Kind, to: Kind, xKind: XKind): Verdict {
  if (from === to) return OK;
  if (from === "scatter" || to === "scatter") return no("散点图不能和其他图型互换");
  if (from === "pie") return OK;
  if (to !== "pie") return OK; // 直角坐标三种互换
  const series = seriesOf(o);
  if (series.length !== 1) return no("多系列不能换成饼图");
  if (xKind === null) return no("旧图缺少类型信息，不能换成饼图");
  if (xKind !== "category") return no("时间轴不能换成饼图");
  const data = Array.isArray(series[0].data) ? series[0].data : [];
  if (data.some((v) => typeof v !== "number")) return no("有空值，不能换成饼图");
  if (data.some((v) => (v as number) < 0)) return no("有负值，不能换成饼图");
  if (data.length > schema.pie_max_slices) return no(`类目超过 ${schema.pie_max_slices} 个，不能换成饼图`);
  return OK;
}

const G = schema.geometry as unknown as { xAxis: Obj; yAxis: Obj };
const F = schema.frame as unknown as { cartesian_grid: Obj; cartesian_bottom: { single: number; multi: number }; pie_legend: Obj; pie_radius: Json[]; pie_center: Json[] };
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

function cartSeries(name: Json, kind: Kind, data: Json[], nCats: number): Obj {
  const s: Obj = { name, type: kind === "bar" ? "bar" : "line", data };
  if (kind === "area") s.areaStyle = {};
  if (kind !== "bar") s.showSymbol = nCats <= schema.show_symbol_max;
  return s;
}

/** 从后端原始 option（已 normalize）换成 to。调用前必须 canChangeKind 为 ok。 */
export function changeKind(o: Option, from: Kind, to: Kind, xKind: XKind): Option {
  if (from === to) return o;
  const out: Option = clone(o);
  const series = seriesOf(out);
  if (isCart(from) && isCart(to)) {
    const cats = isObj(out.xAxis) && Array.isArray(out.xAxis.data) ? out.xAxis.data.length : 0;
    out.series = series.map((s) => cartSeries(s.name, to, Array.isArray(s.data) ? s.data : [], cats));
    if (isObj(out.xAxis)) out.xAxis.boundaryGap = to === "bar";
    return out;
  }
  const keepTitle = (next: Option) => (out.title !== undefined ? { title: out.title, ...next } : next);
  if (to === "pie") {
    const s = series[0];
    const cats = isObj(out.xAxis) && Array.isArray(out.xAxis.data) ? out.xAxis.data : [];
    const vals = Array.isArray(s.data) ? s.data : [];
    return keepTitle({
      tooltip: { trigger: "item" },
      legend: clone(F.pie_legend),
      series: [{ name: s.name, type: "pie", radius: clone(F.pie_radius), center: clone(F.pie_center),
        data: cats.map((c, i) => ({ name: c, value: vals[i] })) }],
    });
  }
  // pie → 直角坐标：pie 的 option 里没有 x 列名，x 轴名为空（KIND_DIFF 唯一一行，和 builder 在 xs.name is None 时一致）
  const s = series[0];
  const items = (Array.isArray(s.data) ? s.data : []).filter(isObj);
  const cats = items.map((d) => d.name);
  const xAxis: Obj = { type: "category", name: "", data: cats, boundaryGap: to === "bar", ...clone(G.xAxis) };
  if (xKind === "time") xAxis.axisLabel = { hideOverlap: true };
  return keepTitle({
    tooltip: { trigger: "axis" },
    legend: { show: false, top: "bottom" },
    grid: { ...clone(F.cartesian_grid), bottom: F.cartesian_bottom.single, ...clone((schema.geometry as unknown as { grid: Obj }).grid) },
    xAxis,
    yAxis: { type: "value", name: s.name, ...clone(G.yAxis) },
    series: [cartSeries(s.name, to, items.map((d) => d.value), cats.length)],
  });
}

/** 换图型契约里允许的差异（表外任何差异都红）。boundaryGap / areaStyle / showSymbol 不在表里：必须和 builder 一致。 */
export const KIND_DIFF: readonly { from: "pie"; path: "xAxis.name"; why: string }[] = [
  { from: "pie", path: "xAxis.name", why: "pie 的 option 里没有 x 列名；和 builder 在 xs.name is None 时一致（空串）" },
];

// ---- 交互态（F3 第六步）-------------------------------------------------------------------------
// 缩放窗口和图例显隐在事件发生时写进 UiState.view（EChart 监听 datazoom / legendselectchanged），导出和屏幕走同一条
// prepare，不从实例里捞（getOption 是渲染产物、带全部 data；getModel 是内部 API。S 10-19）。
// hidden 存图例项的 index，不存名字：名字是用户串（列名 / 类目），不进 UiState。view 只有数值。
export type ZoomWindow = { start: number; end: number };
export type View = { zoom: ZoomWindow | null; hidden: number[] };
export const EMPTY_VIEW: View = { zoom: null, hidden: [] };

/** 合法的缩放窗口：0–100 的有限数、start ≤ end；全量（0, 100）归成 null。不合法返回 null。 */
export function asZoom(start: unknown, end: unknown): ZoomWindow | null {
  if (typeof start !== "number" || typeof end !== "number") return null;
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end > 100 || start > end) return null;
  return start === 0 && end === 100 ? null : { start, end };
}

/** 图例项名：饼图是扇区（series[0].data[i].name），其余是系列（series[i].name）。顺序就是 hidden 里 index 的含义。 */
export function legendItems(o: Option): Json[] {
  const series = seriesOf(o);
  if (series[0]?.type === "pie") return (Array.isArray(series[0].data) ? series[0].data : []).map((d) => (isObj(d) ? d.name : null));
  return series.map((s) => s.name);
}

/** legendselectchanged 的 selected（名字 → 布尔）换成被隐藏项的 index；名字只在这里过一手，不往外带。 */
export function hiddenFromSelected(o: Option, selected: unknown): number[] {
  if (!selected || typeof selected !== "object") return [];
  const sel = selected as Record<string, unknown>;
  const out: number[] = [];
  legendItems(o).forEach((name, i) => {
    if (typeof name === "string" && Object.prototype.hasOwnProperty.call(sel, name) && sel[name] === false) out.push(i);
  });
  return out;
}

/** 把 view 写进 option（就地改）。缩放只在开关已经写出 dataZoom 时生效；hidden 越界的丢掉；图例没显示时不写。 */
export function applyViewTo(o: Option, view: View | undefined): Option {
  if (!view) return o;
  if (view.zoom && Array.isArray(o.dataZoom)) {
    const z = asZoom(view.zoom.start, view.zoom.end);
    if (z) for (const d of o.dataZoom) if (isObj(d)) { d.start = inRange("dataZoom[].start", z.start); d.end = inRange("dataZoom[].end", z.end); }
  }
  if (view.hidden.length && isObj(o.legend) && o.legend.show !== false) {
    const items = legendItems(o);
    const selected: Obj = {};
    for (const i of new Set(view.hidden)) {
      const name = Number.isInteger(i) && i >= 0 && i < items.length ? items[i] : null;
      if (typeof name === "string") selected[name] = false;
    }
    if (Object.keys(selected).length) o.legend.selected = selected;
  }
  return o;
}
