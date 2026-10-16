// F3-ECharts 第一步的 vitest 验收：组件注册表 ↔ 后端白名单双向比对；每个夹具用 SSR SVG 渲染无 warn/error；prepare。
import { init, use as installEcharts } from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import fixtures from "../generated/chart_fixtures.json";
import schema from "../generated/chart_schema.json";
import { BANNED_KEYS, prepare } from "./prepare";
import { ENUMS, productExtensions, TOP_LEVEL } from "./register";

type Spec = { v: number; kind: string; truncated: boolean; option: Record<string, unknown> };
const FIX = fixtures.fixtures as { id: string; spec: Spec }[];

installEcharts([...productExtensions(), SVGRenderer]); // 测试里只把 SVG 当断言工具；产品只注册 canvas

// 范围：只比对顶层键和枚举取值，不比对嵌套键。比如 grid.containLabel 需要 LegacyGridContainLabel，这类依赖不在这里，
// 靠下面的夹具渲染测试兜底。
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
    const log = vi.spyOn(console, "log"); // echarts 的部分提示走 console.log（如 containLabel 缺 LegacyGridContainLabel）
    const c = init(null, null, { renderer: "svg", ssr: true, width: 640, height: 400 });
    try {
      c.setOption(prepare(spec.option), { notMerge: true });
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

describe("prepare v0", () => {
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
      const out = prepare(spec.option);
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
    const out = prepare(evil);
    check(out);
    expect(JSON.stringify(out)).not.toMatch(/"(formatter|extraCssText|graphic|dataset|rich|link)"|onerror|javascript/);
    expect(evil.tooltip.formatter).toBeDefined(); // 输入没被改
  });

  test("tooltip 缺失或是数组时也强制 richText", () => {
    expect(prepare({ series: [] }).tooltip).toEqual({ renderMode: "richText" });
    expect(prepare({ tooltip: [{ trigger: "item", renderMode: "html" }, 3] }).tooltip).toEqual([
      { trigger: "item", renderMode: "richText" },
      { renderMode: "richText" },
    ]);
  });
});

