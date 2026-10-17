// 对照：故意少注册组件，证明 charts.test.ts 的"console 无 warn/error/[ECharts] log"断言真的抓得到缺组件。
// vitest 每个测试文件独立模块图，这里的 use() 不影响主测试。
import { LegacyGridContainLabel } from "echarts/features";
import { init, use as installEcharts } from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import fixtures from "../generated/chart_fixtures.json";
import { prepare } from "./prepare";
import { ENUMS, productExtensions } from "./register";

const bar = ENUMS["series.type"].bar[0];
installEcharts([...productExtensions().filter((e) => e !== bar && e !== LegacyGridContainLabel), SVGRenderer]);

function render(id: string) {
  const spec = fixtures.fixtures.find((f) => f.id === id)!.spec;
  const spies = (["warn", "error", "log"] as const).map((m) => vi.spyOn(console, m).mockImplementation(() => {}));
  const c = init(null, null, { renderer: "svg", ssr: true, width: 640, height: 400 });
  let thrown = false;
  try {
    c.setOption(prepare(spec.option as Record<string, unknown>), { notMerge: true });
    c.renderToSVGString();
  } catch {
    thrown = true;
  } finally {
    c.dispose();
  }
  const msgs = spies.flatMap((s) => s.mock.calls.map((a) => String(a[0])));
  spies.forEach((s) => s.mockRestore());
  return { thrown, msgs };
}

// echarts 的 log 带 onlyOnce（同一句只打一次），所以 containLabel 这条放在最前面。
test("没注册 LegacyGridContainLabel：containLabel 的提示走 console.log，被 [ECharts] 前缀过滤抓到", () => {
  const { msgs } = render("line");
  expect(msgs.some((m) => m.startsWith("[ECharts]") && m.includes("LegacyGridContainLabel"))).toBe(true);
});

test("没注册 BarChart：渲染柱图会报错或报警", () => {
  const { thrown, msgs } = render("bar");
  expect(thrown || msgs.length > 0).toBe(true);
});
