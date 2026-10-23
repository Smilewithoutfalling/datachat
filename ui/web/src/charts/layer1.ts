// F4 层 1 面板（docs/roadmap/phase5-frontend.md「F4：层 1 面板」）：用户对单张图的样式改动。
// - 只改 M13 §3.2 层 1 的样式键：yAxis.min / max（仅用户）、series[i].itemStyle.color（饼图是 data[i].itemStyle.color）、
//   textStyle.fontSize；再加饼图「合并为'其他'」（仅用户，默认关）。visualMap.pieces 不做（方案第 5 条）。
// - 输入只有三类：有限数、调色板 index、枚举。没有任何用户字符串进 option（"其他"、合并提示是前端字面量）。
//   唯一例外是 V2b B3 的 title（见 title.ts）。
//   写出的键和值集合登记在 LAYER1_KEYS，layer1.test.ts 做机制测试。它和 switches.ts 的 FRONTEND_KEYS 分开：
//   FRONTEND_KEYS 和 M13 §12 的开关表逐字比对，层 1 不在那张表里（偏离方案第 8 条"加进 FRONTEND_KEYS"，DEVLOG [44]）。
// - 颜色存调色板 index 不存 hex：换主题后跟着主题走，对比度检查照旧成立。
// - 存储：localStorage 的 datachat.chartEdit:<message_id>:<图序号>，读写 try/catch，逐字段校验，坏字段丢掉。
// V2b（phase5「阶段 5 收尾」B2–B4）：
// - B2 按类目着色：Edit.colorBy "series" | "data"，只对单系列柱图生效，写 series[].colorBy = 'data'；颜色改成按类目
//   （series[0].data[i].itemStyle.color，数值点就地包成 {value}），和饼图一样。
// - B3 标题：Edit.title 是"用户串不进 option"的唯一例外，规则见 title.ts（sanitizeTitle）。
// - B4 图型级默认：每张图只存"自己设过"的字段（EditPatch）；生效的层 1 = EMPTY_EDIT ← 图型默认（datachat.chartEditKind:<kind>，
//   只含可迁移字段 colors / colorBy / font / other）← 这张图自己设过的字段。老数据里有的字段都视为这张图自己设过。
import type { Json, Option } from "./prepare";
import type { Kind } from "./switches";
import { THEMES, type ThemeName } from "./themes";
import { isCleanTitle, sanitizeTitle } from "./title";

export const FONT_SIZES = { s: 12, m: 14, l: 16 } as const;
export type FontSize = keyof typeof FONT_SIZES;
export const FONT_LABEL: Record<FontSize, string> = { s: "小", m: "中", l: "大" };
export const PIE_TOP_N = 9; // 合并为'其他'：保留前 9 个 + 1 个'其他' = 10 色正好不循环
export const OTHER_NAME = "其他";

export type Edit = {
  yMin: number | null;
  yMax: number | null;
  colors: Record<number, number>; // 系列（饼图是扇区）index → 当前主题调色板 index
  font: FontSize;
  other: boolean;
  colorBy: "series" | "data"; // V2b B2：按类目着色（只对单系列柱图生效）
  title: string | null; // V2b B3：用户标题（已过 sanitizeTitle）；null = 用后端标题
};
export const EMPTY_EDIT: Edit = { yMin: null, yMax: null, colors: {}, font: "m", other: false, colorBy: "series", title: null };
/** 一张图自己设过的字段（V2b B4）：没出现的字段跟图型默认走。 */
export type EditPatch = Partial<Edit>;
/** 「应用到所有{图型}」带走的字段；yMin / yMax 跟数据量级绑定、title 是每张图自己的，不迁移。 */
export const TRANSFER_FIELDS = ["colors", "colorBy", "font", "other"] as const;
export type KindEdit = Pick<EditPatch, (typeof TRANSFER_FIELDS)[number]>;

export const LAYER1_KEYS = {
  "yAxis.min": "number",
  "yAxis.max": "number",
  "series[].itemStyle.color": "palette",
  "series[].data[].itemStyle.color": "palette",
  "textStyle.fontSize": [12, 16],
  "series[].data": "merge-other",
  "title.subtext": "merge-note",
  "series[].colorBy": ["data"], // V2b B2
  "series[].data[].value": "wrap", // V2b B2：按类目着色时数值点就地包成 {value}（值不变）
  "title.text": "sanitized-title", // V2b B3：用户标题，已过 sanitizeTitle
} as const;

const fin = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** y 轴范围是否生效：都是有限数（或空），同时填时 min < max。 */
export function rangeError(e: Pick<Edit, "yMin" | "yMax">): string | null {
  if (e.yMin !== null && !fin(e.yMin)) return "最小值不是数字";
  if (e.yMax !== null && !fin(e.yMax)) return "最大值不是数字";
  if (e.yMin !== null && e.yMax !== null && !(e.yMin < e.yMax)) return "最小值要小于最大值";
  return null;
}

export function hasAxis(kind: Kind | null): boolean {
  return !!kind && kind !== "pie";
}

/** 逐字段校验（V2b B4 起只留下出现过且合法的字段，没出现 = 跟图型默认）：不合法的字段丢掉，别的字段照常。
 *  title 单独一条（B3）：必须是 string、≤ 100 码点、且 sanitizeTitle(v) === v，否则只丢 title。 */
export function parseEdit(raw: unknown): EditPatch {
  const out: EditPatch = {};
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) return out;
  const r = raw as Record<string, unknown>;
  if ("yMin" in r && (r.yMin === null || fin(r.yMin))) out.yMin = r.yMin as number | null;
  if ("yMax" in r && (r.yMax === null || fin(r.yMax))) out.yMax = r.yMax as number | null;
  if (rangeError({ yMin: out.yMin ?? null, yMax: out.yMax ?? null })) { delete out.yMin; delete out.yMax; }
  if (r.font === "s" || r.font === "m" || r.font === "l") out.font = r.font;
  if (typeof r.other === "boolean") out.other = r.other;
  if (r.colorBy === "series" || r.colorBy === "data") out.colorBy = r.colorBy;
  if (r.title === null || isCleanTitle(r.title)) out.title = r.title as string | null;
  if (r.colors !== null && typeof r.colors === "object" && !Array.isArray(r.colors)) {
    const colors: Record<number, number> = {};
    for (const [k, v] of Object.entries(r.colors as Record<string, unknown>)) {
      const i = Number(k);
      if (Number.isInteger(i) && i >= 0 && i < 100 && Number.isInteger(v) && (v as number) >= 0 && (v as number) < 10) colors[i] = v as number;
    }
    out.colors = colors;
  }
  return out;
}

/** 图型默认只收可迁移字段。 */
export function parseKindEdit(raw: unknown): KindEdit {
  const p = parseEdit(raw);
  const out: KindEdit = {};
  for (const f of TRANSFER_FIELDS) if (p[f] !== undefined) (out as Record<string, unknown>)[f] = p[f];
  return out;
}

/** 生效的层 1：EMPTY_EDIT ← 图型默认 ← 这张图自己设过的字段。 */
export function resolveEdit(kindDefault: KindEdit, own: EditPatch): Edit {
  return { ...EMPTY_EDIT, ...kindDefault, ...own, colors: { ...(own.colors ?? kindDefault.colors ?? {}) } };
}

/** 用户在输入框里填的标题 → 存储值（清洗；空 = null）。 */
export function titleOf(input: string): string | null {
  const t = sanitizeTitle(input);
  return t === "" ? null : t;
}

export function isEmptyEdit(e: Edit): boolean {
  return e.yMin === null && e.yMax === null && Object.keys(e.colors).length === 0 && e.font === "m" && !e.other
    && e.colorBy === "series" && e.title === null;
}

/** 按类目着色在这个图形状下是否可用（B2：只对单系列柱图开放）。 */
export function colorByAvailable(kind: Kind | null, series: number): boolean {
  return kind === "bar" && series === 1;
}

const isObj = (v: Json | undefined): v is { [k: string]: Json } => v !== null && typeof v === "object" && !Array.isArray(v);
const sub = (o: { [k: string]: Json }, k: string): { [k: string]: Json } => {
  if (!isObj(o[k])) o[k] = {};
  return o[k] as { [k: string]: Json };
};

/** 饼图合并：按值降序保留前 PIE_TOP_N 个，其余求和成一项'其他'。返回合并掉的项数（0 = 没合并）。 */
export function mergeOther(data: Json[]): { data: Json[]; merged: number } {
  if (data.length <= PIE_TOP_N + 1) return { data, merged: 0 };
  const val = (d: Json) => (isObj(d) && fin(d.value) ? d.value : 0);
  const sorted = [...data].sort((a, b) => val(b) - val(a));
  const rest = sorted.slice(PIE_TOP_N);
  const sum = rest.reduce<number>((s, d) => s + val(d), 0);
  return { data: [...sorted.slice(0, PIE_TOP_N), { name: OTHER_NAME, value: sum }], merged: rest.length };
}

export function mergeNote(n: number): string {
  return `已合并 ${n} 项为'${OTHER_NAME}'`;
}

/** 层 1 改动写进 option（就地改，调用方已深拷贝）。kind 是换图型之后的图型。 */
export function applyLayer1To(option: Option, kind: Kind | null, theme: ThemeName, edit: Edit | undefined): Option {
  if (!edit || isEmptyEdit(edit)) return option;
  const palette = THEMES[theme].theme.color;
  const series = Array.isArray(option.series) ? option.series.filter(isObj) : [];
  if (hasAxis(kind) && !rangeError(edit) && isObj(option.yAxis)) {
    if (edit.yMin !== null) option.yAxis.min = edit.yMin;
    if (edit.yMax !== null) option.yAxis.max = edit.yMax;
  }
  if (kind === "pie" && series[0] && Array.isArray(series[0].data)) {
    if (edit.other) {
      const m = mergeOther(series[0].data);
      if (m.merged) {
        series[0].data = m.data;
        sub(option, "title").subtext = mergeNote(m.merged);
      }
    }
    const data = series[0].data as Json[];
    for (const [i, c] of Object.entries(edit.colors)) {
      const d = data[Number(i)];
      if (isObj(d) && palette[c]) sub(d, "itemStyle").color = palette[c];
    }
  } else if (edit.colorBy === "data" && colorByAvailable(kind, series.length) && Array.isArray(series[0].data)) {
    // B2 按类目着色：每根柱子一色；用户改的颜色按类目 index 写到数值点上（数值点就地包成 {value}，值不变）
    const s0 = series[0];
    s0.colorBy = "data";
    const data = s0.data as Json[];
    for (const [i, c] of Object.entries(edit.colors)) {
      const k = Number(i);
      if (k >= data.length || !palette[c]) continue;
      const d = data[k];
      const item: { [k: string]: Json } = isObj(d) ? d : { value: d };
      sub(item, "itemStyle").color = palette[c];
      data[k] = item;
    }
  } else if (edit.colorBy !== "data") { // 按类目存的颜色（index 是类目）在不能按类目着色的图上不套到系列上
    for (const [i, c] of Object.entries(edit.colors)) {
      const s = series[Number(i)];
      if (s && palette[c]) sub(s, "itemStyle").color = palette[c];
    }
  }
  if (edit.font !== "m") sub(option, "textStyle").fontSize = FONT_SIZES[edit.font];
  // B3：用户标题只写 title.text 一处，写之前再过一遍 sanitizeTitle（存储已校验，这里是第二道）
  if (edit.title !== null) {
    const t = sanitizeTitle(edit.title);
    if (t) sub(option, "title").text = t;
  }
  return option;
}

// ---- 存储：每张图一个键（只存这张图自己设过的字段）；图型默认一个图型一个键
export const EDIT_PREFIX = "datachat.chartEdit:";
export const KIND_EDIT_PREFIX = "datachat.chartEditKind:";
const EMPTY_PATCH: EditPatch = {};
const cache = new Map<string, EditPatch>();
const kindCache = new Map<Kind, KindEdit>();
const listeners = new Set<() => void>();
const notify = () => { for (const l of listeners) l(); };

function readJson<T>(key: string, parse: (raw: unknown) => T, empty: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? empty : parse(JSON.parse(raw));
  } catch {
    return empty;
  }
}
function writeJson(key: string, v: object): void {
  try {
    if (Object.keys(v).length === 0) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(v));
  } catch {
    /* 存不了就只在本页生效 */
  }
}

/** 这张图自己设过的字段（同一个键返回同一个对象：useSyncExternalStore 要求快照稳定）。 */
export function getEdit(key: string | undefined): EditPatch {
  if (!key) return EMPTY_PATCH;
  let v = cache.get(key);
  if (!v) cache.set(key, (v = readJson(EDIT_PREFIX + key, parseEdit, EMPTY_PATCH)));
  return v;
}
export function setEdit(key: string | undefined, e: EditPatch): void {
  if (!key) return;
  const v = parseEdit(e);
  cache.set(key, v);
  writeJson(EDIT_PREFIX + key, v);
  notify();
}

/** 图型默认（B4）。 */
export function getKindEdit(kind: Kind): KindEdit {
  let v = kindCache.get(kind);
  if (!v) kindCache.set(kind, (v = readJson(KIND_EDIT_PREFIX + kind, parseKindEdit, EMPTY_PATCH as KindEdit)));
  return v;
}
/** 「应用到所有{图型}」：把这张图生效的可迁移字段存成图型默认。 */
export function applyToKind(kind: Kind, edit: Edit): void {
  const v = parseKindEdit(Object.fromEntries(TRANSFER_FIELDS.map((f) => [f, edit[f]])));
  kindCache.set(kind, v);
  writeJson(KIND_EDIT_PREFIX + kind, v);
  notify();
}
/** 「清除{图型}默认」。 */
export function clearKindEdit(kind: Kind): void {
  kindCache.set(kind, EMPTY_PATCH as KindEdit);
  writeJson(KIND_EDIT_PREFIX + kind, {});
  notify();
}
export function subscribeEdits(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}
export function resetEditsForTest(): void {
  cache.clear();
  kindCache.clear();
}
