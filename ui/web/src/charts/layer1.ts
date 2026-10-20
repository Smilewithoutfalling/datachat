// F4 层 1 面板（docs/roadmap/phase5-frontend.md「F4：层 1 面板」）：用户对单张图的样式改动。
// - 只改 M13 §3.2 层 1 的样式键：yAxis.min / max（仅用户）、series[i].itemStyle.color（饼图是 data[i].itemStyle.color）、
//   textStyle.fontSize；再加饼图「合并为'其他'」（仅用户，默认关）。visualMap.pieces 不做（方案第 5 条）。
// - 输入只有三类：有限数、调色板 index、枚举。没有任何用户字符串进 option（"其他"、合并提示是前端字面量）。
//   写出的键和值集合登记在 LAYER1_KEYS，layer1.test.ts 做机制测试。它和 switches.ts 的 FRONTEND_KEYS 分开：
//   FRONTEND_KEYS 和 M13 §12 的开关表逐字比对，层 1 不在那张表里（偏离方案第 8 条"加进 FRONTEND_KEYS"，DEVLOG [44]）。
// - 颜色存调色板 index 不存 hex：换主题后跟着主题走，对比度检查照旧成立。
// - 存储：localStorage 的 datachat.chartEdit:<message_id>:<图序号>，读写 try/catch，逐字段校验，坏字段丢掉。
import type { Json, Option } from "./prepare";
import type { Kind } from "./switches";
import { THEMES, type ThemeName } from "./themes";

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
};
export const EMPTY_EDIT: Edit = { yMin: null, yMax: null, colors: {}, font: "m", other: false };

export const LAYER1_KEYS = {
  "yAxis.min": "number",
  "yAxis.max": "number",
  "series[].itemStyle.color": "palette",
  "series[].data[].itemStyle.color": "palette",
  "textStyle.fontSize": [12, 16],
  "series[].data": "merge-other",
  "title.subtext": "merge-note",
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

/** 逐字段校验：不合法的字段回到默认。 */
export function parseEdit(raw: unknown): Edit {
  const out: Edit = { ...EMPTY_EDIT, colors: {} };
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) return out;
  const r = raw as Record<string, unknown>;
  if (r.yMin === null || fin(r.yMin)) out.yMin = (r.yMin as number | null) ?? null;
  if (r.yMax === null || fin(r.yMax)) out.yMax = (r.yMax as number | null) ?? null;
  if (rangeError(out)) { out.yMin = null; out.yMax = null; }
  if (r.font === "s" || r.font === "m" || r.font === "l") out.font = r.font;
  if (r.other === true) out.other = true;
  if (r.colors !== null && typeof r.colors === "object" && !Array.isArray(r.colors)) {
    for (const [k, v] of Object.entries(r.colors as Record<string, unknown>)) {
      const i = Number(k);
      if (Number.isInteger(i) && i >= 0 && i < 100 && Number.isInteger(v) && (v as number) >= 0 && (v as number) < 10) out.colors[i] = v as number;
    }
  }
  return out;
}

export function isEmptyEdit(e: Edit): boolean {
  return e.yMin === null && e.yMax === null && Object.keys(e.colors).length === 0 && e.font === "m" && !e.other;
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
  } else {
    for (const [i, c] of Object.entries(edit.colors)) {
      const s = series[Number(i)];
      if (s && palette[c]) sub(s, "itemStyle").color = palette[c];
    }
  }
  if (edit.font !== "m") sub(option, "textStyle").fontSize = FONT_SIZES[edit.font];
  return option;
}

// ---- 存储：每张图一个键
export const EDIT_PREFIX = "datachat.chartEdit:";
const cache = new Map<string, Edit>();
const listeners = new Set<() => void>();

export function getEdit(key: string | undefined): Edit {
  if (!key) return EMPTY_EDIT;
  let v = cache.get(key);
  if (!v) {
    try {
      const raw = localStorage.getItem(EDIT_PREFIX + key);
      v = raw === null ? EMPTY_EDIT : parseEdit(JSON.parse(raw));
    } catch {
      v = EMPTY_EDIT;
    }
    cache.set(key, v);
  }
  return v;
}
export function setEdit(key: string | undefined, e: Edit): void {
  if (!key) return;
  const v = parseEdit(e);
  cache.set(key, v);
  try {
    if (isEmptyEdit(v)) localStorage.removeItem(EDIT_PREFIX + key);
    else localStorage.setItem(EDIT_PREFIX + key, JSON.stringify(v));
  } catch {
    /* 存不了就只在本页生效 */
  }
  for (const l of listeners) l();
}
export function subscribeEdits(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}
export function resetEditsForTest(): void {
  cache.clear();
}
