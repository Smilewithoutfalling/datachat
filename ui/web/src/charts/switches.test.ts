// F3 第五步验收（docs/roadmap/phase5-frontend.md「F3 第五步」）：COMPAT 45 格生效、例外层机制、换图型契约、渐变、排序、
// 偏好存取、历史 spec 归一。夹具全部来自后端 build_option 的真产出（chart_fixtures.json / kind_fixtures.json），不手写 option；
// 唯一手写的是"第三步形状"的历史 spec（库里的老数据，现在的 builder 已经出不来）。
import { init, use as installEcharts } from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
// M13 §12 的表原文（vite ?raw）：switches.test.ts 读它比对 FRONTEND_KEYS
import m13 from "../../../../docs/roadmap/M13-图表方案.md?raw";
import fixtures from "../generated/chart_fixtures.json";
import kindFixtures from "../generated/kind_fixtures.json";
import schema from "../generated/chart_schema.json";
import { type ChartInput, DEFAULT_UI, type Json, normalize, type Option, prepare, type Ctx, type UiState } from "./prepare";
import { FRONTEND_REG, productExtensions } from "./register";
import {
  applyViewTo, asZoom, canChangeKind, changeKind, COMPAT, DATA_ZOOM, DEFAULT_SWITCHES, hiddenFromSelected, FRONTEND_KEYS, viewFromRendered, gradient, KIND_DIFF, KINDS, type Kind, legendItems, rgba0,
  SWITCHES, SWITCH_VALUES, type SwitchName, type Switches, type View,
 DEFAULT_STORED, DESIGN_LABEL, designLabel, resolveSwitches } from "./switches";
import { THEME_NAMES, THEMES, type ThemeName } from "./themes";
import { getPrefs, parseSwitches, PREFS_PREFIX, resetPrefsForTest, setPrefs } from "./uiPrefs";

installEcharts([...productExtensions(), SVGRenderer]);

type Spec = ChartInput & { v: number; truncated: boolean; x_kind: string };
const FIX = fixtures.fixtures as unknown as { id: string; spec: Spec }[];
const GROUPS = kindFixtures.groups as unknown as Record<string, Partial<Record<Kind, Spec>>>;
const fx = (id: string) => FIX.find((f) => f.id === id)!.spec;
const kf = (g: string, k: Kind) => GROUPS[g][k]!;
const ui = (patch: Partial<Switches> = {}, kind: Kind | null = null, view?: View): UiState => ({ kind, sw: { ...DEFAULT_SWITCHES, ...patch }, view });
/** 第一个非默认值 = "开"（legend → top，sort → desc） */
const ON = Object.fromEntries(SWITCHES.map((s) => [s, SWITCH_VALUES[s][1]])) as Switches;
// 递归排序键再 stringify（S 10-19 第四条）：开关全关时对象可能被重建，键序变了不算行为变化；顺带能发现重复键
const canon = (v: unknown): string => JSON.stringify(sortKeys(v));
function sortKeys(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(sortKeys);
  if (v && typeof v === "object") return Object.fromEntries(Object.keys(v).sort().map((k) => [k, sortKeys((v as Record<string, unknown>)[k])]));
  return v;
}
type O = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

// ---- COMPAT 45 格：每格测"生效"，不只测置灰（S 10-19 结构点③）--------------------------------------------------
// 每格的夹具：满足条件的一份测"开了键在、值对 / 关了键不在"，不满足的测"开关产物与关闭时相同"。
const LEGACY_BAR: Spec = (() => { const s = JSON.parse(JSON.stringify(fx("bar"))); delete s.x_kind; return s; })();
const POOL: Record<Kind, { single: Spec; multi?: Spec; time?: Spec }> = {
  bar: { single: fx("bar"), multi: fx("inject-bar"), time: kf("time", "bar") },
  line: { single: fx("line"), multi: fx("line-wide"), time: fx("line-time") },
  area: { single: fx("area"), multi: kf("wide", "area"), time: fx("area-time") },
  pie: { single: fx("pie") },
  scatter: { single: fx("scatter"), multi: fx("scatter-multi") },
};
/** 开关在产物上留下的痕迹（"生效"的判据）；关时这些都不该在。 */
const EFFECT: Record<SwitchName, (o: O, base: O) => boolean> = {
  label: (o) => o.series.every((s: O) => s.label?.show === true),
  legend: (o) => o.legend.top === "top",
  stack: (o) => o.series.every((s: O) => s.stack === "total"),
  smooth: (o) => o.series.every((s: O) => s.smooth === true),
  gradient: (o) => o.series.every((s: O) => (s.areaStyle?.color ?? s.itemStyle?.color)?.type === "linear"),
  radius: (o) => o.series.some((s: O) => canon(s.itemStyle?.borderRadius) === canon([4, 4, 0, 0])),
  sort: (o, base) => canon(o.series[0].data) !== canon(base.series[0].data),
  marks: (o) => o.series.every((s: O) => s.markLine && s.markPoint),
  zoom: (o) => Array.isArray(o.dataZoom),
};
type Cell = [SwitchName, Kind, string, Spec, boolean]; // 开关、图型、夹具说明、夹具、应不应生效
const CELLS: Cell[] = [];
for (const s of SWITCHES) for (const k of KINDS) {
  const p = POOL[k];
  const cond = COMPAT[s][k];
  if (cond === "yes") CELLS.push([s, k, "单系列", p.single, true]);
  if (cond === "no") { CELLS.push([s, k, "单系列", p.single, false]); if (p.multi) CELLS.push([s, k, "多系列", p.multi, false]); }
  if (cond === "multi") { CELLS.push([s, k, "多系列", p.multi!, true], [s, k, "单系列", p.single, false]); }
  if (cond === "single-nontime") {
    CELLS.push([s, k, "单系列类目", p.single, true], [s, k, "多系列", p.multi!, false], [s, k, "时间轴", p.time!, false]);
    // 历史 spec 没有 x_kind：降级规则只有"不可换饼图"一条，排序照常（S 10-19 第五条）
    CELLS.push([s, k, "旧图无 x_kind", LEGACY_BAR, true]);
  }
}

describe("COMPAT 45 格：开关 × 图型都测生效", () => {
  test("45 格一格不少（每格至少一个用例）", () => {
    expect(new Set(CELLS.map(([s, k]) => `${s}×${k}`)).size).toBe(45);
    expect(SWITCHES.length * KINDS.length).toBe(45);
  });
  test.each(CELLS.map((c) => [`${c[0]}×${c[1]}（${c[2]}）`, ...c] as const))("%s", (_n, s, _k, _d, spec, live) => {
    const off = prepare(spec) as O;
    const on = prepare(spec, ui({ [s]: ON[s] })) as O;
    if (live) {
      expect(EFFECT[s](on, off)).toBe(true);
      expect(EFFECT[s](off, off)).toBe(false);
    } else {
      expect(canon(on)).toBe(canon(off));
    }
  });
});

// ---- 例外层机制：prepare 产物相对"builder 等价产物"的差 ⊆ FRONTEND_KEYS，值在值集合里（S 10-19 结构点①）-------------
// 基线 = 同一图型、开关全关（normalize → changeKind → cleanup）。changeKind 已由下面的契约测试钉成等于 builder 的产物，
// 所以基线在后端白名单内；差出来的部分就是白名单外的例外层，必须全部登记在 FRONTEND_KEYS。
const pattern = (path: (string | number)[]) => path.map((p) => (typeof p === "number" ? "[]" : p)).join(".").replace(/\.\[\]/g, "[]");
function diff(out: Json | undefined, base: Json | undefined, path: (string | number)[], theme: ThemeName, hits: Set<string>, bad: string[], root?: Json) {
  root ??= out; // legendItems 的判据要用整份产物（图例项名取自 option 自己）
  const pat = pattern(path);
  const set = FRONTEND_KEYS[pat];
  if (set && canon(out) !== canon(base)) {
    hits.add(pat);
    if ("lit" in set) {
      // 子键另有登记（F3 第六步的 dataZoom[].start / end）：先摘出来按各自的值集合判，剩下的再比字面量
      let rest = out;
      const kids = Object.keys(FRONTEND_KEYS).filter((k) => k.startsWith(`${pat}[].`)).map((k) => k.slice(pat.length + 3));
      if (kids.length && Array.isArray(out)) {
        rest = JSON.parse(JSON.stringify(out)) as Json;
        (rest as Json[]).forEach((el, i) => {
          if (el === null || typeof el !== "object" || Array.isArray(el)) return;
          for (const k of kids) if (k in el) { diff(el[k], undefined, [...path, i, k], theme, hits, bad, root); delete el[k]; }
        });
      }
      if (!set.lit.some((v) => canon(v) === canon(rest))) bad.push(`${pat} 值不在集合里：${JSON.stringify(out)}`);
    }
    else if ("range" in set) {
      if (typeof out !== "number" || !Number.isFinite(out) || out < set.range[0] || out > set.range[1]) bad.push(`${pat} 越界：${JSON.stringify(out)}`);
    }
    else if ("legendItems" in set) {
      const names = new Set(legendItems(root as Option).filter((n) => typeof n === "string"));
      const ok = out !== null && typeof out === "object" && !Array.isArray(out) &&
        Object.entries(out).every(([k, v]) => names.has(k) && typeof v === "boolean");
      if (!ok) bad.push(`${pat} 键不是图例项或值不是布尔：${JSON.stringify(out)}`);
    }
    else if ("gradient" in set) { if (!THEMES[theme].theme.color.some((c) => canon(gradient(c)) === canon(out))) bad.push(`${pat} 不是 ${theme} 的渐变`); }
    else {
      const sorted = (a: Json | undefined) => (Array.isArray(a) ? a.map((x) => JSON.stringify(x)).sort() : []);
      if (canon(sorted(out)) !== canon(sorted(base))) bad.push(`${pat} 不是原数组的排列`);
    }
    return;
  }
  if (Array.isArray(out) && Array.isArray(base) && out.length === base.length) { out.forEach((v, i) => diff(v, base[i], [...path, i], theme, hits, bad, root)); return; }
  const isO = (v: Json | undefined) => v !== null && typeof v === "object" && !Array.isArray(v);
  if (isO(out) && (isO(base) || base === undefined)) {
    const b = (base ?? {}) as Record<string, Json>;
    const o = out as Record<string, Json>;
    for (const k of new Set([...Object.keys(o), ...Object.keys(b)])) diff(o[k], b[k], [...path, k], theme, hits, bad, root);
    return;
  }
  if (canon(out) !== canon(base)) bad.push(`${pat || "(根)"} 未登记：${JSON.stringify(base)?.slice(0, 60)} → ${JSON.stringify(out)?.slice(0, 60)}`);
}
const ALL_SPECS: [string, Spec][] = [
  ...FIX.map((f) => [f.id, f.spec] as [string, Spec]),
  ...Object.entries(GROUPS).flatMap(([g, m]) => Object.entries(m).map(([k, s]) => [`k:${g}:${k}`, s!] as [string, Spec])),
];
// F3 第六步：交互态也走这张表。V1 正常；V2 带越界 / 负数 / 重复 index 和全量区间（应当什么都不写）
const V1: View = { zoom: { start: 10, end: 60 }, hidden: [0] };
const V2: View = { zoom: { start: 0, end: 100 }, hidden: [1, 1, 999, -1] };
const COMBOS: [string, Partial<Switches>, View?][] = [
  ...SWITCHES.map((s) => [s, { [s]: ON[s] }] as [string, Partial<Switches>]), ["全开", ON], ["全开·升序", { ...ON, sort: "asc" }],
  ["全开+view", ON, V1], ["全开+越界 view", ON, V2], ["全关+view", {}, V1],
];

describe("例外层：开关只写 FRONTEND_KEYS 登记的路径和值", () => {
  const hits = new Set<string>();
  test.each(THEME_NAMES)("主题 %s × 全部夹具 × 目标图型 × 开关组合", (theme) => {
    const bad: string[] = [];
    for (const [id, spec] of ALL_SPECS) {
      for (const target of [null, ...KINDS]) {
        const u0 = ui({}, target);
        const base = prepare(spec, u0, theme) as Json;
        for (const [name, patch, view] of COMBOS) {
          const before = bad.length;
          diff(prepare(spec, ui(patch, target, view), theme) as Json, base, [], theme, hits, bad);
          if (bad.length > before) bad.push(`↑ ${id} → ${target ?? "原图型"} / ${name}`);
        }
      }
    }
    expect(bad.slice(0, 20)).toEqual([]);
  }, 60_000); // 穷举：本地每轮约 3.2 s，CI 上 classic 轮 5.4 s 超过默认 5 s（tests run 39205703625）
  test("对照：表外路径、表内路径的表外值、非排列的 data，都会被抓到", () => {
    const base = prepare(fx("bar"), ui(), "classic") as O;
    const cases: [string, (o: O) => void][] = [
      ["表外路径", (o) => { o.legend.left = "right"; }],
      ["表外值", (o) => { o.series[0].stack = "x"; }],
      ["非排列", (o) => { o.series[0].data[0] = 999; }],
      ["别的主题的渐变", (o) => { o.series[0].itemStyle = { color: gradient(THEMES.soft.theme.color[0]) }; }],
      ["用户串进标签", (o) => { o.series[0].label = { show: true, position: o.xAxis.data[0] }; }],
      ["缩放越界", (o) => { o.dataZoom = [{ ...(DATA_ZOOM as O[])[0], start: -5, end: 60 }]; }],
      ["图例键不是图例项", (o) => { o.legend.selected = { 不存在的系列: false }; }],
      ["图例值不是布尔", (o) => { o.legend.selected = { [o.series[0].name]: "false" }; }],
    ];
    for (const [name, mutate] of cases) {
      const out = JSON.parse(JSON.stringify(base)) as O;
      mutate(out);
      const bad: string[] = [];
      diff(out as Json, base as Json, [], "classic", new Set(), bad);
      expect([name, bad.length > 0]).toEqual([name, true]);
    }
  });
  test("对照的反面：合法的缩放窗口和图例显隐不误报", () => {
    const base = prepare(fx("inject-bar"), ui(), "classic") as O;
    const out = JSON.parse(JSON.stringify(base)) as O;
    out.dataZoom = [{ ...(DATA_ZOOM as O[])[0], start: 10, end: 60 }];
    out.legend.selected = { [out.series[1].name]: false };
    const bad: string[] = [];
    diff(out as Json, base as Json, [], "classic", new Set(), bad);
    expect(bad).toEqual([]);
  });
  test("FRONTEND_KEYS 的每条路径都被开关真正写到过（表里没有死条目）", () => {
    expect([...hits].sort()).toEqual(Object.keys(FRONTEND_KEYS).sort());
  });
  test("FRONTEND_KEYS = register 的 FRONTEND_REG（双向）", () => {
    expect(Object.keys(FRONTEND_REG).sort()).toEqual(Object.keys(FRONTEND_KEYS).sort());
  });
  test("FRONTEND_KEYS 的值集合里没有字符串型用户数据：字面量只有固定词，渐变只取主题色", () => {
    const strs = Object.values(FRONTEND_KEYS).flatMap((v) => ("lit" in v ? JSON.stringify(v.lit).match(/"[^"]*"/g) ?? [] : []));
    expect(new Set(strs)).toEqual(new Set(['"top"', '"inside"', '"outside"', '"total"', '"type"', '"average"', '"max"', '"min"',
      '"inside"', '"zoomOnMouseWheel"', '"shift"', '"moveOnMouseWheel"', '"moveOnMouseMove"']));
  });
  test("M13 §12 的「前端实际写出」列 = FRONTEND_KEYS（两条实现约定之二）", () => {
    const sec = (m13 as string).slice((m13 as string).indexOf("## 12."));
    const rows = sec.split("\n").filter((l) => l.startsWith("|"));
    const col = rows[0].split("|").map((c) => c.trim()).findIndex((c) => c.startsWith("前端实际写出"));
    expect(col).toBeGreaterThan(0);
    const listed = rows.slice(2).flatMap((r) => (r.split("|")[col] ?? "").match(/`[^`]+`/g) ?? []).map((x) => x.slice(1, -1));
    expect([...new Set(listed)].sort()).toEqual(Object.keys(FRONTEND_KEYS).sort());
  });
});

// ---- 换图型契约：changeKind(A, B) = builder 直接出的 B，只允许 KIND_DIFF ------------------------------------------
const norm = (s: Spec) => normalize(JSON.parse(JSON.stringify(s.option)) as Option, {} as Ctx);
const withDiff = (want: Option, from: Kind) => {
  const w = JSON.parse(JSON.stringify(want)) as O;
  for (const d of KIND_DIFF) if (d.from === from && d.path === "xAxis.name" && w.xAxis) w.xAxis.name = ""; // 饼图自身没有 xAxis
  return w;
};
const PAIRS = Object.entries(GROUPS).flatMap(([g, m]) =>
  (Object.keys(m) as Kind[]).flatMap((a) => (Object.keys(m) as Kind[]).filter((b) => b !== a).map((b) => [g, a, b] as const)))
  // 时间轴不能换成饼图（canChangeKind 置灰，下面"置灰"用例单测原因）；饼图 → 时间轴直角坐标照常测
  .filter(([g, a, b]) => !(g === "time" && b === "pie" && a !== "pie"));

describe("换图型契约（kind_fixtures.json，同一份数据由 build_option 分别出 bar / line / area / pie）", () => {
  test.each(PAIRS)("%s：%s → %s", (g, a, b) => {
    const A = kf(g, a), B = kf(g, b);
    expect(canChangeKind(norm(A), a, b, A.x_kind as never)).toEqual({ ok: true });
    expect(changeKind(norm(A), a, b, A.x_kind as never)).toEqual(withDiff(B.option as Option, a));
  });
  test("差异表外的差异会红：boundaryGap / areaStyle / showSymbol 都必须和 builder 一致（对照）", () => {
    const got = changeKind(norm(kf("single", "bar")), "bar", "area", "category") as O;
    expect(got.xAxis.boundaryGap).toBe(false);
    expect(got.series[0].areaStyle).toEqual({});
    expect(got.series[0].showSymbol).toBe(true);
    expect(changeKind(norm(kf("many", "bar")), "bar", "line", "category").series).toEqual(kf("many", "line").option.series);
    const broken = { ...got, xAxis: { ...got.xAxis, boundaryGap: true } };
    expect(broken).not.toEqual(kf("single", "area").option);
  });
  test("饼图换不了的情形置灰，原因是固定文案", () => {
    const why = (s: Spec, k: Kind = "bar") => canChangeKind(norm(s), k, "pie", (s.x_kind ?? null) as never);
    expect(why(kf("pie-over", "bar"))).toEqual({ ok: false, reason: `类目超过 ${schema.pie_max_slices} 个，不能换成饼图` });
    expect(why(kf("holes", "bar"))).toEqual({ ok: false, reason: "有空值，不能换成饼图" });
    expect(why(kf("negative", "bar"))).toEqual({ ok: false, reason: "有负值，不能换成饼图" });
    expect(why(kf("wide", "bar"))).toEqual({ ok: false, reason: "多系列不能换成饼图" });
    expect(why(kf("time", "line"), "line")).toEqual({ ok: false, reason: "时间轴不能换成饼图" });
    expect(why(LEGACY_BAR)).toEqual({ ok: false, reason: "旧图缺少类型信息，不能换成饼图" });
    expect(canChangeKind(norm(fx("scatter")), "scatter", "bar", "value").ok).toBe(false);
    expect(canChangeKind(norm(fx("bar")), "bar", "scatter", "category").ok).toBe(false);
  });
  test("A → B → A：链式换回来与原始 A 一致（经过饼图时只丢 x 轴名）", () => {
    for (const [g, a, b] of PAIRS) {
      const A = kf(g, a);
      const back = changeKind(changeKind(norm(A), a, b, A.x_kind as never), b, a, A.x_kind as never);
      const want = withDiff(norm(A), b === "pie" && a !== "pie" ? "pie" : a); // 直角坐标经过饼图丢 x 轴名
      expect([g, a, b, back]).toEqual([g, a, b, want]);
    }
  });
  test("产品路径不链式：prepare(A, 目标 B) 之后再选回 A，与从未换过逐字节相同", () => {
    const A = kf("single", "bar");
    prepare(A, ui({}, "pie"));
    expect(canon(prepare(A, ui({}, "bar")))).toBe(canon(prepare(A)));
  });
  test("spec_kind_is_backend_truth：换图型只改 option，spec.kind 保持后端值（两个同名真相有意不一致，别修）", () => {
    const A = JSON.parse(JSON.stringify(kf("single", "bar"))) as Spec;
    const out = prepare(A, ui({}, "pie")) as O;
    expect(out.series.map((s: O) => s.type)).toEqual(["pie"]);
    expect(A.kind).toBe("bar");
    expect(A).toEqual(kf("single", "bar")); // 输入整份没被改
  });
  test("目标图型换不了时留在后端原图型（UI 置灰之外的兜底）", () => {
    const H = kf("holes", "bar");
    expect(canon(prepare(H, ui({}, "pie")))).toBe(canon(prepare(H)));
  });
});

// ---- 渐变、排序、标签位置、圆角 ------------------------------------------------------------------------------
describe("开关细节", () => {
  test("渐变只写 series 层，产物顶层没有 color；换主题后 colorStops 跟着变", () => {
    for (const id of ["bar", "inject-bar"]) {
      const spec = fx(id);
      for (const t of THEME_NAMES) {
        const o = prepare(spec, ui({ gradient: true }), t) as O;
        expect("color" in o).toBe(false);
        o.series.forEach((s: O, i: number) => {
          const c = THEMES[t].theme.color[i % THEMES[t].theme.color.length];
          expect(s.itemStyle.color.colorStops).toEqual([{ offset: 0, color: c }, { offset: 1, color: rgba0(c) }]);
        });
      }
    }
    const area = prepare(fx("area"), ui({ gradient: true }), "darkCanvas") as O;
    expect(area.series[0].areaStyle.color.colorStops[0].color).toBe(THEMES.darkCanvas.theme.color[0]);
    expect(rgba0("#1F6FB2")).toBe("rgba(31, 111, 178, 0)");
    expect(() => rgba0("red")).toThrow();
  });
  test("排序：类目和值一起移动（按 (类目, 值) 对比），null 永远排最后", () => {
    const spec = fx("bar-missing");
    const pairs = (o: O) => o.xAxis.data.map((c: string, i: number) => [c, o.series[0].data[i]]);
    const orig = pairs(prepare(spec) as O);
    const desc = pairs(prepare(spec, ui({ sort: "desc" })) as O);
    const asc = pairs(prepare(spec, ui({ sort: "asc" })) as O);
    expect(desc.map((p: unknown[]) => p[1])).toEqual([4, 2, 1, null]);
    expect(asc.map((p: unknown[]) => p[1])).toEqual([1, 2, 4, null]);
    const key = (ps: unknown[][]) => ps.map((p) => JSON.stringify(p)).sort();
    expect(key(desc)).toEqual(key(orig));
    expect(key(asc)).toEqual(key(orig));
    const pie = prepare(fx("pie"), ui({ sort: "desc" })) as O;
    expect(pie.series[0].data.map((d: O) => d.value)).toEqual([8, 6, 5, 3, 2]);
  });
  test("数值标签：堆叠时 inside、饼图 outside、其余 top；圆角在堆叠时只给最上面的系列", () => {
    expect((prepare(fx("bar"), ui({ label: true })) as O).series[0].label.position).toBe("top");
    expect((prepare(fx("pie"), ui({ label: true })) as O).series[0].label.position).toBe("outside");
    const st = prepare(fx("inject-bar"), ui({ label: true, stack: true, radius: true })) as O;
    expect(st.series.map((s: O) => s.label.position)).toEqual(["inside", "inside"]);
    expect(st.series.map((s: O) => s.itemStyle?.borderRadius ?? null)).toEqual([null, [4, 4, 0, 0]]);
  });
  test("缩放：inside、Shift + 滚轮、普通滚轮不平移、拖动平移", () => {
    expect((prepare(fx("bar"), ui({ zoom: true })) as O).dataZoom).toEqual([
      { type: "inside", zoomOnMouseWheel: "shift", moveOnMouseWheel: false, moveOnMouseMove: true }]);
  });
});

// ---- 4 套主题 × 全部夹具 × 全开：零 [ECharts] log -------------------------------------------------------------
describe.each(THEME_NAMES)("主题 %s × 全部夹具 × 全开", (theme) => {
  test.each(FIX.map((f) => [f.id, f.spec] as const))("%s", (_id, spec) => {
    const spies = (["warn", "error", "log"] as const).map((k) => vi.spyOn(console, k));
    const c = init(null, theme, { renderer: "svg", ssr: true, width: 640, height: 400 });
    try {
      c.setOption(prepare(spec, ui(ON), theme), { notMerge: true });
      c.renderToSVGString();
      expect(spies[0]).not.toHaveBeenCalled();
      expect(spies[1]).not.toHaveBeenCalled();
      expect(spies[2].mock.calls.filter((a) => String(a[0]).startsWith("[ECharts]"))).toEqual([]);
    } finally {
      c.dispose();
      spies.forEach((s) => s.mockRestore());
    }
  });
});

// ---- 历史 spec 归一（PR #48 评审第四条）-------------------------------------------------------------------------
// 手写：第三步 build_option 的形状（outerBoundsContain 'axisLabel'、带 color、没有 nameLocation / nameTruncate / x_kind）。
// 现在的 builder 出不来这种 spec，但库里有。
const STEP3_BAR: ChartInput = (() => {
  const o = JSON.parse(JSON.stringify(fx("bar").option)) as O;
  o.grid.outerBoundsContain = "axisLabel";
  delete o.grid.outerBoundsClampWidth;
  delete o.grid.outerBoundsClampHeight;
  delete o.xAxis.nameLocation;
  delete o.xAxis.nameGap;
  delete o.xAxis.nameTruncate;
  delete o.yAxis.nameTextStyle;
  delete o.yAxis.nameTruncate;
  o.color = ["#1F6FB2", "#159A8C", "#E2843B"];
  return { kind: "bar", option: o };
})();
describe("历史 spec 经 normalize 归一到当前契约", () => {
  test("第三步形状：几何键等于当前 builder 产出，顶层 color 被删", () => {
    expect(prepare(STEP3_BAR)).toEqual(prepare(fx("bar")));
  });
  test("几何值来自 schema.geometry，不是前端字面量", () => {
    const o = normalize(JSON.parse(JSON.stringify(STEP3_BAR.option)) as Option, {} as Ctx) as O;
    for (const [part, reg] of Object.entries(schema.geometry)) for (const [k, v] of Object.entries(reg)) expect(o[part][k]).toEqual(v);
  });
  test("饼图没有 grid / 轴，normalize 不给它造", () => {
    const o = normalize(JSON.parse(JSON.stringify(fx("pie").option)) as Option, {} as Ctx);
    expect(Object.keys(o).sort()).toEqual(Object.keys(fx("pie").option).sort());
  });
});

// ---- 偏好按图型存（S 10-19，D）--------------------------------------------------------------------------------
describe("开关偏好：localStorage 的 datachat.chartUi:<kind>", () => {
  afterEach(() => { localStorage.clear(); resetPrefsForTest(); vi.restoreAllMocks(); });
  test("按图型读写，键最多 5 个", () => {
    setPrefs("pie", { ...DEFAULT_SWITCHES, label: true });
    setPrefs("bar", { ...DEFAULT_SWITCHES, sort: "desc" });
    expect(JSON.parse(localStorage.getItem(`${PREFS_PREFIX}pie`)!).label).toBe(true);
    resetPrefsForTest();
    expect(getPrefs("pie").label).toBe(true);
    expect(getPrefs("bar").sort).toBe("desc");
    expect(getPrefs("line")).toEqual(DEFAULT_STORED); // P2-18：没碰过的 label 是 undefined（套设计默认），不是 false
    expect(Object.keys(localStorage).every((k) => KINDS.some((kind) => k === PREFS_PREFIX + kind))).toBe(true);
  });
  test("不合法：不认识的字段丢弃、非法值回退默认、坏 JSON 整体回退", () => {
    expect(parseSwitches({ label: true, sort: "random", zoom: "yes", evil: 1 })).toEqual({ ...DEFAULT_SWITCHES, label: true });
    expect(parseSwitches([1, 2])).toEqual(DEFAULT_STORED);
    expect(parseSwitches({ label: "yes" }).label).toBeUndefined(); // 非法 label → 没碰过
    expect(parseSwitches({ label: false }).label).toBe(false); // 用户主动关要保住
    localStorage.setItem(`${PREFS_PREFIX}bar`, "{not json");
    expect(getPrefs("bar")).toEqual(DEFAULT_STORED);
  });
  test("localStorage 抛错（隐私模式 / 配额满）：读回退默认，写只在内存生效，不抛", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("denied"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("quota"); });
    expect(getPrefs("area")).toEqual(DEFAULT_STORED);
    expect(() => setPrefs("area", { ...DEFAULT_SWITCHES, smooth: true })).not.toThrow();
    expect(getPrefs("area").smooth).toBe(true);
  });
});

describe("P2-18 设计默认：resolveSwitches / designLabel", () => {
  test("柱线面积默认开，饼图散点默认关；类目 > 30 降为关；用户显式值优先", () => {
    expect(KINDS.map((k) => [k, resolveSwitches(DEFAULT_STORED, k, 5).label])).toEqual(KINDS.map((k) => [k, DESIGN_LABEL[k]]));
    expect(designLabel("bar", 30)).toEqual({ on: true, tooMany: false });
    expect(designLabel("bar", 31)).toEqual({ on: false, tooMany: true });
    expect(designLabel("pie", 31)).toEqual({ on: false, tooMany: false });
    expect(resolveSwitches({ ...DEFAULT_STORED, label: true }, "bar", 5000).label).toBe(true);
    expect(resolveSwitches({ ...DEFAULT_STORED, label: false }, "bar", 5).label).toBe(false);
  });
  test("全 false 仍等于后端原样：resolve 出来的显式全关走 DEFAULT_UI 恒等（上面的夹具断言不变）", () => {
    expect(resolveSwitches({ ...DEFAULT_STORED, label: false }, "bar", 5)).toEqual(DEFAULT_SWITCHES);
  });
});

test("DEFAULT_UI 下 prepare 不改变任何夹具的开关相关键（开关全关恒等）", () => {
  for (const { spec } of FIX) expect(canon(prepare(spec, DEFAULT_UI))).toBe(canon(prepare(spec)));
});

// ---- 交互态（F3 第六步）：view 只有数值，按 index 写回 legend.selected ------------------------------------------------
describe("交互态 view → applyView", () => {
  const multi = fx("inject-bar"); // 两个系列，系列名是注入载荷（用户串）
  test("缩放窗口写进开关已写出的 dataZoom；zoom 开关关着、或图型不兼容时忽略", () => {
    const on = prepare(multi, ui({ zoom: true }, null, V1)) as O;
    expect(on.dataZoom.map((d: O) => [d.start, d.end])).toEqual([[10, 60]]);
    expect(canon(prepare(multi, ui({}, null, V1)) as O)).toBe(canon(prepare(multi, ui({}, null, { zoom: null, hidden: [0] })) as O));
    expect((prepare(fx("pie"), ui({ zoom: true }, null, V1)) as O).dataZoom).toBeUndefined();
  });
  test("hidden 按 index 生成 legend.selected，键等于 series[i].name（取自 option，不来自 view）", () => {
    const o = prepare(multi, ui({}, null, { zoom: null, hidden: [1] })) as O;
    expect(o.legend.selected).toEqual({ [o.series[1].name]: false });
  });
  test("饼图的图例项是扇区：index 对应 series[0].data[i].name", () => {
    const o = prepare(fx("pie"), ui({}, null, { zoom: null, hidden: [0, 2] })) as O;
    expect(o.legend.selected).toEqual({ [o.series[0].data[0].name]: false, [o.series[0].data[2].name]: false });
  });
  test("越界 / 负数 / 非整数 index、图例没显示时都不写", () => {
    const off = prepare(multi) as O;
    for (const hidden of [[999], [-1], [0.5], [Number.NaN]]) {
      expect((prepare(multi, ui({}, null, { zoom: null, hidden })) as O).legend.selected).toBeUndefined();
    }
    expect(off.legend.selected).toBeUndefined();
    // 单系列 bar 的图例是 show: false：没有能点的图例，hidden 不写
    expect((prepare(fx("bar"), ui({}, null, { zoom: null, hidden: [0] })) as O).legend.selected).toBeUndefined();
  });
  test("asZoom：NaN、越界、start > end、非数值都是 null；全量 (0, 100) 归成 null", () => {
    expect(asZoom(10, 60)).toEqual({ start: 10, end: 60 });
    for (const [a, b] of [[Number.NaN, 50], [-1, 50], [10, 101], [60, 10], ["10", 60], [undefined, 60], [0, 100], [Infinity, 100]]) {
      expect([a, b, asZoom(a, b)]).toEqual([a, b, null]);
    }
  });
  test("applyViewTo 再兜一道：手塞不合法的 view 也写不出越界值", () => {
    const o = prepare(multi, ui({ zoom: true })) as O;
    applyViewTo(o as Option, { zoom: { start: -5, end: 200 }, hidden: [] });
    expect(o.dataZoom[0].start).toBeUndefined();
  });
  test("hiddenFromSelected：名字只在这里换成 index，结果只有数值；未知名字、非 false 的值忽略", () => {
    const o = prepare(multi) as O;
    const [a, b] = [o.series[0].name, o.series[1].name];
    expect(hiddenFromSelected(o as Option, { [a]: true, [b]: false, 不存在: false })).toEqual([1]);
    expect(hiddenFromSelected(o as Option, { [b]: 0 })).toEqual([]);
    expect(hiddenFromSelected(o as Option, null)).toEqual([]);
    expect(hiddenFromSelected(o as Option, { ["__proto__"]: false })).toEqual([]);
  });
  test("viewFromRendered：从 getOption() 的形状回读（组件是数组）；没有 dataZoom → zoom null，全量也归 null；图例不显示 → hidden 空", () => {
    const o = prepare(multi, ui({ zoom: true })) as O;
    const [a, b] = [o.series[0].name, o.series[1].name];
    const rendered = { dataZoom: [{ start: 20, end: 70 }], legend: [{ selected: { [a]: true, [b]: false } }] };
    expect(viewFromRendered(rendered as unknown as Option, o as Option)).toEqual({ zoom: { start: 20, end: 70 }, hidden: [1] });
    expect(viewFromRendered({ legend: [{ selected: { [a]: true, [b]: true } }] } as unknown as Option, o as Option)).toEqual({ zoom: null, hidden: [] });
    expect(viewFromRendered({ dataZoom: [{ start: 0, end: 100 }] } as unknown as Option, o as Option).zoom).toBeNull();
    const noLegend = { ...o, legend: { ...o.legend, show: false } };
    expect(viewFromRendered(rendered as unknown as Option, noLegend as Option).hidden).toEqual([]);
    expect(viewFromRendered({} as Option, o as Option)).toEqual({ zoom: null, hidden: [] });
  });
  test("view 里只有数值（类型之外再用值钉一次）", () => {
    const strs = JSON.stringify([V1, V2]).match(/:"/g);
    expect(strs).toBeNull();
  });
});
