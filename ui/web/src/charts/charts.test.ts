// F3-ECharts 第一步的 vitest 验收：组件注册表 ↔ 后端白名单双向比对；每个夹具用 SSR SVG 渲染无 warn/error；prepare。
import { init, use as installEcharts } from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import fixtures from "../generated/chart_fixtures.json";
import schema from "../generated/chart_schema.json";
import { applyLayer1, applySwitches, BANNED_KEYS, type Json, type Option, prepare, runPipeline, type Step } from "./prepare";
import { ENUMS, productExtensions, TOP_LEVEL } from "./register";

type Spec = { v: number; kind: string; truncated: boolean; option: Record<string, unknown> };
const FIX = fixtures.fixtures as { id: string; spec: Spec }[];

installEcharts([...productExtensions(), SVGRenderer]); // 测试里只把 SVG 当断言工具；产品只注册 canvas

// 范围：只比对顶层键和枚举取值，不比对嵌套键。嵌套字段要求前端 feature 的情况（原来唯一的一条 grid.containLabel →
// LegacyGridContainLabel）第三步已经消掉；如果再出现，靠下面夹具渲染的"零 [ECharts] log"兜底（register.control.test.ts 证明它抓得到）。
describe("注册表 ↔ 后端白名单（双向，仅顶层键 + 枚举值，不含嵌套键）", () => {
  const sorted = (a: Iterable<string>) => [...a].sort();
  test("顶层键：少一项红，多一项也红", () => {
    expect(sorted(Object.keys(TOP_LEVEL))).toEqual(sorted(schema.top_level_keys));
  });
  test("每个枚举：键集合与取值集合都完全一致", () => {
    expect(sorted(Object.keys(ENUMS))).toEqual(sorted(Object.keys(schema.enums)));
    for (const [k, vals] of Object.entries(schema.enums)) expect([k, sorted(Object.keys(ENUMS[k]))]).toEqual([k, sorted(vals)]);
  });
  test("每个 kind 对应的 series.type 都在注册表里", () => {
    expect(sorted(Object.keys(schema.kind_series_type))).toEqual(sorted(schema.kinds));
    for (const t of Object.values(schema.kind_series_type)) expect(ENUMS["series.type"][t]?.length).toBeGreaterThan(0);
  });
  test("夹具覆盖每个 kind", () => {
    expect(sorted(new Set(FIX.map((f) => f.spec.kind)))).toEqual(sorted(schema.kinds));
  });
});

describe("每个夹具 × 产品注册表：SSR SVG 渲染", () => {
  test.each(FIX.map((f) => [f.id, f.spec] as const))("%s", (_id, spec) => {
    const warn = vi.spyOn(console, "warn");
    const error = vi.spyOn(console, "error");
    // echarts 的部分提示走 console.log（如缺 feature）。这道守卫必须留在 vitest：生产构建里 __DEV__ 分支被去掉，e2e 里它是空断言
    const log = vi.spyOn(console, "log");
    const c = init(null, null, { renderer: "svg", ssr: true, width: 640, height: 400 });
    try {
      c.setOption(prepare(spec.option, {}), { notMerge: true });
      const svg = c.renderToSVGString();
      const series = (c as unknown as { getModel(): { getSeries(): unknown[] } }).getModel().getSeries();
      expect(series.length).toBe((spec.option.series as unknown[]).length);
      expect(svg).toMatch(/<path|<circle|<rect/);
      expect(warn).not.toHaveBeenCalled();
      expect(error).not.toHaveBeenCalled();
      expect(log.mock.calls.filter((a) => String(a[0]).startsWith("[ECharts]"))).toEqual([]);
    } finally {
      c.dispose();
      warn.mockRestore();
      error.mockRestore();
      log.mockRestore();
    }
  });
});

// ---- F3 第三步：outerBounds 替换 containLabel 后的布局回归（SSR 与 canvas 共用布局引擎；注意 jsdom 没有 canvas，
// SSR 的文字宽度是 zrender 的估算值，不是真实字体，所以这里断言的是布局逻辑，不是像素）
type Rect = { x: number; y: number; width: number; height: number };
type Zr = { storage: { getDisplayList(update: boolean): { parent?: { anid?: string }; style?: { text?: unknown }; getBoundingRect(): Rect & { clone(): Rect & { applyTransform(m: unknown): void } }; getComputedTransform(): unknown }[] } };
function renderSSR(option: Record<string, unknown>) {
  const c = init(null, null, { renderer: "svg", ssr: true, width: 640, height: 400 });
  c.setOption(prepare(option, {}), { notMerge: true });
  const texts = (c as unknown as { getZr(): Zr }).getZr().storage.getDisplayList(true).flatMap((el) => {
    if (typeof el.style?.text !== "string") return [];
    const r = el.getBoundingRect().clone();
    r.applyTransform(el.getComputedTransform());
    // anid 是 echarts AxisBuilder 给文本元素（显示列表里是它的 tspan 子元素的 parent）的标识：轴标签 label_<tickValue>，
    // 轴名 name。按结构判，不按文本猜（注入夹具里 P4 既是轴名又是类目）
    return [{ text: el.style.text, anid: el.parent?.anid ?? "", x: r.x, y: r.y, width: r.width, height: r.height }];
  });
  type L = { x: number; width: number };
  const m = (c as unknown as { getModel(): { getSeriesByIndex(i: number): { getData(): { getItemLayout(i: number): L } } } }).getModel();
  const bar0 = m.getSeriesByIndex(0).getData().getItemLayout(0);
  c.dispose();
  return { texts, bar0 };
}
const CARTESIAN = FIX.filter((f) => ["bar", "line", "area", "scatter"].includes(f.spec.kind));

describe("outerBounds（F3 第三步）", () => {
  test.each(CARTESIAN.map((f) => [f.id, f.spec] as const))("%s：每个轴标签都在画布内", (id, spec) => {
    const cats = new Set(((spec.option.xAxis as { data?: string[] }).data ?? []) as string[]);
    const { texts } = renderSSR(spec.option);
    const labels = texts.filter((t) => t.anid.startsWith("label_")); // 轴名（anid=name）不算：是否纳入 outerBounds 在第四步定
    expect(labels.length).toBeGreaterThan(0);
    const out = labels.filter((t) => t.x < -0.5 || t.y < -0.5 || t.x + t.width > 640.5 || t.y + t.height > 400.5);
    expect([id, out]).toEqual([id, []]);
    // 已知现象（不是 clamp 导致的溢出）：3 个 120 字类目在 640 宽里 echarts 一个类目标签都不画，其他夹具至少画一个
    const drawnCats = labels.filter((t) => cats.has(t.text)).length;
    if (id === "long-labels-bar") expect(drawnCats).toBe(0);
    else if (cats.size) expect(drawnCats).toBeGreaterThan(0);
  });

  // 替换前的值：2213aac（containLabel: true + LegacyGridContainLabel）同一夹具、同样 640×400 SSR 取出的第一根柱子
  const BEFORE: Record<string, { x: number; width: number }> = {
    bar: { x: 51.91488, width: 80.10624 },
    "bar-missing": { x: 56.4136, width: 100.1328 },
  };
  test.each(Object.entries(BEFORE))("%s：第一根柱子 width 相对变化 < 5%，x 平移 < 画布宽 5%", (id, before) => {
    const { bar0 } = renderSSR(FIX.find((f) => f.id === id)!.spec.option);
    console.info(`[outerBounds] ${id} 第一根柱子 x ${before.x.toFixed(2)} → ${bar0.x.toFixed(2)}，width ${before.width.toFixed(2)} → ${bar0.width.toFixed(2)}`);
    expect(Math.abs(bar0.width - before.width) / before.width).toBeLessThan(0.05);
    expect(Math.abs(bar0.x - before.x) / 640).toBeLessThan(0.05);
  });
});

describe("prepare 管线骨架（F3 第三步）", () => {
  const same = (a: unknown, b: unknown) => expect(JSON.stringify(a)).toBe(JSON.stringify(b));
  test("两个恒等步骤：每个夹具输出与输入逐字节相同", () => {
    for (const { spec } of FIX) {
      const o = JSON.parse(JSON.stringify(spec.option)) as Option;
      same(applyLayer1(o, {}), spec.option);
      same(applySwitches(o, {}), spec.option);
    }
  });
  test("prepare 整体输出与 v0（深拷贝 → 删被禁键 → 强制 richText）逐字节相同", () => {
    const v0 = (option: Record<string, unknown>) => {
      const strip = (n: unknown): unknown =>
        Array.isArray(n) ? n.map(strip) : n && typeof n === "object" ? Object.fromEntries(Object.entries(n).filter(([k]) => !BANNED_KEYS.has(k)).map(([k, v]) => [k, strip(v)])) : n;
      const out = strip(JSON.parse(JSON.stringify(option))) as Record<string, unknown>;
      out.tooltip = { ...(out.tooltip as object), renderMode: "richText" };
      return out;
    };
    for (const { spec } of FIX) same(prepare(spec.option, {}), v0(spec.option));
  });
  test("清理在最后：替身步骤塞进的被禁键和 renderMode=html，最终产物里都没有", () => {
    const evil: Step = (o) => ({ ...o, graphic: [{ type: "text" }], tooltip: { ...(o.tooltip as object), formatter: "{a}", renderMode: "html" } });
    for (const steps of [[evil, applySwitches], [applyLayer1, evil]]) {
      const out = runPipeline(FIX[0].spec.option, {}, steps);
      expect(out.graphic).toBeUndefined();
      expect(out.tooltip).toEqual({ trigger: "axis", renderMode: "richText" });
    }
  });
  test("不修改输入（替身步骤原地改了也不影响调用方）", () => {
    const before = JSON.stringify(FIX[0].spec.option);
    const mutating: Step = (o) => {
      (o.series as Json[]).length = 0;
      return o;
    };
    runPipeline(FIX[0].spec.option, {}, [mutating]);
    expect(JSON.stringify(FIX[0].spec.option)).toBe(before);
  });
  test("耗时记录：5000 点夹具跑 20 次取中位数（只记录，不设阈值）", () => {
    const opt = FIX.find((f) => f.id === "bar-5000")!.spec.option;
    const ts: number[] = [];
    for (let i = 0; i < 20; i++) {
      const t0 = performance.now();
      prepare(opt, {});
      ts.push(performance.now() - t0);
    }
    ts.sort((a, b) => a - b);
    console.info(`[prepare] bar-5000 ×20 中位数 ${((ts[9] + ts[10]) / 2).toFixed(3)} ms（最小 ${ts[0].toFixed(3)}，最大 ${ts[19].toFixed(3)}）`);
    expect(ts).toHaveLength(20);
  });
});

describe("prepare 清理（v0 起的断言，保持不变）", () => {
  const walk = (node: unknown, path: string[], visit: (k: string, v: unknown, path: string[]) => void) => {
    if (Array.isArray(node)) node.forEach((x, i) => walk(x, [...path, String(i)], visit));
    else if (node && typeof node === "object")
      for (const [k, v] of Object.entries(node)) {
        visit(k, v, path);
        walk(v, [...path, k], visit);
      }
  };
  const check = (out: unknown) => {
    walk(out, [], (k, v, path) => {
      if (k === "renderMode") expect([path.join("."), v]).toEqual(["tooltip", "richText"]);
      else expect(BANNED_KEYS.has(k)).toBe(false);
    });
  };

  test("每个夹具：清理后任何层级不含被禁键，renderMode 只在 tooltip 下且为 richText；不改输入", () => {
    for (const { spec } of FIX) {
      const before = JSON.stringify(spec.option);
      const out = prepare(spec.option, {});
      check(out);
      expect((out.tooltip as Record<string, unknown>).renderMode).toBe("richText");
      expect(JSON.stringify(spec.option)).toBe(before);
    }
  });

  test("对照：人为塞进各层级的被禁键确实被删掉", () => {
    const evil = JSON.parse(JSON.stringify(FIX[0].spec.option));
    evil.tooltip.formatter = "<img src=x onerror=alert(1)>";
    evil.tooltip.extraCssText = "x";
    evil.renderMode = "html";
    evil.series[0].label = { rich: { a: {} }, formatter: "{a}" };
    evil.series[0].data = [{ value: 1, link: "javascript:alert(1)" }];
    evil.xAxis.axisLabel = { formatter: "x" };
    evil.graphic = [{ type: "text" }];
    evil.dataset = { source: [] };
    const out = prepare(evil, {});
    check(out);
    expect(JSON.stringify(out)).not.toMatch(/"(formatter|extraCssText|graphic|dataset|rich|link)"|onerror|javascript/);
    expect(evil.tooltip.formatter).toBeDefined(); // 输入没被改
  });

  test("tooltip 缺失或是数组时也强制 richText", () => {
    expect(prepare({ series: [] }, {}).tooltip).toEqual({ renderMode: "richText" });
    expect(prepare({ tooltip: [{ trigger: "item", renderMode: "html" }, 3] }, {}).tooltip).toEqual([
      { trigger: "item", renderMode: "richText" },
      { renderMode: "richText" },
    ]);
  });
});

