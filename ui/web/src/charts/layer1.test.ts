// F4 层 1：applyLayer1 逐图型、存储逐字段校验、颜色 index 跟主题走、合并'其他'、机制测试（写出的键 ⊆ LAYER1_KEYS）。
import fixtures from "../generated/chart_fixtures.json";
import { type ChartInput, DEFAULT_UI, type Json, prepare, type UiState } from "./prepare";
import {
  EDIT_PREFIX, type Edit, EMPTY_EDIT, getEdit, LAYER1_KEYS, mergeNote, mergeOther, OTHER_NAME, parseEdit, PIE_TOP_N, rangeError,
  resetEditsForTest, setEdit,
} from "./layer1";
import { DEFAULT_SWITCHES, KINDS } from "./switches";
import { THEME_NAMES, THEMES } from "./themes";

type F = { id: string; spec: ChartInput };
const FX = (fixtures as unknown as { fixtures: F[] }).fixtures;
const fx = (id: string) => FX.find((f) => f.id === id)!.spec;
const BY_KIND = Object.fromEntries(KINDS.map((k) => [k, FX.find((f) => f.spec.kind === k)!.spec]));
type O = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const ui = (edit: Partial<Edit>): UiState => ({ ...DEFAULT_UI, edit: { ...EMPTY_EDIT, colors: {}, ...edit } });
const run = (spec: ChartInput, edit: Partial<Edit>, theme = "classic" as const) => prepare(spec, ui(edit), theme) as O;

describe("轴范围（仅用户）", () => {
  test.each(["bar", "line", "area", "scatter"] as const)("%s：min / max 写进 yAxis", (k) => {
    const o = run(BY_KIND[k], { yMin: 5, yMax: 50 });
    expect([o.yAxis.min, o.yAxis.max]).toEqual([5, 50]);
  });
  test("饼图：没有 y 轴，不写", () => {
    expect(run(BY_KIND.pie, { yMin: 5 }).yAxis).toBeUndefined();
  });
  test("不合法：min ≥ max 不生效", () => {
    expect(rangeError({ yMin: 5, yMax: 5 })).toBe("最小值要小于最大值");
    const o = run(BY_KIND.bar, { yMin: 9, yMax: 1 });
    expect(o.yAxis.min).toBeUndefined();
    expect(rangeError({ yMin: NaN, yMax: null })).not.toBeNull();
  });
});

describe("系列色：存调色板 index，换主题跟着走", () => {
  test.each(THEME_NAMES)("%s：bar 系列 0 取主题第 3 色", (t) => {
    const o = prepare(BY_KIND.bar, ui({ colors: { 0: 2 } }), t) as O;
    expect(o.series[0].itemStyle.color).toBe(THEMES[t].theme.color[2]);
  });
  test("饼图：按扇区 index 写 data[i].itemStyle.color", () => {
    const o = run(BY_KIND.pie, { colors: { 1: 7 } });
    expect(o.series[0].data[1].itemStyle.color).toBe(THEMES.classic.theme.color[7]);
    expect(o.series[0].data[0].itemStyle).toBeUndefined();
  });
  test("渐变开着：以用户选的色为底", () => {
    const o = prepare(BY_KIND.bar, { kind: null, sw: { ...DEFAULT_SWITCHES, gradient: true }, edit: { ...EMPTY_EDIT, colors: { 0: 4 } } }, "classic") as O;
    expect(JSON.stringify(o.series[0].itemStyle.color)).toContain(THEMES.classic.theme.color[4]);
  });
});

test("字号：中档不写键，小 / 大写 12 / 16", () => {
  expect(run(BY_KIND.bar, { font: "m" }).textStyle).toBeUndefined();
  expect(run(BY_KIND.bar, { font: "s" }).textStyle.fontSize).toBe(12);
  expect(run(BY_KIND.line, { font: "l" }).textStyle.fontSize).toBe(16);
});

describe("饼图合并为'其他'", () => {
  const data = Array.from({ length: 13 }, (_, i) => ({ name: `c${i}`, value: i + 1 }));
  test("前 9 个 + '其他'，总和不变，降序", () => {
    const m = mergeOther(data);
    expect(m.merged).toBe(4);
    expect(m.data).toHaveLength(PIE_TOP_N + 1);
    const vals = (m.data as { value: number }[]).map((d) => d.value);
    expect(vals.reduce((a, b) => a + b)).toBe(data.reduce((a, d) => a + d.value, 0));
    expect((m.data[9] as { name: string }).name).toBe(OTHER_NAME);
    expect(vals.slice(0, 9)).toEqual([13, 12, 11, 10, 9, 8, 7, 6, 5]);
  });
  test("≤ 10 项不合并", () => expect(mergeOther(data.slice(0, 10)).merged).toBe(0));
  test("pie-50 夹具：开关打开后 10 项 + 标注；关着原样", () => {
    const o = run(fx("pie-50"), { other: true });
    expect(o.series[0].data).toHaveLength(10);
    expect(o.title.subtext).toBe(mergeNote(41));
    expect(run(fx("pie-50"), {}).series[0].data).toHaveLength(50);
  });
});

test("空改动 = 不改动（与 DEFAULT_UI 产物逐字节相同）", () => {
  for (const f of FX) expect(JSON.stringify(run(f.spec, {}))).toBe(JSON.stringify(prepare(f.spec)));
});

// 机制测试：层 1 改动相对无改动产物的差，路径全部登记在 LAYER1_KEYS；值只有数字或当前主题色（加'其他'合并的字面量）
function diffPaths(a: Json, b: Json, path: string, out: Set<string>) {
  if (JSON.stringify(a) === JSON.stringify(b)) return;
  if (Array.isArray(a) && Array.isArray(b) && a.length === b.length) {
    a.forEach((x, i) => diffPaths(x, b[i], `${path}[]`, out));
    return;
  }
  if (a && b && typeof a === "object" && typeof b === "object" && !Array.isArray(a) && !Array.isArray(b)) {
    for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) diffPaths((a as O)[k], (b as O)[k], path ? `${path}.${k}` : k, out);
    return;
  }
  out.add(path);
}
test("机制：全部夹具 × 全部改动，差 ⊆ LAYER1_KEYS", () => {
  const hits = new Set<string>();
  const full: Partial<Edit> = { yMin: 1, yMax: 99, colors: { 0: 3, 1: 5 }, font: "l", other: true };
  for (const f of FX) {
    const base = prepare(f.spec) as Json;
    const got = run(f.spec, full) as Json;
    const d = new Set<string>();
    diffPaths(base, got, "", d);
    for (const p of d) {
      const norm = p.replace(/\.itemStyle$/, ".itemStyle.color").replace(/^title$/, "title.subtext").replace(/^textStyle$/, "textStyle.fontSize");
      expect(Object.keys(LAYER1_KEYS)).toContain(norm);
      hits.add(norm);
    }
  }
  expect([...hits].sort()).toEqual(Object.keys(LAYER1_KEYS).sort()); // 表里没有死条目
});

describe("存储", () => {
  beforeEach(() => { localStorage.clear(); resetEditsForTest(); });
  test("逐字段校验：坏字段丢掉、好字段留下", () => {
    const e = parseEdit({ yMin: "1", yMax: 10, colors: { 0: 2, 1: 99, x: 1 }, font: "xl", other: 1, junk: true });
    expect(e).toEqual({ ...EMPTY_EDIT, yMax: 10, colors: { 0: 2 } });
    expect(parseEdit({ yMin: 5, yMax: 1 })).toEqual(EMPTY_EDIT);
    expect(parseEdit("x")).toEqual(EMPTY_EDIT);
  });
  test("写入 / 读回 / 重置删键", () => {
    setEdit("m1:0", { ...EMPTY_EDIT, font: "l" });
    expect(localStorage.getItem(EDIT_PREFIX + "m1:0")).toContain('"font":"l"');
    resetEditsForTest();
    expect(getEdit("m1:0").font).toBe("l");
    setEdit("m1:0", EMPTY_EDIT);
    expect(localStorage.getItem(EDIT_PREFIX + "m1:0")).toBeNull();
  });
  test("坏 JSON 回退空改动", () => {
    localStorage.setItem(EDIT_PREFIX + "m2:0", "{");
    expect(getEdit("m2:0")).toEqual(EMPTY_EDIT);
  });
});
