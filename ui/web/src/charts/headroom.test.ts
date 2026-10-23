// V2b A 组（phase5「阶段 5 收尾」A1–A3 的验收）：y 轴留顶（applyHeadroom）的判据表、触发条件、机制测试；
// x 轴名间距与左右固定留白的 SSR 布局断言。SSR 的文字宽度是 zrender 估算值，断言的是布局逻辑，像素以 CI 截图为准。
import { init, use as installEcharts } from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import fixtures from "../generated/chart_fixtures.json";
import kindFixtures from "../generated/kind_fixtures.json";
import { dataMax, HEADROOM_KEYS, niceMax } from "./headroom";
import { EMPTY_EDIT, type Edit } from "./layer1";
import { type ChartInput, DEFAULT_UI, type Json, type Option, prepare, type UiState } from "./prepare";
import { productExtensions } from "./register";
import { DEFAULT_SWITCHES, type Kind, type Switches } from "./switches";

installEcharts([...productExtensions(), SVGRenderer]);
type F = { id: string; spec: ChartInput };
const FX = (fixtures as unknown as { fixtures: F[] }).fixtures;
const GROUPS = kindFixtures.groups as unknown as Record<string, Partial<Record<Kind, ChartInput>>>;
const fx = (id: string) => FX.find((f) => f.id === id)!.spec;
type O = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const ui = (sw: Partial<Switches> = {}, extra: Partial<UiState> = {}): UiState => ({ ...DEFAULT_UI, sw: { ...DEFAULT_SWITCHES, ...sw }, ...extra });
const LABEL = { label: true } as const;

describe("niceMax 判据（写死的表）", () => {
  test.each([
    [8, false, 10, 2], [97, false, 120, 20], [412, false, 500, 100], [11.4, false, 12.5, 2.5], [0.3, false, 0.4, 0.1],
    [8, true, 10, 5],
  ] as const)("%s（紧凑 %s）→ max %s，interval %s", (d, compact, max, interval) => {
    expect(niceMax(d, compact)).toEqual({ max, interval });
  });
  test("2.5 不是死候选：11.4 → 12.5（刻度 0 / 2.5 / … / 12.5），12 < t ≤ 12.5 才选中它", () => {
    const r = niceMax(11.4)!;
    expect(Array.from({ length: r.max / r.interval + 1 }, (_, i) => i * r.interval)).toEqual([0, 2.5, 5, 7.5, 10, 12.5]);
    expect(niceMax(13)).toEqual({ max: 15, interval: 2.5 }); // (12.5, 15] 段有没有 2.5 都是 15
  });
  test("整除不因浮点多出一格；小数步长按位数取整", () => {
    expect(niceMax(12 / 1.08)).toEqual({ max: 12, interval: 2 });
    expect(niceMax(0.03)).toEqual({ max: 0.04, interval: 0.01 });
    expect(niceMax(0.0114)).toEqual({ max: 0.0125, interval: 0.0025 });
  });
  test("dmax ≤ 0、非有限数不写", () => {
    for (const d of [0, -3, NaN, Infinity, -Infinity]) expect(niceMax(d)).toBeNull();
  });
});

describe("applyHeadroom 触发条件", () => {
  test("夹具 bar（最大 8）开标签写 max 10 / interval 2；关标签不写", () => {
    expect(dataMax(prepare(fx("bar")) as Option, false)).toBe(8);
    const on = prepare(fx("bar"), ui(LABEL)) as O;
    expect([on.yAxis.max, on.yAxis.interval]).toEqual([10, 2]);
    const off = prepare(fx("bar"), ui()) as O;
    expect([off.yAxis.max, off.yAxis.interval]).toEqual([undefined, undefined]);
  });
  test("紧凑（画布 < 300 高）：8 → 10，interval 5", () => {
    const o = prepare(fx("bar"), ui(LABEL, { compact: true })) as O;
    expect([o.yAxis.max, o.yAxis.interval]).toEqual([10, 5]);
  });
  test("用户填了上限或下限：整条不写，以用户为准", () => {
    const e = (p: Partial<Edit>): Edit => ({ ...EMPTY_EDIT, ...p });
    const lo = prepare(fx("bar"), ui(LABEL, { edit: e({ yMin: 1 }) })) as O;
    expect([lo.yAxis.min, lo.yAxis.max, lo.yAxis.interval]).toEqual([1, undefined, undefined]);
    const hi = prepare(fx("bar"), ui(LABEL, { edit: e({ yMax: 9 }) })) as O;
    expect([hi.yAxis.max, hi.yAxis.interval]).toEqual([9, undefined]);
  });
  test("堆叠时按每个类目的堆叠和取最大值", () => {
    const spec = GROUPS.wide.bar!;
    const plain = prepare(spec, ui(LABEL)) as O;
    const stacked = prepare(spec, ui({ label: true, stack: true })) as O;
    const sums = (stacked.xAxis.data as Json[]).map((_, i) => (stacked.series as O[]).reduce((s, x) => s + Math.max(0, Number(x.data[i] ?? 0)), 0));
    expect(stacked.yAxis.max).toBe(niceMax(Math.max(...sums))!.max);
    expect(stacked.yAxis.max).toBeGreaterThan(plain.yAxis.max);
  });
  test("全负不写；饼图、散点不写", () => {
    const neg: ChartInput = JSON.parse(JSON.stringify(fx("bar")));
    const s0 = (neg.option.series as O[])[0];
    s0.data = (s0.data as number[]).map((v) => -Math.abs(v) - 1);
    const o = prepare(neg, ui(LABEL)) as O;
    expect([o.yAxis.max, o.yAxis.interval]).toEqual([undefined, undefined]);
    for (const id of ["pie", "scatter"]) {
      const p = prepare(fx(id), ui(LABEL)) as O;
      expect(p.yAxis?.max).toBeUndefined();
    }
  });
  test("机制：全部夹具开标签（含堆叠、紧凑），写出的键 ⊆ HEADROOM_KEYS 且两个都写到过；关标签与默认产物逐字节相同", () => {
    const hits = new Set<string>();
    const all: ChartInput[] = [...FX.map((f) => f.spec), ...Object.values(GROUPS).flatMap((m) => Object.values(m) as ChartInput[])];
    for (const spec of all) {
      for (const extra of [{}, { compact: true }]) {
        const base = prepare(spec, ui({}, extra)) as O;
        const on = prepare(spec, ui({ label: true, stack: true }, extra)) as O;
        const off = prepare(spec, ui({ stack: true }, extra)) as O;
        // 留顶只动 yAxis 的两个键：把它们从 on 里摘掉，剩下的应当和"只开标签"的开关产物一致（开关本身由 switches.test 钉）
        const y = on.yAxis as O | undefined;
        for (const k of ["max", "interval"]) if (y && y[k] !== undefined && off.yAxis?.[k] === undefined) { hits.add(`yAxis.${k}`); delete y[k]; }
        const offY = off.yAxis as O | undefined;
        expect(JSON.stringify(y ?? null)).toBe(JSON.stringify(offY ?? null));
        expect(JSON.stringify(base.yAxis ?? null)).toBe(JSON.stringify(prepare(spec, { ...DEFAULT_UI, ...extra }).yAxis ?? null));
      }
    }
    expect([...hits].sort()).toEqual([...HEADROOM_KEYS].sort());
  });
});

// ---- SSR 布局 -----------------------------------------------------------------------------------------------
type Rect = { x: number; y: number; width: number; height: number };
type Zr = { storage: { getDisplayList(update: boolean): { parent?: { anid?: string }; style?: { text?: unknown }; getBoundingRect(): Rect & { clone(): Rect & { applyTransform(m: unknown): void } }; getComputedTransform(): unknown }[] } };
function ssr(option: Record<string, unknown>, width = 640, height = 400) {
  const c = init(null, null, { renderer: "svg", ssr: true, width, height });
  c.setOption(option, { notMerge: true });
  const texts = (c as unknown as { getZr(): Zr }).getZr().storage.getDisplayList(true).flatMap((el) => {
    if (typeof el.style?.text !== "string") return [];
    const r = el.getBoundingRect().clone();
    r.applyTransform(el.getComputedTransform());
    return [{ text: el.style.text, anid: el.parent?.anid ?? "", x: r.x, y: r.y, width: r.width, height: r.height }];
  });
  const g = (c as unknown as { getModel(): { getComponent(t: string): { coordinateSystem?: { getRect(): Rect } } | undefined } }).getModel().getComponent("grid");
  const plot = g!.coordinateSystem!.getRect();
  c.dispose();
  return { texts, plot };
}

describe("SSR：y 轴刻度、x 轴名间距、左右留白", () => {
  test("bar（最大 8）开标签：y 轴刻度 0 / 2 / … / 10；关标签不写 max", () => {
    const { texts, plot } = ssr(prepare(fx("bar"), ui(LABEL)));
    const yl = texts.filter((t) => t.anid.startsWith("label_") && t.x + t.width <= plot.x + 0.5).map((t) => t.text);
    expect(yl).toEqual(["0", "2", "4", "6", "8", "10"]);
  });
  test.each([["m", 12], ["l", 8]] as const)("x 轴刻度文字下沿到轴名上沿：字号 %s 时 ≥ %spx（SSR 估算）", (font, min) => {
    for (const w of [640, 880, 1174]) {
      const { texts, plot } = ssr(prepare(fx("bar"), ui(LABEL, { edit: { ...EMPTY_EDIT, font } })), w, 360);
      const below = texts.filter((t) => t.y >= plot.y + plot.height - 0.5);
      const labels = below.filter((t) => t.anid.startsWith("label_"));
      const name = below.find((t) => t.anid === "name");
      expect(labels.length).toBeGreaterThan(0);
      const gap = name!.y - Math.max(...labels.map((t) => t.y + t.height));
      expect([w, font, gap >= min - 0.01]).toEqual([w, font, true]);
    }
  });
  test("grid.left / right 在 640 和 1174 宽下都是 12 / 16（不随宽度变）；右侧到画布边 16px", () => {
    for (const w of [640, 1174]) {
      const o = prepare(fx("bar"), ui(LABEL)) as O;
      expect([o.grid.left, o.grid.right]).toEqual([12, 16]);
      const { plot } = ssr(o, w, 360);
      expect([w, Math.round(w - (plot.x + plot.width))]).toEqual([w, 16]);
    }
  });
});
